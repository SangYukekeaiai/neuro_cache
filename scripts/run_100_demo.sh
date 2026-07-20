#!/bin/bash
# 100-sample demo run for ONE arch, all its (trace_dir, layer) combos,
# sequentially per-combo (each combo internally parallel via --workers).
# Meant to be launched once per arch, in parallel with the other archs'
# invocations, each on a slice of this node's 144 cores.
#
# Usage: run_100_demo.sh <arch> <out_dir> <workers>
set -uo pipefail
cd /u/yyu9/projects/neuro_cache
ARCH="$1"
OUT_DIR="$2"
WORKERS="$3"
SAMPLES=100

while IFS=, read -r arch trace_dir layer status dram_num_steps error; do
    if [ "$arch" != "$ARCH" ] || [ "$status" != "OK" ]; then
        continue
    fi
    echo "=== $arch / $trace_dir / $layer ==="
    conda run -n base python3 scripts/generate_weight_traces.py \
        --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
        --out-dir "$OUT_DIR" \
        --sample-start 0 --sample-count "$SAMPLES" --workers "$WORKERS" < /dev/null \
        || echo "!!! FAILED: $arch/$trace_dir/$layer (exit $?) -- continuing to next combo"
done < <(tail -n +2 outputs/schedules/summary.csv)

echo "=== $ARCH 100-sample demo run complete ==="
