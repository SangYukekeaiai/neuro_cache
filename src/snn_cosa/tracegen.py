"""Shared solve/reconstruct/persist core for weight-trace generation.

Extracts what scripts/sweep_archmodel_layers.py used to do entirely
inline (solve -> iterate tiles -> format_input -> compute_cycles /
weight_addresses) into reusable pieces, so that script and the
generate-once pipeline (scripts/solve_schedules.py,
scripts/generate_weight_traces.py) share one implementation instead of
two copies that could quietly drift apart.

Two independent artifacts, matching the two-stage design
(docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md):

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
import json
import pathlib
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import yaml

from snn_cosa.archmodels import ArchComputeModel, NodeTileSpec
from snn_cosa.archmodels.gustavsnn.model import GustavSNNComputeModel
from snn_cosa.archmodels.loas.model import LoASComputeModel
from snn_cosa.archmodels.prosperity.model import ProsperityComputeModel
from snn_cosa.archmodels.ptb.model import PTBComputeModel
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.trace import build_workload_from_trace
from snn_cosa.mip_solver.solve import solve_schedule
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.layer import SNNProb

ARCH_MODELS = {
    "loas": LoASComputeModel,
    "spinalflow": SpinalFlowComputeModel,
    "ptb": PTBComputeModel,
    "gustavsnn": GustavSNNComputeModel,
    "prosperity": ProsperityComputeModel,
}


@dataclass
class ScheduleArtifact:
    """A solved schedule, persisted once per (arch, trace_dir, layer)."""

    arch: str
    trace_dir: str
    layer_name: str
    workload: Dict[str, Any]
    result: Dict[str, Any]  # raw solve_schedule() output (has_solution, strategy, ...)
    dram_num_steps: int


def _dump_workload_path(workload: Dict[str, Any]) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(workload, f)
        return f.name


def _prob_from_workload(workload: Dict[str, Any]) -> SNNProb:
    return SNNProb(pathlib.Path(_dump_workload_path(workload)))


def solve_and_cache_schedule(
    arch_name: str,
    arch_yaml: str,
    trace_dir_name: str,
    layer_name: str,
    meta: Dict[str, Any],
    next_cin: Optional[int],
    cache_dir: pathlib.Path,
) -> ScheduleArtifact:
    """Solve one (arch, layer)'s schedule and persist it to
    cache_dir/<arch>/<trace_dir>/<layer_name>.json. Always re-solves --
    callers wanting skip-existing behavior should check for that file
    themselves first, matching every other skip-existing check in this
    pipeline (see generate_weight_traces.py).

    Raises ValueError if the schedule is infeasible (callers sweeping many
    layers should catch this and record it, not let it abort the sweep).
    """
    workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
    layer_path = _dump_workload_path(workload)
    prob = SNNProb(pathlib.Path(layer_path))
    result = solve_schedule(layer_path, arch_yaml)
    if not result.get("has_solution"):
        raise ValueError(
            f"solve_and_cache_schedule: infeasible for {arch_name}/{trace_dir_name}/{layer_name}"
        )
    schedule = schedule_from_strategy(result["strategy"], prob)

    artifact = ScheduleArtifact(
        arch=arch_name,
        trace_dir=trace_dir_name,
        layer_name=layer_name,
        workload=workload,
        result=result,
        dram_num_steps=schedule.dram_num_steps,
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


@dataclass
class LayerWeightTrace:
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    tiles: List[TileWeightTrace]


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
            per_sample_tiles[i].append(
                TileWeightTrace(
                    dram_i=tile.dram_i,
                    mac_cycles=cycles.mac_cycles,
                    lif_cycles=cycles.lif_cycles,
                    weight_addresses=list(addresses),
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


def save_weight_trace(trace: LayerWeightTrace, path: pathlib.Path) -> None:
    """Writes gzip-compressed JSON -- verified 19.5x smaller on real
    generated data (9.64MB -> 0.49MB), which is what makes the full sweep's
    storage footprint (otherwise ~510GB at 1000 samples/layer) fit in any
    reasonable quota. `path` should end in .json.gz; transparent to any
    caller going through load_weight_trace/iter_generated_traces below --
    only a direct `open()`/`cat` of the file needs to know it's gzipped."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        json.dump(asdict(trace), fh)


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
