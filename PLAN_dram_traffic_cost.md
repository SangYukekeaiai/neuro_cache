# Plan 1 — DRAM-to-GB traffic cost weighting (CoSA "mechanism 2")

**Status: implemented and verified.**

## Goal

snn_cosa's NoC simulator gave DRAM↔GB traffic **zero** cost in its own
metrics. CoSA's frontend instead applies a fixed `dram_latency` multiplier
to DRAM-level traffic and adds it on top of the NoC-level (GB↔PE) cost. This
change brings snn_cosa's DRAM-to-GB cost computation in line with that.

## Prior state (before this change)

- `core/generator.py::unicast()` only accumulated `unicast_hops` when
  `src == gb_port and dest != dram_port`. Any transaction touching
  `dram_port` (as either src or dest) contributed **nothing** to
  `unicast_hops`/`multicast_hops`.
- `transactions/dram.py` emitted DRAM↔GB unicasts through that same
  `gen.unicast(...)` call, so DRAM traffic was generated but silently
  uncosted.
- CoSA's real frontend (`gen_tc_io.py`) does two separate things:
  - **(a)** A standalone analytical `cost` dict, computed once per `gen_tc()`
    call: `cost['Weights'] = weight_schedule['cost']['Weights'] * dram_latency`,
    and for `Inputs`/`Outputs`/`Outputs_Store`:
    `cost[var] += mem_schedule['cost'][var] * dram_latency`, with
    `dram_latency = 17` hardcoded. The base `cost[var]` there is a raw
    bits-moved figure: `iters[var] * data_size[var] * var_bits[var] * len(addr)`.
  - **(b)** The hop counters (`unicast_hops`/`multicast_hops`) themselves:
    CoSA counts **any** `src == globalbuf_port` send, with **no dest
    exclusion** — so a GB→DRAM store *does* count there. snn_cosa's
    `dest != dram_port` guard excluded it. (DRAM→GB load is excluded from
    the hop counter in both implementations, since `src != gb_port` for a
    load either way.)

## Decisions

1. **Name**: not `dram_hops` — "hop" is a NoC-mesh-distance term and this
   metric never crosses the mesh. Used **`dram_cost`** as the accumulator
   name (parallel structure to `unicast_hops`/`multicast_hops`, distinct
   vocabulary).
2. **`dram_latency` source**: configurable via arch YAML (`DRAM_LATENCY`
   under `arch.bitwidths`), default `17` for CoSA parity.
3. **Direction symmetry**: DRAM→GB and GB→DRAM follow the *same* mechanism
   — both accumulate into `dram_cost` equally. This also resolved the
   hop-counter question: snn_cosa's existing `dest != dram_port` guard on
   `unicast_hops` already excludes *both* directions symmetrically (DRAM→GB
   is excluded because `src != gb_port`; GB→DRAM is excluded by the explicit
   guard) — so no change was needed there. CoSA's own asymmetry (excludes
   DRAM→GB from its hop counter but not GB→DRAM) was not replicated.
4. **Granularity**: per-packet — `num_packets * dram_latency`, matching how
   `unicast_hops`/`multicast_hops` are already expressed.
5. **Per-variable breakdown**: `unicast_hops`, `multicast_hops`, and
   `dram_cost` are all per-variable dicts keyed by `"weight"`/`"psum"`/
   `"vmem"` (`Dict[str, int]`), not flat scalars — snn_cosa previously had
   no per-variable cost tracking at all, unlike CoSA's
   `cost['Weights']`/`cost['Inputs']`/`cost['Outputs']`.
6. **Always-present keys**: all three dicts always contain exactly
   `{"weight", "psum", "vmem"}`, defaulting to 0 — pre-seeded plain dicts,
   not `defaultdict`, so a variable with zero traffic of a given type still
   appears as a key (verified a bare `defaultdict(int)` would instead
   produce sparse dicts, e.g. `multicast_hops == {}` for a schedule with no
   GB-sourced multicast).

## Files changed

- **`src/snn_cosa/parsers/bitwidths.py`** — added `DRAM_LATENCY` parsing
  (default 17), validated as a positive int alongside `BW_WEIGHT`/
  `BW_PSUM`/`BW_VMEM`.
- **`configs/arch/snn_arch.yaml`**, **`configs/arch/snn_arch_large_noc.yaml`**
  — added `DRAM_LATENCY: 17`.
- **`src/snn_cosa/nocsim/core/generator.py`** — the core change:
  - `unicast_hops`/`multicast_hops` changed from flat `int` to
    `Dict[str, int]`, pre-seeded `{"weight": 0, "psum": 0, "vmem": 0}`.
  - New `dram_cost` dict, same shape.
  - `TC_Generator.__init__` takes a `dram_latency: int = 17` param.
  - `unicast()`: existing hop accumulation now keys into
    `self.unicast_hops[var_name]`; new symmetric branch accumulates
    `num_packets * dram_latency` into `self.dram_cost[var_name]` whenever
    `src == dram_port or dest == dram_port`.
  - `multicast()`: dict-ified `self.multicast_hops[var_name]`; no
    `dram_cost` branch (DRAM transactions are unicast-only in this
    simulator — `transactions/dram.py` never calls `multicast()`).
  - `count()`: unaffected.
- **`src/snn_cosa/nocsim/combine.py`** — threads
  `dram_latency=bitwidths.dram_latency` into the `TC_Generator(NoC(X, Y), ...)`
  construction call.
- **`src/snn_cosa/nocsim/sim.py`** — `run()`/`run_from_json()` return type
  changed from `Tuple[int, int]` to
  `Tuple[Dict[str,int], Dict[str,int], Dict[str,int]]`
  (`unicast_hops, multicast_hops, dram_cost`); CLI `main()` printer now
  shows the per-variable breakdown for all three.
- **`NOC_SIM_DESIGN.md`**, **`NOC_SIM_IMPL.md`** — updated to describe the
  per-variable dicts and the `dram_cost` mechanism (previously stated DRAM
  traffic was excluded from all cost tracking and that the hop counters
  were flat totals).

## Smoke test

Regenerated `outputs/sim_demo_tc.csv` from `outputs/sim_demo_schedule.json`
via `python -m snn_cosa.nocsim.sim` and via a direct `combine()` call:

```
transactions  : 672
weight  unicast_hops=1440     multicast_hops=0        dram_cost=1088
  psum  unicast_hops=0        multicast_hops=0        dram_cost=0
  vmem  unicast_hops=0        multicast_hops=0        dram_cost=0
```

Verified:
1. **Sums unchanged**: `sum(unicast_hops.values()) == 1440` and
   `sum(multicast_hops.values()) == 0`, exactly matching the pre-change flat
   scalars — dict-ifying changed shape only, not values.
2. **Keys always present**: all three dicts contain exactly
   `{"weight", "psum", "vmem"}`.
3. **`dram_cost` correct**: `dram_cost["weight"] == 1088`, matching a hand
   computation of `Σ num_packets × dram_latency` for weight's DRAM-touching
   transactions, with `dram_latency` confirmed read from the arch YAML
   (`SNNBitwidths(...).dram_latency == 17`).
4. **TC graph untouched**: transaction count stayed at 672 both before and
   after — this change only added cost bookkeeping, it didn't alter what
   transactions get generated.
5. **No other callers**: `grep` across `src/` and `scripts/` found no code
   outside `nocsim/` consuming `run()`/`run_from_json()`'s return value, so
   the tuple-shape change is contained to this module.
