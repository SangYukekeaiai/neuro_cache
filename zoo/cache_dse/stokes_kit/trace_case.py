#!/usr/bin/env python3
"""Generate and retain one durable Stokes Phase-A weight trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any


THREAD_ENV = {
    name: "1"
    for name in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "RAYON_NUM_THREADS", "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS", "NUMEXPR_MAX_THREADS", "POLARS_MAX_THREADS",
        "TBB_NUM_THREADS", "GOTO_NUM_THREADS",
    )
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with temporary.open("w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_digest(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA256 mismatch: expected {expected}, got {actual}: {path}")


def check_trailer(path: Path) -> int:
    size = path.stat().st_size
    if size < 12:
        raise RuntimeError(f"WCTS is shorter than its 12-byte trailer: {path}")
    with path.open("rb") as stream:
        stream.seek(-12, os.SEEK_END)
        marker, records = struct.unpack("<iQ", stream.read(12))
    if marker != -1:
        raise RuntimeError(f"WCTS trailer marker is {marker}, expected -1: {path}")
    return records


def paths(manifest: dict[str, Any], case: dict[str, Any]) -> tuple[Path, Path, Path]:
    sample_name = case["sample_name"]
    layer = Path(case["layer"])
    if layer.name != case["layer"] or layer.suffix:
        raise RuntimeError(f"unsafe layer name: {case['layer']!r}")
    output_root = Path(manifest["output_root"])
    wcts = output_root / "wcts" / sample_name / f"{case['layer']}.wcts"
    receipt = output_root / "receipts" / sample_name / f"{case['layer']}.json"
    log = output_root / "logs" / sample_name / f"{case['layer']}.log"
    return wcts, receipt, log


def verify_existing(wcts: Path, receipt: Path, case: dict[str, Any]) -> bool:
    if not wcts.exists() and not receipt.exists():
        return False
    if not wcts.is_file() or not receipt.is_file():
        raise RuntimeError(f"incomplete durable output (trace and receipt must both exist): {wcts}")
    info = load(receipt)
    if info.get("status") == "pending":
        return False
    if info.get("status") != "complete":
        raise RuntimeError(f"receipt is not complete: {receipt}")
    if info.get("schedule_sha256") != case["schedule_sha256"]:
        raise RuntimeError(f"receipt schedule digest does not match manifest: {receipt}")
    records = check_trailer(wcts)
    actual = sha256(wcts)
    if info.get("wcts_sha256") != actual or info.get("records") != records:
        raise RuntimeError(f"durable trace does not match its receipt: {wcts}")
    return True


def validate_inputs(manifest: dict[str, Any], case: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    repo = Path(manifest["repo"])
    capture_dir = Path(manifest["capture_root"]) / case["trace_relative_dir"]
    meta = capture_dir / "meta.json"
    capture = capture_dir / f"{case['layer']}.npy"
    schedule = Path(case["schedule_path"])
    worker = repo / "zoo/fig12_edp/stokes/stage1_worker.py"
    arch_yaml = Path(manifest["arch_yaml"])
    mapspace_yaml = Path(manifest["mapspace_yaml"])
    for path, label in (
        (meta, "capture metadata"), (capture, "capture array"),
        (schedule, "schedule"), (worker, "Stage-A worker"),
        (arch_yaml, "architecture YAML"), (mapspace_yaml, "mapspace YAML"),
    ):
        if not path.is_file():
            raise RuntimeError(f"{label} is missing: {path}")
    check_digest(schedule, case["schedule_sha256"], "schedule")
    source = manifest["source_hashes"]
    check_digest(worker, source["stage1_worker_sha256"], "Stage-A worker")
    check_digest(arch_yaml, source["arch_yaml_sha256"], "architecture YAML")
    check_digest(mapspace_yaml, source["mapspace_yaml_sha256"], "mapspace YAML")
    metadata = load(meta)
    if metadata.get("n_samples") != manifest["capture_sample_count"]:
        raise RuntimeError(f"capture sample count changed: {meta}")
    if case["layer"] not in metadata.get("layers", {}):
        raise RuntimeError(f"layer is not present in capture metadata: {case['layer']}")
    return capture_dir, schedule, worker, arch_yaml


def generator_argv(manifest: dict[str, Any], case: dict[str, Any], python: str) -> list[str]:
    capture_dir = Path(manifest["capture_root"]) / case["trace_relative_dir"]
    # This is the same argv assembled by stage1_worker.pipeline, including
    # stream mode and one worker.  The wrapper only retains the stdout WCTS.
    return [
        python, "-m", "lays.weight_trace_gen", "gen",
        "--arch", case["arch"],
        "--trace-root", str(capture_dir.parent),
        "--trace-dir", capture_dir.name,
        "--layer", case["layer"],
        "--schedule-cache", manifest["schedule_cache"],
        "--stream",
        "--sample-start", str(case["sample"]),
        "--sample-count", "1",
        "--workers", "1",
    ]


def run_case(manifest: dict[str, Any], case: dict[str, Any], force: bool) -> str:
    wcts, receipt, log = paths(manifest, case)
    if not force and verify_existing(wcts, receipt, case):
        print(f"case {case['case_index']} already complete: {wcts}")
        return "resumed"
    validate_inputs(manifest, case)
    wcts.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    partial = wcts.with_name(wcts.name + ".part")
    env = os.environ.copy()
    env.update(THREAD_ENV)
    repo = Path(manifest["repo"])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["ARCHX_DISABLE_PERFORMANCE_CACHE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        str(path) for path in (repo, repo / "src", repo / "zoo/archx/zoo")
    )
    base_tmp = Path(env.get("TMPDIR", "/dev/shm"))
    base_tmp.mkdir(parents=True, exist_ok=True)
    command = generator_argv(manifest, case, sys.executable)
    temporary_dir = Path(tempfile.mkdtemp(prefix="t71-phase-a-", dir=base_tmp))
    env["TMPDIR"] = str(temporary_dir)
    try:
        with partial.open("wb") as stdout, log.open("w") as stderr:
            completed = subprocess.run(
                command,
                cwd=repo,
                env=env,
                stdout=stdout,
                stderr=stderr,
                check=False,
                start_new_session=True,
            )
            stdout.flush()
            os.fsync(stdout.fileno())
        if completed.returncode != 0:
            raise RuntimeError(
                f"trace generator failed with exit {completed.returncode}; see {log}"
            )
        records = check_trailer(partial)
        wcts_sha = sha256(partial)
        receipt_value = {
            "schema": "stokes_phase_a_receipt/v1",
            "status": "pending",
            "case_index": case["case_index"],
            "sample": case["sample"],
            "sample_name": case["sample_name"],
            "arch": case["arch"],
            "layer": case["layer"],
            "mode": case["mode"],
            "schedule_path": case["schedule_path"],
            "schedule_sha256": case["schedule_sha256"],
            "stage1_worker_sha256": manifest["source_hashes"]["stage1_worker_sha256"],
            "wcts_path": str(wcts),
            "wcts_sha256": wcts_sha,
            "wcts_bytes": wcts.stat().st_size,
            "records": records,
            "generator_command": command,
        }
        save_json(receipt, receipt_value)
        os.replace(partial, wcts)
        sync_dir(wcts.parent)
        receipt_value["status"] = "complete"
        save_json(receipt, receipt_value)
        print(f"case {case['case_index']} complete: {wcts} ({records} records, {wcts_sha})")
        return "complete"
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--case-index", required=True, type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load(manifest_path)
    if manifest.get("schema") != "stokes_phase_a_manifest/v1":
        raise SystemExit(f"unsupported manifest schema: {manifest.get('schema')!r}")
    cases = manifest.get("cases", [])
    if not 0 <= args.case_index < len(cases):
        raise SystemExit(f"case index must be in 0..{len(cases) - 1}")
    case = cases[args.case_index]
    if case.get("case_index") != args.case_index:
        raise SystemExit("manifest case indexes are not contiguous")
    run_case(manifest, case, args.force)


if __name__ == "__main__":
    main()
