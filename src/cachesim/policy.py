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
from typing import Hashable


class LRUPolicy:
    """One cache set, `capacity` lines, least-recently-used eviction.
    Same logic the original FullyAssociativeLRUCache had; this is that
    same class, now scoped to mean "one set" instead of "the whole
    cache" now that cache.py composes many of these together."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f"LRUPolicy: capacity must be positive, got {capacity}")
        self.capacity = capacity
        self._lines: "OrderedDict[Hashable, None]" = OrderedDict()

    def access(self, tag: Hashable) -> bool:
        """Access tag; returns True on hit, False on miss. A hit moves
        tag to the most-recently-used end; a miss inserts it, evicting
        the least-recently-used line first if this set is full."""
        if tag in self._lines:
            self._lines.move_to_end(tag)
            return True
        if len(self._lines) >= self.capacity:
            self._lines.popitem(last=False)
        self._lines[tag] = None
        return False


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
