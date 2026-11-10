#!/usr/bin/env python3
"""Solve the five published architectures on the Figure 3 arch + layer.

Each architecture is a node-mapspace YAML under mapspaces/.  This runs the
real scheduler (`python -m lays.scheduler solve`, Gurobi) once per mapspace
and records the delay term of its solution -- the marker position for the
histogram in plot.py.

The CLI's result JSON carries the fused mapping strategy rather than the
metrics block, so delay is recomputed here exactly as
src/lays/scheduler/metrics.py `_eval_delay` defines it: the product of every
temporally-assigned factor across all loop levels.  The spatial side of the
same strategy gives the node's PE/T fanout and the inter-node NoC fanout, so
each solution is also reported against the closed-form identity

    delay = total_work / (PE_spatial x T_spatial x NoC_fanout)

that enumerate.py uses.  Writes outputs/baselines.json.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONDA_ENV = "gurobi"


# ---------------------------------------------------------------------------
# Strategy JSON readers (shared with check_consistency.py)
# ---------------------------------------------------------------------------

def _loops(block: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return block.get(key, {}).get("loops", block.get(key, {}).get("factors", []))


def delay_of(strategy: Dict[str, Any]) -> int:
    """metrics.py `_eval_delay`: product of every temporal factor, all levels."""
    dl = 1
    for block, key in (
        (strategy["NodeLevel"], "temporal_tile"),
        (strategy["NoCLevel"], "temporal_permutation"),
        (strategy["DRAM"], "temporal_permutation"),
    ):
        for loop in _loops(block, key):
            dl *= loop["size"]
    return dl


def node_spatial_of(strategy: Dict[str, Any]) -> Dict[str, int]:
    """NodeLevel PE-parallel fanout per dimension (level-0 spatial)."""
    return {
        loop["dim"]: loop["size"]
        for loop in _loops(strategy["NodeLevel"], "spatial_split")
    }


def noc_fanout_of(strategy: Dict[str, Any]) -> int:
    """Inter-node fanout: product of the NoCLevel spatial splitting factors."""
    prod = 1
    for loop in _loops(strategy["NoCLevel"], "spatial_splitting"):
        prod *= loop["size"]
    return prod


def split_pe_t(node_spatial: Dict[str, int]) -> tuple[int, int]:
    """(non-T spatial product, T spatial factor) from a node spatial split."""
    pe = math.prod([v for d, v in node_spatial.items() if d != "T"] or [1])
    return pe, node_spatial.get("T", 1)


# ---------------------------------------------------------------------------
# Solver driver
# ---------------------------------------------------------------------------

def solve(arch: pathlib.Path, layer: pathlib.Path, dataflow: pathlib.Path,
          out: pathlib.Path, env: str = CONDA_ENV) -> Dict[str, Any]:
    """Run `lays.scheduler solve` and return its result JSON (plus stderr on failure)."""
    cmd = [
        "conda", "run", "-n", env, "python", "-m", "lays.scheduler", "solve",
        "--arch", str(arch), "--layer", str(layer),
        "--dataflow", str(dataflow), "--out", str(out),
    ]
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True,
        env={**_base_env(), "PYTHONPATH": str(REPO / "src")},
    )
    if not out.exists():
        return {
            "has_solution": False,
            "status": "NO_OUTPUT",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
        }
    result = json.loads(out.read_text())
    result["returncode"] = proc.returncode
    result["command"] = " ".join(cmd)
    return result


def _base_env() -> Dict[str, str]:
    import os
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arch", default=str(HERE / "arch.yaml"))
    ap.add_argument("--layer", default=str(HERE / "layer.yaml"))
    ap.add_argument("--mapspaces", default=str(HERE / "mapspaces"))
    ap.add_argument("--out", default=str(HERE / "outputs" / "baselines.json"))
    ap.add_argument("--env", default=CONDA_ENV)
    args = ap.parse_args()

    arch, layer = pathlib.Path(args.arch), pathlib.Path(args.layer)
    summary = json.loads((HERE / "outputs" / "summary.json").read_text())
    total_work = summary["total_work"]

    rows: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for mapspace in sorted(pathlib.Path(args.mapspaces).glob("*.yaml")):
            name = mapspace.stem
            out_json = pathlib.Path(tmp) / f"{name}.json"
            print(f"solve {name} ...", flush=True)
            result = solve(arch, layer, mapspace, out_json, env=args.env)
            row: Dict[str, Any] = {
                "name": name,
                "mapspace": str(mapspace.relative_to(REPO)),
                "status": result.get("status"),
                "has_solution": bool(result.get("has_solution")),
                "objective": result.get("objective"),
            }
            if row["has_solution"]:
                strategy = result["strategy"]
                node_sp = node_spatial_of(strategy)
                pe_sp, t_sp = split_pe_t(node_sp)
                fanout = noc_fanout_of(strategy)
                delay = delay_of(strategy)
                row.update({
                    "delay": delay,
                    "node_spatial": node_sp,
                    "pe_spatial": pe_sp,
                    "t_spatial": t_sp,
                    "noc_fanout": fanout,
                    "closed_form_latency": total_work // (pe_sp * t_sp * fanout),
                    "node_temporal": {
                        loop["dim"]: loop["size"]
                        for loop in _loops(strategy["NodeLevel"], "temporal_tile")
                    },
                })
                row["closed_form_matches"] = row["delay"] == row["closed_form_latency"]
            else:
                row["stderr"] = result.get("stderr")
            rows.append(row)
            print(f"  {row['status']}  delay={row.get('delay')}", flush=True)

    feasible = [r for r in rows if r["has_solution"]]
    payload = {
        "arch": str(arch),
        "layer": str(layer),
        "total_work": total_work,
        "n_mapspaces": len(rows),
        "n_feasible": len(feasible),
        "all_closed_form_match": all(r["closed_form_matches"] for r in feasible),
        "baselines": rows,
    }
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"\n{len(feasible)}/{len(rows)} feasible; "
          f"closed-form identity holds for all: {payload['all_closed_form_match']}")
    for r in rows:
        print(f"  {r['name']:20s} {r['status']:12s} delay="
              f"{r.get('delay', 'n/a')}")
    return 0 if len(feasible) == len(rows) and payload["all_closed_form_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
