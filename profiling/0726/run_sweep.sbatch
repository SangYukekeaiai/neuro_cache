#!/bin/bash
#SBATCH --account=bebv-delta-gpu
#SBATCH --partition=gpuA100x4
#SBATCH --gpus-per-node=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=220G
#SBATCH --time=36:00:00
#SBATCH --job-name=cache_sweep
#SBATCH --output=/u/yyu9/projects/neuro_cache/profiling/0726/sweep_run.log

source /u/yyu9/miniconda3/etc/profile.d/conda.sh
conda activate gurobi
cd /u/yyu9/projects/neuro_cache/profiling/0726
python3 -u cache_sweep.py --workers 24
