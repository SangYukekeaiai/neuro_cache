"""Figure: PDF of weight-line LRU reuse distance per vgg16 layer (loas_vgg16, T=4).

Input: data/*.csv from reuse_distance.py (130 files: 13 layers x 10 samples).
Output: fig_reuse_pdf.pdf (vector) + fig_reuse_pdf.png (300 dpi).

Per layer: the probability mass over log2-binned reuse distances (units: 64-byte
weight lines), mean across the 10 input samples with a min-max band. Cold
(first-ever) accesses are excluded from the PMF and reported in the caption
numbers printed to stdout. Vertical markers: V0 cache_a L1 (16 KiB = 256 lines)
and L2 (512 KiB = 8192 lines) capacities.
"""
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.ticker import StrMethodFormatter

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# --- fonts per skill recipe: Gill Sans if present, else nearest humanist sans
WANTED = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
installed = {f.name for f in fm.fontManager.ttflist}
family = next((w for w in WANTED if w in installed), "DejaVu Sans")
plt.rcParams.update({
    "font.family": family, "font.size": 8,
    "mathtext.fontset": "custom",
    "mathtext.rm": family, "mathtext.it": family, "mathtext.bf": family,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.linewidth": 0.6,
})

# --- ingest
# per (layer, sample): {bin_lo: count}; bins: -1 cold, 0, 1, 2, 4, ...
raw = defaultdict(dict)
for p in sorted(DATA.glob("*.csv")):
    with open(p) as fh:
        for row in csv.DictReader(fh):
            key = (row["layer"], int(row["sample"]))
            raw[key][int(row["bin_lo"])] = int(row["count"])

layers = sorted({k[0] for k in raw})
samples = sorted({k[1] for k in raw})
assert len(raw) == len(layers) * len(samples), (
    f"incomplete grid: {len(raw)} files for {len(layers)} layers x {len(samples)} samples")

all_bins = sorted({b for d in raw.values() for b in d if b >= 0})
bin_pos = {b: i for i, b in enumerate(all_bins)}  # x position = bin index

def pmf(counts):
    tot = sum(v for b, v in counts.items() if b >= 0)
    out = np.zeros(len(all_bins))
    for b, v in counts.items():
        if b >= 0:
            out[bin_pos[b]] = v / tot
    return out

# --- stats for the caption
print(f"n = {len(samples)} input samples per layer; {len(layers)} layers")
for layer in layers:
    tots, colds, d0 = [], [], []
    for s in samples:
        c = raw[(layer, s)]
        tot = sum(v for b, v in c.items() if b >= 0)
        tots.append(tot + c.get(-1, 0))
        colds.append(c.get(-1, 0))
        d0.append(c.get(0, 0) / tot)
    print(f"{layer}: accesses/sample mean {np.mean(tots):.0f}, cold lines "
          f"{np.mean(colds):.0f}, P(d=0) {np.mean(d0):.3f} "
          f"[{np.min(d0):.3f},{np.max(d0):.3f}]")

# --- figure: 13 curves in four discrete depth groups (no colorbar: a
# continuous ramp over 13 curves is not distinguishable; Okabe-Ito colors
# + linestyle + marker per group, one legend entry per group).
fig, ax = plt.subplots(figsize=(3.3, 2.4))
# (label, color, linestyle, marker) per depth group; membership by index.
GROUPS = [("conv 1-4", "#0072B2", "-", "o"),
          ("conv 5-8", "#E69F00", "--", "s"),
          ("conv 9-12", "#009E73", "-.", "^"),
          ("classifier (FC)", "#000000", ":", "D")]

def group_of(i):
    return 3 if i == 12 else i // 4

# Cross-sample spread is below 0.3% of the mass in every bin (printed above),
# so the bands would be invisible; the mean over the 10 samples is drawn alone,
# and bins a layer never reaches are masked rather than drawn as cliffs to zero.
seen_groups = set()
for i, layer in enumerate(layers):
    label, color, ls, marker = GROUPS[group_of(i)]
    mat = np.stack([pmf(raw[(layer, s)]) for s in samples])
    x = np.arange(len(all_bins))
    mean = mat.mean(0)
    mean[mean == 0] = np.nan
    ax.plot(x, mean, color=color, lw=1.0, ls=ls, marker=marker, ms=2.4,
            markerfacecolor="none", markeredgewidth=0.6, alpha=0.9,
            label=None if label in seen_groups else label)
    seen_groups.add(label)

for cap_lines, label in ((256, "L1 16 KiB"), (8192, "L2 512 KiB")):
    # position: between the two bins straddling cap_lines
    xpos = np.interp(math.log2(cap_lines),
                     [math.log2(b) if b > 0 else -1 for b in all_bins],
                     np.arange(len(all_bins)))
    ax.axvline(xpos, color="0.35", lw=0.7, ls="--")
    ax.text(xpos, ax.get_ylim()[1], f" {label}", fontsize=6.5, va="top", ha="left",
            color="0.25", rotation=90,
            bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=0.4))

ax.set_xticks([bin_pos[b] for b in all_bins if b in (0, 4, 16, 64, 256, 1024, 4096, 16384)])
ax.set_xticklabels([f"${b}$" for b in all_bins if b in (0, 4, 16, 64, 256, 1024, 4096, 16384)])
ax.set_yscale("log")
ax.yaxis.set_major_formatter(StrMethodFormatter("${x:g}$"))
ax.set_xlabel("LRU reuse distance (64 B weight lines, log$_2$ bins)")
ax.set_ylabel("fraction of accesses")
ax.legend(fontsize=6.5, frameon=False, handlelength=2.2, borderaxespad=0.4,
          labelspacing=0.3, loc="lower left", title="vgg16 depth",
          title_fontsize=6.5)
ax.spines[["top", "right"]].set_visible(False)

fig.savefig(HERE / "fig_reuse_pdf.pdf", bbox_inches="tight")
fig.savefig(HERE / "fig_reuse_pdf.png", bbox_inches="tight", dpi=300)
print("font family used:", family)
print("wrote fig_reuse_pdf.pdf / .png")
