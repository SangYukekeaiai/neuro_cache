#!/bin/bash
set -euo pipefail
STAGE="$HOME/snn_edp_stokes_20261114"
cd "$STAGE/neuro_cache_wcache"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec /apps/anaconda/anaconda-2024.10/bin/conda run --no-capture-output -p "$STAGE/env" python -B zoo/fig12_edp/stokes/full500.py --root "$STAGE/full500" >> "$STAGE/full500/driver.log" 2>&1
