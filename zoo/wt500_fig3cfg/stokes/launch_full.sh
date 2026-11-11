#!/bin/bash
# Launch the full WT500 weighted-shard campaign on Stokes.
# Run on a Stokes login node:  bash zoo/wt500_fig3cfg/stokes/launch_full.sh
# Idempotent: re-running regenerates case files and submits a new array;
# cancel the old array first (scancel --name=wt500-traces).
set -euo pipefail
# Stokes login nodes have RLIMIT_NPROC=100; uncapped BLAS threads SIGABRT.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

REPO="$HOME/neuro_cache_wcache"
PYTHON="$REPO/.venv311/bin/python"
TRACE_ROOT=/lustre/fs1/home/ya867177/data/input_trace_delta
SCHEDULE_CACHE="$REPO/zoo/wt500_fig3cfg/outputs/schedules"
CASE_DIR="$REPO/zoo/wt500_fig3cfg/outputs/slurm/cases_weighted"
RUN_ROOT="$REPO/zoo/wt500_fig3cfg/outputs/slurm/runs_full"
# ponytail: flat 7-day limit for every shard; weights span 76,000x, so split
# a per-shard --time out of estimated_records if queue turnaround matters.
TIME_LIMIT="${TIME_LIMIT:-7-00:00:00}"
CPUS="${CPUS:-4}"

cd "$REPO"
mkdir -p "$RUN_ROOT"
"$PYTHON" zoo/wt500_fig3cfg/slurm/shard_cases.py \
  --shards-file zoo/wt500_fig3cfg/stokes/shards/shards.csv \
  --output-dir "$CASE_DIR" --shard-root "$RUN_ROOT" --cpus "$CPUS" \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"

n=$(ls "$CASE_DIR"/cases_*.json | wc -l)
echo "submitting array 0-$((n - 1)) with --time=$TIME_LIMIT --cpus-per-task=$CPUS"
sbatch --partition=normal --time="$TIME_LIMIT" --cpus-per-task="$CPUS" \
  --array="0-$((n - 1))" \
  --output "$RUN_ROOT/slurm-%A_%a.out" --error "$RUN_ROOT/slurm-%A_%a.err" \
  "$REPO/zoo/wt500_fig3cfg/slurm/run_array.sbatch" \
  --case-dir "$CASE_DIR" --shard-root "$RUN_ROOT" \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"
