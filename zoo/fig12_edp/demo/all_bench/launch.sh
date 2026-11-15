#!/usr/bin/env bash
set -euo pipefail
all_bench_dir=$(cd -- "$(dirname -- "$0")" && pwd)
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR="$all_bench_dir/mplconfig"
export TMPDIR="$all_bench_dir/tmp"
mkdir -p "$TMPDIR"
# A dedicated scope bounds aggregate resident memory, CPU and PIDs; workers also cap address space.
exec setsid -w systemd-run --user --scope -q \
    --unit="fig12-t84-$(date +%s)" \
    -p OOMPolicy=continue -p MemoryMax=24G -p MemorySwapMax=0 \
    -p TasksMax=64 -p CPUQuota=200% \
    bash -c '
        set -euo pipefail
        ulimit -v 56623104
        conda run --no-capture-output -n fig12-archx python -B "$1/run.py" --run --workers 2
        conda run --no-capture-output -n gurobi python -B "$1/plot.py"
    ' bash "$all_bench_dir"
