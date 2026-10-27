"""The solved-schedule artifact: one JSON file per (arch, trace_dir, layer).

Written by solve_and_cache_schedule (the SNN scheduler's Gurobi solve);
read by the weight-trace generator (weight_trace_gen.weight_trace.load_schedule)
through read_artifact.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict

import yaml

from weight_trace_gen.trace import build_workload_from_trace
from nocsim.schedule.decode import schedule_from_strategy
from parsers.layer import SNNProb

# snn_scheduler.solve is imported lazily, inside solve_and_cache_schedule only:
# it pulls in gurobipy at module load, and everything else in this module
# (reading or checking an already-cached schedule) has no need for Gurobi.

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
    cache_dir: pathlib.Path,
) -> ScheduleArtifact:
    """Solve one (arch, layer)'s schedule across every TrafficMode, keep the
    winner by the CoSA reference score
    (w_u*util_sum + w_tr*tr_sum + w_dl*delay, lower is better), and persist
    it to cache_dir/<arch>/<trace_dir>/<layer_name>.json. Always re-solves --
    callers wanting skip-existing behavior should check for that file
    themselves first, matching every other skip-existing check in this
    pipeline (see weight_trace_gen/cli.py).

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
    from snn_scheduler.solve import solve_best_schedule  # lazy: see module-level comment

    workload = build_workload_from_trace(meta, layer_name)
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
        json.dump(asdict(artifact), fh, indent=1)
    return artifact


def read_artifact(path: pathlib.Path) -> ScheduleArtifact:
    """Read a persisted ScheduleArtifact back from its JSON file."""
    with open(path) as fh:
        data = json.load(fh)
    return ScheduleArtifact(**data)


def check_schedule_matches_trace(
    schedule_path: pathlib.Path, trace_dir: pathlib.Path, layer_name: str
) -> None:
    """Raise ValueError when the schedule at schedule_path was solved for a
    different workload than trace_dir/meta.json now gives layer_name, e.g.
    one solved before meta.json carried the layer's true COUT."""
    meta = json.loads((pathlib.Path(trace_dir) / "meta.json").read_text())
    try:
        want = build_workload_from_trace(meta, layer_name)["problem"]
    except ValueError as exc:
        raise ValueError(f"schedule {schedule_path}: {exc}") from exc
    doc = json.loads(pathlib.Path(schedule_path).read_text())
    got = doc["workload"]["problem"]
    if got != want:
        diff = ", ".join(f"{k} {got.get(k)} (meta.json: {want.get(k)})"
                         for k in sorted(set(got) | set(want)) if got.get(k) != want.get(k))
        arch = doc.get("result", {}).get("configs", {}).get("arch") or "the arch it was solved with"
        raise ValueError(
            f"stale schedule {schedule_path}: solved for {diff}. It must be re-solved with "
            f"Gurobi against {arch} (result.configs.arch) and written back to its own "
            f"directory: python -m snn_scheduler solve-trace --force --arch-yaml <that arch> "
            f"--cache-dir <schedule root>"
        )
