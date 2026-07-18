#!/usr/bin/env python3
"""Combined CoSA-style minimization objective for SNN scheduling."""

import logging
from typing import Dict, FrozenSet, Iterable, Sequence

from gurobipy import GRB, Model

from snn_cosa.mip_solver.objectives.compute import build_compute_objective
from snn_cosa.mip_solver.objectives.traffic import build_traffic_cost

logger = logging.getLogger(__name__)


def build_objective(
    m: Model,
    data_size: Dict,
    util_hat,
    temporal_traffic: Dict,
    spatial_cost: Dict,
    x: Dict,
    prime_factors: Sequence[Sequence[int]],
    levels: Iterable[int],
    dims: Iterable[int],
    w_compute: float = 10.0,
    w_utilization: float = 0.1,
    w_traffic: float = 1.0,
    zero_vars: FrozenSet[int] = frozenset(),
    gb_only_vars: FrozenSet[int] = frozenset(),
) -> None:
    """Set the weighted minimization objective on *m*.

    The compute term is intentionally dimension-generic and independent of
    buffer capacity, tensor precision, and communication traffic.  The
    utilization term is reward-like, so it enters the minimization objective
    with a negative coefficient.

    zero_vars / gb_only_vars are forwarded to build_traffic_cost to apply
    the per-variant traffic simplification (see traffic/total.py).
    """
    comp_hat    = build_compute_objective(m, x, prime_factors, levels, dims)
    traffic_hat = build_traffic_cost(
        data_size, temporal_traffic, spatial_cost, zero_vars, gb_only_vars
    )

    total_objective = (
        w_compute * comp_hat
        - w_utilization * util_hat
        + w_traffic * traffic_hat
    )

    m.setObjective(total_objective, GRB.MINIMIZE)
    logger.debug(
        "build_objective: weights compute=%s utilization=%s traffic=%s"
        "  zero_vars=%s  gb_only_vars=%s",
        w_compute, w_utilization, w_traffic, zero_vars, gb_only_vars,
    )
