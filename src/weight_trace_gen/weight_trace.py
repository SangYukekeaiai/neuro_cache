"""The weight-trace data model and its assembly from native-bridge output.

LayerWeightTrace is built here (assemble_layer_traces, reconstruct_samples);
its cycle counts are written by nocsim.step_cycles and its addresses by
cachesim.stream.
"""

from __future__ import annotations

import importlib
import pathlib
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from weight_trace_gen import ARCH_NATIVE_BRIDGES, NodeTileSpec
from nocsim.schedule.decode import schedule_from_strategy
from nocsim.schedule.tiles import iter_node_tiles
from parsers.layer import SNNProb
from snn_scheduler.artifact import ScheduleArtifact, _prob_from_workload, read_artifact


def load_schedule(path: pathlib.Path) -> Tuple[ScheduleArtifact, SNNProb, List[NodeTileSpec]]:
    """Load a persisted ScheduleArtifact and rederive the (prob, tiles) it
    implies. schedule/tiles aren't themselves JSON-serializable, so they're
    rebuilt deterministically from the cached workload+result rather than
    (de)serialized directly -- iter_node_tiles is a pure function of
    (schedule, prob), so this reproduces the exact same tile list every
    time without re-solving anything."""
    artifact = read_artifact(path)
    prob = _prob_from_workload(artifact.workload)
    schedule = schedule_from_strategy(artifact.result["strategy"], prob)
    tiles = list(iter_node_tiles(schedule, prob))
    return artifact, prob, tiles


@dataclass
class CoreEntry:
    """One core's weight fetches at one tick, within one (dram_i, noc_i)
    tile. weight_addresses is that core's own raw bursted-event list for
    this tick only -- same [kh, kw, cin, cout_start, cout_end] shape as
    TileWeightTrace.weight_addresses, just scoped to one core/one tick.
    core_id decodes via nocsim.schedule.tiles.decode_core_id."""
    core_id: int
    weight_addresses: List[Any]


@dataclass
class TickEntry:
    """All cores' fetches at one tick, within one (dram_i, noc_i) tile. A
    core absent from `cores` had no fetch this tick (e.g. it finished its
    local work for the tile earlier) -- omitted, never padded with an
    empty CoreEntry."""
    tick: int
    cores: List[CoreEntry]


def merge_cores_by_tick(core_results: Dict[int, Dict[str, Any]]) -> List[TickEntry]:
    """Merge N cores' own per-tile results into one tile's tick-major
    ticks list -- the canonical on-disk order is dram_i -> noc_i -> tick ->
    core (core fastest-varying). See
    log/2026-08-02-multinode-core-driven-weight-trace-plan.md.

    core_results: {core_id: {"ticks": [{"tick": j, "weight_addresses": [...]}, ...]}},
    one entry per core that was active in this tile -- exactly what one
    per-core native-bridge call returns (already grouped by tick within
    that core's own data; see each arch's main.cpp). This function does
    only the cross-core merge, which is structurally Python's job: no
    single per-core native-bridge call has visibility into other cores'
    results, so nothing native could do this part.

    Raises nothing on an empty core_results -- returns [] (a tile with no
    active cores at all, e.g. num_cores=0, should never happen in practice
    but isn't this function's job to validate).
    """
    by_tick: Dict[int, List[CoreEntry]] = {}
    for core_id, result in core_results.items():
        for entry in result["ticks"]:
            by_tick.setdefault(entry["tick"], []).append(
                CoreEntry(core_id=core_id, weight_addresses=entry["weight_addresses"])
            )
    return [TickEntry(tick=t, cores=by_tick[t]) for t in sorted(by_tick)]


@dataclass
class TileWeightTrace:
    """One (dram_i, noc_i) tile's reconstructed weight fetches, tick-major
    (see log/2026-08-02-multinode-core-driven-weight-trace-plan.md).
    noc_i is always 0 and ticks always has exactly one core (core_id=0) for
    a single-node schedule -- the degenerate case of this same shape, not a
    separate format."""
    dram_i: int
    noc_i: int
    mac_cycles: int
    lif_cycles: Optional[int]
    ticks: List[TickEntry]


@dataclass
class LayerWeightTrace:
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    noc_num_steps: int
    tiles: List[TileWeightTrace]


def assemble_layer_traces(
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    unpacked: Iterable[Any],
    arch_name: str,
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
) -> List[LayerWeightTrace]:
    """Shared assembly step every arch's reconstruct_samples_native calls
    after its own native-binary invocation and per-arch unpacking. Groups
    per-(tile_idx, local_sample_idx) results by (dram_i, noc_i) across
    whichever core_ids `tiles` contains, merges cores via
    merge_cores_by_tick, and packages one LayerWeightTrace per sample.

    `unpacked` yields (tile_idx, local_sample_idx, mac_cycles, ticks) once
    per (tile, sample), sample-outer and tile-inner (the arch binaries'
    emission order; see the Phase D campaign plan, 10.4). This function
    keys everything off each record's own indices, so it is independent of
    that order -- `ticks` already in the
    [{"tick": j, "weight_addresses": [...]}] shape (every arch's native
    output already is that shape). `tiles[tile_idx]`
    supplies that entry's (dram_i, noc_i, core_id).
    """
    noc_num_steps = max((t.noc_i for t in tiles), default=0) + 1
    num_samples = len(sample_indices)
    # per sample: {(dram_i, noc_i): {core_id: {"mac_cycles": int, "ticks": [...]}}}
    groups: List[Dict[tuple, Dict[int, Dict[str, Any]]]] = [dict() for _ in range(num_samples)]

    for tile_idx, local_idx, mac_cycles, ticks in unpacked:
        spec = tiles[tile_idx]
        key = (spec.dram_i, spec.noc_i)
        groups[local_idx].setdefault(key, {})[spec.core_id] = {"mac_cycles": mac_cycles, "ticks": ticks}

    out = []
    for i, sample_idx in enumerate(sample_indices):
        tiles_out = []
        for dram_i, noc_i in sorted(groups[i]):
            core_results = groups[i][(dram_i, noc_i)]
            mac_cycles = max(r["mac_cycles"] for r in core_results.values())
            tiles_out.append(TileWeightTrace(
                dram_i=dram_i, noc_i=noc_i, mac_cycles=mac_cycles, lif_cycles=None,
                ticks=merge_cores_by_tick(core_results),
            ))
        out.append(LayerWeightTrace(
            arch=arch_name, trace_dir=trace_dir_name, layer_name=layer_name,
            sample_idx=sample_idx, workload_dims=workload_dims,
            dram_num_steps=dram_num_steps, noc_num_steps=noc_num_steps,
            tiles=tiles_out,
        ))
    return out


def reconstruct_samples(
    arch_name: str,
    trace: Any,
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
) -> List[LayerWeightTrace]:
    """One LayerWeightTrace per requested sample, dispatching to arch_name's
    native C++ bridge (weight_trace_gen.ARCH_NATIVE_BRIDGES). The single dispatch
    entry point for scripts/generate_weight_traces.py -- callers own the
    trace/worker-pool setup around this, this function owns only the
    dispatch. `trace` should already be loaded (e.g. via
    weight_trace_gen.trace.load_layer_trace(..., mmap=True)); this function
    doesn't load it itself so a caller running many samples across
    multiple workers can load it once per worker instead of once per call.
    """
    module_name = ARCH_NATIVE_BRIDGES.get(arch_name)
    if module_name is None:
        raise KeyError(
            f"no native bridge registered for arch '{arch_name}'; "
            f"known archs: {sorted(ARCH_NATIVE_BRIDGES)}"
        )
    native_fn = importlib.import_module(module_name).reconstruct_samples_native
    return native_fn(
        trace, tiles, sample_indices, arch_name, trace_dir_name, layer_name,
        workload_dims, dram_num_steps,
    )


_CANONICAL_N = 100
_CANONICAL_SEED = 0  # the seed configs/sampling/sample_indices.json was generated with


def sample_indices(n: int = 100, seed: int = 0, n_total: int = 10000) -> List[int]:
    """A fixed, reproducible n-sample subset of range(n_total), drawn live
    via random.Random -- no stored/hardcoded index list (replaces the now-
    deleted configs/sampling/sample_indices.json and the old
    canonical_sample_indices()/random_sample_indices() pair).

    `sample_indices()` (n=100, seed=0) is THE canonical 100-sample subset
    used everywhere a representative random sample (as opposed to the full
    10,000-sample sweep) is needed, so different callers never silently
    diverge onto their own random selections; verified to reproduce, byte
    for byte, the values previously hardcoded in that deleted JSON file.

    For n > 100, always a superset of that same canonical 100 (drawn at
    _CANONICAL_SEED regardless of `seed`) plus n-100 more drawn at `seed`
    from the remaining pool -- so growing n never discards
    already-generated work on the canonical 100 or on any smaller n at the
    same seed, matching every real n>100 call in this pipeline (e.g. the
    4000-sample sweep), which has always used seed=0 for both parts.

    Raises ValueError if n < 100."""
    base = sorted(random.Random(_CANONICAL_SEED).sample(range(n_total), _CANONICAL_N))
    if n < _CANONICAL_N:
        raise ValueError(f"sample_indices: n={n} smaller than the canonical {_CANONICAL_N}-sample base")
    if n == _CANONICAL_N:
        return base
    remaining_pool = [i for i in range(n_total) if i not in set(base)]
    extra = random.Random(seed).sample(remaining_pool, n - _CANONICAL_N)
    return sorted(base + extra)
