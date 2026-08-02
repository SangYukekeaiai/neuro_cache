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

from typing import Dict, List, Tuple

from parsers.layer import DIM_COUT

from archmodels import NodeTileSpec
from .cycles import group_into_waves
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


def event_to_ticks(reconstructed: GustavReconstructed, tile: NodeTileSpec) -> List[int]:
    """Per-line tick: unlike every other arch, GustavSNN genuinely reads
    multiple distinct weight rows in the same cycle. Within a wave (see
    cycles.py's group_into_waves), each of that wave's submatrices
    independently pops its own next line every cycle -- submatrix sm's
    j-th line (0-based) fires at cycle `wave_start + j`, where wave_start
    accumulates prior waves' `max(len(sm.lines) for sm in wave)` (the same
    quantity _wave_cycle_count sums into mac_cycles). So multiple lines
    share a tick exactly when they're at the same position within their
    own submatrix's line list, in the same wave -- up to PE_COUNT_MAX
    lines can share one tick.

    Traverses reconstructed.submatrices in the same (unsorted) order as
    event_to_address, so tick i always corresponds to
    event_to_address(...)[i], even though wave membership itself is
    computed from the piece_idx-sorted order (group_into_waves)."""
    tick_by_piece: Dict[int, List[int]] = {}
    wave_start = 0
    for wave in group_into_waves(reconstructed):
        for sm in wave:
            tick_by_piece[sm.piece_idx] = [wave_start + j for j in range(len(sm.lines))]
        wave_start += max((len(sm.lines) for sm in wave), default=0)

    return [
        tick_by_piece[sm.piece_idx][j]
        for sm in reconstructed.submatrices
        for j in range(len(sm.lines))
    ]
