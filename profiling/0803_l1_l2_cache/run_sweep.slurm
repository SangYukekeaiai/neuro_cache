#!/bin/bash
#SBATCH --job-name=l1_l2_loas
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --output=logs/l1_l2_loas_%j.out
#SBATCH --error=logs/l1_l2_loas_%j.err

set -uo pipefail
cd /u/yyu9/projects/neuro_cache || exit 1
export PYTHONPATH=src
python profiling/0803_l1_l2_cache/run_sweep.py --run --workers "$SLURM_CPUS_PER_TASK"
