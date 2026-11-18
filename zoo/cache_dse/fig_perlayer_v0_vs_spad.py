#!/usr/bin/env python3
"""T74: per-layer performance, fig12's three arms (spad, cacheA, cacheB).

Top panel: vgg16 (B09/loas_vgg16_T4_n500, loas arch, 12 layers).
Bottom panel: spikinglm (A07/spikinglm_t4_T4_n500, loas arch, layers present
in all arms).

All three arms come from the fig12 campaign results
(zoo/fig12_edp/stokes/results_asap7_20261116/sample_*/results_asap7.csv):
arm == "spad" is nocsim multi-node scratchpad; arm == "cacheA" (identical to
the cache_dse V0 rows, verified bit-equal on T_s) and arm == "cacheB" are
cachesim. All share the trace captures and the ASAP7-derived 500 MHz clock.

Per layer: mean over the samples common to all arms, band = 95% CI
(t-interval).

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

WORKLOADS = {
    "vgg16": "B09/loas_vgg16_T4_n500",
    "spikinglm": "A07/spikinglm_t4_T4_n500",
}
ARMS = ("spad", "cacheA", "cacheB")

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


def load_arms() -> dict:
    """-> {workload: {arm: {(layer, sample): T_s}}}"""
    captures = {v: k for k, v in WORKLOADS.items()}
    out = {wl: {arm: {} for arm in ARMS} for wl in WORKLOADS}
    for path in sorted(glob.glob(str(FIG12 / "sample_*" / "results_asap7.csv"))):
        with open(path) as stream:
            for row in csv.DictReader(stream):
                wl = captures.get(row["capture"])
                if wl and row["arch"] == "loas" and row["arm"] in ARMS:
                    out[wl][row["arm"]][(row["layer"], row["sample"])] = \
                        float(row["T_s"])
    return out


def main() -> None:
    data = load_arms()
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Gill Sans", "Gill Sans MT", "DejaVu Sans"],
        "font.size": 8,
        "axes.titlesize": 9,
    })
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 4.6))
    styles = {
        "spad": dict(color="#D55E00", marker="s", ms=3, lw=1.2, ls="--",
                     label="nocsim, multi-node spad"),
        "cacheA": dict(color="#0072B2", marker="o", ms=3, lw=1.2,
                       label="cachesim, cacheA (V0)"),
        "cacheB": dict(color="#009E73", marker="^", ms=3, lw=1.2, ls=":",
                       label="cachesim, cacheB"),
    }
    stats_lines = []
    for ax, wl in zip(axes, ("vgg16", "spikinglm")):
        arms = data[wl]
        layers = sorted(set.intersection(
            *({l for l, _ in arms[a]} for a in ARMS)))
        samples = sorted(set.intersection(
            *({s for _, s in arms[a]} for a in ARMS)), key=int)
        n_used = None
        means = {}
        for arm in ARMS:
            ms, hs = [], []
            for layer in layers:
                vals = [arms[arm][(layer, s)] for s in samples
                        if (layer, s) in arms[arm]]
                n_used = len(vals) if n_used is None else min(n_used, len(vals))
                m, h = mean_ci(vals)
                ms.append(m)
                hs.append(h)
            xs = range(1, len(layers) + 1)
            ax.plot(xs, ms, **styles[arm])
            ax.fill_between(xs, [m - h for m, h in zip(ms, hs)],
                            [m + h for m, h in zip(ms, hs)],
                            color=styles[arm]["color"], alpha=0.18, lw=0)
            means[arm] = ms
        for cache_arm in ("cacheA", "cacheB"):
            ratios = [s / c for s, c in zip(means["spad"], means[cache_arm])
                      if c > 0]
            geo = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
            stats_lines.append(
                f"{wl}: geomean spad/{cache_arm} latency ratio={geo:.3f} "
                f"(layers={len(layers)}, min n={n_used}); "
                f"sum spad={sum(means['spad']):.4g}s "
                f"{cache_arm}={sum(means[cache_arm]):.4g}s")
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
