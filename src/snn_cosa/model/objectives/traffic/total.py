#!/usr/bin/env python3
"""Total traffic-cost expression for SNN scheduling.

The traffic objective includes three pieces per variable:

    GB data size + temporal traffic + spatial NoC traffic

The GB data-size term is the same log-footprint expression used by the
Global Buffer utilization/capacity model.

zero_vars / gb_only_vars
------------------------
Variants modify which terms appear in the sum:

  zero_vars    – TR[v] = 0 (GB-side pattern).  All three pieces for v are
                 dropped from traffic_hat.  Capacity constraints on v are
                 unaffected (utilization is not passed to this function).

  gb_only_vars – Td[v] = 1 (DRAM-side pattern).  temporal_traffic[v] was
                 already restricted to GB perm slots by compute_temporal_traffic;
                 this function simply includes it as-is alongside the normal
                 gb_utilization and spatial_cost terms.  No special handling
                 needed here beyond skipping the zero_vars check.
"""

import logging
from typing import Dict, FrozenSet

from snn_cosa.model.constants import NUM_VARS
from snn_cosa.parsers.arch import MEM_NOC

logger = logging.getLogger(__name__)


def build_traffic_cost(
    gb_utilization: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
    zero_vars: FrozenSet[int] = frozenset(),
    gb_only_vars: FrozenSet[int] = frozenset(),
):
    """Build the unweighted total traffic-cost expression.

    Args:
        gb_utilization: Per-variable GB data-size expressions keyed as
            ``(MEM_NOC, v)``.
        temporal_traffic: Per-variable temporal traffic expressions.
            For v in gb_only_vars this should already be GB-perm-only
            (produced by compute_temporal_traffic with the same gb_only_vars).
        spatial_cost: Per-variable NoC spatial traffic expressions.
        zero_vars:    Variable indices with TR[v] = 0; all three pieces are
                      omitted from the returned expression.
        gb_only_vars: Variable indices with Td[v] = 1; included normally
                      (temporal_traffic already carries the GB-only value).

    Returns:
        Total traffic cost expression to minimize.
    """
    traffic_hat = 0.0
    for v in range(NUM_VARS):
        if v in zero_vars:
            continue
        traffic_hat += gb_utilization[(MEM_NOC, v)]
        traffic_hat += temporal_traffic[v] + spatial_cost[v]

    logger.debug(
        "build_traffic_cost: zero_vars=%s  gb_only_vars=%s",
        zero_vars, gb_only_vars,
    )
    return traffic_hat
