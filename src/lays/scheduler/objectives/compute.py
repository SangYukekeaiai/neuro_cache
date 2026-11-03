#!/usr/bin/env python3
"""Compute-driven objective term for SNN scheduling.

This is the CoSA-style per-PE temporal-iteration surrogate:

    comp_hat = sum_i sum_j sum_n ln(prime_factors[j][n]) * X[(i,j,n,TEMPORAL)]

Only temporally mapped factors contribute.  Spatially mapped factors are
excluded, so minimizing this term favors spatial mapping where constraints
allow it.
"""

import logging
import math
from typing import Dict, Iterable, Sequence

from gurobipy import LinExpr, Model

logger = logging.getLogger(__name__)

TEMPORAL = 1


def build_compute_objective(
    model: Model,
    X: Dict,
    prime_factors: Sequence[Sequence[int]],
    levels: Iterable[int],
    dims: Iterable[int],
) -> LinExpr:
    """Build the temporal compute-iteration objective expression.

    Args:
        model: Gurobi model, unused here but kept for a uniform objective API.
        X: Scheduling variable dict.  This codebase keys X as ``(i,j,n,k)``.
        prime_factors: ``prime_factors[j][n]`` for each problem dimension.
        levels: Mapping/memory levels ``i`` to include.
        dims: Problem dimensions ``j`` to include.

    Returns:
        Gurobi linear expression for ``comp_hat`` in natural-log units.
    """
    del model
    comp_hat = LinExpr()

    for i in levels:
        for j in dims:
            for n, factor in enumerate(prime_factors[j]):
                log_factor = math.log(factor)
                if log_factor == 0.0:
                    continue
                comp_hat += log_factor * X[(i, j, n, TEMPORAL)]

    logger.debug("build_compute_objective: expression built")
    return comp_hat
