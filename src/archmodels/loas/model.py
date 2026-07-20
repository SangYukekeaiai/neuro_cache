"""LoASComputeModel: ArchComputeModel Protocol wrapper.

Wires LoAS's already-verified reconstruct_tile_sequence/event_to_cycle/
event_to_address trio behind the ArchComputeModel Protocol. No new
per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import (
    LoASReconstructed,
    reconstruct_tile_sequence,
    reconstruct_tile_sequence_batch,
)


class LoASComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> LoASReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def format_input_batch(
        self, trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
    ) -> List[LoASReconstructed]:
        return reconstruct_tile_sequence_batch(trace, tile, batch_indices)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)