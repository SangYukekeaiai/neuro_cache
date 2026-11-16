#!/bin/bash
#SBATCH --account=bebv-dtai-gh
#SBATCH --partition=ghx4-interactive
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=288
#SBATCH --gpus-per-node=4
#SBATCH --mem=440G
#SBATCH --time=02:00:00
#SBATCH --job-name=fig12_arm_stream
#SBATCH --output=/u/yyu9/projects/neuro_cache_wcache/zoo/fig12_edp/deltaai/full500/logs/interactive_%j.log
set -euo pipefail
cd /u/yyu9/projects/neuro_cache_wcache
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONDONTWRITEBYTECODE=1
bash zoo/fig12_edp/deltaai/setup_env.sh
exec /sw/user/python/miniforge3-pytorch-2.10.0/bin/conda run --no-capture-output \
    -p /work/hdd/bebv/yyu9/fig12_full500_deltaai/env \
    bash zoo/fig12_edp/deltaai/job.sh "$1" --count-only --chunk-seconds 6300
