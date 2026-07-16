"""Classifies a solved single_node Schedule's weight-loading permutation
against the "Neuromorphic Cache Design" draft's Table I locality types
(Time-Inner Temporal Locality, M-Inner Temporal Locality, N-Inner Spatial
Locality).

Rule derivation note: the paper's own prose description of MITL/NISL is
imprecise ("NISL degrades as M moves inner->outer", "MITL degrades as N
moves outer->inner") -- this implementation instead matches Table I's own
7 rows exactly, reverse-derived directly from the table (see
docs/superpowers/specs/2026-07-16-archmodel-live-wiring-locality-design.md's
Design section for the full row-by-row derivation):

    TITL <- T's position in the permutation (read outer->inner):
            innermost=Strong, middle=Medium, outermost=Weak, absent="N/A"
    NISL <- N's (=COUT) position, the SAME rule as TITL
    MITL <- N's position too, but INVERTED: innermost=Weak, middle=Medium,
            outermost=Strong

M's own position does not independently drive any of the three degrees
in Table I's data -- with only 3 permutation slots, T's and N's positions
already determine M's by elimination, so the table's 7 rows alone cannot
distinguish an M-driven rule from "whichever slot T and N didn't take".
"""

from __future__ import annotations

from typing import Dict, List, Optional

from snn_cosa.nocsim.schedule.decode import Schedule
from snn_cosa.parsers.layer import DIM_COUT, DIM_HO, DIM_T, DIM_WO

# Table I's 7 canonical rows: (order outer->inner, attributed paper/arch).
# M = HO+WO collapsed into one slot; T = DIM_T; N = DIM_COUT.
TABLE1_ROWS: List[Dict[str, object]] = [
    {"order": ["N", "M", "T"], "TITL": "Strong", "MITL": "Strong", "NISL": "Weak", "arch": "GustavSNN [7]"},
    {"order": ["M", "N", "T"], "TITL": "Strong", "MITL": "Medium", "NISL": "Medium", "arch": "SpinalFlow [10]"},
    {"order": ["N", "T", "M"], "TITL": "Medium", "MITL": "Strong", "NISL": "Weak", "arch": None},
    {"order": ["T", "N", "M"], "TITL": "Weak", "MITL": "Medium", "NISL": "Medium", "arch": "Phi/Prosperity [11,12]"},
    {"order": ["M", "T", "N"], "TITL": "Medium", "MITL": "Weak", "NISL": "Strong", "arch": "PTB [6]"},
    {"order": ["T", "M", "N"], "TITL": "Weak", "MITL": "Weak", "NISL": "Strong", "arch": None},
    {"order": ["M", "N"], "TITL": "N/A", "MITL": "Weak", "NISL": "Strong", "arch": "LoAS [5]"},
]


def _dim_tag(dim: int) -> Optional[str]:
    if dim == DIM_T:
        return "T"
    if dim == DIM_COUT:
        return "N"
    if dim in (DIM_HO, DIM_WO):
        return "M"
    return None  # reduction dim (KH/KW/CIN) -- not part of the M/N/T abstraction


def outer_to_inner_order(schedule: Schedule) -> List[str]:
    """This schedule's dram_temporal_loops dims, outer->inner, tagged
    "T"/"N"/"M" -- HO and WO both tag "M" and collapse into one slot if
    adjacent. Reduction dims (KH/KW/CIN) are dropped entirely.

    Raises:
        ValueError: if HO and WO both appear but are non-adjacent (can't
                    collapse into one "M" slot -- non-canonical schedule).
    """
    loops = sorted(schedule.dram_temporal_loops, key=lambda item: -item.level)  # outer -> inner
    seq: List[str] = []
    for item in loops:
        tag = _dim_tag(item.dim)
        if tag is None:
            continue
        if seq and seq[-1] == tag:
            continue  # HO+WO adjacent, both "M" -- collapse
        seq.append(tag)

    if seq.count("M") > 1:
        raise ValueError(f"HO/WO are non-adjacent in this schedule's permutation: {seq}")
    return seq


def _degree(order: List[str], tag: str) -> str:
    if tag not in order:
        return "N/A"
    idx = order.index(tag)
    if idx == len(order) - 1:
        return "Strong"   # innermost
    if idx == 0:
        return "Weak"     # outermost
    return "Medium"


def _invert(degree: str) -> str:
    return {"Strong": "Weak", "Weak": "Strong", "Medium": "Medium", "N/A": "N/A"}[degree]


def classify_schedule(schedule: Schedule) -> Dict[str, object]:
    """Classify a solved single_node Schedule's TITL/MITL/NISL degrees.

    Returns:
        {"order": List[str] or None, "TITL": str, "MITL": str,
         "NISL": str, "table1_row": List[str] or None,
         "table1_arch": str or None, "error": str (only if non-canonical)}
    """
    try:
        order = outer_to_inner_order(schedule)
    except ValueError as exc:
        return {
            "order": None, "TITL": "non-canonical", "MITL": "non-canonical",
            "NISL": "non-canonical", "table1_row": None, "table1_arch": None,
            "error": str(exc),
        }

    nisl = _degree(order, "N")
    result = {
        "order": order,
        "TITL": _degree(order, "T"),
        "MITL": _invert(nisl),
        "NISL": nisl,
        "table1_row": None,
        "table1_arch": None,
    }
    for row in TABLE1_ROWS:
        if row["order"] == order:
            result["table1_row"] = row["order"]
            result["table1_arch"] = row["arch"]
            break
    return result