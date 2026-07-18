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

V2 validation used to require F_j to divide prob_bound[j] exactly, raising
ValueError otherwise. Relaxed (2026-07-16, explicit user direction) to a
best-fit rule: the NodeLevel spatial extent becomes the largest divisor of
the real dimension size that does not exceed the arch's declared cap --
this covers both a real dimension smaller than the cap (use the whole
dimension, fewer PEs than the array's max width) and a real dimension
larger than the cap but not a clean multiple of it (use the largest
divisor that still fits). When F_j already divides prob_bound[j] exactly
(every case that passed under the old strict rule), the effective factor
equals F_j unchanged -- this is a strict superset of previously solvable
cases, never a behavior change for one that already worked. See
docs/superpowers/specs/2026-07-16-v2-spatial-relaxation-design.md for the
full derivation, including why this is always solver-feasible (any
divisor of prob_bound[j] is expressible from that same bound's own prime
factors) and why nothing downstream needs to change (schedule.spatial_
factors is read back from the actually-solved Gurobi variables, never
from the arch's nominal declared cap).
"""

import logging
import math
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.layer import SNNProb

logger = logging.getLogger(__name__)


def _largest_divisor_leq(bound: int, cap: int) -> int:
    """Largest divisor of `bound` that does not exceed `cap`.

    Always >= 1 (the trivial divisor). When `cap >= bound`, returns
    `bound` itself (use the whole dimension). When `cap` already divides
    `bound` exactly, returns `cap` unchanged (non-regressive for every
    previously-solvable case).
    """
    for d in range(min(bound, cap), 0, -1):
        if bound % d == 0:
            return d
    return 1


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
        (No longer raises for a non-dividing split -- see module
        docstring's V2 relaxation. `_largest_divisor_leq` always returns a
        value expressible from prob_bound[j]'s own prime factors, so the
        equality constraint below is always satisfiable.)
    """
    split = arch.node_pe_spatial_split
    assert split is not None, "called without a spatial_split defined"

    spatial_range = range(0, gb_start_level)  # NodeLevel (level 0)
    pf = prob.prob_factors

    for dim_name, F_j in split.items():
        j = prob.prob_name_idx_dict[dim_name]

        # V2 (relaxed): best-fit divisor of the real dimension size, capped
        # at F_j -- never exceeds the arch's declared PE width, and equals
        # F_j unchanged whenever F_j already divided prob_bound[j] exactly.
        effective_F_j = _largest_divisor_leq(prob.prob_bound[j], F_j)
        if effective_F_j < F_j:
            logger.info(
                "Constraint C: dim=%s using %d/%d PEs (real dim=%d doesn't "
                "divide evenly by %d)",
                dim_name, effective_F_j, F_j, prob.prob_bound[j], F_j,
            )

        log_F = math.log2(effective_F_j)
        spatial_sum = sum(
            math.log2(pf[j][n]) * x[(i, j, n, 0)]
            for i in spatial_range
            for n in range(len(pf[j]))
            if math.log2(pf[j][n]) > 0.0
        )

        m.addConstr(spatial_sum == log_F, name=f"pe_split_{dim_name}")
        logger.debug(
            "Constraint C: dim=%s  F_j=%d  effective_F_j=%d  log_F=%.4f  range=level-0",
            dim_name, F_j, effective_F_j, log_F,
        )

        # Bar this dim's TEMPORAL (k=1) assignment at level 0 entirely.
        # node_capacity.py's plain int-cap rule gets "fill max, then nothing
        # more" for free from a SINGLE equality over the temporal variables
        # (any factor not part of reaching the pinned target would break
        # the equality). For a spatial_split dim like COUT, node_capacity.py
        # explicitly skips it ("governed by the separate spatial-fanout
        # mechanism instead"), assuming this function is the complete story
        # -- but until this fix, this function only ever pinned the SPATIAL
        # portion, leaving COUT's remaining (non-spatial) prime factors free
        # to ALSO sit at level 0 as k=1, unconstrained, at zero traffic cost
        # (temporal.py's perm_range excludes level 0 entirely) -- so the
        # solver always parked any leftover there for free instead of
        # pushing it to DRAM. This constraint supplies the missing "nothing
        # more" half explicitly: once the spatial equality above has used up
        # exactly effective_F_j's worth of this dim's factors, every
        # remaining factor is barred from level 0 altogether, so it MUST be
        # assigned at NoCLevel or DRAM (NoCLevel is empty/barred for every
        # single_node arch this dim actually applies to, so in practice this
        # means DRAM). Explicit user direction, 2026-07-16.
        for n in range(len(pf[j])):
            m.addConstr(
                x[(0, j, n, 1)] == 0, name=f"pe_split_no_temporal_{dim_name}_{n}"
            )

    logger.debug(
        "add_pe_spatial_split_constraints: %d equality constraints added",
        len(split),
    )
