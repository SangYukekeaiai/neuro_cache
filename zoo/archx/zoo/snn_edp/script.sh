#!/usr/bin/env bash
# Run with an activated Python environment containing archx.
set -euo pipefail
model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$(dirname -- "$model_dir")"
export PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1
exec "${PYTHON:-python}" -B -m snn_edp.example "$@"
