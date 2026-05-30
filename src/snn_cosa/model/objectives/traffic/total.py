#!/usr/bin/env python3
"""Total traffic-cost expression for SNN scheduling.

The traffic objective includes three pieces per variable:

    GB data size + temporal traffic + spatial NoC traffic

The GB data-size term is the same log-footprint expression used by the
Global Buffer utilization/capacity model.
"""

import logging
from typing import Dict

from snn_cosa.model.constants import NUM_VARS
from snn_cosa.parsers.arch import MEM_NOC

logger = logging.getLogger(__name__)


def build_traffic_cost(
    gb_utilization: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
):
    """Build the unweighted total traffic-cost expression.

    Args:
        gb_utilization: Per-variable GB data-size expressions keyed as
            ``(MEM_NOC, v)``.
        temporal_traffic: Per-variable temporal traffic expressions.
        spatial_cost: Per-variable NoC spatial traffic expressions.

    Returns:
        Total traffic cost expression to minimize.
    """
    traffic_hat = 0.0
    for v in range(NUM_VARS):
        traffic_hat += gb_utilization[(MEM_NOC, v)]
        traffic_hat += temporal_traffic[v] + spatial_cost[v]

    logger.debug("build_traffic_cost: total traffic expression built")
    return traffic_hat
