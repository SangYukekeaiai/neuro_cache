#!/usr/bin/env python3
"""Step 3 – Parse the three-level SNN memory hierarchy from an arch YAML.

Expected memory levels (listed innermost → outermost in the YAML):

  NodeLevel   – per-node compute unit (highest instance count)
  NoCLevel    – on-chip shared buffer (one instance per chip)
  OffChip     – off-chip DRAM (one instance, unbounded capacity)

NodeLevel describes a two-level internal hierarchy:
  pe.registers  – per-PE register file (always required)
  local_buffer  – per-node L1 scratchpad (OPTIONAL)

When local_buffer is present the model has two spatial fanout levels:
  NoCLevel spatial : S[1] = instances // NoCLevel_instances  (inter-node)
  NodeLevel spatial: num_pes                                  (intra-node, Constraint B)

When local_buffer is absent PEs sit directly under the global buffer:
  NoCLevel spatial : num_pes  (GB feeds PEs directly)
  NodeLevel spatial: 1        (no sub-level)

Expected arch YAML format (local_buffer and spatial_split optional)::

    arch:
      bitwidths:
        BW_WEIGHT: 8
        BW_PSUM:   32
        BW_VMEM:   16
      storage:
        - name: NodeLevel
          instances: 128      # number of nodes; drives S[1]
          pe:
            num_pes: 128      # PEs per node; drives intra-node spatial budget
            spatial_split:    # OPTIONAL — pre-defined PE-level spatial split
              COUT: 4         # split COUT by 4 across PEs
            registers:
              entries:
                weight: 128
                psum:   128
                vmem:   256
              bitwidths:
                weight: 8
                psum:   16
                vmem:   32
          local_buffer:       # OPTIONAL — omit for flat GB-to-PE architecture
            entries:
              weight: 1024
              psum:   1024
              vmem:   2048
        - name: NoCLevel
          entries:
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

# Valid problem dimension names for spatial_split validation
_VALID_DIM_NAMES: List[str] = ["KH", "KW", "CIN", "COUT", "HO", "WO", "T"]

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

    Attributes:
        mem_levels (int):        Number of memory levels (always 3).
        mem_entries (List):      Per-variable capacity in bytes.
                                 Index 0 = NodeLevel local_buffer entries
                                 (None when local_buffer is absent);
                                 index 1 = NoCLevel global-buffer entries.
                                 OffChip is unbounded and not stored here.
        has_local_buffer (bool): True when NodeLevel defines a local_buffer.
        node_pe_num_pes (int):   PEs per node.
        node_pe_register_entries (Dict[str,int]): Per-PE register bytes.
        node_pe_register_bitwidths (Dict[str,int]): Per-PE register bit-widths.
        node_pe_spatial_split (Optional[Dict[str,int]]): Pre-defined PE-level
                                 spatial split {dim_name: factor}. None when
                                 not specified. Product of factors <= num_pes
                                 is validated at parse time (V1).
        node_local_buffer_entries (Optional[Dict[str,int]]): Per-node L1 spad
                                 bytes. None when local_buffer is absent.
        mem_instances (List[int]): Instance count for all three levels
                                   [NodeLevel, NoCLevel, OffChip].
        mem_idx (Dict[str,int]): Level name -> index (0=NodeLevel … 2=OffChip).
        mem_name (Dict[int,str]): Index -> level name.
        S (List[int]):           Inter-level spatial fanout.
                                 S[i] = mem_instances[i] // mem_instances[i+1].
                                 S[1] is the NoCLevel inter-node fanout.
                                 S[0] is always 1 (self-ratio) and is NOT used
                                 for NodeLevel spatial; use node_pe_num_pes or
                                 has_local_buffer logic in spatial.py instead.
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
        noc_level  = storage[MEM_NOC]

        (
            self.node_pe_num_pes,
            self.node_pe_register_entries,
            self.node_pe_register_bitwidths,
            self.node_pe_spatial_split,
        ) = self._parse_node_pe(node_level)

        self.node_local_buffer_entries: Optional[Dict[str, int]] = (
            self._parse_node_local_buffer(node_level)
        )

        # Index 0 = NodeLevel (None when no local_buffer), index 1 = NoCLevel.
        self.mem_entries: List[Optional[Dict[str, int]]] = [
            self.node_local_buffer_entries,
            self._parse_entries(noc_level, "entries"),
        ]

        # S[i] = instances[i] // instances[i+1]  (inter-level fanout only).
        # S[0] is always 1; NodeLevel spatial uses node_pe_num_pes directly.
        self.S: List[int] = self._gen_spatial_constraints()

        logger.debug(
            "SNNArch loaded: instances=%s  has_local_buffer=%s  "
            "num_pes=%d  spatial_split=%s  S=%s",
            self.mem_instances, self.has_local_buffer,
            self.node_pe_num_pes, self.node_pe_spatial_split, self.S,
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def has_local_buffer(self) -> bool:
        """True when NodeLevel defines a local_buffer (L1 spad)."""
        return self.node_local_buffer_entries is not None

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

    def _parse_spatial_split(
        self, pe: Dict, num_pes: int
    ) -> Optional[Dict[str, int]]:
        """Parse optional pe.spatial_split and run V1 validation.

        V1: product of all split factors must not exceed num_pes.
        """
        raw_split = pe.get("spatial_split")
        if raw_split is None:
            return None
        if not isinstance(raw_split, dict):
            raise ValueError(
                f"SNNArch: pe.spatial_split must be a mapping of "
                f"{{dim_name: factor}} in {self.path}"
            )

        split: Dict[str, int] = {}
        product = 1
        for dim_name, raw_factor in raw_split.items():
            if dim_name not in _VALID_DIM_NAMES:
                raise ValueError(
                    f"SNNArch: pe.spatial_split unknown dimension '{dim_name}' "
                    f"(valid: {_VALID_DIM_NAMES}) in {self.path}"
                )
            factor = int(raw_factor)
            if factor <= 0:
                raise ValueError(
                    f"SNNArch: pe.spatial_split['{dim_name}']={factor} "
                    f"must be positive in {self.path}"
                )
            split[dim_name] = factor
            product *= factor

        if product > num_pes:
            raise ValueError(
                f"SNNArch: pe.spatial_split product={product} exceeds "
                f"num_pes={num_pes} (V1 violation) in {self.path}"
            )

        return split

    def _parse_node_pe(
        self, lvl: Dict
    ) -> tuple[int, Dict[str, int], Dict[str, int], Optional[Dict[str, int]]]:
        """Parse PE-register metadata and optional spatial_split from NodeLevel."""
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
        if not isinstance(registers, dict):
            raise ValueError(
                f"SNNArch: level '{lvl['name']}' must define pe.registers "
                f"in {self.path}"
            )

        entries_holder = {"name": lvl["name"], "entries": registers.get("entries")}
        entries   = self._parse_entries(entries_holder, "entries")
        bitwidths = self._parse_bitwidths(lvl, registers.get("bitwidths"))
        spatial_split = self._parse_spatial_split(pe, num_pes)

        return num_pes, entries, bitwidths, spatial_split

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
