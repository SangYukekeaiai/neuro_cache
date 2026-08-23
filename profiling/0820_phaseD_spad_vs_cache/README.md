# 2026-08-20 Phase D scratchpad vs cache campaign

Slurm launcher for the staged sweep in
`log/2026-08-20-phaseD-sweep-profiling-plan.md`. **No campaign tier has run.**
The only thing that has run is the local demo and smoke pass recorded at the
bottom of this file.

**This campaign runs on NCSA Delta only (user ruling R7, plan section 8.1).**
CECSUnaryLab is for build, tests, fixture-slice demos and single-point sanity
checks. No campaign tier runs locally. The Delta project root is
`/u/yyu9/projects/neuro_cache`, which is not the local checkout path.

## The grid and the unit of work

The cache grid is 180 configurations: L1 size {2, 4, 8, 16, 32} KB x line size
{16, 32, 64} B x L2 size {256, 512, 1024} KB x prefetch distance {0, 2, 4, 8}
(plan section 4.4). All other axes are pinned.

A grid point is not a process. One unit of work is one
`(arch, n_cores, layer, sample)` trace at one cache layout: the generator
streams it once and every configuration of that layout consumes the one stream
in broadcast lockstep inside a single `wcache_sweep` process (plan section
10.5). The line-size axis is the one axis that cannot share a pass, so the 180
configurations are 3 units of 60. The array is over units, never over
configurations.

## Tiers and array sizes

| Tier | Grid file | Units | Configs per unit | Rows | `sbatch --array=` |
|---|---|---|---|---|---|
| 0 pilot | `grids/tier0.json` | 3 | 60 | 180 | `0-2` |
| 1 baselines | `grids/tier1_spad.json` | 180 | 1 | 180 simulated + 180 oracle | `0-179` |
| 2 ridge | `grids/tier2_ridge.json` | 540 | 13 + 1 + 1 | 2,700 | `0-539` |
| 3 full factorial | `grids/tier3_full.json` | 72 | 60 | 4,320 | `0-71` |
| 4 latency sensitivity | `grids/tier4_latency.json` | 36 | 5 | 180 | `0-35` |

Unit arithmetic: the 36 shared points are 3 architectures x 3 core counts x 4
layers; Tier 1, 2 and 4 run them, Tier 1 and 2 at 5 samples (180 traces), Tier 4
at 1 sample (36 traces). Tier 3 runs 12 points at 16 cores x 2 samples = 24
traces. Tier 0 is one point, one sample: 1 trace.

Traces are not units. One mapper serves a whole `wcache_sweep`, so a grid that
varies the line size is one sweep per line size, each over its own pass of the
stream (`src/wcache/native/src/sweep.cpp:55-61`); a mixed grid is refused at
startup. A unit is therefore one trace at one layout: Tier 0 and Tier 3 split
3 ways, Tier 2 splits into 13 + 1 + 1 configs, and Tier 1 and Tier 4 have one
layout each. Tier 2 carries the `l1_mshrs = 4` calibration row, so it is 15
configs and 2,700 rows rather than the plan's uncalibrated 14 and 2,520.

**This script runs Tier 0 by default**, which is the go/no-go for everything
else: it measures the real per-run cost and is the first place the 2 KB
configurations run at all. Derive the array size for any tier from the driver
rather than from this table:

```bash
PYTHONPATH=src python profiling/0820_phaseD_spad_vs_cache/run_sweep.py \
    --dry-run-units --grid profiling/0820_phaseD_spad_vs_cache/grids/tier2_ridge.json | wc -l
```

## Array tasks, pipeline pairs and workers

`generate_weight_traces.py --stream` rejects `--workers > 1`: N producers cannot
share one stdout pipe into one consumer (plan section 10.4 item 7). Parallelism
therefore moves up a level, to independent producer-consumer pipeline pairs.
Each array task takes one `--unit-index` and runs exactly one pair
(`--workers 1`). To pack several pairs into one allocation instead, give the
driver a unit range and `--workers 4`; the memory arithmetic below covers that
case.

## Memory

Peak RSS of `wcache_sweep` on the checked-in `loas_vgg16_layer01_v2` slice,
over the real 60-config unit shape (5 L1 x 3 L2 x 4 prefetch distances at one
`cin_block`), measured with `/usr/bin/time`. The fixture and release builds give
the same numbers:

```
 1 config    4,352 KB
 4 configs   4,864 KB
60 configs  15,616 KB
```

That is a straight line: about **191 KB per grid engine** on a fixed base of
about **4.1 MB**, and it predicts the 4-config point to within 1%. So one
pipeline pair is

```
4.1 MB + 180 x 191 KB  =  ~38 MB    per pipeline pair
4 concurrent pairs      =  ~150 MB
```

An older figure of 11 MB per engine (`src/wcache/FINDINGS.md:340`) gave
`180 x 11 MB + 2.5 MB ~= 2.0 GB` per pair. That 11 MB is not a per-engine cost:
it is the whole-process peak of a single-engine run over 64,000 bursts and
154,072 emitted lines, a far larger workload than one fixture slice, so it folds
the fixed base and a much bigger tile window into what was read as a per-engine
number. The 2.0 GB it produced is high by about 50x.

Both figures are kept here because the measured one is the slice measurement and
carries one caveat: the per-engine slope is what a fixture slice measures well,
but the fixed base includes only a fixture-sized tile window. A full campaign
trace has a larger window, so the base term grows while the 191 KB slope does
not. Tier 0 measures the real base.

The job requests **128 G**. That is a node share, not a working-set estimate: it
is the figure the plan pins for this partition and the one the 0803 campaign
used. It is left as-is deliberately, and the headroom over the ~150 MB four-pair
working set is a consequence of requesting a node share, not a sizing decision.

## GPU request

The cache arm is CPU-only: the pipeline is a Python generator piped into the
`wcache_sweep` C++ binary, and `spad_nocsim` is a compiled CPU event simulator.
`--gres=gpu:1` and `--partition=gpuA40x4` are kept anyway because the Delta
account `bebv-delta-gpu` is GPU-only and cannot submit to a CPU partition (plan
section 8.1). The A40 is allocated and left unused, exactly as in
`profiling/0803_l1_l2_cache`.

## Resume

Resume is by result, not by input. Stream mode writes no intermediate trace, so
there is no file to skip on (plan section 10.4 item 6). Each unit writes
`results/<tier>/.<unit_key>.csv.<pid>.tmp` and `os.replace`s it into
`<unit_key>.csv` only after `wcache_sweep` exits 0 and the row count equals the
grid size, so a killed job leaves a complete unit file or none. Resubmitting the
same array regenerates only the missing units. This matters: plan section 8.2
puts Stage 3 at about 1.97 h against a 2 h wall cap, so it is at least two jobs.

## Commands

Submit Tier 0 from the repo root on Delta (`logs/` must exist):

```bash
sbatch profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm
```

Any other tier, with the matching array size:

```bash
sbatch --array=0-179 --export=ALL,TIER=tier2_ridge \
    profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm
```

Merge after the array drains:

```bash
PYTHONPATH=src python profiling/0820_phaseD_spad_vs_cache/run_sweep.py \
    --merge-only --results-dir profiling/0820_phaseD_spad_vs_cache/results \
    --out profiling/0820_phaseD_spad_vs_cache/spad_vs_cache.csv
```

## The per-unit command

Every array task runs one pipeline pair through `run_sweep.py`, which owns the
`.tmp`-then-`os.replace` unit cache. The pair it builds is

```
generate_weight_traces.py --stream --arch A --trace-dir D --layer L \
    --sample-start S --sample-count 1 --workers 1 \
  | wcache_sweep --config-grid <unit grid> --trace - \
      --arm cache --tier TIER --git-commit HEAD --out results/TIER/<unit>.csv.tmp
```

`run_sweep.py` prefers `build/release/wcache_sweep` and falls back to
`build/fixture/wcache_sweep`, so build the release binaries before submitting:

```bash
cd src/wcache/native && make MODE=release lib && make MODE=release apps
```

## Expected wall time

About 2.0 h on 16 CPUs for Stage 3, bracket 0.4 to 3.3 h, from a planning figure
of 15 core-seconds per row (plan section 8.2). **That figure is an estimate.**
Tier 0 exists to replace it with a measurement; nothing below Tier 0 should be
submitted until it has. The local demo below is far too small to bound it: it is
a 2-tile fixture slice, not a layer.

## What has run locally, 2026-08-20

Under ruling R7 this machine runs demos and single-point sanity checks only.
**No campaign tier ran here**, and the Slurm script above is for Delta. What ran:

| Run | Grid | Rows | Wall | Result |
|---|---|---|---|---|
| demo | `grids/demo.json` | 8 (2 units x 4 configs) | 0.4 s | `tests/demo_smoke.sh` green |
| demo, release build | `grids/demo.json` | 8 | 0.3 s | identical to the fixture build on all 89 comparable columns |
| duplicate check | `grids/duplicate_check.json` | 4 | 0.2 s | `tests/duplicate_check.sh` green |
| dump and replay | `grids/demo.json` | 4 x 2 | 0.3 s | `tests/replay_check.sh` green, 90 of 91 columns identical |

```bash
python3 run_sweep.py --run --grid grids/demo.json --tier demo --out demo_results.csv
tests/demo_smoke.sh demo_results.csv
python3 run_sweep.py --run --grid grids/duplicate_check.json --tier dupcheck --out dup.csv
tests/duplicate_check.sh dup.csv
```

`-O2 -DNDEBUG` and `-O0 -g` produce the same numbers: comparing the two demo
CSVs column by column, ignoring only `run_id` and `sim_wall_seconds`, leaves 89
columns and no difference. No assert in this tree has a side effect.

Two of the plan's section 2 known-answer checks did not survive contact with the
model, and both are written up in `PROGRESS.md` as decisions rather than patched
over here:

- **`padding_fraction == 0` is not true of the column as defined** (B162). The
  ratio the implementation plan's open question Q-G settled on measures the
  share of each fetched line the trace never consumes, which on an SNN trace is
  input sparsity: 0.203125 on a full real layer whose dimensions divide exactly
  at every block size in the grid, because 13 of its 64 input channels never
  spike in that sample. `tests/demo_smoke.sh` checks the invariant the meter
  does promise, that one value belongs to one (trace, layout) whatever cache
  surrounds it.
- **A prefetch distance above the MSHR budget is not inert** (B164). The budget
  bounds prefetches in flight; the distance bounds how far the prefetch cursor
  leads the demand cursor, and a completed prefetch still counts toward the lead
  while holding no MSHR. Measured here, `d = 16` differs from `d = 15` and is
  slightly worse (623 versus 617 cycles); duplicates begin at 24, the number of
  bursts one core issues in one tile. This matters for the grid: v3's question
  13 expects 15 of its 30 points to be exact duplicates, and they are not.

A third correction is in `tests/demo_smoke.sh` itself (B163): the task brief's
prefetch-accounting check summed three outcome states, and `engine.h:195-197`
states the identity with the five drop counts included. The full identity holds
exactly on every row, 254 + 114 = 368 issued.

## Status

`run_sweep.py` and `grids/` landed with Task 19 and implement the flag
interface this Slurm script calls (`--run`, `--workers`, `--unit-index`,
`--merge-only`, `--grid`, `--tier`, `--results-dir`, `--out`,
`--dry-run-units`). `tests/` holds the five checks that guard them:
`test_resume.sh`, `test_slurm_shape.sh`, `demo_smoke.sh`,
`duplicate_check.sh` and `replay_check.sh`. No campaign tier has run.

Two review findings against the stream and grid readers are open and unfixed,
recorded as U29 and U30 in `PROGRESS.md`: a `burst_dim` other than `COUT`
decodes silently wrong rather than being refused, and `--max-engines` is checked
after the grid it is meant to bound has already been expanded. Neither can be
triggered by anything in this campaign's grids, which all burst along COUT and
all stay far under the engine bound, so neither blocks a tier.
