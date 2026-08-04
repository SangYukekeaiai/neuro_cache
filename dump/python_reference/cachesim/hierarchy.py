"""Two-level cache orchestration: one private L1 Cache per core plus one
shared L2 Cache, driven one tick at a time out of the Stage 1 nested
weight trace (tiles -> ticks -> cores -> weight_addresses). Implements
the "Two-level hierarchy semantics" and "L2 cout-prefetch policy"
sections of log/2026-08-03-l1-l2-cache-policy-plan.md.

The cout prefetch and the same-tick pinning are switches, not fixed
behavior: with both off this engine reproduces its own pre-prefetch,
pre-pinning results exactly, which is what makes each of the two
separately testable.

cache.py's Cache is the single-cache building block, reused unchanged and
instantiated once per core plus once shared. Nothing here reimplements
replacement logic; this module only sequences accesses across those
instances.

Twin of src/cachesim/hierarchy.h -- same class and method names, same
order of operations, same statistics. The two are meant to be read side
by side and changed together. This is the reference implementation the
native one is checked against (debug/14_verify_l1_l2_miss_fill.py); the
native path is what real sweeps run.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from cachesim.config import CacheConfig
from cachesim.stats import HierarchyStats
from .cache import Cache
from .layout import element_tags, expand_events, hybrid_cout_lines, pack_tags
from .policy import PinStamps


class CoreRequest(NamedTuple):
    """One core's weight fetches at one tick, already expanded to packed
    cache-line tags in issue order (per-burst deduped, the same rule
    sweep._burst_hits uses for the single-level replay)."""

    core_id: int
    packed_tags: List[int]


class _CoreLevel1:
    def __init__(self, config: CacheConfig) -> None:
        self.cache = Cache(config)
        self.hits = 0
        self.accesses = 0


class TwoLevelHierarchy:
    def __init__(
        self,
        l1_config: CacheConfig,
        l2_config: CacheConfig,
        *,
        l2_prefetch: bool,
        same_tick_pinning: bool,
    ) -> None:
        """l2_prefetch: insert the next cout block alongside every L2
        demand miss. same_tick_pinning: protect a line that was read as an
        L2 hit this tick from this tick's own fills. Both are required
        arguments, in this language and in the C++ twin, so neither side
        owns a default the other could drift from."""
        self.l1_config = l1_config
        self._l1: Dict[int, _CoreLevel1] = {}
        self._l2 = Cache(l2_config)
        self._l2_prefetch = l2_prefetch
        self._same_tick_pinning = same_tick_pinning
        self._cout_lines = hybrid_cout_lines(l2_config)
        self._pending_fills: List[int] = []
        self._pins: PinStamps = {}
        self._l2_hits = 0
        self._l2_accesses = 0

    def run_tick(self, cores: Sequence[CoreRequest]) -> None:
        """One tick of lock-step execution. `cores` must be in ascending
        core_id order: that is both the order the L2 lookups are recorded
        in and the order this tick's fills are applied in, which the plan
        fixes as core-ascending. The on-disk order within a tick is not
        guaranteed to be sorted (tracegen.merge_cores_by_tick appends in
        whatever order the per-core results were collected), so the
        caller sorts and this checks."""
        for earlier, later in zip(cores, cores[1:]):
            if earlier.core_id >= later.core_id:
                raise ValueError("run_tick needs cores in ascending core_id order")

        # -- Lookup phase ---------------------------------------------
        # Every L1 check and every resulting L2 lookup for this tick is
        # resolved here, against L2 exactly as it stood when the tick
        # began. Cores in one tick run in lock-step, so they are
        # concurrent, not sequential: none of them may observe another
        # core's same-tick fill. That is why the L2 question is asked
        # with contains(), a pure residency test, and not with access():
        # access() moves recency and inserts on a miss, so core k's miss
        # would turn into core k+1's hit inside the same tick.
        self._pending_fills.clear()
        self._pins.clear()
        for request in cores:
            core = self._l1_for(request.core_id)
            for tag in request.packed_tags:
                core.accesses += 1
                if core.cache.access(tag):
                    core.hits += 1
                    continue
                # That access() already inserted the line, which IS the
                # inclusive L1 fill: whether the line comes back from L2
                # or from off chip, the requesting core's L1 gets it.
                # Filling an L1 in place is safe where filling L2 in
                # place is not, because an L1 is private to one core.
                self._l2_accesses += 1
                self._pending_fills.append(tag)
                if self._l2.contains(tag):
                    self._l2_hits += 1
                    # Pin it, carrying the stamp it has right now: L2 is
                    # still in its start-of-tick state, so this is the
                    # recency the overflow fallback is defined against. A
                    # repeated hit on one tag re-reads the same stamp, so
                    # which core wins the insert does not matter.
                    if self._same_tick_pinning:
                        self._pins[tag] = self._l2.stamp(tag)
                elif self._l2_prefetch:
                    # Prefetch on an L2 MISS only, one cout block ahead,
                    # no chaining. Queued as a fill rather than inserted
                    # here: an insert during the lookup phase would be
                    # visible to the same tick's later lookups and would
                    # break the tick-atomic snapshot the whole phase split
                    # exists to keep. It is also not counted as an access
                    # or a hit anywhere, so a prefetch can never move the
                    # reported L2 hit rate by itself.
                    target = self._prefetch_target(tag)
                    if target is not None:
                        self._pending_fills.append(target)

        # -- Fill phase -----------------------------------------------
        # Only now do this tick's L2 updates land, producing the state
        # the NEXT tick's lookups see. _pending_fills was built in
        # core-ascending order above, so replaying it in order is the
        # core-ascending application the plan specifies. Every kind of
        # fill replays as one access_pinned(): a lookup that hit becomes a
        # hit-touch, a lookup that missed becomes a demand insert, a
        # prefetch becomes an insert right behind the demand insert that
        # triggered it, and an L2 miss fills L2 as well as L1 (the
        # off-chip fetch itself is unmodeled). They all take the pin set,
        # including the prefetches: a prefetch is one of this tick's own
        # fills, so it may not throw out a line another core read this
        # tick either.
        #
        # With _pins empty (pinning off, or a tick with no L2 hit) this
        # loop is exactly the plain-access() fill phase it replaces. With
        # _pins non-empty, a line read as a hit is no longer evicted and
        # re-fetched inside its own tick, except in the overflow case
        # policy.py's _victim spells out.
        for tag in self._pending_fills:
            self._l2.access_pinned(tag, self._pins)

    def _prefetch_target(self, tag: int) -> Optional[int]:
        """The tag one cout block ahead of `tag`, or None when there is
        none. cout is the packed tag's innermost component (layout.py's
        pack_tags multiplies it by nothing), so the neighbouring cout
        block is simply the next packed value, and the packing is what
        keeps this cheap: no unpack/repack per L2 miss. The layer ends
        where tag's own cout component is the last block of the layer's
        true COUT, and there the prefetch is a no-op rather than a wrap
        into the next cin block. Distance is one block, fixed by the plan,
        so it is written here rather than made a knob; the C++ twin says
        the same thing in src/cachesim/hierarchy.h."""
        return tag + 1 if (tag % self._cout_lines) + 1 < self._cout_lines else None

    def _l1_for(self, core_id: int) -> _CoreLevel1:
        """Cores are created the first time they appear: a core absent
        from a tick simply issued nothing that tick, and core ids are
        neither contiguous nor known up front."""
        core = self._l1.get(core_id)
        if core is None:
            core = _CoreLevel1(self.l1_config)
            self._l1[core_id] = core
        return core

    def stats(self) -> HierarchyStats:
        per_core = tuple(
            (core_id, self._l1[core_id].hits, self._l1[core_id].accesses) for core_id in sorted(self._l1)
        )
        return HierarchyStats(
            per_core_l1=per_core,
            l1_hits=sum(core.hits for core in self._l1.values()),
            l1_accesses=sum(core.accesses for core in self._l1.values()),
            l2_hits=self._l2_hits,
            l2_accesses=self._l2_accesses,
        )


def burst_packed_tags(events: Sequence[Any], config: CacheConfig, order: Sequence[str]) -> List[int]:
    """Per burst, not per weight value, exactly as sweep._burst_hits does
    it: one weight_addresses event is one memory transaction, so its
    expanded elements collapse to the DISTINCT consecutive line tags that
    burst touches. Dedup never crosses an event boundary."""
    tags = []
    for event in events:
        prev = None
        for tag in element_tags(expand_events([event], order), config):
            if tag != prev:
                tags.append(tag)
                prev = tag
    return pack_tags(tags, config)


def replay_sample(
    sample: Dict[str, Any],
    l1_config: CacheConfig,
    l2_config: CacheConfig,
    order: Sequence[str],
    *,
    l2_prefetch: bool,
    same_tick_pinning: bool,
) -> HierarchyStats:
    """Replay one Stage 1 nested sample (already loaded from its
    .json.gz) through a fresh two-level hierarchy. Tiles are walked in
    file order and their ticks concatenated: a tile boundary is also a
    tick boundary, so nothing crosses it, and cache state persists across
    tiles the same way it does across ticks."""
    shared = ("layout", "line_size_bytes", "cin_block", "cout_block", "kh_bound", "kw_bound", "cin_bound", "cout_bound")
    differing = [f for f in shared if getattr(l1_config, f) != getattr(l2_config, f)]
    if differing:
        # The plan gives L1 and L2 one shared layout formula and one
        # shared line size, differing only in capacity and structure. The
        # native CLI takes those arguments once so a mismatch cannot be
        # expressed; here two configs are passed, so it is checked.
        raise ValueError(f"L1 and L2 must agree on the line layout, they differ in {differing}")
    if l1_config.layout != "hybrid":
        raise ValueError("the hierarchical replay is defined on layout='hybrid' only")

    hierarchy = TwoLevelHierarchy(
        l1_config, l2_config, l2_prefetch=l2_prefetch, same_tick_pinning=same_tick_pinning
    )
    for tile in sample["tiles"]:
        for tick in tile["ticks"]:
            cores = [
                CoreRequest(core["core_id"], burst_packed_tags(core["weight_addresses"], l1_config, order))
                for core in sorted(tick["cores"], key=lambda c: c["core_id"])
            ]
            hierarchy.run_tick(cores)
    return hierarchy.stats()
