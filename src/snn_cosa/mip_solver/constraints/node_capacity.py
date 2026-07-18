#!/usr/bin/env python3
"""Node-level (NodeLevel = level 0) per-dimension capacity constraints.

Replaces the old single_node bypass (model/fixed_schedule.py, retired):
instead of hand-fixing the entire schedule once a NodeLevel tile size is
known, this expresses "how much of each dimension a node can hold at once"
as MIP constraints, so the solver remains free to decide everything else --
including the full DRAM permutation order -- the way it already does for
every other arch.

NodeLevel residency governed by this module is temporal-only (k=1) --
genuine spatial (k=0) PE-parallel fanout at level 0 (e.g. SpinalFlow's
128-wide COUT) is expressed separately via the pre-existing
arch.node_pe_spatial_split mechanism (model/constraints/node_level.py),
which is already bounded by num_pes. A dimension present in
node_pe_spatial_split is skipped here entirely -- its level-0 assignment is
that mechanism's business, not this one's. For every other dimension,
spatial (k=0) at level 0 is forced to zero, so a single dimension's own
factors are never split between spatial and temporal, and dimensions never
compete for the same physical PE-parallel budget that node_pe_spatial_split
already accounts for. (Forcing *everything* to one shared kind was tried
first and made the model infeasible: KH x KW x COUT x T x CIN all forced
spatial simultaneously vastly exceeds num_pes.) This split also keeps
compute-cycle counting -- reconstructing a node's real input sequence and
deriving cycles/addresses from it, separate later logic -- working from a
clean, deterministic spatial-vs-temporal role per dimension.

Only called when arch.node_dim_capacity is not None. Once specified at all,
the mapping is a *complete* per-dimension spec covering all seven SNN
dimensions, three-way per dim (see SNNArch.node_dim_capacity docstring):

  dim present, int size  -- resident factor product at level 0 is the
                            MAXIMUM achievable product of a sub-multiset of
                            this dimension's prime factors that does not
                            exceed size (fill as much as fits, not merely
                            "up to" -- e.g. workload KH=3 with cap=4 forces
                            all of KH to the node, not optionally none of
                            it). This maximum is a deterministic function of
                            the workload's own factorization and the cap, so
                            it is precomputed in Python and pinned with an
                            equality constraint -- there is no real MIP
                            freedom in *which* dims are node-resident, only
                            in how any leftover is ordered at DRAM.
  dim present, None      -- dimension forced entirely resident at level 0
                            (the cap=infinity special case of the rule above).
  dim absent              -- dimension barred from level 0 entirely (the
                            cap=1 special case: max achievable product <=1
                            is always 1, i.e. nothing resident) -- e.g.
                            HO/WO for SpinalFlow, which never appear in its
                            node-level dimension set.
"""

import logging
import math
from typing import Dict, List

from gurobipy import Model

from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.layer import SNNProb

logger = logging.getLogger(__name__)


def _max_product_leq(factors: List[int], cap: int) -> int:
    """Largest product of any sub-multiset of *factors* that does not exceed *cap*.

    Small bounded DP over achievable products: since every factor is >= 2,
    pruning products > cap during the scan keeps the achievable set's size
    bounded by cap itself (every kept value is <= cap).
    """
    achievable = {1}
    for f in factors:
        for p in list(achievable):
            product = p * f
            if product <= cap:
                achievable.add(product)
    return max(achievable)


def add_node_capacity_constraints(
    m:    Model,
    x:    Dict,
    prob: SNNProb,
    arch: SNNArch,
) -> None:
    """Add per-dimension NodeLevel (level 0) capacity constraints.

    Args:
        m:    Gurobi Model (variables already added).
        x:    X variable dict from create_schedule_vars.
        prob: Parsed SNN layer (prime-factor lists, dimension name map).
        arch: Parsed SNN arch. arch.node_dim_capacity must not be None --
              callers are expected to guard with
              `if arch.node_dim_capacity is not None:`, matching the
              existing add_pe_spatial_split_constraints call-site pattern
              in solver.py.
    """
    capacity = arch.node_dim_capacity
    assert capacity is not None, "called without node_dim_capacity defined"

    spatial_split = arch.node_pe_spatial_split or {}
    pf = prob.prob_factors

    for dim_name, j in prob.prob_name_idx_dict.items():
        if dim_name in spatial_split:
            # Governed by the separate spatial-fanout mechanism instead --
            # leave both its spatial and temporal assignment untouched. This
            # dim may also appear in arch.node_dim_capacity purely for
            # documentation (e.g. SpinalFlow's spinalflow.yaml lists COUT in
            # both, since COUT genuinely is part of the node-level dimension
            # set even though it's realized as spatial fanout, not temporal
            # residency) -- its capacity value here is never read.
            continue

        f_j = pf[j]

        # Not a spatial-fanout dim: spatial (k=0) at level 0 is disallowed,
        # so residency is temporal-only (k=1) and never mixed with k=0.
        for n in range(len(f_j)):
            m.addConstr(
                x[(0, j, n, 0)] == 0, name=f"node_cap_no_spatial_{dim_name}_{n}"
            )
        temporal = [x[(0, j, n, 1)] for n in range(len(f_j))]

        if dim_name not in capacity:
            # Barred from level 0 entirely: zero factors of this dim may
            # ever be resident at NodeLevel.
            for n, term in enumerate(temporal):
                m.addConstr(term == 0, name=f"node_cap_bar_{dim_name}_{n}")
            continue

        cap = capacity[dim_name]

        if cap is None:
            # Forced fully resident: every factor of this dim must sit at
            # level 0 (column-sum==1 in assignment.py already guarantees
            # each factor is assigned exactly once overall).
            for n, term in enumerate(temporal):
                m.addConstr(term == 1, name=f"node_cap_full_{dim_name}_{n}")
            continue

        # Capped: pin the resident factor product to the maximum achievable
        # value <= cap (fill as much as fits), same precomputed-float-
        # coefficient equality style as node_level.py's Constraint C.
        target = _max_product_leq(f_j, cap)
        log_target = math.log2(target)
        resident_log_sum = sum(
            math.log2(f_j[n]) * temporal[n]
            for n in range(len(f_j))
            if math.log2(f_j[n]) > 0.0
        )
        m.addConstr(
            resident_log_sum == log_target,
            name=f"node_cap_bound_{dim_name}",
        )
        logger.debug(
            "Constraint node_capacity: dim=%s cap=%d target=%d log_target=%.4f",
            dim_name, cap, target, log_target,
        )

    logger.debug(
        "add_node_capacity_constraints: %d dimensions covered",
        len(prob.prob_name_idx_dict),
    )


def add_no_noc_level_constraints(
    m:              Model,
    x:              Dict,
    prob:           SNNProb,
    gb_start_level: int,
    dram_start:     int,
) -> None:
    """Forbid every factor from using the NoCLevel permutation region.

    arch.single_node=True means no physical Global Buffer exists at all --
    not merely that combine.py elides its transactions. The NoCLevel perm
    slots [gb_start_level, dram_start) must therefore stay completely
    unused: anything not resident at NodeLevel (level 0) has to go straight
    to the DRAM (OffChip) permutation region instead. Without this, the MIP
    is free to park leftover factors at NoCLevel purely because nothing
    else penalizes it, describing hardware that doesn't exist.

    Args:
        m:              Gurobi Model (variables already added).
        x:              X variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        gb_start_level: First NoCLevel permutation slot index.
        dram_start:     First OffChip permutation slot index.
    """
    pf = prob.prob_factors
    for i in range(gb_start_level, dram_start):
        for j, f_j in enumerate(pf):
            for n in range(len(f_j)):
                for k in range(2):
                    m.addConstr(
                        x[(i, j, n, k)] == 0, name=f"no_noc_{i}_{j}_{n}_{k}"
                    )
    logger.debug(
        "add_no_noc_level_constraints: NoCLevel slots [%d, %d) forced empty",
        gb_start_level, dram_start,
    )
