#!/bin/bash
# Runs one (trace_dir, layer, combo_tag) for loas's node32kb sweep subset,
# 5 samples, into outputs/weight_traces/loas/<combo_tag>/<trace_dir>/<layer>/.
# Lives under scripts/tmp/ (not /tmp) -- see run_combo.sh's comment.
set -u
trace_dir="$1"
layer="$2"
combo_tag="$3"
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/scripts/env.sh"
cd "$root" || exit 1
source ~/miniconda3/etc/profile.d/conda.sh
conda activate "$CONDA_ENV"
log="scripts/tmp/logs_loas_sweep/${trace_dir}_${layer}_${combo_tag}.log"
python scripts/generate_weight_traces.py \
  --arch loas --trace-dir "$trace_dir" --layer "$layer" \
  --schedule-cache "outputs/schedules/multinode_sweep/${combo_tag}" \
  --out-dir "$NEURO_CACHE_DATA/neuro_cache_outputs/weight_traces" \
  --combo-tag "$combo_tag" \
  --sample-start 0 --sample-count 5 --workers 1 \
  > "$log" 2>&1
echo "loas $trace_dir $layer $combo_tag exit=$?"
