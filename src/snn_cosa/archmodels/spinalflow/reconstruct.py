"""Builds SpinalFlow's per-tile spike sequence from a real spike trace.

SpinalFlow packs a tile's receptive field into a "spine": every neuron
that actually spiked in this tile's (t, kh, kw, cin) window, in
chronological order (t outermost). Unlike a dense 0/1 vector, only real
spike events are kept -- this is the input to event_to_cycle (cycle count
= spine length) and event_to_address (one weight burst per spine event).

Assumes batch=0, stride=1, "same" padding (hin = ho + kh - pad_h, win =
wo + kw - pad_w, where pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- the
standard convention for an odd kernel, matching HO=Hin/WO=Win exactly).
An (hin, win) that falls outside the real trace's spatial extent is
padding, not data -- treated as zero (no spike) by _spike() below, never
indexed out of bounds. (Originally "valid"/no-padding, hin=ho+kh; changed
by explicit user direction, 2026-07-16, since real VGG/ResNet 3x3 convs
use same-padding.) Matches the reference SpinalFlow tile-computation's
receptive-field shape (neuro_cache/sim/compute/spinalflow_compute.py's
_receptive_field), modulo this padding correction.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


def reconstruct_tile_sequence_batch(
    trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
) -> List[List[Tuple[int, int, int, int]]]:
    """Same spine reconstruction as reconstruct_tile_sequence, for every
    sample in batch_indices at once -- one vectorized gather over
    (T, KH, KW, CIN, batch) instead of len(batch_indices) separate
    Python-level nested loops. batch_indices may repeat/reorder freely;
    output[i] always corresponds to batch_indices[i].
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
    # Positions outside the real trace's spatial extent are padding (zero,
    # never a spike) -- same convention _spike() used to enforce one
    # element at a time. `valid` masks those positions out after the
    # gather below (clip first so the out-of-bounds index never touches
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
    # -> [batch, T, KH, KW, CIN]: flattening the last 4 axes in this order
    # (T slowest, CIN fastest) matches the original loop nesting exactly
    # (t outermost, then kh, then kw, then cin innermost).
    spikes = np.ascontiguousarray(gathered.transpose(1, 0, 3, 4, 2))
    non_silent = spikes != 0

    # nonzero on the full [batch,T,KH,KW,CIN] array, once, instead of once
    # per batch -- b_idx comes back sorted ascending (nonzero visits axis 0
    # slowest), so each batch's events occupy one contiguous slice, already
    # in t-chronological, then (kh,kw,cin), order.
    b_idx, t_idx, kh_idx, kw_idx, cin_idx = np.nonzero(non_silent)
    slice_bounds = np.searchsorted(b_idx, np.arange(len(batch_arr) + 1))
    abs_t = t_off + t_idx
    abs_cin = cin_off + cin_idx

    results: List[List[Tuple[int, int, int, int]]] = []
    for b in range(len(batch_arr)):
        start, end = slice_bounds[b], slice_bounds[b + 1]
        events = [
            (int(abs_t[j]), int(abs_cin[j]), int(kh_idx[j]), int(kw_idx[j]))
            for j in range(start, end)
        ]
        results.append(events)
    return results


def reconstruct_tile_sequence(
    trace: np.ndarray, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int]]:
    """Return this tile's spike events as (t, cin, kh, kw), t-chronological,
    for real captured sample 0. Thin wrapper over
    reconstruct_tile_sequence_batch so there is exactly one reconstruction
    implementation to trust.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel, node_bound[DIM_KH]/
               [DIM_KW] the receptive-field extent, node_bound[DIM_CIN]/
               [DIM_T] (with matching tile_offset, default 0) the
               input-channel and timestep range.
    """
    return reconstruct_tile_sequence_batch(trace, tile, [0])[0]
