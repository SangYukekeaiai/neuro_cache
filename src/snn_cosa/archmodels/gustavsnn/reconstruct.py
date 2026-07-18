"""Builds GustavSNN's per-tile, per-tick NRV (non-zero row vector)
compressed submatrix sequence from a real spike trace.

GustavSNN's column-parallel tick-batch (CPTB) dataflow (Hwang, Lee, Koo &
Kung, HPCA 2026) partitions a tile's HO*WO output-pixel range ("N", the
paper's flattened spike-matrix column count) into P-wide column
submatrices (Section IV-C, Algorithm 1's `Bk = [B0|B1|...|BK-1]`), one
submatrix per PE (up to PE_COUNT_MAX=8 PEs per tile in cycles.py, Table
II). This project keeps HO and WO as two separate DIM axes rather than
one flattened N, so this deployment maps the paper's 1-D column-partition
onto them asymmetrically, matching how a real conv layer's output
actually traverses row-major and matching this project's own MIP
validation (see configs/arch/gustavsnn.yaml's module comment for the full
V1 rationale): **one resident HO row = one submatrix = one PE** (the
paper's `K` submatrices, HO genuinely spatially parallel), and **each
submatrix spans that row's full resident WO width** (the paper's `P`,
this deployment capped at 8 -- see configs/arch/gustavsnn.yaml's `WO: 8`).

Within a submatrix, NRV format (Section IV-D, Fig. 7) drops any
(kh,kw,cin) reduction-index "row" that is entirely zero across that
submatrix's WO-wide columns -- but critically, this is evaluated FRESH AT
EVERY TICK (Algorithm 1's `for t: for d:` loop order; Section V-B's
column-major time-second scheduling sweeps the full D range for one
tick, fires LIF, THEN advances to the next tick, Fig. 12), not once
across the whole T range like LoAS's silent-neuron compression.

This deployment therefore bars T from NodeLevel residency entirely (see
configs/arch/gustavsnn.yaml) -- one node visit here covers exactly ONE
tick, mirroring how HO/WO are barred (DRAM-looped) in
SpinalFlow/PTB/LoAS. tile.tile_offset[DIM_T] gives that one absolute
tick; there is no T loop inside this module at all, and node_bound has no
DIM_T entry to read.

Unlike SpinalFlow/PTB/LoAS (which bar HO/WO from NodeLevel -- one node
visit = one output pixel), GustavSNN's CPTB dataflow needs multiple
output pixels resident and column-partitioned at once, so HO/WO ARE
node-level resident here. tile.node_bound[DIM_HO] gives this visit's
resident HO-row count (one GustavSubmatrix per row); tile.node_bound[DIM_WO]
gives each row's resident WO width (that submatrix's `positions`) -- both
read directly from the tile rather than hardcoded, so this function stays
correct even if a real solve grants more/less residency than the YAML's
nominal 8/8 (e.g. extra temporal residency beyond the spatial cap -- see
cycles.py's wave handling for what happens when node_bound[DIM_HO] > 8).

Assumes batch=0, stride=1, "same" padding (hin=ho+kh-pad_h,
win=wo+kw-pad_w, pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- HO=Hin/WO=Win
exactly). An (hin, win) outside the real trace's spatial extent is
padding, treated as zero (no spike) by _spike() below, matching
src/snn_cosa/archmodels/{spinalflow,ptb,loas}/reconstruct.py's identical
convention (changed from no-padding by explicit user direction,
2026-07-16).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class GustavLine:
    """One non-zero (kh, kw, cin) reduction-index row within one
    submatrix, at this tile's one tick.

    Carries no bit-vector (unlike PTB's/LoAS's per-line T-length bits) --
    GustavSNN's NRV re-derives silence fresh per tick (see module
    docstring), so there is nothing to pack across time here; a line's
    mere presence in a GustavSubmatrix.lines means "non-zero this tick,
    this submatrix."
    """

    kh: int
    kw: int
    cin: int


@dataclass
class GustavSubmatrix:
    """One HO row's WO-wide column-partition submatrix (one PE's assigned
    slice of the tile's HO*WO output-pixel range), at this tile's one
    tick.

    positions: the (ho, wo) output pixels covered by this submatrix --
    a single fixed ho paired with every wo in this tile's resident WO
    range (this visit's P-wide window).
    lines: the non-zero (kh, kw, cin) rows for this submatrix, i.e. every
    reduction index with at least one spike among `positions` at this
    tick -- NRV's row-skip result (Fig. 7).
    """

    piece_idx: int
    positions: List[Tuple[int, int]]
    lines: List[GustavLine]


@dataclass
class GustavReconstructed:
    submatrices: List[GustavSubmatrix]


def reconstruct_tile_sequence_batch(
    trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
) -> List[GustavReconstructed]:
    """Same NRV-compressed reconstruction as reconstruct_tile_sequence, for
    every sample in batch_indices at once -- one vectorized gather over
    (HO, WO, KH, KW, CIN, batch) instead of len(batch_indices) separate
    Python-level nested loops (there is no T loop to vectorize here at
    all -- this tile covers exactly one tick, see module docstring).
    batch_indices may repeat/reorder freely; output[i] always corresponds
    to batch_indices[i].
    """
    t = tile.tile_offset.get(DIM_T, 0)
    ho_off = tile.tile_offset.get(DIM_HO, 0)
    wo_off = tile.tile_offset.get(DIM_WO, 0)
    ho_n = tile.node_bound[DIM_HO]
    wo_n = tile.node_bound[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    cin_n = tile.node_bound[DIM_CIN]
    cin_off = tile.tile_offset.get(DIM_CIN, 0)
    pad_h = (kh_n - 1) // 2
    pad_w = (kw_n - 1) // 2

    hin_full, win_full = trace.shape[3], trace.shape[4]
    ho_arr = ho_off + np.arange(ho_n)
    wo_arr = wo_off + np.arange(wo_n)
    kh_arr = np.arange(kh_n)
    kw_arr = np.arange(kw_n)
    cin_arr = cin_off + np.arange(cin_n)
    batch_arr = np.asarray(batch_indices)

    # hin depends on (ho, kh) jointly, win on (wo, kw) jointly -- unlike the
    # other archs' single-offset KH/KW grids, these are genuine 2-D grids.
    hin_grid = ho_arr[:, None] + kh_arr[None, :] - pad_h  # [HO, KH]
    win_grid = wo_arr[:, None] + kw_arr[None, :] - pad_w  # [WO, KW]
    valid_h = (hin_grid >= 0) & (hin_grid < hin_full)
    valid_w = (win_grid >= 0) & (win_grid < win_full)
    hin_clipped = np.clip(hin_grid, 0, hin_full - 1)
    win_clipped = np.clip(win_grid, 0, win_full - 1)

    trace_t = trace[t]  # fixed single tick -> [B_full, Cin, Hin, Win]

    # Reshape each index array so together they broadcast to one combined
    # [batch, HO, WO, KH, KW, CIN] result -- numpy's advanced-indexing
    # broadcasting rule (this replaces the 4 nested for-loops + the
    # `any(... for _, wo in positions)` reduction over WO).
    b_idx = batch_arr[:, None, None, None, None, None]
    cin_idx = cin_arr[None, None, None, None, None, :]
    hin_idx = hin_clipped[None, :, None, :, None, None]
    win_idx = win_clipped[None, None, :, None, :, None]
    gathered = trace_t[b_idx, cin_idx, hin_idx, win_idx]  # [batch,HO,WO,KH,KW,CIN]

    valid = valid_h[None, :, None, :, None, None] & valid_w[None, None, :, None, :, None]
    gathered = gathered * valid

    # OR across WO (axis 2) -- "active this row" fresh per tick, matching
    # the original `any(_spike(...) for _, wo in positions)`.
    active = (gathered != 0).any(axis=2)  # [batch, HO, KH, KW, CIN]

    num_batch = len(batch_arr)
    b_i, ho_i, kh_i, kw_i, cin_i = np.nonzero(active)
    # (batch, ho) pairs come out already sorted (nonzero visits axis 0
    # slowest, then axis 1) -- combine them into one group key so a single
    # searchsorted slices every submatrix's lines at once.
    group_id = b_i * ho_n + ho_i
    slice_bounds = np.searchsorted(group_id, np.arange(num_batch * ho_n + 1))

    results: List[GustavReconstructed] = []
    for b in range(num_batch):
        submatrices: List[GustavSubmatrix] = []
        for piece_idx, ho in enumerate(range(ho_off, ho_off + ho_n)):
            g = b * ho_n + piece_idx
            start, end = slice_bounds[g], slice_bounds[g + 1]
            positions = [(ho, wo) for wo in range(wo_off, wo_off + wo_n)]
            lines = [
                GustavLine(int(kh_i[j]), int(kw_i[j]), int(cin_off + cin_i[j]))
                for j in range(start, end)
            ]
            submatrices.append(GustavSubmatrix(piece_idx, positions, lines))
        results.append(GustavReconstructed(submatrices=submatrices))
    return results


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> GustavReconstructed:
    """Return this tile's (one tick's) NRV-compressed submatrix sequence,
    one submatrix per resident HO row, for real captured sample 0. Thin
    wrapper over reconstruct_tile_sequence_batch so there is exactly one
    reconstruction implementation to trust.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the tile -- tile_offset.get(DIM_HO, 0) plus
               node_bound[DIM_HO] select this tile's resident HO rows
               (one GustavSubmatrix per row); tile_offset.get(DIM_WO, 0) plus
               node_bound[DIM_WO] select each row's resident WO width
               (this visit's P-wide column window); node_bound[DIM_KH]/
               [DIM_KW]/[DIM_CIN] the full reduction row (must be
               entirely resident -- see module docstring);
               tile_offset.get(DIM_T, 0) the single absolute tick this node
               visit covers. HO and WO use .get(..., 0) because they ARE
               node-level resident (node_bound[DIM_HO]/[DIM_WO] are always
               meaningful), but may have no DRAM-level offset entry when a
               layer's HO/WO fits entirely within node capacity with no
               leftover pushed to DRAM. T uses .get(..., 0) defensively only
               (GustavSNN's own design bars T from NodeLevel entirely, so in
               practice T always has a real DRAM-loop entry).
    """
    return reconstruct_tile_sequence_batch(trace, tile, [0])[0]
