"""Stack-distance (reuse-distance) and footprint analysis over an ordered
weight-address stream.

Stack distance (Mattson et al., 1970): for an access to address `a` that
was last referenced at an earlier position `j`, the stack distance is the
number of DISTINCT addresses referenced strictly between `j` and the
current position -- i.e. how many distinct weight lines an LRU cache
would need to hold to have captured that reuse. A first-time access has
no finite stack distance (None -- a cold miss regardless of cache size).

Computed via a Fenwick (binary indexed) tree over "is this timestep
currently the most-recent occurrence of some address" -- O(n log n) total
for a stream of n accesses. This project's real per-schedule address
streams are small (tens to low thousands of entries, see the live-wiring
plan's sweep), so this reference-model implementation favors clarity over
the streaming/approximate reuse-distance algorithms built for OS-trace-
scale (billions of accesses) analysis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _Fenwick:
    """1-indexed internally; supports point update and range sum over
    0-indexed positions [0, n-1]."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.tree = [0] * (n + 1)

    def update(self, pos: int, delta: int) -> None:
        i = pos + 1
        while i <= self.n:
            self.tree[i] += delta
            i += i & (-i)

    def _prefix_sum(self, pos: int) -> int:
        """Sum over 0-indexed [0, pos] inclusive."""
        if pos < 0:
            return 0
        i = pos + 1
        s = 0
        while i > 0:
            s += self.tree[i]
            i -= i & (-i)
        return s

    def range_sum(self, lo: int, hi: int) -> int:
        """Sum over 0-indexed [lo, hi] inclusive; 0 if lo > hi."""
        if lo > hi:
            return 0
        return self._prefix_sum(hi) - self._prefix_sum(lo - 1)


def stack_distances(addresses: List[Any]) -> List[Optional[int]]:
    """Return one stack distance per access, `None` for first occurrences.

    Args:
        addresses: ordered, hashable weight addresses (e.g. the
                   (kh,kw,cin,cout_off,cout_end) tuples every arch's
                   event_to_address/weight_addresses produces).

    Returns:
        List of the same length as `addresses`; entry i is the stack
        distance of addresses[i] (None if this is that address's first
        occurrence in the stream).
    """
    n = len(addresses)
    fen = _Fenwick(n)
    last_seen: Dict[Any, int] = {}
    distances: List[Optional[int]] = []

    for i, addr in enumerate(addresses):
        if addr in last_seen:
            j = last_seen[addr]
            distances.append(fen.range_sum(j + 1, i - 1))
            fen.update(j, -1)
        else:
            distances.append(None)
        fen.update(i, 1)
        last_seen[addr] = i

    return distances


def reuse_distance_histogram(distances: List[Optional[int]]) -> Dict[int, int]:
    """Bucket finite stack distances into a {distance: count} histogram.

    First-occurrence (None) entries are excluded -- they have no finite
    reuse distance to bucket.
    """
    hist: Dict[int, int] = {}
    for d in distances:
        if d is not None:
            hist[d] = hist.get(d, 0) + 1
    return hist


def footprint_curve(addresses: List[Any], max_window: int = 64) -> Dict[int, float]:
    """{window_size: avg_distinct_addresses_touched}, for window sizes
    1..min(max_window, len(addresses)).

    For each window size w, slides a length-w window across the whole
    stream and averages the number of distinct addresses inside it --
    the working-set-vs-capacity curve: "how many unique weight lines does
    an on-chip cache of this capacity need to hold this tile's reuse."

    O(n * max_window) -- max_window defaults to a modest 64 to keep this
    reference implementation's runtime bounded regardless of stream
    length; pass a larger value explicitly if a wider curve is needed for
    a specific (small) stream.
    """
    n = len(addresses)
    if n == 0:
        return {}
    max_window = min(max_window, n)

    curve: Dict[int, float] = {}
    for w in range(1, max_window + 1):
        window_counts: Dict[Any, int] = {}
        distinct = 0
        total = 0
        samples = 0
        for i in range(n):
            addr = addresses[i]
            window_counts[addr] = window_counts.get(addr, 0) + 1
            if window_counts[addr] == 1:
                distinct += 1
            if i >= w:
                old = addresses[i - w]
                window_counts[old] -= 1
                if window_counts[old] == 0:
                    distinct -= 1
            if i >= w - 1:
                total += distinct
                samples += 1
        curve[w] = total / samples if samples else 0.0

    return curve