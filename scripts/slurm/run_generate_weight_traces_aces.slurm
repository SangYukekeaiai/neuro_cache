#!/bin/bash
#SBATCH --job-name=weight_trace_gen
#SBATCH --partition=cpu
#SBATCH --account=REPLACE_WITH_YOUR_ACES_ACCOUNT_NUMBER
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --mem=240G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

# ACES has a genuine CPU-only partition (unlike DeltaAI's GH200-only
# architecture), so no GPU-equivalent billing conversion applies here --
# https://hprc.tamu.edu/kb/User-Guides/ACES/Batch/. --ntasks-per-node=64
# matches TAMU HPRC's own example; run `maxconfig` on ACES itself to
# confirm the real max cores/node for the cpu partition and raise this
# (and --workers below) if higher is available.

set -euo pipefail
cd /u/yyu9/projects/neuro_cache  # adjust if the repo lives elsewhere on ACES

export GRB_LICENSE_FILE=/path/to/your/gurobi.lic   # set for ACES -- see note below
export PYTHONPATH=src
WORKERS=64
SAMPLES=10000

tail -n +2 outputs/schedules/summary.csv | while IFS=, read -r arch trace_dir layer status dram_num_steps error; do
    if [ "$status" != "OK" ]; then
        continue
    fi
    echo "=== $arch / $trace_dir / $layer ==="
    python3 scripts/generate_weight_traces.py \
        --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
        --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS"
done
