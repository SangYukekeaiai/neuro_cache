"""Per-step position flags for the SNN-CoSA NoC simulator.

Each temporal step is a unique (dram_i, noc_i) pair.  For each pair, the
simulator needs to know whether the combined iteration across BOTH loop levels
(DRAM + NoCLevel) is at the first or last position for the K-reduction group
and for the T-timestep group.

These flags drive skip conditions in combine.py:

    is_first_K → skip psum load from GB   (no prior psum to accumulate)
    is_last_K  → fire LIF + T-chain        (all reduction done)
    is_first_T → skip vmem load from GB   (no prior vmem to carry)
    is_last_T  → skip vmem store to GB    (result is not the final vmem yet)

Dimension groups
-----------------
K group (reduction dims): KH (j=0), KW (j=1), CIN (j=2)
T group (timestep dim):   T  (j=6)

For a dim that appears in BOTH NoCLevel and DRAM temporal loops, the
combined iteration count is:

    combined_total_j = noc_total_j × dram_total_j
    combined_idx_j   = noc_idx_j   + noc_total_j × dram_idx_j

    is_last_j  ⟺  combined_idx_j == combined_total_j - 1
    is_first_j ⟺  combined_idx_j == 0

If a dim has no loops at a level its total for that level defaults to 1
(no variation → trivially first AND last at that level).

Multi-factor dims
-----------------
A single dimension j may appear in more than one LoopItem at the same level
(e.g. KH=6=2×3 → two LoopItems both with dim=KH).  _decode_dim() handles
this by accumulating a mixed-radix counter for that dim:

    idx_j = inner_loop_idx + inner_total × outer_loop_idx
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Tuple

from snn_cosa.parsers.layer import SNNProb, SNN_REDUCTION_DIMS, DIM_T, DIM_COUT
from .decode import LoopItem, Schedule


# Convenience alias: K dims and T dim as frozensets
_K_DIMS:      FrozenSet[int] = SNN_REDUCTION_DIMS              # {KH, KW, CIN}
_T_DIM:       FrozenSet[int] = frozenset([DIM_T])              # {T}
_WEIGHT_DIMS: FrozenSet[int] = _K_DIMS | frozenset([DIM_COUT]) # {KH, KW, CIN, COUT}


class StepInfo:
    """Computes (is_first, is_last) position flags for any (dram_i, noc_i) pair.

    Args:
        schedule: Decoded schedule containing noc_temporal_loops and
                  dram_temporal_loops.
        prob:     Parsed SNN layer (kept for API symmetry; not directly used).
    """

    def __init__(self, schedule: Schedule, _prob: SNNProb) -> None:
        self._noc  = schedule.noc_temporal_loops    # inner → outer
        self._dram = schedule.dram_temporal_loops   # inner → outer

        # Pre-compute per-dim total iteration counts at each level
        self._noc_totals:  Dict[int, int] = _compute_totals(self._noc)
        self._dram_totals: Dict[int, int] = _compute_totals(self._dram)

        # ------------------------------------------------------------------
        # Traffic-free flags — structural properties of the loop ordering,
        # computed once and reused for every (dram_i, noc_i) iteration.
        # ------------------------------------------------------------------

        # DRAM-level: evaluated against dram_temporal_loops only
        self.is_psum_dram_free: bool = _is_dims_innermost(self._dram, _K_DIMS)
        self.is_vmem_dram_free: bool = _is_dims_innermost(self._dram, _T_DIM)

        # GB-level: evaluated against the integrated loop (NoC inner, DRAM outer)
        _integrated = self._noc + self._dram
        self.is_psum_gb_free: bool = _is_dims_innermost(_integrated, _K_DIMS)
        self.is_vmem_gb_free: bool = _is_dims_innermost(_integrated, _T_DIM)

    # ------------------------------------------------------------------
    # Public API — combined (DRAM + NoCLevel) position
    # ------------------------------------------------------------------

    def k_position(self, dram_i: int, noc_i: int) -> Tuple[bool, bool]:
        """Combined K position across DRAM + NoCLevel temporal loops.

        Returns:
            (is_first_K, is_last_K)
        """
        return self._combined_position(dram_i, noc_i, _K_DIMS)

    def t_position(self, dram_i: int, noc_i: int) -> Tuple[bool, bool]:
        """Combined T position across DRAM + NoCLevel temporal loops.

        Returns:
            (is_first_T, is_last_T)
        """
        return self._combined_position(dram_i, noc_i, _T_DIM)

    # ------------------------------------------------------------------
    # Public API — DRAM-level-only position
    # Used to decide DRAM→GB traffic skips (outside the NoCLevel loop)
    # ------------------------------------------------------------------

    def dram_k_position(self, dram_i: int) -> Tuple[bool, bool]:
        """K position within DRAM temporal loops only.

        Returns:
            (is_first_K_dram, is_last_K_dram)
        """
        return _level_position(dram_i, self._dram, self._dram_totals, _K_DIMS)

    def dram_t_position(self, dram_i: int) -> Tuple[bool, bool]:
        """T position within DRAM temporal loops only.

        Returns:
            (is_first_T_dram, is_last_T_dram)
        """
        return _level_position(dram_i, self._dram, self._dram_totals, _T_DIM)

    def weight_changes(self, noc_i: int) -> bool:
        """True if weight must be reloaded at this NoC temporal step.

        Weight-indexed dims {KH, KW, CIN, COUT} determine weight content.
        Weight-invariant dims {HO, WO, T} do not — advancing only those dims
        within the NoC temporal loop reuses the same weight tile.

        Step 0 always returns True: no prior load exists yet.
        All other steps return True only if at least one weight-indexed dim
        has a different combined index compared to step noc_i - 1.
        """
        if noc_i == 0:
            return True
        for dim in _WEIGHT_DIMS:
            if _decode_dim(noc_i,     self._noc, dim) != \
               _decode_dim(noc_i - 1, self._noc, dim):
                return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _combined_position(
        self,
        dram_i: int,
        noc_i:  int,
        target: FrozenSet[int],
    ) -> Tuple[bool, bool]:
        """First/last across both loop levels for every dim in target."""
        is_first = True
        is_last  = True

        for dim in target:
            noc_total  = self._noc_totals.get(dim,  1)
            dram_total = self._dram_totals.get(dim, 1)
            combined   = noc_total * dram_total

            if combined <= 1:
                # dim not in any temporal loop → trivially first and last
                continue

            noc_idx  = _decode_dim(noc_i,  self._noc,  dim)
            dram_idx = _decode_dim(dram_i, self._dram, dim)
            idx      = noc_idx + noc_total * dram_idx

            if idx != 0:
                is_first = False
            if idx != combined - 1:
                is_last = False

        return is_first, is_last


# ---------------------------------------------------------------------------
# Module-level helpers  (pure functions, no state)
# ---------------------------------------------------------------------------

def _is_dims_innermost(loops: List[LoopItem], target: FrozenSet[int]) -> bool:
    """True if every dim in target appears only in the innermost block of loops.

    "Innermost block" means: scanning from innermost (index 0) outward, the
    target dims are never preceded by a non-target dim.  Equivalently, no
    non-target loop appears at an index lower than any target loop.

    Dims absent from loops are trivially innermost (they impose no ordering
    constraint).

    Examples (loops listed inner → outer):
        target = {K}
        [K, T, M]  →  True   (K is the very innermost)
        [K, M, T]  →  True   (K still innermost; T and M are outer)
        [T, K, M]  →  False  (T is inner to K → K is not innermost)
        [T, M]     →  True   (K absent → trivially innermost)

        target = {K, T}
        [K, T, M]  →  True   (K and T together form the innermost block)
        [T, K, M]  →  True   (T and K both before any M)
        [M, K, T]  →  False  (M is inner to K → {K,T} not innermost)
    """
    seen_non_target = False
    for loop in loops:                          # inner → outer
        if loop.dim in target:
            if seen_non_target:
                # A target dim appears outside a non-target dim → not innermost
                return False
        else:
            seen_non_target = True
    return True


def _compute_totals(loops: List[LoopItem]) -> Dict[int, int]:
    """Return {dim: product_of_factors} for all dims in loops."""
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


def _decode_dim(step: int, loops: List[LoopItem], dim: int) -> int:
    """Extract the combined iteration index for `dim` from a flat step index.

    `loops` must be sorted inner → outer (ascending level index).

    When the same dim appears in multiple LoopItems (e.g. KH=6 split as
    2 and 3), the inner item is the low-order digit and the outer item is
    the high-order digit of a mixed-radix counter for that dim:

        idx_dim = inner_loop_idx + inner_factor × outer_loop_idx

    Example — loops = [KH×2 (inner), KH×3 (outer)], step=5:

        inner step decode: KH_inner = 5 % 2 = 1, rem = 5 // 2 = 2
        outer step decode: KH_outer = 2 % 3 = 2, rem = 2 // 3 = 0
        combined KH idx = 1 + 2 × 2 = 5  (range 0..5)
    """
    rem          = step
    idx          = 0
    running_base = 1                # cumulative factor of already-seen dim items

    for loop in loops:              # inner → outer
        loop_idx = rem % loop.factor
        rem      = rem // loop.factor
        if loop.dim == dim:
            idx          += loop_idx * running_base
            running_base *= loop.factor

    return idx


def _level_position(
    step:   int,
    loops:  List[LoopItem],
    totals: Dict[int, int],
    target: FrozenSet[int],
) -> Tuple[bool, bool]:
    """First/last within a single loop level for every dim in target."""
    is_first = True
    is_last  = True

    for dim in target:
        total = totals.get(dim, 1)
        if total <= 1:
            continue
        idx = _decode_dim(step, loops, dim)
        if idx != 0:
            is_first = False
        if idx != total - 1:
            is_last = False

    return is_first, is_last
