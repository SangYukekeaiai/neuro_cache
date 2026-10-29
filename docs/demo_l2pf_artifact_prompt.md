# Artifact-setup prompt: the loas L2 next-tile prefetch comparison

This file is a self-contained prompt. Hand everything below the rule to an
agent on another machine; it carries the repo coordinates, the build, the run,
the expected output, the gates that decide whether the run is valid, and the
figures the artifact should present.

Scope note for the dispatcher: this document is the deliverable. It is a prompt
to be executed elsewhere, not an artifact and not a runner script.

---

## Task

Set up, run, and present the loas L2-prefetch comparison from the
`neuro_cache` repository.

### 1. Repository and revision

```
git clone git@github.com:SangYukekeaiai/neuro_cache.git
cd neuro_cache
git checkout wcache-rebuild-phase-a
```

Use the **head of `wcache-rebuild-phase-a`**. There is no pinned commit SHA to
give you: at the time this prompt was written the work was not yet
committed, so the revision you want is "the commit containing
`scripts/compare_l2pf.py` and `src/cachesim/native/src/prefetch/next_tile.cpp`",
which is the branch head. Confirm both files exist before going further:

```
ls scripts/compare_l2pf.py src/cachesim/native/src/prefetch/next_tile.cpp
```

If either is missing you are on the wrong revision; stop and report that rather
than running anything.

### 2. Environment and build

From the repo root (`docs/REPRODUCE.md:6-13`):

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make build
```

- `make build` compiles the cache simulator, the NoC event simulator, and the
  loas replay binary (`Makefile:5-8`).
- **Gurobi is not needed.** It is required only to *solve* a schedule, and all
  four layers this run uses have tracked schedules under
  `configs/schedules/loas/` (`docs/REPRODUCE.md:22-27`). Do not set up a
  license.
- Input traces are committed (`input_trace/loas/vgg16_T4_n5/`,
  `input_trace/loas/resnet19_T4_n5/`), so nothing has to be downloaded.
- `NEURO_CACHE_DATA` sets the output root and defaults to `data/`
  (`docs/REPRODUCE.md:28-30`). Leave it unset unless you need the outputs
  elsewhere.

Optional sanity check before the run:

```
python scripts/pipeline.py --check-bench loas
```

It exits 0 when the input contract holds (`docs/REPRODUCE.md:56-59`).

### 3. The run

```
python scripts/compare_l2pf.py
```

Defaults are already the intended configuration, so pass no flags:
benchmark `loas`; layers `V8 V9 R9 R16` (the four with tracked schedules,
`scripts/pipeline.py:47`); samples 5 starting at 0; grid
`configs/cache/l2pf_demo.json` (`scripts/compare_l2pf.py:276-284`).

The grid is 2 x 2 x 1 = 4 configs — L1 prefetch `none/0` vs `next_burst/1`,
crossed with L2 prefetch `none` vs `next_tile/1`, L2 banks pinned to 1, line
size 64 B only (`configs/cache/l2pf_demo.json`). Config names are assigned in
grid order as `l2pf_demo_00 .. l2pf_demo_03`
(`scripts/compare_l2pf.py:211`), expanded banks-slowest then L2 prefetch then
L1 prefetch (`src/cachesim/grid.py:36-41`):

| config | L2 prefetch | L1 prefetch | role |
|---|---|---|---|
| `l2pf_demo_00` | `none` | `none/0` | baseline |
| `l2pf_demo_01` | `none` | `next_burst/1` | baseline |
| `l2pf_demo_02` | `next_tile/1` | `none/0` | enhanced |
| `l2pf_demo_03` | `next_tile/1` | `next_burst/1` | enhanced |

This mapping is confirmed against a completed run of the driver, not inferred
from the grid code alone.

### 4. Expected output

`data/demo_l2pf/loas/results.csv` — one row per (trace_dir, layer, sample,
config), so **exactly 80 data rows** plus the header: 4 layers x 5 samples x 4
configs. The driver prints the row count and the path when it finishes
(`scripts/compare_l2pf.py:270`).

Its 32 columns, in order (`scripts/compare_l2pf.py:25-34`):

| Group | Columns |
|---|---|
| Keys | `bench, trace_dir, layer, sample, config` |
| Config echo | `layout, line_size_bytes, l2_banks, prefetch_policy, prefetch_distance, l2_prefetch_policy, l2_prefetch_distance` |
| Latency | `nocsim_total_cycles, wcache_total_cycles, speedup_vs_nocsim, stall_total, fetch_latency_sum, hidden_latency, hidden_fraction` |
| Hit rate | `l1_hits, l1_accesses, l1_hit_rate, l2_hits, l2_accesses, l2_hit_rate, dram_accesses, dram_bytes` |
| L2 prefetch outcomes | `l2_pf_issued, l2_pf_timely, l2_pf_late, l2_pf_wasted, l2_pf_coverage` |

Alongside it, `data/demo_l2pf/loas/summary.md` holds a per-(layer, L1 prefetch,
banks) table: baseline vs enhanced cycles, the cycle delta, both L2 hit rates
and their delta, and both speedups vs nocsim as geomeans
(`scripts/compare_l2pf.py:94-126`).

### 5. Validity gates

Both must pass before you present any number.

**Gate 1 — the baseline arm reproduces the previous demo exactly.** The two
`l2_prefetch=none` configs are, by construction, the previous 48-point demo's
64 B / banks-1 / L1-`none` and L1-`next_burst/1` points, which that demo named
`khkw_32` and `khkw_33`. Their `wcache_total_cycles` must match it on all 40
baseline rows (20 rows per config). This is the gate that proves the original
cache and nocsim settings were not disturbed.

> **Read this before attempting Gate 1.** `data/` is **not** tracked in git —
> a fresh clone has no `data/demo/loas/results.csv` to compare against. You
> must first generate it with `make demo`, which runs the full previous sweep
> (960 rows) and takes considerably longer than the 80-row comparison. If you
> cannot afford that run, say so and report Gate 1 as **not performed** rather
> than skipping it silently. Do not substitute a different baseline.

With `data/demo/loas/results.csv` present, match on the key
(`trace_dir, layer, sample`) and compare `wcache_total_cycles`:
`l2pf_demo_00` against `khkw_32`, `l2pf_demo_01` against `khkw_33`. Every one
of the 40 pairs must be equal. Report any mismatch with its key and both
values; a single mismatch invalidates the comparison.

**Gate 2 — the enhanced arm actually prefetched.** Every row with
`l2_prefetch_policy = next_tile` (the 40 rows of `l2pf_demo_02` and
`l2pf_demo_03`) must have `l2_pf_issued > 0`. A zero means the policy was
selected but never fired, which makes the enhanced arm meaningless even if its
cycle counts look reasonable.

### 6. What the artifact should show

Three presentations, all from `results.csv`:

1. **Per-layer latency bars**, three bars per layer (V8, V9, R9, R16): nocsim
   (`nocsim_total_cycles`), cache baseline and cache `next_tile`
   (`wcache_total_cycles`). Mean over the 5 samples; hold L1 prefetch fixed per
   panel, or show both L1 settings as grouped bars.
2. **Hit-rate bars**, baseline vs enhanced, for L1 (`l1_hit_rate`) and L2
   (`l2_hit_rate`), per layer.
3. **An L2 prefetch outcome table** over `l2_pf_issued, l2_pf_timely,
   l2_pf_late, l2_pf_wasted, l2_pf_coverage` for the `next_tile` rows. Read the
   third and fourth bullets of §7 before captioning it: these columns neither
   sum to `l2_pf_issued` nor belong to `next_tile` alone.

For orientation, the reference run on the authoring machine produced
`l2_pf_timely` exactly equal to `l2_hits` (403200 for `l2pf_demo_02`, 5760 for
`l2pf_demo_03`) and `l2_pf_late = 0` throughout. Treat those as a shape to
expect, not as values to reproduce.

### 7. Honest limits — state these, do not work around them

- **nocsim has no hit rate.** It prints cycle counts only
  (`src/nocsim/sim.py:393-397`). The hit-rate comparison is therefore
  cache-baseline vs cache-enhanced, two bars, with nocsim absent by
  construction. Leave it out of that figure; do not impute a value.
- **"Latency" is `total_cycles`.** There is no per-level latency column in
  either simulator, so total cycles is the latency metric across all three
  arms. `stall_total`, `fetch_latency_sum`, `hidden_latency` and
  `hidden_fraction` come along as supporting columns, not as a latency
  breakdown.
- **The L2 outcome columns are not a partition of `l2_pf_issued`, in both
  directions.** L2 lines still tagged as prefetched when the run ends are not
  charged to `l2_pf_wasted`, so the outcomes can sum to *less* than issued
  (`src/cachesim/native/src/core/engine.cpp:717-719`). They can also be charged
  when the L2 policy issued *nothing*: `l2_pf_issued` counts only L2-policy
  issues (`engine.cpp:393`), while the waste tag is set for any L2 line opened
  by a prefetch with no demand merged onto it (`engine.cpp:550-551`) — which
  includes lines an **L1** `next_burst` prefetch pulled in. The reference run
  shows this plainly: `l2pf_demo_01` has `l2_pf_issued = 0` and
  `l2_pf_wasted = 1034240`. Do not present these columns as percentages of
  issued that add to 100, and do not read `l2_pf_wasted` as attributable to
  `next_tile` alone.

- **The L2 baseline hit rate is identically zero, and that is a real zero.** In
  the reference run both baseline configs have `l2_hits = 0` against
  `l2_accesses = 1213440` (`l2pf_demo_00`) and `18560` (`l2pf_demo_01`) — the
  weight stream has no L2 reuse of its own, so it is not a divide-by-zero
  artifact. Consequence for figure 2: the L2 baseline bar is flat zero for
  every layer, and **every** L2 hit in the enhanced arm is one `next_tile`
  created. Say that rather than letting a reader think the bar is missing.

- **`next_tile` buys L2 hits at the cost of DRAM traffic, and is not a win
  everywhere.** In the reference run `dram_accesses` rises from 1213440
  (`l2pf_demo_00`) to 2005011 (`l2pf_demo_02`), about +65%, with 732211 of
  1203600 issued prefetches charged wasted. Mean cycles accordingly move the
  wrong way in two of the eight (layer, L1-prefetch) groups. Present the cycle
  deltas with their sign, per group, and do not summarize the policy as a
  speedup.
- **One benchmark only.** loas is the only benchmark with a nocsim arch, input
  traces, and tracked schedules in this tree (`scripts/pipeline.py:44-45`); ptb
  and spinalflow are out of scope and cannot run here.
- **Four layers only**, the four with tracked schedules. Running others would
  require Gurobi to solve a schedule first.

### 8. Reporting back

Report: the revision you ran (`git rev-parse HEAD`), the row count, the
outcome of both gates with evidence, the three presentations, and anything in
§7 you could not satisfy. If a gate fails, report the failure and stop — do not
present the comparison as valid.
