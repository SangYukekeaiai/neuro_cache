#!/usr/bin/env bash
#SBATCH --job-name=wt500-cachesim
#SBATCH --partition=normal
#SBATCH --time=7-00:00:00
#SBATCH --array=0-136%137
#SBATCH --cpus-per-task=4
# Set the wave-specific memory grant at submission time with `sbatch --mem=...`.
#SBATCH --output=sim-%A_%a.out
#SBATCH --error=sim-%A_%a.err

set -euo pipefail

REPO="${REPO:-$PWD}"
PYTHON="${PYTHON:-python3}"
SHARD_ROOT="${SHARD_ROOT:-}"
CONFIG="${SIM_CONFIG:-}"

while (($#)); do
    case "$1" in
        --repo) REPO=$2; shift 2 ;;
        --python) PYTHON=$2; shift 2 ;;
        --shard-root) SHARD_ROOT=$2; shift 2 ;;
        --config) CONFIG=$2; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$SHARD_ROOT" || -z "$CONFIG" ]]; then
    echo 'sim_shard.sbatch requires --shard-root and --config (or SHARD_ROOT and SIM_CONFIG)' >&2
    exit 2
fi
if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
    echo 'sim_shard.sbatch requires an array task (SLURM_ARRAY_TASK_ID)' >&2
    exit 2
fi

REPO=$(realpath "$REPO")
SHARD_ROOT=$(realpath -m "$SHARD_ROOT")
CONFIG=$(realpath "$CONFIG")
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
task_index=$((10#${SLURM_ARRAY_TASK_ID}))
task_tag=$(printf '%04d' "$task_index")
SHARD_DIR="$SHARD_ROOT/shard_$task_tag"
NATIVE="$REPO/src/lays/cachesim/native"
BINARY="$NATIVE/build/release/cachesim_run"
STAMP="$NATIVE/build/release/.cachesim_run.stamp"
LOCK="$STAMP.lock"

mkdir -p "$(dirname "$STAMP")"
if ! command -v flock >/dev/null 2>&1; then
    echo 'sim_shard.sbatch requires flock to guard the shared native build' >&2
    exit 2
fi
exec 9>"$LOCK"
flock 9
needs_build=0
if [[ ! -x "$BINARY" || ! -f "$STAMP" ]]; then
    needs_build=1
else
    newer=$(find "$NATIVE/src" "$NATIVE/include" "$NATIVE/apps" \
        -type f -newer "$STAMP" -print -quit)
    [[ -n "$newer" ]] && needs_build=1
fi
if ((needs_build)); then
    make -C "$NATIVE" MODE=release -j4 apps
    touch "$STAMP"
fi

exec env PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" "$REPO/zoo/wt500_fig3cfg/stokes/sim_shard.py" \
    --shard-dir "$SHARD_DIR" --config "$CONFIG" --binary "$BINARY" \
    --workers "${SLURM_CPUS_PER_TASK:-4}"
