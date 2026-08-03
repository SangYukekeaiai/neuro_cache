"""Direct check of tracegen.tick_entries_from_flat -- the transitional
adapter (log/2026-08-02-multinode-core-driven-weight-trace-plan.md,
Milestone 3) used by every arch whose main.cpp hasn't been updated to emit
tick-grouped output natively yet (ptb, gustavsnn, prosperity, spinalflow as
of this writing -- only loas's main.cpp has been updated). Not previously
covered directly: hand-made test 2 (debug/08) exercises merge_cores_by_tick
against already-grouped input, not this flat-to-grouped conversion step.

Same underlying event data as debug/08's worked example, but as the OLD
flat parallel (weight_addresses, tick_ids) arrays these 4 archs' native
binaries still emit, including GustavSNN's real case: two addresses
sharing one tick.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tracegen import CoreEntry, TickEntry, tick_entries_from_flat  # noqa: E402

WEIGHT_ADDRESSES = [
    [1, 1, 0, 0, 4],   # tick 0
    [1, 1, 1, 0, 4],   # tick 1
    [1, 1, 1, 4, 8],   # tick 1 -- same tick as the previous entry (GustavSNN case)
    [1, 1, 2, 0, 4],   # tick 3
]
TICK_IDS = [0, 1, 1, 3]


def main() -> int:
    result = tick_entries_from_flat(WEIGHT_ADDRESSES, TICK_IDS)
    expected = [
        TickEntry(0, [CoreEntry(0, [[1, 1, 0, 0, 4]])]),
        TickEntry(1, [CoreEntry(0, [[1, 1, 1, 0, 4], [1, 1, 1, 4, 8]])]),
        TickEntry(3, [CoreEntry(0, [[1, 1, 2, 0, 4]])]),
    ]

    failures = []
    if result != expected:
        failures.append(f"expected {expected}, got {result}")

    # No event created or dropped, single core throughout.
    n_in = len(WEIGHT_ADDRESSES)
    n_out = sum(len(c.weight_addresses) for t in result for c in t.cores)
    if n_in != n_out or n_out != 4:
        failures.append(f"event count mismatch: n_in={n_in}, n_out={n_out} (expected both 4)")
    if any(len(t.cores) != 1 or t.cores[0].core_id != 0 for t in result):
        failures.append("expected exactly one core (core_id=0) at every tick")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: 3 tick groups (tick 1 correctly holds 2 addresses), "
          "4 events preserved exactly, single core throughout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
