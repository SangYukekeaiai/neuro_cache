#!/bin/bash
#SBATCH --job-name=weight_trace_full
#SBATCH --partition=gpuA100x4
#SBATCH --account=bebv-delta-gpu
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=240G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%x_%A_%a.out
#SBATCH --error=logs/%x_%A_%a.err
#
# 4000-sample sweep (scoped down from the full 10,000, see N_SAMPLES
# below), one Slurm ARRAY TASK per (arch, trace_dir, layer) combo -- each
# combo is its own job, so a stall or crash on one combo can no longer
# burn another combo's time budget, and Slurm schedules array tasks onto
# whichever nodes are free instead of serializing all 155 combos onto one
# node.
#
# Index into outputs/schedules/jobs.txt (one `arch,trace_dir,layer` line
# per combo, written by plan_trace_shards.py) via SLURM_ARRAY_TASK_ID,
# rather than re-deriving the combo list/arithmetic here. Takes one
# required positional arg -- an arch name -- and filters jobs.txt down to
# just that arch's 31 layers, so each arch can be submitted (and
# monitored, cancelled, resubmitted) as its own independent array instead
# of one 155-task array mixing all 5.
#
# Submit with, e.g.:
#   sbatch --job-name=weight_trace_loas --array=0-30 scripts/slurm/run_full_sweep_array.slurm loas
#
# Delta's `cpu` partition IS genuinely CPU-only (confirmed via
# `scontrol show partition cpu`, no GPU gres) -- but this account
# (bebv-delta-gpu) is a GPU-type allocation, and Delta's job_submit
# policy rejects zero-GPU jobs from GPU-type accounts regardless of
# partition ("Jobs requesting no GPU resources must be submitted under
# CPU type accounts" -- confirmed by a real rejected sbatch). There is
# no sibling bebv-delta-cpu account for this group. So this job requests
# the minimum viable GPU (1) purely to satisfy that gate and doesn't use
# it -- CPU-only workload (numpy gather/reduce, no matmuls, see
# tracegen.py's Stage 2 docstring).
#
# Partition/core choice is a live tradeoff between per-task cost
# (`scontrol show partition <name>`'s TRESBillingWeights) and actual
# queue wait, which fluctuates significantly over the course of a day --
# gpuA40x4/gpuA100x4 are cheaper per task but were seeing thousands of
# queued jobs and 18-26h estimated starts at submission time; the
# smaller gpuA100x8/gpuH200x8 pools (6-8 nodes) cost more per task but
# had far fewer competing jobs. Check `squeue --start` on the actual
# submission before assuming either the partition or the core count
# below still matches the cheapest-viable choice.
# --cpus-per-task claims the WHOLE node (not just this GPU's fractional
# share) to maximize CPU throughput per task, at the cost of stranding
# the other GPUs (and their CPU/mem share) on that node for other users
# while this task runs -- a deliberate tradeoff, not a fair-share
# default. Keep WORKERS (below) equal to --cpus-per-task.
set -uo pipefail
cd /u/yyu9/projects/neuro_cache

source /u/yyu9/miniconda3/etc/profile.d/conda.sh
conda activate base
export PYTHONPATH=src
# GustavSNN's native path holds real per-chunk memory (~2.25GB/10-sample
# chunk measured 2026-07-26 on its largest layer, vs. negligible for the
# other 4 archs' Python path) -- 64 workers at that rate risks the same
# OOM a 16-worker/64GB run hit before being scaled back to 8 workers/64GB
# (root cause not fully pinned down, so staying conservative here rather
# than assuming --mem=240G's larger pool obviously covers it). Submit
# gustavsnn with a matching --cpus-per-task/--mem override at the sbatch
# command line (this SBATCH-directive value stays the shared default for
# the other 4 archs).
if [ "${1:-}" == "gustavsnn" ]; then
    WORKERS=8
else
    WORKERS=64
fi
# Scoped down from the full 10,000 to fit /work's real available space
# (~1.6TB measured 2026-07-26, full 10,000-sample x 155-combo sweep
# estimated at ~2.15TB from real per-sample sizes). 4000 via
# tracegen.random_sample_indices (canonical-100 superset, seed 0,
# reproducible) estimates to ~856GB, leaving real margin. See
# log/2026-07-26-workflow-optimization-plan.md.
N_SAMPLES=4000
OUT_DIR=/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces

ARCH_FILTER="${1:?usage: sbatch run_full_sweep_array.slurm <arch>}"
JOBS_FILE=outputs/schedules/jobs.txt
if [ ! -f "$JOBS_FILE" ]; then
    echo "ERROR: $JOBS_FILE not found -- run scripts/plan_trace_shards.py first"
    exit 1
fi

LINE=$(grep "^${ARCH_FILTER}," "$JOBS_FILE" | sed -n "$((SLURM_ARRAY_TASK_ID + 1))p")
if [ -z "$LINE" ]; then
    echo "ERROR: no line $((SLURM_ARRAY_TASK_ID + 1)) for arch '$ARCH_FILTER' in $JOBS_FILE (array index out of range)"
    exit 1
fi
IFS=, read -r ARCH TRACE_DIR LAYER <<< "$LINE"
echo "=== task $SLURM_ARRAY_TASK_ID: $ARCH / $TRACE_DIR / $LAYER ==="
date

# GustavSNN used to need the tile-chunked script instead (avoiding
# re-running its expensive per-tile Python loop once per sample-worker,
# see generate_weight_traces_tile_parallel.py's docstring) -- moot now
# that GustavSNN's reconstruction runs in native C++
# (src/archmodels/gustavsnn/native/, ~10x faster, verified
# byte-identical, wired into generate_weight_traces.py's _process_chunk
# 2026-07-26): its whole per-tile loop lives in one fast subprocess call
# regardless of chunking strategy, so it uses the same sample-chunked
# script as every other arch now, and --workers still parallelizes real
# work (each worker runs its own gustavgen subprocess concurrently).
GEN_SCRIPT=scripts/generate_weight_traces.py

# `< /dev/null`: the python process below forks $WORKERS multiprocessing
# workers; piping/redirecting stdin from something that stays open for
# the shell's lifetime is a known hazard for silently hanging forked
# children (a prior job burned 6.5h/8h at 0% CPU this way -- a bare
# `while read` loop over a pipe kept its read end open as stdin for every
# forked worker to inherit). Skip-existing is on by default (no
# --force), so this naturally resumes/extends whatever sample range
# already exists at $OUT_DIR for this combo.
python3 "$GEN_SCRIPT" \
    --arch "$ARCH" --trace-dir "$TRACE_DIR" --layer "$LAYER" \
    --out-dir "$OUT_DIR" \
    --n-samples "$N_SAMPLES" --workers "$WORKERS" < /dev/null

STATUS=$?
date
if [ $STATUS -ne 0 ]; then
    echo "!!! FAILED: $ARCH/$TRACE_DIR/$LAYER (exit $STATUS)"
fi
exit $STATUS
