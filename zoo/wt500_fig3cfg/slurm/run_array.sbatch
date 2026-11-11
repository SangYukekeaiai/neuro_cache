#!/usr/bin/env bash
#SBATCH --job-name=wt500-traces
#SBATCH --partition=normal
#SBATCH --time=90:00
#SBATCH --array=0-0%1
#SBATCH --cpus-per-task=1
#SBATCH --output=slurm-%A_%a.out
#SBATCH --error=slurm-%A_%a.err

set -euo pipefail

# No cluster-specific absolute paths belong here.  The printed command from
# shard_cases.py supplies these roots (or the caller's shell variables).
CASE_DIR=""
SHARD_ROOT=""
REPO="${REPO:-$PWD}"
PYTHON="${PYTHON:-python}"
TRACE_ROOT=""
SCHEDULE_CACHE=""

if [[ "${1:-}" == "--" ]]; then
    shift
fi
while (($#)); do
    case "$1" in
        --case-dir)
            CASE_DIR=$2
            shift 2
            ;;
        --shard-root)
            SHARD_ROOT=$2
            shift 2
            ;;
        --repo)
            REPO=$2
            shift 2
            ;;
        --python)
            PYTHON=$2
            shift 2
            ;;
        --trace-root)
            TRACE_ROOT=$2
            shift 2
            ;;
        --schedule-cache)
            SCHEDULE_CACHE=$2
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
    echo 'run_array.sbatch requires an array task (SLURM_ARRAY_TASK_ID)' >&2
    exit 2
fi
if [[ -z "$CASE_DIR" || -z "$SHARD_ROOT" || -z "$TRACE_ROOT" || -z "$SCHEDULE_CACHE" ]]; then
    echo 'run_array.sbatch requires --case-dir, --shard-root, --trace-root, and --schedule-cache' >&2
    exit 2
fi

task_index=$((10#${SLURM_ARRAY_TASK_ID}))
task_tag=$(printf '%04d' "$task_index")
CASE_DIR=$(realpath "$CASE_DIR")
SHARD_ROOT=$(realpath -m "$SHARD_ROOT")
REPO=$(realpath "$REPO")
TRACE_ROOT=$(realpath "$TRACE_ROOT")
SCHEDULE_CACHE=$(realpath "$SCHEDULE_CACHE")
SHARD_DIR="$SHARD_ROOT/shard_$task_tag"
CASE_FILE="$CASE_DIR/cases_$task_tag.json"
if [[ ! -f "$CASE_FILE" ]]; then
    echo "missing case file: $CASE_FILE" >&2
    exit 2
fi
mkdir -p "$SHARD_DIR"
exec >"$SHARD_DIR/slurm.log" 2>&1

jobs=${SLURM_CPUS_PER_TASK:-1}
echo "task=$task_index cpus=$jobs case_file=$CASE_FILE shard_dir=$SHARD_DIR"
exec env PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" \
    "$REPO/zoo/wt500_fig3cfg/slurm/harness.py" run-shard \
    --case-file "$CASE_FILE" \
    --shard-dir "$SHARD_DIR" \
    --repo "$REPO" \
    --python "$PYTHON" \
    --trace-root "$TRACE_ROOT" \
    --schedule-cache "$SCHEDULE_CACHE" \
    --workers "$jobs"
