"""Hand-made test 4 of log/2026-08-03-l1-l2-cache-policy-plan.md: the L2
cout-prefetch policy, "triggered only on an L2 miss ... also insert
(kh, kw, cin_blk, cout_blk + 1) if within the layer's true COUT range,
no-op at the boundary ... tracked separately from demand accesses so they
don't inflate the reported L2 hit rate".

Three claims are checked, each by a tick whose answer changes if that
part of the policy is wrong:

  Prefetch produces a hit -- core0 misses on A, so A's cout neighbour B
  is prefetched; a LATER tick's core1 asks for B and hits, purely because
  of that prefetch. Ticks 0/1, and again at ticks 4/5 for C and D. With
  prefetch off both of those are misses, which the test runs and compares
  against.

  No-op at the COUT boundary -- F sits in the layer's last cout block, so
  its miss at tick 2 prefetches nothing. A boundary prefetch would insert
  a line that does not exist in this layer, and in a 3-line L2 it would
  push A out; tick 3's hit on A is what says it did not happen.

  A prefetch is not an access -- L2 sees exactly the L1-missed traffic
  (6 accesses for 6 L1 misses) even though 2 prefetch inserts happened,
  so the reported L2 hit rate is 3/6 and not 3/8.

Fixture layer: KH=1, KW=1, CIN=12, COUT=8 with the fixed 4x4 block, so
1 x 1 x 3 x 2 = 6 cache lines. L1 holds 1 line and L2 holds 3, both fully
associative, so every line competes with every other and the hand
derivation needs no set arithmetic. Same-tick pinning is on (this is the
plan's real configuration) but inert here: no tick both hits on a line
and evicts anything, which the test also confirms by re-running with it
off.

Both engines are run: the native cache_replay_hierarchical and the
Python reference twin. Each is checked against the table below, which was
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

# Five of the layer's six lines, as raw [kh, kw, cin, cout_start,
# cout_end] events: with the 4x4 block, cin 0/4/8 are cin blocks 0/1/2 and
# cout [0,4)/[4,8) are cout blocks 0/1. Each event expands to 4 elements
# that all share one tag, so each event is exactly one access. Packed with
# the layer's true radices (kw=1, cin blocks=3, cout blocks=2) the tags
# are cin_blk * 2 + cout_blk, which is why A and B are neighbours: cout is
# the innermost component, so B is A's next packed value. The sixth line
# (cin block 2, cout block 0) is never requested here.
LINES = {
    "A": [0, 0, 0, 0, 4],   # packed 0, cout block 0 -> prefetches B
    "B": [0, 0, 0, 4, 8],   # packed 1, cout block 1 -> last block, no prefetch
    "C": [0, 0, 4, 0, 4],   # packed 2, cout block 0 -> prefetches D
    "D": [0, 0, 4, 4, 8],   # packed 3, cout block 1 -> last block, no prefetch
    "F": [0, 0, 8, 4, 8],   # packed 5, cout block 1 -> last block, no prefetch
}

# The trace, as (tick, {core_id: [line names]}).
TICKS = [
    {0: ["A"]},
    {1: ["B"]},
    {0: ["F"]},
    {1: ["A"]},
    {0: ["C"]},
    {1: ["D"]},
]

# --------------------------------------------------------------------
# Hand derivation. L1s hold 1 line each, L2 holds 3, LRU, most recently
# used written first. "snapshot" is L2 at the START of the tick, which is
# what every lookup in that tick is answered from; the fills land after
# every lookup of the tick is resolved.
#
# tick 0  L2 snapshot {}          L1_0 {}
#   core0 A: L1 miss, L1_0=[A]; A not in {} -> L2 MISS
#   fills: demand insert A -> L2=[A]
#          prefetch B (A is cout block 0 of 2, so 0+1 is inside the
#          layer) -> L2=[B,A].  Neither fill is an access.
#
# tick 1  L2 snapshot {A,B}       L1_1 {}
#   core1 B: L1 miss, L1_1=[B]; B in snapshot -> L2 HIT
#     THE PREFETCH CASE: nothing has ever demanded B. It is resident only
#     because tick 0's miss on A brought its cout neighbour along.
#   fills: touch B -> L2=[B,A]
#
# tick 2  L2 snapshot {B,A}       L1_0 [A]
#   core0 F: L1 miss, L1_0=[F]; F not in snapshot -> L2 MISS
#   fills: demand insert F -> L2=[F,B,A] (3 lines, now full)
#          no prefetch: F is in cout block 1, the layer's last, so the
#          neighbour would leave the layer -> no-op
#
# tick 3  L2 snapshot {F,B,A}     L1_1 [B]
#   core1 A: L1 miss, L1_1=[A]; A in snapshot -> L2 HIT
#     THE BOUNDARY CASE: had tick 2 prefetched past the COUT edge, that
#     extra insert would have evicted LRU A and this would be a miss.
#   fills: touch A -> L2=[A,F,B]
#
# tick 4  L2 snapshot {A,F,B}     L1_0 [F]
#   core0 C: L1 miss, L1_0=[C]; C not in snapshot -> L2 MISS
#   fills: demand insert C, full, evicts LRU B -> L2=[C,A,F]
#          prefetch D (C is cout block 0), full, evicts LRU F -> L2=[D,C,A]
#
# tick 5  L2 snapshot {D,C,A}     L1_1 [A]
#   core1 D: L1 miss, L1_1=[D]; D in snapshot -> L2 HIT
#     THE PREFETCH CASE again, this time where the prefetch had to evict
#     to land.
#   fills: touch D -> L2=[D,C,A]
#
# No tick above both hits on a line and inserts, so no fill of this
# fixture ever has a pinned line to protect: the numbers below are the
# prefetch policy's alone.
# --------------------------------------------------------------------

# Cumulative (l1_hits, l1_accesses, l2_hits, l2_accesses) after each tick.
EXPECTED_BY_TICK = [
    (0, 1, 0, 1),
    (0, 2, 1, 2),
    (0, 3, 1, 3),
    (0, 4, 2, 4),
    (0, 5, 2, 5),
    (0, 6, 3, 6),
]

# L2 hits per tick (not cumulative), with the prefetch against the answer
# the same fixture gives with the prefetch off. Ticks 1 and 5 are the
# prefetch's own hits. Without it, tick 3 is the only hit, and it survives
# because the boundary no-op means nothing extra was ever inserted:
#   t0 insert A -> [A]; t1 B MISS, insert B -> [B,A]; t2 F MISS, insert
#   F -> [F,B,A]; t3 A HIT, touch -> [A,F,B]; t4 C MISS, insert C evicts
#   B -> [C,A,F]; t5 D MISS, insert D evicts F -> [D,C,A].
PREFETCH_L2_HITS_PER_TICK = [0, 1, 0, 1, 0, 1]
NO_PREFETCH_L2_HITS_PER_TICK = [0, 0, 0, 1, 0, 0]

EXPECTED_PER_CORE_L1 = ((0, 0, 3), (1, 0, 3))
EXPECTED_TOTALS = (0, 6, 3, 6)  # l1_hits, l1_accesses, l2_hits, l2_accesses
EXPECTED_L2_HIT_RATE = 0.5  # 3 / 6, and NOT 3 / 8: the 2 prefetches are not accesses
NO_PREFETCH_TOTALS = (0, 6, 1, 6)


def build_sample():
    """The fixture as a Stage 1 nested sample dict, one tile."""
    return {
        "arch": "handmade",
        "trace_dir": "test15",
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
                for tick_i, cores in enumerate(TICKS)
            ],
        }],
    }


def check_tick_by_tick(l1_config, l2_config, order, failures):
    """Drive the reference twin one tick at a time, so the running counts
    can be checked against the hand derivation at every tick rather than
    only at the end."""
    hierarchy = TwoLevelHierarchy(l1_config, l2_config, l2_prefetch=True, same_tick_pinning=True)
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
        if this_tick != PREFETCH_L2_HITS_PER_TICK[tick_i]:
            failures.append(
                f"tick {tick_i}: expected {PREFETCH_L2_HITS_PER_TICK[tick_i]} L2 hit(s) in the tick, "
                f"got {this_tick}"
            )


def check_stats(label, stats, failures):
    if stats.per_core_l1 != EXPECTED_PER_CORE_L1:
        failures.append(f"{label}: expected per-core L1 {EXPECTED_PER_CORE_L1}, got {stats.per_core_l1}")
    totals = (stats.l1_hits, stats.l1_accesses, stats.l2_hits, stats.l2_accesses)
    if totals != EXPECTED_TOTALS:
        failures.append(f"{label}: expected totals {EXPECTED_TOTALS}, got {totals}")
    if stats.l2_accesses != stats.l1_accesses - stats.l1_hits:
        failures.append(
            f"{label}: L2 should see exactly the L1-missed traffic and no prefetch, got "
            f"{stats.l2_accesses} accesses against {stats.l1_accesses - stats.l1_hits} L1 misses"
        )
    if stats.l2_hit_rate != EXPECTED_L2_HIT_RATE:
        failures.append(f"{label}: expected L2 hit rate {EXPECTED_L2_HIT_RATE}, got {stats.l2_hit_rate}")


def main() -> int:
    order = list(DIMS)
    sample = build_sample()
    l1_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=16, cache_type="fully_associative")
    l2_config = hybrid_config_from_dims(WORKLOAD_DIMS, cache_size_bytes=48, cache_type="fully_associative")

    failures = []
    if (l1_config.capacity_lines, l2_config.capacity_lines) != (1, 3):
        failures.append(
            f"fixture caches should hold 1 and 3 lines, got "
            f"{l1_config.capacity_lines} and {l2_config.capacity_lines}"
        )

    check_tick_by_tick(l1_config, l2_config, order, failures)

    reference = replay_sample(sample, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=True)
    check_stats("python reference twin", reference, failures)

    with tempfile.TemporaryDirectory() as tmp:
        sample_path = pathlib.Path(tmp) / "sample_00000.json.gz"
        with gzip.open(sample_path, "wt") as fh:
            json.dump(sample, fh)
        native = native_hierarchical_stats(
            sample_path, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=True
        )
        check_stats("native cache_replay_hierarchical", native, failures)

        # The same fixture with the prefetch off, which is what an engine
        # that never prefetched would report: this is the mutation the
        # numbers above have to be able to tell apart, so if these two
        # agreed the test would be proving nothing.
        no_prefetch = native_hierarchical_stats(
            sample_path, l1_config, l2_config, order, l2_prefetch=False, same_tick_pinning=True
        )
        # And with pinning off, which must change nothing at all here.
        no_pinning = native_hierarchical_stats(
            sample_path, l1_config, l2_config, order, l2_prefetch=True, same_tick_pinning=False
        )

    no_prefetch_totals = (
        no_prefetch.l1_hits, no_prefetch.l1_accesses, no_prefetch.l2_hits, no_prefetch.l2_accesses
    )
    if no_prefetch_totals != NO_PREFETCH_TOTALS:
        failures.append(
            f"with the prefetch off, expected totals {NO_PREFETCH_TOTALS}, got {no_prefetch_totals}"
        )
    if no_prefetch_totals == EXPECTED_TOTALS:
        failures.append("prefetch on and prefetch off give the same totals, so this fixture proves nothing")
    if no_pinning != native:
        failures.append(
            f"same-tick pinning should be inert on this fixture, but turning it off changed the "
            f"stats:\n    pinning on  {native}\n    pinning off {no_pinning}"
        )
    if native != reference:
        failures.append(f"native and reference disagree:\n    native    {native}\n    reference {reference}")

    print("hand-derived cumulative counts after each tick "
          "(l1_hits, l1_accesses, l2_hits, l2_accesses), and this tick's own L2 hits:")
    for tick_i, expected in enumerate(EXPECTED_BY_TICK):
        with_pf, without_pf = PREFETCH_L2_HITS_PER_TICK[tick_i], NO_PREFETCH_L2_HITS_PER_TICK[tick_i]
        note = f"  <- without the prefetch this tick would give {without_pf}" if with_pf != without_pf else ""
        print(f"  tick {tick_i}: {expected}, {with_pf} L2 hit(s) this tick{note}")
    print(f"native   : {native}")
    print(f"reference: {reference}")
    print(f"  L1 {reference.l1_hit_rate}, L2 {reference.l2_hit_rate}, overall {reference.overall_hit_rate}")
    print(f"prefetch off: {no_prefetch}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: the cout prefetch turns ticks 1 and 5 into L2 hits that are misses without it, "
          "the boundary no-op leaves tick 3's hit on A intact, prefetch inserts are counted as "
          "neither accesses nor hits (L2 sees 6 accesses for 6 L1 misses, hit rate 3/6), and the "
          "native engine and the Python reference twin report identical stats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
