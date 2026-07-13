#!/usr/bin/env python3
"""Constraint C – Pre-defined PE-level spatial split for SNN scheduling.

When arch.node_pe_spatial_split is set, the total spatial extent of each
specified dimension is pinned to the requested factor via a linear equality
constraint over range [0, gb_start_level) -- PE-parallel spatial fanout
always lives at NodeLevel (level 0), regardless of whether a local buffer
is present. (Previously this branched on arch.has_local_buffer, routing
spatial fanout to NoCLevel perm slots instead when no local buffer was
configured; removed -- that routing directly conflicts with
add_no_noc_level_constraints for single_node archs, and level 0 is always
the right place for genuine PE-parallel fanout regardless of buffering.)

arch.node_pe_spatial_split is not a standalone config key -- it's derived
by parsers/arch.py from arch.node_dim_capacity's {spatial: N} entries (e.g.
COUT: {spatial: 128}), so that one arch YAML block describes the complete
NodeLevel dimension set instead of splitting it across pe.spatial_split and
node_dim_capacity.

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
) -> None:
    """Add Constraint C: pin spatial extent of pre-defined dims to their factor.

    Args:
        m:              Gurobi Model (variables already added).
        x:              X variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists and bounds).
        arch:           Parsed SNN arch (node_pe_spatial_split).
        gb_start_level: First NoCLevel permutation slot index -- PE-parallel
                        spatial fanout is pinned over [0, gb_start_level),
                        i.e. NodeLevel (level 0).

    Raises:
        ValueError: If any split factor does not divide its problem dimension
                    (V2 violation).
    """
    split = arch.node_pe_spatial_split
    assert split is not None, "called without a spatial_split defined"

    spatial_range = range(0, gb_start_level)  # NodeLevel (level 0)
    pf = prob.prob_factors

    for dim_name, F_j in split.items():
        j = prob.prob_name_idx_dict[dim_name]

        # V2: F_j must divide the total problem dimension bound.
        if prob.prob_bound[j] % F_j != 0:
            raise ValueError(
                f"node_dim_capacity['{dim_name}']['spatial']={F_j} does not "
                f"divide prob_bound['{dim_name}']={prob.prob_bound[j]} "
                f"(V2 violation)"
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
            "Constraint C: dim=%s  F_j=%d  log_F=%.4f  range=level-0",
            dim_name, F_j, log_F,
        )

    logger.debug(
        "add_pe_spatial_split_constraints: %d equality constraints added",
        len(split),
    )
