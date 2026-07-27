# Weight-trace generation scripts

Run from the **project root** with the `base` conda env active
(`source ~/miniconda3/etc/profile.d/conda.sh && conda activate base`),
`PYTHONPATH=src`. Stage 1 additionally needs `GRB_LICENSE_FILE` set to a
working Gurobi license.

Two-stage pipeline, see `dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md`
for the full design:

```
Stage 1 (Gurobi, low concurrency)     Stage 2 (no Gurobi, embarrassingly parallel)
solve_schedules.py               -->  generate_weight_traces.py
                                       generate_weight_traces_tile_parallel.py (GustavSNN)
outputs/schedules/<arch>/<trace_dir>/<layer>.json
                                       outputs/weight_traces/<arch>/<trace_dir>/<layer>/sample_NNNNN.json.gz
```

## Stage 1: `solve_schedules.py`

Solves every `(arch, trace_dir, layer)` schedule once via full 13-mode
traffic enumeration (`mip_solver.enumerator`/`TrafficMode`), keeps the
winning mode, and persists it plus a `summary.csv`.

```bash
python scripts/solve_schedules.py \
  --trace-root /u/yyu9/neuro_cache_trace/input_trace/loas \
  --trace-dirs vgg16_T4_all resnet19_T4_all \
  --archs loas gustavsnn prosperity ptb \
  --cache-dir outputs/schedules
```

`--force` re-solves and overwrites even if a cached schedule exists.
Skips any arch missing `configs/arch/<arch>.yaml` (currently `spinalflow.yaml`
does not exist on disk, see the arch config's own note if reconstructed).

## `plan_trace_shards.py`

Writes `outputs/schedules/jobs.txt` (one `arch,trace_dir,layer` line per
successfully-solved combo in `summary.csv`), which the Slurm array script
indexes into by `SLURM_ARRAY_TASK_ID`.

```bash
python scripts/plan_trace_shards.py
```

## Stage 2: `generate_weight_traces.py` / `generate_weight_traces_tile_parallel.py`

Loads a Stage-1-cached schedule (no re-solving) and reconstructs a range
of real captured samples against it, one `.json.gz` per sample. Skip-existing
is on by default (`--force` to override).

```bash
python scripts/generate_weight_traces.py \
  --arch loas --trace-dir vgg16_T4_all --layer layer_01_features_3 \
  --out-dir /work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces \
  --sample-start 0 --sample-count 10000 --workers 16
```

`generate_weight_traces_tile_parallel.py` has the identical CLI but
chunks by **tile** instead of by sample, for GustavSNN specifically:
GustavSNN bars `T` from node-level residency, giving ~8000 node-tiles per
sample (vs. low-thousands for the other 4 archs), so sample-chunking
reruns that whole per-tile loop once per worker. See
`src/tracegen.py`'s `reconstruct_tile_chunk` docstring.

## `visualize_dram_permutation.py`

Classifies every finalized schedule's DRAM-level loop permutation into a
canonical M/N/K/T super-dimension string (`src/dram_permutation.py`) and
renders a 5-arch x 31-layer heatmap.

```bash
python scripts/visualize_dram_permutation.py
```

Writes `outputs/figures/dram_permutation.{csv,png,pdf}`.

## `slurm/run_full_sweep_array.slurm`

One Slurm **array task per (arch, trace_dir, layer) combo**, reading
`outputs/schedules/jobs.txt`. Requires `plan_trace_shards.py` to have run
first.

```bash
sbatch --array=0-154%50 scripts/slurm/run_full_sweep_array.slurm
```

Targets NCSA Delta's `gpuA100x4` partition, requesting the minimum
viable GPU (1) purely because this account (`bebv-delta-gpu`) is a
GPU-type allocation and Delta's job_submit policy rejects zero-GPU jobs
from GPU-type accounts on any partition, including the genuinely
CPU-only `cpu` partition; the workload itself never touches the GPU
(pure numpy gather/reduce). See the script's own header comment for the
account-type constraint this works around.

## `sweep_archmodel_layers.py`

Separate from the weight-trace pipeline above: runs each arch's
`ArchComputeModel` through `nocsim.combine`'s live per-tile loop to
produce a NoC/DRAM transaction CSV (`tc.csv`) and per-layer summary
stats, for one sample per layer. Not part of the generate-once sweep;
kept for ad hoc single-sample NoC-simulation checks.
