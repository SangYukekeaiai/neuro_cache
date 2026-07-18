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

Assumes batch=0, stride=1, "same" padding (hin=ho+kh-pad_h,
win=wo+kw-pad_w, pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- HO=Hin/WO=Win
exactly). An (hin, win) outside the real trace's spatial extent is
padding, treated as zero (no spike) by _spike() below, matching
src/snn_cosa/archmodels/{spinalflow,ptb,loas,gustavsnn}/reconstruct.py's
identical convention (changed from no-padding by explicit user
direction, 2026-07-16).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

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

    The row-processing ORDER stays a genuine sequential loop -- row i's
    prefix choice depends on every row already processed before it, so
    this cannot be parallelized across rows. What's vectorized is each
    step's INNER work: originally a Python-level scan of `processed`
    (checking `all(...)` per candidate, then a max() with a lambda), now
    one numpy comparison against a growing array of already-processed
    bit-rows. This matters because M (this pilot's tile size) is 256 --
    the O(M^2) days here are the dominant per-tile cost, unlike every
    other archmodel's reconstruction (see reconstruct_tile_sequence_batch's
    own docstring), so this is the one arch where the batch-vectorized
    gather alone gave essentially no measured speedup (1.0x) until this
    inner loop was addressed too.

    Correctness argument for dropping the explicit `max(key=(popcount, j))`
    tiebreak: `processed` is always built by appending `order`'s own
    (popcount, j)-ascending-stable-sorted sequence one row at a time, so
    at every step it is itself already sorted ascending by (popcount, j).
    Filtering a sorted sequence preserves its order, so among the current
    step's subset candidates, the LAST one (by position in `processed`) is
    already the (popcount, j)-maximal one -- no separate argmax needed.
    """
    m = len(rows_bits)
    bits_arr = np.asarray(rows_bits, dtype=np.int64)  # [M, k]
    popcounts = bits_arr.sum(axis=1)
    # kind="stable" matches Python's sorted()'s own stability -- equal-
    # popcount rows keep ascending original-index order either way.
    order = np.argsort(popcounts, kind="stable")

    bits_bool = bits_arr.astype(bool)
    k = bits_arr.shape[1]
    processed_bits = np.empty((m, k), dtype=bool)
    processed_idx = np.empty(m, dtype=np.int64)

    result: List[ProsperityRow] = []
    for step, idx in enumerate(order.tolist()):
        idx = int(idx)
        bits_row = bits_arr[idx]
        row_bool = bits_bool[idx]

        prefix = None
        pattern = rows_bits[idx]
        if step > 0:
            # Subset test: a processed row j is a subset of the current row
            # iff it has no 1-bit where the current row has a 0 -- i.e.
            # (processed bits AND NOT current bits) is all-zero for that row.
            violates = processed_bits[:step] & ~row_bool
            subset_mask = ~violates.any(axis=1)
            candidates = np.flatnonzero(subset_mask)
            if candidates.size:
                prefix = int(processed_idx[int(candidates[-1])])
                pattern = tuple((bits_row ^ bits_arr[prefix]).tolist())

        ho, wo = row_positions[idx]
        result.append(ProsperityRow(idx, ho, wo, rows_bits[idx], prefix, pattern))
        processed_bits[step] = row_bool
        processed_idx[step] = idx

    return result


def _prosparsity_process_reference(
    rows_bits: List[Tuple[int, ...]], row_positions: List[Tuple[int, int]]
) -> List[ProsperityRow]:
    """Original, unvectorized O(M^2) implementation -- kept only as the
    ground truth _prosparsity_process is checked against; not called from
    reconstruct_tile_sequence_batch."""
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


def reconstruct_tile_sequence_batch(
    trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
) -> List[ProsperityReconstructed]:
    """Same reconstruction as reconstruct_tile_sequence, for every sample in
    batch_indices at once.

    Only the row-bit EXTRACTION is vectorized here (one gather over
    (HO, WO, KH, KW, batch) instead of len(batch_indices) separate
    Python-level nested loops, replacing the tuple-comprehension over
    (kh, kw) per row). _prosparsity_process itself -- the paper's O(M^2)
    all-pairs subset/overlap search -- is a genuinely sequential
    per-sample algorithm (each row's prefix choice depends on every
    previously-processed row) and is deliberately left untouched: it's
    already implemented and independently verified against the pilot's
    own worked example, and re-deriving it to run across samples at once
    would risk the trickiest part of this module for uncertain gain, since
    its own cost (O(M^2)) already dominates the now-vectorized gather.
    batch_indices may repeat/reorder freely; output[i] always corresponds
    to batch_indices[i].
    """
    cin = tile.tile_offset.get(DIM_CIN, 0)
    t = tile.tile_offset.get(DIM_T, 0)
    ho_off = tile.tile_offset.get(DIM_HO, 0)
    wo_off = tile.tile_offset.get(DIM_WO, 0)
    ho_n = tile.node_bound[DIM_HO]
    wo_n = tile.node_bound[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    pad_h = (kh_n - 1) // 2
    pad_w = (kw_n - 1) // 2

    hin_full, win_full = trace.shape[3], trace.shape[4]
    ho_arr = ho_off + np.arange(ho_n)
    wo_arr = wo_off + np.arange(wo_n)
    kh_arr = np.arange(kh_n)
    kw_arr = np.arange(kw_n)
    batch_arr = np.asarray(batch_indices)

    hin_grid = ho_arr[:, None] + kh_arr[None, :] - pad_h  # [HO, KH]
    win_grid = wo_arr[:, None] + kw_arr[None, :] - pad_w  # [WO, KW]
    valid_h = (hin_grid >= 0) & (hin_grid < hin_full)
    valid_w = (win_grid >= 0) & (win_grid < win_full)
    hin_clipped = np.clip(hin_grid, 0, hin_full - 1)
    win_clipped = np.clip(win_grid, 0, win_full - 1)

    trace_tc = trace[t, :, cin]  # fixed tick + channel -> [B_full, Hin, Win]

    b_idx = batch_arr[:, None, None, None, None]
    hin_idx = hin_clipped[None, :, None, :, None]
    win_idx = win_clipped[None, None, :, None, :]
    gathered = trace_tc[b_idx, hin_idx, win_idx]  # [batch, HO, WO, KH, KW]
    valid = valid_h[None, :, None, :, None] & valid_w[None, None, :, None, :]
    gathered = gathered * valid

    # Flatten (HO,WO) -> M rows (ho outer, wo inner, matching the original
    # `for ho: for wo:` order) and (KH,KW) -> k bits (kh outer, kw inner,
    # matching the original bit index kh*KW_n+kw) -- both are plain
    # C-order reshapes since the axes are already in that nested order.
    num_batch = len(batch_arr)
    rows_bits_all = (
        gathered.reshape(num_batch, ho_n * wo_n, kh_n * kw_n).astype(np.int64).tolist()
    )
    row_positions = [(ho, wo) for ho in range(ho_off, ho_off + ho_n) for wo in range(wo_off, wo_off + wo_n)]

    results: List[ProsperityReconstructed] = []
    for b in range(num_batch):
        rows_bits = [tuple(row) for row in rows_bits_all[b]]
        results.append(
            ProsperityReconstructed(rows=_prosparsity_process(rows_bits, row_positions))
        )
    return results


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> ProsperityReconstructed:
    """Return this tile's (one tick's, one channel's) ProSparsity-processed
    row sequence, one row per resident (ho, wo) output pixel, for real
    captured sample 0. Thin wrapper over reconstruct_tile_sequence_batch
    so there is exactly one reconstruction implementation to trust.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the tile -- tile_offset.get(DIM_HO, 0)/tile_offset.get(DIM_WO, 0)
               plus node_bound[DIM_HO]/[DIM_WO] select this tile's resident
               (ho, wo) rows (row-major order: ho outer, wo inner);
               node_bound[DIM_KH]/[DIM_KW] this tile's k=KH_n*KW_n bit
               width; tile_offset.get(DIM_T, 0) the single absolute tick
               and tile_offset.get(DIM_CIN, 0) the single absolute input
               channel this visit covers. CIN and T are barred from
               NodeLevel entirely (see module docstring), so both use
               .get(..., 0). HO and WO ARE node-level resident (node_bound
               [DIM_HO]/[DIM_WO] below are always meaningful), but may
               simply have no DRAM-level offset entry when a layer's HO/WO
               fits entirely within node capacity with no leftover pushed to
               DRAM -- so HO/WO also use .get(DIM_HO/DIM_WO, 0), for a
               different reason than CIN/T's.
    """
    return reconstruct_tile_sequence_batch(trace, tile, [0])[0]
