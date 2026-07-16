"""GustavSNN weight address per non-zero (submatrix, row) pair.

Each submatrix's own non-zero (kh,kw,cin) rows independently trigger a
weight-line fetch, `[m, kh,kw,cin] -> weight[k=(kh,kw,cin),
cout_start:cout_start+8]` -- one burst per non-zero row PER SUBMATRIX,
covering the tile's whole assigned COUT range (8-wide in this
deployment). Because the (up to PE_COUNT_MAX=8) submatrices in a tile run
in parallel PEs, up to PE_COUNT_MAX distinct weight-line fetches can be
issued in the same cycle-position -- one per PE that still has a non-zero
row to process there.

This is an EXPLICIT departure from the paper's Section V-A, which shares
one local weight buffer across all PEs in a tile (a weight row fetched
ONCE, reused by every PE whose submatrix also needs that same (kh,kw,cin)
this tick) -- this deployment does not model that sharing/deduplication:
each submatrix's fetches are counted independently, even when two
submatrices happen to need the identical (kh,kw,cin) weight row in the
same tick. weight_access_count is therefore the sum of every submatrix's
own non-zero-row count, not the count of distinct (kh,kw,cin) values
across the tile.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import GustavReconstructed


def event_to_address(
    reconstructed: GustavReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for sm in reconstructed.submatrices
        for line in sm.lines
    ]


def weight_access_count(reconstructed: GustavReconstructed) -> int:
    return sum(len(sm.lines) for sm in reconstructed.submatrices)
