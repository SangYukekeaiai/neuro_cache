"""Cache: one class implementing all 3 declared cache types
(fully_associative, set_associative, direct_mapped) uniformly, since all
three are really "N sets of M ways each" with different (N, M):

  fully_associative:  N=1,               M=capacity_lines
  direct_mapped:       N=capacity_lines,   M=1
  set_associative:      N=capacity_lines/associativity, M=associativity

Each set is independently managed by one policy.py instance (LRU today),
so cache_type (structural: how many sets/ways) and policy (which line a
given set evicts) compose independently instead of being one hardcoded
class per (type, policy) pair.
"""

from __future__ import annotations

from typing import Hashable, List, Sequence, Tuple

from .config import CacheConfig
from .policy import POLICY_CLASSES


def _num_sets_and_ways(config: CacheConfig) -> Tuple[int, int]:
    """(num_sets, ways_per_set) for config.cache_type. Validated
    elsewhere (CacheConfig.__post_init__) that associativity is set iff
    cache_type == "set_associative", and that capacity_lines is evenly
    divisible by associativity when it applies -- both already true by
    the time a CacheConfig instance exists, so not re-checked here."""
    capacity = config.capacity_lines
    if config.cache_type == "fully_associative":
        return 1, capacity
    if config.cache_type == "direct_mapped":
        return capacity, 1
    if config.cache_type == "set_associative":
        return capacity // config.associativity, config.associativity
    raise ValueError(f"unknown cache_type {config.cache_type!r}")  # unreachable, CacheConfig already validated


class Cache:
    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self.num_sets, self.ways = _num_sets_and_ways(config)

        policy_cls = POLICY_CLASSES[config.policy]
        # One independent policy instance per set -- set A's LRU order
        # (or whichever policy) never depends on what's resident in set B.
        self._sets = [policy_cls(capacity=self.ways) for _ in range(self.num_sets)]

    def _set_index(self, tag: Sequence[int]) -> int:
        """Which of the num_sets sets `tag` maps to. `tag` is a 4-int
        cache-line coordinate (layout.tag_for_element's output), not a
        linear address, so there's no real hardware bit-selection to
        replicate here -- sum-of-components modulo num_sets is a simple,
        deterministic, fully-documented stand-in, not a claim about real
        address-decoder behavior. Degenerates to always 0 when
        num_sets == 1 (the fully-associative case), matching that every
        tag is a "hit-eligible-anywhere" candidate there."""
        if self.num_sets == 1:
            return 0
        return sum(tag) % self.num_sets

    def access(self, tag: Sequence[int]) -> bool:
        """Access tag; returns True on hit, False on miss. Delegates
        entirely to whichever set's policy instance `tag` maps to."""
        return self._sets[self._set_index(tag)].access(tag)


def replay(cache: Cache, tags: Sequence[Hashable]) -> List[bool]:
    """Replay a tag stream through cache in order, returning one
    hit/miss bool per access."""
    return [cache.access(tag) for tag in tags]


def hit_rate(hits: Sequence[bool]) -> float:
    return (sum(hits) / len(hits)) if hits else 0.0
