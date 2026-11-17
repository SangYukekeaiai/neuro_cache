#!/usr/bin/env bash
#SBATCH --job-name=t71-phase-a
#SBATCH --account=dwu2
#SBATCH --partition=normal
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --array=0-129%250
#SBATCH --propagate=NONE
#SBATCH --output=phase-a-%A_%a.out
#SBATCH --error=phase-a-%A_%a.err

set -euo pipefail

KIT="${KIT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
REPO="${REPO:-$(cd "$KIT/../../.." && pwd)}"
STAGE="${STAGE:-$HOME/snn_edp_stokes_20261114}"
CONDA="${CONDA:-/apps/anaconda/anaconda-2024.10/bin/conda}"
ENV_PATH="${ENV_PATH:-$STAGE/env}"
MANIFEST="${MANIFEST:-$KIT/phase_a_manifest.json}"

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1
export BLIS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1
export TBB_NUM_THREADS=1
export GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$REPO:$REPO/src:$REPO/zoo/archx/zoo"
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR="/dev/shm/t71-phase-a-${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$TMPDIR"
cleanup_tmpdir() {
  rmdir "$TMPDIR" 2>/dev/null || true
}
trap cleanup_tmpdir EXIT

cd "$REPO"
setsid "$CONDA" run --no-capture-output -p "$ENV_PATH" \
  python -B "$KIT/trace_case.py" --manifest "$MANIFEST" \
  --case-index "$SLURM_ARRAY_TASK_ID"
