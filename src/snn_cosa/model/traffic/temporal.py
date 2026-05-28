#!/usr/bin/env python3
"""Step 7 – Temporal traffic expressions for SNN scheduling.

Computes log₂-scale temporal traffic for each variable across the unified
permutation range (NoCLevel perm slots + OffChip perm slots combined).

Two formulations, one per variable class:

  weight / psum  (bilinear)
    traffic[v] = log₂(MULT[v]) + Σᵢ  l[i] · y[(v,i)]

    l[i] is the log₂ size of the temporal factor placed at perm slot i.
    y[(v,i)] = 1 when variable v must cross the memory boundary at level i,
    i.e. a related dimension is tiled temporally at or inside level i.
    The product l[i]·y[(v,i)] captures the per-slot traffic contribution.

  vmem  (linear)
    traffic[vmem] = log₂(MULT[vmem]) + Σᵢ Σⱼ∉red Σₙ log₂(f_j[n])·x[(i,j,n,1)]

    vmem (membrane potential) must be loaded and stored at every iteration
    over any non-reduction dimension (COUT, HO, WO, T).  Reduction dims
    (KH, KW, CIN) do not update the vmem address space and are excluded.
    No y indicator: every temporal non-reduction tiling unconditionally
    causes a vmem load+store at that level.

All traffic values are in log₂(elements):
    log₂(TRAFFIC_MULT[v]) accounts for load-only (weight, +0) vs
    load+store (psum/vmem, +1 in log₂ because MULT=2).
    Bit-width scaling is applied in data_size.py, not here.
"""

import logging
import numpy as np
from typing import Dict, Tuple

from snn_cosa.parsers.layer import SNNProb, SNN_REDUCTION_DIMS, DIM_T
from snn_cosa.model.constants import VAR_WEIGHT, VAR_PSUM, VAR_VMEM, TRAFFIC_MULT

logger = logging.getLogger(__name__)


def compute_temporal_traffic(
    x: Dict,
    y: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> Tuple[Dict, Dict]:
    """Compute log₂-scale temporal traffic expressions (no constraints added).

    Args:
        x:              X decision-variable dict from create_schedule_vars.
        y:              Unified y variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        gb_start_level: First NoCLevel perm slot.
        dram_start:     First OffChip perm slot.
        perm_levels:    Slots per permutation boundary.

    Returns:
        l       – {i: LinExpr}   log₂ temporal factor at each perm slot i.
        traffic – {v: Expr}      Unified temporal traffic per variable.
                  weight, psum → QuadExpr  (bilinear l[i]·y[v,i]).
                  vmem         → LinExpr   (linear over non-reduction dims).
                  All in log₂(elements): log₂(TRAFFIC_MULT[v]) included.
    """
    pf = prob.prob_factors
    perm_range = range(gb_start_level, dram_start + perm_levels)

    # ------------------------------------------------------------------
    # l[i]: total temporal log-factor at perm slot i  (not A-weighted)
    #   l[i] = Σⱼ Σₙ log₂(f_j[n]) · x[(i,j,n,1)]
    #   Shared across all variables; variable specificity enters via y.
    # ------------------------------------------------------------------
    l: Dict = {}
    for i in perm_range:
        slot = 0.0
        for j, f_j in enumerate(pf):
            for n in range(len(f_j)):
                lf = np.log2(f_j[n])
                if lf > 0.0:
                    slot += lf * x[(i, j, n, 1)]
        l[i] = slot

    # ------------------------------------------------------------------
    # weight / psum: bilinear traffic
    #   Offset = log₂(TRAFFIC_MULT[v])
    #   Element term = Σᵢ l[i] · y[(v,i)]   (QuadExpr in Gurobi)
    # ------------------------------------------------------------------
    traffic: Dict = {}
    for v in [VAR_WEIGHT, VAR_PSUM]:
        offset = np.log2(TRAFFIC_MULT[v])
        elem = sum(l[i] * y[(v, i)] for i in perm_range)
        traffic[v] = offset + elem

    # ------------------------------------------------------------------
    # vmem: linear traffic = (COUT/HO/WO temporal tile) × (T temporal)
    #   vmem size is HO×WO×COUT (T-independent).  T is NOT a size dim for
    #   vmem but IS a multiplier: for each T temporal tiling at a perm
    #   slot, vmem must be loaded/stored once per outer T iteration.
    #   KH/KW/CIN (reduction dims) do not drive vmem traffic at all.
    #   In log₂ space: product → sum of two separate accumulators.
    # ------------------------------------------------------------------
    offset = np.log2(TRAFFIC_MULT[VAR_VMEM])

    vmem_size = 0.0   # log₂ of COUT/HO/WO temporal tile (vmem spatial extent)
    vmem_T    = 0.0   # log₂ of T temporal factor (multiplier)
    for i in perm_range:
        for j, f_j in enumerate(pf):
            if j in SNN_REDUCTION_DIMS:
                continue
            for n in range(len(f_j)):
                lf = np.log2(f_j[n])
                if lf > 0.0:
                    term = lf * x[(i, j, n, 1)]
                    if j == DIM_T:
                        vmem_T    += term
                    else:          # COUT, HO, WO
                        vmem_size += term

    traffic[VAR_VMEM] = offset + vmem_size + vmem_T   # product in linear space

    logger.debug(
        "compute_temporal_traffic: l slots=%d  traffic vars=%d",
        len(l), len(traffic),
    )
    return l, traffic
