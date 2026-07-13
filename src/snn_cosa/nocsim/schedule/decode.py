"""Decode the solved MIP x-variables into simulation-ready loop structures.

Three things are extracted from the binary solution:

  spatial_factors[dim]   — product of all spatial (k=0) prime factors at NoCLevel
                            permutation slots for each dimension.  These determine
                            the PE grid under the Way-2 layout.

  noc_temporal_loops     — ordered list of temporal (k=1) factors assigned to
                            NoCLevel slots [gb_start, dram_start); one LoopItem
                            per active prime factor, sorted inner → outer.

  dram_temporal_loops    — same for OffChip slots [dram_start, dram_start+P).

  data_size[var]         — element count of each variable's GB tile.  This equals
                            the product of ALL factors (spatial and temporal) at
                            levels strictly inside the DRAM boundary (i < dram_start)
                            for every dimension that affects var (A[j][v] = 1).

Level layout (from schedule.py)
--------------------------------
  level 0                         NodeLevel  (no permutation)
  levels [gb_start, dram_start)   NoCLevel   permutation slots
  levels [dram_start, dram_end)   OffChip    permutation slots

  gb_start   = SNN_GB_START_LEVEL = 1
  perm_levels = sum(len(f_j) for f_j in prob.prob_factors)
  dram_start  = gb_start + perm_levels
  dram_end    = dram_start + perm_levels  (= total_levels - 1 + 1)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
import operator
from typing import Any, Dict, List

from snn_cosa.model.constants import _A, NUM_VARS, VAR_NAMES
from snn_cosa.model.schedule import SNN_GB_START_LEVEL
from snn_cosa.parsers.layer import SNNProb, _get_prime_factors


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LoopItem:
    """One active prime-factor assignment from the MIP solution.

    Attributes:
        dim:      Dimension index (DIM_KH=0 … DIM_T=6).
        dim_name: Human-readable name ("KH", "WO", "T", …).
        factor:   Loop bound (a prime factor of the full dimension size).
        level:    MIP loop-level index where this factor was assigned.
                  Lower index = more inner loop.
    """
    dim:      int
    dim_name: str
    factor:   int
    level:    int   # lower = more inner


@dataclass
class Schedule:
    """Decoded loop structure ready for the NoC simulator.

    Attributes:
        spatial_factors:     dim_idx → product of spatial prime factors
                             (k=0) assigned to NoCLevel perm slots.
                             A value of 1 means that dimension is not
                             spatially unrolled.
        noc_temporal_loops:  LoopItems for NoCLevel temporal factors,
                             sorted inner → outer (ascending level index).
        dram_temporal_loops: LoopItems for OffChip temporal factors,
                             sorted inner → outer.
        data_size:           var_name → element count of the GB tile for
                             that variable.  Used to compute packet counts.
        gb_start:            First NoCLevel permutation slot index.
        dram_start:          First OffChip permutation slot index.
        perm_levels:         Total prime-factor count (= slots per boundary).
    """
    spatial_factors:     Dict[int, int]
    noc_temporal_loops:  List[LoopItem]
    dram_temporal_loops: List[LoopItem]
    data_size:           Dict[str, int]
    gb_start:            int
    dram_start:          int
    perm_levels:         int

    @property
    def noc_num_steps(self) -> int:
        """Total number of NoC temporal iterations (product of all NoCLevel loop bounds)."""
        result = 1
        for item in self.noc_temporal_loops:
            result *= item.factor
        return result

    @property
    def dram_num_steps(self) -> int:
        """Total number of DRAM temporal iterations."""
        result = 1
        for item in self.dram_temporal_loops:
            result *= item.factor
        return result


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode(x: Dict, prob: SNNProb) -> Schedule:
    """Extract spatial and temporal loop structure from the solved MIP solution.

    Args:
        x:    Solved Gurobi binary variables {(i, j, n, k): Var} whose .X
              attribute carries the solved value (0.0 or 1.0).
        prob: Parsed SNN layer (prime-factor lists, dimension name maps).

    Returns:
        Schedule populated with spatial_factors, temporal loop lists, and
        data_size.
    """
    pf = prob.prob_factors
    gb_start    = SNN_GB_START_LEVEL                         # = 1
    perm_levels = sum(len(f_j) for f_j in pf)               # total prime factor count
    dram_start  = gb_start + perm_levels

    # ------------------------------------------------------------------
    # 1. Spatial factors — k=0 assignments at NoCLevel perm slots
    #    (NodeLevel k=0 is constrained to 0 when no local_buffer, and
    #    for the NoC sim we care about the inter-node spatial grid only)
    # ------------------------------------------------------------------
    spatial_factors: Dict[int, int] = {j: 1 for j in range(prob.prob_levels)}
    for i in range(gb_start, dram_start):
        for j, f_j in enumerate(pf):
            for n, factor in enumerate(f_j):
                if x[(i, j, n, 0)].X > 0.5:
                    spatial_factors[j] *= factor

    # ------------------------------------------------------------------
    # 2. NoCLevel temporal loops — k=1 at levels [gb_start, dram_start)
    #    Sorted ascending by level → inner-to-outer order.
    # ------------------------------------------------------------------
    noc_items: List[LoopItem] = []
    for i in range(gb_start, dram_start):
        for j, f_j in enumerate(pf):
            for n, factor in enumerate(f_j):
                if x[(i, j, n, 1)].X > 0.5:
                    noc_items.append(LoopItem(
                        dim=j,
                        dim_name=prob.prob_idx_name_dict[j],
                        factor=factor,
                        level=i,
                    ))
    noc_items.sort(key=lambda it: it.level)

    # ------------------------------------------------------------------
    # 3. OffChip temporal loops — k=1 at levels [dram_start, dram_end)
    # ------------------------------------------------------------------
    dram_end = dram_start + perm_levels
    dram_items: List[LoopItem] = []
    for i in range(dram_start, dram_end):
        for j, f_j in enumerate(pf):
            for n, factor in enumerate(f_j):
                if x[(i, j, n, 1)].X > 0.5:
                    dram_items.append(LoopItem(
                        dim=j,
                        dim_name=prob.prob_idx_name_dict[j],
                        factor=factor,
                        level=i,
                    ))
    dram_items.sort(key=lambda it: it.level)

    # ------------------------------------------------------------------
    # 4. Data size at GB boundary — element count per variable's GB tile
    #    Include every factor (spatial or temporal) at levels < dram_start
    #    for dimensions where A[j][v] = 1.
    #    Mirrors _eval_util in metrics.py but counts elements (not bytes).
    # ------------------------------------------------------------------
    data_size: Dict[str, int] = {}
    for v in range(NUM_VARS):
        size = 1
        for i in range(dram_start):
            for j, f_j in enumerate(pf):
                if _A[j][v] == 0:
                    continue
                for n, factor in enumerate(f_j):
                    if x[(i, j, n, 0)].X > 0.5 or x[(i, j, n, 1)].X > 0.5:
                        size *= factor
        data_size[VAR_NAMES[v]] = size

    return Schedule(
        spatial_factors=spatial_factors,
        noc_temporal_loops=noc_items,
        dram_temporal_loops=dram_items,
        data_size=data_size,
        gb_start=gb_start,
        dram_start=dram_start,
        perm_levels=perm_levels,
    )


# ---------------------------------------------------------------------------
# Strategy-based reconstruction  (no Gurobi required)
# ---------------------------------------------------------------------------

def _expand_loops(
    entries: List[Dict[str, Any]],
    name_to_idx: Dict[str, int],
    start_level: int,
) -> List[LoopItem]:
    """Expand a list of {dim, size} strategy entries into prime-factor LoopItems.

    Each entry may carry a fused (composite) size.  The expansion sorts prime
    factors ascending within each entry so the inner-most sub-factor is the
    smallest prime — consistent with the MIP solver's ordering convention.

    Args:
        entries:     Loop entries already in inner-to-outer order.
        name_to_idx: Dimension name → dim index map from SNNProb.
        start_level: First synthetic level index (incremented per prime factor).

    Returns:
        List of LoopItems in inner-to-outer order with synthetic level numbers.
    """
    items: List[LoopItem] = []
    level = start_level
    for entry in entries:
        j      = name_to_idx[entry["dim"]]
        primes = sorted(_get_prime_factors(entry["size"]))   # small → large = inner → outer
        for p in primes:
            items.append(LoopItem(dim=j, dim_name=entry["dim"], factor=p, level=level))
            level += 1
    return items


def schedule_from_strategy(strategy: Dict[str, Any], prob: SNNProb) -> Schedule:
    """Reconstruct a Schedule from the JSON strategy dict (no Gurobi needed).

    The strategy is the dict stored under the ``'strategy'`` key in the solver
    JSON output.  It uses three sub-dicts:

    * ``NoCLevel.spatial_splitting.loops``        — inner-to-outer spatial dims
    * ``NoCLevel.temporal_permutation.loops``     — **outer-to-inner** in JSON
    * ``DRAM.temporal_permutation.loops``         — **outer-to-inner** in JSON

    NodeLevel factors are not stored explicitly; they are implied by the
    remainder after NoCLevel and DRAM factors are accounted for.

    data_size formula::

        data_size[v] = ∏_{j: A[j][v]=1}  prob_bound[j] / dram_factor[j]

    where dram_factor[j] is the product of all DRAM temporal factors for dim j
    (defaulting to 1 if dim j does not appear in DRAM).

    Args:
        strategy: The ``strategy`` dict from the solver JSON output.
        prob:     Parsed SNN layer (dimension bounds and prime-factor lists).

    Returns:
        Schedule ready for BufSpatial / StepInfo / combine.
    """
    pf          = prob.prob_factors
    perm_levels = sum(len(f_j) for f_j in pf)
    gb_start    = SNN_GB_START_LEVEL       # = 1
    dram_start  = gb_start + perm_levels
    n2i         = prob.prob_name_idx_dict  # "KH" → 0, …, "T" → 6

    # ── 1. Spatial factors ────────────────────────────────────────────────
    spatial_factors: Dict[int, int] = {j: 1 for j in range(prob.prob_levels)}
    for entry in strategy["NoCLevel"]["spatial_splitting"]["loops"]:
        j = n2i[entry["dim"]]
        spatial_factors[j] *= entry["size"]

    # ── 2. NoCLevel temporal loops — JSON is outer-to-inner; reverse ──────
    noc_json  = list(reversed(strategy["NoCLevel"]["temporal_permutation"]["loops"]))
    noc_items = _expand_loops(noc_json, n2i, start_level=gb_start)

    # ── 3. DRAM temporal loops — JSON is outer-to-inner; reverse ─────────
    dram_json  = list(reversed(strategy["DRAM"]["temporal_permutation"]["loops"]))
    dram_items = _expand_loops(dram_json, n2i, start_level=dram_start)

    # ── 4. data_size — GB tile element count per variable ─────────────────
    # All factors at levels < dram_start (NoCLevel + NodeLevel) equal
    # prob_bound[j] divided by whatever is at DRAM level.
    dram_totals: Dict[int, int] = {}
    for item in dram_items:
        dram_totals[item.dim] = dram_totals.get(item.dim, 1) * item.factor

    data_size: Dict[str, int] = {}
    for v in range(NUM_VARS):
        size = 1
        for j, factors in enumerate(pf):
            if _A[j][v] == 0:
                continue
            total_j = reduce(operator.mul, factors, 1)
            dram_j  = dram_totals.get(j, 1)
            size   *= total_j // dram_j
        data_size[VAR_NAMES[v]] = size

    return Schedule(
        spatial_factors=spatial_factors,
        noc_temporal_loops=noc_items,
        dram_temporal_loops=dram_items,
        data_size=data_size,
        gb_start=gb_start,
        dram_start=dram_start,
        perm_levels=perm_levels,
    )
