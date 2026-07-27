#!/bin/bash
#SBATCH --job-name=weight_trace_burst
#SBATCH --partition=gpuA100x4-interactive
#SBATCH --account=bebv-delta-gpu
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=48
#SBATCH --mem=180G
#SBATCH --time=00:55:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Self-resubmitting burst job for ONE (arch, trace_dir, layer) combo on
# Delta's gpuA100x4-interactive partition. That partition caps jobs at
# 1h (MaxTime=01:00:00), too short to finish a full 10,000-sample combo
# in one shot, but empirically had real free capacity RIGHT NOW when the
# regular gpuA100x4/gpuA40x4/gpuA100x8/gpuH200x8 partitions did not
# (confirmed via `srun --immediate`: 64 cores failed, 48 succeeded) --
# interactive partitions get separate/faster scheduling than batch
# partitions, at ~2x the per-core billing rate.
#
# generate_weight_traces.py has no internal checkpointing within a single
# invocation -- when the 55min limit kills this job, only whichever
# worker chunks fully finished get saved (per-worker atomic writes);
# whatever chunk each worker was mid-computation on is lost, same as any
# other interrupted run. Skip-existing on the NEXT burst recomputes only
# the genuinely-missing samples, so nothing already written is wasted,
# and each successive burst's remaining-sample count shrinks, so chunks
# per worker get smaller and finish faster over time.
#
# Self-resubmits via `sbatch` (not `--dependency=afterany`, since the
# combo isn't finished on failure/timeout either, and either exit path
# should chain the same way) until the combo reaches 10,000 samples, or
# ATTEMPT hits MAX_ATTEMPTS (safety cap against a silent bug turning this
# into infinite job spam).
#
# Usage: sbatch run_burst_interactive.slurm <arch> <trace_dir> <layer> [attempt]
set -uo pipefail
cd /u/yyu9/projects/neuro_cache

source /u/yyu9/miniconda3/etc/profile.d/conda.sh
conda activate base
export PYTHONPATH=src
WORKERS="$SLURM_CPUS_PER_TASK"
SAMPLES=10000
MAX_ATTEMPTS=40
OUT_DIR=/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces

ARCH="${1:?usage: sbatch run_burst_interactive.slurm <arch> <trace_dir> <layer> [attempt]}"
TRACE_DIR="${2:?usage: sbatch run_burst_interactive.slurm <arch> <trace_dir> <layer> [attempt]}"
LAYER="${3:?usage: sbatch run_burst_interactive.slurm <arch> <trace_dir> <layer> [attempt]}"
ATTEMPT="${4:-1}"

echo "=== burst attempt $ATTEMPT: $ARCH / $TRACE_DIR / $LAYER ==="
date

if [ "$ARCH" == "gustavsnn" ]; then
    GEN_SCRIPT=scripts/generate_weight_traces_tile_parallel.py
else
    GEN_SCRIPT=scripts/generate_weight_traces.py
fi

python3 "$GEN_SCRIPT" \
    --arch "$ARCH" --trace-dir "$TRACE_DIR" --layer "$LAYER" \
    --out-dir "$OUT_DIR" \
    --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS" < /dev/null

date
LAYER_OUT_DIR="$OUT_DIR/$ARCH/$TRACE_DIR/$LAYER"
N=$(find "$LAYER_OUT_DIR" -name "sample_*.json.gz" 2>/dev/null | wc -l)
echo "=== $N/$SAMPLES samples on disk after attempt $ATTEMPT ==="

if [ "$N" -ge "$SAMPLES" ]; then
    echo "=== combo complete, not resubmitting ==="
elif [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
    echo "!!! MAX_ATTEMPTS ($MAX_ATTEMPTS) reached with $N/$SAMPLES done -- not resubmitting, needs a human look"
else
    NEXT=$((ATTEMPT + 1))
    echo "=== resubmitting attempt $NEXT ==="
    sbatch scripts/slurm/run_burst_interactive.slurm "$ARCH" "$TRACE_DIR" "$LAYER" "$NEXT"
fi
