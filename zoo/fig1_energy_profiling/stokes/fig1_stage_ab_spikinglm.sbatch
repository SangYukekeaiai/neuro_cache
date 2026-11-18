#!/bin/bash
#SBATCH --job-name=fig1-slm-ab
#SBATCH --account=dwu2
#SBATCH --partition=normal
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=04:00:00
set -euo pipefail
sizes=(128k 256k 512k 1m)
size="${sizes[$SLURM_ARRAY_TASK_ID]}"
fig1_root="$SLURM_SUBMIT_DIR"
repo_root="$(cd "$fig1_root/../.." && pwd)"
export PYTHONPATH="$repo_root/src:$repo_root:$repo_root/zoo/archx/src"
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TMPDIR="$fig1_root/outputs/tmp/slm_ab_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$TMPDIR"
exec "$HOME/snn_edp_stokes_20261114/env/bin/python" -B \
  "$fig1_root/archx_config/stage_ab_spikinglm.py" --size "$size"
