#!/bin/bash
#SBATCH --job-name=gustavsnn_regen
#SBATCH --partition=gpuA100x4
#SBATCH --account=bebv-delta-gpu
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#
# Detached regeneration of GustavSNN's canonical-100 weight traces (adds
# tick_ids via the new wave-derived event_to_ticks -- see
# src/archmodels/gustavsnn/address.py). Unlike LoAS/PTB/SpinalFlow/
# Prosperity, GustavSNN can't be patched in place: its tick derivation
# needs the submatrix/wave structure that only exists during
# reconstruction, not the flattened persisted address list. So this is a
# real regeneration, not a patch.
#
# A single 100-sample batch per layer is impractical: timed at >10
# minutes without completing for even the largest layer (1024 tiles).
# generate_weight_traces_canonical100.py already avoids this via its
# existing SAMPLE_CHUNK_SIZE=10 chunking and cross-layer
# ProcessPoolExecutor fan-out -- reused as-is, no new logic here.
#
# --gpus-per-node=1 is a workaround, not a real GPU need: this account
# (bebv-delta-gpu) can only submit to GPU partitions, even for CPU-only
# work (see run_full_sweep_array.slurm's identical precedent).

set -uo pipefail
cd /u/yyu9/projects/neuro_cache
source /u/yyu9/miniconda3/etc/profile.d/conda.sh
conda activate gurobi
export PYTHONPATH=src

python3 scripts/generate_weight_traces_canonical100.py gustavsnn < /dev/null
