#!/usr/bin/env bash
# AWS driver: one case-list row per GNU-parallel job, one simulator thread per case.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=${REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}
ES="$REPO/zoo/eval_scaling"
CASES=${CASES:-"$ES/outputs/cases.txt"}
TRACE_ROOT=${TRACE_ROOT:-/work/nvme/bebv/yyu9/input_trace_delta/B09}
PYTHON=${PYTHON:-python}
JOBS=${JOBS:-$(nproc)}
SCRATCH=${SCRATCH:-${TMPDIR:-/dev/shm}}

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

run_one() {
    local point=$1
    local layer=$2
    local out_dir="$ES/outputs/s4"
    if [[ "$point" == *_cache_x* ]]; then
        out_dir="$ES/outputs/s4c"
    fi
    mkdir -p "$out_dir"
    "$PYTHON" "$ES/run_case.py" \
        --repo "$REPO" \
        --trace-root "$TRACE_ROOT" \
        --point "$point" \
        --layer "$layer" \
        --samples 0 \
        --sample-count 10 \
        --scratch "$SCRATCH" \
        --out "$out_dir/${point}_${layer}.csv"
}

export -f run_one
export ES REPO TRACE_ROOT PYTHON SCRATCH
command -v parallel >/dev/null
parallel --will-cite -j "$JOBS" --colsep ' ' run_one {1} {2} :::: "$CASES"
