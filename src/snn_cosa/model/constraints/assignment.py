#!/usr/bin/env python3
"""Step 5c – Structural assignment constraints for SNN scheduling.

Adds four constraint classes to the Gurobi model (no variables created here):

  1. Spatial-temporal sum <= 1  per (i, j, n)
     At any loop level a factor can be spatial OR temporal, not both.

  2. Column sum == 1  per (j, n)
     Every prime factor is assigned to exactly one loop level.

  3. Row sum <= 1  per permutation slot (NoCLevel and OffChip regions)
     At most one factor occupies each ordering slot.

  4. Unified y monotonicity across both perm regions
     y[v,i] >= y[v,i-1]  and  y[v,i] >= row_sum(v,i)  for all i
     in range [gb_start, dram_start + perm_levels).
     Initialised at gb_start: y[v, gb_start] == row_sum(v, gb_start).

     y is lower-bounded only (no upper-bound constraint is added).
     Under a minimising traffic objective Gurobi will push y to its
     minimum feasible value, making it tight at optimality.  Spatial
     legality constraints (fanout limits, eligible dims) live in a
     separate module: constraints_spatial.py.
"""

import logging
from typing import Dict, Tuple

from gurobipy import Model

from snn_cosa.parsers.layer import SNNProb
from snn_cosa.model.constants import NUM_VARS, _A
from snn_cosa.model.schedule import SNN_GB_START_LEVEL

logger = logging.getLogger(__name__)


def add_assignment_constraints(
    m: Model,
    x: Dict,
    y: Dict,
    prob: SNNProb,
    perm_levels: int,
    total_levels: int,
    gb_start_level: int = SNN_GB_START_LEVEL,
    dram_start: int = None,
) -> Tuple[Dict, Dict]:
    """Add all structural X and y constraints to *m*.

    Args:
        m:              Gurobi Model (variables already added).
        x:              X variable dict from create_schedule_vars.
        y:              Unified y variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        perm_levels:    Slots per permutation boundary.
        total_levels:   1 + 2 * perm_levels.
        gb_start_level: First NoCLevel perm slot (default 1).
        dram_start:     First OffChip perm slot (default gb_start + perm_levels).

    Returns:
        s_gb   – {(v,i): row_sum_expr} for NoCLevel perm slots.
        s_dram – {(v,i): row_sum_expr} for OffChip perm slots.
        Consumed by traffic computation steps.
    """
    if dram_start is None:
        dram_start = gb_start_level + perm_levels

    pf = prob.prob_factors

    # ------------------------------------------------------------------
    # 1. Spatial-temporal sum <= 1  per (i, j, n)
    # ------------------------------------------------------------------
    for i in range(total_levels):
        for j, f_j in enumerate(pf):
            for n in range(len(f_j)):
                st = sum(x[(i, j, n, k)] for k in range(2))
                m.addConstr(st <= 1, name=f"st_{i}_{j}_{n}")

    # ------------------------------------------------------------------
    # 2. Column sum == 1  per (j, n)
    # ------------------------------------------------------------------
    for j, f_j in enumerate(pf):
        for n in range(len(f_j)):
            col = sum(
                x[(i, j, n, k)]
                for i in range(total_levels)
                for k in range(2)
            )
            m.addConstr(col == 1, name=f"col_{j}_{n}")

    # ------------------------------------------------------------------
    # 3. Row sum <= 1  per permutation slot
    # ------------------------------------------------------------------
    for i in range(gb_start_level, dram_start):              # NoCLevel slots
        row = sum(
            x[(i, j, n, k)]
            for j, f_j in enumerate(pf)
            for n in range(len(f_j))
            for k in range(2)
        )
        m.addConstr(row <= 1, name=f"row_gb_{i}")

    for i in range(dram_start, dram_start + perm_levels):    # OffChip slots
        row = sum(
            x[(i, j, n, k)]
            for j, f_j in enumerate(pf)
            for n in range(len(f_j))
            for k in range(2)
        )
        m.addConstr(row <= 1, name=f"row_dram_{i}")

    # ------------------------------------------------------------------
    # 4. Unified y monotonicity across NoCLevel + OffChip perm regions
    #    Single chain: i runs from gb_start to dram_start + perm_levels - 1
    # ------------------------------------------------------------------
    s_gb:   Dict = {}
    s_dram: Dict = {}

    for v in range(NUM_VARS):
        for i in range(gb_start_level, dram_start + perm_levels):
            row_sum = sum(
                x[(i, j, n, 1)] * _A[j][v]
                for j, f_j in enumerate(pf)
                for n in range(len(f_j))
            )

            # Store in the appropriate output dict
            if i < dram_start:
                s_gb[(v, i)] = row_sum
            else:
                s_dram[(v, i)] = row_sum

            if i == gb_start_level:
                m.addConstr(y[(v, i)] == row_sum,       name=f"y_init_{v}")
            else:
                m.addConstr(y[(v, i)] >= y[(v, i - 1)], name=f"y_mono_{v}_{i}")
                m.addConstr(y[(v, i)] >= row_sum,        name=f"y_row_{v}_{i}")

    logger.debug("add_assignment_constraints: all 4 constraint classes added")

    return s_gb, s_dram
