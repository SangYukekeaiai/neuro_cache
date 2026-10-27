#!/bin/bash
#SBATCH --job-name=profile_all_layers
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/profile_all_layers_%A_%a.out
#SBATCH --error=logs/profile_all_layers_%A_%a.err
#
# One array task = one layer of the benchmark: scripts/profile_all_layers.py
# --task-index $SLURM_ARRAY_TASK_ID generates the stream of each of samples
# 0..N-1 and runs cachesim_sweep over the grid on it, writing
# $NEURO_CACHE_DATA/profiling/<bench>/layers/<trace_dir>/<layer>.csv.
# The array size is the number of layers, which the driver reads from the
# captures' meta.json; submit from the repo root, with NEURO_CACHE_DATA set:
#   n=$(python scripts/profile_all_layers.py --bench loas --count)
#   jid=$(sbatch --parsable --array=0-$((n - 1)) --export=ALL,BENCH=loas scripts/slurm/profile_all_layers.slurm)
#   sbatch --dependency=afterany:$jid --export=ALL,BENCH=loas,MERGE=1 scripts/slurm/profile_all_layers.slurm
# The last line runs the merge step (no --array) into .../profiling/<bench>/all_layers.csv;
# it exits 1 and lists the layers whose CSV is missing.
# Optional: N_SAMPLES (default 500), GRID (JSON array of wcache configs), TRACE_ROOT.
#
# NOT RUN ON DELTA YET. Verified only by `profile_all_layers.py --dry-run` and by
# one array task run locally on the 5-sample loas subset with --n-samples 5,
# without Slurm. Confirm on the first Delta submission:
#   - partition and account (#SBATCH --partition/--account/--gres above; copied
#     from profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm, GPU-only account)
#   - module loads: none are done here; the native cachesim_sweep build and a
#     conda on PATH are assumed
#   - conda env activation: `conda run -n "$CONDA_ENV"` (scripts/env.sh), and
#     the env needs gurobipy for layers without a tracked schedule
#   - memory and time limits (--mem, --time) for 500 samples of the largest layer
#   - array size = number of layers (the --count line above)

set -uo pipefail
cd "${SLURM_SUBMIT_DIR:-.}" || exit 1
[ -f scripts/env.sh ] || { echo "submit from the repo root" >&2; exit 1; }
root=$PWD
. "$root/scripts/env.sh"
command -v conda >/dev/null || { echo "conda is not on PATH in this batch shell" >&2; exit 1; }

args=(--bench "${BENCH:-loas}" --n-samples "${N_SAMPLES:-500}" --jobs "${SLURM_CPUS_PER_TASK:-1}")
[ -n "${GRID:-}" ] && args+=(--grid "$GRID")
[ -n "${TRACE_ROOT:-}" ] && args+=(--trace-root "$TRACE_ROOT")
if [ -n "${MERGE:-}" ]; then
    args+=(--merge)
else
    args+=(--task-index "${SLURM_ARRAY_TASK_ID:?not an array task; set MERGE=1 for the merge step}")
fi
conda run -n "$CONDA_ENV" --no-capture-output python scripts/profile_all_layers.py "${args[@]}"
