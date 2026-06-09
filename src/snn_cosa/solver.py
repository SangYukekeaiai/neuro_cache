#!/usr/bin/env python3
"""Build and solve the SNN CoSA scheduling model.

This module is the project-level solver entrypoint.  It wires together the
existing parser, variable, constraint, traffic, and objective modules, then
returns a JSON-friendly final schedule.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, Optional

from gurobipy import GRB, GurobiError, Model

from snn_cosa.model.constraints import (
    add_assignment_constraints,
    add_spatial_constraints,
    add_pe_spatial_split_constraints,
    add_ootk_gb,
    add_ootk_dram,
    add_ootk_boundary,
    add_xxxt_dram,
    add_xxxt_gb,
    add_oooo_dram,
    add_oooo_gb,
)
from snn_cosa.model.objectives import (
    add_utilization_capacity_constraints,
    build_objective,
    build_utilization_terms,
)
from snn_cosa.model.schedule import SNN_GB_START_LEVEL, create_schedule_vars
from snn_cosa.model.objectives.traffic import (
    compute_spatial_traffic,
    compute_temporal_traffic,
)
from snn_cosa.model.constants import (
    NUM_VARS, VAR_NAMES, VAR_WEIGHT, VAR_PSUM, VAR_VMEM, TRAFFIC_MULT, _A,
)
from snn_cosa.parsers.arch import MEM_NOC, parse_snn_arch
from snn_cosa.parsers.bitwidths import SNNBitwidths, parse_snn_bitwidths
from snn_cosa.parsers.layer import parse_snn_layer, SNN_REDUCTION_DIMS
from snn_cosa.parsers.mapspace import parse_snn_mapspace
from snn_cosa.util import build_strategy


# ---------------------------------------------------------------------------
# TrafficMode — selects which permutation constraints and traffic formula
# ---------------------------------------------------------------------------

class TrafficMode(str, Enum):
    BASE            = "base"
    PSUM_GB_OOTK    = "psum_gb_ootk"
    PSUM_DRAM_OOTK  = "psum_dram_ootk"
    PSUM_BOUNDARY   = "psum_boundary"
    VMEM_DRAM_XXXT  = "vmem_dram_xxxt"
    VMEM_GB_XXXT    = "vmem_gb_xxxt"
    BOTH_DRAM_OOOO  = "both_dram_oooo"
    BOTH_GB_OOOO    = "both_gb_oooo"


@dataclass(frozen=True)
class _ModeSpec:
    add_constraints: Optional[Callable]   # None for BASE
    zero_vars:       FrozenSet[int]        # TR[v] = 0  (GB-side patterns)
    gb_only_vars:    FrozenSet[int]        # Td[v] = 1  (DRAM-side patterns)


_MODE_SPECS: Dict[TrafficMode, _ModeSpec] = {
    TrafficMode.BASE:           _ModeSpec(None,              frozenset(),                    frozenset()),
    TrafficMode.PSUM_GB_OOTK:   _ModeSpec(add_ootk_gb,       frozenset({VAR_PSUM}),          frozenset()),
    TrafficMode.PSUM_DRAM_OOTK: _ModeSpec(add_ootk_dram,     frozenset(),                    frozenset({VAR_PSUM})),
    TrafficMode.PSUM_BOUNDARY:  _ModeSpec(add_ootk_boundary, frozenset(),                    frozenset({VAR_PSUM})),
    TrafficMode.VMEM_DRAM_XXXT: _ModeSpec(add_xxxt_dram,     frozenset(),                    frozenset({VAR_VMEM})),
    TrafficMode.VMEM_GB_XXXT:   _ModeSpec(add_xxxt_gb,       frozenset({VAR_VMEM}),          frozenset()),
    TrafficMode.BOTH_DRAM_OOOO: _ModeSpec(add_oooo_dram,     frozenset(),                    frozenset({VAR_PSUM, VAR_VMEM})),
    TrafficMode.BOTH_GB_OOOO:   _ModeSpec(add_oooo_gb,       frozenset({VAR_PSUM, VAR_VMEM}), frozenset()),
}


_STATUS_NAMES = {
    GRB.OPTIMAL: "OPTIMAL",
    GRB.INFEASIBLE: "INFEASIBLE",
    GRB.INF_OR_UNBD: "INF_OR_UNBD",
    GRB.UNBOUNDED: "UNBOUNDED",
    GRB.TIME_LIMIT: "TIME_LIMIT",
    GRB.INTERRUPTED: "INTERRUPTED",
    GRB.SUBOPTIMAL: "SUBOPTIMAL",
}


def solve_schedule(
    layer_path: pathlib.Path | str,
    arch_path: pathlib.Path | str,
    mapspace_path: Optional[pathlib.Path | str] = None,
    time_limit: Optional[float] = None,
    mip_gap: Optional[float] = None,
    output_flag: bool = False,
    traffic_mode: TrafficMode = TrafficMode.BASE,
    return_metrics: bool = False,
) -> Dict[str, Any]:
    """Solve one SNN scheduling problem and return a JSON-friendly result."""
    layer_path = pathlib.Path(layer_path)
    arch_path = pathlib.Path(arch_path)
    mapspace_path = pathlib.Path(mapspace_path) if mapspace_path else None

    prob = parse_snn_layer(layer_path)
    arch = parse_snn_arch(arch_path)
    bitwidths = parse_snn_bitwidths(arch_path)

    mapspace = None
    if mapspace_path is not None:
        mapspace = parse_snn_mapspace(mapspace_path)
        mapspace.init(prob, arch)

    model = Model("snn_cosa_schedule")
    model.Params.OutputFlag = int(output_flag)
    if time_limit is not None:
        model.Params.TimeLimit = float(time_limit)
    if mip_gap is not None:
        model.Params.MIPGap = float(mip_gap)

    x, y, perm_levels, total_levels, dram_start = create_schedule_vars(
        model, prob, arch, SNN_GB_START_LEVEL
    )

    add_assignment_constraints(
        model,
        x,
        y,
        prob,
        perm_levels,
        total_levels,
        gb_start_level=SNN_GB_START_LEVEL,
        dram_start=dram_start,
    )
    add_spatial_constraints(
        model,
        x,
        prob,
        arch,
        SNN_GB_START_LEVEL,
        dram_start,
        perm_levels,
    )

    if arch.node_pe_spatial_split is not None:
        add_pe_spatial_split_constraints(
            model, x, prob, arch, SNN_GB_START_LEVEL, dram_start
        )

    spec = _MODE_SPECS[traffic_mode]
    if spec.add_constraints is not None:
        spec.add_constraints(model, x, prob, SNN_GB_START_LEVEL, dram_start, perm_levels)

    utilization, util_hat, data_size = build_utilization_terms(
        x,
        prob,
        bitwidths,
        arch,
        SNN_GB_START_LEVEL,
        dram_start,
    )
    add_utilization_capacity_constraints(model, utilization, arch)
    _, temporal_traffic = compute_temporal_traffic(
        x, y, prob, SNN_GB_START_LEVEL, dram_start, perm_levels,
        gb_only_vars=spec.gb_only_vars,
    )
    spatial_cost = compute_spatial_traffic(x, prob, SNN_GB_START_LEVEL, dram_start)
    build_objective(
        model,
        data_size,
        util_hat,
        temporal_traffic,
        spatial_cost,
        x,
        prob.prob_factors,
        range(total_levels),
        range(prob.prob_levels),
        zero_vars=spec.zero_vars,
        gb_only_vars=spec.gb_only_vars,
    )

    model.optimize()

    return _collect_result(
        model, prob, x, y, total_levels, dram_start,
        perm_levels=perm_levels,
        bitwidths=bitwidths if return_metrics else None,
        noc_capacity=arch.mem_entries[MEM_NOC] if return_metrics else None,
        zero_vars=spec.zero_vars,
        gb_only_vars=spec.gb_only_vars,
    )


def _collect_result(
    model: Model,
    prob: Any,
    x: Dict,
    y: Dict,
    total_levels: int,
    dram_start: int,
    perm_levels: int = 0,
    bitwidths: Optional[SNNBitwidths] = None,
    noc_capacity: Optional[Dict[str, int]] = None,
    zero_vars: FrozenSet[int] = frozenset(),
    gb_only_vars: FrozenSet[int] = frozenset(),
) -> Dict[str, Any]:
    has_solution = model.SolCount > 0
    result: Dict[str, Any] = {
        "status": _status_name(model.Status),
        "has_solution": has_solution,
        "objective": _safe_attr(model, "ObjVal") if has_solution else None,
    }

    if has_solution:
        result["strategy"] = _extract_strategy(x, prob, total_levels, dram_start)
        if bitwidths is not None:
            result["metrics"] = _extract_metrics(
                x, y, prob, bitwidths,
                SNN_GB_START_LEVEL, dram_start, perm_levels, total_levels,
                noc_capacity=noc_capacity,
                zero_vars=zero_vars,
                gb_only_vars=gb_only_vars,
            )

    return result


def _extract_metrics(
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
    """Read per-variable metrics directly from the binary solution matrix.

    All values are in linear (non-log) scale, computed by multiplying the
    actual prime factors selected by the solver.

    zero_vars / gb_only_vars mirror the same parameters in the optimizer so
    that the reported temporal_traffic values reflect the mode's traffic model:
      zero_vars    – TR[v] = 0; temporal_traffic[v] is set to 0.
      gb_only_vars – traffic restricted to GB perm slots only (matching
                     the gb_only_vars restriction in compute_temporal_traffic).
    """
    pf = prob.prob_factors
    perm_range = range(gb_start_level, dram_start + perm_levels)
    gb_perm    = range(gb_start_level, dram_start)

    bytes_per_elem = [
        bitwidths.bw_weight / 8,
        bitwidths.bw_psum / 8,
        bitwidths.bw_vmem / 8,
    ]

    def _xv(i: int, j: int, n: int, k: int) -> bool:
        return x[(i, j, n, k)].X > 0.5

    def _yv(v: int, i: int) -> bool:
        return y[(v, i)].X > 0.5

    # Util_v: bytes in GB = base_bytes × all factors (spatial or temporal)
    # at NodeLevel + NoCLevel for dimensions where A[j][v] = 1.
    util: Dict[str, float] = {}
    for v in range(NUM_VARS):
        val = bytes_per_elem[v]
        for i in range(dram_start):
            for j, factors in enumerate(pf):
                if _A[j][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    if _xv(i, j, n, 0) or _xv(i, j, n, 1):
                        val *= factor
        util[VAR_NAMES[v]] = val

    # SpatialCost_v: NoC spatial fanout product for v-relevant dimensions.
    spatial_cost: Dict[str, float] = {}
    for v in range(NUM_VARS):
        val = 1.0
        for i in range(gb_start_level, dram_start):
            for j, factors in enumerate(pf):
                if _A[j][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    if _xv(i, j, n, 0):
                        val *= factor
        spatial_cost[VAR_NAMES[v]] = val

    # TemporalTraffic_v: mirrors compute_temporal_traffic with zero_vars /
    #   gb_only_vars applied so reported values match the optimizer's model.
    #   zero_vars    → TR[v] = 0, traffic contribution is 0.
    #   gb_only_vars → restrict summation to GB perm slots only.
    temporal_traffic: Dict[str, float] = {}
    for v in [VAR_WEIGHT, VAR_PSUM]:
        if v in zero_vars:
            temporal_traffic[VAR_NAMES[v]] = 0.0
            continue
        active_range = gb_perm if v in gb_only_vars else perm_range
        val = float(TRAFFIC_MULT[v])
        for i in active_range:
            if _yv(v, i):
                for j, factors in enumerate(pf):
                    for n, factor in enumerate(factors):
                        if _xv(i, j, n, 1):
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
                    if _xv(i, j, n, 1):
                        vmem_val *= factor
        temporal_traffic[VAR_NAMES[VAR_VMEM]] = vmem_val

    # Dl: total temporal iterations across all levels.
    dl = 1
    for i in range(total_levels):
        for j, factors in enumerate(pf):
            for n, factor in enumerate(factors):
                if _xv(i, j, n, 1):
                    dl *= factor

    result: Dict[str, Any] = {
        "util": util,
        "spatial_cost": spatial_cost,
        "temporal_traffic": temporal_traffic,
        "delay": dl,
    }
    if noc_capacity is not None:
        result["capacity"] = dict(noc_capacity)
    return result


def _extract_strategy(
    x: Dict,
    prob: Any,
    total_levels: int,
    dram_start: int,
) -> Dict[str, Any]:
    levels = []
    for i in range(total_levels):
        factors = []
        for j, f_j in enumerate(prob.prob_factors):
            for n, factor in enumerate(f_j):
                for k, kind in enumerate(("spatial", "temporal")):
                    if x[(i, j, n, k)].X > 0.5:
                        factors.append(
                            {
                                "dim": prob.prob_idx_name_dict[j],
                                "dim_index": j,
                                "factor_index": n,
                                "factor": factor,
                                "kind": kind,
                            }
                        )
        levels.append({"level": i, "region": _region(i, dram_start), "factors": factors})

    return build_strategy(levels)


def _region(level: int, dram_start: int) -> str:
    if level < SNN_GB_START_LEVEL:
        return "NodeLevel"
    if level < dram_start:
        return "NoCLevel"
    return "OffChip"


def _status_name(status: int) -> str:
    return _STATUS_NAMES.get(status, f"STATUS_{status}")


def _safe_attr(obj: Any, name: str) -> Optional[float]:
    try:
        return getattr(obj, name)
    except (AttributeError, GurobiError):
        return None


__all__ = ["TrafficMode", "solve_schedule"]
