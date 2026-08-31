#!/bin/sh
# Task 18: wcache_sweep end to end over one pass of one stream.
#
# The stream is the same checked-in fixture slice Task 15's run_cli.sh uses,
# written by `examples/to_stream.py`, so this test needs no corpus and no Delta.
#
# What it is here to prove is D3's exit criterion in miniature: a grid point
# run inside a sweep must produce the same row it produces when it is run
# alone by wcache_run, over a single pass of the stream.
set -e
root=$(cd "$(dirname "$0")/../../../.." && pwd)
native=$root/src/wcache/native
sweep=$native/build/fixture/wcache_sweep
run=$native/build/fixture/wcache_run
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

"$py" "$root/src/wcache/examples/to_stream.py" \
    "$root/src/wcache/examples/loas_vgg16_layer01_v2.json" > "$tmp/fixture.wcts"

# A four-point grid: two L1 sizes crossed with two prefetch distances. The
# first declared axis varies slowest, so the rows come out
# (2048,2) (2048,4) (8192,2) (8192,4).
#
# The plan's own axis is `prefetch_distance` and it is swept here. Distance 0 is
# not one of the points: `prefetch_policy = next_burst` with distance 0 is
# refused at config load rather than silently run as `none`, and the no-prefetch
# case is what tests/run_cli.sh already covers.
cat > "$tmp/grid.json" <<'JSON'
{"base": {"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
          "l1_assoc": 8, "l2_size_bytes": 524288, "l2_assoc": 16,
          "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100,
          "prefetch_policy": "next_burst"},
 "axes": {"l1_size_bytes": [2048, 8192],
          "prefetch_distance": [2, 4]}}
JSON

"$sweep" --config-grid "$tmp/grid.json" --trace "$tmp/fixture.wcts" \
         --run-id fixed --tier smoke --hist "$tmp/hist.csv" \
         --progress > "$tmp/sweep.csv" 2> "$tmp/progress.txt" || { cat "$tmp/progress.txt"; exit 1; }

# 1. A header and one row per grid point, every row the pinned 93 columns.
#
# 91 and not 90: `stall_l1_port` was added, which is the bucket V21's partition
# was missing. The 91 the plan's prose used to assert was an unrelated
# arithmetic error against a 90-entry list. 93 since `layout` and
# `cin_lo_blocks` joined it: a run that swaps the address mapper must say
# which one it swapped to.
"$py" - "$tmp/sweep.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
assert len(rows) == 5, len(rows)
assert all(len(r) == 93 for r in rows), [len(r) for r in rows]
head = rows[0]
data = [dict(zip(head, r)) for r in rows[1:]]
assert [(r["l1_size_bytes"], r["prefetch_distance"]) for r in data] == \
       [("2048", "2"), ("2048", "4"), ("8192", "2"), ("8192", "4")], data
assert len({r["run_id"] for r in data}) == 1, "one sweep, one run id"
for r in data:
    # The stall breakdown closes, exactly. `stall_l1_port` is the bucket that
    # makes it close on a prefetching grid: a prefetch turns a miss into an L1
    # array hit, and that hit still queues on the L1 port.
    causes = ["stall_l1_slot", "stall_l1_line", "stall_l1_port", "stall_l2_slot",
              "stall_l2_line", "stall_l2_port", "stall_channel", "stall_barrier"]
    assert sum(int(r[c]) for c in causes) == int(r["stall_total"]), r
    # The four prefetch outcomes plus the five drop reasons account for every
    # issued prefetch, and this grid really prefetches, so it is not vacuous.
    outcomes = ["pf_timely", "pf_late", "pf_wasted", "pf_dropped_array_hit",
                "pf_dropped_matching", "pf_dropped_no_slot", "pf_dropped_targets_full",
                "pf_dropped_reserve"]
    assert int(r["pf_issued"]) > 0, r
    assert sum(int(r[c]) for c in outcomes) == int(r["pf_issued"]), r
    # A cache cannot beat a scratchpad that never misses.
    assert int(r["total_cycles"]) >= int(r["tick_base_total"]), r
    assert int(r["tick_base_total"]) == 48, r
    assert r["tier"] == "smoke" and r["arm"] == "cache", r
print(f"sweep: {len(data)} rows, {len(head)} columns")
PY

# 2. --progress reports one line per tile, on stderr, out of the CSV's way.
test "$(wc -l < "$tmp/progress.txt")" -eq 2

# 3. The histogram is a property of the trace, so it is written ONCE per sweep
#    and not once per grid point: 1 header + 2 tiles * 8 cores.
test "$(wc -l < "$tmp/hist.csv")" -eq 17

# 4. D3's exit criterion in miniature. The third grid point, run alone by
#    wcache_run, must give the same row it gave inside the sweep.
#
# `run_id` is pinned on both sides and `sim_wall_seconds` is excluded BY NAME,
# because those two cannot be equal across two runs by construction: one
# defaults to a fresh UUIDv4 and the other is wall clock. Every other one of
# the 93 columns must match exactly.
cat > "$tmp/point.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_assoc": 8, "l2_size_bytes": 524288, "l2_assoc": 16,
 "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100,
 "prefetch_policy": "next_burst",
 "l1_size_bytes": 8192, "prefetch_distance": 2}
JSON
"$run" --config "$tmp/point.json" --trace "$tmp/fixture.wcts" \
       --run-id fixed --tier smoke --header > "$tmp/point.csv"

"$py" - "$tmp/sweep.csv" "$tmp/point.csv" <<'PY'
import csv, sys
sweep = list(csv.reader(open(sys.argv[1])))
point = list(csv.reader(open(sys.argv[2])))
assert sweep[0] == point[0], "the two header lines differ"
head = sweep[0]
want = dict(zip(head, point[1]))
got = [r for r in sweep[1:]
       if dict(zip(head, r))["l1_size_bytes"] == want["l1_size_bytes"]
       and dict(zip(head, r))["prefetch_distance"] == want["prefetch_distance"]]
assert len(got) == 1, got
differ = [(c, a, b) for c, a, b in zip(head, got[0], point[1]) if a != b]
assert [c for c, _, _ in differ] in ([], ["sim_wall_seconds"]), differ
print(f"sweep row == run row: identical on {len(head) - len(differ)} of {len(head)} columns")
PY

# 5. A grid whose points do not share one layout is refused at startup, with
#    the reason and the offending point named. One mapper serves the whole
#    sweep, so a line size sweep is one sweep per line size.
cat > "$tmp/mixed.json" <<'JSON'
{"base": {"cout_block": 16}, "axes": {"cin_block": [1, 2]}}
JSON
if "$sweep" --config-grid "$tmp/mixed.json" --trace "$tmp/fixture.wcts" 2> "$tmp/mixed.txt"; then
    echo "expected a nonzero exit for a mixed-layout grid"; exit 1
fi
grep -q "configuration 1" "$tmp/mixed.txt"

# 6. --max-engines refuses an oversized grid before a single engine is built.
if "$sweep" --config-grid "$tmp/grid.json" --trace "$tmp/fixture.wcts" \
            --max-engines 3 2> "$tmp/cap.txt"; then
    echo "expected a nonzero exit for a grid over --max-engines"; exit 1
fi
grep -q "max-engines\|live engines" "$tmp/cap.txt"

# 7. A bad flag is a usage error, exit 2, as in wcache_run.
if "$sweep" --config-grid "$tmp/grid.json" --trace "$tmp/fixture.wcts" --nonsense \
        2> "$tmp/usage.txt"; then
    echo "expected a nonzero exit for an unknown flag"; exit 1
else
    test "$?" -eq 2 || { echo "expected exit 2 for an unknown flag, got $?"; exit 1; }
fi
grep -q -- --nonsense "$tmp/usage.txt"

# 8. The padding meter actually runs, and its value survives the sweep.
#
# Added 2026-08-20 after deleting `padding.observe_tile(window);` survived the
# whole gate. It survived for a reason worth keeping in the file: every grid
# above uses `cin_block = 1`, where a line is exactly one burst wide and the
# true padding_fraction is 0.000000, so a meter that never observes a tile
# reports the same number a correct one does. The check needs a layout where
# the answer is not also the failure value, and `cin_block = 4` is one: four
# COUT-16 bursts share each 64-element line, and the fixture touches only some
# of them.
cat > "$tmp/pad_grid.json" <<'JSON'
[{"cin_block": 4, "cout_block": 16, "weight_bytes": 1,
  "l1_assoc": 8, "l2_size_bytes": 524288, "l2_assoc": 16,
  "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100,
  "l1_size_bytes": 2048}]
JSON
"$sweep" --config-grid "$tmp/pad_grid.json" --trace "$tmp/fixture.wcts" \
         --run-id fixed --tier smoke --header > "$tmp/pad_sweep.csv"
# wcache_run takes ONE configuration object; wcache_sweep takes the array.
sed -e 's/^\[//' -e 's/\]$//' "$tmp/pad_grid.json" > "$tmp/pad_point.json"
"$run" --config "$tmp/pad_point.json" --trace "$tmp/fixture.wcts" \
       --run-id fixed --tier smoke --header > "$tmp/pad_run.csv"

"$py" - "$tmp/pad_sweep.csv" "$tmp/pad_run.csv" <<'PADPY'
import csv, sys
sweep = list(csv.DictReader(open(sys.argv[1])))
run = list(csv.DictReader(open(sys.argv[2])))
assert len(sweep) == len(run) == 1, (len(sweep), len(run))
pad = float(sweep[0]["padding_fraction"])
# Not merely nonzero: the exact value, so a meter that observes the wrong thing
# is caught too. 64 lines touched at 64 elements each and 1872 distinct elements
# give 0.54296875, which the CSV writes to six places as 0.542969.
assert abs(pad - 0.542969) < 1e-6, pad
assert sweep[0]["padding_fraction"] == run[0]["padding_fraction"], \
    (sweep[0]["padding_fraction"], run[0]["padding_fraction"])
print(f"padding meter: {pad} in the sweep and in the single run alike")
PADPY

echo "sweep_cli: OK"
