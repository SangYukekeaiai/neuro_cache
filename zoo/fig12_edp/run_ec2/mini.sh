#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
exec setsid -w systemd-run --user --scope -q --unit="fig12-t71-mini-$(date +%s)" \
  -p OOMPolicy=continue -p MemoryMax=4G -p MemorySwapMax=0 -p TasksMax=32 -p CPUQuota=100% \
  conda run --no-capture-output -n fig12-archx python -B "$here/run.py" --config "$here/mini.json"
