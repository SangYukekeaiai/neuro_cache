#!/usr/bin/env python3
"""Build and solve the SNN CoSA scheduling model.

This module is the project-level solver entrypoint.  It wires together the
existing parser, variable, constraint, traffic, and objective modules, then
returns a JSON-friendly final schedule.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, FrozenSet, Optional

from gurobipy import GRB, GurobiError, Model

from snn_cosa.metrics import extract_metrics
from snn_cosa.modes import TrafficMode, _MODE_SPECS
from snn_cosa.model.constraints import (
    add_assignment_constraints,
    add_spatial_constraints,
    add_pe_spatial_split_constraints,
    add_node_capacity_constraints,
    add_no_noc_level_constraints,
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
from snn_cosa.parsers.arch import MEM_NOC, parse_snn_arch
from snn_cosa.parsers.bitwidths import SNNBitwidths, parse_snn_bitwidths
from snn_cosa.parsers.layer import parse_snn_layer
from snn_cosa.parsers.mapspace import parse_snn_mapspace
from snn_cosa.util import build_strategy


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
            model, x, prob, arch, SNN_GB_START_LEVEL
        )

    if arch.node_dim_capacity is not None:
        add_node_capacity_constraints(model, x, prob, arch)

    if arch.single_node:
        add_no_noc_level_constraints(
            model, x, prob, SNN_GB_START_LEVEL, dram_start
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
            result["metrics"] = extract_metrics(
                x, y, prob, bitwidths,
                SNN_GB_START_LEVEL, dram_start, perm_levels, total_levels,
                noc_capacity=noc_capacity,
                zero_vars=zero_vars,
                gb_only_vars=gb_only_vars,
            )

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
