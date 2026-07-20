#!/usr/bin/env python3
"""Distinct-address distance D_C (plan Sec 3 primary metric, Sec 4.3 algorithm).

D_C(t, s) = number of DISTINCT weight coordinates touched in the interval (t, s]
of the access stream. Unlike D_A = s - t (the raw access-count gap, milestone 2),
repeats of the same address cost nothing extra, so D_C predicts the weight-buffer
capacity needed to keep an anchor resident until its neighbor fires. D_C <= D_A
always (plan Sec 3, Sec 8 invariant).

Two reusable functions:

  dc_bit_sweep(stream, pairs)  - the offline Fenwick/BIT last-occurrence sweep of
      plan Sec 4.3, verbatim: sort queries by s ascending, sweep a BIT over stream
      positions tracking each coordinate's last_pos (decrement-then-increment on a
      repeat), read D_C = BIT.range_sum(t+1, s). O((N + Q) log N).

  dc_bruteforce(stream, t, s)  - the naive validator len(set(a[t+1:s+1])), used by
      the Sec 8 known-answer check to confirm the BIT sweep exactly.
"""
from __future__ import annotations


class Fenwick:
    """Binary indexed tree over 0-indexed positions: point add, inclusive range sum."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.tree = [0] * (n + 1)

    def add(self, i: int, delta: int) -> None:
        i += 1
        while i <= self.n:
            self.tree[i] += delta
            i += i & (-i)

    def _prefix(self, i: int) -> int:
        """Sum over positions [0, i] (i 0-indexed)."""
        i += 1
        s = 0
        while i > 0:
            s += self.tree[i]
            i -= i & (-i)
        return s

    def range_sum(self, lo: int, hi: int) -> int:
        """Sum over positions [lo, hi] inclusive (0-indexed); 0 if hi < lo."""
        if hi < lo:
            return 0
        return self._prefix(hi) - (self._prefix(lo - 1) if lo > 0 else 0)


def dc_bit_sweep(stream: list, pairs: list) -> list:
    """D_C for each (t, s) in `pairs`, returned in the SAME order as `pairs`.

    Faithful to plan Sec 4.3: distinct coords in (t, s] = number of coords whose
    last occurrence <= s falls in (t, s], answered offline by sorting on s.
    Requires t < s for every pair (the resolved-pair case).
    """
    N = len(stream)
    dc = [0] * len(pairs)
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][1])  # by s ascending
    bit = Fenwick(N)
    last_pos: dict = {}
    cur = 0
    for idx in order:
        t, s = pairs[idx]
        while cur <= s:
            coord = stream[cur]
            if coord in last_pos:
                bit.add(last_pos[coord], -1)
            bit.add(cur, +1)
            last_pos[coord] = cur
            cur += 1
        dc[idx] = bit.range_sum(t + 1, s)
    return dc


def dc_bruteforce(stream: list, t: int, s: int) -> int:
    """Naive distinct-count in (t, s]; the plan Sec 8 known-answer reference."""
    return len(set(stream[t + 1:s + 1]))
