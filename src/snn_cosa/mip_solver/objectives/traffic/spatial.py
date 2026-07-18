#!/usr/bin/env python3
"""Spatial traffic objective expressions for SNN scheduling.

Spatial tiling at NoCLevel distributes work across NodeLevel PEs.
Only the NoCLevel perm region carries spatial assignments (S[1] = 1024);
NodeLevel and OffChip are constrained to S = 1 by constraints_spatial.py.

For each variable v, the spatial traffic cost is:

    spatial_cost[v] = Σᵢ∈NoCLevel_perm  Σⱼ  Σₙ  log₂(f_j[n]) · x[(i,j,n,0)] · A[j][v]

Load/store access multiplicity is modeled only in temporal.py through
TRAFFIC_MULT.  The spatial term only captures NoC-level spatial
partition/fanout effects.

The A[j][v] mask ensures only dimensions that contribute to variable v's
buffer size are counted:

    weight  → {KH, KW, CIN, COUT}   (A[HO/WO/T][weight] = 0)
    psum    → {COUT, HO, WO, T}      (A[KH/KW/CIN][psum]  = 0)
    vmem    → {COUT, HO, WO}         (A[KH/KW/CIN/T][vmem] = 0)

This means HO/WO spatial tiling adds no penalty to weight's spatial cost,
and T spatial tiling adds no penalty to vmem's spatial cost.
"""

import logging
import numpy as np
from typing import Dict

from snn_cosa.parsers.layer import SNNProb
from snn_cosa.mip_solver.constants import NUM_VARS, _A

logger = logging.getLogger(__name__)


def compute_spatial_traffic(
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
) -> Dict:
    """Compute log₂-scale A-weighted spatial traffic expressions.

    No Gurobi constraints are added here.

    Args:
        x:              X decision-variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        gb_start_level: First NoCLevel perm slot.
        dram_start:     First OffChip perm slot (= last NoCLevel perm slot + 1).

    Returns:
        spatial_cost – {v: LinExpr}  log₂(elements) spatial traffic per variable.
                       Only NoCLevel perm slots [gb_start_level, dram_start)
                       are included; OffChip spatial is forbidden (S[2]=1).
    """
    pf = prob.prob_factors
    noc_perm = range(gb_start_level, dram_start)

    spatial_cost: Dict = {}
    for v in range(NUM_VARS):
        size = 0.0
        for i in noc_perm:
            for j, f_j in enumerate(pf):
                if _A[j][v] == 0:
                    continue            # dim j irrelevant to variable v
                for n in range(len(f_j)):
                    lf = np.log2(f_j[n])
                    if lf > 0.0:
                        size += lf * x[(i, j, n, 0)]   # k=0 → spatial
        spatial_cost[v] = size

    logger.debug(
        "compute_spatial_traffic: vars=%d  noc_perm_slots=%d",
        len(spatial_cost), len(noc_perm),
    )
    return spatial_cost
