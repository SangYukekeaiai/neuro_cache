"""PTB cycle count: max of the weight-access pipeline and the compute
pipeline, over stSAP-compressed lines.

A tile isn't done until BOTH pipelines are done, so:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

access_cycle_count -- the weight-fetch pipeline issues one burst per
cycle, one per stSAP Pass-1 line (see reconstruct.py; same count as
address.py's weight_access_count). No systolic propagation delay: this is
a flat sequential fetch count.

compute_cycle_count -- PTB's PE array is up to PE_ROWS_MAX rows (one row
per output/COUT neuron) by up to PE_COLS_MAX columns (one column per
active time window). Symmetric to columns: `active_rows` is the tile's
actual resident COUT count, clamped to PE_ROWS_MAX -- if a node-level
tile's COUT is less than the hardware's 16 rows (e.g. a layer with only 8
output channels), only `active_rows` rows are ever driven, and the
pipeline only needs to fill/drain through those, not all 16. Lines (after
stSAP Pass-2 merge) feed into the array one per cycle; the array is a
systolic pipeline, so a line issued at cycle `i` reaches PE-array row `r`,
column `c` at cycle `i + r + c`. Two things bound this pipeline's total
run time:
  1) the membrane-potential update chain across all `total_T` timesteps of
     this tile is inherently serial (vmem[t] depends on vmem[t-1]), so the
     array can't finish before `ln + active_rows + total_T`;
  2) the pipeline itself must fully drain through the last active row and
     column, which takes `ln + active_rows + active_cols +
     last_col_timesteps`.
  compute_cycle_count is the max of these two.

This is a single end-to-end cycle count covering both integration (MAC)
and membrane-potential/spike-generation (LIF) work -- PTB's pipeline
interleaves them per PE, so they are not modeled as two separable numbers
(see archmodels/__init__.py's ComputeCycles.lif_cycles=None convention
for architectures like this one).
"""

from __future__ import annotations

from snn_cosa.parsers.layer import DIM_COUT, DIM_T

from .. import NodeTileSpec
from .reconstruct import PTBReconstructed

TW_SIZE = 8       # time points packed per time window (this PTB config)
PE_ROWS_MAX = 16  # PE-array row count = max distinct COUT rows (this config)
PE_COLS_MAX = 8   # max active time-window columns (16x8 array, this config)


def access_cycle_count(reconstructed: PTBReconstructed) -> int:
    return len(reconstructed.lines_pass1)


def compute_cycle_count(reconstructed: PTBReconstructed, tile: NodeTileSpec) -> int:
    ln = len(reconstructed.lines_pass2)
    active_rows = min(tile.node_bound[DIM_COUT], PE_ROWS_MAX)
    total_t = tile.node_bound[DIM_T]

    active_cols = min(-(-total_t // TW_SIZE), PE_COLS_MAX)  # ceil division
    last_col_timesteps = total_t - TW_SIZE * (active_cols - 1)

    full_total = ln + active_rows + total_t
    active_drain = ln + active_rows + active_cols + last_col_timesteps
    return max(full_total, active_drain)


def event_to_cycle(reconstructed: PTBReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
