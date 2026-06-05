#!/usr/bin/env python3
"""Constraint C – Pre-defined PE-level spatial split for SNN scheduling.

When arch.node_pe_spatial_split is set, the total spatial extent of each
specified dimension in the PE-parallelism region is pinned to the requested
factor via a linear equality constraint.

The PE-parallelism region differs by architecture mode:

  has_local_buffer = True:
    PE spatial lives at level 0 (intra-node, L1 spad → PEs).
    Equality applied over range [0, gb_start_level).

  has_local_buffer = False:
    PE spatial lives at NoCLevel perm slots (GB → PEs directly).
    Equality applied over range [gb_start_level, dram_start).

V2 validation (F_j divides prob_bound[j]) is performed here before any
Gurobi constraints are added, so infeasible splits are reported immediately.
"""

import logging
import math
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.layer import SNNProb

logger = logging.getLogger(__name__)


def add_pe_spatial_split_constraints(
    m: Model,
    x: Dict,
    prob: SNNProb,
    arch: SNNArch,
    gb_start_level: int,
    dram_start: int,
) -> None:
    """Add Constraint C: pin spatial extent of pre-defined dims to their factor.

    Args:
        m:              Gurobi Model (variables already added).
        x:              X variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists and bounds).
        arch:           Parsed SNN arch (node_pe_spatial_split, has_local_buffer).
        gb_start_level: First NoCLevel permutation slot index.
        dram_start:     First OffChip permutation slot index.

    Raises:
        ValueError: If any split factor does not divide its problem dimension
                    (V2 violation).
    """
    split = arch.node_pe_spatial_split
    assert split is not None, "called without a spatial_split defined"

    # Select the loop range where PE spatial lives.
    if arch.has_local_buffer:
        spatial_range = range(0, gb_start_level)           # level 0
    else:
        spatial_range = range(gb_start_level, dram_start)  # NoCLevel perm slots

    pf = prob.prob_factors

    for dim_name, F_j in split.items():
        j = prob.prob_name_idx_dict[dim_name]

        # V2: F_j must divide the total problem dimension bound.
        if prob.prob_bound[j] % F_j != 0:
            raise ValueError(
                f"pe.spatial_split['{dim_name}']={F_j} does not divide "
                f"prob_bound['{dim_name}']={prob.prob_bound[j]} (V2 violation)"
            )

        log_F = math.log2(F_j)
        spatial_sum = sum(
            math.log2(pf[j][n]) * x[(i, j, n, 0)]
            for i in spatial_range
            for n in range(len(pf[j]))
            if math.log2(pf[j][n]) > 0.0
        )

        m.addConstr(spatial_sum == log_F, name=f"pe_split_{dim_name}")
        logger.debug(
            "Constraint C: dim=%s  F_j=%d  log_F=%.4f  range=%s",
            dim_name, F_j, log_F,
            "level-0" if arch.has_local_buffer else "NoCLevel-perm",
        )

    logger.debug(
        "add_pe_spatial_split_constraints: %d equality constraints added",
        len(split),
    )
