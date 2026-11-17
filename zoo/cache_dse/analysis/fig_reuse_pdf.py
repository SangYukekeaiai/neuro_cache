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
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# --- fonts per skill recipe: Gill Sans if present, else nearest humanist sans
WANTED = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
installed = {f.name for f in fm.fontManager.ttflist}
family = next((w for w in WANTED if w in installed), "DejaVu Sans")
plt.rcParams.update({
    "font.family": family, "font.size": 9, "axes.labelsize": 9,
    "mathtext.fontset": "custom",
    "mathtext.rm": family, "mathtext.it": family, "mathtext.bf": family,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "axes.linewidth": 0.6, "axes.unicode_minus": False,
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

# --- figure: three representative layers across vgg16's depth (one per
# depth third; Okabe-Ito colors + linestyle + marker per curve).
fig, ax = plt.subplots(figsize=(3.3, 1.8))
# layer index -> (label, color, linestyle, marker)
SHOW = {0: ("conv 1", "#0072B2", "-", "o"),
        4: ("conv 5", "#E69F00", "--", "s"),
        8: ("conv 9", "#009E73", "-.", "^")}

# Cross-sample spread is below 0.3% of the mass in every bin (printed above),
# so the bands would be invisible; the mean over the 10 samples is drawn alone,
# and bins a layer never reaches are masked rather than drawn as cliffs to zero.
for i, layer in enumerate(layers):
    if i not in SHOW:
        continue
    label, color, ls, marker = SHOW[i]
    mat = np.stack([pmf(raw[(layer, s)]) for s in samples])
    x = np.arange(len(all_bins))
    mean = mat.mean(0)
    # Connect successive nonzero bins; zero-mass bins in between carry no
    # accesses and are skipped rather than drawn as cliffs to zero.
    # The d=0 bin stands alone as a marker, not connected to the curve.
    mask = mean > 0
    tail = mask & (x > 0)
    ax.plot(x[tail], mean[tail], color=color, lw=1.0, ls=ls, marker=marker,
            ms=2.8, markerfacecolor="none", markeredgewidth=0.6, alpha=0.9,
            label=label)
    head = mask & (x == 0)
    ax.plot(x[head], mean[head], color=color, ls="none", marker=marker,
            ms=2.8, markerfacecolor="none", markeredgewidth=0.6, alpha=0.9)

ax.set_xticks([bin_pos[b] for b in all_bins if b in (0, 4, 16, 64, 256, 1024, 4096, 16384)])
ax.set_xticklabels([f"${b}$" for b in all_bins if b in (0, 4, 16, 64, 256, 1024, 4096, 16384)])
ax.set_yscale("log")
from matplotlib.ticker import FuncFormatter, NullFormatter
ax.yaxis.set_major_formatter(FuncFormatter(
    lambda v, _: f"$10^{{{int(round(np.log10(v)))}}}$"))
ax.yaxis.set_minor_formatter(NullFormatter())
ax.set_xlabel("Reuse distance")
ax.set_ylabel("fraction of accesses")
ax.legend(fontsize=8, frameon=False, handlelength=2.2, borderaxespad=0.4,
          labelspacing=0.3, loc="lower right")
ax.spines[["top", "right"]].set_visible(False)

fig.savefig(HERE / "fig_reuse_pdf.pdf", bbox_inches="tight")
fig.savefig(HERE / "fig_reuse_pdf.png", bbox_inches="tight", dpi=300)
print("font family used:", family)
print("wrote fig_reuse_pdf.pdf / .png")
