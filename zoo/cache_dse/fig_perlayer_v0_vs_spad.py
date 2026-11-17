#!/usr/bin/env python3
"""T74: per-layer performance, cachesim cacheA (V0) vs nocsim multinode spad.

Top panel: vgg16 (B09/loas_vgg16_T4_n500, loas arch, 12 layers).
Bottom panel: spikinglm (A07/spikinglm_t4_T4_n500, loas arch, layers present
in both simulators).

Cache side:
  vgg16    -> results/cache_dse_asap7.csv, label == "cacheA", row_type ==
              "layer", T_s column (already seconds).
  spikinglm-> results/spikinglm_cache_v0.csv, total_cycles / 500 MHz.
Spad side (both workloads): zoo/fig12_edp/stokes/results_asap7_20261116/
  sample_*/results_asap7.csv, arm == "spad", arch == "loas", T_s column.

Per layer: mean over the samples common to both simulators, band = 95% CI
(t-interval). Caveat carried into the caption: the two series come from
different simulators (cachesim vs nocsim) sharing the trace capture and the
ASAP7 1 GHz-synthesis-derived 500 MHz clock, not from one model.

Run: conda run -n base python zoo/cache_dse/fig_perlayer_v0_vs_spad.py
"""

from __future__ import annotations

import csv
import glob
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIG12 = REPO / "zoo" / "fig12_edp" / "stokes" / "results_asap7_20261116"
FREQ_HZ = 500e6

WORKLOADS = {
    "vgg16": "B09/loas_vgg16_T4_n500",
    "spikinglm": "A07/spikinglm_t4_T4_n500",
}

# 95% two-sided t critical values by dof (enough for n <= 11)
T95 = {1: 12.71, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
       7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def mean_ci(vals):
    n = len(vals)
    m = sum(vals) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    half = T95.get(n - 1, 1.96) * math.sqrt(var / n)
    return m, half


def load_cache() -> dict:
    """-> {workload: {(layer, sample): T_s}}"""
    out = defaultdict(dict)
    with (HERE / "results" / "cache_dse_asap7.csv").open() as stream:
        for row in csv.DictReader(stream):
            if row["label"] == "cacheA" and row["row_type"] == "layer":
                out["vgg16"][(row["layer"], row["sample"])] = float(row["T_s"])
    with (HERE / "results" / "spikinglm_cache_v0.csv").open() as stream:
        for row in csv.DictReader(stream):
            t = float(row["total_cycles"]) / FREQ_HZ
            out["spikinglm"][(row["layer"], row["sample_idx"])] = t
    return out


def load_spad() -> dict:
    """-> {workload: {(layer, sample): T_s}}"""
    captures = {v: k for k, v in WORKLOADS.items()}
    out = defaultdict(dict)
    for path in sorted(glob.glob(str(FIG12 / "sample_*" / "results_asap7.csv"))):
        with open(path) as stream:
            for row in csv.DictReader(stream):
                wl = captures.get(row["capture"])
                if wl and row["arm"] == "spad" and row["arch"] == "loas":
                    out[wl][(row["layer"], row["sample"])] = float(row["T_s"])
    return out


def main() -> None:
    cache = load_cache()
    spad = load_spad()
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Gill Sans", "Gill Sans MT", "DejaVu Sans"],
        "font.size": 8,
        "axes.titlesize": 9,
    })
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 4.6))
    styles = {
        "cache": dict(color="#0072B2", marker="o", ms=3, lw=1.2,
                      label="cachesim, cacheA (V0)"),
        "spad": dict(color="#D55E00", marker="s", ms=3, lw=1.2, ls="--",
                     label="nocsim, multi-node spad"),
    }
    stats_lines = []
    for ax, wl in zip(axes, ("vgg16", "spikinglm")):
        c_pairs, s_pairs = cache[wl], spad[wl]
        layers = sorted({l for l, _ in c_pairs} & {l for l, _ in s_pairs})
        samples = sorted({s for _, s in c_pairs} & {s for _, s in s_pairs},
                         key=int)
        n_used = None
        series = {"cache": c_pairs, "spad": s_pairs}
        ratios = []
        for key, pairs in series.items():
            means, halves = [], []
            for layer in layers:
                vals = [pairs[(layer, s)] for s in samples if (layer, s) in pairs]
                n_used = len(vals) if n_used is None else min(n_used, len(vals))
                m, h = mean_ci(vals)
                means.append(m)
                halves.append(h)
            xs = range(1, len(layers) + 1)
            ax.plot(xs, means, **styles[key])
            ax.fill_between(xs, [m - h for m, h in zip(means, halves)],
                            [m + h for m, h in zip(means, halves)],
                            color=styles[key]["color"], alpha=0.18, lw=0)
            series[key] = means
        for mc, ms_ in zip(series["cache"], series["spad"]):
            if mc > 0:
                ratios.append(ms_ / mc)
        geomean = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        stats_lines.append(
            f"{wl}: layers={len(layers)} samples(min n)={n_used} "
            f"geomean spad/cacheA latency ratio={geomean:.3f} "
            f"sum cacheA={sum(series['cache']):.4g}s sum spad={sum(series['spad']):.4g}s")
        ax.set_yscale("log")
        ax.set_xlabel(f"{wl} layer index")
        ax.set_ylabel("Per-layer latency (s)")
        ax.set_title(f"{wl} - loas arch, per-layer latency, "
                     f"mean of {n_used} shared input samples (95% CI band)")
        ax.grid(alpha=0.25, lw=0.4)
        if wl == "spikinglm":
            ax.set_xticks(range(0, len(layers) + 1, 6))
        ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    out = HERE / "results"
    for suffix in ("pdf", "png"):
        path = out / f"fig_perlayer_v0_vs_spad.{suffix}"
        fig.savefig(path, dpi=300 if suffix == "png" else None,
                    bbox_inches="tight")
        print(f"-> {path}")
    for line in stats_lines:
        print(line)


if __name__ == "__main__":
    main()
