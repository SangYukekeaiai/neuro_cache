"""Builds Prosperity's per-tile ProSparsity-compressed row sequence from a
real spike trace.

Prosperity (Wei, Guo, Cheng, Li, Yang, Li & Chen, "Prosperity:
Accelerating Spiking Neural Networks via Product Sparsity", HPCA 2025)
tiles a layer's spiking GeMM into m x n x k sub-tiles (Section V-A,
Table III's evaluated config: m=256, k=16, n=128 -- exactly this
pilot's node size, per the pilot's own spec). Each of the tile's m rows
is one im2col'd receptive-field vector: k=16 bits, one per (kh, kw)
reduction index. This pilot fixes k = KH*KW = 4*4 = 16 with a SINGLE
input channel per node visit (CIN barred from NodeLevel entirely, one
channel per visit, tile.tile_offset[DIM_CIN] the absolute channel --
Table III's own k=16 has no CIN term, so this pilot does not attempt a
general CIN>1 mechanism; a future generalization would need k to absorb
CIN too, same tiling idea, more bits per row). T is likewise barred
entirely (one tick per node visit, tile.tile_offset[DIM_T] the absolute
tick) -- the paper's own spiking-GeMM formulation unrolls and
concatenates every timestep's spike matrix into extra M-dimension rows
(Section II-A), but this pilot's node size (m=256 = HO(16)*WO(16))
already exactly saturates the m=256 row budget with no room left for a
T factor, so this deployment processes one (HO,WO) block per tick,
mirroring GustavSNN's own T-barred, one-tick-per-visit precedent.

ProSparsity compression (Section III, Section III-D's heuristic
O(m) algorithm) has two parts:

  1. Temporal ordering (Section III-C, Section V-B "Temporal
     Detection"): the tile's m rows are processed in ASCENDING popcount
     order (a stable sort keeps original row order as the tiebreak among
     equal-popcount rows) -- required because a Partial-Match Prefix must
     always have fewer spikes than its Suffix, and an Exact-Match Prefix
     must have the smaller original row index (Section III-C).

  2. Prefix selection + XOR-based pattern generation (Section III-B's
     Partial Match/Exact Match relationships, pruned per Section III-D's
     "Pruning Rules" and Section V-C's "Efficient Pruning" to exactly one
     Prefix per row): among already-processed rows whose spike set is a
     SUBSET of the current row's spike set, pick the one with the largest
     overlap (most 1-bits, i.e. Section III-D's "largest common
     sub-combination"); ties broken by the largest row index (Section
     III-D: "we keep the edges from the node with largest index"). The
     row's `pattern` is then the bitwise XOR of its own bits against the
     chosen Prefix's bits (Section V-C's "ProSparsity Sparsifying": "the
     bit-wise XOR is equivalent to the operation Sq - Sp" since the
     Prefix is always a subset). A row with no valid Prefix emits its
     `pattern` unchanged (the full row) -- this is what
     `_prosparsity_process` below implements directly from the pilot's
     own worked pseudocode.

Assumes batch=0 and stride=1/no-padding convolution (hin=ho+kh,
win=wo+kw), matching
src/snn_cosa/archmodels/{spinalflow,ptb,loas,gustavsnn}/reconstruct.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class ProsperityRow:
    """One (ho, wo) output pixel's row, after ProSparsity processing.

    row_idx: this row's index in the tile's original row-major (ho, wo)
    enumeration (0..M-1) -- the "smaller/larger index" the paper's own
    Exact-Match tiebreak and Section III-D's "largest index" pruning rule
    both refer to. NOT the processing-order position (see
    ProsperityReconstructed.rows, which is already sorted into processing
    order).
    bits: this row's raw k-bit spike vector, one bit per (kh, kw) in
    nested [KH, KW] order (bit index = kh*KW_n + kw), for this tile's one
    fixed input channel and one fixed tick.
    prefix_row_idx: the row_idx of the chosen Prefix row, or None if this
    row had no valid subset candidate among already-processed rows (its
    `pattern` is then its own `bits`, unchanged).
    pattern: the residual bits actually computed for this row -- `bits`
    XOR the Prefix's `bits` (or `bits` itself if `prefix_row_idx` is
    None). This is what cycles.py/address.py both read: one weight fetch
    + one accumulate cycle per set bit in `pattern`.
    """

    row_idx: int
    ho: int
    wo: int
    bits: Tuple[int, ...]
    prefix_row_idx: Optional[int]
    pattern: Tuple[int, ...]


@dataclass
class ProsperityReconstructed:
    rows: List[ProsperityRow]  # in PROCESSING order (ascending-popcount stable sort)


def _prosparsity_process(
    rows_bits: List[Tuple[int, ...]], row_positions: List[Tuple[int, int]]
) -> List[ProsperityRow]:
    """Pure ProSparsity compression over already-extracted row bit-vectors.

    rows_bits[i]/row_positions[i] are this tile's row `i`'s bits/(ho, wo),
    in original row-major order (row_positions is only carried through for
    ProsperityRow's ho/wo fields, not used by the algorithm itself).
    Factored out from reconstruct_tile_sequence so the ProSparsity
    algorithm itself -- independent of how rows are sliced from a real
    trace -- can be verified directly against the pilot's own hand-built
    worked example (adjacent output rows' receptive fields overlap in any
    real stride-1 trace, so hand-picking arbitrary per-row bit patterns
    like the worked example's is only representable at this pure-data
    level, not through a single consistent trace tensor).
    """
    order = sorted(range(len(rows_bits)), key=lambda i: sum(rows_bits[i]))
    processed: List[int] = []
    result: List[ProsperityRow] = []
    for idx in order:
        bits = rows_bits[idx]
        candidates = [
            j
            for j in processed
            if all(rows_bits[j][b] == 0 or bits[b] == 1 for b in range(len(bits)))
        ]
        if candidates:
            prefix = max(candidates, key=lambda j: (sum(rows_bits[j]), j))
            pattern = tuple(a ^ b for a, b in zip(bits, rows_bits[prefix]))
        else:
            prefix = None
            pattern = bits
        ho, wo = row_positions[idx]
        result.append(ProsperityRow(idx, ho, wo, bits, prefix, pattern))
        processed.append(idx)
    return result


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> ProsperityReconstructed:
    """Return this tile's (one tick's, one channel's) ProSparsity-processed
    row sequence, one row per resident (ho, wo) output pixel.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the tile -- tile_offset[DIM_HO]/[DIM_WO] plus
               node_bound[DIM_HO]/[DIM_WO] select this tile's resident
               (ho, wo) rows (row-major order: ho outer, wo inner);
               node_bound[DIM_KH]/[DIM_KW] this tile's k=KH_n*KW_n bit
               width; tile_offset.get(DIM_T, 0) the single absolute tick
               and tile_offset.get(DIM_CIN, 0) the single absolute input
               channel this visit covers -- both CIN and T are barred
               from NodeLevel (see module docstring), so both use the
               same defensive .get(..., 0) access.
    """
    batch = 0
    cin = tile.tile_offset.get(DIM_CIN, 0)
    t = tile.tile_offset.get(DIM_T, 0)
    ho_off = tile.tile_offset[DIM_HO]
    wo_off = tile.tile_offset[DIM_WO]
    ho_n = tile.node_bound[DIM_HO]
    wo_n = tile.node_bound[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]

    rows_bits: List[Tuple[int, ...]] = []
    row_positions: List[Tuple[int, int]] = []
    for ho in range(ho_off, ho_off + ho_n):
        for wo in range(wo_off, wo_off + wo_n):
            bits = tuple(
                int(trace[t, batch, cin, ho + kh, wo + kw])
                for kh in range(kh_n)
                for kw in range(kw_n)
            )
            rows_bits.append(bits)
            row_positions.append((ho, wo))

    return ProsperityReconstructed(rows=_prosparsity_process(rows_bits, row_positions))
