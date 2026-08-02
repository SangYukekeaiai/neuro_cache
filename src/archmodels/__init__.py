"""ArchComputeModel: pluggable, trace-driven per-node cycle counts.

Replaces combine.py's static dense-tile formula with an architecture-
specific model that derives MAC/LIF cycle counts (and, for a real trace-
driven model, the weight addresses touched) from an actual spike trace.

NodeTileSpec identifies which slice of a real trace one node-level tile
covers, using the same dimension indices as parsers.layer
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
from typing import Any, Dict, List, Optional, Protocol, Sequence

# Canonical arch registry: arch name -> the module holding its
# reconstruct_samples_native entry point. The compiled C++ binary reached
# through that bridge is the only reconstruction path; the superseded
# pure-Python compute modules now live in dump/python_reference/. Module
# path strings, not imports, so this module stays free of arch imports.
ARCH_NATIVE_BRIDGES = {
    "loas": "archmodels.loas.native_bridge",
    "spinalflow": "archmodels.spinalflow.native_bridge",
    "ptb": "archmodels.ptb.native_bridge",
    "gustavsnn": "archmodels.gustavsnn.native_bridge",
    "prosperity": "archmodels.prosperity.native_bridge",
}


@dataclass(frozen=True)
class NodeTileSpec:
    dram_i: int
    node_bound: Dict[int, int]
    tile_offset: Dict[int, int]
    is_last_K: bool


@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: Optional[int] = None
    """None means this architecture has no meaningful split between MAC
    and LIF cycles -- mac_cycles just holds the tile's total_cycle_count.
    This is the general case for single-node/pipelined architectures where
    MAC and LIF work are interleaved per PE rather than separated along a
    schedule-level VAR_VMEM dimension (e.g. PTB, see archmodels/ptb/).
    combine.py treats None as contributing 0 additional LIF-transaction
    cycles."""


class ArchComputeModel(Protocol):
    """Per-architecture plugin, called once per node-level tile."""

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        """Slice/reconstruct this tile's real-trace-derived representation."""
        ...

    def format_input_batch(self, trace: Any, tile: NodeTileSpec, batch_indices: Sequence[int]) -> List[Any]:
        """Same as format_input, for every sample in batch_indices at once
        (one vectorized reconstruction pass instead of len(batch_indices)
        separate format_input calls). output[i] corresponds to
        batch_indices[i]."""
        ...

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        """Derive this tile's (mac_cycles, lif_cycles) from format_input's output."""
        ...

    def weight_addresses(self, packed: Any, tile: NodeTileSpec) -> List[Any]:
        """Ordered weight addresses this tile touches (this arch's own
        address.py::event_to_address, wrapped). Not consumed by combine.py's
        transaction generator (which still uses byte-size accounting) --
        exists so the locality analyzer has one per-arch entry point for
        both timing and addressing, instead of reaching around the
        Protocol into each arch's raw address.py function.
        """
        ...

    def weight_ticks(self, packed: Any, tile: NodeTileSpec) -> List[int]:
        """Per-tile-local cycle index (0-based, restarting at 0 for every
        tile) at which each corresponding entry of weight_addresses(...)
        was fetched -- same length and order as weight_addresses(...), so
        callers zip the two to know which addresses shared a cycle.

        For every architecture except GustavSNN, weight fetches are
        strictly one per cycle by construction of that architecture's own
        compute_cycles model (LoAS/PTB: one burst per surviving reduction-
        index row, already covering the full T range per burst;
        SpinalFlow/Prosperity: one event/residual-bit per cycle), so this
        is just range(len(weight_addresses(packed, tile))). GustavSNN is
        the one case with genuine same-cycle parallelism: up to
        PE_COUNT_MAX submatrices each advance their own line pointer every
        cycle, so multiple addresses can share a tick -- see
        gustavsnn/address.py.
        """
        ...
