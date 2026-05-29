#!/usr/bin/env python3
"""Capacity constraints for SNN scheduling.

Ensures that the tile footprint for each variable fits within the available
memory at the Global Buffer / NoC level:

    buf_util[(v, MEM_NOC)] <= log₂(capacity_bytes[MEM_NOC][var_name])

buf_util is in log₂(bytes) (from data_size.compute_log_sizes).
arch.mem_entries[MEM_NOC][var_name] is the global-buffer capacity in bytes.

Only NoCLevel / Global Buffer is constrained.  PE-register, node
local-buffer, and DRAM capacities are metadata only in the current model.
"""

import logging
import numpy as np
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.arch import SNNArch
from snn_cosa.model.constants import NUM_VARS, VAR_NAMES
from snn_cosa.model.data_size import MEM_NOC

logger = logging.getLogger(__name__)


def add_capacity_constraints(
    m: Model,
    buf_util: Dict,
    arch: SNNArch,
) -> None:
    """Add memory capacity constraints to *m*.

    Args:
        m:        Gurobi Model (variables already added).
        buf_util: {(v, mem_idx): LinExpr} from compute_log_sizes — log₂(bytes).
        arch:     Parsed SNN architecture with NoCLevel byte capacities.
    """
    for v in range(NUM_VARS):
        var_name = VAR_NAMES[v]
        cap_log2 = np.log2(arch.mem_entries[MEM_NOC][var_name])
        m.addConstr(
            buf_util[(v, MEM_NOC)] <= cap_log2,
            name=f"cap_gb_{var_name}",
        )

    logger.debug("add_capacity_constraints: NoCLevel capacity constraints added")
