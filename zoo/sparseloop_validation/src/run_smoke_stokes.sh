#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
module load anaconda/anaconda-2024.10 gcc/gcc-9.1.0
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export LD_LIBRARY_PATH="$root/vendor/paper_backend/timeloop/build:$root/vendor/envs/tlv/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR="$root/outputs/tmp" XDG_CACHE_HOME="$root/outputs/cache"
conda run --no-capture-output -p "$root/vendor/envs/tlv" python -B src/verify_inputs.py > outputs/remote_ingest_verification.json
conda run --no-capture-output -p "$root/vendor/envs/tlv" python -B src/smoke_stokes.py
conda list -p "$root/vendor/envs/tlv" --explicit > outputs/conda_explicit.txt
