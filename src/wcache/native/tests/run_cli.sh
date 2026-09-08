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
# every other one of the 111 columns matches, which is what §10.6's replay
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

# 3. The row's arity matches the header's, and both are the pinned 111.
#
# 91 and not 90: `stall_l1_port` was added, which is the bucket V21's partition
# was missing. The 91 the plan's prose used to assert was an unrelated
# arithmetic error against a 90-entry list. 111 since the L2 neighbour
# prefetcher joined it, adding five `l2_prefetch_*` knobs and thirteen
# `l2_pf_*` counters to the 93 that `layout` and `cin_lo_blocks` had brought
# it to; `layout` is there because a run that swaps the address mapper must
# say which one it swapped to.
"$py" - "$tmp/a.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
assert len(rows) == 2, rows
assert len(rows[0]) == len(rows[1]) == 111, (len(rows[0]), len(rows[1]))
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
#
# A reserve AT the file it reserves from, which is refused on the same rule the
# L1 uses: it would make prefetching unreachable while claiming to be on. A bare
# `l2_demand_reserve` is no longer the example, because the knob went live with
# the L2 neighbour prefetcher and a plain value of 4 now loads and runs.
cat > "$tmp/bad.json" <<'JSON'
{"l2_demand_reserve": 20, "l2_mshrs": 20}
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

# 8. W4's equivalence gate: the layout knob reaches the mapper, and what it
#    changes is placement and nothing else.
#
# ptb_resnet19 rather than the loas slice this script otherwise uses, because
# loas re-references almost nothing (1 hit in 384) and a layout that changes
# where lines go cannot show on a trace with no reuse. The L1 is squeezed to
# 16 lines over 8 sets so conflicts, and therefore placement, decide the run.
#
# The two halves of the gate pull in opposite directions on purpose:
#   dram_bytes IDENTICAL  -- the same lines are fetched, so the layout is a
#                            relabelling and not a different working set
#   l1_hits    DIFFERENT  -- the labels land in different sets, which is the
#                            only thing this change was supposed to do
#
# The dram_bytes half holds HERE and is not a general law, which W5 found the
# hard way. The relabelling preserves the SET of lines, so DRAM traffic is
# invariant only while the L2 never has to evict. This fixture's whole layer is
# 2,304 lines against a 524,288-byte 16-way L2, so it fits many times over and
# the equality is exact. On a layer whose working set exceeds the L2, the two
# layouts hand the L2 different reuse distances, it evicts different lines, and
# dram_bytes moves: measured on V8 at 4.32 MB under block_pack against 6.40 MB
# under split_cin. Sizing this L2 down until the layer stopped fitting would
# turn this check red without anything being wrong, so it stays large.
"$py" "$root/src/wcache/examples/to_stream.py" \
    "$root/src/wcache/examples/ptb_resnet19_layer01_v2.json" > "$tmp/reuse.wcts"
for layout in block_pack split_cin; do
    cat > "$tmp/lay.json" <<JSON
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 256, "l1_assoc": 2, "l2_size_bytes": 524288, "l2_assoc": 16,
 "layout": "$layout"}
JSON
    "$bin" --config "$tmp/lay.json" --trace "$tmp/reuse.wcts" --run-id fixed --header \
        > "$tmp/$layout.csv"
done
"$py" - "$tmp/block_pack.csv" "$tmp/split_cin.csv" <<'GATE'
import csv, sys
a, b = [dict(zip(*list(csv.reader(open(f))))) for f in sys.argv[1:]]
assert a["layout"] == "block_pack" and b["layout"] == "split_cin", (a["layout"], b["layout"])
assert a["cin_lo_blocks"] == "-1", a["cin_lo_blocks"]
assert b["cin_lo_blocks"] == b["l1_num_sets"], (b["cin_lo_blocks"], b["l1_num_sets"])
assert a["dram_bytes"] == b["dram_bytes"], (a["dram_bytes"], b["dram_bytes"])
assert a["dram_accesses"] == b["dram_accesses"], (a["dram_accesses"], b["dram_accesses"])
assert a["l1_accesses"] == b["l1_accesses"], (a["l1_accesses"], b["l1_accesses"])
assert a["l1_hits"] != b["l1_hits"], "the layout knob did not reach the mapper"
print(f"layout gate: dram_bytes {a['dram_bytes']} both, "
      f"l1_hits {a['l1_hits']} -> {b['l1_hits']}")
GATE

# 9. Belady at BOTH levels, in two passes, which is the only way an offline
#    policy can be run: pass 1 writes the access log, pass 2 turns it into one
#    oracle per core for the private L1s plus one shared oracle for the L2.
#
# The squeezed L1 of section 8 is reused rather than the loas slice, and for the
# same reason: with a cache large enough to hold the layer nothing is ever
# evicted, so an optimal replacement policy and LRU produce the identical row
# and the check would pass on a broken oracle.
#
# Pass 1 is run under `lru`. Any non-belady policy would do, because a core's L1
# demand stream is a pure function of the trace, the core and the mapper, and
# `lru` is the arm the belady number is compared against anyway.
cat > "$tmp/tight.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 256, "l1_assoc": 2, "l2_size_bytes": 4096, "l2_assoc": 4}
JSON
sed -e 's/{/{"policy": "belady", /' "$tmp/tight.json" > "$tmp/tight_belady.json"

"$bin" --config "$tmp/tight.json" --trace "$tmp/reuse.wcts" --run-id fixed --header \
       --access-log "$tmp/access.bin" > "$tmp/lru.csv"
"$bin" --config "$tmp/tight_belady.json" --trace "$tmp/reuse.wcts" --run-id fixed --header \
       --oracle "$tmp/access.bin" > "$tmp/belady.csv" 2> "$tmp/belady.err"

# The L1 oracles are EXACT, so their overrun count is 0 and not merely small: an
# overrun means pass 2 asked for a reference pass 1 never logged, which for a
# private L1 can only mean the two passes disagree about the stream.
grep -q "oracle overruns, l1 0," "$tmp/belady.err"

"$py" - "$tmp/lru.csv" "$tmp/belady.csv" <<'BELPY'
import csv, sys
lru, bel = [dict(zip(*list(csv.reader(open(f))))) for f in sys.argv[1:]]
assert lru["policy"] == "lru" and bel["policy"] == "belady", (lru["policy"], bel["policy"])
# The demand stream does not depend on the policy, which is the assumption the
# whole two-pass scheme rests on, so this equality is the scheme's own check.
assert lru["l1_accesses"] == bel["l1_accesses"], (lru["l1_accesses"], bel["l1_accesses"])
# Nothing blocked, so no request re-triaged and no occurrence was counted twice.
assert bel["max_wait_depth"] == "0", bel["max_wait_depth"]
# An optimal policy cannot lose to LRU on the same geometry, and here it wins,
# so the oracle is reaching the L1 rather than being carried along inertly.
assert int(bel["l1_hits"]) > int(lru["l1_hits"]), (lru["l1_hits"], bel["l1_hits"])
assert int(bel["l2_hits"]) > int(lru["l2_hits"]), (lru["l2_hits"], bel["l2_hits"])
print(f"belady: l1_hits {lru['l1_hits']} -> {bel['l1_hits']}, "
      f"l2_hits {lru['l2_hits']} -> {bel['l2_hits']}")
BELPY

# 10. The same config with no oracle is refused rather than run. A silent
#     fallback would report an every-slot-looks-dead policy as Belady's bound.
if "$bin" --config "$tmp/tight_belady.json" --trace "$tmp/reuse.wcts" \
        2> "$tmp/no_oracle.txt"; then
    echo "expected a nonzero exit for policy = belady with no --oracle"; exit 1
fi
grep -q -- "--oracle" "$tmp/no_oracle.txt"

echo "run_cli: OK"
