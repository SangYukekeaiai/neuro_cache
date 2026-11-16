#!/usr/bin/env bash
#SBATCH --job-name=eval-scaling
#SBATCH --partition=normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=outputs/slurm/es-%A_%a.out
#SBATCH --error=outputs/slurm/es-%A_%a.err
# Submit with: sbatch --array=0-$((N-1))%64 run_array.sbatch
# Case list: one "point layer" pair per line in outputs/cases.txt.
set -euo pipefail
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export LD_LIBRARY_PATH="/apps/python/python-3.11.4-gcc-12.2.0/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

REPO="$HOME/neuro_cache_wcache"
PYTHON="$REPO/.venv311/bin/python"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
ES="$REPO/zoo/eval_scaling"
TRACE_ROOT=/lustre/fs1/home/ya867177/data/input_trace_delta/B09
CASES="$ES/outputs/cases.txt"
SCRATCH="${TMPDIR:-/dev/shm}"

line=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$CASES")
point=$(echo "$line" | awk '{print $1}')
layer=$(echo "$line" | awk '{print $2}')
[[ -n "$point" && -n "$layer" ]] || { echo "bad case line $SLURM_ARRAY_TASK_ID"; exit 2; }

exec "$PYTHON" "$ES/run_case.py" --repo "$REPO" --trace-root "$TRACE_ROOT" \
  --point "$point" --layer "$layer" --samples 0 --sample-count 10 \
  --scratch "$SCRATCH" --out "$ES/outputs/s4/${point}_${layer}.csv"
