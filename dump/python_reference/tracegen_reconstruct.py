"""Superseded pure-Python reconstruction/read path from tracegen.py.

Every arch now reconstructs samples through its native C++ bridge
(archmodels.<arch>.native_bridge.reconstruct_samples_native, dispatched via
tracegen.reconstruct_samples), so reconstruct_samples_for_schedule and
reconstruct_tile_chunk below are dead in the live pipeline -- kept here only
as the reference implementation debug/04_diff_reconstruction.py diffs the
native output against. load_weight_trace and iter_generated_traces are kept
alongside them for the same reason other archived modules keep their
read-side helpers together (dump/python_reference/cachesim/sweep.py's own
`from tracegen import load_weight_trace`); nothing in the live pipeline
reads a persisted weight trace back through them (see
src/cachesim/native_bridge.py, which reads the raw JSON directly instead,
same as this module's own callers historically did).
"""

from __future__ import annotations

import gzip
import json
import pathlib
from typing import Any, Dict, Iterator, List, Sequence, Tuple

from archmodels import ArchComputeModel, NodeTileSpec
from tracegen import LayerWeightTrace, TileWeightTrace


def reconstruct_samples_for_schedule(
    model: ArchComputeModel,
    trace: Any,
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    arch_name: str,
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
) -> List[LayerWeightTrace]:
    """One LayerWeightTrace per requested sample. Calls format_input_batch
    once per tile (reconstructing every requested sample in one vectorized
    pass) instead of format_input once per (tile, sample) -- this is
    exactly the win each arch's reconstruct_tile_sequence_batch was built
    for; calling this with sample_indices=[0] reproduces exactly what
    sweep_archmodel_layers.py's own inline loop already computes.
    """
    num_samples = len(sample_indices)
    per_sample_tiles: List[List[TileWeightTrace]] = [[] for _ in range(num_samples)]
    for tile in tiles:
        packed_per_sample = model.format_input_batch(trace, tile, sample_indices)
        for i, packed in enumerate(packed_per_sample):
            cycles = model.compute_cycles(packed, tile)
            addresses = model.weight_addresses(packed, tile)
            ticks = model.weight_ticks(packed, tile)
            per_sample_tiles[i].append(
                TileWeightTrace(
                    dram_i=tile.dram_i,
                    mac_cycles=cycles.mac_cycles,
                    lif_cycles=cycles.lif_cycles,
                    weight_addresses=list(addresses),
                    tick_ids=list(ticks),
                )
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


def reconstruct_tile_chunk(
    model: ArchComputeModel,
    trace: Any,
    tile_chunk: Sequence[Tuple[int, NodeTileSpec]],
    sample_indices: Sequence[int],
) -> List[Tuple[int, List[TileWeightTrace]]]:
    """Experimental alternate axis for reconstruct_samples_for_schedule's
    work: given a SUBSET of (original_tile_index, tile) pairs, compute
    every requested sample's TileWeightTrace for just those tiles --
    format_input_batch still vectorizes across the FULL sample_indices
    batch per tile (unchanged), but now the multiprocessing split is
    along tiles instead of samples. Returns one (original_tile_index,
    [TileWeightTrace per sample, in sample_indices order]) pair per tile
    in tile_chunk, so a caller can scatter these back into per-sample
    tile lists at the tiles' original positions and reproduce exactly
    what reconstruct_samples_for_schedule would have produced.

    Motivation: GustavSNN bars T from node-level residency (see
    archmodels/gustavsnn/reconstruct.py's module docstring), so its
    `tiles` list has one entry per tick -- up to ~8000 entries observed
    on real resnet19 layers, vs. a few thousand at most for the other
    archs. reconstruct_samples_for_schedule's `for tile in tiles:` loop
    (this module, above) then reruns that same multi-thousand-iteration
    Python loop once per worker process when samples are chunked across
    workers, since sample-chunking leaves the tiles list untouched inside
    each worker. Chunking tiles instead means each tile's loop iteration
    (and its format_input_batch call) happens exactly once, total, no
    matter how many workers are used.
    """
    out: List[Tuple[int, List[TileWeightTrace]]] = []
    for orig_idx, tile in tile_chunk:
        packed_per_sample = model.format_input_batch(trace, tile, sample_indices)
        per_sample: List[TileWeightTrace] = []
        for packed in packed_per_sample:
            cycles = model.compute_cycles(packed, tile)
            addresses = model.weight_addresses(packed, tile)
            ticks = model.weight_ticks(packed, tile)
            per_sample.append(
                TileWeightTrace(
                    dram_i=tile.dram_i,
                    mac_cycles=cycles.mac_cycles,
                    lif_cycles=cycles.lif_cycles,
                    weight_addresses=list(addresses),
                    tick_ids=list(ticks),
                )
            )
        out.append((orig_idx, per_sample))
    return out


def load_weight_trace(path: pathlib.Path) -> LayerWeightTrace:
    with gzip.open(path, "rt") as fh:
        data = json.load(fh)
    tiles = [
        TileWeightTrace(
            dram_i=t["dram_i"],
            mac_cycles=t["mac_cycles"],
            lif_cycles=t["lif_cycles"],
            # JSON has no tuple type -- addresses come back as lists;
            # restore tuples so callers can hash/set them (e.g. a future
            # locality analyzer counting distinct weight lines).
            weight_addresses=[tuple(a) if isinstance(a, list) else a for a in t["weight_addresses"]],
            tick_ids=t["tick_ids"],
        )
        for t in data["tiles"]
    ]
    data["tiles"] = tiles
    return LayerWeightTrace(**data)


def iter_generated_traces(root: pathlib.Path) -> Iterator[LayerWeightTrace]:
    """Yield every persisted LayerWeightTrace under root
    (outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/sample_*.json.gz),
    for future analysis consumers to load directly instead of recomputing."""
    for path in sorted(root.glob("*/*/*/sample_*.json.gz")):
        yield load_weight_trace(path)
