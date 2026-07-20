# Plan 2 — Backend compute-cycle (latency) generator ("eventsim")

**Status: implemented and verified.**

## Goal

A standalone discrete-event NoC latency simulator, written in C++ for speed,
that consumes the same `tc.csv` `combine.py` already writes and computes
total compute latency with real link-contention modeling — without the
SystemC/RTL toolchain, `NOC_X`/`NOC_Y` compile-time coupling, or
`DRAMPort` fragility of CoSA's real C++ backend.

## Decisions

1. **Link contention is required.** Neither "Added" (sum all transaction
   durations, assumes full serialization) nor "Max" (take the longest
   single transaction, assumes full parallelism) produces a correct total
   latency — Added over-counts independent transactions, Max under-counts
   conflicting ones. Only tracking real per-link occupancy over time
   (transactions serialize iff they share a physical resource) gives the
   correct number.
2. **Link-occupancy granularity: coarse.** A transaction claims its entire
   route for its full duration (`hops + packets × flits_per_packet`) — not
   a per-flit pipelined model.
3. **Multicast: farthest-only.** Cost/occupancy is computed from the single
   farthest destination: `hops(S, d_farthest) + packets × flits_per_packet`
   — a multicast occupies only the links on the path to its farthest
   destination, equivalent to a unicast to that one node for occupancy
   purposes. Branch links to closer destinations are not marked busy
   (known trade-off, accepted).
4. **DRAM transaction duration = `packets × dram_latency`, no hops term.**
   Matches Plan 1's `dram_cost` formula exactly — DRAM traffic does not use
   NoC mesh links (`transactions/dram.py`'s own docstring: "DRAM ↔ GB
   transfers use the off-chip DRAM bus, not the NoC mesh"), so no route is
   computed or occupied for DRAM-touching transactions; only the actor
   (port) itself is held busy for the duration.
5. **Actor serialization**: each `actor_id` (port) runs at most one
   transaction at a time, regardless of which links (if any) it uses —
   matches the real C++ backend's per-port `SrcDest` queue model. This
   applies uniformly to every op type, including two on-chip sends from the
   same source port with otherwise-disjoint routes (see "Bug caught during
   verification" below).
6. **Output: scalar `total_cycles` + per-op-type breakdown**
   (`unicast_cycles`/`multicast_cycles`/`count_cycles`/`dram_cycles`),
   mirroring CoSA's C++ backend's `tc.summary.json` shape. The breakdown
   fields are *summed per-transaction durations* (total work of that type),
   not portions of the makespan — `total_cycles` is the actual simulated
   finish time (the max over all transactions' finish times).
7. **Implementation: separate compiled module, not Python.** New directory
   `src/snn_cosa/nocsim/eventsim/`, built with a `Makefile`, no SystemC/HLS
   dependency (plain C++17). Reads the same `tc.csv` `combine.py` already
   writes — runs standalone against any conforming CSV, including CoSA's
   own.
8. **Topology parameters passed as CLI args**: `tc.csv` alone carries no
   metadata about mesh size or port roles. `eventsim` takes
   `--X --Y --dram-port --dram-latency` explicitly; `sim.py` supplies them
   from `gen.noc.X/Y/dram_port` and `bitwidths.dram_latency`. `gb_port` is
   not needed by the simulation logic (GB has no special-cased behavior,
   unlike DRAM) and was dropped from the CLI to keep it minimal.

## Bug caught during verification — corrected here for the record

While hand-verifying the simulator against a synthetic 3-transaction
contention example (`TC_A`, `TC_B`, `TC_C`, all sourced from the same GB
port, `TC_C` using links disjoint from `TC_A`/`TC_B`), the actual build
produced `total_cycles = 18`, not the `13` that had been worked out by hand
and already relayed verbally (durations 7/6/5; `TC_A`+`TC_B` share links so
must serialize 0→7→13, `TC_C` was assumed to overlap with `TC_A` since it
uses a different link).

That hand-worked "13" was wrong: `TC_A`, `TC_B`, and `TC_C` all share the
**same source actor** (GB), and decision 5 above (actor serialization,
already agreed before that example was worked out) applies regardless of
link overlap — GB can only run one send at a time, full stop. Correct
trace: `TC_A` 0→7, `TC_B` 7→13 (shares GB *and* links with `TC_A`), `TC_C`
13→18 (shares GB with both, even though its links are disjoint). Total = 18
— identical to "Added" for this particular example, since every
transaction shares the same source port.

Confirmed the implementation is internally consistent by adding a 4th
transaction from a genuinely different source port (`TC_D`: PE2→PE3,
duration 5, disjoint links *and* disjoint actor from A/B/C):
`total_cycles` stayed at 18 (`TC_D` finishes at 5, fully inside the
GB-chain's window) — real parallelism requires differing in *both* actor
and links, not links alone. This is the correct, implemented, and verified
behavior; the earlier "13" example (already sent externally) is superseded
by this one.

## Files added

- `src/snn_cosa/nocsim/eventsim/Makefile` — `g++ -O2 -std=c++17`, no
  external dependencies.
- `src/snn_cosa/nocsim/eventsim/Transaction.h` — `tc.csv` row parser
  (skips `#` comments, parses the 7-field grammar into a `Transaction`
  struct).
- `src/snn_cosa/nocsim/eventsim/NoC.h` — C++ port of `core/noc.py`'s
  `get_xy()`/`_hops_single()`/`manhattan()`, kept structurally identical so
  route computation matches the Python static metrics exactly.
- `src/snn_cosa/nocsim/eventsim/EventSim.h` — the event loop: reverse
  dependency index, `remaining_deps` countdown, `actor_free_time`/
  `link_free_time` maps, ready-queue drain (ascending tc_id tie-break) +
  completion-heap pop cycle, per-op cost buckets, dependency-cycle
  detection.
- `src/snn_cosa/nocsim/eventsim/main.cpp` — CLI arg parsing, JSON stdout
  output, error handling.
- `src/snn_cosa/nocsim/sim.py` — added `run_eventsim()` (subprocess wrapper,
  independent of `run()`/`run_from_json()`'s existing signatures — kept
  Plan 1's already-tested 3-tuple return shape untouched), `--simulate` CLI
  flag, and `main()` wiring (recomputes `X`/`Y`/`dram_port` cheaply from the
  schedule's spatial factors rather than re-running `combine()`).
- `NOC_SIM_IMPL.md` — project-structure listing updated with `eventsim/`.

## Verification

**Synthetic contention test** (`TC_A`/`TC_B`/`TC_C`/`TC_D`, 2×2 mesh):
confirmed `total_cycles = 18` for the 3-transaction same-actor case (see
bug section above) and `total_cycles = 18` (unchanged) after adding a
genuinely-parallel 4th transaction from a different actor — confirms both
link contention and actor serialization are being applied correctly, and
that real overlap requires differing in both.

**Error handling**: verified all four failure paths exit non-zero with a
clear message — unknown `tc_id` in a `dep` list, a genuine dependency cycle
(`unresolved dependency cycle -- only 0 of 2 transactions completed`),
missing required CLI args, and a nonexistent input file.

**Real schedule** (`sim_demo_schedule.json`, X=1 Y=6 mesh, regenerated via
`sim.py`):
```
{"total_cycles":3360,"unicast_cycles":2240,"multicast_cycles":0,"count_cycles":19200,"dram_cycles":1088}
```
- Deterministic: identical output across repeated runs.
- **Cross-checked against Plan 1**: `dram_cycles == 1088` exactly matches
  `dram_cost["weight"] == 1088` computed independently by the Python side
  (both apply the identical `packets × dram_latency` formula) — a genuine
  correctness cross-check between the two independently-implemented tools,
  not just an internal self-consistency check.

**End-to-end Python wiring** (`python -m snn_cosa.nocsim.sim ... --simulate`):
confirmed it prints the same CSV/cost breakdown as before, plus the
eventsim summary, exit code 0. Confirmed the graceful-failure path too:
temporarily removed the compiled binary and reran with `--simulate` — CSV
generation still succeeds, then a clear
`eventsim not available: ... build it first: cd .../eventsim && make`
message on stderr with exit code 2, rather than a crash or silent
mis-report.
