#!/bin/bash
#SBATCH --job-name=weight_trace_1000
#SBATCH --partition=ghx4-interactive
#SBATCH --account=bebv-dtai-gh
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=144
#SBATCH --mem=350G
#SBATCH --time=01:30:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Per-arch 1000-sample weight-trace generation on a DEDICATED node --
# not the shared login node. ghx4-interactive schedules far faster than
# plain ghx4 (confirmed empirically: instant vs. 45min-2h queue wait), but
# caps time limit at 2h, hence --time=01:30:00 for margin. MUST be
# submitted via sbatch, not srun: srun ties the job's lifetime to the
# submitting shell/session, and a session restart mid-run silently killed
# two jobs this way (one ~93% through its last layer) -- sbatch jobs are
# detached and survive that.
#
# Targets the SAME OUT_DIR the 100-sample demo wrote to, with no --force,
# so generate_weight_traces.py's per-sample skip-existing check naturally
# extends sample_00000..00099 (already done) up through sample_00999 (900
# new samples/layer), instead of recomputing the first 100 -- and, thanks
# to save_weight_trace's atomic temp-file+os.replace write, also safely
# resumes past any sample left mid-write by a prior interrupted run.
#
# Usage: sbatch scripts/slurm/run_1000_arch.slurm <arch>
set -uo pipefail
cd /u/yyu9/projects/neuro_cache
export GRB_LICENSE_FILE=/u/yyu9/gurobi.lic
export PYTHONPATH=src
ARCH="${1:?usage: sbatch run_1000_arch.slurm <arch>}"
WORKERS=144
SAMPLES=1000
OUT_DIR=/projects/bebv/yyu9/neuro_cache_outputs/weight_traces

while IFS=, read -r arch trace_dir layer status dram_num_steps error; do
    if [ "$arch" != "$ARCH" ] || [ "$status" != "OK" ]; then
        continue
    fi
    echo "=== $arch / $trace_dir / $layer ==="
    timeout 15m conda run -n base python3 scripts/generate_weight_traces.py \
        --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
        --out-dir "$OUT_DIR" \
        --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS" < /dev/null \
        || echo "!!! FAILED: $arch/$trace_dir/$layer (exit $?) -- continuing to next combo"
done < <(tail -n +2 outputs/schedules/summary.csv)

echo "=== $ARCH 1000-sample run complete ==="
