#!/usr/bin/env python3
"""Mock of the RQ5 figures (zoo/sensitivity/docs/plan.md) - FAKE numbers.

PERFORMANCE is the reported metric in both graphs (performance = 1 / T_s;
normalized, it is an inverse cycle ratio).

  G1  reuse-distance CDF across the swept VGG16 layers, TIED TO PERFORMANCE:
      one step curve per layer, and each legend entry carries that layer's
      performance, so CDF shape is checked against performance in one graph.
      The deep layer also carries a thin dashed REAL-CAPTURE validation
      curve, drawn for that layer alone to show the encoding Q6 decides on.
  G2  performance CHANGE vs density, swept DOWNWARD, three curves = the three
      layer types. cacheA only - no spad, no cacheB (plan, "The arms").
      y(d) = performance(d) / performance(d=1.00) for that same layer, which
      is what lets three layers whose absolute cycle counts differ by >10x
      share one panel.

These ship as TWO SEPARATE single-column floats; they are drawn into one
image here for review convenience only (plan, "Figure form").

REAL: layer names and shapes (zoo/wt500_fig3cfg/layer_shapes.md:217-231),
the L1/L2 capacity rules in lines (16384/64 = 256, 524288/64 = 8192), the
nine-point density grid, and the measured real input densities.
FAKE: every performance number, every CDF, every cycle count.
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rng = np.random.default_rng(11)

L1_LINES, L2_LINES = 256, 8192          # 16 KiB / 64 B, 512 KiB / 64 B
GRID = [1.00, 0.70, 0.50, 0.35, 0.25, 0.15, 0.10, 0.05, 0.02]
G1_DENSITY = 0.15                        # the grid point G1 is conditioned on

# (key, label, colour, dash, knee of the fake CDF, measured real density,
#  FAKE performance at d=0.15 in inferences/s, FAKE total_cycles)
LAYERS = [
    ("shallow", "layer_01_core_features_3   64/64  32x32  (36 KiB)",
     "#4477aa", (0, (1, 1)),   22.0, 0.1424, 7.9e3, 63_400),
    ("mid",     "layer_05_core_features_17  256/256  8x8  (576 KiB)",
     "#ccbb44", (0, (5, 2)),  140.0, 0.1669, 5.2e3, 96_300),
    ("deep",    "layer_08_core_features_27  512/512  4x4  (2.25 MiB)",
     "#ee6677", (0, ()),      620.0, 0.1968, 2.6e3, 192_600),
]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.5))

# =========================== G1: CDF tied to performance ===================
def fake_cdf(knee, n=900):
    """Fake reuse distances: lognormal around a per-layer knee, so the deeper
    layer's mass sits further right and crosses the capacity rules later."""
    d = rng.lognormal(np.log(knee), 0.85, n)
    x = np.sort(d)
    return x, np.arange(1, n + 1) / n

ax1.axvline(L1_LINES, color="0.55", lw=0.9, ls="--", zorder=1)
ax1.axvline(L2_LINES, color="0.55", lw=0.9, ls="--", zorder=1)

for key, label, colour, dash, knee, dreal, perf, cycles in LAYERS:
    x, y = fake_cdf(knee)
    cold = {"shallow": 3.1, "mid": 1.4, "deep": 0.9}[key]
    # Performance in the legend is what makes G1 one graph rather than a CDF
    # panel plus a performance panel.
    lbl = (f"{label}\n     perf {perf/1e3:.1f}k inf/s   "
           f"({cycles:,} cyc)   cold {cold:.1f} %")
    ax1.step(x, y, where="post", color=colour, ls=dash, lw=1.5, label=lbl,
             zorder=3)
    # Real-capture validation curve (plan S4, Q6): drawn for the deep layer
    # alone, so the encoding is visible without doubling G1's curve count.
    if key == "deep":
        xv, yv = fake_cdf(knee * 1.45)
        ax1.step(xv, yv, where="post", color=colour, ls=(0, (4, 2)), lw=0.9,
                 alpha=0.75, zorder=2,
                 label="deep, REAL capture at d = 0.197 (validation)")

# Rule labels go in the headroom ABOVE every curve: at the bottom of the
# panel they sit exactly where the deep layer's CDF crosses the L1 rule.
ax1.text(L1_LINES, 1.055, "L1  256 lines", fontsize=6.0, color="0.4",
         ha="center", va="bottom")
ax1.text(L2_LINES, 1.055, "L2  8192 lines", fontsize=6.0, color="0.4",
         ha="center", va="bottom")

ax1.set_xscale("log")
ax1.set_xlim(1, 3e5)
ax1.set_ylim(0, 1.12)
ax1.set_xlabel("reuse distance [unique 64 B weight lines]", fontsize=8.5)
ax1.set_ylabel("cumulative fraction of non-cold references", fontsize=8.5)
ax1.set_title(f"G1  reuse-distance CDF vs performance, VGG16 by depth\n"
              f"(synthetic traces at d = {G1_DENSITY})", fontsize=9)
# Below the panel: the three-line entries are too tall to sit inside
# without covering one of the curves they describe.
ax1.legend(fontsize=6.1, loc="upper left", bbox_to_anchor=(0.0, -0.155),
           bbox_transform=ax1.transAxes, frameon=False, labelspacing=0.55,
           handlelength=2.6)

# =========================== G2: performance change vs density =============
def fake_perf_change(d, strength):
    """Fake performance change relative to the dense anchor d=1.00.
    Rises as density falls; a bigger layer gains more, because more of its
    weight footprint is skipped once spikes gate the fetch."""
    return 1.0 + strength * (1.0 - np.asarray(d)) ** 1.35

STRENGTH = {"shallow": 0.42, "mid": 0.95, "deep": 1.85}

g = np.array(GRID)
for key, label, colour, dash, knee, dreal, perf, cycles in LAYERS:
    y = fake_perf_change(g, STRENGTH[key]) * rng.normal(1, 0.012, len(g))
    y[0] = 1.0                                   # the anchor is exact
    ax2.plot(g, y, marker="o", ms=4, lw=1.6, color=colour, ls=dash,
             label=f"{key}  {label.split()[0]}", zorder=3)
    # Measured real density for this layer: interpolation vs extrapolation.
    ax2.axvline(dreal, color=colour, lw=0.7, alpha=0.30, zorder=1)

# The stretch-only companion series, drawn for the deep layer alone so the
# encoding is visible without doubling the curve count (plan Q12).
ys = fake_perf_change(g, 1.85 * 0.46)
ax2.plot(g, ys, lw=1.2, ls=":", color="#ee6677", alpha=0.85, zorder=2,
         label="deep, stretch only (memory's share)")

ax2.axhline(1.0, color="0.3", lw=1.0, ls="--", zorder=2)
# Anchored at the sparse end: at the dense end the rule label sits under
# the three curves as they leave 1.0.
ax2.text(0.04, 0.975, "dense anchor (normalization, not a result)",
         fontsize=6.2, color="0.35", va="top", ha="right")

ax2.axvspan(0.12, 0.21, color="0.85", alpha=0.55, zorder=0)
ax2.text(0.165, 3.25, "measured real\ndensity band", fontsize=6.2,
         color="0.4", ha="center", va="top")

ax2.set_xlim(1.03, 0.0)                  # DECREASING left to right
ax2.set_xticks(GRID)
ax2.set_xticklabels([f"{v:g}" for v in GRID], fontsize=6.8, rotation=90)
ax2.set_ylim(0.90, 3.45)
ax2.set_xlabel("input spike density  (swept downward →)", fontsize=8.5)
ax2.set_ylabel("performance / performance at d = 1.00", fontsize=8.5)
ax2.set_title("G2  performance change vs controlled density\n"
              "cacheA only, three layer types", fontsize=9)
ax2.legend(fontsize=6.2, loc="upper left", frameon=False, handlelength=2.4)

for ax in (ax1, ax2):
    ax.grid(alpha=0.22, lw=0.4, which="both")
    ax.tick_params(labelsize=7)

fig.suptitle("MOCK - every performance number and every curve is fake "
             "(layer names, shapes, capacities and the density grid are real); "
             "these ship as TWO SEPARATE figures",
             fontsize=8.2, color="#bb2222", y=0.995)
fig.subplots_adjust(left=0.065, right=0.985, top=0.845, bottom=0.295,
                    wspace=0.22)
for ext in ("png", "pdf"):
    fig.savefig(f"sensitivity_mock.{ext}", dpi=200)
print("-> sensitivity_mock.png / .pdf")
