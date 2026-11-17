"""RQ4 tornado proposal: one-at-a-time cache DSE vs our design (cacheA, V0).

Central vertical line = cacheA. Each row flips ONE knob; the bar shows the
paired per-sample change on four metrics: L1 hit rate, L2 hit rate,
performance (1/latency), energy. Bars extend LEFT when the variant is
BETTER than our design, RIGHT when worse. Whiskers: 95% Student-t CI over
the 10 paired samples. Hit rates are layer means (per-layer access counts
are not in the extract); performance and energy are whole-model sums.

Run: conda run -n gurobi python fig_dse_tornado.py
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm

HERE = Path(__file__).resolve().parent
CSV = HERE / "results" / "cache_dse_asap7.csv"

GROUP_COLOUR = {"capacity": "#4477aa", "replacement": "#228833",
                "bound": "#aa3377", "prefetch": "#ee6677"}
ORDER = [  # (label, display)
    ("L2 256 KiB", "L2 256K"), ("L2 1 MiB", "L2 1M"),
    ("L1 8 KiB", "L1 8K"), ("L1 32 KiB", "L1 32K"),
    ("pure LRU", "LRU"), ("pure LFU", "LFU"),
    ("Belady L2", "Belady"),
    ("L1 next-line", "L1 +1 ln"), ("L1+L2 next-line", "L1+L2 +1 ln"),
]
T_CRIT = 2.2621571628540993  # t(9), 97.5%


def main() -> None:
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 8,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family, "mathtext.bf": family,
        "axes.unicode_minus": False,
    })

    per = defaultdict(lambda: defaultdict(list))  # label -> sample -> layer rows
    groups = {}
    with CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            if r["row_type"] != "layer":
                continue
            per[r["label"]][r["sample"]].append(r)
            groups[r["label"]] = r["group"]

    def agg(label):
        """sample -> (perf, energy, l1, l2)."""
        out = {}
        for s, rows in per[label].items():
            T = sum(float(r["T_s"]) for r in rows)
            E = sum(float(r["E_total_nJ"]) for r in rows)
            l1 = np.mean([float(r["l1_hit_rate"]) for r in rows])
            l2 = np.mean([float(r["l2_hit_rate"]) for r in rows])
            out[s] = (1.0 / T, E, l1, l2)
        return out

    base = agg("cacheA")
    METRICS = ["L1 hit rate", "L2 hit rate", "Performance", "Energy"]
    # improvement per metric (positive = better than ours), per sample
    data = {}
    for label, disp in ORDER:
        v = agg(label)
        ids = sorted(set(v) & set(base))
        imp = {m: [] for m in METRICS}
        for s in ids:
            pv, ev, l1v, l2v = v[s]
            pb, eb, l1b, l2b = base[s]
            imp["L1 hit rate"].append((l1v - l1b) * 100)          # pp
            imp["L2 hit rate"].append((l2v - l2b) * 100)          # pp
            imp["Performance"].append((pv / pb - 1) * 100)        # %
            imp["Energy"].append(-(ev / eb - 1) * 100)            # % (less = better)
        data[(label, disp)] = imp

    fig, axes2 = plt.subplots(2, 2, figsize=(3.4, 3.1), sharey=True)
    axes = axes2.ravel()
    ys = np.arange(len(ORDER))[::-1]
    for ax, metric in zip(axes, METRICS):
        for (label, disp), y in zip(ORDER, ys):
            vals = np.array(data[(label, disp)][metric])
            mean = vals.mean()
            ci = T_CRIT * vals.std(ddof=1) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
            colour = GROUP_COLOUR[groups[label]]
            probe = groups[label] == "bound"
            ax.barh(y, -mean, height=0.62, color="none" if probe else colour,
                    edgecolor=colour, hatch="//" if probe else None,
                    lw=0.9 if probe else 0.4, zorder=3)
            ax.errorbar(-mean, y, xerr=ci, fmt="none", ecolor="0.2",
                        elinewidth=0.7, capsize=1.5, zorder=4)
        ax.axvline(0, color="0.15", lw=1.2, zorder=2)
        unit = "pp" if "hit" in metric else "%"
        lim = max(abs(v) for (ld, i) in data.items() for v in i[metric]) * 1.25
        ax.set_xlim(-lim, lim)
        ax.set_xlabel(f"{metric} ($\\Delta$ {unit})", fontsize=8, labelpad=1.5)
        ax.grid(axis="x", alpha=0.25, lw=0.4, zorder=0)
        ax.tick_params(labelsize=7.5, pad=1.5)
        ax.spines[["top", "right", "left"]].set_visible(False)
    for ax in axes2[0]:
        ax.annotate("$\\leftarrow$ better", xy=(0.47, 1.0), xycoords="axes fraction",
                    ha="right", va="bottom", fontsize=7, color="0.35")
        ax.annotate("worse $\\rightarrow$", xy=(0.53, 1.0), xycoords="axes fraction",
                    ha="left", va="bottom", fontsize=7, color="0.35")
    for ax in axes2[:, 0]:
        ax.set_yticks(ys)
        ax.set_yticklabels([d for _, d in ORDER], fontsize=8)
    fig.tight_layout(h_pad=0.9, w_pad=0.6)
    for ext in ("pdf", "png"):
        fig.savefig(HERE / "results" / f"fig_dse_tornado.{ext}",
                    bbox_inches="tight", dpi=300)
    print(f"font: {family}; wrote results/fig_dse_tornado.pdf / .png")


if __name__ == "__main__":
    main()
