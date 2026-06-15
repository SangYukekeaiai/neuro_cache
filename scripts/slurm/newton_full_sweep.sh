#!/bin/bash
#SBATCH --job-name=snn_cosa_sweep
#SBATCH --output=outputs/full_arch_sweep/slurm/logs/%A_%a.out
#SBATCH --error=outputs/full_arch_sweep/slurm/logs/%A_%a.err
#SBATCH --array=0-1567         # one task per arch config (4×4×7×7×2 = 1568)
#SBATCH --cpus-per-task=16     # 16 workers per task (matches --jobs below)
#SBATCH --mem=16G
#SBATCH --time=04:00:00        # 4h wall time per task (generous for 135 wl × 8 modes × 30s)
#SBATCH --partition=general    # adjust to your Newton partition

# --- project root (adjust if needed) ---
PROJ=$HOME/projects/snn_cosa

# --- Gurobi WLS license ---
export GRB_LICENSE_FILE=$HOME/gurobi.lic

# --- conda env ---
source "$HOME/miniconda3/etc/profile.d/conda.sh"   # or anaconda3
conda activate cosa_snn

mkdir -p "$PROJ/outputs/full_arch_sweep/slurm/logs"

cd "$PROJ"

python scripts/run_full_arch_sweep.py \
    --arch-index "$SLURM_ARRAY_TASK_ID" \
    --jobs 16 \
    --time-limit 30 \
    --mip-gap 0.001 \
    --out-dir outputs/full_arch_sweep
