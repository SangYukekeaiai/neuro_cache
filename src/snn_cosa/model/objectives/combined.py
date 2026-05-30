#!/usr/bin/env python3
"""Combined CoSA-style minimization objective for SNN scheduling."""

import logging
from typing import Dict, Iterable, Sequence

from gurobipy import GRB, Model

from snn_cosa.model.objectives.compute import build_compute_objective
from snn_cosa.model.objectives.traffic import build_traffic_cost

logger = logging.getLogger(__name__)


def build_objective(
    m: Model,
    utilization: Dict,
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
) -> None:
    """Set the weighted minimization objective on *m*.

    The compute term is intentionally dimension-generic and independent of
    buffer capacity, tensor precision, and communication traffic.  The
    utilization term is reward-like, so it enters the minimization objective
    with a negative coefficient.
    """
    comp_hat = build_compute_objective(m, x, prime_factors, levels, dims)
    traffic_hat = build_traffic_cost(utilization, temporal_traffic, spatial_cost)

    total_objective = (
        w_compute * comp_hat
        # - w_utilization * util_hat
        + w_traffic * traffic_hat
    )

    m.setObjective(total_objective, GRB.MINIMIZE)
    logger.debug(
        "build_objective: weights compute=%s utilization=%s traffic=%s",
        w_compute,
        w_utilization,
        w_traffic,
    )
