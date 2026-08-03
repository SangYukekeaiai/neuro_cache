"""Python bridge to the compiled gustavgen C++ binary, a port
of reconstruct_tile_sequence_batch + event_to_address + event_to_ticks
that replaces this project's own profiling finding: 94% of GustavSNN's
weight-trace generation time is pure Python object/tuple construction in
those three functions, not the numpy gather (see
log/2026-07-26-workflow-optimization-plan.md's "Speedup methodology").

Drop-in alternative to tracegen.reconstruct_samples_for_schedule for
GustavSNN specifically: same signature shape, same LayerWeightTrace
output, but does ONE subprocess call for the whole (schedule, sample
batch) instead of one Python format_input_batch call per tile -- see
main.cpp's task/output binary format docstring for the wire
format.
"""

from __future__ import annotations

import pathlib
import struct
import subprocess
import tempfile
from typing import Any, Dict, List, Sequence

import numpy as np

from parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec

_HERE = pathlib.Path(__file__).resolve().parent
_BINARY = _HERE / "gustavgen"


def _pack_task(trace_shape: Sequence[int], tiles: Sequence[NodeTileSpec], sample_indices: Sequence[int]) -> bytes:
    T, B_full, Cin_full, Hin_full, Win_full = trace_shape
    parts = [struct.pack("<5i", T, B_full, Cin_full, Hin_full, Win_full)]
    parts.append(struct.pack("<2i", len(tiles), len(sample_indices)))
    for tile in tiles:
        parts.append(struct.pack(
            "<12i",
            tile.dram_i,
            tile.tile_offset.get(DIM_T, 0),
            tile.tile_offset.get(DIM_HO, 0), tile.node_bound[DIM_HO],
            tile.tile_offset.get(DIM_WO, 0), tile.node_bound[DIM_WO],
            tile.node_bound[DIM_KH], tile.node_bound[DIM_KW],
            tile.tile_offset.get(DIM_CIN, 0), tile.node_bound[DIM_CIN],
            tile.tile_offset.get(DIM_COUT, 0), tile.node_bound[DIM_COUT],
        ))
    for s in sample_indices:
        parts.append(struct.pack("<i", s))
    return b"".join(parts)


def _unpack_output(data: bytes, num_tiles: int, sample_indices: Sequence[int]):
    """Parses the tick-grouped wire format gustavgen's main.cpp now writes
    (src/archmodels/tick_output.h): per (tile, sample), tick_value +
    num_addresses_at_tick pairs, addresses without a per-address tick field
    (the tick value is the group key). Yields ticks already in the
    [{"tick": j, "weight_addresses": [...]}] shape tracegen.assemble_layer_traces
    expects. GustavSNN is the one arch where a tick group can genuinely
    hold more than one address (real same-cycle parallelism, see main.cpp's
    own wave_start_of[i]+j tick assignment) -- write_tick_grouped already
    buckets correctly for that case, so no extra handling is needed here."""
    off = 0
    n = len(data)
    for _tile_idx in range(num_tiles):
        for _s in sample_indices:
            tile_idx, sample_idx, mac_cycles, num_ticks = struct.unpack_from("<4i", data, off)
            off += 16
            ticks = []
            for _ in range(num_ticks):
                tick_value, num_addr = struct.unpack_from("<2i", data, off)
                off += 8
                addresses = []
                for _ in range(num_addr):
                    kh, kw, cin, cout_start, cout_end = struct.unpack_from("<5i", data, off)
                    off += 20
                    addresses.append((kh, kw, cin, cout_start, cout_end))
                ticks.append({"tick": tick_value, "weight_addresses": addresses})
            yield tile_idx, sample_idx, mac_cycles, ticks
    assert off == n, f"gustavgen output: {off} bytes consumed, {n} in file (framing bug)"


def reconstruct_samples_native(
    trace: np.ndarray,
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    arch_name: str,
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
):
    """Native-C++ equivalent of tracegen.reconstruct_samples_for_schedule,
    specialized to GustavSNN. Returns the same List[LayerWeightTrace]
    shape so callers (generate_weight_traces_canonical100.py etc.) can
    swap this in without changing anything downstream of the call site.

    Requires gustavgen to be built first (make in this directory).

    `tiles` may span multiple (dram_i, noc_i, core_id) triples (multi-node)
    or just dram_i (single-node) -- one subprocess call handles the whole
    flat list either way (see loas/native_bridge.py's docstring for why).
    tracegen.assemble_layer_traces owns grouping the flat per-tile results
    back into (dram_i, noc_i)-keyed, cross-core-merged LayerWeightTraces.
    """
    # Imported here, not at module top, to avoid tracegen<->this module
    # import-order issues (tracegen imports archmodels.gustavsnn.model,
    # which does not import this bridge -- only callers that explicitly
    # want the native path do).
    from tracegen import assemble_layer_traces

    if not _BINARY.exists():
        raise FileNotFoundError(
            f"gustavgen binary not found at {_BINARY} -- build it first: "
            f"cd {_BINARY.parent} && make"
        )

    # Slice to just the requested samples before handing off -- the full
    # trace (all ~10,000 samples in the _all trace variants) is B_full's
    # worth of data regardless of how many samples this call actually
    # needs, and writing/loading that in full for every chunk (16 workers
    # concurrently) is what OOM-killed the first real run (2026-07-26):
    # each worker duplicated the entire multi-GB trace into a temp file
    # for what was usually a 10-sample chunk. C++ gets local indices
    # 0..N-1 into this slice; the true sample_idx only exists Python-side
    # (mapped back via sample_indices[local_idx] below).
    trace_slice = np.ascontiguousarray(trace[:, sample_indices], dtype=np.uint8)
    local_indices = list(range(len(sample_indices)))
    task_bytes = _pack_task(trace_slice.shape, tiles, local_indices)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        trace_path = tmp_path / "trace.bin"
        task_path = tmp_path / "task.bin"
        out_path = tmp_path / "out.bin"

        trace_path.write_bytes(trace_slice.tobytes())
        task_path.write_bytes(task_bytes)

        subprocess.run(
            [str(_BINARY), str(trace_path), str(task_path), str(out_path)],
            check=True,
        )
        out_data = out_path.read_bytes()

    unpacked = _unpack_output(out_data, len(tiles), local_indices)
    return assemble_layer_traces(
        tiles, sample_indices, unpacked,
        arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps,
    )
