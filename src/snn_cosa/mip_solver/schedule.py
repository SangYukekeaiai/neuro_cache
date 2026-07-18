#!/usr/bin/env python3
"""Step 5b – Gurobi decision variable creation for SNN scheduling.

Two variable families are created (no constraints here):

X[(i, j, n, k)]  –  Binary.
    i : loop level  (0 … total_levels-1)
    j : dimension   (0=KH … 6=T)
    n : prime-factor index within dimension j
    k : 0 = spatial, 1 = temporal

y[(v, i)]  –  Integer {0, 1}, unified across both perm regions.
    v : variable index (0=weight, 1=psum, 2=vmem)
    i : permutation loop level spanning NoCLevel AND OffChip slots

    y[v,i] is a lower-bound liveness indicator: the constraints guarantee
    y[v,i] >= 1 whenever any related temporal dimension is assigned at
    level i or any inner level (i' <= i).  Under a minimising objective
    y is tight at optimality; without one it may be spuriously 1.

    A single unified y is required because OffChip-tiled dimensions
    make v "live" at the NoCLevel boundary too (y is monotone
    inner→outer, so liveness propagates outward across both regions).
    Splitting into y_gb / y_dram would break this propagation.

Loop-level layout
------------------
  level 0                              NodeLevel  (inner, no permutation)
  levels gb_start … dram_start-1      NoCLevel   permutation slots
  levels dram_start … dram_start+p-1  OffChip    permutation slots

  gb_start   = 1
  dram_start = 1 + perm_levels
  total_levels = 1 + 2 * perm_levels
"""

import logging
from typing import Dict, Tuple

from gurobipy import GRB, Model

from snn_cosa.parsers.layer import SNNProb
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.mip_solver.constants import NUM_VARS

logger = logging.getLogger(__name__)

SNN_GB_START_LEVEL: int = 1


def create_schedule_vars(
    m: Model,
    prob: SNNProb,
    arch: SNNArch,
    gb_start_level: int = SNN_GB_START_LEVEL,
) -> Tuple[Dict, Dict, int, int, int]:
    """Add X and y Gurobi variables to model *m*.

    No constraints are added here.

    Args:
        m:               Gurobi Model.
        prob:            Parsed SNN layer (prime-factor lists).
        arch:            Parsed SNN architecture (mem_levels).
        gb_start_level:  First NoCLevel permutation slot (default 1).

    Returns:
        x             – {(i,j,n,k): BinaryVar}
        y             – {(v,i): IntVar} unified over both perm regions
        perm_levels   – prime-factor count (= slots per perm boundary)
        total_levels  – 1 + 2 * perm_levels
        dram_start    – first OffChip permutation slot index
    """
    prime_factors = prob.prob_factors
    perm_levels: int = sum(len(f_j) for f_j in prime_factors)

    dram_start: int   = gb_start_level + perm_levels
    total_levels: int = 1 + 2 * perm_levels

    logger.debug(
        "schedule_vars: perm=%d  total=%d  gb_start=%d  dram_start=%d",
        perm_levels, total_levels, gb_start_level, dram_start,
    )

    # ------------------------------------------------------------------
    # X[(i, j, n, k)] – binary, spans all loop levels
    # ------------------------------------------------------------------
    x: Dict = {}
    for i in range(total_levels):
        for j, f_j in enumerate(prime_factors):
            for n in range(len(f_j)):
                for k in range(2):
                    x[(i, j, n, k)] = m.addVar(
                        vtype=GRB.BINARY, name=f"X({i},{j},{n},{k})"
                    )

    # ------------------------------------------------------------------
    # y[(v, i)] – unified reuse tracker spanning NoCLevel + OffChip slots
    #
    # Defined over the full combined range so that monotonicity constraints
    # in constraints.py can propagate liveness continuously from NoCLevel
    # slots through to OffChip slots without a break.
    # ------------------------------------------------------------------
    y: Dict = {}
    for v in range(NUM_VARS):
        for i in range(gb_start_level, dram_start + perm_levels):
            y[(v, i)] = m.addVar(
                lb=0, ub=1, vtype=GRB.INTEGER, name=f"y({v},{i})"
            )

    m.update()

    logger.debug(
        "created: |X|=%d  |y|=%d", len(x), len(y),
    )

    return x, y, perm_levels, total_levels, dram_start
