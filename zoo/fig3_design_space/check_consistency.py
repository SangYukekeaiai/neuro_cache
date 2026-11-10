#!/usr/bin/env python3
"""Cross-check the closed-form enumeration against the real Gurobi scheduler.

Samples schedules from outputs/schedules.csv, pins each one's NodeLevel role
assignment as a dataflow YAML (spatial roles become {spatial: N}, resident
roles become an integer cap, role '-' dims are omitted and therefore barred),
re-solves with `python -m lays.scheduler solve`, and asserts that the MIP and
enumerate.py agree:

  1. the pinned assignment is feasible;
  2. the solver's PE and T spatial fanout equal the sampled row's;
  3. the solver's delay equals the closed form
     total_work / (PE_spatial x T_spatial x NoC_fanout) at the fanout the
     solver itself chose;
  4. that fanout is one enumerate.py accepts for this assignment (so the
     solver never reaches a point the enumeration calls invalid), and the
     solver's delay never beats the enumeration's best latency for it.

A dataflow YAML cannot pin the inter-node fanout -- the MIP picks it from the
full objective -- so check 3 compares at the solver's chosen fanout rather
than at the sampled row's.  Writes outputs/consistency.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import sys
import tempfile
from typing import Any, Dict, List, Set

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import importlib

_enum = importlib.import_module("enumerate")
from run_baselines import (  # noqa: E402  (local module, path set above)
    delay_of, node_spatial_of, noc_fanout_of, split_pe_t, solve,
)

DIMS = _enum.DIMS
ROLE_SPATIAL, ROLE_RESIDENT, ROLE_NONE = (
    _enum.ROLE_SPATIAL, _enum.ROLE_RESIDENT, _enum.ROLE_NONE,
)


def sample_rows(csv_path: pathlib.Path, n: int, seed: int) -> List[Dict[str, str]]:
    """Reservoir-sample *n* rows, plus the first row of every distinct latency.

    The reservoir gives a count-weighted sample of the bulk of the space; the
    per-latency rows guarantee both ends (best and worst) are exercised.
    """
    rng = random.Random(seed)
    reservoir: List[Dict[str, str]] = []
    by_latency: Dict[str, Dict[str, str]] = {}
    with open(csv_path, newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            by_latency.setdefault(row["latency"], row)
            if len(reservoir) < n:
                reservoir.append(row)
            else:
                j = rng.randrange(i + 1)
                if j < n:
                    reservoir[j] = row
    extremes = [by_latency[k] for k in (min(by_latency, key=int), max(by_latency, key=int))]
    picked, seen = [], set()
    for row in extremes + reservoir:
        key = tuple(row[f"node_{d}"] + row[f"role_{d}"] for d in DIMS) + (row["fan_KH"],)
        if key not in seen:
            seen.add(key)
            picked.append(row)
    return picked[:n]


def dataflow_yaml(row: Dict[str, str]) -> str:
    """Pin one enumerated node assignment as a node-mapspace YAML."""
    lines = ["dataflow:", "  node_dim_capacity:"]
    body = []
    for d in DIMS:
        factor, role = int(row[f"node_{d}"]), row[f"role_{d}"]
        if role == ROLE_NONE or factor == 1:
            continue          # omitted => barred from NodeLevel
        if role == ROLE_SPATIAL:
            body.append(f"    {d}: {{spatial: {factor}}}")
        else:
            body.append(f"    {d}: {factor}")
    if not body:
        lines[-1] = "  node_dim_capacity: {}"
    return "\n".join(lines + body) + "\n"


def legal_fanouts(row: Dict[str, str], bounds, glb_caps) -> Set[int]:
    """The inter-node fanout products enumerate.py accepts for this assignment."""
    node_factors = tuple(int(row[f"node_{d}"]) for d in DIMS)
    lb_bytes = (int(row["lb_weight_B"]), int(row["lb_psum_B"]), int(row["lb_vmem_B"]))
    return {
        fanout
        for _fan, fanout, _glb in _enum.enumerate_fanouts(
            bounds, node_factors, lb_bytes, glb_caps
        )
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arch", default=str(HERE / "arch.yaml"))
    ap.add_argument("--layer", default=str(HERE / "layer.yaml"))
    ap.add_argument("--schedules", default=str(HERE / "outputs" / "schedules.csv"))
    ap.add_argument("--summary", default=str(HERE / "outputs" / "summary.json"))
    ap.add_argument("--out", default=str(HERE / "outputs" / "consistency.json"))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--env", default="gurobi")
    args = ap.parse_args()

    summary = json.loads(pathlib.Path(args.summary).read_text())
    total_work = summary["total_work"]
    bounds = [summary["bounds"][d] for d in DIMS]
    glb_caps = summary["glb_byte_caps"]

    rows = sample_rows(pathlib.Path(args.schedules), args.n, args.seed)
    print(f"sampled {len(rows)} schedules (seed {args.seed})", flush=True)

    checks: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        for i, row in enumerate(rows):
            df = tmp_path / f"pin_{i}.yaml"
            df.write_text(dataflow_yaml(row))
            result = solve(
                pathlib.Path(args.arch), pathlib.Path(args.layer), df,
                tmp_path / f"pin_{i}.json", env=args.env,
            )
            entry: Dict[str, Any] = {
                "index": i,
                "node_factors": {d: int(row[f"node_{d}"]) for d in DIMS},
                "roles": {d: row[f"role_{d}"] for d in DIMS},
                "row_pe_spatial": int(row["pe_spatial"]),
                "row_t_spatial": int(row["t_spatial"]),
                "row_noc_fanout": int(row["noc_fanout"]),
                "row_latency": int(row["latency"]),
                "dataflow": dataflow_yaml(row),
                "status": result.get("status"),
                "feasible": bool(result.get("has_solution")),
            }
            if entry["feasible"]:
                strategy = result["strategy"]
                pe_sp, t_sp = split_pe_t(node_spatial_of(strategy))
                fanout = noc_fanout_of(strategy)
                delay = delay_of(strategy)
                closed = total_work // (pe_sp * t_sp * fanout)
                fanouts = legal_fanouts(row, bounds, glb_caps)
                best = min(total_work // (pe_sp * t_sp * f) for f in fanouts)
                entry.update({
                    "solver_pe_spatial": pe_sp,
                    "solver_t_spatial": t_sp,
                    "solver_noc_fanout": fanout,
                    "solver_delay": delay,
                    "closed_form_latency": closed,
                    "fanout_is_enumerated": fanout in fanouts,
                    "enumerated_best_latency": best,
                })
                entry["ok"] = (
                    pe_sp == entry["row_pe_spatial"]
                    and t_sp == entry["row_t_spatial"]
                    and delay == closed
                    and entry["fanout_is_enumerated"]
                    and delay >= best
                )
            else:
                entry["ok"] = False
                entry["stderr"] = result.get("stderr")
            checks.append(entry)
            print(f"  [{i + 1}/{len(rows)}] {entry['status']:12s} "
                  f"solver_delay={entry.get('solver_delay')} "
                  f"closed_form={entry.get('closed_form_latency')} "
                  f"ok={entry['ok']}", flush=True)

    n_ok = sum(1 for c in checks if c["ok"])
    payload = {
        "arch": args.arch,
        "layer": args.layer,
        "schedules_csv": args.schedules,
        "seed": args.seed,
        "n_sampled": len(checks),
        "n_ok": n_ok,
        "all_match": n_ok == len(checks),
        "checks": checks,
    }
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\n{n_ok}/{len(checks)} schedules agree with the solver")
    return 0 if payload["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
