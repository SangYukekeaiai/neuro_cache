"""Python bridge to the compiled spinalflowgen C++ binary, a
port of reconstruct_tile_sequence_batch + event_to_address + event_to_ticks.
See src/archmodels/gustavsnn/native_bridge.py for the pattern this
mirrors (same wire-format shape, same slice-to-requested-samples fix for
the OOM found there 2026-07-26).
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
_BINARY = _HERE / "spinalflowgen"


def _pack_task(trace_shape: Sequence[int], tiles: Sequence[NodeTileSpec], sample_indices: Sequence[int]) -> bytes:
    T, B_full, Cin_full, Hin_full, Win_full = trace_shape
    parts = [struct.pack("<5i", T, B_full, Cin_full, Hin_full, Win_full)]
    parts.append(struct.pack("<2i", len(tiles), len(sample_indices)))
    for tile in tiles:
        parts.append(struct.pack(
            "<11i",
            tile.dram_i,
            tile.tile_offset[DIM_HO], tile.tile_offset[DIM_WO],
            tile.node_bound[DIM_KH], tile.node_bound[DIM_KW],
            tile.tile_offset.get(DIM_CIN, 0), tile.node_bound[DIM_CIN],
            tile.tile_offset.get(DIM_T, 0), tile.node_bound[DIM_T],
            tile.tile_offset.get(DIM_COUT, 0), tile.node_bound[DIM_COUT],
        ))
    for s in sample_indices:
        parts.append(struct.pack("<i", s))
    return b"".join(parts)


def _unpack_output(data: bytes, num_tiles: int, sample_indices: Sequence[int]):
    """Parses the tick-grouped wire format spinalflowgen's main.cpp now
    writes (src/archmodels/tick_output.h): per (tile, sample), tick_value +
    num_addresses_at_tick pairs, addresses without a per-address tick field
    (the tick value is the group key). Yields ticks already in the
    [{"tick": j, "weight_addresses": [...]}] shape tracegen.assemble_layer_traces
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
    assert off == n, f"spinalflowgen output: {off} bytes consumed, {n} in file (framing bug)"


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
    specialized to SpinalFlow. Same LayerWeightTrace output shape as the
    Python path. Requires spinalflowgen to be built first
    (make in this directory).

    `tiles` may span multiple (dram_i, noc_i, core_id) triples (multi-node)
    or just dram_i (single-node) -- one subprocess call handles the whole
    flat list either way (see loas/native_bridge.py's docstring for why).
    tracegen.assemble_layer_traces owns grouping the flat per-tile results
    back into (dram_i, noc_i)-keyed, cross-core-merged LayerWeightTraces."""
    from tracegen import assemble_layer_traces

    if not _BINARY.exists():
        raise FileNotFoundError(
            f"spinalflowgen binary not found at {_BINARY} -- build it first: "
            f"cd {_BINARY.parent} && make"
        )

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
