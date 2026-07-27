# Full 10,000-sample weight-trace generation across 5 archs x 31 layers

> Created: 2026-07-20. Rephrased requirements plus an execution plan for
> scaling the weight-trace generation pipeline from a 1-sample proof of
> concept to the full 10,000-sample x 155-combo sweep, informed by a live
> audit of what's already on disk and on the cluster.

## Context

The project has a two-stage pipeline: `mip_solver` (Gurobi schedule
solving), then `archmodels`/`tracegen.py` (reconstruct real per-tile
weight-address traces from captured spike data), meant to feed a
downstream cache-locality analysis of 5 SNN accelerator designs (LoAS,
SpinalFlow, PTB, GustavSNN, Prosperity) across ResNet19 (19 layers) plus
VGG16 (12 layers), 31 layers total, at full scale (10,000 real CIFAR-10
samples per layer, matching what's actually captured).

A prior session built this exact pipeline (Stage 1 solve, Stage 2
reconstruct, Slurm wrappers), ran it partially, and then the `scripts/`
directory was deleted in commit `ee26d70` ("Restructure repo... drop
scripts/"). The work is not starting from zero: real progress exists on
disk in three places outside this repo's git history, and the request
here was to (a) correct a mistaken premise about the input data, (b)
verify/finish the schedule-solving stage with full mode enumeration and
visualize it, and (c) scale the reconstruction stage to the full
10,000-sample scope and get it running on the cluster as fast as is
reasonable for a shared resource.

## Rephrased requirements (corrected against what's actually on disk)

1. ~~Generate 10,000x31 input traces from LoAS~~ -> **Not needed.** The
   captured `.npy` traces at
   `/u/yyu9/neuro_cache_trace/input_trace/loas/{resnet19_T4_all,vgg16_T4_all}`
   already contain all 10,000 CIFAR-10 samples for all 31 layers
   (`meta.json`: `n_samples: 10000`, captured 2026-07-17, shapes verified,
   e.g. `[4, 10000, 64, 32, 32]`). What is *actually* only partial is the
   **reconstructed weight-trace output**, see item (3).

2. Verify/finalize the 5-archs x 31-layers schedules via full traffic-mode
   enumeration (all 13 `TrafficMode`s: `BASE` plus 12 named modes in
   `src/mip_solver/modes.py`), then classify each schedule's DRAM-level
   loop permutation by fusing `{HO,WO}` into `M`, `{COUT}` into `N`,
   `{KH,KW,CIN}` into `K`, `T` stays `T` (adjacent-same-superdim fusion
   only, sizes ignored), and visualize the per-arch x per-layer
   permutation classes.

3. Using the finalized schedules, reconstruct weight-address traces for
   all 10,000 real samples across all 155 (arch x layer) combos via each
   arch's `ArchComputeModel`, gzip-compress, store outside home/quota-tight
   storage, and run the sweep on the cluster with resource sizing that
   accounts for GustavSNN being structurally the slowest (it bars `T` from
   node-level residency, giving roughly 8,000 node-tiles/sample vs.
   low-thousands for the other 4 archs), monitoring the run periodically
   until done.

## Key findings from the audit

- **Cluster is NCSA Delta** (`dt-login03.delta.ncsa.illinois.edu`,
  `ClusterName=delta`), not DeltaAI. Unlike what the deleted scripts
  assumed (`ghx4`, GH200-only, no CPU partition), Delta has a genuine
  CPU-only partition: `cpu`, 136 nodes x 128 cores, `DefaultTime=00:30:00`,
  `MaxTime=2-00:00:00`, QOS `cpuqos`, `AllowAccounts=ALL` (the only
  account, `bebv-delta-gpu`, can submit there, no `--gres=gpu` needed).
  This removes an entire artificial constraint the old scripts worked
  around.
- **Storage**: home (`/u`) is at 64.5GB of a 103GB hard quota, excluded
  per explicit instruction. `/projects/bebv` group quota is 500GB with
  only **176GB free** (325GB already used cluster-wide by the group), too
  tight for a full 10,000x155 sweep. `/work/hdd/bebv` (group-writable,
  part of Delta's 8.5PB `dltawork` Lustre space, 3.6PB free), confirmed
  write access, is the target.
- **Existing partial corpus** at `/projects/bebv/yyu9/neuro_cache_outputs/weight_traces/`
  (147GB) already covers **all 155 combos** (not just 1), at these
  per-combo sample counts:

  | Arch | Samples/combo done |
  |---|---|
  | loas | 1000/1000 (complete at 1k scope) |
  | prosperity | 1000/1000 |
  | spinalflow | 1000/1000 |
  | ptb | 892 to 1000 (a few combos short) |
  | gustavsnn | 100/100 only, confirms it's the slow one |

  For one spot-checked combo (`loas/vgg16_T4_all/layer_01_features_3`),
  the old sample data's `dram_num_steps` (4096) and tile count (4096)
  **match** the currently-cached `outputs/schedules/.../layer_01...json`
  exactly, evidence (not yet full proof) that this partial corpus was
  generated against the same schedule geometry that's cached today, so
  it's likely reusable, not stale.
- **However**, the 155 cached schedule JSONs in this repo's own
  `outputs/schedules/` are missing the `mode` field entirely (predating
  it, added in commit `5e97068`, "Select best TrafficMode per layer
  schedule"). This means we cannot tell from the file alone whether it
  was produced by full 13-mode enumeration or an older single-mode solve.
  **This must be verified before trusting either the cached schedules or
  the partial corpus reconstructed from them** (see Phase 2, step 0).
- The reusable core (`solve_and_cache_schedule`, `reconstruct_samples_for_schedule`,
  `reconstruct_tile_chunk`, `save_weight_trace`/`load_weight_trace`,
  gzip skip-existing-safe atomic writes) already lives in
  `src/tracegen.py`, no need to rebuild this.
- The driver scripts that used it (`scripts/solve_schedules.py`,
  `scripts/generate_weight_traces.py`, and 5 Slurm wrapper variants) were
  deleted in `ee26d70` but are fully recoverable via
  `git show ee26d70^:scripts/<path>`. Their inline comments document real
  incidents worth preserving (288 to 144 workers after an OOM stall, a
  stdin-pipe-inherited-by-fork hang, a home-quota crash, a disk-quota
  crash). Restore and adapt rather than rewrite.
- **No DRAM-permutation classifier/visualizer exists yet**, this is new
  work. `src/mip_solver/cli.py`'s `_fmt_perm` (adjacent-same-*dim*
  fusion, used for the `enumerate` CLI's pretty-print) is a useful
  reference but doesn't do the M/N/K/T super-dimension fusion this needs.

## Decisions

- **Storage target for new/extended output**: `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/`.
- **Concurrency**: aggressive, target roughly 50+ concurrent nodes on the
  shared `cpu` partition while the sweep runs.
- **Existing partial corpus**: reuse it, skip already-done samples. To
  reconcile this with the storage-target decision, Stage 2 first does a
  one-time parallel copy of the existing 147GB from `/projects/bebv/yyu9/neuro_cache_outputs/weight_traces/`
  into the new `/work/hdd/bebv/yyu9/...` location (adapting the existing
  `/projects/bebv/yyu9/migrate_compress_parallel.py` pattern, this time a
  straight copy since the source is already gzip-compressed, not a
  recompress), then runs the sweep against `/work` with skip-existing so
  it naturally computes only the samples missing up to 10,000 per combo.
  This step is **gated on the Phase 2 verification** below: if that
  verification shows the old schedules were NOT enumeration winners, the
  old partial corpus is stale and this migration step is skipped instead
  (full regeneration from the newly-solved schedules).

## Plan of execution

### Phase 0: restore reusable code
- Restore `scripts/solve_schedules.py`, `scripts/generate_weight_traces.py`,
  and the Slurm wrappers from `git show ee26d70^:scripts/...`, adapted for:
  - `--partition=cpu` (not `ghx4`), no `--gres=gpu`.
  - Default `--out-dir` / `OUT_DIR` pointing at
    `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces`.
  - Current `src/tracegen.py` API (already slightly ahead of what the
    deleted `generate_weight_traces.py` called, e.g. `reconstruct_tile_chunk`
    exists now but isn't wired up yet; wire it in for GustavSNN, see Phase 4).

### Phase 1: confirm input traces (no action expected)
- Re-verify `meta.json` `n_samples == 10000` for both trace dirs (already
  done) and spot-check a couple of `.npy` shapes. Closed, no capture
  re-run needed.

### Phase 2: finalize schedules (Stage 1)
- **Step 0 (verification, do first):** on a compute node/interactive
  session with the `cosa_snn`/`base` conda env and Gurobi license
  available, run `solve_and_cache_schedule` fresh for 2-3 spot-check
  combos (e.g. `loas/vgg16_T4_all/layer_01_features_3`,
  `gustavsnn/resnet19_T4_all/layer_01_layer1_0_conv1`) into a scratch
  cache dir, and diff `dram_num_steps` plus winning mode plus DRAM
  permutation against both the currently-cached `outputs/schedules/...json`
  and the `dram_num_steps` recorded in the existing partial samples.
  - **If they match**: the cached schedules are already enumeration
    winners; just backfill the missing `mode` field into all 155 JSONs
    (cheap, no re-solve) and treat the partial corpus as valid, then
    proceed to the migrate-and-extend path in Phase 4.
  - **If they don't match**: re-run Stage 1 (`solve_schedules.py`) for
    real across all 5 archs x 31 layers (fast, Gurobi-bound, low
    concurrency, roughly 155 x 13 = 2000 solves at a few seconds each,
    done interactively or in one small job) and treat the old partial
    corpus as stale (full Stage 2 regeneration, no reuse).
- Either way, end this phase with `outputs/schedules/summary.csv`
  refreshed and every schedule JSON carrying a real `mode`.

### Phase 3: DRAM-permutation classification and visualization
- New script (e.g. `src/dram_permutation.py` or
  `scripts/classify_dram_permutation.py`): for each of the 155 finalized
  schedules, read `result.strategy.DRAM.temporal_permutation.loops`, map
  each loop's `dim` to its super-dimension (`HO`,`WO` -> `M`; `COUT` -> `N`;
  `KH`,`KW`,`CIN` -> `K`; `T` -> `T`), fuse consecutive entries of the same
  super-dim (sizes discarded, order preserved), producing a canonical
  class string per combo, e.g. `M->K->N->T`.
- Aggregate into a 5-arch x 31-layer table/heatmap (one figure per arch,
  or one combined grid), colored by permutation class, saved under
  `outputs/figures/`. Review this before spending compute in Phase 4,
  since Phase 4 reconstructs directly from these same schedules.

### Phase 4: Stage 2, full-scale weight-trace generation
- One-time migration of the 147GB existing partial corpus from
  `/projects/bebv/yyu9/neuro_cache_outputs/weight_traces/` into
  `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/` (parallel copy,
  adapted from `migrate_compress_parallel.py`), only if Phase 2's
  verification confirmed reuse is valid.
- Restored `generate_weight_traces.py`, extended to call
  `tracegen.reconstruct_tile_chunk` (tile-parallel) instead of
  `reconstruct_samples_for_schedule` (sample-parallel) specifically for
  `arch == "gustavsnn"`, matching why that helper already exists in
  `src/tracegen.py` (its docstring explains GustavSNN's roughly
  8000-tile/sample shape makes sample-parallel chunking rerun that loop
  once per worker).
- Slurm job array over the 155 combos on `--partition=cpu`
  (`--account=bebv-delta-gpu`), one array task per (arch, layer), sized
  around 128 cores/task, `--workers` tuned below the OOM threshold the
  deleted script's own comments measured (144 workers safe, 288 was not,
  on a 350G-mem GPU node; recheck the equivalent safe ratio for Delta's
  roughly 257G/128-core CPU nodes), samples 0-9999, skip-existing on,
  `--array=...%N` throttled so **roughly 50+ nodes** are in flight at
  once, but not literally all 136 (leave headroom for the rest of the
  `bebv` group).
- Give GustavSNN combos a longer per-task time budget and earlier
  submission priority than the other 4 archs, since it's both the
  slowest per-sample *and* now has the most remaining samples to compute
  (100 to 10,000 vs. 1000 to 10,000 for the others).
- Preserve the deleted scripts' safety fixes: `timeout` per combo so one
  stall doesn't eat the whole job's walltime, `< /dev/null` on the python
  invocation (stdin-pipe-inherited-by-fork hang fix), `set -uo pipefail`
  without `-e` (one combo's failure shouldn't abort the array task), and
  the atomic temp-file-plus-`os.replace` write `save_weight_trace`
  already does.

### Phase 5: monitoring and verification
- Periodic `squeue -u yyu9` / `sacct` checks plus tailing per-task
  `logs/%x_%j.out`/`.err` while the sweep runs.
- After completion, run a `--summarize` pass (per the original design
  doc) to build `manifest.csv` over `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/`,
  confirming all 155 combos x 10,000 samples exist with no `ERROR`
  status, and sanity-check total compressed size against the roughly
  19.5x compression ratio already measured on real data.

## Critical files

- `src/tracegen.py`: reusable solve/reconstruct/persist core (reuse as-is
  except wiring `reconstruct_tile_chunk` into GustavSNN's path).
- `src/mip_solver/modes.py`, `src/mip_solver/enumerator.py`: 13-mode
  enumeration (reuse as-is).
- `src/mip_solver/cli.py` (`_fmt_perm`, `_print_enumeration_summary`):
  reference for permutation formatting conventions.
- `outputs/schedules/summary.csv`, `outputs/schedules/<arch>/<trace_dir>/<layer>.json`:
  Stage 1 output to finalize.
- `/u/yyu9/neuro_cache_trace/input_trace/loas/{resnet19_T4_all,vgg16_T4_all}/{*.npy,meta.json}`:
  already-complete input (read-only).
- `/projects/bebv/yyu9/neuro_cache_outputs/weight_traces/` (source, 147GB)
  migrating to `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/`
  (new target): Stage 2 output.
- Recovered from git history: `git show ee26d70^:scripts/solve_schedules.py`,
  `scripts/generate_weight_traces.py`, `scripts/slurm/run_generate_weight_traces.slurm`
  (plus variants): restore and adapt.

## Verification

- Phase 2 step 0's spot-check IS the correctness gate for everything
  downstream, do not skip it.
- Cross-check: sum of `len(tiles)` per generated `LayerWeightTrace` must
  match `dram_num_steps` from the same combo's schedule (already true for
  the one spot-checked combo: 4096 tiles equals `dram_num_steps` 4096).
- Run Stage 2 on the smallest/fastest combo first end-to-end before
  submitting the full array, inspect a sample file by hand.
- Re-run without `--force` on an already-done combo, confirm it reports
  skipped, not recomputed.
- Final `--summarize` / `manifest.csv` pass is the completion signal for
  the whole sweep.
