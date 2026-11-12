#!/bin/bash
#SBATCH --job-name=wt500-pilot-l1
#SBATCH --partition=normal
#SBATCH --time=8:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=60G
#SBATCH --nodes=1
# L1-size pilot: loas / B09 loas_vgg16_T4_n500, all layers, samples 0-9,
# cachesim arm=cache under l1_8k.json vs l1_16k.json. Streams one wcts per
# (layer, sample) into shm, simulates both configs, deletes the wcts.
set -euo pipefail
export TMPDIR=/dev/shm
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export LD_LIBRARY_PATH="/apps/python/python-3.11.4-gcc-12.2.0/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
REPO=$HOME/neuro_cache_wcache
PY=$REPO/.venv311/bin/python
PILOT=$REPO/zoo/wt500_fig3cfg/stokes/pilot_l1
OUT=$REPO/zoo/wt500_fig3cfg/outputs/pilot_l1
TRACE_ROOT=/lustre/fs1/home/ya867177/data/input_trace_delta/B09
TRACE_DIR=loas_vgg16_T4_n500
SCHED=$REPO/zoo/wt500_fig3cfg/outputs/schedules
BIN=$REPO/src/lays/cachesim/native/build/release/cachesim_run
JOBS=${SLURM_CPUS_PER_TASK:-4}

# A Delta-built binary rsynced into the tree fails here with GLIBC version
# errors, so test by running it, not by -x.
if ! "$BIN" --help >/dev/null 2>&1 && ! "$BIN" 2>&1 | grep -q "cachesim_run"; then
  echo "rebuilding cachesim natives locally (g++: $(g++ --version | head -1))"
  # newer toolchain if the default g++ is too old for the sources
  command -v module >/dev/null && module load gcc 2>/dev/null || true
  make -B -C "$REPO/src/lays/cachesim/native" MODE=release apps
fi
mkdir -p "$OUT/rows"
WCTS=$(mktemp -d)
trap 'rm -rf "$WCTS"' EXIT

layers=$(PYTHONPATH=$REPO/src "$PY" - <<EOF
import json
m = json.load(open("$REPO/zoo/wt500_fig3cfg/outputs/slurm/cases_weighted/manifest.json"))
print("\n".join(sorted({c[2] for c in m["combos"] if c[0] == "loas" and c[1] == "$TRACE_DIR"})))
EOF
)
echo "layers:"; echo "$layers"

for layer in $layers; do
  # stream the 10 samples (4 at a time), then simulate both configs
  for s in $(seq 0 9); do
    echo "$layer $s"
  done | xargs -P "$JOBS" -n 2 sh -c '
    set -e
    layer=$0; s=$1
    out="'"$WCTS"'/${layer}_s${s}.wcts"
    [ -s "$out" ] || PYTHONPATH='"$REPO"'/src '"$PY"' -m lays.weight_trace_gen gen \
      --arch loas --trace-root '"$TRACE_ROOT"' --trace-dir '"$TRACE_DIR"' \
      --layer "$layer" --schedule-cache '"$SCHED"' \
      --stream --sample-start "$s" --sample-count 1 --dump-trace "$out" >/dev/null
    for cfg in l1_8k l1_16k; do
      '"$BIN"' --config '"$PILOT"'/$cfg.json --trace "$out" --arm cache \
        --tier "$cfg" --run-id "pilot-$cfg-$layer-s$s" --header \
        --out "'"$OUT"'/rows/${cfg}__${layer}__s${s}.csv"
    done
    rm -f "$out"
  '
done

# merge: one CSV, config/layer/sample prefixed
merged=$OUT/pilot_l1_results.csv
first=1
for f in "$OUT"/rows/*.csv; do
  base=$(basename "$f" .csv)
  cfg=${base%%__*}; rest=${base#*__}; layer=${rest%%__*}; s=${rest##*__s}
  if [ $first -eq 1 ]; then
    echo "config,layer,sample,$(head -1 "$f")" > "$merged"; first=0
  fi
  tail -n +2 "$f" | sed "s/^/$cfg,$layer,$s,/" >> "$merged"
done
echo "merged -> $merged ($(wc -l < "$merged") lines)"
