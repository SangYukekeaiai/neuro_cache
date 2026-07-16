"""GustavSNNComputeModel: ArchComputeModel Protocol wrapper.

Wires GustavSNN's already-verified reconstruct_tile_sequence/
event_to_cycle/event_to_address trio behind the ArchComputeModel
Protocol. No new per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import GustavReconstructed, reconstruct_tile_sequence


class GustavSNNComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> GustavReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)