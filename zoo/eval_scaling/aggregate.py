#!/usr/bin/env python3
"""S2+S5 for eval_scaling: analytic CoSA traffic + nocsim joins -> aggregate.csv.

S2 (per point, layer; schedule-determined, no sample axis):
  W_v = TRAFFIC_MULT-included temporal_traffic[v] * util[v]   [bytes]
  read from the S1 schedule JSON metrics (linear scale; util is already in
  bytes of the GB/LB footprint, temporal_traffic is the boundary-crossing
  repeat count including the load+store factor).

S5 (per point, from S4 CSVs):
  U = sum_l C_l / (N * sum_l T_l), per sample; mean +/- 95% CI over samples.
  Counted DRAM words (diagnostic + CI panel) = sum_l dram_cost_total / DRAM_LATENCY.
  Traffic normalized to the single_x1 baseline.
"""

import csv
import json
import math
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "outputs"
CAPTURE = "loas_vgg16_T4_n500"
DRAM_LATENCY = 0.25
T95 = 2.262  # two-sided t, df=9


def analytic_traffic(point: str) -> float:
    total = 0.0
    sched_dir = OUT / "s1" / point / "schedules" / "loas" / CAPTURE
    for path in sorted(sched_dir.glob("*.json")):
        m = json.loads(path.read_text())["result"]["metrics"]
        for v in ("weight", "psum", "vmem"):
            total += m["temporal_traffic"][v] * m["util"][v]
    return total


def mean_ci(xs):
    n = len(xs)
    mu = sum(xs) / n
    if n < 2:
        return mu, 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return mu, T95 * sd / math.sqrt(n)


def main() -> None:
    rows_by_point = defaultdict(list)
    for path in sorted((OUT / "s4").glob("*.csv")):
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                rows_by_point[row["point"]].append(row)

    agg = []
    for point, rows in sorted(rows_by_point.items()):
        nodes = int(rows[0]["nodes"])
        layers = {r["layer"] for r in rows}
        samples = sorted({int(r["sample"]) for r in rows})
        u_s, w_s = [], []
        for s in samples:
            sub = [r for r in rows if int(r["sample"]) == s]
            assert len(sub) == len(layers), (point, s, len(sub))
            c = sum(int(r["count_cycles"]) for r in sub)
            t = sum(int(r["total_cycles"]) for r in sub)
            u_s.append(c / (nodes * t))
            w_s.append(sum(
                (float(r["dram_cost_weight"]) + float(r["dram_cost_psum"])
                 + float(r["dram_cost_vmem"])) for r in sub) / DRAM_LATENCY)
        u_mu, u_ci = mean_ci(u_s)
        w_mu, w_ci = mean_ci(w_s)
        side, mult = point.rsplit("_x", 1)
        agg.append({
            "point": point, "side": side, "multiplier": int(mult),
            "nodes": nodes, "layers": len(layers), "samples": len(samples),
            "util_mean": u_mu, "util_ci95": u_ci,
            "counted_dram_words_mean": w_mu, "counted_dram_words_ci95": w_ci,
            "analytic_traffic_bytes": analytic_traffic(point),
        })

    base = next((r for r in agg if r["point"] == "single_x1"), None)
    for r in agg:
        if base:
            r["analytic_traffic_norm"] = (
                r["analytic_traffic_bytes"] / base["analytic_traffic_bytes"])
            r["counted_traffic_norm"] = (
                r["counted_dram_words_mean"] / base["counted_dram_words_mean"])
            r["counted_traffic_norm_ci95"] = (
                r["counted_dram_words_ci95"] / base["counted_dram_words_mean"])

    out = OUT / "aggregate.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(agg[0]))
        w.writeheader()
        w.writerows(sorted(agg, key=lambda r: (r["side"], r["multiplier"])))
    for r in agg:
        print(r["point"], f"U={r['util_mean']:.3f}+/-{r['util_ci95']:.3f}",
              f"W_analytic={r['analytic_traffic_bytes']:.3e}")
    print("->", out)


if __name__ == "__main__":
    main()
