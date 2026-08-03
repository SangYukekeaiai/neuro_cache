"""Hand-made test 1 (log/2026-08-02-multinode-core-driven-weight-trace-plan.md):
iter_node_tiles's multi-node generalization against a tiny hand-computable
fixture, built directly (no MIP solve needed) -- a Schedule/prob pair small
enough to trace on paper.

Fixture: COUT total = 8, everything else = 1. COUT spatially split 2 ways
(2 cores), and each core's own 4-wide COUT slice further split into 2
NoC-temporal steps (2-wide each). No DRAM-temporal split. Hand-derived
expected coverage (worked in planning):

  core 0, noc_i=0 -> COUT[0:2)   core 0, noc_i=1 -> COUT[2:4)
  core 1, noc_i=0 -> COUT[4:6)   core 1, noc_i=1 -> COUT[6:8)

i.e. the 4 (core, noc_i) combinations must tile COUT[0:8) exactly once each,
with no gaps or overlaps.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from nocsim.schedule.decode import LoopItem, Schedule  # noqa: E402
from nocsim.schedule.tiles import iter_node_tiles  # noqa: E402
from parsers.layer import DIM_COUT  # noqa: E402

# 7 dims, KH=0..T=6 (parsers.layer.DIM_*). Only COUT (index 3) has real size;
# everything else is size 1 (empty prime-factor list, matching SNNProb's own
# convention for a dimension of size 1).
_PROB_FACTORS = [[], [], [], [2, 2, 2], [], [], []]  # COUT = 2*2*2 = 8


class _FakeProb:
    """Minimal stand-in for SNNProb -- iter_node_tiles only reads
    prob.prob_factors, and StepInfo's own prob param is unused (see its
    docstring: "kept for API symmetry; not directly used")."""
    def __init__(self, prob_factors):
        self.prob_factors = prob_factors


def main() -> int:
    prob = _FakeProb(_PROB_FACTORS)
    schedule = Schedule(
        spatial_factors={DIM_COUT: 2},
        noc_temporal_loops=[LoopItem(dim=DIM_COUT, dim_name="COUT", factor=2, level=1)],
        dram_temporal_loops=[],
        data_size={}, gb_start=1, dram_start=1, perm_levels=1,
    )

    tiles = list(iter_node_tiles(schedule, prob))
    failures = []

    if len(tiles) != 4:
        failures.append(f"expected 4 tiles (1 dram_i x 2 noc_i x 2 cores), got {len(tiles)}")

    expected_offsets = {(0, 0): 0, (1, 0): 2, (0, 1): 4, (1, 1): 6}  # (noc_i, core_id) -> COUT offset
    seen_offsets = {}
    for t in tiles:
        if t.dram_i != 0:
            failures.append(f"expected dram_i=0 always, got {t.dram_i}")
        if t.node_bound.get(DIM_COUT) != 2:
            failures.append(f"(noc_i={t.noc_i}, core={t.core_id}): expected node_bound[COUT]=2, "
                             f"got {t.node_bound.get(DIM_COUT)}")
        if not t.is_last_K:
            failures.append(f"(noc_i={t.noc_i}, core={t.core_id}): expected is_last_K=True "
                             f"(KH/KW/CIN are all trivially resident, size 1)")
        seen_offsets[(t.noc_i, t.core_id)] = t.tile_offset.get(DIM_COUT)

    for key, expected_offset in expected_offsets.items():
        got = seen_offsets.get(key)
        if got != expected_offset:
            failures.append(f"(noc_i, core_id)={key}: expected tile_offset[COUT]={expected_offset}, got {got}")

    # No two (core, noc_i) combinations should claim the same COUT slice --
    # the 4 offsets must exactly partition COUT[0:8) into 4 disjoint 2-wide
    # ranges.
    covered = sorted(seen_offsets.values())
    if covered != [0, 2, 4, 6]:
        failures.append(f"COUT slices don't exactly partition [0,8): got offsets {covered}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASS: {len(tiles)} tiles, all 4 (core, noc_i) combinations tile "
          f"COUT[0:8) exactly once with the hand-derived offsets {expected_offsets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
