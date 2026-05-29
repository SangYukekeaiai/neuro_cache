#!/usr/bin/env python3
"""Combined minimization objective for SNN scheduling."""

import logging
from typing import Dict, Iterable, Sequence

from gurobipy import GRB, Model

from snn_cosa.model.constants import NUM_VARS
from snn_cosa.model.data_size import MEM_NODE
from snn_cosa.model.objectives.compute import build_compute_objective

logger = logging.getLogger(__name__)


def build_objective(
    m: Model,
    buf_util: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
    x: Dict,
    prime_factors: Sequence[Sequence[int]],
    levels: Iterable[int],
    dims: Iterable[int],
    w_compute: float = 1.0,
    w_buffer: float = 1.0,
    w_temporal: float = 1.0,
    w_spatial: float = 1.0,
) -> None:
    """Set the weighted minimization objective on *m*.

    The compute term is intentionally dimension-generic and independent of
    buffer capacity, tensor precision, and communication traffic.
    """
    comp_hat = build_compute_objective(m, x, prime_factors, levels, dims)

    total_objective = w_compute * comp_hat
    total_objective += sum(
        w_buffer * buf_util[(v, MEM_NODE)]
        + w_temporal * temporal_traffic[v]
        + w_spatial * spatial_cost[v]
        for v in range(NUM_VARS)
    )

    m.setObjective(total_objective, GRB.MINIMIZE)
    logger.debug(
        "build_objective: weights compute=%s buffer=%s temporal=%s spatial=%s",
        w_compute, w_buffer, w_temporal, w_spatial,
    )
