#!/usr/bin/env python3
"""Total traffic-cost expression for SNN scheduling.

Mirrors CoSA's total_traffic structure:

    traffic_hat[v] = 0.99 × data_size[v]
                   + 0.99 × spatial_cost[v]
                   +        temporal_traffic[v]

data_size and spatial_cost carry coefficient 0.99 (heuristic proxies for
inner-level streaming and NoC broadcast overhead).  temporal_traffic is the
primary boundary-crossing cost and carries full weight 1.0.

gb_utilization is intentionally excluded — it serves only as a capacity
constraint (see utilization.py) and must not appear here.

zero_vars / gb_only_vars
------------------------
  zero_vars    – TR[v] = 0.  All three pieces for v are dropped.
  gb_only_vars – temporal_traffic[v] already restricted to GB perm slots
                 by compute_temporal_traffic; no special handling needed.
"""

import logging
from typing import Dict, FrozenSet

from snn_cosa.mip_solver.constants import NUM_VARS

logger = logging.getLogger(__name__)


def build_traffic_cost(
    data_size: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
    zero_vars: FrozenSet[int] = frozenset(),
    gb_only_vars: FrozenSet[int] = frozenset(),
):
    """Build the unweighted total traffic-cost expression.

    Args:
        data_size:        Per-variable inner-level streaming cost expressions
                          (from build_utilization_terms).
        temporal_traffic: Per-variable temporal traffic expressions.
        spatial_cost:     Per-variable NoC spatial traffic expressions.
        zero_vars:        Variable indices with TR[v] = 0; all pieces omitted.
        gb_only_vars:     Variable indices with Td[v] = 1; included normally
                          (temporal_traffic already carries the GB-only value).

    Returns:
        Total traffic cost expression to minimize.
    """
    traffic_hat = 0.0
    for v in range(NUM_VARS):
        if v in zero_vars:
            continue
        traffic_hat += 0.99 * data_size[v]
        traffic_hat += 0.99 * spatial_cost[v]
        traffic_hat += temporal_traffic[v]

    logger.debug(
        "build_traffic_cost: zero_vars=%s  gb_only_vars=%s",
        zero_vars, gb_only_vars,
    )
    return traffic_hat
