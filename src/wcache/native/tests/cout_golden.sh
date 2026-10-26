#!/bin/sh
# 5d: a COUT stream from the WCTS v2 writer must give the same wcache CSV, bit
# for bit, as the v1 reader gave on the same stream.
#
# tests/cout_golden.csv was captured from the pre-5d (v1) wcache_sweep fed this
# same to_stream.py output with its format_version byte set back to 1. A v2
# COUT record equals the v1 record, so only git_commit and sim_wall_seconds,
# which name the build and the wall clock, may differ.
set -e
root=$(cd "$(dirname "$0")/../../../.." && pwd)
native=$root/src/wcache/native
sweep=$native/build/fixture/wcache_sweep
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

"$py" "$root/src/wcache/examples/to_stream.py" \
    "$root/src/wcache/examples/loas_vgg16_layer01_v2.json" > "$tmp/fixture.wcts"

# Four runs: L1 2048 and 8192 bytes, each without and with next_burst prefetch.
"$py" - > "$tmp/grid.json" <<'PY'
import json
base = {"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
        "l1_assoc": 8, "l2_size_bytes": 524288, "l2_assoc": 16,
        "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100}
print(json.dumps([dict(base, l1_size_bytes=l1, **pf)
                  for l1 in (2048, 8192)
                  for pf in ({}, {"prefetch_policy": "next_burst", "prefetch_distance": 2})]))
PY

"$sweep" --config-grid "$tmp/grid.json" --trace "$tmp/fixture.wcts" \
         --run-id fixed --tier smoke > "$tmp/sweep.csv"

"$py" - "$tmp/fixture.wcts" "$tmp/sweep.csv" "$native/tests/cout_golden.csv" <<'PY'
import csv, struct, sys
version = struct.unpack_from("<I", open(sys.argv[1], "rb").read(12), 8)[0]
assert version == 2, f"to_stream.py wrote format_version {version}, expected 2"

def rows(path):
    table = list(csv.reader(open(path)))
    keep = [i for i, name in enumerate(table[0]) if name not in ("git_commit", "sim_wall_seconds")]
    assert len(keep) == len(table[0]) - 2, "git_commit or sim_wall_seconds column missing"
    return [[r[i] for i in keep] for r in table]

got, want = rows(sys.argv[2]), rows(sys.argv[3])
assert len(got) == len(want), f"{len(got)} rows, golden has {len(want)}"
for n, (g, w) in enumerate(zip(got, want)):
    diff = [(want[0][i], w[i], g[i]) for i in range(len(w)) if g[i] != w[i]]
    assert g == w, f"row {n} differs from the golden (column, golden, now): {diff[:5]}"
PY
echo "cout_golden: OK"
