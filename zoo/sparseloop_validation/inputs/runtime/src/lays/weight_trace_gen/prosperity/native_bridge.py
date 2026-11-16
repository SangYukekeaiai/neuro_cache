"""Python bridge to the compiled prosperitygen C++ binary.

The native kernel consumes one CIN per invocation; this bridge expands a
resident CIN tile into one invocation per CIN and concatenates those
independent walks. The trace is sliced to the requested samples before
packing. GustavSNN's task record carries a wave_width field; Prosperity keeps
its own task-record format.
"""

from __future__ import annotations

import pathlib
import struct
import subprocess
import tempfile
from dataclasses import replace
from typing import Any, Dict, List, Sequence

import numpy as np

from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec

_HERE = pathlib.Path(__file__).resolve().parent
_BINARY = _HERE / "prosperitygen"


def _pack_task(trace_shape: Sequence[int], tiles: Sequence[NodeTileSpec], sample_indices: Sequence[int]) -> bytes:
    T, B_full, Cin_full, Hin_full, Win_full = trace_shape
    parts = [struct.pack("<5i", T, B_full, Cin_full, Hin_full, Win_full)]
    parts.append(struct.pack("<2i", len(tiles), len(sample_indices)))
    for tile in tiles:
        parts.append(struct.pack(
            "<12i",
            tile.dram_i,
            tile.tile_offset.get(DIM_HO, 0), tile.node_bound[DIM_HO],
            tile.tile_offset.get(DIM_WO, 0), tile.node_bound[DIM_WO],
            tile.node_bound[DIM_KH], tile.node_bound[DIM_KW],
            tile.tile_offset.get(DIM_CIN, 0),
            tile.tile_offset.get(DIM_T, 0), tile.node_bound[DIM_T],
            tile.tile_offset.get(DIM_COUT, 0), tile.node_bound[DIM_COUT],
        ))
    for s in sample_indices:
        parts.append(struct.pack("<i", s))
    return b"".join(parts)


def _expand_cin_tiles(tiles: Sequence[NodeTileSpec]):
    """Make one native one-CIN tile for every resident CIN in each tile.

    Prosperity's compression prefix is meaningful only between rows for the
    same input channel: a prefix from another CIN would name different
    weights. The native kernel therefore remains one-CIN and the bridge
    concatenates one independent walk per resident channel below.
    """
    expanded = []
    origins = []
    for origin, tile in enumerate(tiles):
        cin_count = int(tile.node_bound.get(DIM_CIN, 1))
        cin_start = int(tile.tile_offset.get(DIM_CIN, 0))
        for cin_local in range(cin_count):
            node_bound = dict(tile.node_bound)
            node_bound[DIM_CIN] = 1
            tile_offset = dict(tile.tile_offset)
            tile_offset[DIM_CIN] = cin_start + cin_local
            expanded.append(replace(tile, node_bound=node_bound, tile_offset=tile_offset))
            origins.append(origin)
    return expanded, origins


def _combine_cin_results(unpacked, origins):
    """Concatenate each tile's independent CIN walks into one tile result."""
    combined = {}
    for expanded_idx, local_idx, mac_cycles, ticks in unpacked:
        origin = origins[expanded_idx]
        key = (origin, local_idx)
        state = combined.setdefault(key, {"mac_cycles": 0, "ticks": []})
        tick_offset = state["mac_cycles"]
        state["ticks"].extend(
            {
                "tick": entry["tick"] + tick_offset,
                "weight_addresses": entry["weight_addresses"],
            }
            for entry in ticks
        )
        state["mac_cycles"] += mac_cycles

    for (origin, local_idx), state in sorted(combined.items()):
        yield origin, local_idx, state["mac_cycles"], state["ticks"]


def _unpack_output(data: bytes, num_tiles: int, sample_indices: Sequence[int]):
    """Parses the tick-grouped wire format prosperitygen's main.cpp now
    writes (src/lays/weight_trace_gen/tick_output.h): per (tile, sample), tick_value +
    num_addresses_at_tick pairs, addresses without a per-address tick field
    (the tick value is the group key). Yields ticks already in the
    [{"tick": j, "weight_addresses": [...]}] shape lays.weight_trace_gen.weight_trace.assemble_layer_traces
    expects -- no further adaptation needed."""
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
    assert off == n, f"prosperitygen output: {off} bytes consumed, {n} in file (framing bug)"


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
    """Native-C++ Prosperity reconstruction with the same
    LayerWeightTrace output shape as the Python path. Requires prosperitygen
    to be built first
    (make in this directory).

    `tiles` may span multiple (dram_i, noc_i, core_id) triples (multi-node)
    or just dram_i (single-node) -- one subprocess call handles the whole
    flat list either way (see loas/native_bridge.py's docstring for why).
    lays.weight_trace_gen.weight_trace.assemble_layer_traces owns grouping the flat per-tile results
    back into (dram_i, noc_i)-keyed, cross-core-merged LayerWeightTraces."""
    from lays.weight_trace_gen.weight_trace import assemble_layer_traces

    if not _BINARY.exists():
        raise FileNotFoundError(
            f"prosperitygen binary not found at {_BINARY} -- build it first: "
            f"cd {_BINARY.parent} && make"
        )

    trace_slice = np.ascontiguousarray(trace[:, sample_indices], dtype=np.uint8)
    local_indices = list(range(len(sample_indices)))
    expanded_tiles, origins = _expand_cin_tiles(tiles)
    task_bytes = _pack_task(trace_slice.shape, expanded_tiles, local_indices)

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

    unpacked = _unpack_output(out_data, len(expanded_tiles), local_indices)
    return assemble_layer_traces(
        tiles, sample_indices, _combine_cin_results(unpacked, origins),
        arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps,
    )
