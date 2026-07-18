"""Default ArchComputeModel: today's analytical dense-tile formula.

This is combine.py's original _pe_cycles/_lif_cycles, refactored behind
the ArchComputeModel Protocol with zero behavior change. It ignores the
real trace and the NodeTileSpec entirely -- every node-level tile gets the
same cycle count, computed once from the schedule's loop-factor structure,
matching combine()'s existing single upfront call (mac_cyc/lif_cyc are
computed once per run today, not per tile, because this formula is static).
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import Any, Dict, List

from snn_cosa.mip_solver.constants import _A, VAR_VMEM
from snn_cosa.nocsim.schedule.decode import Schedule
from snn_cosa.parsers.layer import SNNProb

from . import ArchComputeModel, ComputeCycles, NodeTileSpec


def _dim_totals(loops) -> Dict[int, int]:
    """Return {dim: product-of-all-factors} for every dim that appears in loops."""
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


class DenseStaticComputeModel(ArchComputeModel):
    def __init__(self, schedule: Schedule, prob: SNNProb) -> None:
        self._schedule = schedule
        self._prob = prob

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        return None

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(
            mac_cycles=self._pe_cycles(),
            lif_cycles=self._lif_cycles(),
        )

    def weight_addresses(self, packed: Any, tile: NodeTileSpec) -> List[Any]:
        return []

    def _pe_cycles(self) -> int:
        noc_t = _dim_totals(self._schedule.noc_temporal_loops)
        dram_t = _dim_totals(self._schedule.dram_temporal_loops)
        cycles = 1
        for j, factors in enumerate(self._prob.prob_factors):
            total_j = reduce(operator.mul, factors, 1)
            above_j = (
                self._schedule.spatial_factors[j]
                * noc_t.get(j, 1)
                * dram_t.get(j, 1)
            )
            node_j = total_j // above_j
            cycles *= max(node_j, 1)
        return cycles

    def _lif_cycles(self) -> int:
        noc_t = _dim_totals(self._schedule.noc_temporal_loops)
        dram_t = _dim_totals(self._schedule.dram_temporal_loops)
        cycles = 1
        for j, factors in enumerate(self._prob.prob_factors):
            if _A[j][VAR_VMEM] == 0:
                continue
            total_j = reduce(operator.mul, factors, 1)
            above_j = (
                self._schedule.spatial_factors[j]
                * noc_t.get(j, 1)
                * dram_t.get(j, 1)
            )
            node_j = total_j // above_j
            cycles *= max(node_j, 1)
        return cycles
