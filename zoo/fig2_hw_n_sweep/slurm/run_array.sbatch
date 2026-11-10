#!/usr/bin/env bash
#SBATCH --job-name=fig2-hw-n
#SBATCH --partition=normal
#SBATCH --time=90:00
#SBATCH --array=0-0%1
#SBATCH --cpus-per-task=1
#SBATCH --output=/lustre/fs1/home/ya867177/projects/neuro_cache_wcache/zoo/fig2_hw_n_sweep/outputs/slurm/runs/slurm-%A_%a.out
#SBATCH --error=/lustre/fs1/home/ya867177/projects/neuro_cache_wcache/zoo/fig2_hw_n_sweep/outputs/slurm/runs/slurm-%A_%a.err

set -euo pipefail

REPO_DEFAULT=/lustre/fs1/home/ya867177/projects/neuro_cache_wcache
PYTHON_DEFAULT=/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python
CASE_DIR="$REPO_DEFAULT/zoo/fig2_hw_n_sweep/outputs/slurm/cases"
SHARD_ROOT="$REPO_DEFAULT/zoo/fig2_hw_n_sweep/outputs/slurm/runs"
REPO="$REPO_DEFAULT"
PYTHON="$PYTHON_DEFAULT"
BATCH_ARGS=()

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
        --batch-samples)
            BATCH_ARGS+=(--batch-samples)
            shift
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

task_index=$((10#${SLURM_ARRAY_TASK_ID}))
task_tag=$(printf '%04d' "$task_index")
CASE_DIR=$(realpath "$CASE_DIR")
SHARD_ROOT=$(realpath -m "$SHARD_ROOT")
SHARD_DIR="$SHARD_ROOT/shard_$task_tag"
CASE_FILE="$CASE_DIR/cases_$task_tag.json"
if [[ ! -f "$CASE_FILE" ]]; then
    echo "missing case file: $CASE_FILE" >&2
    exit 2
fi
mkdir -p "$SHARD_DIR"
exec >"$SHARD_DIR/slurm.log" 2>&1

cd "$REPO"
jobs=${SLURM_CPUS_PER_TASK:-1}
echo "task=$task_index cpus=$jobs case_file=$CASE_FILE shard_dir=$SHARD_DIR"
exec env PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" \
    "$REPO/zoo/fig2_hw_n_sweep/run.py" \
    --case-file "$CASE_FILE" \
    --output-dir "$SHARD_DIR" \
    --results-suffix "_$task_tag" \
    --no-summary \
    "${BATCH_ARGS[@]}" \
    --jobs "$jobs"
