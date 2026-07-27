"""Python bridge to the compiled prosperitygen C++ binary (native/), a
port of reconstruct_tile_sequence_batch + _prosparsity_process +
event_to_address + event_to_ticks. See
src/archmodels/gustavsnn/native_bridge.py for the pattern this mirrors
(same wire-format shape, same slice-to-requested-samples fix for the OOM
found there 2026-07-26).
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
_BINARY = _HERE / "native" / "prosperitygen"


def _pack_task(trace_shape: Sequence[int], tiles: Sequence[NodeTileSpec], sample_indices: Sequence[int]) -> bytes:
    T, B_full, Cin_full, Hin_full, Win_full = trace_shape
    parts = [struct.pack("<5i", T, B_full, Cin_full, Hin_full, Win_full)]
    parts.append(struct.pack("<2i", len(tiles), len(sample_indices)))
    for tile in tiles:
        parts.append(struct.pack(
            "<11i",
            tile.dram_i,
            tile.tile_offset.get(DIM_HO, 0), tile.node_bound[DIM_HO],
            tile.tile_offset.get(DIM_WO, 0), tile.node_bound[DIM_WO],
            tile.node_bound[DIM_KH], tile.node_bound[DIM_KW],
            tile.tile_offset.get(DIM_CIN, 0),
            tile.tile_offset.get(DIM_T, 0),
            tile.tile_offset.get(DIM_COUT, 0), tile.node_bound[DIM_COUT],
        ))
    for s in sample_indices:
        parts.append(struct.pack("<i", s))
    return b"".join(parts)


def _unpack_output(data: bytes, num_tiles: int, sample_indices: Sequence[int]):
    off = 0
    n = len(data)
    for _tile_idx in range(num_tiles):
        for _s in sample_indices:
            tile_idx, sample_idx, mac_cycles, num_addr = struct.unpack_from("<4i", data, off)
            off += 16
            addresses = []
            ticks = []
            for _ in range(num_addr):
                kh, kw, cin, cout_start, cout_end, tick = struct.unpack_from("<6i", data, off)
                off += 24
                addresses.append((kh, kw, cin, cout_start, cout_end))
                ticks.append(tick)
            yield tile_idx, sample_idx, mac_cycles, addresses, ticks
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
    """Native-C++ equivalent of tracegen.reconstruct_samples_for_schedule,
    specialized to Prosperity. Same LayerWeightTrace output shape as the
    Python path. Requires native/prosperitygen to be built first
    (cd native && make)."""
    from tracegen import LayerWeightTrace, TileWeightTrace

    if not _BINARY.exists():
        raise FileNotFoundError(
            f"prosperitygen binary not found at {_BINARY} -- build it first: "
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

    num_samples = len(sample_indices)
    per_sample_tiles: List[List[Any]] = [[None] * len(tiles) for _ in range(num_samples)]

    for tile_idx, local_idx, mac_cycles, addresses, ticks in _unpack_output(out_data, len(tiles), local_indices):
        i = local_idx
        per_sample_tiles[i][tile_idx] = TileWeightTrace(
            dram_i=tiles[tile_idx].dram_i,
            mac_cycles=mac_cycles,
            lif_cycles=None,
            weight_addresses=addresses,
            tick_ids=ticks,
        )

    return [
        LayerWeightTrace(
            arch=arch_name,
            trace_dir=trace_dir_name,
            layer_name=layer_name,
            sample_idx=sample_idx,
            workload_dims=workload_dims,
            dram_num_steps=dram_num_steps,
            tiles=per_sample_tiles[i],
        )
        for i, sample_idx in enumerate(sample_indices)
    ]
