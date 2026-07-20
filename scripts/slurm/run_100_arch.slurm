#!/bin/bash
#SBATCH --job-name=weight_trace_100
#SBATCH --partition=ghx4
#SBATCH --account=bebv-dtai-gh
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=144
#SBATCH --mem=350G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Per-arch 100-sample weight-trace generation on a DEDICATED ghx4 node --
# replaces the login-node run that OOM'd (login node's per-user cgroup
# caps at ~35.8GB; 120 concurrent workers there blew past it and the
# kernel OOM-killer silently killed 291 processes, hanging pool.map()).
# A dedicated node's real --mem=350G budget gives ~2.43GB/worker at 144
# workers, matching this project's own prior tuning (see
# run_generate_weight_traces.slurm's WORKERS=144 comment).
#
# --force: the login-node run this replaces left an unknown number of
# samples corrupted (truncated mid-write by OOM kills, not yet fully
# audited) sitting at paths skip-existing would otherwise trust. Forcing
# a clean rewrite of all 100 samples/layer here is cheap (a few extra
# minutes on a dedicated node) and removes any dependency on the audit
# being exhaustive.
#
# Usage: sbatch scripts/slurm/run_100_arch.slurm <arch>
set -uo pipefail
cd /u/yyu9/projects/neuro_cache
export GRB_LICENSE_FILE=/u/yyu9/gurobi.lic
export PYTHONPATH=src
ARCH="${1:?usage: sbatch run_100_arch.slurm <arch>}"
WORKERS=144
SAMPLES=100
OUT_DIR=/projects/bebv/yyu9/neuro_cache_outputs/weight_traces

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
