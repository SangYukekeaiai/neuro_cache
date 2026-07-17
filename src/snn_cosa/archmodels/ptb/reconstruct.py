"""Builds PTB's per-tile line sequence from a real spike trace, with
stSAP compression.

PTB packs a tile's receptive field into "lines": one length-T bit-vector
per (kh, kw, cin) reduction index, in [KH, KW, CIN] nested order -- one
line is fed into the PE array per cycle. stSAP (spatiotemporally-non-
overlapping spiking activity packing) then compresses these lines in two
passes:

  Pass 1 (silence removal): drop any line that never fires across its
  whole T range (a "silent" reduction index) -- spatial sparsity. Pass
  1's surviving line count is what actually touches the weight memory:
  event_to_address (address.py) emits exactly one weight burst per
  Pass-1 line.

  Pass 2 (adjacent non-overlap merge): scan the Pass-1 lines in order and
  greedily OR together each line with its immediate neighbor whenever
  their spikes never coincide at the same timestep (bitwise AND is all-
  zero) -- temporal sparsity, packing two lines into a single PE-array
  row-slot. Pass 2's group count (`ln`) is what determines the PE array's
  fill/drain latency: event_to_cycle (cycles.py) uses `ln`, NOT the
  Pass-1 count, because a merged pair still occupies only one row-slot
  even though it required two separate weight fetches.

Assumes batch=0, stride=1, "same" padding (hin = ho + kh - pad_h, win =
wo + kw - pad_w, pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- HO=Hin/WO=Win
exactly). An (hin, win) outside the real trace's spatial extent is
padding, treated as zero (no spike) by _spike() below, matching
src/snn_cosa/archmodels/spinalflow/reconstruct.py's identical convention
(changed from no-padding by explicit user direction, 2026-07-16).
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
class PTBLine:
    """One (kh, kw, cin) reduction index's line: its length-T spike bit-vector.

    bits[i] is 1 if the input at receptive-field offset (kh, kw), input
    channel cin, fired at the i-th timestep of this tile's T range
    (absolute timestep tile_offset[DIM_T] + i), else 0 -- one bit per
    timestep, straight from the trace. This is exactly what stSAP's two
    passes test: Pass 1 drops a line where any(bits) is False (never
    fires anywhere in T); Pass 2 merges two adjacent lines if their bits
    never overlap (bitwise AND is all-zero at every timestep).
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class PTBReconstructed:
    lines_pass1: List[PTBLine]        # after silent-line removal
    lines_pass2: List[List[PTBLine]]  # after adjacent non-overlap merge; each group has 1 or 2 lines


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> PTBReconstructed:
    """Return this tile's stSAP-compressed lines, in [KH, KW, CIN] order.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel, node_bound[DIM_KH]/
               [DIM_KW] the receptive-field extent, node_bound[DIM_CIN]/
               [DIM_T] (with matching tile_offset, default 0) the
               input-channel and timestep range.
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
    pad_h = (kh_n - 1) // 2
    pad_w = (kw_n - 1) // 2

    lines: List[PTBLine] = []
    for kh in range(kh_n):
        for kw in range(kw_n):
            hin = ho + kh - pad_h
            win = wo + kw - pad_w
            for cin in range(cin_off, cin_off + cin_n):
                bits = tuple(
                    _spike(trace, t, batch, cin, hin, win)
                    for t in range(t_off, t_off + t_n)
                )
                lines.append(PTBLine(kh, kw, cin, bits))

    # Pass 1: drop silent lines (never fire across the whole T range).
    lines_pass1 = [line for line in lines if any(line.bits)]

    # Pass 2: greedily merge each line with its immediate neighbor if their
    # spikes never coincide at the same timestep.
    lines_pass2: List[List[PTBLine]] = []
    i = 0
    while i < len(lines_pass1):
        cur = lines_pass1[i]
        if i + 1 < len(lines_pass1):
            nxt = lines_pass1[i + 1]
            if all(a == 0 or b == 0 for a, b in zip(cur.bits, nxt.bits)):
                lines_pass2.append([cur, nxt])
                i += 2
                continue
        lines_pass2.append([cur])
        i += 1

    return PTBReconstructed(lines_pass1=lines_pass1, lines_pass2=lines_pass2)
