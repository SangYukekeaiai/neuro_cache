#!/bin/sh
# W0: the 4 layers x 5 samples of WCTS the Stage 4 cache study replays.
#
# Same interpreter, same flags and the same input_trace/schedules trees Stage 2
# used, so sample 0 comes out byte-identical to the file Stage 2 left behind.
# That equality is the whole point of regenerating a file we already have: it
# proves this script is the same generator, and therefore that samples 1..4,
# which no earlier stage produced, are trustworthy.
#
# --dump-trace takes ONE sample per invocation, so this is 20 runs. Each is
# 10 to 40 seconds, well inside the login node's per-process CPU cap.
set -e
root=$(cd "$(dirname "$0")/../../../.." && pwd)
py=${PYTHON:-/u/yyu9/miniconda3/bin/python}
stage2=$root/profiling/0823_stagewise_verify/stage2_weight_trace
out=$root/profiling/0823_stagewise_verify/stage4_wcache/inputs/streams
mkdir -p "$out"

# tag  trace_dir          layer
set -- \
    "V8  vgg16_T4_n5      layer_08_features_27" \
    "V9  vgg16_T4_n5      layer_09_features_30" \
    "R9  resnet19_T4_n5   layer_09_layer2_0_conv2" \
    "R16 resnet19_T4_n5   layer_16_layer3_0_conv2"

for spec in "$@"; do
    # shellcheck disable=SC2086
    set -- $spec
    tag=$1; dir=$2; layer=$3
    s=0
    while [ "$s" -lt 5 ]; do
        dst="$out/${tag}_s0000${s}.wcts"
        if [ -f "$dst" ]; then
            echo "have  $tag sample $s"
        else
            echo "gen   $tag sample $s"
            "$py" "$root/scripts/generate_weight_traces.py" \
                --arch loas \
                --trace-root "$stage2/inputs/input_trace" \
                --trace-dir "$dir" --layer "$layer" \
                --schedule-cache "$stage2/inputs/schedules" \
                --workers 1 --stream --sample-start "$s" --sample-count 1 \
                --dump-trace "$dst" > /dev/null
        fi
        s=$((s + 1))
    done
done

echo "--- sample 0 must be byte-identical to Stage 2's own dumps ---"
cmp "$out/V8_s00000.wcts"  "$stage2/outputs/stream/layer_08_features_27_s00000.wcts"
cmp "$out/V9_s00000.wcts"  "$stage2/outputs/stream/layer_09_features_30_s00000.wcts"
cmp "$out/R9_s00000.wcts"  "$stage2/outputs/stream/layer_09_layer2_0_conv2_s00000.wcts"
cmp "$out/R16_s00000.wcts" "$stage2/outputs/stream/layer_16_layer3_0_conv2_s00000.wcts"
echo "gen_streams: OK, sample 0 reproduces Stage 2 byte for byte"
