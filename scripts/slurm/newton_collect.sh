#!/bin/bash
#SBATCH --job-name=snn_collect
#SBATCH --output=outputs/full_arch_sweep/slurm/logs/collect_%j.out
#SBATCH --error=outputs/full_arch_sweep/slurm/logs/collect_%j.err
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --partition=normal

set -euo pipefail

PROJ="$HOME/projects/snn_cosa"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate cosa_snn

cd "$PROJ"

mkdir -p outputs/full_arch_sweep/slurm/logs

python scripts/collect_full_sweep.py \
    --sweep-dir outputs/full_arch_sweep \
    --out outputs/full_arch_sweep/summary.csv