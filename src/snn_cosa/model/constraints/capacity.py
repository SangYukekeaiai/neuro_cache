#!/usr/bin/env python3
"""Capacity constraints for SNN scheduling.

Ensures that the tile footprint for each stored variable fits within the
available Global Buffer / NoCLevel memory capacity:

    utilization[(MEM_NOC, v)] <= log₂(capacity_bytes[MEM_NOC][var_name])

The utilization expression is in log₂(bytes).  NodeLevel and DRAM/OffChip are
excluded from this capacity path.
"""

import logging
import numpy as np
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.arch import MEM_NOC, SNNArch
from snn_cosa.model.constants import NUM_VARS, VAR_NAMES, _B

logger = logging.getLogger(__name__)


def add_capacity_constraints(
    m: Model,
    utilization: Dict,
    arch: SNNArch,
) -> None:
    """Add memory capacity constraints to *m*.

    Args:
        m:        Gurobi Model (variables already added).
        utilization: {(mem_idx, v): LinExpr} in log₂(bytes).
        arch:     Parsed SNN architecture with NoCLevel byte capacities.
    """
    for v in range(NUM_VARS):
        if _B[v][MEM_NOC] == 0:
            continue
        var_name = VAR_NAMES[v]
        cap_log2 = np.log2(arch.mem_entries[MEM_NOC][var_name])
        m.addConstr(
            utilization[(MEM_NOC, v)] <= cap_log2,
            name=f"cap_{arch.mem_name[MEM_NOC]}_{var_name}",
        )

    logger.debug("add_capacity_constraints: NoCLevel capacity constraints added")
