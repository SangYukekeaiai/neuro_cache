"""Hand-made test 5 of log/2026-08-03-l1-l2-cache-policy-plan.md: same-tick
pinning, "a tag that was an L2 hit this tick is protected from eviction by
this tick's own fills", and its overflow fallback, "if every resident line
in L2 is pinned this tick and a miss still needs to evict, evict the
pinned line that was closest to LRU BEFORE this tick's touches".

Three fixtures, each a separate trace through a fresh hierarchy:

  A -- the plan's normal case, literally: L2 holds [Y, X] with Y most
  recently used, one tick has core0 miss on a new tag Z and core1 hit on
  X, and Y is evicted instead of X because X is protected. Worth knowing
  before reading the numbers: this case is NOT observable from outside.
  With pinning off the insert of Z evicts X, and then X's own hit-touch
  (a fill like any other) re-inserts it and evicts Y anyway, so the tick
  ends with the same two lines in the same order either way. The eviction
  differs, the outcome does not, so fixture A checks the derivation and
  asserts the two answers agree; fixtures B and C are where pinning is
  load-bearing.

  B -- the same protection where it does change the outcome: the pinned
  line's hit-touch lands FIRST in the tick and two inserts follow it.
  Protection keeps Y resident; plain LRU throws Y out on the second
  insert and nothing brings it back, so the next tick's read of Y is a
  hit with pinning and a miss without.

  C -- the overflow case: both resident lines are read in one tick, so
  both are pinned, and a third core still misses and must evict. The
  fallback sacrifices X, the line closest to LRU before this tick's
  touches, even though X's own hit-touch has since moved it to the most
  recently used end. An implementation that instead took the current LRU
  end would sacrifice Y, which ticks 2 and 3 tell apart in both
  directions.

Fixture layer: KH=1, KW=1, CIN=20, COUT=8 with the fixed 4x4 block. Every
tag used here sits in cout block 1, the layer's last, so the cout
prefetch is a no-op on every miss and these fixtures are about pinning
alone: the test runs with the prefetch on (the plan's real configuration)
and confirms that turning it off changes nothing. L1 holds 1 line and L2
holds 2, both fully associative, so every line competes with every other
and the hand derivation needs no set arithmetic.

Both engines are run: the native cache_replay_hierarchical and the Python
reference twin. Each is checked against the tables below, which were
derived by hand, and against the other.
"""

import gzip
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, hybrid_config_from_dims  # noqa: E402
from cachesim.native_bridge import native_hierarchical_stats  # noqa: E402
from python_reference.cachesim.hierarchy import replay_sample  # noqa: E402

WORKLOAD_DIMS = {"KH": 1, "KW": 1, "CIN": 20, "COUT": 8}

# Four lines of the layer, as raw [kh, kw, cin, cout_start, cout_end]
# events: with the 4x4 block, cin 0/4/8/12 are cin blocks 0/1/2/3 and cout
# [4,8) is cout block 1. Each event expands to 4 elements that all share
# one tag, so each event is exactly one access. Packed with the layer's
# true radices (kw=1, cin blocks=5, cout blocks=2) the tags are
# cin_blk * 2 + 1, all odd, i.e. all in the layer's LAST cout block, which
# is what makes the prefetch a no-op throughout.
LINES = {
    "X": [0, 0, 0, 4, 8],    # packed 1
    "Y": [0, 0, 4, 4, 8],    # packed 3
    "Z": [0, 0, 8, 4, 8],    # packed 5
    "W": [0, 0, 12, 4, 8],   # packed 7
}

# --------------------------------------------------------------------
# Fixture A -- the plan's normal case. L1s hold 1 line each, L2 holds 2,
# LRU, most recently used written first. "snapshot" is L2 at the START of
# the tick; fills land after every lookup of the tick is resolved, in
# core-ascending order.
#
# tick 0  L2 snapshot {}
#   core0 X: L1 miss, L1_0=[X]; X not in {} -> L2 MISS
#   core1 Y: L1 miss, L1_1=[Y]; Y not in {} -> L2 MISS
#   fills: insert X -> [X]; insert Y -> [Y,X]
#     L2 is now the plan's starting state: Y most recently used, X least.
#
# tick 1  L2 snapshot {Y,X}
#   core0 Z: L1 miss, L1_0=[Z]; Z not in snapshot -> L2 MISS
#   core1 X: L1 miss, L1_1=[X]; X in snapshot -> L2 HIT, so X is PINNED,
#            carrying the recency it had before this tick (X was the LRU
#            end, stamped older than Y)
#   fills: insert Z -> L2 is full; walking from the LRU end, X is pinned
#          and Y is not, so Y is evicted -> [Z,X]
#          touch X -> [X,Z]
#     Without pinning: insert Z evicts LRU X -> [Z,Y]; then X's hit-touch
#     misses, inserts, and evicts LRU Y -> [X,Z]. Same content, same
#     order. The protection changed which line died mid-tick and nothing
#     else, which is why this fixture cannot tell the two apart.
#
# tick 2  L2 snapshot {X,Z}
#   core0 X: L1 miss (L1_0=[Z]), L1_0=[X]; X in snapshot -> L2 HIT
#   core1 Y: L1 miss (L1_1=[X]), L1_1=[Y]; Y not in snapshot -> L2 MISS
#     Y is gone either way, X survives either way: the probe confirms the
#     derived content, not the protection.
#   fills: touch X -> [X,Z]; insert Y, X pinned, so Z is evicted -> [Y,X]
# --------------------------------------------------------------------
FIXTURE_A_TICKS = [
    {0: ["X"], 1: ["Y"]},
    {0: ["Z"], 1: ["X"]},
    {0: ["X"], 1: ["Y"]},
]
FIXTURE_A_BY_TICK = [(0, 2, 0, 2), (0, 4, 1, 4), (0, 6, 2, 6)]
FIXTURE_A_PER_CORE = ((0, 0, 3), (1, 0, 3))
# Pinning does not move this fixture, so both answers are the same table.
FIXTURE_A_NO_PINNING_BY_TICK = FIXTURE_A_BY_TICK

# --------------------------------------------------------------------
# Fixture B -- protection that does change the outcome.
#
# tick 0  L2 snapshot {}
#   core0 X: L1 miss, L1_0=[X]; L2 MISS
#   core1 Y: L1 miss, L1_1=[Y]; L2 MISS
#   fills: insert X -> [X]; insert Y -> [Y,X]
#
# tick 1  L2 snapshot {Y,X}
#   core0 Y: L1 miss (L1_0=[X]), L1_0=[Y]; Y in snapshot -> L2 HIT, Y PINNED
#   core1 Z: L1 miss (L1_1=[Y]), L1_1=[Z]; Z not in snapshot -> L2 MISS
#   core2 W: L1 miss (first tick for this core), L1_2=[W]; -> L2 MISS
#   fills: touch Y -> [Y,X]
#          insert Z: full; from the LRU end X is unpinned -> evict X -> [Z,Y]
#          insert W: full; from the LRU end Y is pinned, Z is not ->
#                    evict Z -> [W,Y]
#     Without pinning: touch Y -> [Y,X]; insert Z evicts LRU X -> [Z,Y];
#     insert W evicts LRU Y -> [W,Z]. Y is gone and nothing re-fetches it,
#     because its hit-touch already happened.
#
# tick 2  L2 snapshot {W,Y}
#   core1 Y: L1 miss (L1_1=[Z]), L1_1=[Y]; Y in snapshot -> L2 HIT
#     Without pinning the snapshot is {W,Z} instead and this is a MISS.
#   fills: touch Y -> [Y,W]
# --------------------------------------------------------------------
FIXTURE_B_TICKS = [
    {0: ["X"], 1: ["Y"]},
    {0: ["Y"], 1: ["Z"], 2: ["W"]},
    {1: ["Y"]},
]
FIXTURE_B_BY_TICK = [(0, 2, 0, 2), (0, 5, 1, 5), (0, 6, 2, 6)]
FIXTURE_B_PER_CORE = ((0, 0, 2), (1, 0, 3), (2, 0, 1))
FIXTURE_B_NO_PINNING_BY_TICK = [(0, 2, 0, 2), (0, 5, 1, 5), (0, 6, 1, 6)]

# --------------------------------------------------------------------
# Fixture C -- the overflow case.
#
# tick 0  L2 snapshot {}
#   core0 X: L1 miss, L1_0=[X]; L2 MISS
#   core1 Y: L1 miss, L1_1=[Y]; L2 MISS
#   fills: insert X -> [X]; insert Y -> [Y,X]
#     X is stamped older than Y: it was filled first, and nothing has
#     touched it since. That is the whole basis of the fallback below.
#
# tick 1  L2 snapshot {Y,X}
#   core0 Y: L1 miss (L1_0=[X]), L1_0=[Y]; Y in snapshot -> L2 HIT, Y PINNED
#   core1 X: L1 miss (L1_1=[Y]), L1_1=[X]; X in snapshot -> L2 HIT, X PINNED
#   core2 Z: L1 miss (first tick for this core), L1_2=[Z]; -> L2 MISS
#   fills: touch Y -> [Y,X]
#          touch X -> [X,Y]
#          insert Z: full, and BOTH resident lines are pinned, so the walk
#            from the LRU end finds no unpinned victim. Fallback: of the
#            pinned lines, X was closest to LRU before this tick's touches
#            (X was the LRU end at the start of the tick), so X is
#            evicted -> [Z,Y]
#     Note the current LRU end at that moment is Y, not X: this tick's own
#     two touches reversed them. An implementation reading the live order
#     instead of the pre-tick one would evict Y here.
#     Without pinning at all: insert Z evicts the LRU end, Y -> [Z,X].
#
# tick 2  L2 snapshot {Z,Y}
#   core1 Y: L1 miss (L1_1=[X]), L1_1=[Y]; Y in snapshot -> L2 HIT
#     Y survived only because the fallback picked X. Both wrong answers
#     (no pinning, or a fallback reading the live LRU order) evict Y here
#     and make this a MISS.
#   fills: touch Y -> [Y,Z]
#
# tick 3  L2 snapshot {Y,Z}
#   core0 X: L1 miss (L1_0=[Y]), L1_0=[X]; X not in snapshot -> L2 MISS
#     The other direction: X really was sacrificed. A fallback that had
#     evicted Y instead would report a hit here.
#   fills: insert X, nothing pinned, evicts LRU Z -> [X,Y]
# --------------------------------------------------------------------
FIXTURE_C_TICKS = [
    {0: ["X"], 1: ["Y"]},
    {0: ["Y"], 1: ["X"], 2: ["Z"]},
    {1: ["Y"]},
    {0: ["X"]},
]
FIXTURE_C_BY_TICK = [(0, 2, 0, 2), (0, 5, 2, 5), (0, 6, 3, 6), (0, 7, 3, 7)]
FIXTURE_C_PER_CORE = ((0, 0, 3), (1, 0, 3), (2, 0, 1))
# With no pinning the tick-1 insert evicts Y, so tick 2 misses on Y and
# tick 3 still misses on X (X went out at tick 2 instead). A fallback that
# read the live LRU order would evict Y too, giving this same table, which
# is why both wrong implementations fail the same assertions.
FIXTURE_C_NO_PINNING_BY_TICK = [(0, 2, 0, 2), (0, 5, 2, 5), (0, 6, 2, 6), (0, 7, 2, 7)]


def build_sample(ticks):
    """One fixture's tick list as a Stage 1 nested sample dict."""
    return {
        "arch": "handmade",
        "trace_dir": "test16",
        "layer_name": "layer_00",
        "sample_idx": 0,
        "workload_dims": WORKLOAD_DIMS,
        "dram_num_steps": 1,
        "noc_num_steps": 1,
        "tiles": [{
            "dram_i": 0,
            "noc_i": 0,
            "mac_cycles": 1,
            "lif_cycles": None,
            "ticks": [
                {
                    "tick": tick_i,
                    "cores": [
                        {"core_id": core_id, "weight_addresses": [LINES[name] for name in names]}
                        for core_id, names in sorted(cores.items())
                    ],
                }
                for tick_i, cores in enumerate(ticks)
            ],
        }],
    }


def prefix_sample(ticks, n):
    """The fixture truncated to its first n ticks. Running each prefix
    through a fresh hierarchy checks the cumulative counts tick by tick
    on both engines, not only at the end."""
    return build_sample(ticks[:n])


def totals(stats):
    return (stats.l1_hits, stats.l1_accesses, stats.l2_hits, stats.l2_accesses)


def check_fixture(name, ticks, by_tick, per_core, no_pinning_by_tick, configs, order, failures):
    l1_config, l2_config = configs
    with tempfile.TemporaryDirectory() as tmp:
        for tick_i in range(len(ticks)):
            sample = prefix_sample(ticks, tick_i + 1)
            sample_path = pathlib.Path(tmp) / f"sample_{tick_i:05d}.json.gz"
            with gzip.open(sample_path, "wt") as fh:
                json.dump(sample, fh)

            reference = replay_sample(
                sample, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=True
            )
            native = native_hierarchical_stats(
                sample_path, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=True
            )
            unpinned = native_hierarchical_stats(
                sample_path, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=False
            )
            unprefetched = native_hierarchical_stats(
                sample_path, l1_config, l2_config, order, l2_prefetch=False, same_tick_pinning=True
            )

            if totals(reference) != by_tick[tick_i]:
                failures.append(
                    f"{name} reference after tick {tick_i}: expected "
                    f"(l1_hits, l1_accesses, l2_hits, l2_accesses) {by_tick[tick_i]}, "
                    f"got {totals(reference)}"
                )
            if native != reference:
                failures.append(
                    f"{name} after tick {tick_i}: native and reference disagree:\n"
                    f"    native    {native}\n    reference {reference}"
                )
            if totals(unpinned) != no_pinning_by_tick[tick_i]:
                failures.append(
                    f"{name} with pinning off after tick {tick_i}: expected "
                    f"{no_pinning_by_tick[tick_i]}, got {totals(unpinned)}"
                )
            if totals(unprefetched) != by_tick[tick_i]:
                failures.append(
                    f"{name} after tick {tick_i}: every tag here is in the layer's last cout "
                    f"block, so the prefetch should be a no-op, but turning it off gave "
                    f"{totals(unprefetched)} instead of {by_tick[tick_i]}"
                )
            if tick_i == len(ticks) - 1 and native.per_core_l1 != per_core:
                failures.append(f"{name}: expected per-core L1 {per_core}, got {native.per_core_l1}")
    return reference


def main() -> int:
    order = list(DIMS)
    l1_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=16, cache_type="fully_associative")
    l2_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=32, cache_type="fully_associative")

    failures = []
    if (l1_config.capacity_lines, l2_config.capacity_lines) != (1, 2):
        failures.append(
            f"fixture caches should hold 1 and 2 lines, got "
            f"{l1_config.capacity_lines} and {l2_config.capacity_lines}"
        )

    fixtures = [
        ("A (plan's normal case)", FIXTURE_A_TICKS, FIXTURE_A_BY_TICK, FIXTURE_A_PER_CORE,
         FIXTURE_A_NO_PINNING_BY_TICK),
        ("B (protection that shows)", FIXTURE_B_TICKS, FIXTURE_B_BY_TICK, FIXTURE_B_PER_CORE,
         FIXTURE_B_NO_PINNING_BY_TICK),
        ("C (overflow fallback)", FIXTURE_C_TICKS, FIXTURE_C_BY_TICK, FIXTURE_C_PER_CORE,
         FIXTURE_C_NO_PINNING_BY_TICK),
    ]
    for name, ticks, by_tick, per_core, no_pinning in fixtures:
        final = check_fixture(name, ticks, by_tick, per_core, no_pinning, (l1_config, l2_config),
                              order, failures)
        print(f"fixture {name}: cumulative (l1_hits, l1_accesses, l2_hits, l2_accesses) per tick")
        for tick_i, expected in enumerate(by_tick):
            note = "" if expected == no_pinning[tick_i] else f"  <- without pinning: {no_pinning[tick_i]}"
            print(f"  tick {tick_i}: {expected}{note}")
        print(f"  final: {final}")
        print(f"  L1 {final.l1_hit_rate}, L2 {final.l2_hit_rate}, overall {final.overall_hit_rate}")

    # Fixtures B and C are the ones carrying the evidence; if either
    # stopped depending on pinning the test would still pass its tables
    # while proving nothing, so that dependence is asserted directly.
    for name, by_tick, no_pinning in (
        ("B (protection that shows)", FIXTURE_B_BY_TICK, FIXTURE_B_NO_PINNING_BY_TICK),
        ("C (overflow fallback)", FIXTURE_C_BY_TICK, FIXTURE_C_NO_PINNING_BY_TICK),
    ):
        if by_tick == no_pinning:
            failures.append(f"fixture {name} expects the same numbers with and without pinning, "
                            f"so it cannot tell them apart")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: the plan's normal case evicts Y and keeps X (fixture A, an eviction that LRU "
          "hides again by the end of the tick), protection keeps a line alive that plain LRU "
          "loses (fixture B, a hit at tick 2 that is a miss without pinning), the overflow "
          "fallback sacrifices the line closest to pre-tick LRU rather than the live LRU end "
          "(fixture C, checked in both directions at ticks 2 and 3), the cout prefetch is inert "
          "on all three, and the native engine and the Python reference twin report identical "
          "stats at every tick")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
