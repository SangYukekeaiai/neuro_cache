"""HierarchyStats: what a two-level (private L1s + shared L2) replay of
one sample reports, and the only place the four hit-rate formulas of
log/2026-08-03-l1-l2-cache-policy-plan.md are written down.

Counts, not rates, are what the engines produce: cache_replay_hierarchical
prints the integers and the Python reference twin
(dump/python_reference/cachesim/hierarchy.py) returns the same integers,
so the rate definitions exist once, here, instead of once per language.
Both paths build this same type, which is also what makes them directly
comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class HierarchyStats:
    # (core_id, l1_hits, l1_accesses) per core that was active at least
    # once, ascending by core_id. Cores are discovered from the trace: a
    # core absent from a tick simply issued nothing that tick, and core
    # ids are neither contiguous nor known up front.
    per_core_l1: Tuple[Tuple[int, int, int], ...]
    l1_hits: int
    l1_accesses: int
    # L2 sees L1-missed traffic only, so l2_accesses == l1_accesses - l1_hits.
    l2_hits: int
    l2_accesses: int

    @property
    def per_core_l1_hit_rates(self) -> Dict[int, float]:
        return {core_id: (hits / accesses if accesses else 0.0) for core_id, hits, accesses in self.per_core_l1}

    @property
    def l1_hit_rate(self) -> float:
        """Aggregate over every core's L1 access."""
        return self.l1_hits / self.l1_accesses if self.l1_accesses else 0.0

    @property
    def l2_hit_rate(self) -> float:
        """Over L1-missed traffic only, which is all L2 ever sees."""
        return self.l2_hits / self.l2_accesses if self.l2_accesses else 0.0

    @property
    def overall_hit_rate(self) -> float:
        """Share of core-issued line accesses served on chip, by either
        level -- equivalently, one minus the share that went off chip."""
        return (self.l1_hits + self.l2_hits) / self.l1_accesses if self.l1_accesses else 0.0


@dataclass(frozen=True)
class HierarchySweepResult:
    cache_type: str
    associativity: Optional[int]
    l1_size_bytes: int
    l2_size_bytes: int
    stats: HierarchyStats
