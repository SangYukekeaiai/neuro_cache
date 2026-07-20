"""SpinalFlow cycle count: max of the weight-access pipeline and the
compute pipeline, over the reconstructed spike-event "spine".

Mirrors PTB's archmodels/ptb/cycles.py structure:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

For SpinalFlow both pipelines are driven by the exact same quantity --
the reconstructed event count -- so access_cycle_count ==
compute_cycle_count == len(events) always; there is no dominance case to
distinguish here (unlike PTB, where stSAP's two-pass compression makes
the two counts genuinely diverge).

access_cycle_count -- one weight burst per spike event (see address.py):
event_to_address emits exactly one (kh, kw, cin, cout_start, cout_end)
burst per event, so the weight-fetch pipeline takes len(events) cycles.

compute_cycle_count -- SpinalFlow's PE array processes exactly one spine
entry per cycle -- the reconstruction in reconstruct.py already flattened
time and dropped non-spikes, so this is also len(events).

This is a single end-to-end cycle count with no separable LIF component
-- a future SpinalFlowComputeModel implementing the ArchComputeModel
Protocol would report ComputeCycles(mac_cycles=event_to_cycle(...),
lif_cycles=None), the same convention PTB uses (see
archmodels/__init__.py's ComputeCycles.lif_cycles=None docstring).
"""

from __future__ import annotations

from typing import List, Tuple

from .. import NodeTileSpec


def access_cycle_count(events: List[Tuple[int, int, int, int]]) -> int:
    return len(events)


def compute_cycle_count(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> int:
    return len(events)


def event_to_cycle(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> int:
    return max(access_cycle_count(events), compute_cycle_count(events, tile))
