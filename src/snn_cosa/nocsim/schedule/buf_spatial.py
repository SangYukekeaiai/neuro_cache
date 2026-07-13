"""Build buf_spatial for all three variables under the Way-2 PE layout.

Way-2 layout
-------------
Each PE is identified by a tuple of per-dimension spatial indices.  The
mapping from index tuple to pe_id uses the canonical Way-2 spatial loop order
(inner to outer):

    [T, WO, HO, CIN, KW, KH, COUT]

    X axis (columns, horizontal):  T  →  WO  →  HO
    Y axis (rows,    vertical  ):  CIN → KW  →  KH → COUT

    pe_id = y × X + x
    x     = t + T_s × wo + T_s × WO_s × ho
    y     = cin + CIN_s × kw + CIN_s × KW_s × kh + CIN_s × KW_s × KH_s × cout

buf_spatial[var]
-----------------
A list of length num_pes indexed by pe_id.  Each entry is a 7-tuple
(one slot per dimension 0=KH … 6=T) where dimensions that do NOT
contribute to variable v's size (A[j][v] == 0) are zeroed.

    weight: keeps KH, KW, CIN, COUT  (rows 0-2, 3); zeros HO, WO, T
    psum:   keeps COUT, HO, WO, T    (rows 3-6);    zeros KH, KW, CIN
    vmem:   keeps COUT, HO, WO       (rows 3-5);    zeros KH, KW, CIN, T

Reduction chains
-----------------
PEs with the SAME zeroed address share the same data tile:
  - same weight addr → multicast from GB
  - same psum  addr → K-chain (reduce along K; K dims are zeroed → shared group)
  - same vmem  addr → T-chain (reduce along T at K_max position)

K-chain order: within a psum addr group, sorting pe_ids ascending gives
K=0 → K_max order (higher K index → higher y → higher pe_id under Way-2).

T-chain order: among PEs at K_max position, sorting pe_ids ascending within
a vmem addr group gives T=0 → T_max order (higher T → higher x → higher
pe_id within a fixed y row).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from snn_cosa.model.constants import _A, VAR_WEIGHT, VAR_PSUM, VAR_VMEM
from snn_cosa.parsers.layer import (
    SNNProb, DIM_KH, DIM_KW, DIM_CIN, DIM_COUT, DIM_HO, DIM_WO, DIM_T,
)
from .decode import Schedule

# Canonical Way-2 spatial loop order, inner → outer
_WAY2_ORDER: List[int] = [DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT]

# Dimensions that form the K-reduction axis (Y axis in Way-2)
_K_DIMS: Tuple[int, ...] = (DIM_KH, DIM_KW, DIM_CIN)

# Type alias: address tuple → sorted list of pe_ids
AddrGroups = Dict[tuple, List[int]]


class BufSpatial:
    """Spatial address arrays and group helpers for the SNN-CoSA NoC simulator.

    Constructed once per solve result; all group lookups are computed lazily
    on first access and cached.

    Attributes:
        num_pes: Total PE count (product of all active spatial factors).
        weight:  buf_spatial list for weight  (len = num_pes).
        psum:    buf_spatial list for psum.
        vmem:    buf_spatial list for vmem.
    """

    def __init__(self, schedule: Schedule, prob: SNNProb) -> None:
        sf = schedule.spatial_factors       # dim_idx → spatial product (≥ 1)

        # Active spatial dims in Way-2 order
        active = [j for j in _WAY2_ORDER if sf[j] > 1]

        # Strides for pe_id encoding (inner dim has stride 1)
        strides: Dict[int, int] = {}
        prod = 1
        for j in active:
            strides[j] = prod
            prod *= sf[j]

        self.num_pes = prod
        self._sf     = sf
        self._prob   = prob

        # pe_id → per-dim spatial index (all dims, 0 for inactive dims)
        self._indices: List[Dict[int, int]] = []
        for pe_id in range(self.num_pes):
            rem = pe_id
            idx: Dict[int, int] = {j: 0 for j in range(prob.prob_levels)}
            for j in active:                    # inner → outer
                idx[j] = rem % sf[j]
                rem   //= sf[j]
            self._indices.append(idx)

        # buf_spatial arrays — built once, read many times
        self.weight = self._make(VAR_WEIGHT)
        self.psum   = self._make(VAR_PSUM)
        self.vmem   = self._make(VAR_VMEM)

        # Cached group dicts (populated on first access)
        self._k_chain_cache:    AddrGroups | None = None
        self._t_chain_cache:    AddrGroups | None = None

    # ------------------------------------------------------------------
    # Internal build helper
    # ------------------------------------------------------------------

    def _make(self, v: int) -> List[tuple]:
        """Build the 7-tuple address list for variable v.

        For each pe_id, zero out dimensions where A[j][v] == 0.
        """
        return [
            tuple(
                self._indices[pe_id][j] if _A[j][v] == 1 else 0
                for j in range(self._prob.prob_levels)
            )
            for pe_id in range(self.num_pes)
        ]

    # ------------------------------------------------------------------
    # Generic grouping
    # ------------------------------------------------------------------

    @staticmethod
    def addr_groups(buf: List[tuple]) -> AddrGroups:
        """Group pe_ids by their buf_spatial address.

        Returns a dict mapping each distinct address tuple to a sorted list
        of pe_ids that hold that address.

        Usage::

            for addr, pes in bs.addr_groups(bs.weight).items():
                if len(pes) == 1:
                    gen.unicast("weight", ..., dest=pes[0], ...)
                else:
                    gen.multicast("weight", ..., dests=pes, ...)
        """
        groups: AddrGroups = {}
        for pe_id, addr in enumerate(buf):
            groups.setdefault(addr, []).append(pe_id)
        return {addr: sorted(pes) for addr, pes in groups.items()}

    # ------------------------------------------------------------------
    # K-chain helpers  (psum reduction, vertical / Y axis)
    # ------------------------------------------------------------------

    def k_chain_groups(self) -> AddrGroups:
        """Return K-chains keyed by psum addr.

        Each value is an ordered list of pe_ids representing one serial
        K-chain: pe_ids[0] holds K=0 (chain head), pe_ids[-1] holds K_max
        (chain tail, the PE that accumulates the final psum).

        Ordering guarantee: within a psum addr group all pe_ids share the
        same column (same x coordinate); increasing pe_id == increasing K
        index because higher K → higher y → higher pe_id under Way-2.
        """
        if self._k_chain_cache is None:
            self._k_chain_cache = self.addr_groups(self.psum)
        return self._k_chain_cache

    def k_max_pes(self) -> AddrGroups:
        """Return the K-chain tail pe_id for each psum addr group.

        Key   = psum address tuple.
        Value = single pe_id at K_max position (last in k_chain_groups list).
        """
        return {addr: chain[-1] for addr, chain in self.k_chain_groups().items()}

    # ------------------------------------------------------------------
    # T-chain helpers  (vmem reduction, horizontal / X axis)
    # ------------------------------------------------------------------

    def t_chain_groups(self) -> AddrGroups:
        """Return T-chains keyed by vmem addr, restricted to K_max row.

        The T-chain fires only after K-chain reduction is complete, so only
        PEs sitting at the K_max position (all K-dim indices at maximum) are
        included.

        Each value is an ordered list of pe_ids: pe_ids[0] = T=0 (head),
        pe_ids[-1] = T_max (tail).  Ordering: ascending T index == ascending
        pe_id within a fixed-y (K_max) row.
        """
        if self._t_chain_cache is None:
            sf       = self._sf
            k_max_idx = {j: sf[j] - 1 for j in _K_DIMS}  # max index per K dim

            raw: AddrGroups = {}
            for pe_id in range(self.num_pes):
                idx = self._indices[pe_id]
                if any(idx[j] != k_max_idx[j] for j in _K_DIMS):
                    continue                                # not at K_max row
                addr = self.vmem[pe_id]
                raw.setdefault(addr, []).append(pe_id)

            # sort within each group by T index (== by pe_id since T → X axis)
            self._t_chain_cache = {
                addr: sorted(pes, key=lambda pe: self._indices[pe][DIM_T])
                for addr, pes in raw.items()
            }

        return self._t_chain_cache

    def t_min_pes(self) -> AddrGroups:
        """Return the T-chain head pe_id (T=0) for each vmem addr group."""
        return {addr: chain[0] for addr, chain in self.t_chain_groups().items()}

    def t_max_pes(self) -> AddrGroups:
        """Return the T-chain tail pe_id (T=T_max) for each vmem addr group."""
        return {addr: chain[-1] for addr, chain in self.t_chain_groups().items()}
