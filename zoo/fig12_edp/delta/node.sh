#!/bin/bash
set -euo pipefail
ROOT=$1
SAMPLE=$2
REPO=$(pwd)
shift 2
mkdir -p "$ROOT/build" "$ROOT/logs"
python -B zoo/fig12_edp/delta/native_build.py --root "$ROOT"
exec python -B zoo/fig12_edp/delta/run_node.py --root "$ROOT" --sample "$SAMPLE" "$@"
