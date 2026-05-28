#!/usr/bin/env python3
"""Command-line interface for SNN CoSA."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, Optional

from gurobipy import GurobiError

from snn_cosa.solver import solve_schedule


DEFAULT_LAYER = "configs/workloads/sample_snn_layer.yaml"
DEFAULT_ARCH = "configs/arch/snn_arch.yaml"
DEFAULT_MAPSPACE = "configs/mapspace/mapspace.yaml"
DEFAULT_OUT = "outputs/schedule.json"


def main(argv: Optional[list[str]] = None) -> int:
    """Run the SNN CoSA command-line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "solve":
        return _run_solve(args)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m snn_cosa",
        description="Solve SNN CoSA mapping schedules.",
    )
    subparsers = parser.add_subparsers(dest="command")

    solve = subparsers.add_parser(
        "solve",
        help="solve one SNN layer schedule and write JSON output",
    )
    solve.add_argument("--layer", default=DEFAULT_LAYER, help="layer YAML path")
    solve.add_argument("--arch", default=DEFAULT_ARCH, help="architecture YAML path")
    solve.add_argument(
        "--mapspace",
        default=DEFAULT_MAPSPACE,
        help="mapspace YAML path; use an empty string to skip it",
    )
    solve.add_argument("--out", default=DEFAULT_OUT, help="output JSON path")
    solve.add_argument("--time-limit", type=float, default=None, help="seconds")
    solve.add_argument("--mip-gap", type=float, default=None, help="relative MIP gap")
    solve.add_argument(
        "--solver-log",
        action="store_true",
        help="show Gurobi solver log",
    )
    return parser


def _run_solve(args: argparse.Namespace) -> int:
    mapspace = args.mapspace if args.mapspace else None
    try:
        result = solve_schedule(
            layer_path=args.layer,
            arch_path=args.arch,
            mapspace_path=mapspace,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
            output_flag=args.solver_log,
        )
    except (FileNotFoundError, ValueError, GurobiError) as exc:
        print(f"snn_cosa solve failed: {exc}", file=sys.stderr)
        return 2

    out_path = pathlib.Path(args.out)
    _write_json(result, out_path)
    _print_summary(result, out_path)
    return 0 if result["has_solution"] else 3


def _write_json(result: Dict[str, Any], out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")


def _print_summary(result: Dict[str, Any], out_path: pathlib.Path) -> None:
    status = result["status"]
    objective = result["objective"]
    print(f"status: {status}")
    if objective is not None:
        print(f"objective: {objective:.6f}")
    print(f"output: {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
