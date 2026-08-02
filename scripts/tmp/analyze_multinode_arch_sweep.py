#!/usr/bin/env python3
"""Classify and summarize the schedules produced by
scripts/tmp/sweep_multinode_arch_sweep.py.

Per 2026-07-30 follow-up, only three views are kept (NodeLevel dropped
entirely):
  NoC-S      -- NoCLevel spatial_splitting: unordered set of
                super-dimensions present (order-free, solver output has
                no permutation to preserve there).
  NoC-T      -- NoCLevel temporal_permutation: super-dimension *order*.
  DRAM-T     -- DRAM temporal_permutation: super-dimension *order*.

Every loop's tile SIZE is dropped in all three (mip_solver.analysis.
dram_permutation.classify_permutation already drops sizes; the NoC-S set
form does the same for the unordered case). Super-dims: M={HO,WO},
N={COUT}, K={KH,KW,CIN}, T={T}.

Reads outputs/schedules/multinode_sweep/summary.csv (written by the sweep
driver) for the combo grid, loads each solved (OK or SKIPPED) row's
schedule JSON, and writes outputs/schedules/multinode_sweep/classification.csv
plus prints summary statistics. Read-only -- never re-solves anything.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, "src")

from mip_solver.analysis.dram_permutation import classify_permutation, SUPER_DIM

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SUMMARY_PATH = REPO_ROOT / "outputs" / "schedules" / "multinode_sweep" / "summary.csv"
SCHEDULE_ROOT = REPO_ROOT / "outputs" / "schedules" / "multinode_sweep"
OUT_CSV = REPO_ROOT / "outputs" / "schedules" / "multinode_sweep" / "classification.csv"


def _size_tag(n: int) -> str:
    return f"{n // 1024}kb"


def superdim_set(factors) -> str:
    present = {SUPER_DIM[f["dim"]] for f in factors}
    return "+".join(t for t in ("M", "N", "K", "T") if t in present) or "-"


def schedule_path(row: dict) -> pathlib.Path:
    arch, instances = row["arch"], row["instances"]
    node_tag, noc_tag = _size_tag(int(row["node_size"])), _size_tag(int(row["noc_size"]))
    return (
        SCHEDULE_ROOT / f"inst{instances}_node{node_tag}_noc{noc_tag}"
        / arch / row["trace_dir"] / f"{row['layer']}.json"
    )


def classify_row(row: dict) -> dict:
    path = schedule_path(row)
    with open(path) as fh:
        data = json.load(fh)
    strategy = data["result"]["strategy"]

    noc_spatial = superdim_set(strategy["NoCLevel"]["spatial_splitting"]["loops"])
    noc_temporal_order = classify_permutation(strategy["NoCLevel"]["temporal_permutation"]["loops"]) or "-"
    dram_order = classify_permutation(strategy["DRAM"]["temporal_permutation"]["loops"]) or "-"

    return {
        **row,
        "noc_spatial_class": noc_spatial,
        "noc_temporal_order": noc_temporal_order,
        "dram_order_class": dram_order,
    }


def main() -> int:
    with open(SUMMARY_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))

    # SKIPPED means "found an existing schedule JSON on disk" (from an
    # earlier run) -- a genuinely solved combo, not an unattempted one.
    # Excluding it here undercounts every feasibility stat and drops those
    # schedules from classification entirely (found 2026-07-31: 1,116
    # combos affected).
    solved_rows = [r for r in rows if r["status"] in ("OK", "SKIPPED")]
    classified = [classify_row(r) for r in solved_rows]

    fields = [
        "arch", "instances", "node_size", "noc_size", "trace_dir", "layer", "mode",
        "noc_spatial_class", "noc_temporal_order", "dram_order_class",
    ]
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in classified:
            writer.writerow({k: row.get(k, "") for k in fields})

    n_total = len(rows)
    n_solved = len(solved_rows)
    n_infeasible = sum(1 for r in rows if r["status"] == "INFEASIBLE")
    n_error = sum(1 for r in rows if r["status"] == "ERROR")
    print(f"{n_total} combos total: {n_solved} solved, {n_infeasible} infeasible, {n_error} error")

    print("\nfeasible combos by arch:")
    for arch, n in Counter(r["arch"] for r in solved_rows).most_common():
        print(f"  {arch:<12} {n}")

    print("\nfeasible combos by NodeLevel size:")
    for size, n in sorted(Counter(int(r["node_size"]) for r in solved_rows).items()):
        print(f"  {_size_tag(size):>6} {n}")

    print("\nfeasible combos by NoCLevel size:")
    for size, n in sorted(Counter(int(r["noc_size"]) for r in solved_rows).items()):
        print(f"  {_size_tag(size):>6} {n}")

    print("\nfeasible combos by instances:")
    for inst, n in sorted(Counter(int(r["instances"]) for r in solved_rows).items()):
        print(f"  {inst:>6} {n}")

    print("\nstructural classes (NoC-S | NoC-T order | DRAM-T order):")
    class_counts = Counter(
        (r["noc_spatial_class"], r["noc_temporal_order"], r["dram_order_class"])
        for r in classified
    )
    for key, n in class_counts.most_common():
        print(f"  {' | '.join(key):<40} {n}")

    print(f"\nWrote {len(classified)} classified row(s) to {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
