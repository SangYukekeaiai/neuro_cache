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
from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


def _spike(trace: np.ndarray, t: int, batch: int, cin: int, hin: int, win: int) -> int:
    """Zero-padding boundary check: an (hin, win) outside the real trace's
    spatial extent is padding, not data -- returns 0 (no spike) instead of
    indexing out of bounds."""
    if hin < 0 or hin >= trace.shape[3] or win < 0 or win >= trace.shape[4]:
        return 0
    return int(trace[t, batch, cin, hin, win])


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


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> GustavReconstructed:
    """Return this tile's (one tick's) NRV-compressed submatrix sequence,
    one submatrix per resident HO row.

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
    batch = 0
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

    submatrices: List[GustavSubmatrix] = []
    for piece_idx, ho in enumerate(range(ho_off, ho_off + ho_n)):
        positions = [(ho, wo) for wo in range(wo_off, wo_off + wo_n)]
        lines: List[GustavLine] = []
        for kh in range(kh_n):
            for kw in range(kw_n):
                for cin in range(cin_off, cin_off + cin_n):
                    active = any(
                        _spike(trace, t, batch, cin, ho + kh - pad_h, wo + kw - pad_w)
                        for _, wo in positions
                    )
                    if active:
                        lines.append(GustavLine(kh, kw, cin))
        submatrices.append(GustavSubmatrix(piece_idx, positions, lines))

    return GustavReconstructed(submatrices=submatrices)
