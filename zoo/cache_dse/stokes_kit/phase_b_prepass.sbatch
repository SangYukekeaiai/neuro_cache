#!/usr/bin/env bash
#SBATCH --job-name=t71-cache-oracle
#SBATCH --account=dwu2
#SBATCH --partition=normal
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --array=0-119%250
#SBATCH --propagate=NONE
#SBATCH --output=t71-cache-oracle-%A_%a.out
#SBATCH --error=t71-cache-oracle-%A_%a.err

set -euo pipefail
KIT="${KIT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
REPO="${REPO:-$(cd "$KIT/../../.." && pwd)}"
CONDA="${CONDA:-/apps/anaconda/anaconda-2024.10/bin/conda}"
ENV_PATH="${ENV_PATH:-$HOME/snn_edp_stokes_20261114/env}"
MANIFEST="${MANIFEST:?set MANIFEST to the generated cache-DSE manifest}"

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1 POLARS_MAX_THREADS=1
export TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
export PYTHONPATH="$REPO:$REPO/src:$REPO/zoo/archx/zoo:$REPO/zoo/archx/src"
export LD_LIBRARY_PATH="${STAGE:-$HOME/snn_edp_stokes_20261114}/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR=/dev/shm

cd "$REPO"
setsid "$CONDA" run --no-capture-output -p "$ENV_PATH" python -B \
  "$KIT/run_cache_case.py" --manifest "$MANIFEST" --prepass \
  --trace-index "$SLURM_ARRAY_TASK_ID"
