#!/bin/sh
# Task 19: the per-unit cache is atomic and resume is exact.
#
# The plan wrote this with `conda run -n cosa_snn python`. This machine has no
# conda and the driver needs no environment, so it runs $PYTHON (default
# python3), the same convention tests/sweep_cli.sh already uses.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# 1. The preview runs without --run and writes nothing.
"$py" "$here/run_sweep.py" --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" > "$tmp/preview.txt"
test ! -d "$tmp/results"
grep -q "units" "$tmp/preview.txt"

# 2. A full run produces one file per unit.
"$py" "$here/run_sweep.py" --run --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
units=$("$py" "$here/run_sweep.py" --dry-run-units \
        --grid "$here/grids/demo.json" | wc -l)
test "$(ls "$tmp/results/demo" | wc -l)" -eq "$units"

# 3. Deleting one unit file and rerunning regenerates ONLY that one.
first=$(ls "$tmp/results/demo" | head -1)
cp "$tmp/results/demo/$first" "$tmp/gold.csv"
touch -d '2000-01-01' "$tmp/results/demo"/*
rm "$tmp/results/demo/$first"
"$py" "$here/run_sweep.py" --run --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
# only the regenerated file has a new mtime
test "$(find "$tmp/results/demo" -type f -newermt '2001-01-01' | wc -l)" -eq 1
# 4. and it is byte-identical to the first run, ignoring run_id and wall time.
"$py" - "$tmp/gold.csv" "$tmp/results/demo/$first" <<'PY'
import csv, sys
def norm(p):
    rows = list(csv.reader(open(p)))
    head = rows[0]
    drop = {head.index("run_id"), head.index("sim_wall_seconds")}
    return [[c for i, c in enumerate(r) if i not in drop] for r in rows]
a, b = norm(sys.argv[1]), norm(sys.argv[2])
assert a == b, "resume is not byte-identical"
print("resume: byte-identical")
PY

# 5. --merge-only produces the merged CSV and validates the row count.
rm -f "$tmp/out.csv"
"$py" "$here/run_sweep.py" --merge-only \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
test -s "$tmp/out.csv"
echo "test_resume: OK"
