"""SpinalFlow MAC cycle count: one spike event = one cycle.

SpinalFlow's PE array processes exactly one spine entry per cycle -- the
reconstruction in reconstruct.py already flattened time and dropped
non-spikes, so cycle count is simply the reconstructed event count.
"""

from __future__ import annotations

from typing import List, Tuple

from .. import NodeTileSpec


def event_to_cycle(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> int:
    return len(events)
