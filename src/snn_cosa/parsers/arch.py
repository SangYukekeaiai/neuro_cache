#!/usr/bin/env python3
"""Step 3 – Parse the three-level SNN memory hierarchy from an arch YAML.

Expected memory levels (listed innermost → outermost in the YAML):

  NodeLevel   – per-PE local buffer (highest instance count)
  NoCLevel    – on-chip shared buffer (one instance per chip)
  OffChip     – off-chip DRAM (one instance, unbounded capacity)

NodeLevel can describe a two-level internal hierarchy for hardware metadata:
PE registers and a per-node local buffer.  These are not extra mapping levels.

Expected arch YAML format::

    arch:
      bitwidths:           # parsed by parsers/bitwidths.py
        BW_WEIGHT: 8
        BW_PSUM:   32
        BW_VMEM:   16
      storage:             # innermost first
        - name: NodeLevel
          instances: 1024  # number of parallel instances
          pe:              # internal metadata only
            num_pes: 1024
            registers:
              entries:     # bytes per PE
                weight: 128
                psum:   128
                vmem:   256
              bitwidths:
                weight: 8
                psum:   16
                vmem:   32
          local_buffer:    # internal metadata only
            entries:       # bytes per node
              weight: 1024
              psum:   1024
              vmem:   2048
        - name: NoCLevel
          entries:         # shared on-chip/global-buffer bytes
            weight: 16384
            psum:   16384
            vmem:   32768
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
_REQUIRED_ENTRY_KEYS: List[str] = ["weight", "psum", "vmem"]
_REQUIRED_BITWIDTH_KEYS: List[str] = ["weight", "psum", "vmem"]

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
        mem_entries (List[Dict[str,int]]): Per-variable capacity in bytes for
                                           NodeLevel local buffer and NoCLevel
                                           global buffer (length 2; OffChip is
                                           unbounded).  Only NoCLevel is used
                                           by capacity constraints.
        node_pe_num_pes (int):   PE count stored as NodeLevel metadata.
        node_pe_register_entries (Dict[str,int]): Per-PE register bytes.
        node_pe_register_bitwidths (Dict[str,int]): Per-PE register bit-widths.
        node_local_buffer_entries (Dict[str,int]): Per-node local buffer bytes.
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

        node_level = storage[MEM_NODE]
        noc_level = storage[MEM_NOC]
        (
            self.node_pe_num_pes,
            self.node_pe_register_entries,
            self.node_pe_register_bitwidths,
        ) = self._parse_node_pe(node_level)
        self.node_local_buffer_entries = self._parse_node_local_buffer(node_level)

        # Keep the legacy index shape for callers: index 0 is NodeLevel
        # local-buffer metadata, index 1 is NoCLevel global-buffer capacity.
        # The current optimization model constrains only index 1.
        self.mem_entries: List[Dict[str, int]] = [
            self.node_local_buffer_entries,
            self._parse_entries(noc_level, "entries"),
        ]

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

    def _parse_entries(self, lvl: Dict, field_name: str) -> Dict[str, int]:
        """Parse required per-variable byte capacities for one storage level."""
        raw_entries = lvl.get(field_name)
        level_name = lvl["name"]
        if not isinstance(raw_entries, dict):
            raise ValueError(
                f"SNNArch: level '{level_name}' must define per-variable "
                f"{field_name} with keys {_REQUIRED_ENTRY_KEYS} in {self.path}"
            )

        keys = sorted(raw_entries.keys())
        required = sorted(_REQUIRED_ENTRY_KEYS)
        if keys != required:
            raise ValueError(
                f"SNNArch: level '{level_name}' {field_name} must have exactly "
                f"keys {_REQUIRED_ENTRY_KEYS}, got {keys} in {self.path}"
            )

        entries: Dict[str, int] = {}
        for key in _REQUIRED_ENTRY_KEYS:
            value = int(raw_entries[key])
            if value <= 0:
                raise ValueError(
                    f"SNNArch: level '{level_name}' has non-positive "
                    f"{field_name}.{key}={value} in {self.path}"
                )
            entries[key] = value
        return entries

    def _parse_bitwidths(self, lvl: Dict, raw_bitwidths: Dict) -> Dict[str, int]:
        """Parse required per-variable bit-widths from NodeLevel metadata."""
        level_name = lvl["name"]
        if not isinstance(raw_bitwidths, dict):
            raise ValueError(
                f"SNNArch: level '{level_name}' pe.registers.bitwidths must "
                f"define keys {_REQUIRED_BITWIDTH_KEYS} in {self.path}"
            )

        keys = sorted(raw_bitwidths.keys())
        required = sorted(_REQUIRED_BITWIDTH_KEYS)
        if keys != required:
            raise ValueError(
                f"SNNArch: level '{level_name}' pe.registers.bitwidths must "
                f"have exactly keys {_REQUIRED_BITWIDTH_KEYS}, got {keys} "
                f"in {self.path}"
            )

        bitwidths: Dict[str, int] = {}
        for key in _REQUIRED_BITWIDTH_KEYS:
            value = int(raw_bitwidths[key])
            if value <= 0:
                raise ValueError(
                    f"SNNArch: level '{level_name}' has non-positive "
                    f"pe.registers.bitwidths.{key}={value} in {self.path}"
                )
            bitwidths[key] = value
        return bitwidths

    def _parse_node_pe(self, lvl: Dict) -> tuple[int, Dict[str, int], Dict[str, int]]:
        """Parse PE-register metadata nested inside NodeLevel."""
        pe = lvl.get("pe")
        if not isinstance(pe, dict):
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' must define pe metadata "
                f"in {self.path}"
            )

        num_pes = int(pe.get("num_pes", 0))
        if num_pes <= 0:
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' has non-positive "
                f"pe.num_pes={num_pes} in {self.path}"
            )
        if num_pes != self.mem_instances[MEM_NODE]:
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' pe.num_pes={num_pes} must "
                f"match instances={self.mem_instances[MEM_NODE]} so existing "
                f"fanout behavior remains unambiguous in {self.path}"
            )

        registers = pe.get("registers")
        if not isinstance(registers, dict):
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' must define pe.registers "
                f"in {self.path}"
            )

        entries_holder = {"name": lvl["name"], "entries": registers.get("entries")}
        entries = self._parse_entries(entries_holder, "entries")
        bitwidths = self._parse_bitwidths(lvl, registers.get("bitwidths"))
        return num_pes, entries, bitwidths

    def _parse_node_local_buffer(self, lvl: Dict) -> Dict[str, int]:
        """Parse local-buffer metadata nested inside NodeLevel."""
        local_buffer = lvl.get("local_buffer")
        if not isinstance(local_buffer, dict):
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' must define local_buffer "
                f"metadata in {self.path}"
            )
        entries_holder = {"name": lvl["name"], "entries": local_buffer.get("entries")}
        return self._parse_entries(entries_holder, "entries")

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
