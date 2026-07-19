#!/bin/bash
#SBATCH --job-name=weight_trace_gen
#SBATCH --partition=ghx4
#SBATCH --account=bebv-dtai-gh
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=288
#SBATCH --mem=350G
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

# Full-node core count (confirmed via `scontrol show node`: CPUTot=288,
# RealMemory=488000MB per ghx4 node) rather than half. Billing is
# max(GPUs requested, cores/72, memory/110) GH200-equivalents
# (.../job-accounting.html): 288/72 = 4 GH200-equivalents/hour, i.e. the
# full node's rate -- same as requesting all 4 GPUs explicitly. Total SU
# cost for a fixed amount of work is roughly invariant to this choice
# (more GH200-equivalents/hour x proportionally fewer hours needed), so
# this trades a higher hourly rate for finishing in less wall-clock time,
# which matters more here since the real per-sample cost (measured
# against real captured data, not the synthetic sparsity used to
# benchmark reconstruct_tile_sequence_batch) turned out higher than
# estimated -- the original 144-core/8h budget would not have finished
# the full sweep.

# NOT set -e: a single combo's failure (e.g. the disk-quota crash that
# killed job 2681186 partway through) must not abort the whole 155-combo
# sweep -- log it and move on to the next combo instead.
set -uo pipefail
cd /u/yyu9/projects/neuro_cache

export GRB_LICENSE_FILE=/u/yyu9/gurobi.lic
export PYTHONPATH=src
WORKERS=288
SAMPLES=1000
# Scoped to 1000 samples/layer (not the full 10,000) per the real-data-
# calibrated estimate: ~457 CPU-hours / ~6.4 SU-hours total for this scope,
# vs ~4572 CPU-hours / ~63.5 SU-hours (essentially the entire remaining
# balance) for the full 10,000. Skip-existing means this is safe to bump
# up later (e.g. re-run with SAMPLES=5000) without redoing anything
# already generated -- only the new sample indices get computed.

# Moved off /u/yyu9 (home quota is only 103GB hard limit; job 2681186 hit
# it after 3 layers -- weight_traces alone was already 54GB uncompressed).
# /projects/bebv is the persistent group allocation (550GB hard limit,
# ~372GB headroom) -- with gzip compression (verified 19.5x smaller on
# real data), the full 1000-sample/155-combo scope needs ~26GB, comfortably
# within it.
OUT_DIR=/projects/bebv/yyu9/neuro_cache_outputs/weight_traces

# Loop over every successfully-solved (arch, trace_dir, layer) from Stage 1's
# real summary.csv -- no need to hardcode the 155-combo list separately.
#
# Process substitution (< <(...)), not a pipe (tail ... | while ...): the
# python subprocess below forks 144 workers via multiprocessing.Pool, which
# inherit the parent's file descriptors including stdin. Piping into a
# `while read` loop keeps that pipe's read end open as the loop's own
# stdin for its entire lifetime; 144 forked children inheriting a
# reference to it is a well-known bash hazard that silently hangs the
# whole thing (confirmed: this is exactly what happened on job 2679580,
# 6.5h/8h burned with 0% CPU and zero output -- isolated tests of the
# python script itself, at the same worker count and on the same layer,
# completed in 14s). `< /dev/null` on the inner command is a second,
# redundant layer of the same fix, in case anything else in the
# conda/python startup chain ever touches stdin.
while IFS=, read -r arch trace_dir layer status dram_num_steps error; do
    if [ "$status" != "OK" ]; then
        continue
    fi
    echo "=== $arch / $trace_dir / $layer ==="
    conda run -n base python3 scripts/generate_weight_traces.py \
        --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
        --out-dir "$OUT_DIR" \
        --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS" < /dev/null \
        || echo "!!! FAILED: $arch/$trace_dir/$layer (exit $?) -- continuing to next combo"
done < <(tail -n +2 outputs/schedules/summary.csv)
