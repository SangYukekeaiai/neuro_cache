#!/usr/bin/env python3
"""Validate the Stokes inputs and write the 130-case Phase-A manifest.

The manifest is deliberately explicit about every input path and digest.  The
case runner uses the command from ``stage1_worker.pipeline`` verbatim for the
trace-generation step; it only changes the destination from the worker's
scratch file to a durable ``wcts/`` file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


KIT = Path(__file__).resolve().parent
REPO_DEFAULT = KIT.parents[2]
ARCH = "loas"
TRACE_RELATIVE_DIR = Path("B09/loas_vgg16_T4_n500")
LAYER_COUNT = 13
SAMPLE_START = 0
SAMPLE_COUNT = 10
FULL_SAMPLE_COUNT = 500


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read JSON {path}: {exc}") from exc


def required_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"{label} is missing: {path}")
    return path


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def layers_from_meta(meta: dict[str, Any]) -> list[str]:
    layers = meta.get("layers")
    if isinstance(layers, dict):
        names = list(layers)
    elif isinstance(layers, list):
        names = [str(name) for name in layers]
    else:
        raise SystemExit("capture meta.json has no layers mapping/list")
    if len(names) != LAYER_COUNT or len(set(names)) != LAYER_COUNT:
        raise SystemExit(f"expected {LAYER_COUNT} unique capture layers, found {len(names)}")
    layer_params = meta.get("layer_params")
    if not isinstance(layer_params, dict) or set(names) - set(layer_params):
        raise SystemExit("capture meta.json layer_params does not cover all layers")
    return names


def schedule_status(schedule: dict[str, Any], path: Path) -> str:
    result = schedule.get("result")
    if not isinstance(result, dict):
        raise SystemExit(f"schedule has no result object: {path}")
    status = result.get("status")
    if status != "OPTIMAL":
        raise SystemExit(f"schedule is not OPTIMAL ({status!r}): {path}")
    if not result.get("has_solution", True):
        raise SystemExit(f"schedule has no solution: {path}")
    return str(status)


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).expanduser().resolve()
    stage_root = Path(args.stage_root).expanduser().resolve()
    capture_root = Path(args.capture_root).expanduser().resolve()
    capture_dir = (capture_root / args.trace_relative_dir).resolve()
    schedule_dir = Path(args.schedule_dir).expanduser().resolve()
    arch_yaml = required_file(Path(args.arch_yaml), "architecture YAML")
    mapspace_yaml = required_file(Path(args.mapspace_yaml), "mapspace YAML")
    worker = required_file(repo / "zoo/fig12_edp/stokes/stage1_worker.py",
                           "Stage-A worker")
    meta_path = required_file(capture_dir / "meta.json", "capture metadata")
    meta = read_json(meta_path)
    if meta.get("n_samples") != FULL_SAMPLE_COUNT:
        raise SystemExit(
            f"capture is not full-{FULL_SAMPLE_COUNT}: n_samples={meta.get('n_samples')!r}"
        )
    # Capture metadata names the benchmark (``loas_vgg16``), while schedules
    # and the generator name the simulator architecture (``loas``).
    if meta.get("arch") not in (None, ARCH, "loas_vgg16"):
        raise SystemExit(f"capture architecture is not LoAS VGG16: {meta.get('arch')!r}")
    layers = layers_from_meta(meta)
    for layer in layers:
        required_file(capture_dir / f"{layer}.npy", f"capture array for {layer}")

    schedule_files = sorted(schedule_dir.glob("*.json"))
    if len(schedule_files) != LAYER_COUNT:
        raise SystemExit(
            f"expected {LAYER_COUNT} schedule JSONs in {schedule_dir}, found {len(schedule_files)}"
        )
    schedules: dict[str, tuple[Path, dict[str, Any], str]] = {}
    arch_digest = sha256(arch_yaml)
    mapspace_digest = sha256(mapspace_yaml)
    for path in schedule_files:
        schedule = read_json(path)
        layer = schedule.get("layer_name")
        if not isinstance(layer, str) or layer != path.stem:
            raise SystemExit(f"schedule layer_name does not match filename: {path}")
        if layer in schedules:
            raise SystemExit(f"duplicate schedule layer: {layer}")
        if schedule.get("arch") != ARCH:
            raise SystemExit(f"schedule architecture is not {ARCH!r}: {path}")
        if schedule.get("mode") != args.expected_mode:
            raise SystemExit(
                f"schedule mode is {schedule.get('mode')!r}, expected {args.expected_mode!r}: {path}"
            )
        schedule_status(schedule, path)
        if schedule.get("arch_yaml_sha256") != arch_digest:
            raise SystemExit(f"architecture hash mismatch in schedule: {path}")
        if schedule.get("mapspace_yaml_sha256") != mapspace_digest:
            raise SystemExit(f"mapspace hash mismatch in schedule: {path}")
        schedules[layer] = (path, schedule, sha256(path))
    if set(schedules) != set(layers):
        missing = sorted(set(layers) - set(schedules))
        extra = sorted(set(schedules) - set(layers))
        raise SystemExit(f"schedule/capture layer mismatch; missing={missing}, extra={extra}")

    schedule_cache = schedule_dir.parent.parent
    cases: list[dict[str, Any]] = []
    for sample in range(SAMPLE_START, SAMPLE_START + SAMPLE_COUNT):
        for layer_index, layer in enumerate(layers):
            schedule_path, schedule, schedule_digest = schedules[layer]
            cases.append({
                "case_index": len(cases),
                "sample": sample,
                "sample_name": f"sample_{sample:03d}",
                "layer_index": layer_index,
                "arch": ARCH,
                "trace_relative_dir": args.trace_relative_dir,
                "layer": layer,
                "schedule_path": str(schedule_path),
                "schedule_sha256": schedule_digest,
                "mode": schedule["mode"],
                "schedule_arch_yaml_sha256": schedule["arch_yaml_sha256"],
                "schedule_mapspace_yaml_sha256": schedule["mapspace_yaml_sha256"],
            })

    output_root = Path(args.output_root).expanduser().resolve()
    manifest = {
        "schema": "stokes_phase_a_manifest/v1",
        "phase": "A-trace-generation",
        "created_for": "loas_vgg16_T4_n500",
        "arch": ARCH,
        "expected_mode": args.expected_mode,
        "sample_start": SAMPLE_START,
        "sample_count": SAMPLE_COUNT,
        "capture_sample_count": FULL_SAMPLE_COUNT,
        "layer_count": len(layers),
        "case_count": len(cases),
        "repo": str(repo),
        "stage_root": str(stage_root),
        "capture_root": str(capture_root),
        "trace_relative_dir": args.trace_relative_dir,
        "capture_meta": str(meta_path),
        "schedule_dir": str(schedule_dir),
        "schedule_cache": str(schedule_cache),
        "arch_yaml": str(arch_yaml),
        "mapspace_yaml": str(mapspace_yaml),
        "output_root": str(output_root),
        "wcts_root": str(output_root / "wcts"),
        "receipt_root": str(output_root / "receipts"),
        "log_root": str(output_root / "logs"),
        "layers": layers,
        "source_hashes": {
            "capture_meta_sha256": sha256(meta_path),
            "arch_yaml_sha256": arch_digest,
            "mapspace_yaml_sha256": mapspace_digest,
            "stage1_worker_sha256": sha256(worker),
        },
        "generator": {
            "reuse": "zoo/fig12_edp/stokes/stage1_worker.py:pipeline generation command",
            "argv": [
                "{python}", "-m", "lays.weight_trace_gen", "gen",
                "--arch", "{arch}", "--trace-root", "{trace_root}",
                "--trace-dir", "{trace_dir}", "--layer", "{layer}",
                "--schedule-cache", "{schedule_cache}", "--stream",
                "--sample-start", "{sample}", "--sample-count", "1",
                "--workers", "1",
            ],
            "stdout": "wcts temporary file; retained and renamed after trailer validation",
        },
        "cases": cases,
    }
    return manifest


def parser() -> argparse.ArgumentParser:
    stage_default = Path.home() / "snn_edp_stokes_20261114"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", default=str(stage_default))
    parser.add_argument("--repo", default=str(REPO_DEFAULT))
    parser.add_argument("--capture-root")
    parser.add_argument("--trace-relative-dir", default=str(TRACE_RELATIVE_DIR))
    parser.add_argument("--schedule-dir")
    parser.add_argument("--arch-yaml")
    parser.add_argument("--mapspace-yaml")
    parser.add_argument("--output-root")
    parser.add_argument("--expected-mode", default="gb_oooo")
    parser.add_argument("--manifest", default=str(KIT / "phase_a_manifest.json"))
    return parser


def main() -> None:
    args = parser().parse_args()
    stage_root = Path(args.stage_root).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    args.capture_root = args.capture_root or str(stage_root / "input_trace_full500")
    args.schedule_dir = args.schedule_dir or str(
        stage_root / "schedules/schedules/loas/loas_vgg16_T4_n500"
    )
    args.arch_yaml = args.arch_yaml or str(repo / "zoo/wt500_fig3cfg/arch.yaml")
    args.mapspace_yaml = args.mapspace_yaml or str(repo / "zoo/wt500_fig3cfg/mapspaces/loas.yaml")
    args.output_root = args.output_root or str(stage_root / "cache_dse_stokes_phase_a")
    manifest = build_manifest(args)
    atomic_json(Path(args.manifest), manifest)
    print(
        f"wrote {args.manifest}: {manifest['case_count']} cases, "
        f"{manifest['layer_count']} layers, samples "
        f"{manifest['sample_start']:03d}-{manifest['sample_start'] + manifest['sample_count'] - 1:03d}, "
        f"mode={manifest['expected_mode']}"
    )


if __name__ == "__main__":
    main()
