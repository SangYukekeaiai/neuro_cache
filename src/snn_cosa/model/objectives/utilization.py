#!/usr/bin/env python3
"""CoSA-style utilization objective terms.

Mirrors CoSA's total_util and data_size design:

  total_util  = Σ_{inner mem levels i} Σ_v  buf_util[(i,v)]
              → REWARD: sum of inner memory utilisation across all inner
                hardware levels (MEM_NODE and MEM_NOC), each restricted to
                factors at positions ≤ i via the Z matrix.
                In snn_cosa's single-inner-level hierarchy both levels
                reduce to the same level-0-only expression, so
                util_hat = 2 × Σ_v node_utilization[(MEM_NODE, v)].

  data_size[v] = Σ_{i < gb_start} (0.8 + 0.04·i) · log2(f) · (x_sp + x_tp) · A[d][v]
              → TRAFFIC COST: inner-level streaming proxy, added to
                traffic_hat with coefficient 0.99.

  gb_utilization[(MEM_NOC, v)]
              → CAPACITY CONSTRAINT only (not in objective).
                Covers levels [0, dram_start) — the full GB tile footprint.
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
) -> Tuple[Dict, LinExpr, Dict]:
    """Build CoSA-style utilization expressions and inner streaming cost.

    Args:
        x: Scheduling variable dict keyed as ``(i,d,n,k)``.
        prob: Parsed SNN layer with prime-factor lists.
        bitwidths: Per-variable bit widths.
        arch: Parsed memory hierarchy.
        gb_start_level: First NoCLevel permutation slot (= 1 in snn_cosa).
        dram_start: First OffChip permutation slot.

    Returns:
        ``(utilization, util_hat, data_size)`` where:
          - ``utilization[(l,v)]`` — log2(bytes) capacity expressions used
            only for capacity constraints (keys: MEM_NOC and MEM_NODE).
          - ``util_hat`` — CoSA total_util reward: sum of inner-level
            buf_util across MEM_NODE and MEM_NOC (level-0 factors only).
          - ``data_size[v]`` — inner-level streaming cost per variable,
            added to traffic_hat with coefficient 0.99.
    """
    pf = prob.prob_factors
    bytes_by_var = _bytes_by_var(bitwidths)

    utilization: Dict = {}
    util_hat = LinExpr()
    data_size: Dict = {}

    # ------------------------------------------------------------------
    # NoCLevel global-buffer utilization — CAPACITY CONSTRAINT only.
    # Sums all factors at levels [0, dram_start): the full GB tile.
    # NOT added to util_hat (CoSA keeps GB tile size out of the reward).
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
        # util_hat intentionally omitted here

    # ------------------------------------------------------------------
    # NodeLevel L1 spad utilization — CAPACITY CONSTRAINT + util_hat.
    # Sums factors at levels [0, gb_start_level) = level 0 only.
    #
    # CoSA's total_util sums buf_util across ALL inner hardware memory
    # levels (MEM_NODE and MEM_NOC), each Z-restricted to inner factors.
    # In snn_cosa's single-inner-level hierarchy both reduce to the same
    # level-0-only expression → util_hat += expr_node twice.
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
            util_hat += expr_node  # MEM_NODE inner contribution
            util_hat += expr_node  # MEM_NOC inner contribution (Z-correct: level 0 only)

    # ------------------------------------------------------------------
    # data_size: inner-level streaming cost (CoSA §data_size).
    # Σ_{i < gb_start} (0.8 + 0.04·i) · log2(f) · (x_sp + x_tp) · A[d][v]
    # Level 0 only in snn_cosa; the 0.04·i gradient is inert here but
    # preserved for structural fidelity with CoSA.
    # Added to traffic_hat with coefficient 0.99 in traffic/total.py.
    # ------------------------------------------------------------------
    for v in range(NUM_VARS):
        if _B[v][l_noc] == 0:
            data_size[v] = 0.0
            continue

        size = LinExpr()
        for i in range(gb_start_level):
            for d, factors in enumerate(pf):
                if _A[d][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    coef = (0.8 + 0.04 * i) * math.log2(factor)
                    if coef == 0.0:
                        continue
                    for k in MAPPING_KINDS:
                        size += coef * x[(i, d, n, k)]
        data_size[v] = size

    logger.debug(
        "build_utilization_terms: U entries=%d  has_local_buffer=%s",
        len(utilization), arch.has_local_buffer,
    )
    return utilization, util_hat, data_size


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
