#!/bin/bash
#SBATCH --job-name=snn_cosa_sweep
#SBATCH --output=outputs/full_arch_sweep/slurm/logs/%A_%a.out
#SBATCH --error=outputs/full_arch_sweep/slurm/logs/%A_%a.err
#SBATCH --array=0-1567%8
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --partition=normal

set -euo pipefail

PROJ="$HOME/projects/snn_cosa"

export GRB_LICENSE_FILE="$HOME/gurobi.lic"

# Avoid hidden thread explosion from numpy / scipy / BLAS.
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate cosa_snn

cd "$PROJ"

mkdir -p outputs/full_arch_sweep/slurm/logs
mkdir -p outputs/full_arch_sweep

python scripts/run_full_arch_sweep.py \
    --arch-index "$SLURM_ARRAY_TASK_ID" \
    --jobs "$SLURM_CPUS_PER_TASK" \
    --time-limit 30 \
    --mip-gap 0.001 \
    --out-dir outputs/full_arch_sweep