#!/usr/bin/env python3
"""Run every generated architecture config against every workload config."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arch-root",
        default="configs/arch/sweep",
        help="root containing generated architecture YAMLs",
    )
    parser.add_argument(
        "--workload-root",
        default="configs/workloads",
        help="root containing workload YAMLs",
    )
    parser.add_argument(
        "--mapspace",
        default="configs/mapspace/mapspace.yaml",
        help="mapspace YAML used for every run",
    )
    parser.add_argument(
        "--out-root",
        default="outputs/sweeps",
        help="root directory for hierarchical schedule outputs",
    )
    parser.add_argument("--time-limit", type=float, default=None, help="Gurobi time limit")
    parser.add_argument("--mip-gap", type=float, default=None, help="Gurobi MIP gap")
    parser.add_argument("--solver-log", action="store_true", help="show solver log")
    parser.add_argument("--skip-existing", action="store_true", help="skip existing schedules")
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    args = parser.parse_args()

    arch_paths = _yaml_files(Path(args.arch_root))
    workload_paths = _yaml_files(Path(args.workload_root))
    total = len(arch_paths) * len(workload_paths)
    print(f"arch configs: {len(arch_paths)}")
    print(f"workloads: {len(workload_paths)}")
    print(f"runs: {total}")

    failures = 0
    for arch_path in arch_paths:
        for workload_path in workload_paths:
            out_dir = _output_dir(Path(args.out_root), arch_path, workload_path)
            schedule_path = out_dir / "schedule.json"
            if args.skip_existing and schedule_path.exists():
                continue

            cmd = _solve_command(args, arch_path, workload_path, schedule_path)
            if args.dry_run:
                print(" ".join(str(part) for part in cmd))
                continue

            out_dir.mkdir(parents=True, exist_ok=True)
            _write_metadata(out_dir, cmd, arch_path, workload_path)
            result = subprocess.run(
                cmd,
                cwd=Path.cwd(),
                env=_env_with_pythonpath(),
                text=True,
                capture_output=True,
                check=False,
            )
            (out_dir / "stdout.txt").write_text(result.stdout)
            (out_dir / "stderr.txt").write_text(result.stderr)
            if result.returncode != 0:
                failures += 1
                print(f"FAIL {result.returncode}: {arch_path} x {workload_path}")

    if failures:
        print(f"completed with {failures} failed runs")
        return 1
    print("completed sweep")
    return 0


def _yaml_files(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("*.yaml") if path.is_file())


def _output_dir(out_root: Path, arch_path: Path, workload_path: Path) -> Path:
    arch_parts = arch_path.with_suffix("").parts
    try:
        arch_rel = Path(*arch_parts[arch_parts.index("sweep") + 1 :])
    except ValueError:
        arch_rel = Path(arch_path.stem)

    workload_rel = workload_path.with_suffix("")
    if workload_rel.parts[:2] == ("configs", "workloads"):
        workload_rel = Path(*workload_rel.parts[2:])

    return out_root / arch_rel / workload_rel


def _solve_command(
    args: argparse.Namespace,
    arch_path: Path,
    workload_path: Path,
    schedule_path: Path,
) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "snn_cosa",
        "solve",
        "--layer",
        str(workload_path),
        "--arch",
        str(arch_path),
        "--mapspace",
        args.mapspace,
        "--out",
        str(schedule_path),
    ]
    if args.time_limit is not None:
        cmd.extend(["--time-limit", str(args.time_limit)])
    if args.mip_gap is not None:
        cmd.extend(["--mip-gap", str(args.mip_gap)])
    if args.solver_log:
        cmd.append("--solver-log")
    return cmd


def _write_metadata(out_dir: Path, cmd: List[str], arch_path: Path, workload_path: Path) -> None:
    metadata = {
        "command": cmd,
        "arch": str(arch_path),
        "workload": str(workload_path),
    }
    with open(out_dir / "run.json", "w") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")


def _env_with_pythonpath() -> dict:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else f"{src_path}:{existing}"
    return env


if __name__ == "__main__":
    raise SystemExit(main())
