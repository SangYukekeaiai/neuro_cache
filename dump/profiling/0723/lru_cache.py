"""Fully-associative cache with LRU replacement, for replaying a tagged
weight-access stream. No index/set partitioning -- any tag can occupy any
of the cache's `capacity` resident lines; associativity is deferred.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Hashable, List, Sequence


class FullyAssociativeLRUCache:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self.capacity = capacity
        self._lines: "OrderedDict[Hashable, None]" = OrderedDict()

    def access(self, tag: Hashable) -> bool:
        """Access tag; returns True on hit, False on miss. A hit moves
        tag to the most-recently-used end; a miss inserts it, evicting
        the least-recently-used line first if the cache is full."""
        if tag in self._lines:
            self._lines.move_to_end(tag)
            return True
        if len(self._lines) >= self.capacity:
            self._lines.popitem(last=False)
        self._lines[tag] = None
        return False


def replay(cache: FullyAssociativeLRUCache, tags: Sequence[Hashable]) -> List[bool]:
    """Replay a tag stream through cache in order, returning one
    hit/miss bool per access."""
    return [cache.access(tag) for tag in tags]
