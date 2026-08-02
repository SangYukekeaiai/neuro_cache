#!/bin/bash
#SBATCH --job-name=patch_tick_ids
#SBATCH --partition=gpuA100x4
#SBATCH --account=bebv-delta-gpu
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Backfills tick_ids into already-generated LoAS/PTB/SpinalFlow/Prosperity
# weight traces in place (see scripts/patch_tick_ids_trivial_archs.py's
# own docstring for why this is safe for these 4 archs and not GustavSNN).
#
# --gpus-per-node=1 is a workaround, not a real GPU need: this account
# (bebv-delta-gpu) can only submit to GPU partitions, even for CPU-only
# work.

set -uo pipefail
cd /u/yyu9/projects/neuro_cache
source /u/yyu9/miniconda3/etc/profile.d/conda.sh
conda activate gurobi
export PYTHONPATH=src

python3 scripts/patch_tick_ids_trivial_archs.py --workers 16 < /dev/null
