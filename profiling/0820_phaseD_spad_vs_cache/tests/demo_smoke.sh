#!/bin/sh
# Task 20: the local demo smoke run, checked against every known-answer test
# section 2 of the campaign plan lists as "must pass before any sweep row is
# trusted", plus the two the task brief names.
#
# The plan wrote this with `conda run -n cosa_snn python`. This machine has no
# conda and the checks need no environment beyond the standard library, so it
# runs $PYTHON (default python3), the same convention tests/test_resume.sh and
# tests/sweep_cli.sh already use.
#
# Usage: tests/demo_smoke.sh <merged-csv>
set -e
py=${PYTHON:-python3}
test -n "$1" || { echo "usage: $0 <merged-csv>"; exit 2; }

"$py" - "$1" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
assert rows, "no rows"
for r in rows:
    # 1. total_cycles exists, is positive, and is at least the oracle.
    assert int(r["total_cycles"]) >= int(r["tick_base_total"]) > 0
    assert int(r["stretch_cycles"]) == int(r["total_cycles"]) - int(r["tick_base_total"])
    # 2. V21: the stall breakdown sums.
    parts = sum(int(r[k]) for k in
                ("stall_l1_slot", "stall_l1_line", "stall_l2_slot", "stall_l2_line",
                 "stall_l1_port", "stall_l2_port", "stall_channel", "stall_barrier"))
    assert parts == int(r["stall_total"]), (parts, r["stall_total"])
    # 3. every prefetch issued ends in exactly one state, so the three outcome
    #    states and the five drop counts sum to pf_issued. The task brief wrote
    #    this as the three outcome states alone; that is a transcription slip
    #    against engine.h:195-197, which states the identity WITH the five drop
    #    counts, and the three-term version is false of a correct run: measured
    #    2026-08-20 on this grid, 254 + 114 = 368 issued (PROGRESS.md B163).
    assert (int(r["pf_timely"]) + int(r["pf_late"]) + int(r["pf_wasted"])
            + int(r["pf_dropped_array_hit"]) + int(r["pf_dropped_matching"])
            + int(r["pf_dropped_no_slot"]) + int(r["pf_dropped_targets_full"])
            + int(r["pf_dropped_reserve"])
            == int(r["pf_issued"])), r["pf_issued"]
    # 4. hidden_latency = fetch_latency - core_stall, and it is never negative (R8).
    hid = int(r["fetch_latency_sum"]) - int(r["core_stall_sum"])
    assert int(r["hidden_latency"]) == hid >= 0, (r["hidden_latency"], hid)
    # 5. at d = 0 hidden_latency is identically zero (R8, section 5.4).
    if int(r["prefetch_distance"]) == 0:
        assert int(r["hidden_latency"]) == 0, r["hidden_latency"]
    # 6. padding_fraction is a fraction, and it is a property of the LAYOUT and
    #    the trace, so every config sharing a layout and a trace reports the
    #    same value (grouped check below).
    #
    #    The plan's section 3.3 check, `padding_fraction == 0` because the
    #    chosen layers divide exactly, is NOT applied, because it is false of
    #    the column as open question Q-G defines it. Measured 2026-08-20 on the
    #    full-layer trace
    #    outputs/weight_traces/loas/resnet19_T4_all/layer_03.../sample_00000:
    #    KH=KW=3, CIN=64, COUT=128 divides exactly at every block size in the
    #    grid, all 1152 lines of the tensor are touched, and the value is
    #    0.203125 at cin_block/cout_block of 4/16, 8/8 and 16/4 alike. The
    #    cause is not the layout: 13 of the 64 input channels never spike in
    #    that sample, so 1664 of each kh,kw plane's 8192 elements are never
    #    read. Q-G's ratio therefore measures INPUT SPARSITY, or equivalently
    #    the share of each fetched line the trace never consumes, and it is 0
    #    only for a trace that touches every element of every line it pulls.
    #    The quantity section 3.3 predicts to be 0 is the layout's ceiling
    #    padding, (num_lines * elements_per_line - KH*KW*CIN*COUT) /
    #    (num_lines * elements_per_line), which is a different number and is
    #    not on the row. See PROGRESS.md decision B162.
    assert 0.0 <= float(r["padding_fraction"]) < 1.0, r["padding_fraction"]
    # 7. non_inclusive means no back-invalidation (C4's exit criterion).
    if r["inclusion"] == "non_inclusive":
        assert int(r.get("back_invalidations", 0) or 0) == 0
    # 8. the section 4.5 geometry is reconstructable from the row alone.
    assert (int(r["l1_size_bytes"]) // int(r["line_size_bytes"])
            == int(r["l1_num_lines"]))
    assert int(r["l1_num_lines"]) // int(r["l1_assoc"]) == int(r["l1_num_sets"])
# 6b. one padding_fraction per (trace, layout), whatever the cache around it.
by_layout = {}
for r in rows:
    key = (r["arch"], r["workload"], r["layer"], r["sample_idx"],
           r["cin_block"], r["cout_block"], r["weight_bytes"], r["line_size_bytes"])
    by_layout.setdefault(key, set()).add(r["padding_fraction"])
for key, values in by_layout.items():
    assert len(values) == 1, (key, sorted(values))

print(f"demo_smoke: {len(rows)} rows, {len(by_layout)} layout group(s), "
      f"every known-answer check passed")
PY
