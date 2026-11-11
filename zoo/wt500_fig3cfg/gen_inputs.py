#!/usr/bin/env python3
"""Build the wt500 schedule cache and freeze its input manifest.

The weight-trace campaign has two deliberately separate stages.  This script
does the small, DeltaAI-side stage: it derives a workload from each capture's
``meta.json``, enumerates all traffic modes and selects one schedule for every
``(arch, trace, layer)`` pair, and
checks that the resulting tiles satisfy the native bridge contracts before a
trace-generation array is launched.

The default invocation covers the complete matrix.  ``--smoke`` is useful on a
new checkout: it enumerates the first replayable layer of the first capture for
each architecture while still writing the complete capture/layer inventory to
the manifest.  A smoke manifest is marked as such and must not be used for a
full generation run.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import yaml

from lays.parsers.layer import (
    DIM_CIN,
    DIM_HO,
    DIM_KH,
    DIM_KW,
    DIM_T,
    DIM_WO,
    SNNProb,
)
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.scheduler.artifact import sha256_file
from lays.weight_trace_gen.trace import (
    build_workload_from_trace,
    exclusion_reason,
    valid_layer_names,
)
from lays.weight_trace_gen.weight_trace import load_schedule


HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_TRACE_ROOT = pathlib.Path("/work/nvme/bebv/yyu9/input_trace_delta")
DEFAULT_OUTPUT_DIR = HERE / "outputs"
DEFAULT_ARCH_YAML = HERE / "arch.yaml"
DEFAULT_MAPSPACE_DIR = HERE / "mapspaces"
CONDA_ENV = "gurobi"
SAMPLE_START = 0
SAMPLE_COUNT = 500

ARCHES: Tuple[str, ...] = (
    "loas",
    "ptb",
    "spinalflow",
    "prosperity",
    "gustavsnn",
)

# Keep this order stable: it is the order used for the campaign's capture
# inventory and also makes --smoke deterministic.
CAPTURE_RELATIVE_DIRS: Tuple[str, ...] = (
    "A02/spikformer_4_384_cifar100_T4_n500",
    "A04/sdt_2_512_cifar100_T4_n500",
    "A07/spikinglm_t4_T4_n500",
    "A08/vgg16_cifar10_loas_T32_n500",
    "B09/loas_vgg16_T4_n500",
    "B09/loas_resnet19_T4_n500",
    "C01/sma_azo_vgg_cifar10_dvs_T10_n500",
    "C01/sma_azo_vgg_dvs128_gesture_T16_n500",
)


@dataclass(frozen=True)
class Capture:
    """Metadata and replayable workloads for one Delta capture."""

    relative_dir: str
    path: pathlib.Path
    meta_path: pathlib.Path
    meta: Mapping[str, Any]
    valid_layers: Tuple[str, ...]
    excluded_layers: Mapping[str, str]
    workloads: Mapping[str, Mapping[str, Any]]

    @property
    def name(self) -> str:
        return self.path.name


def _json_dump(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _path_string(path: pathlib.Path, base: pathlib.Path | None = None) -> str:
    """Use stable relative paths for campaign artifacts when possible."""
    path = path.resolve()
    if base is not None:
        try:
            return path.relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def _load_captures(trace_root: pathlib.Path) -> List[Capture]:
    captures: List[Capture] = []
    seen_names: set[str] = set()
    for relative_dir in CAPTURE_RELATIVE_DIRS:
        trace_dir = trace_root / relative_dir
        meta_path = trace_dir / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"missing capture metadata: {meta_path}")
        meta = json.loads(meta_path.read_text())
        n_samples = meta.get("n_samples")
        if n_samples != SAMPLE_COUNT:
            raise ValueError(
                f"{meta_path}: n_samples={n_samples!r}, expected {SAMPLE_COUNT}"
            )
        if trace_dir.name in seen_names:
            raise ValueError(f"capture directory names must be unique: {trace_dir.name}")
        seen_names.add(trace_dir.name)

        valid = tuple(valid_layer_names(meta))
        excluded = {
            name: exclusion_reason(meta, name)
            for name in meta["layers"]
            if name not in valid
        }
        # Build every workload even in --smoke mode.  That makes the manifest
        # a complete, reviewable inventory and catches malformed metadata
        # before a partial solver run begins.
        workloads = {
            name: build_workload_from_trace(meta, name)
            for name in valid
        }
        captures.append(Capture(
            relative_dir=relative_dir,
            path=trace_dir,
            meta_path=meta_path,
            meta=meta,
            valid_layers=valid,
            excluded_layers=excluded,
            workloads=workloads,
        ))
    return captures


def _workload_path(
    output_dir: pathlib.Path, capture: Capture, layer_name: str,
) -> pathlib.Path:
    return output_dir / "workloads" / capture.name / f"{layer_name}.yaml"


def _write_workload(
    output_dir: pathlib.Path, capture: Capture, layer_name: str,
) -> pathlib.Path:
    path = _workload_path(output_dir, capture, layer_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(capture.workloads[layer_name], sort_keys=False))
    return path


def _solver_command(
    arch_yaml: pathlib.Path,
    layer_yaml: pathlib.Path,
    mapspace_yaml: pathlib.Path,
    out_path: pathlib.Path,
    conda_env: str,
    conda_exe: str,
) -> List[str]:
    return [
        conda_exe,
        "run",
        "-n",
        conda_env,
        "python",
        "-m",
        "lays.scheduler",
        "enumerate",
        "--arch",
        str(arch_yaml.resolve()),
        "--layer",
        str(layer_yaml.resolve()),
        "--dataflow",
        str(mapspace_yaml.resolve()),
        "--time-limit",
        "30",
        "--out",
        str(out_path.resolve()),
    ]


def _solver_env() -> Dict[str, str]:
    env = dict(os.environ)
    src = str((REPO / "src").resolve())
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not old else f"{src}{os.pathsep}{old}"
    return env


def _artifact_matches(
    path: pathlib.Path,
    arch: str,
    capture: Capture,
    layer_name: str,
    workload: Mapping[str, Any],
    arch_yaml: pathlib.Path,
    mapspace_yaml: pathlib.Path,
) -> bool:
    """Reject stale cached schedules rather than silently reusing them."""
    try:
        artifact = json.loads(path.read_text())
        result = artifact["result"]
        configs = result.get("configs", {})
        mode_statuses = result.get("mode_statuses")
        return (
            artifact["arch"] == arch
            and artifact["trace_dir"] == capture.name
            and artifact["layer_name"] == layer_name
            and artifact["workload"] == workload
            and isinstance(artifact.get("mode"), str)
            and isinstance(mode_statuses, list)
            and result.get("has_solution") is True
            and isinstance(result.get("strategy"), dict)
            and configs.get("arch") in {str(arch_yaml), str(arch_yaml.resolve())}
            and configs.get("dataflow") in {str(mapspace_yaml), str(mapspace_yaml.resolve())}
            and artifact.get("arch_yaml_sha256") == sha256_file(arch_yaml)
            and artifact.get("mapspace_yaml_sha256") == sha256_file(mapspace_yaml)
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False


def _make_artifact(
    arch: str,
    capture: Capture,
    layer_name: str,
    workload: Mapping[str, Any],
    result: Mapping[str, Any],
    arch_yaml: pathlib.Path,
    mapspace_yaml: pathlib.Path,
) -> Dict[str, Any]:
    best_mode = result.get("best_mode")
    candidates = result.get("candidates")
    best_strategy = result.get("best_strategy")
    if not isinstance(best_mode, str) or not best_mode:
        raise ValueError("enumeration result has no best_mode")
    if not isinstance(candidates, list):
        raise ValueError("enumeration result has no candidates list")
    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("enumeration result candidates are not objects")
    if not isinstance(best_strategy, dict):
        raise ValueError("enumeration result has no best_strategy")
    best_candidate = next(
        (candidate for candidate in candidates if candidate.get("mode") == best_mode),
        None,
    )
    if not isinstance(best_candidate, dict):
        raise ValueError(f"enumeration result has no candidate for best_mode {best_mode!r}")
    selected_result = {
        "status": best_candidate.get("status", "SOLVED"),
        "has_solution": True,
        "objective": best_candidate.get("gurobi_objective"),
        "strategy": best_strategy,
        "metrics": best_candidate.get("metrics"),
        "mode_statuses": [
            {"mode": candidate.get("mode"), "status": candidate.get("status")}
            for candidate in candidates
        ],
        "configs": {
            "arch": str(arch_yaml.resolve()),
            "dataflow": str(mapspace_yaml.resolve()),
        },
    }
    # SNNProb is path-based, while the solver result artifact stores the
    # workload inline.  Keep the parser's temporary YAML scoped to this call.
    with tempfile.TemporaryDirectory(prefix="schedule-problem-") as tmp:
        workload_path = pathlib.Path(tmp) / "layer.yaml"
        workload_path.write_text(yaml.safe_dump(workload, sort_keys=False))
        prob = SNNProb(workload_path)
        schedule = schedule_from_strategy(selected_result["strategy"], prob)
    return {
        "arch": arch,
        "trace_dir": capture.name,
        "layer_name": layer_name,
        "workload": workload,
        "result": selected_result,
        "dram_num_steps": schedule.dram_num_steps,
        "mode": best_mode,
        "arch_yaml_sha256": sha256_file(arch_yaml),
        "mapspace_yaml_sha256": sha256_file(mapspace_yaml),
    }


def _solve_pair(
    *,
    arch: str,
    capture: Capture,
    layer_name: str,
    workload: Mapping[str, Any],
    output_dir: pathlib.Path,
    arch_yaml: pathlib.Path,
    mapspace_yaml: pathlib.Path,
    conda_env: str,
    conda_exe: str,
    force: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    schedule_path = output_dir / "schedules" / arch / capture.name / f"{layer_name}.json"
    record: Dict[str, Any] = {
        "arch": arch,
        "trace_dir": capture.name,
        "trace_relative_dir": capture.relative_dir,
        "layer": layer_name,
        "workload": workload,
        "arch_yaml": _path_string(arch_yaml, REPO),
        "mapspace": _path_string(mapspace_yaml, REPO),
        "arch_yaml_sha256": sha256_file(arch_yaml),
        "mapspace_yaml_sha256": sha256_file(mapspace_yaml),
        "schedule_path": _path_string(schedule_path, output_dir),
    }

    if not force and schedule_path.is_file() and _artifact_matches(
        schedule_path, arch, capture, layer_name, workload, arch_yaml, mapspace_yaml
    ):
        cached_artifact = json.loads(schedule_path.read_text())
        record.update({
            "status": "CACHED",
            "solver_status": "CACHED",
            "mode": cached_artifact["mode"],
            "mode_statuses": cached_artifact["result"]["mode_statuses"],
            "schedule_sha256": sha256_file(schedule_path),
        })
        return record

    if dry_run:
        record.update({"status": "NOT_RUN", "solver_status": "NOT_RUN"})
        return record

    layer_yaml = _write_workload(output_dir, capture, layer_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="solver-", dir=output_dir) as tmp:
        raw_path = pathlib.Path(tmp) / "result.json"
        command = _solver_command(
            arch_yaml, layer_yaml, mapspace_yaml, raw_path, conda_env, conda_exe
        )
        try:
            proc = subprocess.run(
                command,
                cwd=REPO,
                env=_solver_env(),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            record.update({
                "status": "ERROR",
                "solver_status": "EXEC_FAILED",
                "stderr": f"{type(exc).__name__}: {exc}",
            })
            return record
        record["command"] = command
        record["returncode"] = proc.returncode
        if not raw_path.is_file():
            record.update({
                "status": "ERROR",
                "solver_status": "NO_OUTPUT",
                "stderr": proc.stderr[-4000:],
                "stdout": proc.stdout[-2000:],
            })
            return record
        try:
            result = json.loads(raw_path.read_text())
        except json.JSONDecodeError as exc:
            record.update({
                "status": "ERROR",
                "solver_status": "INVALID_JSON",
                "stderr": f"{exc}: {proc.stderr[-4000:]}",
            })
            return record

    if (
        "best_mode" not in result
        or not isinstance(result.get("candidates"), list)
        or not all(isinstance(candidate, dict) for candidate in result["candidates"])
    ):
        record.update({
            "status": "ERROR",
            "solver_status": "INVALID_ENUMERATION",
            "stderr": proc.stderr[-4000:],
        })
        return record

    if result.get("best_mode") is None:
        record.update({
            "status": "INFEASIBLE",
            "solver_status": "INFEASIBLE",
            "mode": None,
            "mode_statuses": [
                {"mode": candidate.get("mode"), "status": candidate.get("status")}
                for candidate in result["candidates"]
            ],
            "stderr": proc.stderr[-4000:],
        })
        return record

    try:
        artifact = _make_artifact(
            arch, capture, layer_name, workload, result, arch_yaml, mapspace_yaml,
        )
        _json_dump(schedule_path, artifact)
    except Exception as exc:  # noqa: BLE001 - record one bad pair and continue
        record.update({
            "status": "ERROR",
            "solver_status": "ARTIFACT_FAILED",
            "stderr": f"{type(exc).__name__}: {exc}",
        })
        return record
    record.update({
        "status": "SOLVED",
        "solver_status": artifact["result"].get("status", "SOLVED"),
        "mode": artifact["mode"],
        "mode_statuses": artifact["result"]["mode_statuses"],
        "schedule_sha256": sha256_file(schedule_path),
        "dram_num_steps": artifact["dram_num_steps"],
    })
    return record


def _dim(tile: Any, key: int) -> int:
    return int(tile.node_bound.get(key, 1))


def _offset(tile: Any, key: int) -> int | None:
    value = tile.tile_offset.get(key)
    return None if value is None else int(value)


def _bridge_tile_violations(
    arch: str, tile: Any, problem: Mapping[str, int], tile_index: int,
) -> List[Dict[str, Any]]:
    """Return contract violations for one decoded NodeTileSpec.

    The native bridges do not receive the full schedule, so these conditions
    are intentionally checked here rather than relying on the solver's
    mapspace comments.  In particular, Prosperity accepts a resident CIN
    range: its bridge reconstructs one independent native walk per resident
    channel and concatenates those walks in channel order.
    """
    violations: List[Dict[str, Any]] = []

    def bad(code: str, message: str, **details: Any) -> None:
        violations.append({
            "tile": tile_index,
            "code": code,
            "message": message,
            **details,
        })

    # Every bridge's tile record has a complete kernel window and no kernel
    # offset.  An offset would be ignored by the native bridge.
    for dim, name in ((DIM_KH, "KH"), (DIM_KW, "KW")):
        if _offset(tile, dim) not in (None, 0):
            bad("kernel_offset", f"{name} offset is not supported", dimension=name)
        if _dim(tile, dim) != int(problem[name]):
            bad(
                "kernel_tile_bound",
                f"{name} tile bound is not the full kernel",
                dimension=name,
                bound=_dim(tile, dim),
                expected=int(problem[name]),
            )

    if arch in {"loas", "ptb", "spinalflow"}:
        # Section 8: one output pixel, all resident CIN and T.  The native
        # bridges default an absent HO/WO offset to zero; that is safe exactly
        # when the problem dimension is 1, because zero is then the only
        # possible position.  A split dimension still needs an explicit offset.
        for dim, name in ((DIM_HO, "HO"), (DIM_WO, "WO")):
            if _dim(tile, dim) != 1:
                bad(
                    "pixel_tile_bound",
                    f"{arch} requires one output pixel per tile",
                    dimension=name,
                    bound=_dim(tile, dim),
                )
            if _offset(tile, dim) is None and int(problem[name]) != 1:
                bad(
                    "missing_pixel_offset",
                    f"{arch} requires an explicit {name} tile offset when the problem dimension is split",
                    dimension=name,
                )
        for dim, name in ((DIM_CIN, "CIN"), (DIM_T, "T")):
            if _dim(tile, dim) != int(problem[name]):
                bad(
                    "resident_dimension",
                    f"{arch} requires all {name} values in every tile",
                    dimension=name,
                    bound=_dim(tile, dim),
                    expected=int(problem[name]),
                )
    elif arch == "prosperity":
        # Section 5: Prosperity reuses rows across a block. Each resident CIN
        # is reconstructed as an independent sequential walk, and all T
        # values remain resident in the tile.
        if _dim(tile, DIM_T) != int(problem["T"]):
            bad(
                "prosperity_resident_t",
                "Prosperity bridge requires all T values in every tile",
                bound=_dim(tile, DIM_T),
                expected=int(problem["T"]),
            )
    elif arch == "gustavsnn":
        # Section 5: GustavSNN is the complementary shape -- all CIN resident
        # and exactly one timestep, with HO rows allowed to run in parallel.
        if _dim(tile, DIM_CIN) != int(problem["CIN"]):
            bad(
                "gustavsnn_resident_cin",
                "GustavSNN bridge requires all CIN values in every tile",
                bound=_dim(tile, DIM_CIN),
                expected=int(problem["CIN"]),
            )
        if _dim(tile, DIM_T) != 1:
            bad(
                "gustavsnn_t_per_tile",
                "GustavSNN bridge requires exactly one T per tile",
                bound=_dim(tile, DIM_T),
                expected=1,
            )
    else:  # defensive: the CLI constrains this, but gate helpers are public.
        bad("unknown_arch", f"no bridge contract for {arch}")

    # A dimension that is split across tiles needs an offset in the tile record;
    # otherwise a bridge using .get(..., 0) would replay the first slice.
    for dim, name in (
        (DIM_CIN, "CIN"),
        (DIM_T, "T"),
        (DIM_HO, "HO"),
        (DIM_WO, "WO"),
    ):
        total = int(problem[name])
        bound = _dim(tile, dim)
        if total > bound and _offset(tile, dim) is None:
            bad(
                "missing_split_offset",
                f"{name} is split across tiles but has no tile offset",
                dimension=name,
                bound=bound,
                total=total,
            )

    return violations


def check_bridge_compatibility(
    schedule_path: pathlib.Path,
    arch: str,
) -> Dict[str, Any]:
    """Decode every tile and check the native bridge assumptions."""
    try:
        artifact, prob, tiles = load_schedule(schedule_path)
        problem = artifact.workload["problem"]
        violations: List[Dict[str, Any]] = []
        for index, tile in enumerate(tiles):
            violations.extend(_bridge_tile_violations(arch, tile, problem, index))
        # Duplicate messages for every tile are noisy in a frozen manifest;
        # preserve counts and the first few examples while retaining all codes.
        counts: Dict[str, int] = {}
        for violation in violations:
            counts[violation["code"]] = counts.get(violation["code"], 0) + 1
        return {
            "passed": not violations,
            "tiles_checked": len(tiles),
            "violation_count": len(violations),
            "violation_codes": counts,
            "violations": violations[:32],
        }
    except Exception as exc:  # noqa: BLE001 - gate must record, not hide, bad artifacts
        return {
            "passed": False,
            "tiles_checked": 0,
            "violation_count": 1,
            "violation_codes": {"schedule_decode": 1},
            "violations": [{
                "tile": None,
                "code": "schedule_decode",
                "message": f"{type(exc).__name__}: {exc}",
            }],
        }


def _pair_dict(arch: str, capture: Capture, layer: str, reason: str | None = None) -> Dict[str, Any]:
    pair = {
        "arch": arch,
        "trace_dir": capture.name,
        "trace_relative_dir": capture.relative_dir,
        "layer": layer,
    }
    if reason is not None:
        pair["reason"] = reason
    return pair


def _select_pairs(
    captures: Sequence[Capture],
    arches: Sequence[str],
    smoke: bool,
) -> List[Tuple[str, Capture, str]]:
    if smoke:
        if not captures or not captures[0].valid_layers:
            return []
        layer = captures[0].valid_layers[0]
        return [(arch, captures[0], layer) for arch in arches]
    return [
        (arch, capture, layer)
        for arch in arches
        for capture in captures
        for layer in capture.valid_layers
    ]


def _mode_digest(schedules: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    per_mode: Dict[str, Dict[str, int]] = {}
    winner_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    for record in schedules:
        for mode_status in record.get("mode_statuses", []):
            mode = mode_status.get("mode")
            status = mode_status.get("status")
            if not isinstance(mode, str) or not isinstance(status, str):
                continue
            counts = per_mode.setdefault(mode, {"OPTIMAL": 0, "INFEASIBLE": 0})
            counts[status] = counts.get(status, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
        winner = record.get("mode")
        if isinstance(winner, str):
            winner_counts[winner] = winner_counts.get(winner, 0) + 1
    time_limit_count = status_counts.get("TIME_LIMIT", 0)
    return {
        "candidate_count": sum(status_counts.values()),
        "per_mode": per_mode,
        "status_counts": status_counts,
        "winner_mode_counts": winner_counts,
        "time_limit_count": time_limit_count,
        "no_time_limit": time_limit_count == 0,
    }


def build_manifest_inventory(
    captures: Sequence[Capture], arches: Sequence[str], trace_root: pathlib.Path,
) -> Dict[str, Any]:
    """Create the immutable portion of the manifest before solving."""
    excluded_pairs = [
        _pair_dict(arch, capture, layer, reason)
        for arch in arches
        for capture in captures
        for layer, reason in capture.excluded_layers.items()
    ]
    return {
        "schema": "wt500_fig3cfg-manifest-v1",
        "trace_root": str(trace_root.resolve()),
        "capture_order": [capture.relative_dir for capture in captures],
        "captures": [
            {
                "trace_dir": capture.name,
                "trace_relative_dir": capture.relative_dir,
                "trace_path": str(capture.path.resolve()),
                "meta_path": str(capture.meta_path.resolve()),
                "captured_arch": capture.meta.get("arch"),
                "n_samples": capture.meta.get("n_samples"),
                "valid_layers": list(capture.valid_layers),
                "excluded_layers": dict(capture.excluded_layers),
                "workloads": dict(capture.workloads),
            }
            for capture in captures
        ],
        "samples": {
            "start": SAMPLE_START,
            "count": SAMPLE_COUNT,
            "indices": list(range(SAMPLE_START, SAMPLE_START + SAMPLE_COUNT)),
        },
        "excluded_pairs": excluded_pairs,
        "infeasible_pairs": [],
        "bridge_incompatible_pairs": [],
        "schedules": [],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace-root", type=pathlib.Path, default=DEFAULT_TRACE_ROOT,
        help=f"Delta capture root (default: {DEFAULT_TRACE_ROOT})",
    )
    parser.add_argument(
        "--output-dir", type=pathlib.Path, default=DEFAULT_OUTPUT_DIR,
        help=f"campaign output root (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--arch", dest="arches", action="append", choices=ARCHES,
                        help="restrict the solve to one or more architectures")
    parser.add_argument("--smoke", action="store_true",
                        help="solve one layer from the first capture per architecture")
    parser.add_argument("--dry-run", action="store_true",
                        help="write inventory and planned pairs without invoking Gurobi")
    parser.add_argument("--force", action="store_true",
                        help="re-solve even when a matching schedule artifact exists")
    parser.add_argument("--allow-bridge-violations", action="store_true",
                        help="write the manifest and return success despite gate failures")
    parser.add_argument("--conda-env", default=CONDA_ENV,
                        help=f"conda environment for solver (default: {CONDA_ENV})")
    parser.add_argument("--conda-exe", default="conda",
                        help="conda executable (default: conda)")
    parser.add_argument("--arch-yaml", type=pathlib.Path, default=DEFAULT_ARCH_YAML)
    parser.add_argument("--mapspace-dir", type=pathlib.Path, default=DEFAULT_MAPSPACE_DIR)
    parser.add_argument("--manifest", type=pathlib.Path, default=None,
                        help="manifest path (default: <output-dir>/manifest.json)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    trace_root = args.trace_root.resolve()
    output_dir = args.output_dir.resolve()
    arches = tuple(args.arches or ARCHES)
    arch_yaml = args.arch_yaml.resolve()
    mapspace_dir = args.mapspace_dir.resolve()
    manifest_path = (args.manifest or output_dir / "manifest.json").resolve()

    if not arch_yaml.is_file():
        raise FileNotFoundError(f"missing campaign arch YAML: {arch_yaml}")
    for arch in arches:
        mapspace = mapspace_dir / f"{arch}.yaml"
        if not mapspace.is_file():
            raise FileNotFoundError(f"missing campaign mapspace YAML: {mapspace}")

    captures = _load_captures(trace_root)
    manifest = build_manifest_inventory(captures, arches, trace_root)
    selected = _select_pairs(captures, arches, args.smoke)
    selected_keys = {(arch, capture.name, layer) for arch, capture, layer in selected}
    all_keys = {
        (arch, capture.name, layer)
        for arch in arches
        for capture in captures
        for layer in capture.valid_layers
    }
    manifest["run"] = {
        "mode": "smoke" if args.smoke else "full",
        "dry_run": bool(args.dry_run),
        "selected_pair_count": len(selected),
        "planned_valid_pair_count": len(all_keys),
        "unselected_valid_pairs": [
            _pair_dict(arch, capture, layer)
            for arch in arches
            for capture in captures
            for layer in capture.valid_layers
            if (arch, capture.name, layer) not in selected_keys
        ],
    }
    manifest["configs"] = {
        "arch_yaml": _path_string(arch_yaml, REPO),
        "arch_yaml_sha256": sha256_file(arch_yaml),
        "mapspace_dir": _path_string(mapspace_dir, REPO),
        "mapspaces": {arch: _path_string(mapspace_dir / f"{arch}.yaml", REPO) for arch in arches},
        "mapspace_yaml_sha256": {
            arch: sha256_file(mapspace_dir / f"{arch}.yaml") for arch in arches
        },
        "solver": [
            args.conda_exe, "run", "-n", args.conda_env, "python", "-m", "lays.scheduler",
            "enumerate", "--time-limit", "30",
        ],
    }

    print(
        f"captures={len(captures)} valid_pairs={len(all_keys)} "
        f"selected={len(selected)} mode={manifest['run']['mode']}",
        flush=True,
    )
    for index, (arch, capture, layer) in enumerate(selected, 1):
        mapspace_yaml = mapspace_dir / f"{arch}.yaml"
        print(f"[{index}/{len(selected)}] {arch}/{capture.name}/{layer}", flush=True)
        record = _solve_pair(
            arch=arch,
            capture=capture,
            layer_name=layer,
            workload=capture.workloads[layer],
            output_dir=output_dir,
            arch_yaml=arch_yaml,
            mapspace_yaml=mapspace_yaml,
            conda_env=args.conda_env,
            conda_exe=args.conda_exe,
            force=args.force,
            dry_run=args.dry_run,
        )
        if record["status"] in {"SOLVED", "CACHED"}:
            schedule_path = output_dir / record["schedule_path"]
            gate = check_bridge_compatibility(schedule_path, arch)
            record["bridge_gate"] = gate
            if not gate["passed"]:
                record["status"] = "BRIDGE_INCOMPATIBLE"
                manifest["bridge_incompatible_pairs"].append({
                    **_pair_dict(arch, capture, layer),
                    "violation_codes": gate["violation_codes"],
                    "violations": gate["violations"],
                })
            print(
                f"  {record['status']} bridge={'PASS' if gate['passed'] else 'FAIL'} "
                f"tiles={gate['tiles_checked']}",
                flush=True,
            )
        elif record["status"] == "INFEASIBLE":
            manifest["infeasible_pairs"].append({
                **_pair_dict(arch, capture, layer),
                "solver_status": record.get("solver_status"),
            })
            print(f"  INFEASIBLE ({record.get('solver_status')})", flush=True)
        else:
            print(f"  {record['status']} ({record.get('solver_status')})", flush=True)
        manifest["schedules"].append(record)

    manifest["bridge_gate"] = {
        "contracts": {
            "loas_ptb_spinalflow": "one HO/WO pixel, full CIN and T, full KH/KW, no KH/KW offset",
            "prosperity": "resident CIN range, full T, full KH/KW, no KH/KW offset",
            "gustavsnn": "full CIN, one T per tile, full KH/KW, no KH/KW offset",
        },
        "checked_schedule_count": sum(
            1 for record in manifest["schedules"] if "bridge_gate" in record
        ),
        "passed_schedule_count": sum(
            1 for record in manifest["schedules"]
            if record.get("bridge_gate", {}).get("passed") is True
        ),
        "violation_pair_count": len(manifest["bridge_incompatible_pairs"]),
        "violation_count": sum(
            record.get("bridge_gate", {}).get("violation_count", 0)
            for record in manifest["schedules"]
        ),
        "passed": not manifest["bridge_incompatible_pairs"],
    }
    manifest["mode_digest"] = _mode_digest(manifest["schedules"])
    manifest["manifest_path"] = _path_string(manifest_path, output_dir.parent)
    _json_dump(manifest_path, manifest)
    print(f"manifest: {manifest_path}", flush=True)

    n_errors = sum(record.get("status") == "ERROR" for record in manifest["schedules"])
    if n_errors:
        print(f"solver errors: {n_errors}", file=sys.stderr)
        return 1
    if manifest["bridge_incompatible_pairs"] and not args.allow_bridge_violations:
        print(
            f"bridge gate failed for {len(manifest['bridge_incompatible_pairs'])} schedule(s); "
            "see manifest and re-solve or extend the bridge",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
