#!/usr/bin/env python3
"""S2+S5 for eval_scaling: analytic CoSA traffic + nocsim joins -> aggregate.csv.

Primary traffic metric (Archie review 2026-11-16, SEV-1): the nocsim-counted
DRAM words. The analytic util*temporal_traffic product is kept as a
DIAGNOSTIC column only - it reconstructs total weight volume rather than
measuring capacity-dependent refetch, and over-counts when the GB tile grows
without the trip count shrinking. Do not plot it.

S5 (per point, from S4 CSVs + S1 schedules):
  U = sum_l C_l / (sum_l N_l * T_l), per sample; mean +/- 95% CI over
  samples. N_l is read from the schedule's NoCLevel spatial product per
  layer (SEV-5: layer_13 splits COUT 5-way, not 16-way).
  Counted DRAM words = sum_l dram_cost_total / DRAM_LATENCY.
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
    """DIAGNOSTIC only (SEV-1): weight term only; BW_WEIGHT=8 so entries==bytes."""
    total = 0.0
    sched_dir = OUT / "s1" / point / "schedules" / "loas" / CAPTURE
    for path in sorted(sched_dir.glob("*.json")):
        m = json.loads(path.read_text())["result"]["metrics"]
        total += m["temporal_traffic"]["weight"] * m["util"]["weight"]
    return total


def nodes_per_layer(point: str) -> dict:
    """N_l = product of the schedule's NoCLevel spatial_splitting loop sizes."""
    out = {}
    sched_dir = OUT / "s1" / point / "schedules" / "loas" / CAPTURE
    for path in sorted(sched_dir.glob("*.json")):
        strat = json.loads(path.read_text())["result"]["strategy"]
        n = 1
        for loop in strat["NoCLevel"]["spatial_splitting"]["loops"]:
            n *= int(loop["size"])
        out[path.stem] = n
    return out


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
        n_l = nodes_per_layer(point)
        layers = {r["layer"] for r in rows}
        samples = sorted({int(r["sample"]) for r in rows})
        u_s, w_s = [], []
        for s in samples:
            sub = [r for r in rows if int(r["sample"]) == s]
            assert len(sub) == len(layers), (point, s, len(sub))
            c = sum(int(r["count_cycles"]) for r in sub)
            nt = sum(n_l[r["layer"]] * int(r["total_cycles"]) for r in sub)
            u_s.append(c / nt)
            w_s.append(sum(
                (float(r["dram_cost_weight"]) + float(r["dram_cost_psum"])
                 + float(r["dram_cost_vmem"])) for r in sub) / DRAM_LATENCY)
        u_mu, u_ci = mean_ci(u_s)
        w_mu, w_ci = mean_ci(w_s)
        side, mult = point.rsplit("_x", 1)
        agg.append({
            "point": point, "side": side, "multiplier": int(mult),
            "nodes": max(n_l.values()), "layers": len(layers), "samples": len(samples),
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
