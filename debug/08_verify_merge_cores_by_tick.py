"""Hand-made test 2 (log/2026-08-02-multinode-core-driven-weight-trace-plan.md):
tracegen.merge_cores_by_tick against the concrete worked example from
planning -- 2 cores, one (dram_i, noc_i) tile, real [kh,kw,cin,cs,ce] event
tuples. Core 0 fetches at ticks 0,1,1,3 (two fetches share tick 1); core 1
fetches at ticks 0,2 and finishes before core 0 (no tick-3 entry).
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tracegen import CoreEntry, merge_cores_by_tick  # noqa: E402

CORE_RESULTS = {
    0: {"ticks": [
        {"tick": 0, "weight_addresses": [[1, 1, 0, 0, 4]]},
        {"tick": 1, "weight_addresses": [[1, 1, 1, 0, 4], [1, 1, 1, 4, 8]]},
        {"tick": 3, "weight_addresses": [[1, 1, 2, 0, 4]]},
    ]},
    1: {"ticks": [
        {"tick": 0, "weight_addresses": [[1, 1, 0, 4, 8]]},
        {"tick": 2, "weight_addresses": [[1, 1, 2, 4, 8]]},
    ]},
}


def main() -> int:
    result = merge_cores_by_tick(CORE_RESULTS)
    failures = []

    got_ticks = [t.tick for t in result]
    if got_ticks != [0, 1, 2, 3]:
        failures.append(f"expected ticks [0,1,2,3] in order, got {got_ticks}")

    expected_cores = {
        0: [CoreEntry(0, [[1, 1, 0, 0, 4]]), CoreEntry(1, [[1, 1, 0, 4, 8]])],
        1: [CoreEntry(0, [[1, 1, 1, 0, 4], [1, 1, 1, 4, 8]])],
        2: [CoreEntry(1, [[1, 1, 2, 4, 8]])],
        3: [CoreEntry(0, [[1, 1, 2, 0, 4]])],
    }
    by_tick = {t.tick: t.cores for t in result}
    for tick, expected in expected_cores.items():
        got = by_tick.get(tick)
        if got != expected:
            failures.append(f"tick={tick}: expected {expected}, got {got}")

    # Absent-core check: tick 2 and tick 3 must have exactly one core entry
    # each (the other core finished early), not a padded empty CoreEntry.
    if len(by_tick.get(2, [])) != 1:
        failures.append(f"tick=2: expected exactly 1 core entry (core 0 absent), got {len(by_tick.get(2, []))}")
    if len(by_tick.get(3, [])) != 1:
        failures.append(f"tick=3: expected exactly 1 core entry (core 1 absent), got {len(by_tick.get(3, []))}")

    # No event created or dropped by the reshape.
    n_in = sum(len(r["weight_addresses"]) for tile in CORE_RESULTS.values() for r in tile["ticks"])
    n_out = sum(len(c.weight_addresses) for t in result for c in t.cores)
    if n_in != n_out or n_in != 6:
        failures.append(f"event count mismatch: n_in={n_in}, n_out={n_out} (expected both 6)")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASS: 4 ticks, {n_out} events preserved exactly, "
          f"absent cores omitted (not padded) at ticks 2 and 3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
