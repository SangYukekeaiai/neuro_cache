#!/bin/sh
# Task 16: invariant V1 end to end, producer -> pipe -> wcache_run.
#
# Unbounded cache, l1_latency = 0 -> tile_origin[N] == tick_base[N] EXACTLY,
# for every tile. v3 :1380, and section 2's "known-answer check 1".
#
# The stream comes from `examples/to_stream.py`, so this runs the producer, the
# wire format, the reader, the engine and the CSV in one go, on the checked-in
# fixture slices, with no corpus and no Delta.
#
# Three things are checked per fixture:
#   1. V1 on the whole two-tile slice: total_cycles == tick_base_total.
#   2. V1 on a one-tile prefix, which is tile_origin[1] against tick_base[1].
#      Together with 1 that pins every tile boundary of these slices, so no
#      compensating pair of errors passes.
#   3. V27, the exact-drift companion: l1_latency = 1 stretches the makespan by
#      exactly 48 cycles, both tiles' drift accumulating into tile_origin[2].
#
# Then the same V1 check is pointed at a deliberately broken run and REQUIRED to
# fail. A green check that cannot go red proves nothing, and that is what this
# last part is here to keep true.
set -e
root=$(cd "$(dirname "$0")/../../../.." && pwd)
native=$root/src/wcache/native
bin=$native/build/fixture/wcache_run
py=${PYTHON:-python3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# The unbounded baseline: ii = 0 never delays, every latency 0, and a cache
# large enough that nothing is ever evicted.
cat > "$tmp/unbounded.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 16777216, "l1_assoc": 8,
 "l2_size_bytes": 16777216, "l2_assoc": 16,
 "l1_latency": 0, "l1_ii": 0,
 "l2_latency": 0, "l2_to_l1_latency": 0, "l2_miss_latency": 0,
 "l2_ii": 0, "dram_ii": 0, "l2_banks": 1,
 "l1_mshrs": 64, "l1_tgts_per_mshr": 64,
 "l2_mshrs": 64, "l2_tgts_per_mshr": 64,
 "core_accept_ii": 1, "prefetch_policy": "none", "prefetch_distance": 0}
JSON

# The same baseline with one cycle of L1 hit latency: the V27 drift case.
sed 's/"l1_latency": 0/"l1_latency": 1/' "$tmp/unbounded.json" > "$tmp/latency1.json"

# A 128-byte L1 with real L2 latencies: the deliberately broken case below.
cat > "$tmp/tiny_l1.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 128, "l1_assoc": 1,
 "l2_size_bytes": 524288, "l2_assoc": 16,
 "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100}
JSON

# The one check, used by both the green cases and the red ones. Exits 1 naming
# the columns that disagree.
cat > "$tmp/check_v1.py" <<'PY'
import csv, sys

path, label = sys.argv[1], sys.argv[2]
rows = list(csv.reader(open(path)))
row = dict(zip(rows[0], rows[1]))
total, base, stretch = (row["total_cycles"], row["tick_base_total"],
                        row["stretch_cycles"])
if total != base or stretch != "0":
    sys.exit(f"V1 VIOLATED on {label}: total_cycles {total} != tick_base_total "
             f"{base}, stretch_cycles {stretch}")
print(f"V1 exact on {label}: total_cycles == tick_base_total == {total}")
PY

# `expect` is the whole slice, `expect1` the one-tile prefix.
check() {  # fixture expect expect1
    "$py" "$root/src/wcache/examples/to_stream.py" \
        "$root/src/wcache/examples/$1.json" 2>/dev/null > "$tmp/$1.wcts"
    "$bin" --config "$tmp/unbounded.json" --trace - --header \
        < "$tmp/$1.wcts" 2>/dev/null > "$tmp/$1.csv"
    "$py" "$tmp/check_v1.py" "$tmp/$1.csv" "$1"
    grep -q ",$2,$2,0," "$tmp/$1.csv" ||
        { echo "$1: expected total_cycles $2" >&2; exit 1; }

    "$py" "$root/src/wcache/examples/to_stream.py" \
        "$root/src/wcache/examples/$1.json" 1 2>/dev/null > "$tmp/$1.1.wcts"
    "$bin" --config "$tmp/unbounded.json" --trace - --header \
        < "$tmp/$1.1.wcts" 2>/dev/null > "$tmp/$1.1.csv"
    "$py" "$tmp/check_v1.py" "$tmp/$1.1.csv" "$1 tile 0 only"
    grep -q ",$3,$3,0," "$tmp/$1.1.csv" ||
        { echo "$1: expected one-tile total_cycles $3" >&2; exit 1; }

    # V27: one cycle of L1 latency drifts every burst, and both tiles' drift
    # lands in tile_origin[2], so the makespan grows by 48 on every fixture.
    "$bin" --config "$tmp/latency1.json" --trace "$tmp/$1.wcts" --header \
        2>/dev/null > "$tmp/$1.lat1.csv"
    grep -q ",$2,48," "$tmp/$1.lat1.csv" ||
        { echo "$1: expected stretch_cycles 48 at l1_latency 1" >&2; exit 1; }
    echo "V27 exact on $1: stretch_cycles == 48 at l1_latency 1"
}

check loas_vgg16_layer01_v2       48 24
check ptb_resnet19_layer01_v2     88 44
check spinalflow_vgg16_layer01_v2 48 24
check prosperity_vgg16_layer01_v2 48 24

# Non-vacuity. Two perturbations that V1 must catch, run through the same
# check_v1.py the green cases just passed.
echo "--- the check must go red on a broken run ---"
red() {  # config label
    "$bin" --config "$1" --trace "$tmp/loas_vgg16_layer01_v2.wcts" --header \
        2>/dev/null > "$tmp/red.csv"
    if "$py" "$tmp/check_v1.py" "$tmp/red.csv" "$2"; then
        echo "v1_pipe: FAIL, the V1 check passed a run it must reject ($2)" >&2
        exit 1
    fi
}
red "$tmp/latency1.json" "loas, l1_latency 1"
red "$tmp/tiny_l1.json"  "loas, 128-byte L1"

echo "v1_pipe: OK"
