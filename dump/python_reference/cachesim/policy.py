"""Per-set replacement-policy implementations. A policy manages exactly
one cache SET's resident lines (up to `capacity` of them) -- cache.py's
Cache class creates one policy instance per set and routes each access to
the set (and therefore the policy instance) its tag maps to, so
cache_type (how many sets, how many ways each) and policy (which line a
given set evicts) compose independently: a fully-associative cache is
just "one set", a direct-mapped cache is "capacity_lines sets of 1 way
each", either way each individual set's own eviction behavior is exactly
this module's job, unaware of how many other sets exist.

Only LRUPolicy is real. The other four names in config.POLICIES are
declared (so CacheConfig validation and a future sweep harness can name
and enumerate them) but not yet built:
  - fifo/lfu/random: standard baselines, straightforward to add later.
  - input_activity: the ACTUAL hypothesis from
    log/2026-07-22-replacement-policy-cache-sim-plan.md ("prioritize
    retaining weights associated with the hot zone of the input spikes"),
    the reason this whole cache-sim effort exists. Needs a real design
    (it requires runtime spike-activity signal beyond a plain tag
    stream, not just this module's Hashable-in/bool-out interface), not
    a quick addition -- deliberately left for a dedicated round.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Hashable, Optional

# The lines one tick has pinned, tag -> that line's recency stamp from
# before this tick's touches. hierarchy.py builds one of these per tick
# out of the L2 lookups that hit, and access_pinned consults it: a pinned
# line is not evicted by this tick's own fills, and the stamps only break
# the overflow case where every resident line of the set is pinned. Empty
# means "nothing pinned", which is exactly plain LRU. C++ twin:
# src/cachesim/policy.h's PinStamps.
PinStamps = Dict[Hashable, int]


class LRUPolicy:
    """One cache set, `capacity` lines, least-recently-used eviction.
    Same logic the original FullyAssociativeLRUCache had; this is that
    same class, now scoped to mean "one set" instead of "the whole
    cache" now that cache.py composes many of these together."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f"LRUPolicy: capacity must be positive, got {capacity}")
        self.capacity = capacity
        # tag -> the counter value at that line's last access. Insertion
        # order is the recency order, least recently used first, and the
        # stamps say the same thing as a number the pin set can carry
        # around after this order has moved on.
        self._lines: "OrderedDict[Hashable, int]" = OrderedDict()
        self._clock = 0

    def access(self, tag: Hashable) -> bool:
        """Access tag; returns True on hit, False on miss. A hit moves
        tag to the most-recently-used end; a miss inserts it, evicting
        the least-recently-used line first if this set is full."""
        return self._insert_or_touch(tag, None)

    def access_pinned(self, tag: Hashable, pins: PinStamps) -> bool:
        """access() with this tick's pin set honored on eviction.
        Identical to access() whenever `pins` is empty, which is what lets
        the two-level engine reproduce its pre-pinning results exactly."""
        return self._insert_or_touch(tag, pins)

    def stamp(self, tag: Hashable) -> int:
        """When `tag` was last accessed, on this set's own monotonic
        counter. Recency order IS stamp order, so the smallest stamp is
        the LRU end; hierarchy.py reads a stamp while L2 still holds its
        start-of-tick state and hands it back as a pin, which is how
        "closest to LRU before this tick's touches" survives the touches
        that follow. Stamps are per set, and are only ever compared
        between lines of one set, so the per-instance counter is enough.
        KeyError if the line is not resident."""
        return self._lines[tag]

    def _insert_or_touch(self, tag: Hashable, pins: Optional[PinStamps]) -> bool:
        if tag in self._lines:
            self._lines.move_to_end(tag)
            self._clock += 1
            self._lines[tag] = self._clock  # assignment to a present key keeps its position
            return True
        if len(self._lines) >= self.capacity:
            del self._lines[self._victim(pins)]
        self._clock += 1
        self._lines[tag] = self._clock
        return False

    def _victim(self, pins: Optional[PinStamps]) -> Hashable:
        """Plain LRU takes the least-recently-used line. With a non-empty
        pin set the rule becomes: the LRU-most line that is NOT pinned,
        walking from the LRU end towards the MRU end. If the walk runs
        out, every resident line of this set was read this tick and
        protection has to give way to something: the plan's overflow
        fallback sacrifices the pinned line that was closest to LRU BEFORE
        this tick's touches, which is the smallest pinned stamp. Not the
        current LRU end, which this tick's own hit-touches have already
        reshuffled."""
        if not pins:
            return next(iter(self._lines))
        fallback = None
        for tag in self._lines:  # least recently used first
            if tag not in pins:
                return tag
            if fallback is None or pins[tag] < pins[fallback]:
                fallback = tag
        return fallback  # never None: a full set has at least one line

    def contains(self, tag: Hashable) -> bool:
        """Residency only: no move to the most-recently-used end, no
        insert on a miss. hierarchy.py resolves every core's L2 lookup
        within one tick against the set as it stood when the tick began,
        so it has to be able to ask "is this line resident?" without
        access()'s two side effects, either of which would let one core's
        same-tick lookup change what the next core sees."""
        return tag in self._lines


class _UnimplementedPolicy:
    """Base for declared-but-not-yet-built policies -- constructing one
    raises immediately, at Cache-construction time, not on the first
    access(), so a sweep enumerating policies fails fast per config
    rather than partway through a run."""

    name: str

    def __init__(self, capacity: int) -> None:
        raise NotImplementedError(
            f"policy {self.name!r} is declared in config.POLICIES for "
            f"completeness but not yet implemented"
        )


class FIFOPolicy(_UnimplementedPolicy):
    name = "fifo"


class LFUPolicy(_UnimplementedPolicy):
    name = "lfu"


class RandomPolicy(_UnimplementedPolicy):
    name = "random"


class InputActivityPolicy(_UnimplementedPolicy):
    name = "input_activity"


POLICY_CLASSES = {
    "lru": LRUPolicy,
    "fifo": FIFOPolicy,
    "lfu": LFUPolicy,
    "random": RandomPolicy,
    "input_activity": InputActivityPolicy,
}
