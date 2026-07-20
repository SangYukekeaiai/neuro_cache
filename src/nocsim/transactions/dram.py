"""DRAM ↔ GB unicast transactions.

Two generic functions called once per DRAM temporal step for each variable
that has traffic at that step:

  load_from_dram — DRAM port → GB port  (fetch one GB tile from off-chip)
  store_to_dram  — GB port  → DRAM port (write one GB tile back to off-chip)

Skip conditions are evaluated by combine.py and passed as a boolean:

  weight load : no skip  (always transfers at every DRAM step)
  psum   load : skip if is_first_K_dram  OR  is_psum_dram_free
  psum   store: skip if is_last_K_dram   OR  is_psum_dram_free
  vmem   load : skip if is_first_T_dram  OR  is_vmem_dram_free
  vmem   store: skip if is_last_T_dram   OR  is_vmem_dram_free

Data sizing
-----------
The GB tile size is data_size[var_name] elements.  One full tile is
transferred per call:

    size_bits = data_size[var_name] × datawidth

Hop accounting
--------------
DRAM ↔ GB transfers use the off-chip DRAM bus, not the NoC mesh.  They
are excluded from unicast_hops and multicast_hops.

  load_from_dram  src = dram_port  (≠ gb_port)  → not counted  ✓
  store_to_dram   src = gb_port,   dest = dram_port
                  → generator.unicast guards against this with
                    ``dest != dram_port`` (see core/generator.py)  ✓
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..core.generator import TC_Generator


def load_from_dram(
    gen:          TC_Generator,
    var_name:     str,
    data_size:    Dict[str, int],
    datawidth:    int,
    skip:         bool,
    deps:         List[int],
    label_prefix: str,
) -> Optional[int]:
    """Unicast one GB tile of var_name from DRAM port to GB port.

    Args:
        gen:          TC_Generator.
        var_name:     Variable name key into data_size (``"weight"``,
                      ``"psum"``, or ``"vmem"``).
        data_size:    GB tile element counts keyed by var name.
        datawidth:    Bits per element for this variable.
        skip:         True → return None immediately (no TC emitted).
                      Computed by combine.py from traffic-free flags and
                      first/last K/T position at DRAM level.
        deps:         TC ids that must complete before this transfer starts.
        label_prefix: DRAM step identifier, e.g. ``"dram_3"`` (dram_i=3).

    Returns:
        tc_id of the emitted unicast TC, or None if skipped.
    """
    if skip:
        return None

    size_bits = data_size[var_name] * datawidth
    label     = f"{label_prefix}__load_{var_name}"
    return gen.unicast(
        var_name, size_bits, datawidth,
        gen.noc.dram_port, gen.noc.gb_port,
        deps, label,
    )


def store_to_dram(
    gen:          TC_Generator,
    var_name:     str,
    data_size:    Dict[str, int],
    datawidth:    int,
    skip:         bool,
    deps:         List[int],
    label_prefix: str,
) -> Optional[int]:
    """Unicast one GB tile of var_name from GB port back to DRAM port.

    Args:
        gen:          TC_Generator.
        var_name:     Variable name key into data_size.
        data_size:    GB tile element counts keyed by var name.
        datawidth:    Bits per element for this variable.
        skip:         True → return None immediately (no TC emitted).
        deps:         TC ids that must complete before this transfer starts.
        label_prefix: DRAM step identifier, e.g. ``"dram_3"`` (dram_i=3).

    Returns:
        tc_id of the emitted unicast TC, or None if skipped.
    """
    if skip:
        return None

    size_bits = data_size[var_name] * datawidth
    label     = f"{label_prefix}__store_{var_name}"
    return gen.unicast(
        var_name, size_bits, datawidth,
        gen.noc.gb_port, gen.noc.dram_port,
        deps, label,
    )
