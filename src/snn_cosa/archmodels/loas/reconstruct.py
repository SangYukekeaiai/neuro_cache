"""Builds LoAS's per-row compressed fiber (bitmask + pointer + packed
non-silent data) from a real spike trace.

LoAS compresses one output pixel's full reduction row (fixed m; k = every
(kh, kw, cin) reduction index, in [KH, KW, CIN] nested order) in the
paper's own two-part Fig. 8 format (Yin et al., MICRO 2024, Section IV-A):

  1. A ROW-LEVEL BITMASK, one bit per candidate k position (length
     KH*KW*CIN): 1 marks a "non-silent neuron" (fires at least once
     across the whole T range), 0 marks a "silent" one. Followed by a
     POINTER to the start of the packed non-zero data.
  2. The PACKED NON-ZERO DATA: for each non-silent k only, its own
     length-T spike bit-vector (e.g. "1001" for a 4-timestep neuron that
     spikes at t0 and t3, silent at t1/t2) -- silent k's are dropped
     entirely, contributing nothing here ("no silent neuron inside").

There is no further compression pass (unlike PTB's stSAP, which
additionally merges adjacent non-overlapping lines; LoAS has no such
merge step in this deployment).

ptr is always 0 in this standalone reconstruction: each call processes
exactly one row/fiber in isolation (one NodeTileSpec tile = one output
pixel's row), so its own pointer trivially points to the start of its own
packed segment. ptr would only become a meaningful non-zero offset once
multiple rows' compressed data share a single memory arena -- out of
scope for this per-tile pilot (see Global Constraints).

This deployment requires KH, KW, and CIN to be entirely resident at
NodeLevel (configs/arch/loas.yaml's `KH: null`/`KW: null`/`CIN: null`) --
the full reduction row must be visible at once to build one complete
fiber, matching the paper's row-wise compression unit.

Assumes batch=0, stride=1, "same" padding (hin = ho + kh - pad_h, win =
wo + kw - pad_w, pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- HO=Hin/WO=Win
exactly). An (hin, win) outside the real trace's spatial extent is
padding, treated as zero (no spike) by _spike() below, matching
src/snn_cosa/archmodels/{spinalflow,ptb}/reconstruct.py's identical
convention (changed from no-padding by explicit user direction,
2026-07-16).

cin_off/t_off (tile.tile_offset.get(DIM_CIN/DIM_T, 0)) are NOT about
supporting a nonzero offset in this deployment -- configs/arch/loas.yaml
forces CIN and T fully resident (null), so a real solved schedule never
splits either dimension across multiple node visits, and their entries
are simply ABSENT from tile_offset (there's only ever one visit, so no
offset needs tracking). `.get(dim, 0)` exists to avoid a KeyError on that
absence, not to handle a real nonzero value -- same convention as
SpinalFlow's reconstruct.py, which has the identical CIN/T:null setup.
Contrast with tile_offset[DIM_HO]/[DIM_WO] just below, accessed with
plain `[...]`: HO/WO are barred from NodeLevel entirely (always vary
across node visits), so their tile_offset entry is mandatory and a
missing key there is a genuine bug worth crashing on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class LoASLine:
    """One non-silent (kh, kw, cin) reduction index's packed spike data.

    bits[i] is 1 if this neuron fired at the i-th timestep of this tile's
    T range (absolute timestep tile_offset[DIM_T] + i), else 0 -- e.g.
    bits=(1,0,1,0) is the paper's "1010" packed value. Only non-silent
    lines (any(bits) is True) are ever constructed; LoASReconstructed's
    row-level bitmask records exactly which (kh, kw, cin) positions these
    correspond to.
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class LoASReconstructed:
    """This row's compressed fiber: row-level bitmask + pointer, plus the
    non-silent lines' packed data -- the paper's two-part Fig. 8 format
    (see module docstring).
    """

    bitmask: Tuple[int, ...]  # length KH*KW*CIN, [KH,KW,CIN] order; 1 = non-silent, 0 = silent
    ptr: int                  # start offset of the packed non-zero data; always 0 here (see module docstring)
    lines: List[LoASLine]     # non-silent lines only, same relative order as bitmask's set bits


def reconstruct_tile_sequence_batch(
    trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
) -> List[LoASReconstructed]:
    """Same fiber reconstruction as reconstruct_tile_sequence, for every
    sample in batch_indices at once.

    One tile's receptive field is reused identically across every real
    captured sample (batch doesn't participate in the schedule/tiling
    dims -- see build_workload_from_trace), so this replaces what would
    otherwise be len(batch_indices) separate Python-level nested loops
    over (KH, KW, CIN, T) with a single vectorized gather over
    (KH, KW, CIN, T, batch) -- the win scales with len(batch_indices).
    batch_indices may repeat or reorder freely; output[i] always
    corresponds to batch_indices[i].
    """
    ho = tile.tile_offset[DIM_HO]
    wo = tile.tile_offset[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    cin_n = tile.node_bound[DIM_CIN]
    cin_off = tile.tile_offset.get(DIM_CIN, 0)
    t_n = tile.node_bound[DIM_T]
    t_off = tile.tile_offset.get(DIM_T, 0)
    pad_h = (kh_n - 1) // 2
    pad_w = (kw_n - 1) // 2

    hin_full, win_full = trace.shape[3], trace.shape[4]
    hin_arr = ho + np.arange(kh_n) - pad_h
    win_arr = wo + np.arange(kw_n) - pad_w
    # Positions landing outside the real trace's spatial extent are padding
    # (zero, never a spike) -- same convention _spike() used to enforce one
    # element at a time. `valid` masks those positions out after the gather
    # below instead (clip first so the out-of-bounds index never touches
    # numpy's own fancy-indexing bounds check).
    valid = ((hin_arr >= 0) & (hin_arr < hin_full))[:, None] & (
        (win_arr >= 0) & (win_arr < win_full)
    )[None, :]
    hin_clipped = np.clip(hin_arr, 0, hin_full - 1)
    win_clipped = np.clip(win_arr, 0, win_full - 1)
    cin_arr = np.arange(cin_off, cin_off + cin_n)
    t_arr = np.arange(t_off, t_off + t_n)
    batch_arr = np.asarray(batch_indices)

    # trace: [T,B,Cin,Hin,Win] -> gathered: [T, batch, CIN, KH, KW]
    gathered = trace[np.ix_(t_arr, batch_arr, cin_arr, hin_clipped, win_clipped)]
    gathered = gathered * valid[None, None, None, :, :]
    # -> [batch, KH, KW, CIN, T], matching the bitmask's [KH,KW,CIN] nested
    # order (CIN fastest) once flattened per-sample below.
    spikes = np.ascontiguousarray(gathered.transpose(1, 3, 4, 2, 0)).astype(np.int64)
    non_silent = spikes.any(axis=-1)  # [batch, KH, KW, CIN]

    num_batch = len(batch_arr)
    # .tolist() converts a whole numpy array to nested Python ints/lists in
    # one C-level call -- doing this once per tile (not once per element per
    # batch) is what actually delivers the vectorization win; a per-batch
    # Python loop calling int() element-by-element here would just move the
    # original per-element Python overhead around instead of removing it.
    bitmask_all = non_silent.reshape(num_batch, -1).tolist()

    # nonzero on the full [batch,KH,KW,CIN] array, once, instead of once per
    # batch -- b_idx comes back sorted ascending (nonzero visits axis 0
    # slowest), so each batch's lines occupy one contiguous slice.
    b_idx, kh_idx, kw_idx, cin_idx = np.nonzero(non_silent)
    bits_all = spikes[b_idx, kh_idx, kw_idx, cin_idx].tolist()
    slice_bounds = np.searchsorted(b_idx, np.arange(num_batch + 1))

    results: List[LoASReconstructed] = []
    for b in range(num_batch):
        start, end = slice_bounds[b], slice_bounds[b + 1]
        lines = [
            LoASLine(int(kh_idx[j]), int(kw_idx[j]), int(cin_off + cin_idx[j]), tuple(bits_all[j]))
            for j in range(start, end)
        ]
        results.append(LoASReconstructed(bitmask=tuple(bitmask_all[b]), ptr=0, lines=lines))
    return results


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> LoASReconstructed:
    """Return this tile's (one row's) compressed fiber: bitmask + ptr + lines,
    for real captured sample 0. Thin wrapper over
    reconstruct_tile_sequence_batch so there is exactly one reconstruction
    implementation to trust.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel (this row), node_bound
               [DIM_KH]/[DIM_KW]/[DIM_CIN] the full reduction row (must
               be entirely resident -- see module docstring), node_bound
               [DIM_T]/tile_offset[DIM_T] (default 0) the timestep range.
    """
    return reconstruct_tile_sequence_batch(trace, tile, [0])[0]
