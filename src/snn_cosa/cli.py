#!/usr/bin/env python3
"""Command-line interface for SNN CoSA."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional

from gurobipy import GurobiError

from snn_cosa.enumerator import enumerate_modes
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
    if args.command == "enumerate":
        return _run_enumerate(args)

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

    enum_p = subparsers.add_parser(
        "enumerate",
        help="enumerate all traffic-mode variants and report the globally optimal schedule",
    )
    enum_p.add_argument("--layer", default=DEFAULT_LAYER, help="layer YAML path")
    enum_p.add_argument("--arch", default=DEFAULT_ARCH, help="architecture YAML path")
    enum_p.add_argument(
        "--mapspace",
        default=DEFAULT_MAPSPACE,
        help="mapspace YAML path; use an empty string to skip it",
    )
    enum_p.add_argument("--out", default="outputs/enumeration.json", help="output JSON path")
    enum_p.add_argument("--time-limit", type=float, default=None, help="per-mode seconds")
    enum_p.add_argument("--mip-gap", type=float, default=None, help="per-mode relative MIP gap")
    enum_p.add_argument(
        "--solver-log",
        action="store_true",
        help="show Gurobi solver log for each mode",
    )
    enum_p.add_argument(
        "--w-u", type=float, default=0.1,
        help="weight for utilization sum term (default: 0.1)",
    )
    enum_p.add_argument(
        "--w-tr", type=float, default=1.0,
        help="weight for per-variable traffic product sum (default: 1.0)",
    )
    enum_p.add_argument(
        "--w-dl", type=float, default=10.0,
        help="weight for compute-latency delay term (default: 10.0)",
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


def _run_enumerate(args: argparse.Namespace) -> int:
    mapspace = args.mapspace if args.mapspace else None
    try:
        result = enumerate_modes(
            layer_path=args.layer,
            arch_path=args.arch,
            mapspace_path=mapspace,
            w_u=args.w_u,
            w_tr=args.w_tr,
            w_dl=args.w_dl,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
            output_flag=args.solver_log,
        )
    except (FileNotFoundError, ValueError, GurobiError) as exc:
        print(f"snn_cosa enumerate failed: {exc}", file=sys.stderr)
        return 2

    out_path = pathlib.Path(args.out)
    _write_json(result, out_path)
    summary = format_enumeration_summary(result, str(out_path))
    sys.stdout.write(summary)
    out_path.with_suffix(".txt").write_text(summary)
    return 0 if result["best_mode"] else 3


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


_WRAP_WIDTH = 80


def _print_enumeration_summary(result: Dict[str, Any], out_path: pathlib.Path) -> None:
    w = result["weights"]
    print(f"weights: w_u={w['w_u']}  w_tr={w['w_tr']}  w_dl={w['w_dl']}")
    print()

    candidates = sorted(
        result["candidates"],
        key=lambda c: (c["comparison_score"] is None, c["comparison_score"] or 0),
    )
    best_mode = result["best_mode"]

    for rank, c in enumerate(candidates, 1):
        marker = "*" if c["mode"] == best_mode else " "
        score_str = (
            f"score={c['comparison_score']:.4e}"
            if c["comparison_score"] is not None
            else "infeasible"
        )
        print(f"#{rank}{marker} {c['mode']:<22}  {score_str}  {c['status']}")

        if c.get("strategy"):
            s = c["strategy"]
            _print_wrapped("  dram: ", _fmt_perm(s["DRAM"]["temporal_permutation"]["loops"]))
            _print_wrapped("  gb:   ", _fmt_perm(s["NoCLevel"]["temporal_permutation"]["loops"]))
            _print_wrapped("  sp:   ", _fmt_unordered(s["NoCLevel"]["spatial_splitting"]["loops"]))
            _print_wrapped("  node: ", _fmt_unordered(s["NodeLevel"]["temporal_tile"]["factors"]))
            pe_sp = _fmt_unordered(s["NodeLevel"]["spatial_split"]["factors"])
            if pe_sp != "none":
                _print_wrapped("  pe_sp:", pe_sp)

        if c.get("metrics"):
            m = c["metrics"]
            util_total = sum(m["util"].values())
            traffic_total = sum(
                m["util"][v] * m["spatial_cost"][v] * m["temporal_traffic"][v]
                for v in m["util"]
            )
            cap = m.get("capacity")
            if cap:
                cap_total = sum(cap.values())
                util_str = (
                    f"{_autoscale(util_total)}/{_autoscale(cap_total)}"
                    f" ({100 * util_total / cap_total:.0f}%)"
                )
            else:
                util_str = _autoscale(util_total)
            print(
                f"  latency={m['delay']:,}  "
                f"traffic={_autoscale(traffic_total)}  "
                f"util={util_str}"
            )
            if cap:
                parts = [
                    f"{v}={_autoscale(m['util'][v])}/{_autoscale(cap[v])}"
                    f" ({100 * m['util'][v] / cap[v]:.0f}%)"
                    for v in m["util"]
                ]
                print("  util/cap: " + "  ".join(parts))

        print()

    if best_mode:
        print(f"best: {best_mode}  score={result['best_comparison_score']:.4e}")
    else:
        print("no feasible solution found")
    print(f"output: {out_path}")


def format_enumeration_summary(result: Dict[str, Any], label: str = "") -> str:
    """Return the full enumeration summary as a formatted string.

    label is appended as the final "output: <label>" line; pass an empty
    string to omit it (e.g. when the caller will write the text elsewhere).
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _print_enumeration_summary(result, label)
    return buf.getvalue()


def _fmt_perm(loops: List[Dict[str, Any]]) -> str:
    """Format temporal permutation loops, fusing only adjacent same-dim entries."""
    if not loops:
        return "none"
    dims: List[str] = []
    sizes: List[int] = []
    for loop in loops:
        if dims and dims[-1] == loop["dim"]:
            sizes[-1] *= loop["size"]
        else:
            dims.append(loop["dim"])
            sizes.append(loop["size"])
    return " → ".join(f"{d}={s}" for d, s in zip(dims, sizes))


def _fmt_unordered(loops: List[Dict[str, Any]]) -> str:
    """Format unordered factors (spatial/node tile), fusing all same-dim entries."""
    if not loops:
        return "none"
    totals: Dict[str, int] = {}
    order: List[str] = []
    for loop in loops:
        dim, size = loop["dim"], loop["size"]
        if dim not in totals:
            totals[dim] = 1
            order.append(dim)
        totals[dim] *= size
    return "  ".join(f"{d}={totals[d]}" for d in order)


def _autoscale(value: float) -> str:
    """Auto-scale a byte count to a human-readable string."""
    for unit, threshold in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
        if value >= threshold:
            return f"{value / threshold:.1f} {unit}"
    return f"{value:.0f} B"


def _print_wrapped(prefix: str, content: str) -> None:
    """Print prefix+content, wrapping at ' → ' boundaries when over _WRAP_WIDTH."""
    if len(prefix) + len(content) <= _WRAP_WIDTH:
        print(prefix + content)
        return
    indent = " " * len(prefix)
    tokens = content.split(" → ")
    line = prefix
    for i, tok in enumerate(tokens):
        sep = " → " if i < len(tokens) - 1 else ""
        if line != prefix and len(line) + len(tok) + len(sep) > _WRAP_WIDTH:
            print(line)
            line = indent + tok + sep
        else:
            line += tok + sep
    print(line)


if __name__ == "__main__":
    raise SystemExit(main())
