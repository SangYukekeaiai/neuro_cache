#!/bin/sh
# Task 20 step 4: the prefetch-distance duplicate check, section 2's
# known-answer check 6.
#
# What the campaign plan predicted, and what this script does NOT assert: that
# a distance above the L1 prefetch budget is inert, so d = 16 reproduces
# d = 15. Measured 2026-08-20, it does not: see grids/duplicate_check.json and
# PROGRESS.md B164. The budget bounds prefetches in flight, the distance bounds
# the prefetch cursor's lead over the demand cursor, and a completed prefetch
# still counts toward the lead while holding no MSHR.
#
# What it asserts instead, all three measured on this grid:
#   1. the budget binds exactly where predicted: pf_budget_exhausted is 0 at
#      d = 15 and nonzero at d = 16;
#   2. d = 16 is NOT a duplicate of d = 15, which is the finding itself;
#   3. duplicates begin at the per-core per-tile burst count, 24 here: d = 32
#      reproduces d = 24 byte for byte.
#
# Usage: tests/duplicate_check.sh [csv]   (default dup.csv beside this tree)
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
py=${PYTHON:-python3}
csv=${1:-$here/dup.csv}

"$py" - "$csv" <<'PY'
import csv, sys
rows = {int(r["prefetch_distance"]): r for r in csv.DictReader(open(sys.argv[1]))}
missing = {15, 16, 24, 32} - set(rows)
assert not missing, f"grid is missing prefetch distances {sorted(missing)}"
ignore = {"run_id", "sim_wall_seconds", "prefetch_distance", "events_per_cycle"}

def differs(a, b):
    return {k for k in rows[a] if k not in ignore and rows[a][k] != rows[b][k]}

# 1. the budget binds at 16, which is l1_mshrs - l1_demand_reserve + 1.
assert int(rows[15]["pf_budget_exhausted"]) == 0, rows[15]["pf_budget_exhausted"]
assert int(rows[16]["pf_budget_exhausted"]) > 0, rows[16]["pf_budget_exhausted"]

# 2. and binding it is not the same as making the distance inert.
assert differs(15, 16), "d=16 reproduced d=15: the finding in B164 has reversed"

# 3. the real duplicate point: one core's bursts in one tile, 24 on this fixture.
extra = differs(24, 32)
assert not extra, f"d=32 does not reproduce d=24: {sorted(extra)}"

print("duplicate check: budget binds at d=16, d=16 differs from d=15, "
      "and d=32 reproduces d=24 exactly")
PY
