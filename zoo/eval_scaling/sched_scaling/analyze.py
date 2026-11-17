#!/usr/bin/env python3
"""T76 S2: aggregate scheduler-only scaling solves into CSV + 2x5 figure.

Scheduler metrics only (no simulation): per point,
  performance = 1 / sum_l(result.metrics.delay_l), normalized to single_x1;
  dram traffic = sum_l(temporal_traffic.weight_l * util.weight_l),
  normalized to single_x1 (the CoSA-style analytic weight volume).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ARCHES = ("spinalflow", "ptb", "loas", "prosperity", "gustavsnn")
PRETTY = {"spinalflow": "SpinalFlow", "ptb": "PTB", "loas": "LoAS",
          "prosperity": "Prosperity", "gustavsnn": "GustavSNN"}
MULTIPLIERS = (1, 2, 4)
CAP_LABELS = {1: "128K", 2: "256K", 4: "512K"}
EXPECTED_LAYERS = 13


def point_metrics(arch: str, side: str, m: int) -> tuple[float, float, int]:
    sched_dir = OUT / "s1" / arch / f"{side}_x{m}" / "schedules" / arch
    files = sorted(sched_dir.glob("*/layer_*.json"))
    if len(files) != EXPECTED_LAYERS:
        raise SystemExit(f"{arch}_{side}_x{m}: {len(files)} schedules, "
                         f"expected {EXPECTED_LAYERS}")
    delay_sum = 0.0
    traffic_sum = 0.0
    nodes = set()
    for f in files:
        doc = json.loads(f.read_text())
        res = doc["result"]
        if res.get("status") not in ("OPTIMAL", "FEASIBLE") and not res.get("has_solution"):
            raise SystemExit(f"no solution in {f}")
        metrics = res["metrics"]
        delay_sum += float(metrics["delay"])
        traffic_sum += float(metrics["temporal_traffic"]["weight"]) * float(metrics["util"]["weight"])
        loops = res["strategy"].get("NoCLevel", {}).get("spatial_splitting", {}).get("loops", [])
        prod = 1
        for loop in loops:
            prod *= int(loop["size"])
        nodes.add(prod)
    # The solver may legitimately leave some nodes idle on a layer (spatial
    # product < instances), so per-layer node usage can vary within a point.
    return delay_sum, traffic_sum, max(nodes)


def main() -> None:
    rows = []
    for arch in ARCHES:
        base_delay = base_traffic = None
        for side in ("single", "multi"):
            for m in MULTIPLIERS:
                delay, traffic, nodes = point_metrics(arch, side, m)
                rows.append({"arch": arch, "side": side, "multiplier": m,
                             "nodes": nodes, "delay_sum": delay,
                             "analytic_weight_traffic": traffic})
                if side == "single" and m == 1:
                    base_delay, base_traffic = delay, traffic
        for row in rows:
            if row["arch"] == arch:
                row["perf_norm"] = base_delay / row["delay_sum"]
                row["traffic_norm"] = (row["analytic_weight_traffic"] / base_traffic
                                       if base_traffic else float("nan"))
    csv_path = OUT / "sched_scaling.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"-> {csv_path}")

    fig, axes = plt.subplots(2, 5, figsize=(14, 5.2), sharex=True)
    styles = {"single": dict(color="#4477aa", marker="o", ls="-",
                             label="single node (1 core, capacity grows)"),
              "multi": dict(color="#ee6677", marker="s", ls="--",
                            label="multi node (cores grow 1/2/4, LB fixed 64K)")}
    for col, arch in enumerate(ARCHES):
        for metric_row, key, ylabel in ((0, "perf_norm", "Performance / single-node 128K\n(1 / scheduler delay)"),
                                        (1, "traffic_norm", "Analytic DRAM weight traffic\n/ single-node 128K")):
            ax = axes[metric_row][col]
            for side in ("single", "multi"):
                pts = [r for r in rows if r["arch"] == arch and r["side"] == side]
                pts.sort(key=lambda r: r["multiplier"])
                ax.plot([CAP_LABELS[r["multiplier"]] for r in pts],
                        [r[key] for r in pts], **styles[side])
            if metric_row == 0:
                ax.set_title(PRETTY[arch])
            if metric_row == 1:
                ax.set_xlabel("Total on-chip weight capacity")
            if col == 0:
                ax.set_ylabel(ylabel)
            ax.grid(alpha=0.25, lw=0.4)
            ax.axhline(1.0, color="0.4", lw=0.8, ls=":")
    axes[0][0].legend(fontsize=8, loc="best")
    fig.suptitle("Scheduler-only scaling: scale-up (single) vs scale-out (multi) "
                 "at equal total weight capacity - vgg16, Gurobi solves, no simulation",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for suffix in ("png", "pdf"):
        path = OUT / f"sched_scaling.{suffix}"
        fig.savefig(path, dpi=220 if suffix == "png" else None)
        print(f"-> {path}")


if __name__ == "__main__":
    main()
