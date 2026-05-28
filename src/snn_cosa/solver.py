#!/usr/bin/env python3
"""Build and solve the SNN CoSA scheduling model.

This module is the project-level solver entrypoint.  It wires together the
existing parser, variable, constraint, traffic, and objective modules, then
returns a JSON-friendly final schedule.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, Optional

from gurobipy import GRB, GurobiError, Model

from snn_cosa.model.constraints import (
    add_assignment_constraints,
    add_capacity_constraints,
    add_spatial_constraints,
)
from snn_cosa.model.constants import NUM_VARS, VAR_NAMES
from snn_cosa.model.data_size import MEM_NOC, MEM_NODE, compute_log_sizes
from snn_cosa.model.objective import build_objective
from snn_cosa.model.schedule import SNN_GB_START_LEVEL, create_schedule_vars
from snn_cosa.model.traffic.spatial import compute_spatial_traffic
from snn_cosa.model.traffic.temporal import compute_temporal_traffic
from snn_cosa.parsers.arch import parse_snn_arch
from snn_cosa.parsers.bitwidths import parse_snn_bitwidths
from snn_cosa.parsers.layer import parse_snn_layer
from snn_cosa.parsers.mapspace import parse_snn_mapspace


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

    buf_util = compute_log_sizes(x, prob, bitwidths, SNN_GB_START_LEVEL, dram_start)
    add_capacity_constraints(model, buf_util, arch)
    _, temporal_traffic = compute_temporal_traffic(
        x, y, prob, SNN_GB_START_LEVEL, dram_start, perm_levels
    )
    spatial_cost = compute_spatial_traffic(x, prob, SNN_GB_START_LEVEL, dram_start)
    build_objective(model, buf_util, temporal_traffic, spatial_cost)

    model.optimize()

    return _collect_result(
        model, prob, bitwidths, mapspace, x, y, buf_util,
        temporal_traffic, spatial_cost, perm_levels, total_levels,
        dram_start, layer_path, arch_path, mapspace_path,
    )


def _collect_result(
    model: Model,
    prob: Any,
    bitwidths: Any,
    mapspace: Any,
    x: Dict,
    y: Dict,
    buf_util: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
    perm_levels: int,
    total_levels: int,
    dram_start: int,
    layer_path: pathlib.Path,
    arch_path: pathlib.Path,
    mapspace_path: Optional[pathlib.Path],
) -> Dict[str, Any]:
    has_solution = model.SolCount > 0
    result: Dict[str, Any] = {
        "status": _status_name(model.Status),
        "status_code": model.Status,
        "has_solution": has_solution,
        "objective": _safe_attr(model, "ObjVal") if has_solution else None,
        "runtime_sec": _safe_attr(model, "Runtime"),
        "mip_gap": _safe_attr(model, "MIPGap") if has_solution else None,
        "model_size": {
            "variables": model.NumVars,
            "constraints": model.NumConstrs,
            "quadratic_constraints": model.NumQConstrs,
        },
        "inputs": {
            "layer": str(layer_path.resolve()),
            "arch": str(arch_path.resolve()),
            "mapspace": str(mapspace_path.resolve()) if mapspace_path else None,
        },
        "problem": {
            prob.prob_idx_name_dict[i]: prob.prob_bound[i]
            for i in range(prob.prob_levels)
        },
        "bitwidths": {
            "weight": bitwidths.bw_weight,
            "psum": bitwidths.bw_psum,
            "vmem": bitwidths.bw_vmem,
        },
        "layout": {
            "gb_start_level": SNN_GB_START_LEVEL,
            "dram_start": dram_start,
            "perm_levels": perm_levels,
            "total_levels": total_levels,
        },
    }

    if mapspace is not None:
        result["mapspace"] = {"spatial_dims": [
            prob.prob_idx_name_dict[i] for i in mapspace.spatial_dim_indices
        ]}

    if has_solution:
        result["schedule"] = _extract_schedule(x, y, prob, total_levels, dram_start)
        result["costs"] = _extract_costs(buf_util, temporal_traffic, spatial_cost)

    return result


def _extract_schedule(
    x: Dict,
    y: Dict,
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

    y_values = []
    for (v, i), var in sorted(y.items()):
        if var.X > 0.5:
            y_values.append(
                {"var": VAR_NAMES[v], "var_index": v, "level": i, "value": int(round(var.X))}
            )

    return {
        "levels": levels,
        "reuse_indicators": y_values,
        "summary": _summarize_levels(levels, prob),
    }


def _summarize_levels(levels: list, prob: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for region in ("NodeLevel", "NoCLevel", "OffChip"):
        summary[region] = {
            kind: {prob.prob_idx_name_dict[j]: 1 for j in range(prob.prob_levels)}
            for kind in ("spatial", "temporal")
        }
    for level in levels:
        region = level["region"]
        for factor in level["factors"]:
            dim = factor["dim"]
            kind = factor["kind"]
            summary[region][kind][dim] *= factor["factor"]
    return summary


def _extract_costs(buf_util: Dict, temporal_traffic: Dict, spatial_cost: Dict) -> Dict[str, Any]:
    costs = {}
    for v, name in enumerate(VAR_NAMES):
        node_log2_bytes = _value(buf_util[(v, MEM_NODE)])
        noc_log2_bytes = _value(buf_util[(v, MEM_NOC)])
        costs[name] = {
            "node_log2_bytes": node_log2_bytes,
            "node_bytes": 2.0 ** node_log2_bytes,
            "noc_log2_bytes": noc_log2_bytes,
            "noc_bytes": 2.0 ** noc_log2_bytes,
            "temporal_log2_elements": _value(temporal_traffic[v]),
            "spatial_log2_elements": _value(spatial_cost[v]),
        }
    return costs


def _region(level: int, dram_start: int) -> str:
    if level < SNN_GB_START_LEVEL:
        return "NodeLevel"
    if level < dram_start:
        return "NoCLevel"
    return "OffChip"


def _status_name(status: int) -> str:
    return _STATUS_NAMES.get(status, f"STATUS_{status}")


def _value(expr: Any) -> float:
    if hasattr(expr, "getValue"):
        return float(expr.getValue())
    return float(expr)


def _safe_attr(obj: Any, name: str) -> Optional[float]:
    try:
        return getattr(obj, name)
    except (AttributeError, GurobiError):
        return None


__all__ = ["solve_schedule"]
