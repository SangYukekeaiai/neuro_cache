#!/bin/sh
# Task 21: the Slurm script's shape, checked without a scheduler.
set -e
f=$(dirname "$0")/../run_sweep.slurm
grep -q '^#SBATCH --time=02:00:00' "$f"
grep -q '^#SBATCH --cpus-per-task=16' "$f"
grep -q '^#SBATCH --mem=128' "$f"
grep -q '^#SBATCH --account=bebv-delta-gpu' "$f"
grep -q '^#SBATCH --partition=gpuA40x4' "$f"
grep -q '^#SBATCH --array=' "$f"
grep -q 'set -uo pipefail' "$f"
grep -q 'unit-index "\$SLURM_ARRAY_TASK_ID"' "$f"
grep -q 'run_sweep.py' "$f"
# The campaign plan's global constraint: python runs through conda, never bare.
grep -q 'conda run -n' "$f"
if grep -qE '^[[:space:]]*(python|python3) ' "$f"; then
    echo "the Slurm script must not call python directly; use conda run"; exit 1
fi
# One pipeline pair per array task: never a worker pool inside one pipeline.
grep -q -- '--workers 1' "$f"
# and it must NOT read or write an on-disk trace corpus
if grep -q 'weight_traces/' "$f"; then
    echo "the Slurm script must not reference an on-disk trace corpus"; exit 1
fi
echo "test_slurm_shape: OK"
