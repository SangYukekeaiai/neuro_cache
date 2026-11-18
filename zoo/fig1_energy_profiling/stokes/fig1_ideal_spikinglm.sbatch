#!/bin/bash
#SBATCH --job-name=fig1-slm-ideal
#SBATCH --account=dwu2
#SBATCH --partition=normal
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
set -euo pipefail
fig1_root="$SLURM_SUBMIT_DIR"
repo_root="$(cd "$fig1_root/../.." && pwd)"
export PYTHONPATH="$repo_root/src:$repo_root:$fig1_root/src"
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export TMPDIR="$fig1_root/outputs/tmp/slm_ideal_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$TMPDIR"
exec "$HOME/snn_edp_stokes_20261114/env/bin/python" -B "$fig1_root/src/whole_run_ideal.py" \
  --index "$SLURM_ARRAY_TASK_ID" \
  --trace-root "$HOME/snn_edp_stokes_20261114/input_trace_full500" \
  --cases "$fig1_root/configs/cases_spikinglm.json" \
  --counts-root "$fig1_root/outputs/counts_spikinglm" \
  --out-root "$fig1_root/outputs/whole_run_ideal_spikinglm/counts" \
  --manifest-root "$fig1_root/outputs/manifest_spikinglm"
