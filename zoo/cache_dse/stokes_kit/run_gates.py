#!/usr/bin/env python3
"""Run the mandatory V0 identity, Belady pilot, and FN-CACTI pilot gates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import resource
import struct
import subprocess
import sys
import time
from typing import Any


THREAD_ENV = {name: "1" for name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "RAYON_NUM_THREADS", "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_MAX_THREADS", "POLARS_MAX_THREADS",
    "TBB_NUM_THREADS", "GOTO_NUM_THREADS")}
VOLATILE_COLUMNS = {"run_id", "sim_wall_seconds"}
ACCESS_LOG_MAGIC = 0x5743414C4F473031


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_row(path: Path) -> dict[str, str]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RuntimeError(f"expected one row in {path}, found {len(rows)}")
    row = rows[0]
    if row.get("max_wait_depth") != "0":
        raise RuntimeError(f"max_wait_depth is not zero in {path}")
    return row


def l2_demand_stream(path: Path) -> list[int]:
    raw = path.read_bytes()
    if len(raw) < 8 or struct.unpack_from("<Q", raw)[0] != ACCESS_LOG_MAGIC:
        raise RuntimeError(f"invalid access-log header: {path}")
    payload = raw[8:]
    if len(payload) % 8:
        raise RuntimeError(f"truncated access-log record: {path}")
    return [line for level, core, demand, pad, line in struct.iter_unpack("<BBBBI", payload)
            if level == 1 and demand == 1]


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(partial, path)


def run_binary(command: list[str], repo: Path, log: Path, env: dict[str, str]) -> tuple[float, int]:
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                   stderr=stream, start_new_session=True)
        if hasattr(os, "wait4"):
            _, status, usage = os.wait4(process.pid, 0)
            if os.WIFEXITED(status):
                returncode = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                returncode = -os.WTERMSIG(status)
            else:
                returncode = 1
            process.returncode = returncode
        else:
            returncode = process.wait()
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed = time.monotonic() - started
    if returncode:
        raise RuntimeError(f"cachesim gate failed with exit {returncode}; see {log}")
    # Linux reports ru_maxrss in KiB.  wait4 gives the usage of this command,
    # rather than the process-wide maximum over all earlier gate children; the
    # explicit RUSAGE_CHILDREN read keeps the gate's resource accounting
    # visible on platforms where wait4 reports zero for a short-lived child.
    children_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    peak_rss_kib = int(usage.ru_maxrss or children_usage.ru_maxrss)
    return elapsed, peak_rss_kib


def compare_v0(reference: dict[str, str], actual: dict[str, str]) -> list[dict[str, str]]:
    fields = sorted((set(reference) | set(actual)) - VOLATILE_COLUMNS)
    return [{"field": field, "reference": reference.get(field, ""), "actual": actual.get(field, "")}
            for field in fields if reference.get(field, "") != actual.get(field, "")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cacti-delegated", action="store_true",
                        help="record the FN-CACTI pilot as delegated to a host whose glibc "
                             "runs the vendored binary (Stokes ships glibc 2.28; the binary "
                             "needs 2.34), instead of running it here")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "stokes_cache_dse_manifest/v1":
        raise SystemExit(f"unsupported manifest schema: {manifest.get('schema')!r}")
    repo = Path(manifest["repo"])
    binary = Path(manifest["binary"])
    baseline_path = Path(manifest["baseline_csv"])
    config = next(c for c in manifest["configs"] if c["id"] == "V0")
    belady = next(c for c in manifest["configs"] if c["id"] == "V4")
    trace = next(t for t in manifest["traces"]
                 if t["sample"] == 0 and t["layer"] == "layer_08_core_features_27")
    for path in (binary, baseline_path, Path(config["config_path"]), Path(belady["config_path"]), Path(trace["path"])):
        if not path.is_file():
            raise SystemExit(f"gate input is missing: {path}")
    if digest(binary) != manifest["binary_sha256"]:
        raise SystemExit("cachesim binary changed since manifest creation")
    if digest(Path(config["config_path"])) != config["config_sha256"]:
        raise SystemExit("V0 config changed since manifest creation")
    if digest(Path(belady["config_path"])) != belady["config_sha256"]:
        raise SystemExit("V4 config changed since manifest creation")
    gate_root = Path(manifest["output_root"]) / "gates"
    gate_root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **THREAD_ENV, "PYTHONDONTWRITEBYTECODE": "1",
           "TMPDIR": os.environ.get("TMPDIR", "/dev/shm")}
    v0_csv = gate_root / "v0.csv"
    access = gate_root / "v0.access.bin"
    v0_log = gate_root / "v0.log"
    v0_command = [str(binary), "--trace", trace["path"], "--config", config["config_path"],
                  "--arm", "cache", "--header", "--out", str(v0_csv),
                  "--access-log", str(access), "--run-id", "t71_gate_v0"]
    v0_seconds, v0_peak_rss_kib = run_binary(v0_command, repo, v0_log, env)
    actual = load_row(v0_csv)
    with baseline_path.open(newline="") as stream:
        reference = next(csv.DictReader(stream))
    mismatches = compare_v0(reference, actual)
    if mismatches:
        save(gate_root / "v0_mismatches.json", {"status": "fail", "mismatches": mismatches})
        raise SystemExit(f"V0 byte-identity gate failed: {len(mismatches)} stable fields differ")
    v4_csv = gate_root / "belady_v4.csv"
    v4_log = gate_root / "belady_v4.log"
    current_oracle = access
    oracle_stream = l2_demand_stream(current_oracle)
    v4_seconds = 0.0
    v4_peak_rss_kib = 0
    v4_iterations = 0
    fixpoint = False
    for iteration in range(3):
        v4_access = gate_root / f"belady_v4_iter{iteration}.access.bin"
        v4_command = [str(binary), "--trace", trace["path"], "--config", belady["config_path"],
                      "--arm", "cache", "--header", "--out", str(v4_csv),
                      "--l2-oracle", str(current_oracle), "--access-log", str(v4_access),
                      "--run-id", f"t71_gate_v4_iter{iteration}"]
        elapsed, peak_rss_kib = run_binary(v4_command, repo, v4_log, env)
        v4_seconds += elapsed
        v4_peak_rss_kib = max(v4_peak_rss_kib, peak_rss_kib)
        v4_iterations = iteration + 1
        belady_row = load_row(v4_csv)
        candidate_stream = l2_demand_stream(v4_access)
        if candidate_stream == oracle_stream:
            fixpoint = True
            break
        current_oracle = v4_access
        oracle_stream = candidate_stream
    if not fixpoint:
        save(gate_root / "belady_fixpoint.json", {
            "status": "fail", "iterations": v4_iterations,
            "oracle_l2_refs": len(oracle_stream),
            "candidate_l2_refs": len(candidate_stream),
        })
        raise SystemExit("Belady L2 access-log did not reach a fixpoint in three iterations")
    if args.cacti_delegated:
        cacti_pilot = {"status": "delegated",
                       "reason": "vendored cacti binary needs glibc >= 2.34; harvest runs on Delta "
                                 "and ships to cacti/harvest.json before aggregate"}
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from cacti_reharvest import GEOMETRIES, harvest_one
        cacti_dir = gate_root / "cacti_pilot"
        cacti = harvest_one(repo, cacti_dir, "l1_8192", GEOMETRIES["l1_8192"])
        cacti_pilot = {"status": "pass", "geometry": cacti}
    result = {
        "schema": "stokes_cache_dse_gates/v1", "status": "pass",
        "v0_identity": {"status": "pass", "compared_fields": len(reference) - len(VOLATILE_COLUMNS),
                        "stable_columns": sorted(set(reference) - VOLATILE_COLUMNS),
                        "total_cycles": int(actual["total_cycles"]), "wall_seconds": v0_seconds,
                        "peak_rss_kib": v0_peak_rss_kib},
        "belady_pilot": {"status": "pass", "total_cycles": int(belady_row["total_cycles"]),
                          "max_wait_depth": int(belady_row["max_wait_depth"]), "wall_seconds": v4_seconds,
                          "peak_rss_kib": v4_peak_rss_kib,
                          "oracle_sha256": digest(current_oracle),
                          "initial_oracle_sha256": digest(access),
                          "access_log_sha256": digest(v4_access),
                          "l2_demand_references": len(oracle_stream),
                          "fixpoint_iterations": v4_iterations},
        "cacti_pilot": cacti_pilot,
        "manifest_sha256": digest(manifest_path),
    }
    save(Path(manifest["gates_path"]), result)
    print(json.dumps({"status": "pass", "v0_cycles": actual["total_cycles"],
                      "belady_cycles": belady_row["total_cycles"],
                      "cacti": cacti_pilot.get("geometry", {}).get("name", cacti_pilot["status"])},
                     sort_keys=True))


if __name__ == "__main__":
    main()
