#!/usr/bin/env bash
#SBATCH --job-name=fig12-spinalflow-counts
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=zoo/fig12_edp/counts/slurm-%j.log
set -euo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
# Supply a CPU allocation account at submission (see Delta's accounts command).
repo=${SLURM_SUBMIT_DIR:?Submit from the repository root}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
exec conda run --no-capture-output -n base python \
    "$repo/zoo/fig12_edp/counts/spinalflow_counts.py" \
    --trace-root /work/nvme/bebv/yyu9/input_trace_delta \
    --output "$repo/zoo/fig12_edp/counts/spinalflow_counts.csv" \
    --threads 1 --resume "$@"
