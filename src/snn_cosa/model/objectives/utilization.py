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

    Returns:
        ``(utilization, util_hat, data_size)`` where:
          - ``utilization[(l,v)]`` — log2(bytes) capacity expressions (keys:
            MEM_NOC and MEM_NODE); used only for capacity constraints.
          - ``util_hat`` — CoSA total_util reward (inner-level buf_util sum).
          - ``data_size[v]`` — inner-level streaming cost (× 0.99 in objective).
    """
    pf           = prob.prob_factors
    bytes_by_var = _bytes_by_var(bitwidths)

    noc_util = (
        _build_noc_utilization(x, pf, bytes_by_var, dram_start)
        if arch.has_noc_buffer else {}
    )
    node_util, util_hat    = _build_node_util_reward(x, pf, bytes_by_var, gb_start_level, arch.has_local_buffer)
    data_size              = _build_data_size(x, pf, gb_start_level)

    utilization = {**noc_util, **node_util}
    logger.debug(
        "build_utilization_terms: U entries=%d  has_local_buffer=%s  has_noc_buffer=%s",
        len(utilization), arch.has_local_buffer, arch.has_noc_buffer,
    )
    return utilization, util_hat, data_size


def _build_noc_utilization(
    x: Dict,
    pf: list,
    bytes_by_var: Tuple,
    dram_start: int,
) -> Dict:
    """NoCLevel GB utilization — capacity constraint only, not in objective.

    Sums log2(factor) × x[(i,d,n,k)] for all levels [0, dram_start), both
    spatial and temporal, for every dimension d where A[d][v] != 0. Only
    called when arch.has_noc_buffer (NoCLevel entries present) -- callers
    skip this entirely otherwise, mirroring how _build_node_util_reward is
    skipped when has_local_buffer is False.
    """
    result: Dict = {}
    for v in range(NUM_VARS):
        if _B[v][MEM_NOC] == 0:
            continue
        expr = LinExpr(math.log2(bytes_by_var[v]))
        for i in range(dram_start):
            for d, factors in enumerate(pf):
                if _A[d][v] == 0:
                    continue
                for n, factor in enumerate(factors):
                    coef = math.log2(factor)
                    if coef == 0.0:
                        continue
                    for k in MAPPING_KINDS:
                        expr += coef * x[(i, d, n, k)]
        result[(MEM_NOC, v)] = expr
    return result


def _build_node_util_reward(
    x: Dict,
    pf: list,
    bytes_by_var: Tuple,
    gb_start_level: int,
    has_local_buffer: bool,
) -> Tuple[Dict, LinExpr]:
    """NodeLevel L1 spad utilization — capacity constraint + util_hat reward.

    CoSA sums buf_util over ALL inner hardware levels (MEM_NODE and MEM_NOC),
    each Z-restricted to inner factors. In snn_cosa's single-inner-level
    hierarchy both reduce to level-0-only expressions, so util_hat += expr_node
    twice (once for MEM_NODE, once for MEM_NOC's inner Z-contribution).
    """
    result: Dict = {}
    util_hat = LinExpr()
    if not has_local_buffer:
        return result, util_hat
    for v in range(NUM_VARS):
        if _B[v][MEM_NODE] == 0:
            continue
        expr_node = LinExpr(math.log2(bytes_by_var[v]))
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
        result[(MEM_NODE, v)] = expr_node
        util_hat += expr_node  # MEM_NODE inner contribution
        util_hat += expr_node  # MEM_NOC inner Z-contribution (level 0 ≤ gb_start)
    return result, util_hat


def _build_data_size(
    x: Dict,
    pf: list,
    gb_start_level: int,
) -> Dict:
    """Inner-level streaming cost (CoSA §data_size), added to traffic_hat × 0.99.

    coef = (0.8 + 0.04·i) × log2(factor)   for i ∈ [0, gb_start_level)
    The 0.04·i gradient is inert at level 0 but preserved for CoSA fidelity.
    """
    result: Dict = {}
    for v in range(NUM_VARS):
        if _B[v][MEM_NOC] == 0:
            result[v] = 0.0
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
        result[v] = size
    return result


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
