#!/usr/bin/env python3
"""Step 3 – Parse the three-level SNN memory hierarchy from an arch YAML.

Expected memory levels (listed innermost → outermost in the YAML):

  NodeLevel   – per-node compute unit (highest instance count)
  NoCLevel    – on-chip shared buffer (one instance per chip)
  OffChip     – off-chip DRAM (one instance, unbounded capacity)

NodeLevel requires only pe.num_pes. Everything else about it is optional:
  pe.registers  – per-PE register file (metadata only, unused by the solver)
  local_buffer  – per-node L1 scratchpad byte capacity (a real MIP constraint
                  when present; no NodeLevel byte-capacity check when absent)

NoCLevel's entries is also optional: absent means no NoCLevel
byte-capacity check (e.g. single_node archs with no physical Global Buffer
to size realistically).

Expected arch YAML format (local_buffer, pe.registers, and NoCLevel.entries
all optional)::

    arch:
      bitwidths:
        BW_WEIGHT: 8
        BW_PSUM:   32
        BW_VMEM:   16
      storage:
        - name: NodeLevel
          instances: 128      # number of nodes; drives S[1]
          pe:
            num_pes: 128      # PEs per node; required
          local_buffer:       # OPTIONAL — omit for no NodeLevel byte check
            entries:
              weight: 1024
              psum:   1024
              vmem:   2048
        - name: NoCLevel
          entries:            # OPTIONAL — omit for no NoCLevel byte check
            weight: 16384
            psum:   16384
            vmem:   32768
          instances: 1
        - name: OffChip
          instances: 1

All three levels store weight, psum, and vmem (no bypass).
"""

import logging
import pathlib
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Required level names, innermost → outermost
_REQUIRED_LEVELS: List[str] = ["NodeLevel", "NoCLevel", "OffChip"]
_REQUIRED_ENTRY_KEYS: List[str] = ["weight", "psum", "vmem"]
_REQUIRED_BITWIDTH_KEYS: List[str] = ["weight", "psum", "vmem"]

# Index constants (match position in _REQUIRED_LEVELS)
MEM_NODE    = 0   # NodeLevel
MEM_NOC     = 1   # NoCLevel
MEM_OFFCHIP = 2   # OffChip


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

    ``mem_entries[0]`` holds optional per-node local-buffer capacities and
    ``mem_entries[1]`` holds optional shared-GB capacities. ``num_pes`` is
    the per-node PE fanout budget; ``S[1]`` is the inter-node fanout.
    NodeLevel dimension placement belongs to a separate dataflow YAML.
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

        if "node_dim_capacity" in arch:
            raise ValueError(
                f"SNNArch: node_dim_capacity belongs in a dataflow YAML, "
                f"not {self.path}"
            )

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
        noc_level  = storage[MEM_NOC]

        (
            self.node_pe_num_pes,
            self.node_pe_register_entries,
            self.node_pe_register_bitwidths,
        ) = self._parse_node_pe(node_level)

        self.node_local_buffer_entries: Optional[Dict[str, int]] = (
            self._parse_node_local_buffer(node_level)
        )

        # Index 0 = NodeLevel (None when no local_buffer), index 1 = NoCLevel
        # (None when entries absent -- unconstrained/no capacity check, e.g.
        # single_node archs with no physical Global Buffer to size).
        self.mem_entries: List[Optional[Dict[str, int]]] = [
            self.node_local_buffer_entries,
            self._parse_optional_entries(noc_level, "entries"),
        ]

        # S[i] = instances[i] // instances[i+1]  (inter-level fanout only).
        # S[0] is always 1; NodeLevel spatial uses node_pe_num_pes directly.
        self.S: List[int] = self._gen_spatial_constraints()

        # Pure hardware-topology flag consumed by nocsim/combine.py.
        self.single_node: bool = bool(arch.get("single_node", False))

        logger.debug(
            "SNNArch loaded: instances=%s  has_local_buffer=%s  "
            "num_pes=%d  S=%s  single_node=%s",
            self.mem_instances, self.has_local_buffer,
            self.node_pe_num_pes, self.S, self.single_node,
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def has_local_buffer(self) -> bool:
        """True when NodeLevel defines a local_buffer (L1 spad)."""
        return self.node_local_buffer_entries is not None

    @property
    def has_noc_buffer(self) -> bool:
        """True when NoCLevel defines entries (a byte-capacity-checked GB)."""
        return self.mem_entries[MEM_NOC] is not None

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

    def _parse_optional_entries(
        self, lvl: Dict, field_name: str
    ) -> Optional[Dict[str, int]]:
        """Like _parse_entries, but returns None when field_name is absent.

        Used for NoCLevel: entries absent means no capacity check for that
        level (e.g. single_node archs with no physical Global Buffer to
        size realistically) rather than a parse error.
        """
        if lvl.get(field_name) is None:
            return None
        return self._parse_entries(lvl, field_name)

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

    def _parse_node_pe(
        self, lvl: Dict
    ) -> tuple[int, Optional[Dict[str, int]], Optional[Dict[str, int]]]:
        """Parse pe.num_pes (required) and optional pe.registers.

        pe.registers is metadata only -- parsed and stored on SNNArch for
        potential future use (e.g. per-PE energy/area modeling), but not
        currently read by any constraint, objective, or nocsim code. It's
        optional so archs that don't need it aren't forced to invent numbers
        that affect nothing.
        """
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

        registers = pe.get("registers")
        if registers is None:
            entries, bitwidths = None, None
        else:
            if not isinstance(registers, dict):
                raise ValueError(
                    f"SNNArch: level '{lvl['name']}' pe.registers must be a "
                    f"mapping in {self.path}"
                )
            entries_holder = {"name": lvl["name"], "entries": registers.get("entries")}
            entries   = self._parse_entries(entries_holder, "entries")
            bitwidths = self._parse_bitwidths(lvl, registers.get("bitwidths"))

        return num_pes, entries, bitwidths

    def _parse_node_local_buffer(self, lvl: Dict) -> Optional[Dict[str, int]]:
        """Parse optional local_buffer entries from NodeLevel.

        Returns None when the local_buffer key is absent (flat GB-to-PE arch).
        """
        local_buffer = lvl.get("local_buffer")
        if local_buffer is None:
            return None
        if not isinstance(local_buffer, dict):
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' local_buffer must be a "
                f"mapping in {self.path}"
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
