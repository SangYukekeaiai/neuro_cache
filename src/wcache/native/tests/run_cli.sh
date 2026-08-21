#!/bin/sh
# Task 15: wcache_run end to end over a stream produced by the Python writer.
#
# The stream comes from `examples/to_stream.py`, which is the one place the
# fixture-to-WCTS conversion is written, applied to a checked-in fixture slice,
# so this test needs no corpus and no Delta.
set -e
root=$(cd "$(dirname "$0")/../../../.." && pwd)
native=$root/src/wcache/native
bin=$native/build/fixture/wcache_run
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

"$py" "$root/src/wcache/examples/to_stream.py" \
    "$root/src/wcache/examples/loas_vgg16_layer01_v2.json" > "$tmp/fixture.wcts"

cat > "$tmp/cfg.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 8192, "l1_assoc": 8,
 "l2_size_bytes": 524288, "l2_assoc": 16,
 "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100}
JSON

# 1. A path trace, header plus one row.
"$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" --run-id fixed --header > "$tmp/a.csv"
test "$(wc -l < "$tmp/a.csv")" -eq 2

# 2. The same trace on stdin gives the same row.
#
# The plan asked for `cmp a.csv b.csv` on two default invocations. That cannot
# hold and the fixture is rebuilt here: `run_id` defaults to a fresh UUIDv4 and
# `sim_wall_seconds` is wall-clock, so two runs of one binary over one stream
# differ in those two cells by design. Pinning --run-id removes the first, and
# the comparison below excludes `sim_wall_seconds` BY NAME and asserts that
# every other one of the 91 columns matches, which is what §10.6's replay
# contract actually claims.
"$bin" --config "$tmp/cfg.json" --trace - --run-id fixed --header < "$tmp/fixture.wcts" > "$tmp/b.csv"
"$py" - "$tmp/a.csv" "$tmp/b.csv" <<'PY'
import csv, sys
a = list(csv.reader(open(sys.argv[1])))
b = list(csv.reader(open(sys.argv[2])))
assert a[0] == b[0], "the two header lines differ"
differ = [(c, x, y) for c, x, y in zip(a[0], a[1], b[1]) if x != y]
assert [c for c, _, _ in differ] in ([], ["sim_wall_seconds"]), differ
print(f"path vs stdin: {len(a[0]) - len(differ)} of {len(a[0])} columns identical")
PY

# 3. The row's arity matches the header's, and both are the pinned 91.
#
# 91 and not 90: `stall_l1_port` was added, which is the bucket V21's partition
# was missing. The 91 the plan's prose used to assert was an unrelated
# arithmetic error against a 90-entry list; the list itself has 91 entries now.
"$py" - "$tmp/a.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
assert len(rows) == 2, rows
assert len(rows[0]) == len(rows[1]) == 91, (len(rows[0]), len(rows[1]))
row = dict(zip(rows[0], rows[1]))
assert int(row["total_cycles"]) > 0
assert int(row["l1_accesses"]) > 0
assert float(row["padding_fraction"]) == 0.0, row["padding_fraction"]
assert row["arch"] == "loas" and row["n_cores"] == "8", row
print("wcache_run: OK")
PY

# 4. The oracle arm needs no engine and reproduces tick_base.
"$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" \
       --oracle-only --arm spad_oracle --header > "$tmp/o.csv"
"$py" - "$tmp/o.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
row = dict(zip(rows[0], rows[1]))
assert row["arm"] == "spad_oracle"
assert row["total_cycles"] == row["tick_base_total"] == "48", row["total_cycles"]  # 24 + 24
assert row["l1_hits"] == ""
print("oracle arm: OK")
PY

# 5. A rejected config exits nonzero and names the knob.
cat > "$tmp/bad.json" <<'JSON'
{"l2_demand_reserve": 4}
JSON
if "$bin" --config "$tmp/bad.json" --trace "$tmp/fixture.wcts" 2> "$tmp/err.txt"; then
    echo "expected a nonzero exit for l2_demand_reserve"; exit 1
fi
grep -q l2_demand_reserve "$tmp/err.txt"

# 6. A bad flag is a usage error, exit 2, and says so on stderr.
if "$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" --nonsense 2> "$tmp/usage.txt"; then
    echo "expected a nonzero exit for an unknown flag"; exit 1
else
    test "$?" -eq 2 || { echo "expected exit 2 for an unknown flag, got $?"; exit 1; }
fi
grep -q -- --nonsense "$tmp/usage.txt"

# 7. --hist writes the G14 sidecar for every (core, tile) of the slice.
"$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" --run-id fixed \
       --hist "$tmp/hist.csv" > /dev/null
test "$(wc -l < "$tmp/hist.csv")" -eq 17   # 1 header + 2 tiles * 8 cores

echo "run_cli: OK"
