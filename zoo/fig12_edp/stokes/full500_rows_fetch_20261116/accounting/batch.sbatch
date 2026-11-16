#!/bin/bash
set -euo pipefail
STAGE="$HOME/snn_edp_stokes_20261114"
cd "$STAGE/neuro_cache_wcache"
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONDONTWRITEBYTECODE=1
# configure() sets shared thread caps and vendored model paths before fan-out.
exec /apps/anaconda/anaconda-2024.10/bin/conda run --no-capture-output \
    -p "$STAGE/env" python -B zoo/fig12_edp/stokes/full500_batch.py \
    --manifest "$1" --batch-index "$SLURM_ARRAY_TASK_ID"
