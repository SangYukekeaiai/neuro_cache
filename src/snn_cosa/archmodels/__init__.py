"""ArchComputeModel: pluggable, trace-driven per-node cycle counts.

Replaces combine.py's static dense-tile formula with an architecture-
specific model that derives MAC/LIF cycle counts (and, for a real trace-
driven model, the weight addresses touched) from an actual spike trace.

NodeTileSpec identifies which slice of a real trace one node-level tile
covers, using the same dimension indices as snn_cosa.parsers.layer
(DIM_KH, DIM_KW, DIM_CIN, DIM_COUT, DIM_HO, DIM_WO, DIM_T):

  node_bound[dim]  -- how many values of `dim` this tile spans
  tile_offset[dim] -- the starting index into the real trace for `dim`

The default model (archmodels.dense.DenseStaticComputeModel) ignores the
real trace and both NodeTileSpec fields entirely, returning the same
static value for every tile -- see its docstring. A real model (e.g.
archmodels.spinalflow) uses them to slice the trace and reconstruct that
tile's actual spike sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class NodeTileSpec:
    dram_i: int
    node_bound: Dict[int, int]
    tile_offset: Dict[int, int]
    is_last_K: bool


@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: int


class ArchComputeModel(Protocol):
    """Per-architecture plugin, called once per node-level tile."""

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        """Slice/reconstruct this tile's real-trace-derived representation."""
        ...

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        """Derive this tile's (mac_cycles, lif_cycles) from format_input's output."""
        ...
