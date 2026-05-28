#!/usr/bin/env python3
"""Step 9 – Objective function for SNN scheduling.

Total cost = Σᵥ (NodeLevel data size  +  temporal traffic  +  spatial traffic)

  buf_util[(v, MEM_NODE)]   log₂(bytes) tile at NodeLevel — minimising this
                             reduces the inner-loop working set, which drives
                             NodeLevel SRAM reads/writes per outer iteration.
  temporal_traffic[v]       log₂(element) traffic across NoCLevel + OffChip
                             perm boundaries (bilinear for weight/psum,
                             linear for vmem).
  spatial_cost[v]           log₂(element) NoCLevel spatial fanout cost,
                             A-weighted per variable.

All three are in comparable log₂ units, so the sum approximates total
log₂(data movement) across the memory hierarchy.
"""

import logging
from typing import Dict

from gurobipy import Model, GRB

from snn_cosa.model.constants import NUM_VARS
from snn_cosa.model.data_size import MEM_NODE

logger = logging.getLogger(__name__)


def build_objective(
    m: Model,
    buf_util: Dict,
    temporal_traffic: Dict,
    spatial_cost: Dict,
) -> None:
    """Set the minimisation objective on *m*.

    Args:
        m:                Gurobi Model.
        buf_util:         {(v, mem_idx): LinExpr} from compute_log_sizes.
        temporal_traffic: {v: Expr} from compute_temporal_traffic.
        spatial_cost:     {v: LinExpr} from compute_spatial_traffic.
    """
    obj = sum(
        buf_util[(v, MEM_NODE)] + temporal_traffic[v] + spatial_cost[v]
        for v in range(NUM_VARS)
    )
    m.setObjective(obj, GRB.MINIMIZE)
    logger.debug("build_objective: objective set for %d variables", NUM_VARS)
