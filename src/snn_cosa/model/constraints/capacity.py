#!/usr/bin/env python3
"""Capacity constraints for SNN scheduling.

Ensures that the tile footprint for each variable fits within the available
memory at each level:

    buf_util[(v, mem_idx)] <= log₂(capacity_bytes[mem_idx])

buf_util is in log₂(bytes) (from data_size.compute_log_sizes).
arch.mem_entries[mem_idx] is the capacity in bytes per instance.

Only NodeLevel (MEM_NODE) and NoCLevel (MEM_NOC) are constrained;
OffChip is unbounded and skipped.
"""

import logging
import numpy as np
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.arch import SNNArch
from snn_cosa.model.constants import NUM_VARS
from snn_cosa.model.data_size import MEM_NODE, MEM_NOC

logger = logging.getLogger(__name__)

_CONSTRAINED_LEVELS = (MEM_NODE, MEM_NOC)
_LEVEL_NAMES = {MEM_NODE: "node", MEM_NOC: "noc"}


def add_capacity_constraints(
    m: Model,
    buf_util: Dict,
    arch: SNNArch,
) -> None:
    """Add memory capacity constraints to *m*.

    Args:
        m:        Gurobi Model (variables already added).
        buf_util: {(v, mem_idx): LinExpr} from compute_log_sizes — log₂(bytes).
        arch:     Parsed SNN architecture; arch.mem_entries[idx] in bytes.
    """
    for mem_idx in _CONSTRAINED_LEVELS:
        cap_log2 = np.log2(arch.mem_entries[mem_idx])
        tag = _LEVEL_NAMES[mem_idx]
        for v in range(NUM_VARS):
            m.addConstr(
                buf_util[(v, mem_idx)] <= cap_log2,
                name=f"cap_{tag}_v{v}",
            )

    logger.debug("add_capacity_constraints: capacity constraints added")
