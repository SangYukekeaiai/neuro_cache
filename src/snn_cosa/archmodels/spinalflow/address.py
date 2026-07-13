"""SpinalFlow weight address per spike event.

A spike at receptive-field position (kh, kw) and input channel cin
requires exactly one weight burst: the fixed (kh, kw, cin) reduction
index, contiguous across this tile's full output-channel range
(SpinalFlow's 128-wide PE array reads all output channels for a given
input in one burst). One address per event, same order as the input
event list (already t-chronological from reconstruct.py).
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec


def event_to_address(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (kh, kw, cin, cout_off, cout_off + cout_n)
        for (_t, cin, kh, kw) in events
    ]
