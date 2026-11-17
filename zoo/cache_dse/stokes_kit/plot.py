#!/usr/bin/env python3
"""Plot the measured ten-bar cache-DSE performance and EDP figure."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


GROUP_COLOUR = {"base": "#444444", "capacity": "#4477aa", "replacement": "#228833",
                "bound": "#aa3377", "prefetch": "#ee6677"}
ORDER = ["V0", "V1a", "V1b", "V2a", "V2b", "V3a", "V3b", "V4", "V5", "V6"]
BELADY = ORDER.index("V4")
# changed config keys per variant, printed under the tick labels (mock layout)
CONFIG_KEYS = {"V0": "operating point", "V1a": "l2_size_bytes=262144",
               "V1b": "l2_size_bytes=1048576", "V2a": "l1_size_bytes=8192",
               "V2b": "l1_size_bytes=32768", "V3a": "l2_policy=lru",
               "V3b": "policy=lfu, l2_policy=lfu", "V4": "l2_policy=belady",
               "V5": "prefetch_policy=next_line",
               "V6": "+ l2_prefetch_policy=next_line"}


def rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as stream:
        values = {row["variant"]: row for row in csv.DictReader(stream)}
    if list(values) != ORDER or set(values) != set(ORDER):
        raise SystemExit(f"summary must contain variants in plan order: {path}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--png", required=True)
    parser.add_argument("--pdf", required=True)
    args = parser.parse_args()
    data = rows(Path(args.summary).expanduser().resolve())
    # display-only shortenings for single-column fit at >=6 pt type; the
    # caption and groups carry the dropped words
    SHORT = {"pure LRU": "LRU", "pure LFU": "LFU",
             "L1 next-line": "L1 n-l", "L1+L2 n-l": "L1+L2",
             # manifest's qualifier, not yet in the committed summary CSV
             "Belady\n(V4)": "demand-only\nBelady (V4)"}
    labels = [data[key]["short_label"] for key in ORDER]
    for old, new in SHORT.items():
        labels = [label.replace(old, new) for label in labels]
    groups = [data[key]["group"] for key in ORDER]
    performance = np.array([float(data[key]["performance_norm"]) for key in ORDER])
    perf_err = np.array([float(data[key]["performance_ci95"]) for key in ORDER])
    edp = np.array([float(data[key]["edp_norm"]) for key in ORDER])
    edp_err = np.array([float(data[key]["edp_ci95"]) for key in ORDER])
    x = np.arange(len(ORDER))
    # single-column geometry (user call 2026-11-16): same content, ~3.4 in wide
    fig, (axp, axe) = plt.subplots(2, 1, figsize=(3.4, 4.0), sharex=True)
    for ax, values, errors, ylabel, better in (
            (axp, performance, perf_err, "performance / cacheA\n(1 / latency)", "higher is better"),
            (axe, edp, edp_err, "EDP / cacheA\n(sum(E) x sum(t))", "lower is better")):
        colours = [GROUP_COLOUR[group] for group in groups]
        bars = ax.bar(x, values, width=0.68, color=colours, edgecolor="0.25", lw=0.6, zorder=3)
        ax.errorbar(x, values, yerr=errors, fmt="none", ecolor="0.2", elinewidth=0.7,
                    capsize=1.8, zorder=4)
        belady_bar = bars[BELADY]
        belady_bar.set_facecolor("none")
        belady_bar.set_hatch("///")
        belady_bar.set_edgecolor(GROUP_COLOUR["bound"])
        belady_bar.set_linewidth(1.2)
        # band between the 1.0 rule and the V4 probe in both panels: the
        # probe's distance from cacheA (its loss on EDP), not headroom
        lo, hi = sorted((1.0, float(values[BELADY])))
        ax.axhspan(lo, hi, color=GROUP_COLOUR["bound"], alpha=0.10, zorder=0)
        ax.axhline(1.0, color="0.3", lw=0.9, ls="--", zorder=2)
        ax.text(len(ORDER) - 0.42, 1.015, "cacheA", fontsize=5.8, color="0.3",
                ha="right", va="bottom")
        ax.set_ylabel(ylabel, fontsize=7.0)
        ax.set_ylim(0, max(1.0, float(np.max(values + errors))) * 1.22)
        ax.text(0.004, 0.94, better, transform=ax.transAxes, fontsize=6.0,
                color="0.3", style="italic", va="top")
        ax.grid(axis="y", alpha=0.25, lw=0.4, zorder=0)
        ax.tick_params(labelsize=6.0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for i in range(1, len(ORDER)):
            if groups[i] != groups[i - 1]:
                ax.axvline(i - 0.5, color="0.8", lw=0.7, zorder=1)
    # V4 reading per RUN.md: prefetched fills have no demand-oracle entry
    # (kNever) and are evicted first, so V4 probes demand-retention value;
    # the band is the oracle's loss (refetch energy), not headroom.
    axe.annotate("demand-only Belady probe, not a design:\nband = EDP lost to evicting prefetched fills",
                 xy=(BELADY - 0.3, edp[BELADY]),
                 xytext=(0.9, float(axe.get_ylim()[1]) * 0.72),
                 fontsize=5.8, color=GROUP_COLOUR["bound"], ha="left",
                 arrowprops=dict(arrowstyle="->", color=GROUP_COLOUR["bound"],
                                 lw=0.8, connectionstyle="arc3,rad=-0.15"))
    axe.set_xticks(x)
    # stagger alternate labels so neighbours clear each other at 6 pt
    axe.set_xticklabels([lab if i % 2 == 0 else "\n\n" + lab
                         for i, lab in enumerate(labels)], fontsize=6.0,
                        linespacing=0.95)
    axe.set_xlim(-0.7, len(ORDER) - 0.3)
    # config-key row removed (user call 2026-11-16): the long rotated
    # labels are gone; CONFIG_KEYS stays for reference.
    seen, start = groups[0], 0
    for i in range(1, len(groups) + 1):
        group = groups[i] if i < len(groups) else None
        if group != seen:
            # "replacement" is display-shortened so the five bold group
            # headers clear each other at single-column width; "bound" is
            # displayed as "probe" - V4 is a demand-only probe, not a bound
            axp.text((start + i - 1) / 2.0, 1.012,
                     {"replacement": "replace.", "bound": "probe"}.get(seen, seen),
                     fontsize=6.0, color=GROUP_COLOUR[seen], ha="center",
                     va="bottom", transform=axp.get_xaxis_transform(),
                     weight="bold")
            seen, start = group, i
    fig.suptitle("RQ4 cache design space - B09/loas_vgg16_T4_n500, arch loas",
                 fontsize=6.4, y=0.995)
    fig.text(0.5, 0.935,
             "Measured cacheA variants; 12 conv layers x 10 samples;\n"
             "EDP: ASAP7 1 GHz measured logic + 7 nm CACTI cache + pinned DDR4",
             fontsize=5.8, color="0.3", ha="center", va="top")
    fig.subplots_adjust(left=0.155, right=0.98, top=0.858, bottom=0.115, hspace=0.12)
    Path(args.png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.png, dpi=220)
    fig.savefig(args.pdf)
    print(f"wrote {args.png} and {args.pdf}")


if __name__ == "__main__":
    main()
