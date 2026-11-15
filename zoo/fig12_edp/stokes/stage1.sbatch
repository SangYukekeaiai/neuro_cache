#!/bin/bash
#SBATCH --partition=normal
#SBATCH --account=dwu2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --propagate=NONE
set -euo pipefail
STAGE="$HOME/snn_edp_stokes_20261114"
REPO="$STAGE/neuro_cache_wcache"
cd "$REPO"
unset CONDA_SHLVL CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER BASH_ENV ENV
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1
export BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1 POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$REPO:$REPO/src:$REPO/zoo/archx/zoo"
date -Is
hostname
ulimit -a
exec /apps/anaconda/anaconda-2024.10/bin/conda run --no-capture-output -p "$STAGE/env" python -B zoo/fig12_edp/stokes/stage1_worker.py \
    --config "$STAGE/stage1/config.json" --case-index "$SLURM_ARRAY_TASK_ID" --attempt "${T97_ATTEMPT:-0}"
