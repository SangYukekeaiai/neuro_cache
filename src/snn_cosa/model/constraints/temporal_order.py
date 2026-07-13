#!/usr/bin/env python3
"""Temporal permutation ordering constraints for SNN CoSA schedule variants.

Each public function adds MIP constraints to a Gurobi model to enforce one
specific temporal permutation pattern in either the GB or DRAM perm region.
No variables are created here — only constraints on the existing x dict.

All functions share the same signature:
    (m, x, prob, gb_start_level, dram_start, perm_levels)

Region layout (slot indices):
    GB   perm: [gb_start_level, dram_start)
    DRAM perm: [dram_start,     dram_start + perm_levels)

Conditional big-M encoding used throughout:
    "if factor b is in R at slot s, and factor a is also in R, then a is above b"

    wslot[a] >= wslot[b] + in_R[b] - M * (1 - in_R[a])

    where M = max possible slot value in R + 1 (one above the region ceiling).

    Case analysis:
      b in R at slot s, a in R:     wslot[a] >= s + 1             (a strictly above b)
      b not in R:                    wslot[a] >= -M                (trivially satisfied)
      a not in R (wslot[a] = 0):    0 >= wslot[b] + in_R[b] - M  (safe when M is chosen correctly)
"""

import logging
from typing import Dict

from gurobipy import Model

from snn_cosa.parsers.layer import (
    SNNProb,
    DIM_KH, DIM_KW, DIM_CIN,
    DIM_COUT, DIM_HO, DIM_WO, DIM_T,
)

logger = logging.getLogger(__name__)

_K_DIMS = (DIM_KH, DIM_KW, DIM_CIN)
_NON_K_NON_T_DIMS = (DIM_COUT, DIM_HO, DIM_WO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wslot(x: Dict, j: int, n: int, region: range):
    """Weighted slot: Σᵢ∈region i·x[(i,j,n,1)].

    Equals the slot index where prime factor (j,n) is placed as temporal
    inside region, or 0 if the factor is placed outside region.
    """
    return sum(i * x[(i, j, n, 1)] for i in region)


def _in_region(x: Dict, j: int, n: int, region: range):
    """Indicator: Σᵢ∈region x[(i,j,n,1)].

    Equals 1 if prime factor (j,n) is assigned as temporal inside region,
    else 0.
    """
    return sum(x[(i, j, n, 1)] for i in region)


def _above_all_k(
    m: Model, x: Dict, pf, j_prime: int, n_prime: int, region: range, M: int
) -> None:
    """Add: if (j_prime,n_prime) is temporal in region, it must be above every
    K-dim factor that is also temporal in region."""
    ws_jp = _wslot(x, j_prime, n_prime, region)
    ir_jp = _in_region(x, j_prime, n_prime, region)
    for j_K in _K_DIMS:
        for n_K in range(len(pf[j_K])):
            ws_K = _wslot(x, j_K, n_K, region)
            ir_K = _in_region(x, j_K, n_K, region)
            m.addConstr(ws_jp >= ws_K + ir_K - M * (1 - ir_jp))


def _above_all_t(
    m: Model, x: Dict, pf, j_prime: int, n_prime: int, region: range, M: int
) -> None:
    """Add: if (j_prime,n_prime) is temporal in region, it must be above every
    T prime factor that is also temporal in region."""
    ws_jp = _wslot(x, j_prime, n_prime, region)
    ir_jp = _in_region(x, j_prime, n_prime, region)
    for n_T in range(len(pf[DIM_T])):
        ws_T = _wslot(x, DIM_T, n_T, region)
        ir_T = _in_region(x, DIM_T, n_T, region)
        m.addConstr(ws_jp >= ws_T + ir_T - M * (1 - ir_jp))


def _t_above_all_o(
    m: Model, x: Dict, pf, region: range, M: int
) -> None:
    """Add: if T factor is temporal in region, it must be above every
    non-K non-T (COUT/HO/WO) factor that is also temporal in region."""
    for n_T in range(len(pf[DIM_T])):
        ws_T  = _wslot(x, DIM_T, n_T, region)
        ir_T  = _in_region(x, DIM_T, n_T, region)
        for j_O in _NON_K_NON_T_DIMS:
            for n_O in range(len(pf[j_O])):
                ws_O = _wslot(x, j_O, n_O, region)
                ir_O = _in_region(x, j_O, n_O, region)
                m.addConstr(ws_T >= ws_O + ir_O - M * (1 - ir_T))


# ---------------------------------------------------------------------------
# A-group: ooTK — K block innermost, T block immediately above K
# ---------------------------------------------------------------------------

def add_ootk_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """A1 — ooTK in GB perm (TR[psum] = 0).

    K block at innermost GB slots; T block contiguous immediately above K.
    Neither K nor T may appear as temporal in DRAM.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start          # one above the max GB slot (dram_start - 1)

    # Force at least one K factor temporal in GB (pattern is non-trivial)
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in GB) >= 1
    )

    # Force at least one T factor temporal in GB (otherwise TK → just K innermost,
    # which is not ooTK — the big-M ordering constraints are vacuous when T is absent)
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for n in range(len(pf[DIM_T]))
            for i in GB) >= 1
    )

    # All non-K temporal factors in GB must be above all K temporal factors in GB
    # Covers T (non-K) and COUT/HO/WO; naturally forces T into GB when K is in GB
    for j_prime in (*_NON_K_NON_T_DIMS, DIM_T):
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, GB, M)

    # All non-K non-T temporal factors in GB must be above all T temporal factors in GB
    # Ensures no COUT/HO/WO sits between the K block and the T block
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, GB, M)

    # No K temporal in DRAM
    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in DRAM:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    # No T temporal in DRAM
    for n in range(len(pf[DIM_T])):
        for i in DRAM:
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    logger.debug("add_ootk_gb: A1 constraints added")


def add_ootk_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """A2 — ooTK in DRAM perm (TR[psum] = D·L·Tgb[psum]).

    K block at innermost DRAM slots; T block contiguous immediately above K.
    K and T are free in GB.
    """
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start + perm_levels   # one above the max DRAM slot

    # Force at least one K factor temporal in DRAM
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in DRAM) >= 1
    )

    # Force at least one T factor temporal in DRAM (same vacuity issue as add_ootk_gb)
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for n in range(len(pf[DIM_T]))
            for i in DRAM) >= 1
    )

    # All non-K temporal factors in DRAM must be above all K temporal factors in DRAM
    for j_prime in (*_NON_K_NON_T_DIMS, DIM_T):
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, DRAM, M)

    # All non-K non-T temporal factors in DRAM must be above all T temporal factors in DRAM
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, DRAM, M)

    logger.debug("add_ootk_dram: A2 constraints added")


def add_otok_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """A3 — oToK non-adjacent in DRAM perm (TR[psum] = 0).

    K block at innermost DRAM slots; T block outermost in DRAM;
    at least one non-K non-T (COUT/HO/WO) separator between K and T in DRAM.
    Ordering enforced: K < O < T (inner to outer) within DRAM.
    """
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start + perm_levels

    # Force at least one K factor temporal in DRAM
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in DRAM) >= 1
    )

    # Force at least one T factor temporal in DRAM
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for n in range(len(pf[DIM_T]))
            for i in DRAM) >= 1
    )

    # Force at least one non-K non-T (O) separator temporal in DRAM
    m.addConstr(
        sum(x[(i, j_O, n, 1)]
            for j_O in _NON_K_NON_T_DIMS
            for n in range(len(pf[j_O]))
            for i in DRAM) >= 1
    )

    # All non-K temporal factors in DRAM must be above all K temporal factors
    for j_prime in (*_NON_K_NON_T_DIMS, DIM_T):
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, DRAM, M)

    # T must be above all non-K non-T temporal factors in DRAM (K < O < T)
    _t_above_all_o(m, x, pf, DRAM, M)

    logger.debug("add_otok_dram: A3 constraints added")


def add_otok_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """A4 — oToK integrated (TR[psum] = 0).

    K block innermost in GB perm; no K in DRAM; at least one non-K non-T (O)
    separator in GB; T not forced to DRAM (may sit in GB or DRAM).
    When T is in GB, T must be above all O in GB (K < O < T within GB).
    When T is in DRAM, O in GB is inherently inner to DRAM, providing the gap.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start

    # No K temporal in DRAM (K_d = 0)
    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in DRAM:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    # Force at least one K temporal in GB
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in GB) >= 1
    )

    # All non-K temporal factors in GB must be above all K temporal factors in GB
    for j_prime in (*_NON_K_NON_T_DIMS, DIM_T):
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, GB, M)

    # Force at least one non-K non-T (O) separator temporal in GB
    m.addConstr(
        sum(x[(i, j_O, n, 1)]
            for j_O in _NON_K_NON_T_DIMS
            for n in range(len(pf[j_O]))
            for i in GB) >= 1
    )

    # If T is in GB, T must be above all O in GB (K < O < T within GB)
    _t_above_all_o(m, x, pf, GB, M)

    logger.debug("add_otok_gb: A4 constraints added")


# ---------------------------------------------------------------------------
# B-group: xxxT — T block innermost
# ---------------------------------------------------------------------------

def add_xxxt_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """B1 — xxxT in DRAM perm (TR[vmem] = D·L·Tgb[vmem]).

    T block at the innermost DRAM slots; ≥1 K temporal in DRAM (outer to T).
    """
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start + perm_levels

    # At least one T factor temporal in DRAM
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for i in DRAM
            for n in range(len(pf[DIM_T]))) >= 1
    )

    # At least one K factor temporal in DRAM (outer to T by the ordering below)
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in DRAM) >= 1
    )

    # All non-T temporal factors in DRAM must be above all T temporal factors in DRAM
    non_t_dims = [j for j in range(len(pf)) if j != DIM_T]
    for j_prime in non_t_dims:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, DRAM, M)

    logger.debug("add_xxxt_dram: B1 constraints added")


def add_xxxt_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """B2 — xxxT in GB perm (TR[vmem] = 0).

    T block at the innermost GB slots; ≥1 K temporal in GB or DRAM; no T in DRAM.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start

    # At least one T factor temporal in GB
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for i in GB
            for n in range(len(pf[DIM_T]))) >= 1
    )

    # At least one K factor temporal in GB or DRAM (x means ≥1 K, outer to T)
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in (*GB, *DRAM)) >= 1
    )

    # All non-T temporal factors in GB must be above all T temporal factors in GB
    non_t_dims = [j for j in range(len(pf)) if j != DIM_T]
    for j_prime in non_t_dims:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, GB, M)

    # No T temporal in DRAM
    for n in range(len(pf[DIM_T])):
        for i in DRAM:
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    logger.debug("add_xxxt_gb: B2 constraints added")


# ---------------------------------------------------------------------------
# C-group: oooo — neither K nor T in the region
# ---------------------------------------------------------------------------

def add_oooo_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """C1 — oooo in DRAM perm (TR[psum] = D·L·Tgb[psum], TR[vmem] = D·L·Tgb[vmem]).

    No K or T temporal factors in DRAM; at least one K factor temporal in GB
    (T-only-in-GB schedules belong to gb_ooot, not here).
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors

    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in DRAM:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    for n in range(len(pf[DIM_T])):
        for i in DRAM:
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    # Require at least one K factor temporal in GB to distinguish from gb_oooo (C2)
    # and gb_ooot (T-only in GB).
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in GB) >= 1
    )

    logger.debug("add_oooo_dram: C1 constraints added")


def add_oooo_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """C2 — oooo in GB perm (TR[psum] = 0, TR[vmem] = 0).

    No K or T temporal factors in GB or DRAM; both are forced to NodeLevel
    temporal or spatial assignments only.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    both = [*GB, *DRAM]

    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in both:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    for n in range(len(pf[DIM_T])):
        for i in both:
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    logger.debug("add_oooo_gb: C2 constraints added")


# ---------------------------------------------------------------------------
# D-group: oooT — T innermost, no K in any perm region
# ---------------------------------------------------------------------------

def add_ooot_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """D1 — oooT in GB perm (TR[psum] = 0, TR[vmem] = 0).

    T block at the innermost GB slots; no K or T temporal in DRAM; no K in GB.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start

    # No K temporal in GB or DRAM
    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in (*GB, *DRAM):
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    # At least one T factor temporal in GB
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for i in GB
            for n in range(len(pf[DIM_T]))) >= 1
    )

    # All non-K non-T temporal factors in GB must be above all T temporal factors in GB
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, GB, M)

    # No T temporal in DRAM
    for n in range(len(pf[DIM_T])):
        for i in DRAM:
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    logger.debug("add_ooot_gb: D1 constraints added")


def add_ooot_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """D2 — oooT in DRAM perm (TR[psum] = D·L·Tgb[psum], TR[vmem] = D·L·Tgb[vmem]).

    T block at the innermost DRAM slots; no K temporal in DRAM.
    """
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start + perm_levels

    # No K temporal in DRAM
    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in DRAM:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    # At least one T factor temporal in DRAM
    m.addConstr(
        sum(x[(i, DIM_T, n, 1)]
            for i in DRAM
            for n in range(len(pf[DIM_T]))) >= 1
    )

    # All non-K non-T temporal factors in DRAM must be above all T temporal factors
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_t(m, x, pf, j_prime, n_prime, DRAM, M)

    logger.debug("add_ooot_dram: D2 constraints added")


# ---------------------------------------------------------------------------
# E-group: oooK — K innermost, no T in any perm region
# ---------------------------------------------------------------------------

def add_oook_gb(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """E1 — oooK in GB perm (TR[psum] = 0, TR[vmem] = 0).

    K block at the innermost GB slots; no T in GB or DRAM; no K in DRAM.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start

    # No T temporal in GB or DRAM
    for n in range(len(pf[DIM_T])):
        for i in (*GB, *DRAM):
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    # At least one K factor temporal in GB
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in GB) >= 1
    )

    # All non-K non-T temporal factors in GB must be above all K temporal factors in GB
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, GB, M)

    # No K temporal in DRAM
    for j_K in _K_DIMS:
        for n in range(len(pf[j_K])):
            for i in DRAM:
                m.addConstr(x[(i, j_K, n, 1)] == 0)

    logger.debug("add_oook_gb: E1 constraints added")


def add_oook_dram(
    m: Model,
    x: Dict,
    prob: SNNProb,
    gb_start_level: int,
    dram_start: int,
    perm_levels: int,
) -> None:
    """E2 — oooK in DRAM perm (TR[psum] = D·L·Tgb[psum], TR[vmem] = D·L·Tgb[vmem]).

    K block at the innermost DRAM slots; no T in GB or DRAM.
    """
    GB   = range(gb_start_level, dram_start)
    DRAM = range(dram_start, dram_start + perm_levels)
    pf   = prob.prob_factors
    M    = dram_start + perm_levels

    # No T temporal in GB or DRAM
    for n in range(len(pf[DIM_T])):
        for i in (*GB, *DRAM):
            m.addConstr(x[(i, DIM_T, n, 1)] == 0)

    # At least one K factor temporal in DRAM
    m.addConstr(
        sum(x[(i, j_K, n, 1)]
            for j_K in _K_DIMS
            for n in range(len(pf[j_K]))
            for i in DRAM) >= 1
    )

    # All non-K non-T temporal factors in DRAM must be above all K temporal factors
    for j_prime in _NON_K_NON_T_DIMS:
        for n_prime in range(len(pf[j_prime])):
            _above_all_k(m, x, pf, j_prime, n_prime, DRAM, M)

    logger.debug("add_oook_dram: E2 constraints added")
