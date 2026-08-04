"""Hand-made test 3 of log/2026-08-03-l1-l2-cache-policy-plan.md: the
two-level hierarchy's inclusive miss-fill and, above all, its tick-atomic
L2 semantics.

Cores inside one tick run in lock-step, so they are concurrent, not
sequential: every L1-missed core's L2 lookup in a tick must be answered
from L2 as it stood when the tick BEGAN, and only afterwards may that
tick's fills be applied (core-ascending) to make the state the next tick
sees. Processing cores one after another and letting each one's fill be
visible to the next is the bug this test exists to catch, and it shows up
in two different shapes here:

  False hit -- core k misses a line, core k+1 asks for the same line in
  the same tick. Sequential processing reports a hit off core k's fill;
  the correct answer is a miss, because at the start of the tick the line
  was not there. Tick 4 below.

  False miss -- a line is resident when the tick begins, this tick's own
  fills evict it, and a later core in the SAME tick asks for it.
  Sequential processing reports a miss; the correct answer is a hit,
  because the line was genuinely resident when it was read. Ticks 2 and
  6 below. This is the plan's "evicted then immediately re-fetched" churn
  case, in its non-prefetch form -- prefetch does not exist until
  Milestone 3, and Milestone 3's same-tick pinning is what will stop the
  eviction itself.

The engine's two policy switches, the L2 cout prefetch and the same-tick
pinning, are off throughout this test: the derivation below is the plain
miss-fill behavior, and tests 15 and 16 are where each switch is turned
on against its own hand derivation. Running them off here is also what
keeps this test a standing check that adding them moved nothing else.

Fixture layer: KH=1, KW=1, CIN=12, COUT=8 with the fixed 4x4 block, so
1 x 1 x 3 x 2 = 6 cache lines, named A..F. L2 holds 2 lines and each L1
holds 1, both fully associative, so every line competes with every other
and the hand derivation needs no set arithmetic.

Both engines are run: the native cache_replay_hierarchical and the Python
reference twin. Each is checked against the table below, which was
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
from python_reference.cachesim.hierarchy import (  # noqa: E402
    CoreRequest,
    TwoLevelHierarchy,
    burst_packed_tags,
    replay_sample,
)

WORKLOAD_DIMS = {"KH": 1, "KW": 1, "CIN": 12, "COUT": 8}

# The six lines of this layer as raw [kh, kw, cin, cout_start, cout_end]
# events, one event per line: with the 4x4 block, cin 0/4/8 are cin blocks
# 0/1/2 and cout [0,4)/[4,8) are cout blocks 0/1. Each event expands to 4
# elements that all share one tag, so each event is exactly one access.
# Packed with the layer's true radices (kw=1, cin blocks=3, cout blocks=2)
# these are 0..5, but under a fully associative cache only their identity
# matters.
LINES = {
    "A": [0, 0, 0, 0, 4],
    "B": [0, 0, 0, 4, 8],
    "C": [0, 0, 4, 0, 4],
    "D": [0, 0, 4, 4, 8],
    "E": [0, 0, 8, 0, 4],
    "F": [0, 0, 8, 4, 8],
}

# The trace, as (tile, tick, {core_id: [line names]}). Split across two
# tiles to confirm a tile boundary is just another tick boundary: cache
# state carries across it, nothing merges over it. Core 5 appears only
# once and cores drop in and out, so nothing may assume a fixed core count
# or contiguous ids.
TICKS = [
    # tile 0
    {0: ["A"], 1: ["B"]},
    {0: ["B"], 1: ["A"]},
    {0: ["C"], 1: ["B"]},
    {0: ["C"], 1: ["C"]},
    # tile 1
    {0: ["D"], 1: ["D"]},
    {1: ["E"], 5: ["D"]},
    {0: ["F", "E"]},
]
TILE_SPLIT = 4  # first this many ticks are tile 0, the rest tile 1

# --------------------------------------------------------------------
# Hand derivation. L1s hold 1 line each, L2 holds 2, LRU, most recently
# used first. "snapshot" is L2 at the START of the tick, which is what
# every lookup in that tick is answered from.
#
# tick 0  L2 snapshot {}          L2 after []
#   core0 A: L1_0 empty        -> L1 miss, L1_0=[A]; A not in {} -> L2 MISS
#   core1 B: L1_1 empty        -> L1 miss, L1_1=[B]; B not in {} -> L2 MISS
#     (sequential would call B a miss too, but only by luck; tick 4 is the
#      case where the two answers differ)
#   fills: access(A) inserts, access(B) inserts -> L2=[B,A]
#
# tick 1  L2 snapshot {A,B}
#   core0 B: L1_0=[A]          -> L1 miss, L1_0=[B]; B in snapshot -> L2 HIT
#   core1 A: L1_1=[B]          -> L1 miss, L1_1=[A]; A in snapshot -> L2 HIT
#   fills: access(B) touch, access(A) touch -> L2=[A,B]
#     (each core hits on the line the OTHER core filled a tick earlier:
#      an earlier tick's fills are exactly what a later tick may hit on)
#
# tick 2  L2 snapshot {A,B}
#   core0 C: L1_0=[B]          -> L1 miss, L1_0=[C]; C not in snapshot -> L2 MISS
#   core1 B: L1_1=[A]          -> L1 miss, L1_1=[B]; B in snapshot -> L2 HIT
#   fills: access(C) misses, evicts LRU B -> L2=[C,A]
#          access(B) misses (just evicted), evicts LRU A -> L2=[B,C]
#     FALSE MISS case: core1 read B while it was still resident, so it is
#     a hit, even though this tick's own fills threw B out and refetched
#     it. Sequential processing would have reported a miss.
#
# tick 3  L2 snapshot {B,C}
#   core0 C: L1_0=[C]          -> L1 HIT, no L2 lookup
#   core1 C: L1_1=[B]          -> L1 miss, L1_1=[C]; C in snapshot -> L2 HIT
#   fills: access(C) touch -> L2=[C,B]
#
# tick 4  L2 snapshot {B,C}
#   core0 D: L1_0=[C]          -> L1 miss, L1_0=[D]; D not in snapshot -> L2 MISS
#   core1 D: L1_1=[C]          -> L1 miss, L1_1=[D]; D not in snapshot -> L2 MISS
#     FALSE HIT case: sequential processing would report core1's D as a
#     hit off core0's fill from this same tick.
#   fills: access(D) misses, evicts LRU B -> L2=[D,C]
#          access(D) hits -> L2=[D,C]
#
# tick 5  L2 snapshot {C,D}
#   core1 E: L1_1=[D]          -> L1 miss, L1_1=[E]; E not in snapshot -> L2 MISS
#   core5 D: L1_5 empty        -> L1 miss, L1_5=[D]; D in snapshot -> L2 HIT
#   fills: access(E) misses, evicts LRU C -> L2=[E,D]
#          access(D) hits -> L2=[D,E]
#     (core0 is simply absent this tick, and core5 is seen for the first
#      time; both are ordinary)
#
# tick 6  L2 snapshot {D,E}
#   core0 F: L1_0=[D]          -> L1 miss, L1_0=[F]; F not in snapshot -> L2 MISS
#   core0 E: L1_0=[F]          -> L1 miss, L1_0=[E]; E in snapshot -> L2 HIT
#   fills: access(F) misses, evicts LRU E -> L2=[F,D]
#          access(E) misses (just evicted), evicts LRU D -> L2=[E,F]
#     FALSE MISS again, this time within one core's own two accesses:
#     every lookup in a tick is answered from the tick's start, including
#     the second one a single core makes.
# --------------------------------------------------------------------

# Cumulative (l1_hits, l1_accesses, l2_hits, l2_accesses) after each tick.
EXPECTED_BY_TICK = [
    (0, 2, 0, 2),
    (0, 4, 2, 4),
    (0, 6, 3, 6),
    (1, 8, 4, 7),
    (1, 10, 4, 9),
    (1, 12, 5, 11),
    (1, 14, 6, 13),
]

# L2 hits per tick (not cumulative), the tick-atomic answer against the
# answer sequential processing would give if each core saw the fills of
# the cores before it in its own tick. The L1 numbers would be identical
# either way, because an L1 is private. Ticks 2, 4 and 6 are where the
# two part; the cumulative totals happen to coincide again at tick 4,
# which is why this comparison is made per tick.
ATOMIC_L2_HITS_PER_TICK = [0, 2, 1, 1, 0, 1, 1]
SEQUENTIAL_L2_HITS_PER_TICK = [0, 2, 0, 1, 1, 1, 0]

EXPECTED_PER_CORE_L1 = ((0, 1, 7), (1, 0, 6), (5, 0, 1))
EXPECTED_TOTALS = (1, 14, 6, 13)  # l1_hits, l1_accesses, l2_hits, l2_accesses
EXPECTED_OVERALL_HIT_RATE = 0.5  # (1 + 6) / 14


def build_sample():
    """The fixture as a Stage 1 nested sample dict."""
    tiles = []
    for tile_i, tick_slice in enumerate((TICKS[:TILE_SPLIT], TICKS[TILE_SPLIT:])):
        tiles.append({
            "dram_i": tile_i,
            "noc_i": 0,
            "mac_cycles": 1,
            "lif_cycles": None,
            "ticks": [
                {
                    "tick": tick_i,
                    # Deliberately NOT sorted by core_id on disk: the
                    # engines must sort, since the fill order is
                    # core-ascending and merge_cores_by_tick does not
                    # guarantee it.
                    "cores": [
                        {"core_id": core_id, "weight_addresses": [LINES[name] for name in names]}
                        for core_id, names in sorted(cores.items(), reverse=True)
                    ],
                }
                for tick_i, cores in enumerate(tick_slice)
            ],
        })
    return {
        "arch": "handmade",
        "trace_dir": "test14",
        "layer_name": "layer_00",
        "sample_idx": 0,
        "workload_dims": WORKLOAD_DIMS,
        "dram_num_steps": len(tiles),
        "noc_num_steps": 1,
        "tiles": tiles,
    }


def check_tick_by_tick(l1_config, l2_config, order, failures):
    """Drive the reference twin one tick at a time, so the running counts
    can be checked against the hand derivation at every tick rather than
    only at the end."""
    hierarchy = TwoLevelHierarchy(l1_config, l2_config, l2_prefetch=False, same_tick_pinning=False)
    previous_l2_hits = 0
    for tick_i, cores in enumerate(TICKS):
        hierarchy.run_tick([
            CoreRequest(core_id, burst_packed_tags([LINES[n] for n in names], l1_config, order))
            for core_id, names in sorted(cores.items())
        ])
        stats = hierarchy.stats()
        got = (stats.l1_hits, stats.l1_accesses, stats.l2_hits, stats.l2_accesses)
        if got != EXPECTED_BY_TICK[tick_i]:
            failures.append(
                f"after tick {tick_i}: expected (l1_hits, l1_accesses, l2_hits, l2_accesses) "
                f"{EXPECTED_BY_TICK[tick_i]}, got {got}"
            )
        this_tick = stats.l2_hits - previous_l2_hits
        previous_l2_hits = stats.l2_hits
        if this_tick != ATOMIC_L2_HITS_PER_TICK[tick_i]:
            failures.append(
                f"tick {tick_i}: expected {ATOMIC_L2_HITS_PER_TICK[tick_i]} L2 hit(s) in the tick, "
                f"got {this_tick}"
            )
        if this_tick == SEQUENTIAL_L2_HITS_PER_TICK[tick_i] != ATOMIC_L2_HITS_PER_TICK[tick_i]:
            failures.append(
                f"tick {tick_i}: L2 hits match the sequential answer "
                f"{SEQUENTIAL_L2_HITS_PER_TICK[tick_i]}, so same-tick cores are seeing "
                f"each other's fills"
            )


def check_stats(label, stats, failures):
    if stats.per_core_l1 != EXPECTED_PER_CORE_L1:
        failures.append(f"{label}: expected per-core L1 {EXPECTED_PER_CORE_L1}, got {stats.per_core_l1}")
    totals = (stats.l1_hits, stats.l1_accesses, stats.l2_hits, stats.l2_accesses)
    if totals != EXPECTED_TOTALS:
        failures.append(f"{label}: expected totals {EXPECTED_TOTALS}, got {totals}")
    if stats.l2_accesses != stats.l1_accesses - stats.l1_hits:
        failures.append(
            f"{label}: L2 should see exactly the L1-missed traffic, got "
            f"{stats.l2_accesses} accesses against {stats.l1_accesses - stats.l1_hits} L1 misses"
        )
    if stats.overall_hit_rate != EXPECTED_OVERALL_HIT_RATE:
        failures.append(
            f"{label}: expected overall hit rate {EXPECTED_OVERALL_HIT_RATE}, got {stats.overall_hit_rate}"
        )


def main() -> int:
    order = list(DIMS)
    sample = build_sample()
    l1_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=16, cache_type="fully_associative")
    l2_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=32, cache_type="fully_associative")

    failures = []
    if (l1_config.capacity_lines, l2_config.capacity_lines) != (1, 2):
        failures.append(
            f"fixture caches should hold 1 and 2 lines, got "
            f"{l1_config.capacity_lines} and {l2_config.capacity_lines}"
        )

    check_tick_by_tick(l1_config, l2_config, order, failures)

    reference = replay_sample(
        sample, l1_config, l2_config, order, l2_prefetch=False, same_tick_pinning=False
    )
    check_stats("python reference twin", reference, failures)

    with tempfile.TemporaryDirectory() as tmp:
        sample_path = pathlib.Path(tmp) / "sample_00000.json.gz"
        with gzip.open(sample_path, "wt") as fh:
            json.dump(sample, fh)
        native = native_hierarchical_stats(
            sample_path, l1_config, l2_config, order, l2_prefetch=False, same_tick_pinning=False
        )
    check_stats("native cache_replay_hierarchical", native, failures)

    if native != reference:
        failures.append(f"native and reference disagree:\n    native    {native}\n    reference {reference}")

    print("hand-derived cumulative counts after each tick "
          "(l1_hits, l1_accesses, l2_hits, l2_accesses), and this tick's own L2 hits:")
    for tick_i, expected in enumerate(EXPECTED_BY_TICK):
        atomic, sequential = ATOMIC_L2_HITS_PER_TICK[tick_i], SEQUENTIAL_L2_HITS_PER_TICK[tick_i]
        note = f"  <- sequential processing would say {sequential}" if atomic != sequential else ""
        print(f"  tick {tick_i}: {expected}, {atomic} L2 hit(s) this tick{note}")
    print(f"native   : {native}")
    print(f"reference: {reference}")
    print(f"  per-core L1 hit rates: {reference.per_core_l1_hit_rates}")
    print(f"  L1 {reference.l1_hit_rate}, L2 {reference.l2_hit_rate}, overall {reference.overall_hit_rate}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: tick-atomic L2 lookups match the hand derivation at every tick "
          "(the false-hit case at tick 4 and the evicted-then-refetched false-miss "
          "case at ticks 2 and 6 all disagree with sequential processing, and the "
          "engines give the tick-atomic answer), inclusive miss-fill sends exactly "
          "the L1-missed traffic to L2, and the native engine and the Python "
          "reference twin report identical stats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
