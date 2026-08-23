#!/bin/bash
#SBATCH --job-name=phaseD_spad_vs_cache
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --array=0-2
#SBATCH --output=logs/phaseD_spad_vs_cache_%A_%a.out
#SBATCH --error=logs/phaseD_spad_vs_cache_%A_%a.err

# One array task = one unit = one trace at one cache LAYOUT = one
# generator-into-wcache_sweep pipeline pair. Parallelism is the array, not a
# worker pool inside a pipeline: --stream rejects --workers > 1 because N
# producers cannot share one stdout pipe (campaign plan section 10.4 item 7).
# One mapper serves a whole sweep, so a grid that varies the line size is one
# sweep per line size over its own pass of the stream: Tier 0's 180
# configurations are 3 units of 60, not 1 unit of 180.
# The default array covers Tier 0 (3 units). Set the tier and the matching array
# size at submit time; README.md lists the unit count per tier.
#   sbatch --array=0-179 --export=ALL,TIER=tier2_ridge run_sweep.slurm
# The A40 is requested because the Delta account is GPU-only, not because this
# campaign needs a GPU (see README.md).

set -uo pipefail
cd /u/yyu9/projects/neuro_cache || exit 1
export PYTHONPATH=src

TIER="${TIER:-tier0}"
HERE=profiling/0820_phaseD_spad_vs_cache

# The campaign plan's global constraint is that Python runs through conda, never
# a bare `python`. The 0803 script predates that constraint and does use a bare
# `python`; it is not the precedent to follow here. Checked rather than assumed,
# because `conda run` failing to resolve would otherwise surface as a python that
# cannot import the generator's dependencies, several minutes in.
CONDA_ENV="${CONDA_ENV:-cosa_snn}"
command -v conda >/dev/null || {
    echo "conda is not on PATH in this batch shell; submit with --export=ALL from a" >&2
    echo "shell where it is, or set CONDA_ENV and load the module first." >&2
    exit 1
}

# run_sweep.py owns the pipeline pair, the .tmp-then-os.replace unit cache and
# the resume decision. It runs, per unit:
#   generate_weight_traces.py --stream ... | wcache_sweep --config-grid ... --trace -
# --no-capture-output so the per-unit progress lines reach the Slurm log as they
# happen rather than at exit.
conda run -n "$CONDA_ENV" --no-capture-output python "$HERE/run_sweep.py" --run \
    --grid "$HERE/grids/${TIER}.json" \
    --tier "$TIER" \
    --unit-index "$SLURM_ARRAY_TASK_ID" \
    --workers 1 \
    --results-dir "$HERE/results" \
    --out "$HERE/spad_vs_cache.csv"
