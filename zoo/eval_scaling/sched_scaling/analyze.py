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
    # plot-only fallback: reuse the committed CSV when the Gurobi schedule
    # outputs are not on this machine (--from-csv or missing inputs)
    import sys
    csv_existing = OUT / "sched_scaling.csv"
    if "--from-csv" in sys.argv and csv_existing.is_file():
        with csv_existing.open(newline="") as stream:
            rows = [{k: (v if k in ("arch", "side") else float(v))
                     for k, v in r.items()} for r in csv.DictReader(stream)]
        plot(rows)
        return
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

    plot(rows)


def plot(rows) -> None:
    # --- publication figure: two compact panels ---------------------------
    # Multi-node perf_norm is identical (1/2/4) across all five arches and
    # single-node lines are flat at 1.0, so one speedup panel suffices;
    # DRAM weight traffic differs per arch and gets its own panel.
    from matplotlib import font_manager as fm
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 8,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family, "mathtext.bf": family,
    })
    for a_ in ARCHES:
        mp = [r["perf_norm"] for r in rows if r["arch"] == a_ and r["side"] == "multi"]
        assert all(abs(v - w) < 1e-3 for v, w in zip(mp, [1.0, 2.0, 4.0])), (a_, mp)

    ARCH_COLOUR = {"gustavsnn": "#444444", "loas": "#4477aa",
                   "prosperity": "#228833", "ptb": "#aa3377",
                   "spinalflow": "#ee6677"}
    ARCH_MARKER = {"spinalflow": "P", "ptb": "D", "loas": "s",
                   "prosperity": "^", "gustavsnn": "o"}
    caps = [CAP_LABELS[m] for m in MULTIPLIERS]
    x = range(len(caps))
    fig, (axp, axt) = plt.subplots(1, 2, figsize=(3.4, 1.8))
    axp.plot(x, [1.0, 2.0, 4.0], color="#ee6677", marker="s", ms=4, ls="--",
             label="multi-node (all arches)")
    axp.plot(x, [1.0, 1.0, 1.0], color="#4477aa", marker="o", ms=4, ls="-",
             label="single node")
    axp.set_ylabel("Speedup / single 128K")
    axp.set_yticks([1, 2, 3, 4])
    axp.legend(fontsize=8, frameon=False, loc="upper left", borderaxespad=0.2,
               handlelength=1.6, handletextpad=0.4)
    for arch in ARCHES:
        pts = sorted((r for r in rows if r["arch"] == arch and r["side"] == "multi"),
                     key=lambda r: r["multiplier"])
        axt.plot(x, [r["traffic_norm"] for r in pts], color=ARCH_COLOUR[arch],
                 marker=ARCH_MARKER[arch], ms=3.6, lw=1.0, ls="--",
                 markerfacecolor="none", label=PRETTY[arch])
    axt.axhline(1.0, color="0.4", lw=0.8, ls=":")
    axt.set_ylabel("DRAM weight traffic\n/ single 128K", fontsize=7.5)
    axt.legend(fontsize=8, frameon=False, loc="upper right", borderaxespad=0.1,
               handlelength=1.4, handletextpad=0.3, labelspacing=0.25)
    for ax in (axp, axt):
        ax.set_xticks(list(x)); ax.set_xticklabels(caps, fontsize=8)
        ax.set_xlabel("Total weight capacity", fontsize=8)
        ax.grid(alpha=0.25, lw=0.4)
        ax.tick_params(labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        path = OUT / f"sched_scaling.{suffix}"
        fig.savefig(path, dpi=300 if suffix == "png" else None, bbox_inches="tight")
        print(f"-> {path}")
    print(f"font: {family}")


if __name__ == "__main__":
    main()
