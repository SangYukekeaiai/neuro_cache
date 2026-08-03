"""Hand-made test 4 (log/2026-08-02-multinode-core-driven-weight-trace-plan.md):
iter_node_tiles must use the COMBINED si.k_position(dram_i, noc_i), not the
DRAM-only si.dram_k_position(dram_i) the original single-node-only code
used -- the two coincide only when NoC-temporal loops are empty (true for
every single-node schedule, false the moment K is a NoC-temporal dim).

Fixture: CIN (a K-dim) total = 2, split as a 2-step NoC-temporal loop (no
DRAM-temporal split at all, dram_num_steps=1). Hand-derived expectation:
is_last_K must be False at noc_i=0 and True at noc_i=1. The old DRAM-only
check would see no CIN loop at all (CIN never appears in
dram_temporal_loops here) and trivially report is_last_K=True at every
step, silently wrong at noc_i=0.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from nocsim.schedule.decode import LoopItem, Schedule  # noqa: E402
from nocsim.schedule.steps import StepInfo  # noqa: E402
from nocsim.schedule.tiles import iter_node_tiles  # noqa: E402
from parsers.layer import DIM_CIN  # noqa: E402

_PROB_FACTORS = [[], [], [2], [], [], [], []]  # CIN (index 2) = 2, everything else = 1


class _FakeProb:
    def __init__(self, prob_factors):
        self.prob_factors = prob_factors


def main() -> int:
    prob = _FakeProb(_PROB_FACTORS)
    schedule = Schedule(
        spatial_factors={},
        noc_temporal_loops=[LoopItem(dim=DIM_CIN, dim_name="CIN", factor=2, level=1)],
        dram_temporal_loops=[],
        data_size={}, gb_start=1, dram_start=1, perm_levels=1,
    )

    failures = []

    # Demonstrate the bug the fix avoids: the OLD DRAM-only check never
    # sees CIN's NoC-temporal loop at all, so it trivially (and wrongly)
    # reports is_last_K=True regardless of noc_i.
    si = StepInfo(schedule, prob)
    _, dram_only_is_last = si.dram_k_position(0)
    if not dram_only_is_last:
        failures.append("expected the DRAM-only check to (wrongly) report True unconditionally -- "
                         "fixture assumption broke, this test no longer demonstrates the bug")

    tiles = list(iter_node_tiles(schedule, prob))
    by_noc_i = {t.noc_i: t.is_last_K for t in tiles}

    if by_noc_i.get(0) is not False:
        failures.append(f"noc_i=0: expected is_last_K=False (combined check), got {by_noc_i.get(0)}")
    if by_noc_i.get(1) is not True:
        failures.append(f"noc_i=1: expected is_last_K=True (combined check), got {by_noc_i.get(1)}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: combined is_last_K correctly False at noc_i=0, True at noc_i=1 "
          "(the DRAM-only check would have wrongly said True at both)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
