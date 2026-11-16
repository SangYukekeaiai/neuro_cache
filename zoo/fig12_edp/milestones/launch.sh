#!/bin/bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
CONDA=/u/yyu9/miniconda3/bin/conda
ROOT=$("$CONDA" run --no-capture-output -n fig12-archx python -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$HERE/config.json")
mkdir -p "$ROOT"
if [[ ${1:-} != --inside ]]; then
    tmux new-session -d -s fig12-partial100 "bash '$HERE/launch.sh' --inside"
    exit
fi
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR="$ROOT/mplconfig"
exec systemd-run --user --scope -p MemoryMax=4G -p TasksMax=32 \
    "$CONDA" run --no-capture-output -n fig12-archx python -B "$HERE/watch.py" \
    --config "$HERE/config.json" >> "$ROOT/watch.log" 2>&1
