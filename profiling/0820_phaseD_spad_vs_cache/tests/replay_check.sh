#!/bin/sh
# Open question Q-I: D3's "reproduces byte-identically" exit criterion, read by
# the implementation plan as satisfied by the dump-and-replay path.
#
# That reading had no test. Two halves existed and the composite did not:
#   tests/test_stream_dump.py and tests/test_stream_flag.sh prove the --dump-trace
#     tee is a byte-identical prefix of what the consumer saw;
#   src/wcache/native/tests/run_cli.sh proves a file replay and a stdin run of the
#     same bytes agree on every column but sim_wall_seconds.
# Neither one dumps a stream and replays THAT through the consumer, which is the
# claim Q-I actually makes. This script does.
#
# Scope, stated rather than implied: the producer here is run_sweep.py's fixture
# emitter, the same one the demo grid uses, not scripts/generate_weight_traces.py.
# The generator half needs the trace corpus, a solved schedule and the cosa_snn
# conda environment, none of which exist on this machine (ruling R7), and it is
# covered by tests/test_stream_flag.sh where they do.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
root=$(cd "$here/../.." && pwd)
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

sweep=""
for mode in release fixture; do
    if [ -x "$root/src/wcache/native/build/$mode/wcache_sweep" ]; then
        sweep="$root/src/wcache/native/build/$mode/wcache_sweep"; break
    fi
done
test -n "$sweep" || { echo "no wcache_sweep built; run make apps"; exit 2; }

# The grid is the demo grid, expanded by the driver's own code so the two never
# drift apart.
PYTHONPATH="$here" "$py" - "$here/grids/demo.json" "$tmp/grid.json" <<'PY'
import json, sys, importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "run_sweep", pathlib.Path(sys.argv[1]).parent.parent / "run_sweep.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
doc = mod.load_grid(pathlib.Path(sys.argv[1]))
pathlib.Path(sys.argv[2]).write_text(json.dumps(mod.expand_configs(doc)))
PY

fixture=loas_vgg16_layer01_v2

# 1. The dump: one pass of the producer captured to a file.
"$py" "$here/run_sweep.py" --emit-fixture-stream "$fixture" > "$tmp/dump.wcts"
test -s "$tmp/dump.wcts"

# 2. Replay the dump from the file.
"$sweep" --config-grid "$tmp/grid.json" --trace "$tmp/dump.wcts" \
         --run-id fixed --arm cache --tier replay --out "$tmp/replay.csv" 2>/dev/null

# 3. The live pipe, producer straight into the consumer, no file in between.
"$py" "$here/run_sweep.py" --emit-fixture-stream "$fixture" \
  | "$sweep" --config-grid "$tmp/grid.json" --trace - \
             --run-id fixed --arm cache --tier replay --out "$tmp/live.csv" 2>/dev/null

# 4. Every column but the wall clock agrees, on every row.
"$py" - "$tmp/replay.csv" "$tmp/live.csv" <<'PY'
import csv, sys
a = list(csv.reader(open(sys.argv[1])))
b = list(csv.reader(open(sys.argv[2])))
assert a[0] == b[0], "the two header lines differ"
assert len(a) == len(b) > 1, (len(a), len(b))
names = a[0]
bad = []
for i, (ra, rb) in enumerate(zip(a[1:], b[1:])):
    for c, x, y in zip(names, ra, rb):
        if x != y and c != "sim_wall_seconds":
            bad.append((i, c, x, y))
assert not bad, bad
print(f"replay: {len(a) - 1} rows, {len(names) - 1} of {len(names)} columns "
      f"identical between the dumped replay and the live pipe")
PY
echo "replay_check: OK"
