"""Shared solve/reconstruct/persist core for weight-trace generation.

Extracts what scripts/sweep_archmodel_layers.py used to do entirely
inline (solve -> iterate tiles -> format_input -> compute_cycles /
weight_addresses) into reusable pieces, so that script and the
generate-once pipeline (scripts/solve_schedules.py,
scripts/generate_weight_traces.py) share one implementation instead of
two copies that could quietly drift apart.

Two independent artifacts, matching the two-stage design
(dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md):

  ScheduleArtifact  -- one solved MIP schedule, persisted once per
                       (arch, trace_dir, layer). Reused across every
                       sample's reconstruction, since batch never
                       participates in the workload/tiling dimensions
                       (archmodels/trace.py's build_workload_from_trace
                       never reads B at all).
  LayerWeightTrace  -- one sample's per-tile weight-address stream +
                       cycle counts, persisted once per
                       (arch, trace_dir, layer, sample).
"""

from __future__ import annotations

import gzip
import importlib
import json
import os
import pathlib
import random
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from archmodels import ARCH_NATIVE_BRIDGES, NodeTileSpec
from archmodels.trace import build_workload_from_trace
from nocsim.schedule.decode import schedule_from_strategy
from nocsim.schedule.tiles import iter_node_tiles
from parsers.layer import SNNProb

# mip_solver is imported lazily, inside solve_and_cache_schedule only:
# mip_solver.solve pulls in gurobipy at module load, and everything else
# in this module (loading/reconstructing an already-cached schedule) has
# no need for Gurobi at all -- see dump/python_reference/cachesim/sweep.py's
# own deferred-import comment for the same reasoning applied elsewhere.

@dataclass
class ScheduleArtifact:
    """A solved schedule, persisted once per (arch, trace_dir, layer)."""

    arch: str
    trace_dir: str
    layer_name: str
    workload: Dict[str, Any]
    result: Dict[str, Any]  # raw solve_schedule() output (has_solution, strategy, ...)
    dram_num_steps: int
    mode: str = "base"  # winning TrafficMode's .value; default keeps old caches loadable


def _dump_workload_path(workload: Dict[str, Any]) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(workload, f)
        return f.name


def _prob_from_workload(workload: Dict[str, Any]) -> SNNProb:
    return SNNProb(pathlib.Path(_dump_workload_path(workload)))


def solve_and_cache_schedule(
    arch_name: str,
    arch_yaml: str,
    dataflow_yaml: str,
    trace_dir_name: str,
    layer_name: str,
    meta: Dict[str, Any],
    next_cin: Optional[int],
    cache_dir: pathlib.Path,
) -> ScheduleArtifact:
    """Solve one (arch, layer)'s schedule across every TrafficMode, keep the
    winner by the same score sweep_weights.py/run_full_sweep.py use
    (w_u*util_sum + w_tr*tr_sum + w_dl*delay, lower is better), and persist
    it to cache_dir/<arch>/<trace_dir>/<layer_name>.json. Always re-solves --
    callers wanting skip-existing behavior should check for that file
    themselves first, matching every other skip-existing check in this
    pipeline (see generate_weight_traces.py).

    BASE is always feasible (unconstrained) but is not special-cased --
    across all 155 real (arch, layer) pairs in this project's own trace
    data, BASE never actually wins (verified 2026-07-19): every other
    TrafficMode either is infeasible for these single_node archs or beats
    BASE's score once feasible, since BASE's objective has no credit for
    the psum/vmem DRAM-traffic elimination the other modes' loop-order
    constraints unlock.

    Raises ValueError if EVERY mode is infeasible (callers sweeping many
    layers should catch this and record it, not let it abort the sweep).
    """
    from mip_solver.solve import solve_best_schedule  # lazy: see module-level comment

    workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
    layer_path = _dump_workload_path(workload)
    prob = SNNProb(pathlib.Path(layer_path))

    try:
        best_mode, best_result = solve_best_schedule(layer_path, arch_yaml, dataflow_yaml)
    except ValueError as exc:
        raise ValueError(
            f"solve_and_cache_schedule: infeasible for {arch_name}/{trace_dir_name}/{layer_name} "
            f"(every TrafficMode infeasible)"
        ) from exc
    schedule = schedule_from_strategy(best_result["strategy"], prob)

    artifact = ScheduleArtifact(
        arch=arch_name,
        trace_dir=trace_dir_name,
        layer_name=layer_name,
        workload=workload,
        result=best_result,
        dram_num_steps=schedule.dram_num_steps,
        mode=best_mode.value,
    )
    out_path = cache_dir / arch_name / trace_dir_name / f"{layer_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(asdict(artifact), fh)
    return artifact


def load_schedule(path: pathlib.Path) -> Tuple[ScheduleArtifact, SNNProb, List[NodeTileSpec]]:
    """Load a persisted ScheduleArtifact and rederive the (prob, tiles) it
    implies. schedule/tiles aren't themselves JSON-serializable, so they're
    rebuilt deterministically from the cached workload+result rather than
    (de)serialized directly -- iter_node_tiles is a pure function of
    (schedule, prob), so this reproduces the exact same tile list every
    time without re-solving anything."""
    with open(path) as fh:
        data = json.load(fh)
    artifact = ScheduleArtifact(**data)
    prob = _prob_from_workload(artifact.workload)
    schedule = schedule_from_strategy(artifact.result["strategy"], prob)
    tiles = list(iter_node_tiles(schedule, prob))
    return artifact, prob, tiles


@dataclass
class TileWeightTrace:
    dram_i: int
    mac_cycles: int
    lif_cycles: Optional[int]
    weight_addresses: List[Any]
    tick_ids: List[int]


@dataclass
class LayerWeightTrace:
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    tiles: List[TileWeightTrace]


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
    native C++ bridge (archmodels.ARCH_NATIVE_BRIDGES). Single consolidated
    entry point for what used to be two copy-pasted dispatch blocks in
    scripts/generate_weight_traces.py and
    scripts/generate_weight_traces_canonical100.py -- callers own the
    trace/worker-pool setup around this, this function owns only the
    dispatch. `trace` should already be loaded (e.g. via
    archmodels.trace.load_layer_trace(..., mmap=True)); this function
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


def save_weight_trace(trace: LayerWeightTrace, path: pathlib.Path) -> None:
    """Writes gzip-compressed JSON -- verified 19.5x smaller on real
    generated data (9.64MB -> 0.49MB), which is what makes the full sweep's
    storage footprint (otherwise ~510GB at 1000 samples/layer) fit in any
    reasonable quota. `path` should end in .json.gz; transparent to any
    caller reading it back with gzip.open -- only a direct `open()`/`cat`
    of the file needs to know it's gzipped. (The read-side counterpart,
    load_weight_trace, moved to dump/python_reference/tracegen_reconstruct.py
    since nothing in the live pipeline reads a trace back this way --
    src/cachesim/native_bridge.py reads the raw JSON directly instead.)

    Writes to a sibling temp file and os.replace()s it into place, so a
    process killed mid-write (OOM, SLURM time limit, etc.) can never leave
    a truncated file sitting at `path` -- skip-existing checks (this
    module's callers, generate_weight_traces.py) only ever see either the
    complete prior file or nothing, never a corrupted partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        with gzip.open(tmp_name, "wt") as fh:
            json.dump(asdict(trace), fh)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


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
