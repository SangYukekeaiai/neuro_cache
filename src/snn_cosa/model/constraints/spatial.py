#!/usr/bin/env python3
"""Spatial legality constraints for SNN scheduling.

One constraint class (no variables created here):

  Per-region spatial fanout
     The combined spatial tile within each loop-level region must not
     exceed the architectural fanout cap S[region]:

       NodeLevel inner  levels [0, gb_start)            S[0] = 1
       NoCLevel  perm   levels [gb_start, dram_start)   S[1] = fanout
       OffChip   perm   levels [dram_start, dram+P)     S[2] = 1

     For S == 1 (no fanout), individual x[(i,j,n,0)] == 0 constraints
     are added instead of the log2-sum form; this directly fixes the
     loophole where OffChip-spatial factors escape both traffic and
     capacity accounting, and produces tighter LP relaxations.

     For S > 1, a single log2-sum constraint covers the whole region:
       sum_{i in region, j, n} log2(f_j[n]) * x[(i,j,n,0)] <= log2(S)
"""

import logging
import numpy as np
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.layer import SNNProb
from snn_cosa.parsers.arch import SNNArch

logger = logging.getLogger(__name__)


def add_spatial_constraints(
    m: Model,
    x: Dict,
    prob: SNNProb,
    arch: SNNArch,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """Add spatial fanout constraints to *m*.

    Args:
        m:              Gurobi Model (variables already added).
        x:              X variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        arch:           Parsed SNN architecture (spatial fanout S).
        gb_start_level: First NoCLevel perm slot (default 1).
        dram_start:     First OffChip perm slot.
        perm_levels:    Slots per permutation boundary.
    """
    pf = prob.prob_factors

    # ------------------------------------------------------------------
    # Per-region spatial fanout
    #
    #    Regions and their arch.S value:
    #      NodeLevel inner : [0, gb_start)             S[0] (= 1 for SNN)
    #      NoCLevel perm   : [gb_start, dram_start)    S[1] (= 1024 for SNN)
    #      OffChip perm    : [dram_start, dram+P)      S[2] (= 1 for SNN)
    #
    #    S == 1 → no spatial allowed; prohibit directly via x==0 so the
    #             constraint is non-trivially tight even for factor == 1.
    #    S >  1 → single log2-sum constraint for the whole region.
    # ------------------------------------------------------------------
    regions = [
        (range(0,              gb_start_level),          arch.S[0], "node"),
        (range(gb_start_level, dram_start),               arch.S[1], "noc"),
        (range(dram_start,     dram_start + perm_levels), arch.S[2], "dram"),
    ]

    for loop_range, S_val, tag in regions:
        if S_val <= 1:
            for i in loop_range:
                for j, f_j in enumerate(pf):
                    for n in range(len(f_j)):
                        m.addConstr(
                            x[(i, j, n, 0)] == 0,
                            name=f"no_spatial_{tag}_{i}_{j}_{n}",
                        )
        else:
            spatial_tile = sum(
                np.log2(f_j[n]) * x[(i, j, n, 0)]
                for i in loop_range
                for j, f_j in enumerate(pf)
                for n in range(len(f_j))
            )
            m.addConstr(
                spatial_tile <= np.log2(S_val),
                name=f"spatial_fanout_{tag}",
            )

    logger.debug("add_spatial_constraints: all spatial constraints added")
