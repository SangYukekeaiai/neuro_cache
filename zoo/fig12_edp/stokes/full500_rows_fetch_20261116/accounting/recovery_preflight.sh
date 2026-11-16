#!/bin/bash
set -euo pipefail
STAGE="$HOME/snn_edp_stokes_20261114"
cd "$STAGE/neuro_cache_wcache"
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
export PYTHONPATH="$PWD:$PWD/src:$PWD/zoo/archx/zoo:$PWD/zoo/archx/src"
sha256sum -c "$STAGE/logs/native_sha256.txt" > "$STAGE/full500/recovery_glibc_20261115/native_hash_audit.log"
zoo/fig12_edp/demo/native_build/cachesim_run --help > "$STAGE/full500/recovery_glibc_20261115/demo_native_help.log" 2>&1
/apps/anaconda/anaconda-2024.10/bin/conda run --no-capture-output -p "$STAGE/env" python -B -m pytest -q zoo/fig12_edp/demo/test_cache_configs.py::test_both_configs_in_native_simulator zoo/fig12_edp/demo/test_cache_configs.py::test_production_configs_are_byte_pinned > "$STAGE/full500/recovery_glibc_20261115/native_tests.log" 2>&1
bash "$STAGE/full500/fixture_gate.sh"
printf '{"passed":true,"binary_sha256":"2500622500c8c8af98ae2a7cba7edfff86e9a63e04a008cabc7dda2372a4ebb2"}\n' > "$STAGE/full500/recovery_glibc_20261115/preflight.json"
tmux new-session -d -s full500 "bash $STAGE/full500/driver.sh"
