#!/usr/bin/env python3
"""Traffic-mode configuration for SNN CoSA enumeration.

Defines the complete set of enumerable schedule variants and the per-mode
constraint/traffic specification that the solver consumes.

Three categories (plus BASE):

  A — PSUM/ooTK  : psum accumulation reuse via innermost K–T block
  B — VMEM/xxxT  : vmem temporal streaming via innermost T block
  C — OOOO/OOOT/OOOK : neither psum nor vmem cross the chosen boundary
      OOOO — no K, no T in region
      OOOT — T innermost, no K
      OOOK — K innermost, no T

Each _ModeSpec carries:
  add_constraints  — optional function that adds ordering constraints to the
                     Gurobi model (None for BASE, which is unconstrained).
  zero_vars        — frozenset of variable indices whose temporal traffic is
                     forced to zero (GB-side patterns that eliminate DRAM
                     boundary crossings for those variables).
  gb_only_vars     — frozenset of variable indices whose temporal traffic sum
                     is restricted to GB perm slots only (DRAM-side patterns
                     where Td[v] = 1, so DRAM contributes no multiplier).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, FrozenSet, Optional

from snn_cosa.model.constants import VAR_PSUM, VAR_VMEM
from snn_cosa.model.constraints import (
    add_ootk_gb,
    add_ootk_dram,
    add_xxxt_dram,
    add_xxxt_gb,
    add_oooo_dram,
    add_oooo_gb,
    add_ooot_gb,
    add_ooot_dram,
    add_oook_gb,
    add_oook_dram,
)


class TrafficMode(str, Enum):
    BASE            = "base"
    # A — PSUM/ooTK
    PSUM_GB_OOTK    = "psum_gb_ootk"
    PSUM_DRAM_OOTK  = "psum_dram_ootk"
    # B — VMEM/xxxT
    VMEM_DRAM_XXXT  = "vmem_dram_xxxt"
    VMEM_GB_XXXT    = "vmem_gb_xxxt"
    # C — OOOO/OOOT/OOOK (DRAM-side: gb_only; GB-side: zero)
    DRAM_OOOO       = "dram_oooo"
    DRAM_OOOT       = "dram_ooot"
    DRAM_OOOK       = "dram_oook"
    GB_OOOO         = "gb_oooo"
    GB_OOOT         = "gb_ooot"
    GB_OOOK         = "gb_oook"


@dataclass(frozen=True)
class _ModeSpec:
    add_constraints: Optional[Callable]  # None for BASE (unconstrained)
    zero_vars:       FrozenSet[int]      # TR[v] = 0  (GB-side patterns)
    gb_only_vars:    FrozenSet[int]      # Td[v] = 1  (DRAM-side patterns)


_MODE_SPECS: Dict[TrafficMode, _ModeSpec] = {
    TrafficMode.BASE:           _ModeSpec(None,          frozenset(),                     frozenset()),
    # A — PSUM/ooTK
    TrafficMode.PSUM_GB_OOTK:   _ModeSpec(add_ootk_gb,   frozenset({VAR_PSUM}),           frozenset()),
    TrafficMode.PSUM_DRAM_OOTK: _ModeSpec(add_ootk_dram, frozenset(),                     frozenset({VAR_PSUM})),
    # B — VMEM/xxxT
    TrafficMode.VMEM_DRAM_XXXT: _ModeSpec(add_xxxt_dram, frozenset(),                     frozenset({VAR_VMEM})),
    TrafficMode.VMEM_GB_XXXT:   _ModeSpec(add_xxxt_gb,   frozenset({VAR_VMEM}),           frozenset()),
    # C — DRAM-side (gb_only for both psum + vmem)
    TrafficMode.DRAM_OOOO:      _ModeSpec(add_oooo_dram, frozenset(),                     frozenset({VAR_PSUM, VAR_VMEM})),
    TrafficMode.DRAM_OOOT:      _ModeSpec(add_ooot_dram, frozenset(),                     frozenset({VAR_PSUM, VAR_VMEM})),
    TrafficMode.DRAM_OOOK:      _ModeSpec(add_oook_dram, frozenset(),                     frozenset({VAR_PSUM, VAR_VMEM})),
    # C — GB-side (zero both psum + vmem)
    TrafficMode.GB_OOOO:        _ModeSpec(add_oooo_gb,   frozenset({VAR_PSUM, VAR_VMEM}), frozenset()),
    TrafficMode.GB_OOOT:        _ModeSpec(add_ooot_gb,   frozenset({VAR_PSUM, VAR_VMEM}), frozenset()),
    TrafficMode.GB_OOOK:        _ModeSpec(add_oook_gb,   frozenset({VAR_PSUM, VAR_VMEM}), frozenset()),
}


__all__ = ["TrafficMode", "_ModeSpec", "_MODE_SPECS"]
