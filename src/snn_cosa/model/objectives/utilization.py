#!/usr/bin/env python3
"""CoSA-style Global Buffer utilization objective terms.

For every valid Global Buffer storage pair ``B[v][NoCLevel] == 1`` this builds

    U[l,v] = log2(bytes[v])
             + sum_{i below l, d, n, k}
               log2(prime_factor[d][n]) * A[d][v] * X[i,d,n,k]

Both spatial and temporal factors contribute to the resident tile footprint.
NodeLevel and OffChip/DRAM are intentionally excluded from ``util_hat``.
"""

import logging
import math
from typing import Dict, Tuple

from gurobipy import LinExpr, Model

from snn_cosa.model.constants import NUM_VARS, VAR_NAMES, _A, _B
from snn_cosa.parsers.arch import MEM_NODE, MEM_NOC, SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.parsers.layer import SNNProb

logger = logging.getLogger(__name__)

SPATIAL = 0
TEMPORAL = 1
MAPPING_KINDS: Tuple[int, int] = (SPATIAL, TEMPORAL)


def build_utilization_terms(
    x: Dict,
    prob: SNNProb,
    bitwidths: SNNBitwidths,
    arch: SNNArch,
    gb_start_level: int,
    dram_start: int,
) -> Tuple[Dict, LinExpr]:
    """Build CoSA-style Global Buffer utilization expressions.

    Args:
        x: Scheduling variable dict keyed as ``(i,d,n,k)``.
        prob: Parsed SNN layer with prime-factor lists.
        bitwidths: Per-variable bit widths.
        arch: Parsed memory hierarchy.
        gb_start_level: First NoCLevel permutation slot.
        dram_start: First OffChip permutation slot.

    Returns:
        ``(U, util_hat)`` where ``U[(l,v)]`` is log2(bytes) for storage
        level ``l == MEM_NOC`` and variable ``v``, and ``util_hat`` is the sum
        over all valid Global Buffer storage pairs.
    """
    pf = prob.prob_factors
    bytes_by_var = _bytes_by_var(bitwidths)

    utilization: Dict = {}
    util_hat = LinExpr()

    # ------------------------------------------------------------------
    # NoCLevel global-buffer utilization (enters both objective and
    # capacity constraint).  Sums all factors at levels [0, dram_start).
    # ------------------------------------------------------------------
    l_noc = MEM_NOC
    upper = _loop_upper_for_global_buffer(dram_start)
    for v in range(NUM_VARS):
        if _B[v][l_noc] == 0:
            continue

        expr = LinExpr()
        expr += math.log2(bytes_by_var[v])

        for i in range(upper):
            for d, factors in enumerate(pf):
                if _A[d][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    coef = math.log2(factor)
                    if coef == 0.0:
                        continue
                    for k in MAPPING_KINDS:
                        expr += coef * x[(i, d, n, k)]

        utilization[(l_noc, v)] = expr
        util_hat += expr

    # ------------------------------------------------------------------
    # NodeLevel L1 spad utilization (capacity constraint only — not in
    # objective).  Only added when local_buffer is present.
    # Sums factors at levels [0, gb_start_level) = level 0 only.
    # ------------------------------------------------------------------
    if arch.has_local_buffer:
        l_node = MEM_NODE
        for v in range(NUM_VARS):
            if _B[v][l_node] == 0:
                continue

            expr_node = LinExpr()
            expr_node += math.log2(bytes_by_var[v])

            for i in range(gb_start_level):
                for d, factors in enumerate(pf):
                    if _A[d][v] == 0:
                        continue
                    for n, factor in enumerate(factors):
                        coef = math.log2(factor)
                        if coef == 0.0:
                            continue
                        for k in MAPPING_KINDS:
                            expr_node += coef * x[(i, d, n, k)]

            utilization[(l_node, v)] = expr_node

    logger.debug(
        "build_utilization_terms: U entries=%d  has_local_buffer=%s",
        len(utilization), arch.has_local_buffer,
    )
    return utilization, util_hat


def add_utilization_capacity_constraints(
    m: Model,
    utilization: Dict,
    arch: SNNArch,
) -> None:
    """Constrain each Global Buffer ``U[l,v]`` against byte capacity."""
    for (l, v), expr in utilization.items():
        var_name = VAR_NAMES[v]
        capacity = arch.mem_entries[l][var_name]
        m.addConstr(
            expr <= math.log2(capacity),
            name=f"cap_{arch.mem_name[l]}_{var_name}",
        )

    logger.debug(
        "add_utilization_capacity_constraints: constraints=%d",
        len(utilization),
    )


def _bytes_by_var(bitwidths: SNNBitwidths) -> Tuple[float, float, float]:
    return (
        bitwidths.bw_weight / 8.0,
        bitwidths.bw_psum / 8.0,
        bitwidths.bw_vmem / 8.0,
    )


def _loop_upper_for_global_buffer(dram_start: int) -> int:
    return dram_start
