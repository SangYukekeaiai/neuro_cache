"""PTB weight address per stSAP Pass-1 line.

Each surviving (kh, kw, cin) reduction index -- after Pass-1 silence
removal but BEFORE Pass-2 merging -- requires exactly one weight burst,
contiguous across this tile's full output-channel range (all COUT rows of
the array read the same weight simultaneously). Pass-2 merging only packs
two lines into a shared row-slot for timing purposes (see cycles.py); it
does not reduce the number of distinct weights fetched, since a merged
pair still comes from two different (kh, kw, cin) indices. This is why
weight_access_count is len(lines_pass1), not len(lines_pass2) -- the same
count as cycles.py's access_cycle_count.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import PTBReconstructed


def event_to_address(
    reconstructed: PTBReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for line in reconstructed.lines_pass1
    ]


def weight_access_count(reconstructed: PTBReconstructed) -> int:
    return len(reconstructed.lines_pass1)
