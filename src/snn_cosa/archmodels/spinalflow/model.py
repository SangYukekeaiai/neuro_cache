"""SpinalFlowComputeModel: ArchComputeModel Protocol wrapper.

Wires SpinalFlow's already-verified reconstruct_tile_sequence/
event_to_cycle/event_to_address trio (reconstruct.py/cycles.py/
address.py) behind the ArchComputeModel Protocol so it can be passed to
combine()/run()/run_from_json() as a real per-tile cycle-count model. No
new per-arch algorithm here -- pure plumbing over what the SpinalFlow
pilot already verified standalone.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import reconstruct_tile_sequence


class SpinalFlowComputeModel(ArchComputeModel):
    def format_input(
        self, trace: np.ndarray, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int]]:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)