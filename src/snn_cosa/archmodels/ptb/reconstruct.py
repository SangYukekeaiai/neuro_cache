"""Builds PTB's per-tile line sequence from a real spike trace, with
stSAP compression.

PTB packs a tile's receptive field into "lines": one length-T bit-vector
per (kh, kw, cin) reduction index, in [KH, KW, CIN] nested order -- one
line is fed into the PE array per cycle. stSAP (spatiotemporally-non-
overlapping spiking activity packing) then compresses these lines in two
passes:

  Pass 1 (silence removal): drop any line that never fires across its
  whole T range (a "silent" reduction index) -- spatial sparsity. Pass
  1's surviving line count is what actually touches the weight memory:
  event_to_address (address.py) emits exactly one weight burst per
  Pass-1 line.

  Pass 2 (adjacent non-overlap merge): scan the Pass-1 lines in order and
  greedily OR together each line with its immediate neighbor whenever
  their spikes never coincide at the same timestep (bitwise AND is all-
  zero) -- temporal sparsity, packing two lines into a single PE-array
  row-slot. Pass 2's group count (`ln`) is what determines the PE array's
  fill/drain latency: event_to_cycle (cycles.py) uses `ln`, NOT the
  Pass-1 count, because a merged pair still occupies only one row-slot
  even though it required two separate weight fetches.

Assumes batch=0, stride=1, "same" padding (hin = ho + kh - pad_h, win =
wo + kw - pad_w, pad_h=(kh_n-1)//2, pad_w=(kw_n-1)//2 -- HO=Hin/WO=Win
exactly). An (hin, win) outside the real trace's spatial extent is
padding, treated as zero (no spike) by _spike() below, matching
src/snn_cosa/archmodels/spinalflow/reconstruct.py's identical convention
(changed from no-padding by explicit user direction, 2026-07-16).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class PTBLine:
    """One (kh, kw, cin) reduction index's line: its length-T spike bit-vector.

    bits[i] is 1 if the input at receptive-field offset (kh, kw), input
    channel cin, fired at the i-th timestep of this tile's T range
    (absolute timestep tile_offset[DIM_T] + i), else 0 -- one bit per
    timestep, straight from the trace. This is exactly what stSAP's two
    passes test: Pass 1 drops a line where any(bits) is False (never
    fires anywhere in T); Pass 2 merges two adjacent lines if their bits
    never overlap (bitwise AND is all-zero at every timestep).
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class PTBReconstructed:
    lines_pass1: List[PTBLine]        # after silent-line removal
    lines_pass2: List[List[PTBLine]]  # after adjacent non-overlap merge; each group has 1 or 2 lines


def reconstruct_tile_sequence_batch(
    trace: np.ndarray, tile: NodeTileSpec, batch_indices: Sequence[int]
) -> List[PTBReconstructed]:
    """Same stSAP-compressed reconstruction as reconstruct_tile_sequence,
    for every sample in batch_indices at once. Pass 1 (silence removal)
    vectorizes exactly like LoAS's bitmask/lines. Pass 2 (adjacent merge)
    is inherently a sequential per-sample walk (whether line i merges
    depends on whether line i-1 already consumed it) -- that part stays a
    Python loop, but only over Pass 1's actual (sparse) survivor count,
    and the expensive per-pair bit-overlap check it consults is
    precomputed for every adjacent pair in one vectorized numpy op instead
    of being recomputed inside the loop.
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
    # -> [batch, KH, KW, CIN, T], matching the [KH,KW,CIN] nested order.
    spikes = np.ascontiguousarray(gathered.transpose(1, 3, 4, 2, 0)).astype(np.int64)
    non_silent = spikes.any(axis=-1)  # [batch, KH, KW, CIN]

    num_batch = len(batch_arr)
    # Pass 1, vectorized exactly like LoAS: one nonzero() call across every
    # batch's lines at once instead of once per batch, then one bulk
    # .tolist() instead of a per-element int() loop.
    b_idx, kh_idx, kw_idx, cin_idx = np.nonzero(non_silent)
    bits_all = spikes[b_idx, kh_idx, kw_idx, cin_idx].tolist()
    slice_bounds = np.searchsorted(b_idx, np.arange(num_batch + 1))

    results: List[PTBReconstructed] = []
    for b in range(num_batch):
        start, end = slice_bounds[b], slice_bounds[b + 1]
        lines_pass1 = [
            PTBLine(int(kh_idx[j]), int(kw_idx[j]), int(cin_off + cin_idx[j]), tuple(bits_all[j]))
            for j in range(start, end)
        ]

        # Precompute, for every adjacent pair in this sample's Pass-1 line
        # sequence, whether their spikes ever coincide -- one array op
        # instead of a per-pair zip/all() call inside the merge walk below.
        n_lines = len(lines_pass1)
        if n_lines > 1:
            bits_arr = np.asarray(bits_all[start:end])  # [n_lines, T]
            overlap = (bits_arr[:-1] != 0) & (bits_arr[1:] != 0)
            would_merge = ~overlap.any(axis=1)  # [n_lines - 1]
        else:
            would_merge = np.zeros(0, dtype=bool)

        # Pass 2: still a sequential greedy walk (merging line i consumes
        # i+1, so the decision at i depends on what happened at i-1), but
        # over Pass 1's real survivor count, not the full KH*KW*CIN grid,
        # and each step is just a would_merge[] lookup, not a bits comparison.
        lines_pass2: List[List[PTBLine]] = []
        i = 0
        while i < n_lines:
            if i < len(would_merge) and would_merge[i]:
                lines_pass2.append([lines_pass1[i], lines_pass1[i + 1]])
                i += 2
            else:
                lines_pass2.append([lines_pass1[i]])
                i += 1

        results.append(PTBReconstructed(lines_pass1=lines_pass1, lines_pass2=lines_pass2))
    return results


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> PTBReconstructed:
    """Return this tile's stSAP-compressed lines, in [KH, KW, CIN] order,
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
