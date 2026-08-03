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

from archmodels import NodeTileSpec
from parsers.layer import (
    SNNProb,
    DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT,
)

from .decode import Schedule
from .steps import StepInfo, _decode_dim  # _decode_dim is private to steps.py --
# reused directly rather than re-deriving its mixed-radix decoding a second
# time (matches this codebase's tolerance for a tiny private cross-module
# import over duplicating nontrivial logic; see combine.py's/dense.py's own
# duplicated _dim_totals one-liner for the opposite, "duplicate the trivial
# stuff" convention this module also follows below).

# core_id mixed-radix order, inner -> outer. Deliberately matches combine.py's
# Way-2 NoC layout (X = T*WO*HO, Y = CIN*KW*KH*COUT) so a core_id decomposes
# directly into NoC.get_xy's pe_id = x + y*X scheme with no separate
# translation layer, if a later stage wants NoC-hop consistency. See
# log/2026-08-02-multinode-core-driven-weight-trace-plan.md.
_CORE_ID_ORDER = [DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT]


def encode_core_id(idx: Dict[int, int], spatial_factors: Dict[int, int]) -> int:
    """Inverse of decode_core_id: a per-dim spatial index -> one flat core_id."""
    core_id = 0
    running_base = 1
    for d in _CORE_ID_ORDER:
        core_id += idx.get(d, 0) * running_base
        running_base *= spatial_factors.get(d, 1)
    return core_id


def decode_core_id(core_id: int, spatial_factors: Dict[int, int]) -> Dict[int, int]:
    """Flat core_id -> {dim: spatial index}, one entry per dim in
    _CORE_ID_ORDER. A dim with spatial_factors[dim] in (missing, 1)
    contributes radix 1 and always decodes to index 0 -- no special-casing
    needed for schedules that don't spatially split every dim."""
    idx: Dict[int, int] = {}
    rem = core_id
    for d in _CORE_ID_ORDER:
        radix = spatial_factors.get(d, 1)
        idx[d] = rem % radix
        rem //= radix
    return idx


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
    """Yield one NodeTileSpec per (dram_i, noc_i, core_id), in solved-schedule
    order. Degenerates exactly to the original single-node-only behavior
    (one NodeTileSpec per dram_i, noc_i=0, core_id=0) whenever
    schedule.noc_temporal_loops is empty and schedule.spatial_factors is
    trivial (all 1) -- true for every single_node schedule, since NoCLevel
    is empty/irrelevant there. See
    log/2026-08-02-multinode-core-driven-weight-trace-plan.md.

    node_bound[dim] now divides out DRAM-temporal, NoC-temporal, AND spatial
    (inter-core) factors -- single-node only ever divided out DRAM-temporal,
    since NoCLevel is empty there. tile_offset[dim] additively composes a
    spatial slice offset (which core owns this dim's slice) with the
    existing per-tile temporal offset (dram + noc), since a dim can be both
    spatially split across cores and still temporally stepped within one
    core's own slice.

    Args:
        schedule: decoded Schedule (from decode() or schedule_from_strategy()).
        prob:     parsed SNN layer (prob.prob_factors gives each dim's total
                  as a prime-factor list).

    Yields:
        NodeTileSpec(dram_i, noc_i, core_id, node_bound, tile_offset,
        is_last_K), one per (dram_i, noc_i, core_id) triple.
    """
    si = StepInfo(schedule, prob)
    dram_t = _dim_totals(schedule.dram_temporal_loops)
    noc_t = _dim_totals(schedule.noc_temporal_loops)
    spatial = schedule.spatial_factors

    node_bound: Dict[int, int] = {}
    for j, factors in enumerate(prob.prob_factors):
        total_j = reduce(operator.mul, factors, 1)
        divisor = dram_t.get(j, 1) * noc_t.get(j, 1) * spatial.get(j, 1)
        node_bound[j] = max(total_j // divisor, 1)

    offset_dims: List[int] = []
    for item in schedule.dram_temporal_loops + schedule.noc_temporal_loops:
        if item.dim not in offset_dims:
            offset_dims.append(item.dim)
    for j, factor in spatial.items():
        if factor > 1 and j not in offset_dims:
            offset_dims.append(j)

    num_cores = reduce(operator.mul, spatial.values(), 1)

    for dram_i in range(schedule.dram_num_steps):
        for noc_i in range(schedule.noc_num_steps):
            # Combined (DRAM + NoC) K-position -- correct for both single-
            # node (noc_temporal_loops empty, noc_i always 0, coincides
            # exactly with the old DRAM-only si.dram_k_position(dram_i)) and
            # multi-node (where K may be a NoC-temporal dim, which the old
            # DRAM-only call would silently mis-flag).
            _, is_last_K = si.k_position(dram_i, noc_i)
            for core_id in range(num_cores):
                core_idx = decode_core_id(core_id, spatial)
                tile_offset = {
                    j: (
                        core_idx.get(j, 0) * node_bound[j] * noc_t.get(j, 1) * dram_t.get(j, 1)
                        + _decode_dim(noc_i, schedule.noc_temporal_loops, j) * node_bound[j] * dram_t.get(j, 1)
                        + _decode_dim(dram_i, schedule.dram_temporal_loops, j) * node_bound[j]
                    )
                    for j in offset_dims
                }
                yield NodeTileSpec(
                    dram_i=dram_i,
                    noc_i=noc_i,
                    core_id=core_id,
                    node_bound=dict(node_bound),
                    tile_offset=tile_offset,
                    is_last_K=is_last_K,
                )