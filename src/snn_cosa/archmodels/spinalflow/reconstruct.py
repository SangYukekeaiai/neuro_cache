"""Builds SpinalFlow's per-tile spike sequence from a real spike trace.

SpinalFlow packs a tile's receptive field into a "spine": every neuron
that actually spiked in this tile's (t, kh, kw, cin) window, in
chronological order (t outermost). Unlike a dense 0/1 vector, only real
spike events are kept -- this is the input to event_to_cycle (cycle count
= spine length) and event_to_address (one weight burst per spine event).

Assumes batch=0 and stride=1/no-padding convolution (hin = ho + kh,
win = wo + kw), matching the reference SpinalFlow tile-computation
(neuro_cache/sim/compute/spinalflow_compute.py's _receptive_field).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


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

    events: List[Tuple[int, int, int, int]] = []
    for t in range(t_off, t_off + t_n):
        for kh in range(kh_n):
            for kw in range(kw_n):
                hin = ho + kh
                win = wo + kw
                for cin in range(cin_off, cin_off + cin_n):
                    if trace[t, batch, cin, hin, win]:
                        events.append((t, cin, kh, kw))
    return events
