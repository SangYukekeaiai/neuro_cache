#!/usr/bin/env python3
"""Step 3 – Parse the three-level SNN memory hierarchy from an arch YAML.

Expected memory levels (listed innermost → outermost in the YAML):

  NodeLevel   – per-PE local buffer (highest instance count)
  NoCLevel    – on-chip shared buffer (one instance per chip)
  OffChip     – off-chip DRAM (one instance, unbounded capacity)

Expected arch YAML format::

    arch:
      bitwidths:           # parsed by parsers/bitwidths.py
        BW_WEIGHT: 8
        BW_PSUM:   32
        BW_VMEM:   16
      storage:             # innermost first
        - name: NodeLevel
          entries:   512   # capacity in elements per instance
          instances: 1024  # number of parallel instances
        - name: NoCLevel
          entries:   65536
          instances: 1
        - name: OffChip
          instances: 1
          # no 'entries' key – OffChip capacity is treated as unbounded

All three levels store weight, psum, and vmem (no bypass).
"""

import logging
import pathlib
from typing import Dict, List

import yaml

logger = logging.getLogger(__name__)

# Required level names, innermost → outermost
_REQUIRED_LEVELS: List[str] = ["NodeLevel", "NoCLevel", "OffChip"]

# Index constants (match position in _REQUIRED_LEVELS)
MEM_NODE   = 0   # NodeLevel
MEM_NOC    = 1   # NoCLevel
MEM_OFFCHIP = 2  # OffChip


def parse_snn_arch(arch_path: pathlib.Path) -> "SNNArch":
    """Parse the three-level memory hierarchy from *arch_path*.

    Args:
        arch_path: Path to an arch YAML with ``arch.storage`` listing
                   NodeLevel, NoCLevel, and OffChip (innermost first).

    Returns:
        SNNArch populated with validated capacity and instance data.

    Raises:
        FileNotFoundError: If *arch_path* does not exist.
        ValueError: If the storage section is missing, has wrong level names,
                    or has non-positive entries / instances.
    """
    return SNNArch(arch_path)


class SNNArch:
    """Three-level SNN memory hierarchy parsed from an arch YAML.

    Attributes:
        mem_levels (int):        Number of memory levels (always 3).
        mem_entries (List[int]): Capacity in bytes for NodeLevel and
                                 NoCLevel (length 2; OffChip is unbounded).
        mem_instances (List[int]): Instance count for all three levels
                                   [NodeLevel, NoCLevel, OffChip].
        mem_idx (Dict[str,int]): Level name -> index (0=NodeLevel … 2=OffChip).
        mem_name (Dict[int,str]): Index -> level name.
        S (List[int]):           Spatial fanout constraint per level.
                                 S[i] = mem_instances[i] // mem_instances[i+1];
                                 length equals mem_levels.
        path (pathlib.Path):     Resolved path to the source arch YAML.
    """

    def __init__(self, arch_path: pathlib.Path) -> None:
        self.path = pathlib.Path(arch_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"SNNArch: arch config not found: {self.path}"
            )

        with open(self.path, "r") as f:
            raw = yaml.safe_load(f)

        if "arch" not in raw:
            raise ValueError(
                f"SNNArch: YAML at {self.path} must have a top-level 'arch' key"
            )
        arch = raw["arch"]

        if "storage" not in arch:
            raise ValueError(
                f"SNNArch: 'arch.storage' section missing in {self.path}"
            )
        storage: List[Dict] = arch["storage"]

        # Validate level names and order
        names = [lvl["name"] for lvl in storage]
        if names != _REQUIRED_LEVELS:
            raise ValueError(
                f"SNNArch: storage levels must be {_REQUIRED_LEVELS} "
                f"(innermost first), got {names} in {self.path}"
            )

        self.mem_levels: int = len(_REQUIRED_LEVELS)
        self.mem_idx: Dict[str, int] = {name: i for i, name in enumerate(_REQUIRED_LEVELS)}
        self.mem_name: Dict[int, str] = {i: name for i, name in enumerate(_REQUIRED_LEVELS)}

        # Parse instances for all three levels
        self.mem_instances: List[int] = []
        for lvl in storage:
            instances = int(lvl.get("instances", 1))
            if instances <= 0:
                raise ValueError(
                    f"SNNArch: level '{lvl['name']}' has non-positive "
                    f"instances={instances} in {self.path}"
                )
            self.mem_instances.append(instances)

        # Parse entries for NodeLevel and NoCLevel; OffChip is unbounded
        self.mem_entries: List[int] = []
        for lvl in storage[:-1]:  # exclude OffChip
            entries = int(lvl.get("entries", 0))
            if entries <= 0:
                raise ValueError(
                    f"SNNArch: level '{lvl['name']}' has non-positive "
                    f"entries={entries} in {self.path}"
                )
            self.mem_entries.append(entries)

        # Spatial fanout: S[i] = instances[i] // instances[i+1]
        # S[0] is the internal PE-level fanout (typically 1 for register files),
        # S[1] is the NoC-level fanout (number of PEs sharing NoCLevel),
        # S[2] is the chip-level fanout (number of chips sharing OffChip).
        self.S: List[int] = self._gen_spatial_constraints()

        logger.debug(
            "SNNArch loaded: instances=%s  entries=%s  S=%s",
            self.mem_instances, self.mem_entries, self.S,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gen_spatial_constraints(self) -> List[int]:
        """Return per-level spatial fanout S[i] = instances[i] // instances[i+1]."""
        S: List[int] = []
        inner = self.mem_instances[0]
        for inst in self.mem_instances:
            if inst == 0:
                raise ValueError("SNNArch: zero instances encountered")
            S.append(inner // inst)
            inner = inst
        return S

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def config_str(self) -> str:
        """Return a compact string identifying this arch configuration."""
        return self.path.stem

    def print(self) -> None:
        for i, name in self.mem_name.items():
            cap = self.mem_entries[i] if i < len(self.mem_entries) else "unbounded"
            print(
                f"  [{i}] {name:12s}  instances={self.mem_instances[i]}"
                f"  entries={cap}  S={self.S[i]}"
            )
