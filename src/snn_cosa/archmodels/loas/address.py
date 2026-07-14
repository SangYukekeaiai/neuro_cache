"""LoAS weight address per non-silent input neuron.

The weight access pattern is driven by the INPUT's own address: for a
row with non-silent k's at, say, positions 0 and K, `[m, 0]` maps to
`weight[k=0, cout_start : cout_start+16]` and `[m, K]` maps to
`weight[k=K, cout_start : cout_start+16]` -- one weight burst per
non-silent (kh, kw, cin) reduction index, each covering the tile's whole
assigned output-channel range as a single contiguous "line" of weight
data (16-wide in this deployment). Because weight B is dense (no
column-wise bitmask compression, see cycles.py's docstring), this burst
always covers the *entire* assigned COUT range regardless of individual
weight values -- there is no further per-output skip.

Like cycles.py, this module doesn't read reconstructed.bitmask/.ptr --
only .lines (the actual non-silent (kh, kw, cin) positions) matters for
addressing.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import LoASReconstructed


def event_to_address(
    reconstructed: LoASReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for line in reconstructed.lines
    ]


def weight_access_count(reconstructed: LoASReconstructed) -> int:
    return len(reconstructed.lines)