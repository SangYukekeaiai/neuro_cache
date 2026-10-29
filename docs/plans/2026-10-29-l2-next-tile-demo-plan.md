# L2 next-tile prefetch demo - plan (2026-10-29, for user review; no code yet)

Goal: re-run the 4-layer demo comparison with three arms - **nocsim** (baseline NoC
simulator), **cachesim with the original settings**, and **cachesim with a new
"next-tile" L2 prefetch policy** - and produce a comparison CSV of latency and hit
rate, plus a prompt document that guides the artifact setup on another machine.

Everything below is grounded in the tree at `36aea41`. File:line references were
verified by two read-only audits on 2026-10-29.

---

## 1. Corrections to the request (facts found in the tree)

These change the request's wording, not its intent:

1. **5 samples is already the default.** `scripts/pipeline.py:458` defaults
   `--sample-count` to 5, and the committed traces hold exactly 5 samples
   (`input_trace/loas/*_T4_n5/meta.json`). The only "500" in the repo is the
   gitignored delta-capture naming in `input_trace/README.md:31-40`. Nothing to
   reduce.
2. **ptb and spinalflow are out of scope (user decision 2026-10-29).** They
   cannot run in this tree (the pipeline hardcodes
   `NOCSIM_ARCH = {"loas": ...}` at `scripts/pipeline.py:44-45`, and input
   traces and tracked schedules exist only for loas), and the user ruled the
   demo runs **on loas only**. No multi-bench wiring is done.
3. **nocsim has no hit rate, and cachesim has no per-level latency column.**
   nocsim prints only cycle counts (`src/nocsim/sim.py:393-397`). cachesim has
   `l1_hit_rate`/`l2_hit_rate` plus stall and latency-proxy columns
   (`src/cachesim/native/src/instrument/stats.cpp:256-285`), but no per-level
   latency. So the CSV compares: **latency = total_cycles** across all three
   arms, and **hit rate = cachesim-baseline vs cachesim-enhanced** (two columns,
   nocsim blank by construction). Stall breakdown and `hidden_fraction` come
   along as supporting columns.
4. **The current results.csv drops everything we need.** `KEY_FIELDS`
   (`scripts/pipeline.py:51-52`) keeps only 6 config columns + `total_cycles`;
   hit rates and all `l2_pf_*` / `l2_prefetch_*` columns are discarded at
   :385-392. The new driver keeps them (§5).

## 2. Experiment design

**Fixed, identical across arms and identical to the previous demo** (the "keep
cache and nocsim settings the same for multicore / hardware stays the same"
requirement):

| Setting | Value | Where |
|---|---|---|
| Bench | loas only (user decision) | `scripts/pipeline.py` |
| Layers | V8, V9, R9, R16 (the 4 tracked-schedule layers) | `pipeline.py:47` |
| Samples | 5 (start 0) | `pipeline.py:457-458` |
| Cores | 16, from the schedules (NoC COUTx16, node COUT 4) - both simulators read the same schedule, so multicore stays matched by construction | `configs/schedules/loas/*` |
| nocsim arch | `configs/arch/loas_inst16_node32kb.yaml`, unchanged | `pipeline.py:44-45` |
| Layout | `khkw_split` | `configs/cache/base.json` |
| Line size | **64 B only** (`cin_block=16`, `cout_block=4`, `weight_bytes=1`) | `src/cachesim/grid.py:26` |
| Sizes/latencies | L1 16 KiB/8-way, L2 512 KiB/16-way, `l2_latency=2`, `l2_miss_latency=24`, all other `base.json` keys unchanged | `configs/cache/base.json` |
| Replacement | LRU both levels (the existing default; no `policy` key) | `config.cpp` defaults |

**Swept axes** (the comparison grid, replacing the old 48-point khkw sweep):

| Axis | Values | Count |
|---|---|---|
| L1 prefetch | `none/0` vs `next_burst/1` (user decision) | 2 |
| L2 prefetch | `none` (baseline) vs `next_tile/1` (enhanced) | 2 |
| L2 banks | 1 (pinned, user decision) | 1 |

Grid = 2 × 2 × 1 = **4 configs**; rows = 4 layers × 5 samples × 4 = **80 rows**
(vs 960 before). nocsim runs once per (layer, sample) as today and is joined
onto every cachesim row.

**Sanity cross-check built into the plan:** the two `l2_prefetch=none` configs
are exactly the previous demo's 64 B, banks-1 configs with L1 prefetch none and
next_burst/1 (`khkw_32` and `khkw_33` in grid order: line slowest, then banks,
then prefetch). Their `wcache_total_cycles` must reproduce
`data/demo/loas/results.csv` byte-for-byte on those 40 rows. That is the
acceptance gate proving "original settings unchanged".

## 3. The `next_tile` L2 prefetch policy

**Semantics (revised 2026-10-29 after the T33 stream verification; user
approved).** The plan's original +64-cout stride assumption is wrong on the
real traces. Observed on V8 and R9 streams (core 0, sample 0): each core owns a
contiguous cout chunk for the whole layer and advances its cout anchor by
**+4 cout = +1 cacheline-width cout block** once per run of tiles (every 16
tiles in V8, every 64 in R9), with the anchor constant inside a run. So "the
next tile's cacheline" for a core is **one cout block ahead**. `next_tile`
therefore prefetches, for a request on line at cout block `b`, the line(s) at
cout blocks `b+1..b+d` (forward only), with `d = l2_prefetch_distance`,
default 1.

**Mechanics** (all hooks already exist - this is a policy, not an engine change):

- New `NextTilePrefetcher` implementing the existing `Prefetcher` interface
  (`include/cachesim/prefetch/prefetcher.h:37-93`). `on_demand` emits
  `ctx.mapper.neighbour(ctx.line, Axis::COUT, +i * stride_blocks)` for
  `i = 1..distance`. `neighbour` on `khkw_split` is exactly `line +
  delta × COUT_stride` and returns `nullopt` past the cout extent
  (`src/layout/khkw_split.cpp:154-172`), so over-the-edge targets drop safely.
- **Stride: +1 cout block per step, forward only, stateless.** The policy is a
  fixed-axis (COUT), up-only emitter: targets `+1..+d` blocks. It ignores
  `l2_prefetch_axis`/`up`/`down` (documented in the header). **No new config
  key is needed**: `l2_prefetch_policy: "next_tile"` and
  `l2_prefetch_distance` reuse existing keys, keeping the 112-column CSV
  schema and its three pinned counts untouched.
- **Trigger rule: keep the existing one** (recommended; see §7 Q2). The L2
  prefetch hook fires on an L2 demand **miss** and on a demand hit of a
  **still-prefetched** line (`src/core/engine.cpp:458-473`), not on every
  demand hit. For a streaming weight trace this self-sustains: tile t's lines
  were prefetched → demanded → each hit retriggers the prefetch of tile t+1.
  Firing on literally every probe would require an engine change at
  engine.cpp:458-473 that also alters the existing `neighbour` L2 policy unless
  gated - cost without evident benefit.
- **Known cold spots, accepted:** the first cout block of each core's chunk
  gets no prefetch (nothing triggers it), prefetches issued early in a run sit
  in L2 for a full run (16-64 tiles) before use, and at a core's chunk end the
  +1 target falls in the next core's chunk (still useful in the shared L2) or
  past the cout extent (`neighbour` returns nullopt, dropped safely). All show
  up honestly in `l2_pf_timely`/`l2_pf_wasted`.
- **Relation to `neighbour`:** at distance 1 the prefetch stream equals
  `neighbour` with axis=cout, up-only. `next_tile` is kept as a named policy
  per the user's decision (the deliverable is a policy, and it hard-wires the
  trace-derived semantics instead of relying on a four-knob configuration).
- L2-originated prefetches never fill L1 and are dropped (never queued) when
  they can't allocate - existing behavior (`engine.cpp:590-593`,
  `cache_level.cpp:115-220`), unchanged.

**Pre-implementation verification (step 0): DONE, assumption overturned.**
T33 (2026-10-29) dumped the V8 and R9 streams and found per-core cout deltas of
0 within a run and +4 elements (+1 block) at run boundaries (V8: tiles
16,32,...,112 of 128; R9: tiles 64,128,192 of 256), never +64. The semantics
above are the user-approved consequence.

### Files the policy touches (from the audit)

1. `include/cachesim/prefetch/next_tile.h`, `src/prefetch/next_tile.cpp` (new;
   native Makefile globs pick them up).
2. `include/cachesim/prefetch/prefetcher.h:56` - add `PrefetchKind::NextTile`.
3. `src/prefetch/prefetcher.cpp:15-27` - factory case.
4. `include/cachesim/enum_names.h:57-72` - `name_of` + `parse` (missing
   `name_of` makes stats throw).
5. `src/config.cpp:636-669` - validation: `next_tile` is **L2-only** (refused as
   an L1 policy) and refused with distance 0, mirroring the existing refusals.
   Axis/up/down keys are ignored by the policy (header comment states this).
6. Tests: new `tests/prefetch/test_next_tile.cpp` (unit: exact target lines on a
   `KhkwSplitMapper`; integration: engine run with `l2_pf_issued > 0`, MSHRs
   drained - pattern of `tests/prefetch/test_neighbour.cpp:18-84`), plus
   `tests/test_config.cpp` parse/refusal cases (pattern at :130-145, :327-336).
7. `tests/mutation_check.sh` - add `next_tile.cpp` to the `FILES=` line (:80), a
   `mutate_in` helper, and kill recipes per the file's own rules (:28-52). While
   in there, apply the board's standing fold-in note: change the
   `/on_issued/,$` anchor at :2031-2032 to
   `/^void NextBurstPrefetcher::on_issued/,$` (it currently matches a comment
   first and survives only by line ordering).
8. **Not touched:** `EngineParams` aliases, stats columns, CSV schema, engine
   trigger code (under the recommended Q2 answer).

## 4. Pipeline and grid changes

Per `docs/REPRODUCE.md:214-243`, new sweeps should be a thin script that imports
`scripts/pipeline.py` helpers rather than editing the demo. So:

- **New grid file** `configs/cache/l2pf_demo.json`: `line_bytes: [64]`,
  `l2_banks: [1]`, `prefetch: [[none,0],[next_burst,1]]`, crossed with
  `l2_prefetch: [[none,0],[next_tile,1]]`. This
  needs a small extension to `src/cachesim/grid.py:20-29` (it currently expands
  only the L1 prefetch pair) - additive, keyed off the new JSON key, so the
  existing `khkw_sweep.json` path is untouched and `make demo` is byte-stable.
- **New driver** `scripts/compare_l2pf.py`: imports `run_all` / `join_results` /
  `resolve_layers` from `pipeline.py`, runs the same stages into
  `data/demo_l2pf/<bench>/`, and writes the comparison CSV (§5). `pipeline.py`
  itself gets only the minimal seams the driver needs (e.g. parameterizing
  `KEY_FIELDS`/kept columns), nothing behavior-changing for `make demo`.
- No multi-bench wiring: loas only, per the user decision in §1.

## 5. The comparison CSV

`data/demo_l2pf/<bench>/results.csv`, one row per (trace_dir, layer, sample,
config):

| Group | Columns |
|---|---|
| Keys | `bench, trace_dir, layer, sample, config` |
| Config echo | `layout, line_size_bytes, l2_banks, prefetch_policy, prefetch_distance, l2_prefetch_policy, l2_prefetch_distance` |
| Latency | `nocsim_total_cycles, wcache_total_cycles, speedup_vs_nocsim, stall_total, fetch_latency_sum, hidden_latency, hidden_fraction` |
| Hit rate | `l1_hits, l1_accesses, l1_hit_rate, l2_hits, l2_accesses, l2_hit_rate, dram_accesses, dram_bytes` |
| L2 prefetch outcomes | `l2_pf_issued, l2_pf_timely, l2_pf_late, l2_pf_wasted, l2_pf_coverage` |

All of these already exist in the raw cachesim stdout
(`stats.cpp:175-215, 256-337`); the driver simply keeps them instead of
dropping them. A short `summary.md` reports, per (layer, L1-prefetch, banks):
baseline vs enhanced `wcache_total_cycles` delta, `l2_hit_rate` delta, and both
speedups vs nocsim - the table the artifact will plot.

## 6. Artifact-setup prompt (deliverable, not an artifact)

`docs/demo_l2pf_artifact_prompt.md` - a self-contained prompt for the agent on
the run machine. Contents: repo + branch + commit to check out; build commands
(`make build`); the loas input requirements (the committed input traces and
tracked schedules suffice; no Gurobi needed for V8/V9/R9/R16); the exact
`compare_l2pf.py` invocation; the expected CSV schema (§5) and the 80-row
count; the baseline cross-check (§2) as a validity gate; and what the artifact
should show (latency bars: nocsim vs cache-baseline vs cache-next_tile per
layer; hit-rate bars: baseline vs enhanced L1/L2; the `l2_pf_*` outcome table).
No artifact is produced here.

## 7. Open questions

Resolved by the user 2026-10-29: loas only (no ptb/spinalflow); L1 prefetch
{none, next_burst@1}; banks pinned to 1; 4 configs total.

Remaining, resolved by default unless the user objects:

1. **Trigger rule.** Keep the existing L2 trigger (miss + hit-on-prefetched
   retrigger, self-sustaining chain) rather than literally firing on every L2
   request. No engine change, no effect on existing policies.

## 8. Task split (dispatched only after plan approval)

| id | task | files | owner |
|---|---|---|---|
| T33 | Step-0 stream verification: dump V8+R9 streams, confirm per-core +64-cout tile stride, report wrap pattern | scratch only | impl |
| T34 | `next_tile` policy + enum/factory/config validation + unit & config tests | §3 list items 1-6 | impl |
| T35 | mutation_check.sh: next_tile recipes + the standing `on_issued` anchor fix | tests/mutation_check.sh | impl |
| T36 | Grid extension + `l2pf_demo.json` + `compare_l2pf.py` driver + CSV/summary | grid.py, configs/cache/, scripts/ | impl |
| T38 | Local loas run: 80-row CSV, baseline cross-check vs data/demo/loas/results.csv | data/demo_l2pf/ | impl |
| T39 | Artifact-setup prompt doc | docs/demo_l2pf_artifact_prompt.md | scribe |
| T40 | Atlas/doc pass: cachesim_native.md prefetch sections + drifted citations | docs/atlas/ | scribe |

Ordering: T33 gates T34; T34 gates T35/T36 reviews; T38 needs T34+T36;
T39/T40 go out only after their subjects read reviewed-pass (board rule). Every
row is reviewed by archie; `make test`, `make test-cli`, and the mutation sweep
must pass before T38's run.

**Acceptance for the whole job:** (1) baseline rows byte-match the previous
demo's 64 B rows; (2) enhanced rows show `l2_pf_issued > 0` and the CSV carries
every §5 column; (3) `make demo` output is byte-identical to before (the demo
path is untouched); (4) full test suite + mutation check green.
