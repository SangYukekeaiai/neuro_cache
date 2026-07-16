"""Prosperity weight address per residual ('pattern') spike bit.

Each row's residual pattern (the query row's bits XOR its chosen Prefix
row's bits -- see reconstruct.py) still needs one weight-row fetch per
surviving 1-bit: the paper's Processor (Section V-E, Fig. 5(d) Step 10)
decodes the weight address by bit-scan-forward on the ProSparsity
pattern, fetching the K x N weight sub-matrix's row at that bit's
(kh, kw) index, spanning the FULL N=COUT range in one burst (the weight
sub-matrix has k rows and n columns, Section V-A) -- "load one line of
[KH, KW, COUT[start, start+127]]" per the pilot's own spec. This is
identical in shape to SpinalFlow's/PTB's/LoAS's/GustavSNN's own
(kh, kw, cin, cout_start, cout_end) burst tuples; cin is always this
tile's single fixed input channel (see reconstruct.py's module docstring
-- CIN is barred from NodeLevel in this pilot, one channel per node
visit), included only for shape parity with the other archmodels'
addresses, not because Prosperity's own weight indexing uses it.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_CIN, DIM_COUT, DIM_KW

from .. import NodeTileSpec
from .reconstruct import ProsperityReconstructed


def event_to_address(
    reconstructed: ProsperityReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    kw_n = tile.node_bound[DIM_KW]
    cin = tile.tile_offset.get(DIM_CIN, 0)
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]

    addrs: List[Tuple[int, int, int, int, int]] = []
    for row in reconstructed.rows:
        for bit_idx, bit in enumerate(row.pattern):
            if bit:
                kh, kw = divmod(bit_idx, kw_n)
                addrs.append((kh, kw, cin, cout_off, cout_off + cout_n))
    return addrs


def weight_access_count(reconstructed: ProsperityReconstructed) -> int:
    return sum(sum(row.pattern) for row in reconstructed.rows)
