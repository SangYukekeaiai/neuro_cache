#!/bin/bash
# Runs one (arch, trace_dir, layer) combo, 5 samples, into outputs/weight_traces.
# Called via xargs -P for parallelism across the 155-combo baseline grid.
# Lives under scripts/tmp/ (not /tmp) because it must be visible from the
# srun-allocated compute node, not just the login node -- /tmp is
# node-local, this project directory is on shared storage.
set -u
arch="$1"
trace_dir="$2"
layer="$3"
cd /u/yyu9/projects/neuro_cache || exit 1
source ~/miniconda3/etc/profile.d/conda.sh
conda activate base
export PYTHONPATH=src
log="scripts/tmp/logs_baseline/${arch}_${trace_dir}_${layer}.log"
python scripts/generate_weight_traces.py \
  --arch "$arch" --trace-dir "$trace_dir" --layer "$layer" \
  --schedule-cache outputs/schedules/multinode \
  --out-dir outputs/weight_traces \
  --sample-start 0 --sample-count 5 --workers 1 \
  > "$log" 2>&1
echo "$arch $trace_dir $layer exit=$?"
