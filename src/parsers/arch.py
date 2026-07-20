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

PE-parallel spatial fanout always lives at NodeLevel (level 0), regardless
of whether local_buffer is present -- it's expressed via
node_dim_capacity's {spatial: N} form (see SNNArch.node_dim_capacity),
not a separate pe.spatial_split key.

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
      node_dim_capacity:      # OPTIONAL — complete NodeLevel dimension spec
        KH: 4                 # temporal cap: fill as much as fits, <= 4
        T: null                # temporal: forced fully resident
        COUT: {spatial: 128}  # spatial fanout, pinned to exactly 128
                               # (HO/WO absent here -> barred from NodeLevel)
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

# Valid problem dimension names for node_dim_capacity validation
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
                                 index 1 = NoCLevel global-buffer entries
                                 (None when absent -- no capacity check for
                                 that level). OffChip is unbounded and not
                                 stored here.
        has_local_buffer (bool): True when NodeLevel defines a local_buffer.
        has_noc_buffer (bool):   True when NoCLevel defines entries.
        node_pe_num_pes (int):   PEs per node.
        node_pe_register_entries (Optional[Dict[str,int]]): Per-PE register
                                 bytes. None when pe.registers is absent.
                                 Metadata only -- not read by any constraint,
                                 objective, or nocsim code.
        node_pe_register_bitwidths (Optional[Dict[str,int]]): Per-PE
                                 register bit-widths. None when pe.registers
                                 is absent. Metadata only, same as above.
        node_pe_spatial_split (Optional[Dict[str,int]]): Genuine PE-parallel
                                 spatial fanout {dim_name: factor}, derived
                                 from node_dim_capacity's {spatial: N}
                                 entries (not a separate config key). None
                                 when no dim uses that form. Product of
                                 factors <= num_pes is validated at parse
                                 time (V1). Enforced by
                                 model/constraints/node_level.py.
        node_local_buffer_entries (Optional[Dict[str,int]]): Per-node L1 spad
                                 bytes. None when local_buffer is absent.
        mem_instances (List[int]): Instance count for all three levels
                                   [NodeLevel, NoCLevel, OffChip].
        mem_idx (Dict[str,int]): Level name -> index (0=NodeLevel … 2=OffChip).
        mem_name (Dict[int,str]): Index -> level name.
        single_node (bool): Hardware topology flag -- True means no Global
                                 Buffer exists, so nocsim/combine.py collapses
                                 every DRAM<->GB<->node leg into a direct
                                 DRAM<->node transfer. Independent of how the
                                 schedule itself is produced (always the MIP
                                 solver; see node_dim_capacity below).
        node_dim_capacity (Optional[Dict[str, object]]): Complete
                                 per-dimension NodeLevel (level 0) spec,
                                 four-way per dim:
                                   - int size:  temporal resident factor
                                                product at level 0 may not
                                                exceed size (MIP fills as
                                                much as fits).
                                   - None:      dimension forced entirely
                                                resident at level 0,
                                                temporal.
                                   - {"spatial": N}: genuine PE-parallel
                                                spatial fanout, pinned to
                                                exactly N -- see
                                                node_pe_spatial_split above,
                                                which is derived from these
                                                entries. Kept here too,
                                                purely for documentation of
                                                the complete node dimension
                                                set (model/constraints/
                                                node_capacity.py skips these
                                                dims entirely).
                                   - dim absent from the mapping: the
                                                dimension is barred from
                                                level 0 entirely (zero
                                                factors of it may be
                                                assigned there) -- e.g. HO/WO
                                                never appear in SpinalFlow's
                                                node level.
                                 None (the whole attribute, not a per-dim
                                 value) when arch.node_dim_capacity is absent
                                 from the YAML entirely -- in that case the
                                 feature is unused and NodeLevel is fully
                                 unconstrained (today's default, backward
                                 compatible). Enforced by
                                 model/constraints/node_capacity.py.
        S (List[int]):           Inter-level spatial fanout.
                                 S[i] = mem_instances[i] // mem_instances[i+1].
                                 S[1] is the NoCLevel inter-node fanout.
                                 S[0] is always 1 (self-ratio) and is NOT used
                                 for NodeLevel spatial; use node_pe_num_pes
                                 instead (see model/constraints/spatial.py).
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

        # single_node: pure hardware-topology flag, consumed by
        # nocsim/combine.py to skip the GB leg (direct DRAM<->node
        # transfers). Does not affect schedule generation.
        self.single_node: bool = bool(arch.get("single_node", False))
        self.node_dim_capacity: Optional[Dict[str, object]]
        self.node_pe_spatial_split: Optional[Dict[str, int]]
        self.node_dim_capacity, self.node_pe_spatial_split = (
            self._parse_node_dim_capacity(arch, self.node_pe_num_pes)
        )

        logger.debug(
            "SNNArch loaded: instances=%s  has_local_buffer=%s  "
            "num_pes=%d  spatial_split=%s  S=%s  single_node=%s  "
            "node_dim_capacity=%s",
            self.mem_instances, self.has_local_buffer,
            self.node_pe_num_pes, self.node_pe_spatial_split, self.S,
            self.single_node, self.node_dim_capacity,
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

    def _validate_spatial_split(
        self, raw_split: Dict[str, int], num_pes: int
    ) -> Dict[str, int]:
        """Run V1 validation (product of factors <= num_pes) on a spatial split.

        raw_split is already known to have valid dim names and positive
        int factors -- extracted from node_dim_capacity's {spatial: N}
        entries by the caller, so only the cross-dimension product check
        remains to do here.
        """
        product = 1
        for factor in raw_split.values():
            product *= factor
        if product > num_pes:
            raise ValueError(
                f"SNNArch: node_dim_capacity spatial-tagged entries "
                f"product={product} exceeds num_pes={num_pes} (V1 violation) "
                f"in {self.path}"
            )
        return raw_split

    def _parse_node_dim_capacity(
        self, arch: Dict, num_pes: int
    ) -> tuple[Optional[Dict[str, object]], Optional[Dict[str, int]]]:
        """Parse optional top-level arch.node_dim_capacity.

        Each entry is one of (see SNNArch docstring for full semantics):
          - int size:       temporal residency at NodeLevel (level 0) capped
                            at size; model/constraints/node_capacity.py lets
                            the MIP choose the split (fill as much as fits).
          - null:           dimension forced entirely resident at level 0,
                            temporal.
          - {spatial: N}:   genuine PE-parallel spatial fanout, pinned to
                            exactly N (validated against num_pes here -- V1).
                            Extracted into the returned spatial_split dict;
                            node_capacity.py skips these dims entirely
                            (enforced by add_pe_spatial_split_constraints
                            instead). Kept in the capacity dict too, in its
                            {spatial: N} form, purely for documentation.
        Any of the seven valid dimensions NOT present as a key is barred
        from level 0 entirely once this block is specified at all --
        node_capacity.py forces zero factors of it to level 0.

        Returns:
            (capacity, spatial_split) -- both None when arch.node_dim_capacity
            is absent from the YAML entirely (feature unused, NodeLevel fully
            unconstrained). spatial_split is None (not {}) when no entry uses
            the {spatial: N} form, matching the previous
            arch.node_pe_spatial_split contract.
        """
        raw = arch.get("node_dim_capacity")
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            raise ValueError(
                f"SNNArch: arch.node_dim_capacity must be a mapping of "
                f"{{dim_name: size|null|{{spatial: N}}}} in {self.path}"
            )
        capacity: Dict[str, object] = {}
        spatial_raw: Dict[str, int] = {}
        for dim_name, raw_value in raw.items():
            if dim_name not in _VALID_DIM_NAMES:
                raise ValueError(
                    f"SNNArch: arch.node_dim_capacity unknown dimension "
                    f"'{dim_name}' (valid: {_VALID_DIM_NAMES}) in {self.path}"
                )
            if raw_value is None:
                capacity[dim_name] = None
                continue
            if isinstance(raw_value, dict):
                keys = set(raw_value.keys())
                if keys != {"spatial"}:
                    raise ValueError(
                        f"SNNArch: arch.node_dim_capacity['{dim_name}'] dict "
                        f"form must have exactly key 'spatial', got "
                        f"{sorted(keys)} in {self.path}"
                    )
                factor = int(raw_value["spatial"])
                if factor <= 0:
                    raise ValueError(
                        f"SNNArch: arch.node_dim_capacity['{dim_name}']"
                        f"['spatial']={factor} must be positive in {self.path}"
                    )
                capacity[dim_name] = {"spatial": factor}
                spatial_raw[dim_name] = factor
                continue
            size = int(raw_value)
            if size <= 0:
                raise ValueError(
                    f"SNNArch: arch.node_dim_capacity['{dim_name}']={size} "
                    f"must be positive, null, or {{spatial: N}} in {self.path}"
                )
            capacity[dim_name] = size

        spatial_split = (
            self._validate_spatial_split(spatial_raw, num_pes)
            if spatial_raw else None
        )
        return capacity, spatial_split

    def _parse_node_pe(
        self, lvl: Dict
    ) -> tuple[int, Optional[Dict[str, int]], Optional[Dict[str, int]]]:
        """Parse pe.num_pes (required) and optional pe.registers.

        pe.registers is metadata only -- parsed and stored on SNNArch for
        potential future use (e.g. per-PE energy/area modeling), but not
        currently read by any constraint, objective, or nocsim code. It's
        optional so archs that don't need it aren't forced to invent numbers
        that affect nothing. Spatial fanout no longer lives under pe -- see
        node_dim_capacity's {spatial: N} form instead.
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
