"""Builds LoAS's per-row compressed fiber (bitmask + pointer + packed
non-silent data) from a real spike trace.

LoAS compresses one output pixel's full reduction row (fixed m; k = every
(kh, kw, cin) reduction index, in [KH, KW, CIN] nested order) in the
paper's own two-part Fig. 8 format (Yin et al., MICRO 2024, Section IV-A):

  1. A ROW-LEVEL BITMASK, one bit per candidate k position (length
     KH*KW*CIN): 1 marks a "non-silent neuron" (fires at least once
     across the whole T range), 0 marks a "silent" one. Followed by a
     POINTER to the start of the packed non-zero data.
  2. The PACKED NON-ZERO DATA: for each non-silent k only, its own
     length-T spike bit-vector (e.g. "1001" for a 4-timestep neuron that
     spikes at t0 and t3, silent at t1/t2) -- silent k's are dropped
     entirely, contributing nothing here ("no silent neuron inside").

There is no further compression pass (unlike PTB's stSAP, which
additionally merges adjacent non-overlapping lines; LoAS has no such
merge step in this deployment).

ptr is always 0 in this standalone reconstruction: each call processes
exactly one row/fiber in isolation (one NodeTileSpec tile = one output
pixel's row), so its own pointer trivially points to the start of its own
packed segment. ptr would only become a meaningful non-zero offset once
multiple rows' compressed data share a single memory arena -- out of
scope for this per-tile pilot (see Global Constraints).

This deployment requires KH, KW, and CIN to be entirely resident at
NodeLevel (configs/arch/loas.yaml's `KH: null`/`KW: null`/`CIN: null`) --
the full reduction row must be visible at once to build one complete
fiber, matching the paper's row-wise compression unit.

Assumes batch=0 and stride=1/no-padding convolution (hin = ho + kh,
win = wo + kw), matching
src/snn_cosa/archmodels/{spinalflow,ptb}/reconstruct.py.

cin_off/t_off (tile.tile_offset.get(DIM_CIN/DIM_T, 0)) are NOT about
supporting a nonzero offset in this deployment -- configs/arch/loas.yaml
forces CIN and T fully resident (null), so a real solved schedule never
splits either dimension across multiple node visits, and their entries
are simply ABSENT from tile_offset (there's only ever one visit, so no
offset needs tracking). `.get(dim, 0)` exists to avoid a KeyError on that
absence, not to handle a real nonzero value -- same convention as
SpinalFlow's reconstruct.py, which has the identical CIN/T:null setup.
Contrast with tile_offset[DIM_HO]/[DIM_WO] just below, accessed with
plain `[...]`: HO/WO are barred from NodeLevel entirely (always vary
across node visits), so their tile_offset entry is mandatory and a
missing key there is a genuine bug worth crashing on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class LoASLine:
    """One non-silent (kh, kw, cin) reduction index's packed spike data.

    bits[i] is 1 if this neuron fired at the i-th timestep of this tile's
    T range (absolute timestep tile_offset[DIM_T] + i), else 0 -- e.g.
    bits=(1,0,1,0) is the paper's "1010" packed value. Only non-silent
    lines (any(bits) is True) are ever constructed; LoASReconstructed's
    row-level bitmask records exactly which (kh, kw, cin) positions these
    correspond to.
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class LoASReconstructed:
    """This row's compressed fiber: row-level bitmask + pointer, plus the
    non-silent lines' packed data -- the paper's two-part Fig. 8 format
    (see module docstring).
    """

    bitmask: Tuple[int, ...]  # length KH*KW*CIN, [KH,KW,CIN] order; 1 = non-silent, 0 = silent
    ptr: int                  # start offset of the packed non-zero data; always 0 here (see module docstring)
    lines: List[LoASLine]     # non-silent lines only, same relative order as bitmask's set bits


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> LoASReconstructed:
    """Return this tile's (one row's) compressed fiber: bitmask + ptr + lines.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel (this row), node_bound
               [DIM_KH]/[DIM_KW]/[DIM_CIN] the full reduction row (must
               be entirely resident -- see module docstring), node_bound
               [DIM_T]/tile_offset[DIM_T] (default 0) the timestep range.
    """
    batch = 0
    ho = tile.tile_offset[DIM_HO]
    wo = tile.tile_offset[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    cin_n = tile.node_bound[DIM_CIN]
    cin_off = tile.tile_offset.get(DIM_CIN, 0)
    t_n = tile.node_bound[DIM_T]
    t_off = tile.tile_offset.get(DIM_T, 0)

    bitmask: List[int] = []
    lines: List[LoASLine] = []
    for kh in range(kh_n):
        for kw in range(kw_n):
            hin = ho + kh
            win = wo + kw
            for cin in range(cin_off, cin_off + cin_n):
                bits = tuple(
                    int(trace[t, batch, cin, hin, win])
                    for t in range(t_off, t_off + t_n)
                )
                non_silent = any(bits)
                bitmask.append(1 if non_silent else 0)
                if non_silent:
                    lines.append(LoASLine(kh, kw, cin, bits))

    return LoASReconstructed(bitmask=tuple(bitmask), ptr=0, lines=lines)