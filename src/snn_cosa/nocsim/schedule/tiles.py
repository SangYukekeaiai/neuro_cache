"""Derives one real NodeTileSpec per dram_i from a solved Schedule.

For a single_node arch, NoCLevel is empty/irrelevant and every node visit
is fully resident at NodeLevel EXCEPT whatever the MIP pushed to DRAM --
so node_bound[dim] (the width this dim occupies at every node visit,
INCLUDING both spatial fanout and any leftover NodeLevel-temporal
multiplier) is simply the dimension's total divided by whatever fraction
of it was pushed to DRAM-temporal:

    node_bound[dim] = total[dim] // dram_temporal_total[dim]

This differs from archmodels.dense.DenseStaticComputeModel's node_j,
which ADDITIONALLY divides out spatial_factors[dim] and any NoC-temporal
factor -- appropriate there because spatial fanout across PEs doesn't
cost extra MAC cycles, but wrong here: NodeTileSpec.node_bound must
describe the tile's actual real-trace RESIDENCY width -- what
reconstruct_tile_sequence slices out of the trace, and what address.py's
burst spans (e.g. SpinalFlow's burst covers the tile's "whole assigned
output-channel range" -- the full spatial width, not 1 per PE). Tracing
through PTB's `active_rows = min(tile.node_bound[DIM_COUT], PE_ROWS_MAX)`
and every arch's existing "COUT costs zero/clamped cycles regardless of
magnitude" convention confirms this: node_bound[dim] must include the
full spatial fanout, dividing out ONLY whatever the MIP actually pushed
to DRAM for that dim.

tile_offset[dim] only varies across dims that appear in
schedule.dram_temporal_loops -- the only thing that changes from one node
visit to the next for a single_node arch (NodeLevel/NoCLevel factors are
the same resident block on every visit).
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import Dict, Iterator, List

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.parsers.layer import SNNProb

from .decode import Schedule
from .steps import StepInfo, _decode_dim  # _decode_dim is private to steps.py --
# reused directly rather than re-deriving its mixed-radix decoding a second
# time (matches this codebase's tolerance for a tiny private cross-module
# import over duplicating nontrivial logic; see combine.py's/dense.py's own
# duplicated _dim_totals one-liner for the opposite, "duplicate the trivial
# stuff" convention this module also follows below).


def _dim_totals(loops) -> Dict[int, int]:
    """Return {dim: product-of-all-factors} for every dim that appears in loops.

    Local copy matching combine.py's/dense.py's own copies of this
    one-liner -- this codebase's existing convention for tiny per-module
    helpers rather than a shared cross-module import.
    """
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


def iter_node_tiles(schedule: Schedule, prob: SNNProb) -> Iterator[NodeTileSpec]:
    """Yield one NodeTileSpec per dram_i, in solved-schedule order.

    Args:
        schedule: decoded Schedule (from decode() or schedule_from_strategy()).
        prob:     parsed SNN layer (prob.prob_factors gives each dim's total
                  as a prime-factor list).

    Yields:
        NodeTileSpec(dram_i, node_bound, tile_offset, is_last_K), one per
        dram_i in [0, schedule.dram_num_steps).
    """
    si = StepInfo(schedule, prob)
    dram_t = _dim_totals(schedule.dram_temporal_loops)

    node_bound: Dict[int, int] = {}
    for j, factors in enumerate(prob.prob_factors):
        total_j = reduce(operator.mul, factors, 1)
        node_bound[j] = max(total_j // dram_t.get(j, 1), 1)

    dram_dims: List[int] = []
    for item in schedule.dram_temporal_loops:
        if item.dim not in dram_dims:
            dram_dims.append(item.dim)

    for dram_i in range(schedule.dram_num_steps):
        tile_offset = {
            j: _decode_dim(dram_i, schedule.dram_temporal_loops, j) * node_bound[j]
            for j in dram_dims
        }
        _, is_last_K = si.dram_k_position(dram_i)
        yield NodeTileSpec(
            dram_i=dram_i,
            node_bound=dict(node_bound),
            tile_offset=tile_offset,
            is_last_K=is_last_K,
        )