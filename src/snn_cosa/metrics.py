#!/usr/bin/env python3
"""Post-solve linear-scale metric evaluation for SNN CoSA.

After model.optimize() the Gurobi variables carry solved binary values.
This module reads those values and recomputes the same three quantities
that objectives/ expresses symbolically — but in linear (non-log) scale,
by multiplying the actual prime factors the solver chose.

Public entry point:  extract_metrics(x, y, prob, bitwidths, ...)

Four private helpers do one evaluation each:
  _eval_util              — bytes resident in GB per variable
  _eval_spatial_cost      — NoC spatial fanout product per variable
  _eval_temporal_traffic  — temporal traffic, honoring zero_vars / gb_only_vars
  _eval_delay             — total temporal iterations across all levels
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional

from snn_cosa.mip_solver.constants import (
    NUM_VARS, VAR_NAMES, VAR_WEIGHT, VAR_PSUM, VAR_VMEM, TRAFFIC_MULT, _A,
)
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.parsers.layer import SNN_REDUCTION_DIMS


# ---------------------------------------------------------------------------
# Private helpers — one evaluation each
# ---------------------------------------------------------------------------

def _eval_util(
    x: Dict,
    pf: List[List[int]],
    bytes_per_elem: List[float],
    dram_start: int,
) -> Dict[str, float]:
    """Util_v: bytes in GB = base_bytes × all assigned factors at levels < dram_start.

    Both spatial (k=0) and temporal (k=1) factors are included; the GB tile
    footprint is the product of every factor assigned at or inside the GB boundary.
    Only dimensions where A[j][v] = 1 contribute to variable v's footprint.
    """
    util: Dict[str, float] = {}
    for v in range(NUM_VARS):
        val = bytes_per_elem[v]
        for i in range(dram_start):
            for j, factors in enumerate(pf):
                if _A[j][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    if x[(i, j, n, 0)].X > 0.5 or x[(i, j, n, 1)].X > 0.5:
                        val *= factor
        util[VAR_NAMES[v]] = val
    return util


def _eval_spatial_cost(
    x: Dict,
    pf: List[List[int]],
    gb_start_level: int,
    dram_start: int,
) -> Dict[str, float]:
    """SpatialCost_v: NoC spatial fanout product for v-relevant dimensions.

    Only NoCLevel perm slots [gb_start_level, dram_start) and only k=0
    (spatial) assignments are included. OffChip spatial is forbidden by
    constraints, so dram slots are excluded.
    """
    spatial_cost: Dict[str, float] = {}
    for v in range(NUM_VARS):
        val = 1.0
        for i in range(gb_start_level, dram_start):
            for j, factors in enumerate(pf):
                if _A[j][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    if x[(i, j, n, 0)].X > 0.5:
                        val *= factor
        spatial_cost[VAR_NAMES[v]] = val
    return spatial_cost


def _eval_temporal_traffic(
    x: Dict,
    y: Dict,
    pf: List[List[int]],
    perm_range: range,
    gb_perm: range,
    zero_vars: FrozenSet[int],
    gb_only_vars: FrozenSet[int],
) -> Dict[str, float]:
    """TemporalTraffic_v: linear-scale mirror of compute_temporal_traffic.

    weight / psum (bilinear in log-space):
      val = TRAFFIC_MULT[v] × product of temporal factors at slots where y[v,i]=1
      Active range restricted to gb_perm when v in gb_only_vars.

    vmem (linear in log-space — no y indicator):
      val = TRAFFIC_MULT[vmem] × product of non-reduction temporal factors
      Active range restricted to gb_perm when VAR_VMEM in gb_only_vars.

    zero_vars: TR[v] = 0 for the given variable indices.
    """
    temporal_traffic: Dict[str, float] = {}

    for v in [VAR_WEIGHT, VAR_PSUM]:
        if v in zero_vars:
            temporal_traffic[VAR_NAMES[v]] = 0.0
            continue
        active_range = gb_perm if v in gb_only_vars else perm_range
        val = float(TRAFFIC_MULT[v])
        for i in active_range:
            if y[(v, i)].X > 0.5:
                for j, factors in enumerate(pf):
                    for n, factor in enumerate(factors):
                        if x[(i, j, n, 1)].X > 0.5:
                            val *= factor
        temporal_traffic[VAR_NAMES[v]] = val

    if VAR_VMEM in zero_vars:
        temporal_traffic[VAR_NAMES[VAR_VMEM]] = 0.0
    else:
        vmem_range = gb_perm if VAR_VMEM in gb_only_vars else perm_range
        vmem_val = float(TRAFFIC_MULT[VAR_VMEM])
        for i in vmem_range:
            for j, factors in enumerate(pf):
                if j in SNN_REDUCTION_DIMS:
                    continue
                for n, factor in enumerate(factors):
                    if x[(i, j, n, 1)].X > 0.5:
                        vmem_val *= factor
        temporal_traffic[VAR_NAMES[VAR_VMEM]] = vmem_val

    return temporal_traffic


def _eval_delay(
    x: Dict,
    pf: List[List[int]],
    total_levels: int,
) -> int:
    """Dl: product of all temporal prime factors across every loop level."""
    dl = 1
    for i in range(total_levels):
        for j, factors in enumerate(pf):
            for n, factor in enumerate(factors):
                if x[(i, j, n, 1)].X > 0.5:
                    dl *= factor
    return dl


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_metrics(
    x: Dict,
    y: Dict,
    prob: Any,
    bitwidths: SNNBitwidths,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
    total_levels: int,
    noc_capacity: Optional[Dict[str, int]] = None,
    zero_vars: FrozenSet[int] = frozenset(),
    gb_only_vars: FrozenSet[int] = frozenset(),
) -> Dict[str, Any]:
    """Read per-variable metrics from the solved binary solution matrix.

    All values are in linear (non-log) scale.  zero_vars / gb_only_vars must
    mirror the mode flags passed to the optimizer so that reported
    temporal_traffic values match what the solver was minimising.
    """
    pf             = prob.prob_factors
    perm_range     = range(gb_start_level, dram_start + perm_levels)
    gb_perm        = range(gb_start_level, dram_start)
    bytes_per_elem = [bitwidths.bw_weight / 8, bitwidths.bw_psum / 8, bitwidths.bw_vmem / 8]

    util             = _eval_util(x, pf, bytes_per_elem, dram_start)
    spatial_cost     = _eval_spatial_cost(x, pf, gb_start_level, dram_start)
    temporal_traffic = _eval_temporal_traffic(
        x, y, pf, perm_range, gb_perm, zero_vars, gb_only_vars,
    )
    dl = _eval_delay(x, pf, total_levels)

    result: Dict[str, Any] = {
        "util":             util,
        "spatial_cost":     spatial_cost,
        "temporal_traffic": temporal_traffic,
        "delay":            dl,
    }
    if noc_capacity is not None:
        result["capacity"] = dict(noc_capacity)
    return result


__all__ = ["extract_metrics"]
