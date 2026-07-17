"""Builds SpinalFlow's per-tile spike sequence from a real spike trace.

SpinalFlow packs a tile's receptive field into a "spine": every neuron
that actually spiked in this tile's (t, kh, kw, cin) window, in
chronological order (t outermost). Unlike a dense 0/1 vector, only real
spike events are kept -- this is the input to event_to_cycle (cycle count
= spine length) and event_to_address (one weight burst per spine event).

Assumes batch=0, stride=1, "same" padding (hin = ho + kh - pad_h, win =
wo + kw - pad_w, where pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- the
standard convention for an odd kernel, matching HO=Hin/WO=Win exactly).
An (hin, win) that falls outside the real trace's spatial extent is
padding, not data -- treated as zero (no spike) by _spike() below, never
indexed out of bounds. (Originally "valid"/no-padding, hin=ho+kh; changed
by explicit user direction, 2026-07-16, since real VGG/ResNet 3x3 convs
use same-padding.) Matches the reference SpinalFlow tile-computation's
receptive-field shape (neuro_cache/sim/compute/spinalflow_compute.py's
_receptive_field), modulo this padding correction.
"""

from __future__ import annotations

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


def reconstruct_tile_sequence(
    trace: np.ndarray, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int]]:
    """Return this tile's spike events as (t, cin, kh, kw), t-chronological.

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

    events: List[Tuple[int, int, int, int]] = []
    for t in range(t_off, t_off + t_n):
        for kh in range(kh_n):
            for kw in range(kw_n):
                hin = ho + kh - pad_h
                win = wo + kw - pad_w
                for cin in range(cin_off, cin_off + cin_n):
                    if _spike(trace, t, batch, cin, hin, win):
                        events.append((t, cin, kh, kw))
    return events
