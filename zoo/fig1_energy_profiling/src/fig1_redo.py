"""Fig 1 redo: PTB + LoAS only, off-chip segments only, 128K baseline.

Reads the pinned campaign product outputs/fig1_numbers.csv (snapshot on
/work; raw nJ means per arch x bar x segment) and re-renders:
  - panels: PTB, LoAS (GustavSNN dropped per user call);
  - segments: off-chip weights + off-chip other only (compute and local
    SRAM dropped per user call, 2026-11-17);
  - normalization: each architecture's own 128K off-chip total = 1.0;
  - the ideal bar's off_chip_other segment is substituted with the 1M
    configuration's value (ideal's own leakage term follows the
    uncertain runtime midpoint; the 1M figure stands in for it);
  - each non-baseline bar is labeled with its gap to the 128K baseline
    (arrow, CI whiskers, and the dashed baseline line removed).

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
SEGMENTS = [("off_chip_weights", "Off-chip weights", "#ee7733", "//"),
            ("off_chip_other", "Off-chip other", "#bbbbbb", "xx")]


def load():
    rows = {}
    with NUMBERS.open(newline="") as stream:
        for row in csv.DictReader(stream):
            rows[(row["arch"], row["bar"], row["segment"])] = row
    return rows


def main():
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "Cantarell", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 8,
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

    fig, axes = plt.subplots(1, len(ARCHES), figsize=(3.4, 1.8), sharey=True)
    for ax, (arch, title) in zip(axes, ARCHES):
        base = sum(float(seg(arch, "128k", s)["mean_energy_nJ"])
                   for s, _, _, _ in SEGMENTS)
        tops = {}
        for bi, bar in enumerate(BARS):
            bottom = 0.0
            for segment, _, colour, hatch in SEGMENTS:
                value = float(seg(arch, bar, segment)["mean_energy_nJ"]) / base
                ax.bar(bi, value, width=0.66, bottom=bottom, color=colour,
                       hatch=hatch, edgecolor="0.25", lw=0.5, zorder=3)
                bottom += value
            tops[bar] = bottom
            if bar != "128k":
                ax.text(bi, bottom + 0.035, f"$-{(1 - bottom) * 100:.0f}$%",
                        ha="center", va="bottom", fontsize=6)
        gain = tops["128k"] / tops["ideal"]
        print(f"{arch}: off-chip ideal gain {gain:.2f}x; totals " +
              " ".join(f"{b}={tops[b]:.3f}" for b in BARS))

        ax.set_title(title, fontsize=8.5, weight="bold", pad=3)
        ax.set_xticks(range(len(BARS)))
        ax.set_xticklabels(BAR_LABELS, fontsize=7, rotation=38, ha="right")
        ax.set_ylim(0, 1.12)
        ax.grid(axis="y", alpha=0.25, lw=0.4, zorder=0)
        ax.tick_params(labelsize=7, pad=1.5)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("Normalized off-chip\nenergy (128 KiB = 1)", fontsize=7.5)
    fig.legend(handles=[Patch(facecolor=c, hatch=h, edgecolor="0.25", label=l)
                        for _, l, c, h in SEGMENTS],
               ncol=2, frameon=False, fontsize=7, loc="lower center",
               bbox_to_anchor=(0.54, 0.915), handletextpad=0.5, columnspacing=0.9)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_energy_profiling_v2.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig1_energy_profiling_v2.png", bbox_inches="tight", dpi=300)
    print("wrote outputs/fig1_energy_profiling_v2.pdf / .png")
    print(f"font: {family}")


if __name__ == "__main__":
    main()
