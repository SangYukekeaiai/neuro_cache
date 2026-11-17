"""Fig 1 redo: PTB + LoAS only, 128K baseline, ideal off-chip-other from 1M.

Reads the pinned campaign product outputs/fig1_numbers.csv (snapshot on
/work; raw nJ means + CIs per arch x bar x segment) and re-renders:
  - panels: PTB, LoAS (GustavSNN dropped per user call);
  - normalization: each architecture's own 128K total = 1.0 (first bar);
  - the ideal bar's off_chip_other segment is substituted with the 1M
    configuration's value (user call: ideal's own leakage term follows
    the uncertain runtime midpoint; the 1M figure stands in for it) -
    stated in the caption, whiskers use the substituted interval;
  - an arrow annotates the off-chip (weights + other) energy reduction
    of ideal versus the 128K baseline, in x.

Run: conda run -n base python src/fig1_redo.py
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent.parent
NUMBERS = Path("/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/"
               "fig1_energy_profiling/outputs/fig1_numbers.csv")
OUT = HERE / "outputs"
ARCHES = [("ptb", "PTB"), ("loas", "LoAS")]
BARS = ["128k", "256k", "512k", "1m", "ideal"]
BAR_LABELS = ["128K", "256K", "512K", "1M", "Ideal"]
SEGMENTS = [("compute", "Compute", "#0077bb", ""),
            ("on_chip_sram", "Local SRAM", "#ddaa33", ".."),
            ("off_chip_weights", "Off-chip weights", "#ee7733", "//"),
            ("off_chip_other", "Off-chip other", "#bbbbbb", "xx")]


def load():
    rows = {}
    with NUMBERS.open(newline="") as stream:
        for row in csv.DictReader(stream):
            rows[(row["arch"], row["bar"], row["segment"])] = row
    return rows


def main():
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 7,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family, "mathtext.bf": family,
        "hatch.linewidth": 0.5,
    })

    rows = load()

    def seg(arch, bar, segment):
        """Raw-nJ row for a segment, with the ideal other <- 1M substitution."""
        if bar == "ideal" and segment == "off_chip_other":
            return rows[(arch, "1m", segment)]
        return rows[(arch, bar, segment)]

    fig, axes = plt.subplots(1, len(ARCHES), figsize=(3.4, 2.15), sharey=True)
    for ax, (arch, title) in zip(axes, ARCHES):
        base = float(rows[(arch, "128k", "total")]["mean_energy_nJ"])
        tops = {}
        for bi, bar in enumerate(BARS):
            bottom = 0.0
            lo_sum = hi_sum = 0.0
            for segment, _, colour, hatch in SEGMENTS:
                row = seg(arch, bar, segment)
                value = float(row["mean_energy_nJ"]) / base
                lo_sum += float(row["interval_lower_nJ"]) / base
                hi_sum += float(row["interval_upper_nJ"]) / base
                ax.bar(bi, value, width=0.66, bottom=bottom, color=colour,
                       hatch=hatch, edgecolor="0.25", lw=0.5, zorder=3)
                bottom += value
            tops[bar] = bottom
            ax.errorbar(bi, (lo_sum + hi_sum) / 2.0,
                        yerr=[[(lo_sum + hi_sum) / 2.0 - lo_sum],
                              [hi_sum - (lo_sum + hi_sum) / 2.0]],
                        fmt="none", ecolor="0.15", elinewidth=0.8, capsize=1.6,
                        zorder=4)
        ax.axhline(1.0, color="0.3", lw=0.9, ls="--", zorder=2)

        # off-chip reduction arrow: 128K baseline vs ideal (weights + other)
        off_base = sum(float(seg(arch, "128k", s)["mean_energy_nJ"])
                       for s in ("off_chip_weights", "off_chip_other")) / base
        off_ideal = sum(float(seg(arch, "ideal", s)["mean_energy_nJ"])
                        for s in ("off_chip_weights", "off_chip_other")) / base
        gain = off_base / off_ideal
        ax.annotate("", xy=(len(BARS) - 1 + 0.05, tops["ideal"] + 0.03),
                    xytext=(0.37, tops["128k"] - 0.02),
                    arrowprops=dict(arrowstyle="->", color="0.1", lw=1.0,
                                    connectionstyle="arc3,rad=-0.25"))
        ax.text(2.7, 1.035, f"{gain:.1f}$\\times$ less off-chip energy",
                fontsize=5.8, ha="center", color="0.1")
        print(f"{arch}: off-chip 128K {off_base:.4f} -> ideal {off_ideal:.4f} "
              f"({gain:.2f}x); totals " +
              " ".join(f"{b}={tops[b]:.3f}" for b in BARS))

        ax.set_title(title, fontsize=7.5, weight="bold", pad=3)
        ax.set_xticks(range(len(BARS)))
        ax.set_xticklabels(BAR_LABELS, fontsize=6, rotation=38, ha="right")
        ax.set_ylim(0, 1.12)
        ax.grid(axis="y", alpha=0.25, lw=0.4, zorder=0)
        ax.tick_params(labelsize=6.2, pad=1.5)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("Normalized energy\n(128 KiB = 1)", fontsize=7)
    fig.legend(handles=[Patch(facecolor=c, hatch=h, edgecolor="0.25", label=l)
                        for _, l, c, h in SEGMENTS],
               ncol=2, frameon=False, fontsize=6.2, loc="lower center",
               bbox_to_anchor=(0.54, 0.955), handletextpad=0.5, columnspacing=0.9)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_energy_profiling_v2.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig1_energy_profiling_v2.png", bbox_inches="tight", dpi=300)
    print("wrote outputs/fig1_energy_profiling_v2.pdf / .png")
    print(f"font: {family}")


if __name__ == "__main__":
    main()
