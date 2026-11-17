"""Roofline: spad vs cacheA paired per benchmark, cacheB omitted.

Replaces the 3-panel fig12_roofline view for the paper: one panel, the three
benchmarks whose cacheA benefit is unambiguous across all five architectures
(A02 spikformer: geomean OI x11.9 at P x0.99; C01 dvs128-gesture: OI x9.6,
P x1.39; C01 cifar10-dvs: OI x4.4, P x1.05 -- computed from outputs/
roofline.csv). Arm notation: spad = open ring, cacheA = filled, one thin gray
connector per (arch, benchmark) pair showing the shift. Marker shape = arch,
color = benchmark (Okabe-Ito). Error bars: CI95 over n=23 complete samples
(from fig12_roofline's aggregate). Roofs and points reuse fig12_roofline's
own loaders -- nothing is recomputed here.

Run: conda run -n <env> python fig_roofline_cacheA.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.lines import Line2D

import fig12_roofline as base

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"

KEEP_WORKLOADS = (
    "A02/spikformer_4_384_cifar100_T4_n500",
    "C01/sma_azo_vgg_cifar10_dvs_T10_n500",
    "C01/sma_azo_vgg_dvs128_gesture_T16_n500",
)
KEEP_ARMS = ("spad", "cacheA")
# Okabe-Ito
WL_COLORS = {KEEP_WORKLOADS[0]: "#0072B2", KEEP_WORKLOADS[1]: "#E69F00",
             KEEP_WORKLOADS[2]: "#009E73"}
ARCH_MARKERS = {arch: m for arch, m in zip(base.ARCHES, ("o", "s", "^", "D", "P"))}


def main() -> None:
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 12,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family, "mathtext.bf": family,
        "xtick.labelsize": 10, "ytick.labelsize": 10, "axes.linewidth": 1.0,
    })

    samples_by_group, metadata = base.load_extract(OUT / "extract.csv")
    points = [p for p in base.aggregate(samples_by_group)
              if p["workload"] in KEEP_WORKLOADS and p["arm"] in KEEP_ARMS]
    expected = len(KEEP_WORKLOADS) * len(base.ARCHES) * len(KEEP_ARMS)
    missing = expected - len(points)
    if missing:
        have = {(p["arch"], p["arm"], p["workload"]) for p in points}
        gaps = [(a, m, w) for w in KEEP_WORKLOADS for a in base.ARCHES
                for m in KEEP_ARMS if (a, m, w) not in have]
        print(f"note: {missing} missing group(s), excluded upstream: {gaps}")

    frequencies = metadata["frequencies_MHz"]
    assert len(frequencies) == 1, frequencies
    repo_root = Path(__file__).resolve().parents[2]
    roofs = base._roof_config(base.DEFAULT_ARCH_CONFIG.resolve(), frequencies[0] * 1e6,
                              base.DEFAULT_ARCHX_DIR.resolve(),
                              base.DEFAULT_MAPSPACE_DIR.resolve(), repo_root)
    base.validate_roofs(points, roofs)

    fig, ax = plt.subplots(figsize=(4.8, 3.4))
    bw = roofs["dram_bw_bytes_s"]
    compute_roofs = roofs["compute"]
    xs = [p[k] for p in points for k in ("OI_ci95_low", "OI_ci95_high")]
    ys = [p[k] for p in points for k in ("P_ci95_low", "P_ci95_high")]
    x_min, x_max = min(xs) * 0.5, max(xs) * 1.3
    roof_groups = {}
    for arch in base.ARCHES:
        roof_groups.setdefault(compute_roofs[arch]["compute_roof_ops_s"], []).append(arch)
    y_cap = max(max(ys), max(roof_groups)) * 2.0
    dram_x = np.logspace(np.log10(x_min), np.log10(y_cap / bw), 100)
    ax.plot(dram_x, bw * dram_x, color="0.2", lw=1.3)
    for roof, names in sorted(roof_groups.items()):
        ridge = roof / bw
        ax.plot([max(ridge, x_min), x_max], [roof, roof],
                color="0.45", lw=1.2, ls=(0, (4, 2)))
        ax.annotate(", ".join(names), xy=(x_max, roof), xytext=(-2, 3),
                    textcoords="offset points", ha="right", va="bottom",
                    fontsize=9, color="0.35")

    by_pair = {}
    for p in points:
        by_pair.setdefault((p["arch"], p["workload"]), {})[p["arm"]] = p
    for (arch, wl), arms in sorted(by_pair.items()):
        if len(arms) == 2:
            s, c = arms["spad"], arms["cacheA"]
            ax.annotate("", xy=(c["OI"], c["P"]), xytext=(s["OI"], s["P"]),
                        arrowprops=dict(arrowstyle="-|>", color="0.6", lw=0.8,
                                        shrinkA=4.5, shrinkB=5.5,
                                        mutation_scale=8), zorder=1)
        for arm, p in arms.items():
            ring = arm == "spad"
            ax.errorbar(
                p["OI"], p["P"],
                xerr=[[p["OI"] - p["OI_ci95_low"]], [p["OI_ci95_high"] - p["OI"]]],
                yerr=[[p["P"] - p["P_ci95_low"]], [p["P_ci95_high"] - p["P"]]],
                fmt=ARCH_MARKERS[arch], ms=6.5, elinewidth=0.7, capsize=0,
                color=WL_COLORS[wl],
                markerfacecolor="none" if ring else WL_COLORS[wl],
                markeredgecolor=WL_COLORS[wl], markeredgewidth=1.5, zorder=3)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(min(ys) * 0.55, y_cap)
    # worked example of the arm notation, drawn in the freed upper-left space
    ex_x, ex_y = x_min * 2.6, y_cap * 0.34
    ax.plot([ex_x], [ex_y], marker="o", ms=6.5, markerfacecolor="none",
            markeredgecolor="0.2", markeredgewidth=1.5, ls="none", zorder=4)
    ax.plot([ex_x * 3.2], [ex_y], marker="o", ms=6.5, color="0.2", ls="none", zorder=4)
    ax.annotate("", xy=(ex_x * 3.2, ex_y), xytext=(ex_x, ex_y),
                arrowprops=dict(arrowstyle="-|>", color="0.45", lw=0.9,
                                shrinkA=5, shrinkB=5.5, mutation_scale=8))
    ax.annotate("spad", xy=(ex_x, ex_y), xytext=(0, 7), textcoords="offset points",
                ha="center", fontsize=9, color="0.2")
    ax.annotate("cache A", xy=(ex_x * 3.2, ex_y), xytext=(0, 7), textcoords="offset points",
                ha="center", fontsize=9, color="0.2")
    ax.set_xlabel("operational intensity (Operations / DRAM byte)")
    ax.set_ylabel("performance (Operations / s)")
    ax.spines[["top", "right"]].set_visible(False)

    short = {KEEP_WORKLOADS[0]: "spikformer-cifar100",
             KEEP_WORKLOADS[1]: "sma-cifar10-dvs",
             KEEP_WORKLOADS[2]: "sma-dvs128-gesture"}
    handles = [Line2D([0], [0], marker="o", ls="none", ms=6,
                      markerfacecolor=WL_COLORS[w], markeredgecolor=WL_COLORS[w],
                      label=short[w]) for w in KEEP_WORKLOADS]
    handles += [Line2D([0], [0], marker=ARCH_MARKERS[a], ls="none", ms=6,
                       color="#444444", label=a) for a in base.ARCHES]
    ax.legend(handles=handles, fontsize=9, ncol=3, frameon=False,
              loc="lower center", bbox_to_anchor=(0.5, 1.01),
              handletextpad=0.3, columnspacing=0.7, borderaxespad=0.0)

    fig.savefig(OUT / "fig_roofline_cacheA.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_roofline_cacheA.png", bbox_inches="tight", dpi=300)
    n_set = {int(p["n_samples"]) for p in points}
    print(f"points: {len(points)}; n per point: {sorted(n_set)}; font: {family}")
    print("wrote outputs/fig_roofline_cacheA.pdf / .png")


if __name__ == "__main__":
    main()
