#!/bin/bash
set -euo pipefail
STAGE="$HOME/snn_edp_stokes_20261114"
cd "$STAGE/neuro_cache_wcache"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$PWD/zoo/archx/zoo:$PWD/zoo/archx/src:$PWD/src"
/apps/anaconda/anaconda-2024.10/bin/conda run --no-capture-output -p "$STAGE/env" python -B -m snn_edp.verify > "$STAGE/full500/fixture_gate.log" 2>&1
cp zoo/archx/zoo/snn_edp/validation.json "$STAGE/full500/fixture_validation_a352ced.json"
printf '{"passed":true,"commit":"a352ced35b918fcb2e27f454d9d983c639f38739","validation":"fixture_validation_a352ced.json"}\n' > "$STAGE/full500/fixture_gate.json.part"
mv "$STAGE/full500/fixture_gate.json.part" "$STAGE/full500/fixture_gate.json"
