#!/bin/bash
#SBATCH --job-name=weight_trace_100_all
#SBATCH --partition=ghx4
#SBATCH --account=bebv-dtai-gh
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=144
#SBATCH --mem=350G
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Single-job replacement for 5 separate per-arch sbatch submissions --
# those queued for 45min-2h each (5 simultaneous full-node requests
# contend much harder than 1 does, 828 pending jobs partition-wide at
# submit time). This requests ONE dedicated node and runs all 5 archs in
# parallel inside it (same pattern as run_100_demo.sh, which ran directly
# on the login node and OOM'd there because the login node caps a user's
# cgroup at ~35.8GB) -- here we have a real --mem=350G allocation, so
# 5 archs x 28 workers = 140 workers safely fits (~2.5GB/worker vs. the
# ~830MB peak observed per worker).
#
# --force: same reasoning as run_100_arch.slurm -- don't trust whatever
# partial/possibly-corrupted state the login-node run left behind.
set -uo pipefail
cd /u/yyu9/projects/neuro_cache
export GRB_LICENSE_FILE=/u/yyu9/gurobi.lic
export PYTHONPATH=src
OUT_DIR=/projects/bebv/yyu9/neuro_cache_outputs/weight_traces
SAMPLES=100
WORKERS=28

run_arch() {
    local ARCH="$1"
    while IFS=, read -r arch trace_dir layer status dram_num_steps error; do
        if [ "$arch" != "$ARCH" ] || [ "$status" != "OK" ]; then
            continue
        fi
        echo "=== $arch / $trace_dir / $layer ==="
        timeout 15m conda run -n base python3 scripts/generate_weight_traces.py \
            --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
            --out-dir "$OUT_DIR" \
            --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS" --force < /dev/null \
            || echo "!!! FAILED: $arch/$trace_dir/$layer (exit $?) -- continuing to next combo"
    done < <(tail -n +2 outputs/schedules/summary.csv)
    echo "=== $ARCH 100-sample run complete ==="
}

for a in loas spinalflow ptb gustavsnn prosperity; do
    run_arch "$a" &
done
wait
echo "=== ALL 5 ARCHS' 100-SAMPLE RUNS COMPLETE ==="
