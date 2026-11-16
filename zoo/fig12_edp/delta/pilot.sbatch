#!/bin/bash
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=240G
#SBATCH --time=12:00:00
#SBATCH --job-name=fig12_delta_499
#SBATCH --output=/u/yyu9/projects/neuro_cache_wcache/zoo/fig12_edp/delta/full500/logs/pilot_%j.log
set -euo pipefail
REPO=/u/yyu9/projects/neuro_cache_wcache
ROOT=/work/hdd/bebv/yyu9/fig12_full500_delta
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONDONTWRITEBYTECODE=1
cd "$REPO"
exec /u/yyu9/miniconda3/bin/conda run --no-capture-output -n fig12-archx \
    bash zoo/fig12_edp/delta/node.sh "$ROOT" "${1:-499}"
