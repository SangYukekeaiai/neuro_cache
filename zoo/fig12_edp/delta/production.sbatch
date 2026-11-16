#!/bin/bash
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA40x4,gpuA40x4-preempt
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gpus-per-node=2
#SBATCH --mem=140G
#SBATCH --time=06:00:00
#SBATCH --array=0-9%2
#SBATCH --requeue
#SBATCH --job-name=fig12_delta_490_499
#SBATCH --output=/u/yyu9/projects/neuro_cache_wcache/zoo/fig12_edp/delta/full500/logs/production_%A_%a.log
set -euo pipefail
sample_top=${1:-499}
if [[ $sample_top == /* ]]; then
    mapfile -t assigned_samples < "$sample_top"
    sample=${assigned_samples[$SLURM_ARRAY_TASK_ID]}
else
    sample=$((sample_top-SLURM_ARRAY_TASK_ID))
fi
cd /u/yyu9/projects/neuro_cache_wcache
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONDONTWRITEBYTECODE=1
exec /u/yyu9/miniconda3/bin/conda run --no-capture-output -n fig12-archx \
    bash zoo/fig12_edp/delta/node.sh /work/hdd/bebv/yyu9/fig12_full500_delta \
    "$sample" --memory-gib 128 --cores 32
