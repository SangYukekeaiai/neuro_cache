#!/usr/bin/env python3
"""Run one cache-DSE case, or one V0 access-log prepass, on Stokes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any


THREAD_ENV = {name: "1" for name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "RAYON_NUM_THREADS", "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_MAX_THREADS", "POLARS_MAX_THREADS",
    "TBB_NUM_THREADS", "GOTO_NUM_THREADS")}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(partial, path)


def read_row(path: Path) -> dict[str, str]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RuntimeError(f"expected one cachesim row in {path}, found {len(rows)}")
    row = rows[0]
    if row.get("arm") != "cache":
        raise RuntimeError(f"unexpected arm in {path}: {row.get('arm')!r}")
    if row.get("max_wait_depth") != "0":
        raise RuntimeError(f"max_wait_depth is not zero in {path}: {row.get('max_wait_depth')!r}")
    if not row.get("total_cycles") or int(row["total_cycles"]) < 1:
        raise RuntimeError(f"invalid total_cycles in {path}")
    return row


def config_by_id(manifest: dict[str, Any], variant: str) -> dict[str, Any]:
    for config in manifest["configs"]:
        if config["id"] == variant:
            return config
    raise RuntimeError(f"unknown variant: {variant}")


def trace_by_index(manifest: dict[str, Any], trace_index: int) -> dict[str, Any]:
    traces = manifest["traces"]
    if not 0 <= trace_index < len(traces):
        raise RuntimeError(f"trace index must be in 0..{len(traces) - 1}")
    return traces[trace_index]


def ensure_inputs(manifest: dict[str, Any], config: dict[str, Any], trace: dict[str, Any]) -> tuple[Path, Path]:
    binary = Path(manifest["binary"])
    config_path = Path(config["config_path"])
    trace_path = Path(trace["path"])
    for path, label in ((binary, "cachesim binary"), (config_path, "config"), (trace_path, "WCTS")):
        if not path.is_file():
            raise RuntimeError(f"{label} is missing: {path}")
    if digest(binary) != manifest["binary_sha256"]:
        raise RuntimeError("cachesim binary changed since manifest creation")
    if digest(config_path) != config["config_sha256"]:
        raise RuntimeError(f"config changed since manifest creation: {config_path}")
    if digest(trace_path) != trace["sha256"]:
        raise RuntimeError(f"trace changed since manifest creation: {trace_path}")
    return binary, config_path


def require_gate(manifest: dict[str, Any]) -> None:
    gate = Path(manifest["gates_path"])
    if not gate.is_file():
        raise RuntimeError(f"gates have not passed: {gate}")
    value = load(gate)
    if value.get("status") != "pass":
        raise RuntimeError(f"gates are not passing: {gate}")
    expected_manifest = manifest.get("_manifest_sha256")
    if expected_manifest and value.get("manifest_sha256") != expected_manifest:
        raise RuntimeError("gate receipt belongs to a different manifest")


def run_binary(command: list[str], repo: Path, log: Path, env: dict[str, str]) -> float:
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                stderr=stream, check=False, start_new_session=True)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        raise RuntimeError(f"cachesim failed with exit {result.returncode}; see {log}")
    return elapsed


def output_paths(manifest: dict[str, Any], case: dict[str, Any]) -> tuple[Path, Path, Path]:
    root = Path(manifest["raw_root"]) / case["variant"] / case["sample_name"]
    stem = case["layer"]
    return root / f"{stem}.csv", root / f"{stem}.json", root / f"{stem}.log"


def existing_raw(csv_path: Path, receipt_path: Path, case: dict[str, Any],
                 oracle: Path | None) -> bool:
    if not csv_path.exists() and not receipt_path.exists():
        return False
    if not csv_path.is_file() or not receipt_path.is_file():
        raise RuntimeError(f"incomplete raw output: {csv_path}")
    receipt = load(receipt_path)
    if receipt.get("status") != "complete" or receipt.get("case_index") != case["case_index"]:
        raise RuntimeError(f"raw receipt is not complete: {receipt_path}")
    row = read_row(csv_path)
    if receipt.get("csv_sha256") != digest(csv_path) or receipt.get("total_cycles") != int(row["total_cycles"]):
        raise RuntimeError(f"raw CSV differs from receipt: {csv_path}")
    if oracle is not None:
        if receipt.get("oracle_path") != str(oracle) or receipt.get("oracle_sha256") != digest(oracle):
            raise RuntimeError(f"Belady oracle differs from receipt: {csv_path}")
    return True


def run_sweep_case(manifest: dict[str, Any], case: dict[str, Any], force: bool) -> str:
    require_gate(manifest)
    config = config_by_id(manifest, case["variant"])
    trace = trace_by_index(manifest, case["trace_index"])
    csv_path, receipt_path, log_path = output_paths(manifest, case)
    oracle = None
    if config["belady"]:
        oracle = Path(manifest["oracle_root"]) / trace["sample_name"] / f"{trace['layer']}.access.bin"
        if not oracle.is_file():
            raise RuntimeError(f"Belady oracle prepass is missing: {oracle}")
    if not force and existing_raw(csv_path, receipt_path, case, oracle):
        print(f"case {case['case_index']} already complete: {csv_path}")
        return "resumed"
    binary, config_path = ensure_inputs(manifest, config, trace)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    partial = csv_path.with_name(csv_path.name + ".part")
    partial.unlink(missing_ok=True)
    env = {**os.environ, **THREAD_ENV, "PYTHONDONTWRITEBYTECODE": "1"}
    repo = Path(manifest["repo"]) if "repo" in manifest else Path(__file__).resolve().parents[2]
    env["TMPDIR"] = env.get("TMPDIR", "/dev/shm")
    command = [str(binary), "--trace", trace["path"], "--config", str(config_path),
               "--arm", "cache", "--header", "--out", str(partial), "--run-id",
               f"t71_{case['variant']}_{case['sample_name']}_{case['layer']}"]
    if oracle is not None:
        command.extend(["--l2-oracle", str(oracle)])
    elapsed = run_binary(command, repo, log_path, env)
    row = read_row(partial)
    os.replace(partial, csv_path)
    save(receipt_path, {
        "schema": "stokes_cache_dse_row_receipt/v1", "status": "complete",
        "case_index": case["case_index"], "variant": case["variant"],
        "sample": case["sample"], "sample_name": case["sample_name"],
        "layer": case["layer"], "trace_index": case["trace_index"],
        "trace_sha256": trace["sha256"], "config_sha256": config["config_sha256"],
        "oracle_path": str(oracle) if oracle else None,
        "oracle_sha256": digest(oracle) if oracle else None,
        "csv_path": str(csv_path), "csv_sha256": digest(csv_path),
        "total_cycles": int(row["total_cycles"]), "max_wait_depth": int(row["max_wait_depth"]),
        "wall_seconds": elapsed,
    })
    print(f"case {case['case_index']} complete: {case['variant']} {case['sample_name']} {case['layer']}")
    return "complete"


def prepass_paths(manifest: dict[str, Any], trace: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    root = Path(manifest["oracle_root"]) / trace["sample_name"]
    prepass = Path(manifest["prepass_root"]) / trace["sample_name"]
    stem = trace["layer"]
    return (root / f"{stem}.access.bin", root / f"{stem}.json",
            prepass / f"{stem}.csv", prepass / f"{stem}.log")


def run_prepass(manifest: dict[str, Any], trace_index: int, force: bool) -> str:
    require_gate(manifest)
    config = config_by_id(manifest, "V0")
    trace = trace_by_index(manifest, trace_index)
    access, receipt, csv_path, log_path = prepass_paths(manifest, trace)
    if not force and access.exists() and receipt.exists() and csv_path.exists():
        value = load(receipt)
        if (value.get("status") == "complete" and value.get("access_sha256") == digest(access)
                and value.get("trace_sha256") == trace["sha256"]):
            read_row(csv_path)
            print(f"prepass {trace_index} already complete: {access}")
            return "resumed"
    binary, config_path = ensure_inputs(manifest, config, trace)
    access.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    access_part = access.with_name(access.name + ".part")
    csv_part = csv_path.with_name(csv_path.name + ".part")
    access_part.unlink(missing_ok=True); csv_part.unlink(missing_ok=True)
    env = {**os.environ, **THREAD_ENV, "PYTHONDONTWRITEBYTECODE": "1",
           "TMPDIR": os.environ.get("TMPDIR", "/dev/shm")}
    repo = Path(manifest["repo"]) if "repo" in manifest else Path(__file__).resolve().parents[2]
    command = [str(binary), "--trace", trace["path"], "--config", str(config_path),
               "--arm", "cache", "--header", "--out", str(csv_part),
               "--access-log", str(access_part), "--run-id",
               f"t71_prepass_{trace['sample_name']}_{trace['layer']}"]
    elapsed = run_binary(command, repo, log_path, env)
    row = read_row(csv_part)
    os.replace(csv_part, csv_path)
    os.replace(access_part, access)
    save(receipt, {
        "schema": "stokes_cache_dse_oracle_receipt/v1", "status": "complete",
        "trace_index": trace_index, "sample": trace["sample"], "layer": trace["layer"],
        "trace_sha256": trace["sha256"], "config_sha256": config["config_sha256"],
        "access_path": str(access), "access_sha256": digest(access),
        "csv_path": str(csv_path), "csv_sha256": digest(csv_path),
        "total_cycles": int(row["total_cycles"]), "max_wait_depth": int(row["max_wait_depth"]),
        "wall_seconds": elapsed,
    })
    print(f"prepass {trace_index} complete: {access}")
    return "complete"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--case-index", type=int)
    parser.add_argument("--prepass", action="store_true")
    parser.add_argument("--trace-index", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = load(Path(args.manifest).expanduser().resolve())
    if manifest.get("schema") != "stokes_cache_dse_manifest/v1":
        raise SystemExit(f"unsupported manifest schema: {manifest.get('schema')!r}")
    manifest["_manifest_sha256"] = digest(Path(args.manifest).expanduser().resolve())
    if args.prepass:
        if args.trace_index is None or args.case_index is not None:
            raise SystemExit("--prepass requires --trace-index and no --case-index")
        run_prepass(manifest, args.trace_index, args.force)
    else:
        if args.case_index is None or args.trace_index is not None:
            raise SystemExit("sweep mode requires --case-index and no --trace-index")
        cases = manifest["cases"]
        if not 0 <= args.case_index < len(cases):
            raise SystemExit(f"case index must be in 0..{len(cases) - 1}")
        run_sweep_case(manifest, cases[args.case_index], args.force)


if __name__ == "__main__":
    main()
