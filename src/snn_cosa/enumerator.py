#!/usr/bin/env python3
"""Enumerate all CoSA traffic-mode variants and select the globally optimal schedule.

Comparison objective (lower is better):

    score = W_u  × (Util_weight + Util_psum + Util_vmem)
          + W_Tr × (Tr_weight   + Tr_psum   + Tr_vmem)
          + W_Dl × Dl

where, for each variable v (all values in linear, non-log scale):

    Util_v        — bytes resident in the Global Buffer
    Tr_v          — Util_v × SpatialCost_v × TemporalTraffic_v
    Dl            — total temporal iterations across all levels

Default weights match CoSA's existing w_utilization / w_traffic / w_compute:
    W_u = 0.1,  W_Tr = 1.0,  W_Dl = 10.0
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional

from snn_cosa.solver import TrafficMode, solve_schedule


def enumerate_modes(
    layer_path: pathlib.Path | str,
    arch_path: pathlib.Path | str,
    mapspace_path: Optional[pathlib.Path | str] = None,
    w_u: float = 0.1,
    w_tr: float = 1.0,
    w_dl: float = 10.0,
    time_limit: Optional[float] = None,
    mip_gap: Optional[float] = None,
    output_flag: bool = False,
) -> Dict[str, Any]:
    """Solve all TrafficMode variants and return the globally optimal schedule.

    Args:
        layer_path:   Path to layer YAML.
        arch_path:    Path to arch YAML.
        mapspace_path: Optional mapspace YAML; None to skip.
        w_u:          Weight for the utilization sum term.
        w_tr:         Weight for the per-variable traffic product sum.
        w_dl:         Weight for the compute-latency delay term.
        time_limit:   Per-mode Gurobi time limit in seconds.
        mip_gap:      Per-mode Gurobi relative MIP gap tolerance.
        output_flag:  Show Gurobi solver log for each mode.

    Returns:
        Dict with keys:
          "weights"               – {w_u, w_tr, w_dl} used for scoring
          "candidates"            – list of per-mode result dicts
          "best_mode"             – name of the best mode (None if all infeasible)
          "best_comparison_score" – float score of the best candidate
          "best_strategy"         – strategy dict of the best candidate
    """
    candidates: List[Dict[str, Any]] = []

    for mode in TrafficMode:
        result = solve_schedule(
            layer_path=layer_path,
            arch_path=arch_path,
            mapspace_path=mapspace_path,
            time_limit=time_limit,
            mip_gap=mip_gap,
            output_flag=output_flag,
            traffic_mode=mode,
            return_metrics=True,
        )

        score: Optional[float] = None
        if result["has_solution"] and result.get("metrics"):
            score = _comparison_score(result["metrics"], w_u, w_tr, w_dl)

        candidates.append({
            "mode": mode.value,
            "status": result["status"],
            "has_solution": result["has_solution"],
            "gurobi_objective": result.get("objective"),
            "comparison_score": score,
            "metrics": result.get("metrics"),
            "strategy": result.get("strategy"),
        })

    feasible = [c for c in candidates if c["comparison_score"] is not None]
    best = min(feasible, key=lambda c: c["comparison_score"]) if feasible else None

    return {
        "weights": {"w_u": w_u, "w_tr": w_tr, "w_dl": w_dl},
        "candidates": candidates,
        "best_mode": best["mode"] if best else None,
        "best_comparison_score": best["comparison_score"] if best else None,
        "best_strategy": best["strategy"] if best else None,
    }


def _comparison_score(
    metrics: Dict[str, Any],
    w_u: float,
    w_tr: float,
    w_dl: float,
) -> float:
    """Compute the weighted comparison score from a solved mode's metrics.

    Tr_v = Util_v × SpatialCost_v × TemporalTraffic_v  (per variable)

    score = w_u  × Σ_v Util_v
          + w_tr × Σ_v Tr_v
          + w_dl × Dl
    """
    util = metrics["util"]
    sp   = metrics["spatial_cost"]
    tt   = metrics["temporal_traffic"]
    dl   = metrics["delay"]

    util_sum = sum(util.values())

    tr_sum = sum(
        util[name] * sp[name] * tt[name]
        for name in util
    )

    return w_u * util_sum + w_tr * tr_sum + w_dl * dl


__all__ = ["enumerate_modes"]
