#!/bin/bash
#SBATCH --job-name=snn_collect
#SBATCH --output=outputs/full_arch_sweep/slurm/logs/collect_%j.out
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --partition=general

PROJ=$HOME/projects/snn_cosa

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate cosa_snn

cd "$PROJ"

python scripts/collect_full_sweep.py \
    --sweep-dir outputs/full_arch_sweep \
    --out outputs/full_arch_sweep/summary.csv
