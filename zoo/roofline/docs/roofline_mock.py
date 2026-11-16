#!/usr/bin/env python3
"""Mock of the RQ3 roofline figure (zoo/roofline/docs/plan.md) - FAKE numbers.

Axes/roofs per plan: P = SOP/cycle, OI = SOP/DRAM payload byte,
compute roof 64 SOP/cycle (16 nodes x 4 PEs), BW roof 128 B/cycle.
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOF_P, ROOF_BW = 64.0, 128.0
RIDGE = ROOF_P / ROOF_BW  # 0.5 SOP/byte

# point: (OI, P, label, color, marker)
POINTS = [
    (0.08, 9.8,  "multi-node spad",   "#ee6677", "s"),
    (0.21, 21.0, "spad + SpikeX tags", "#ccbb44", "D"),
    (0.65, 36.0, "cache (seq pf)",     "#228833", "o"),
    (1.10, 44.0, "cache (spike pf)",   "#228833", "^"),
    (2.60, 57.0, "Belady ceiling",     "0.2",     "*"),
]

oi = np.logspace(-1.5, 1, 200)
roof = np.minimum(ROOF_P, ROOF_BW * oi)

fig, ax = plt.subplots(figsize=(4.4, 3.2))
ax.plot(oi, roof, color="0.15", lw=1.4)
ax.axvline(RIDGE, color="0.75", lw=0.6, ls=":")
ax.text(0.04, 20, "DRAM BW roof\n128 B/cycle", fontsize=7, color="0.3", rotation=38)
ax.text(1.5, 67, "compute roof 64 SOP/cycle", fontsize=7, color="0.3")

for x, y, lbl, c, mk in POINTS:
    ax.errorbar(x, y, xerr=x * 0.06, yerr=y * 0.05, fmt=mk, color=c,
                ms=8 if mk == "*" else 5.5, capsize=2, zorder=3)
    ax.annotate(lbl, (x, y), textcoords="offset points", xytext=(5, -9), fontsize=7)

# distance-to-roof for the headline pair
for x, y in [(0.08, 9.8), (1.10, 44.0)]:
    r = min(ROOF_P, ROOF_BW * x)
    ax.annotate("", (x, r), (x, y), arrowprops=dict(arrowstyle="->", color="0.6", lw=0.7))
    ax.text(x * 1.08, (y * r) ** 0.5, f"{r / y:.1f}x", fontsize=6.5, color="0.4")

ax.set(xscale="log", yscale="log", xlim=(0.03, 10), ylim=(3, 90),
       xlabel="Operational intensity [SOP / DRAM byte]",
       ylabel="Performance [SOP / cycle]")
ax.grid(alpha=0.25, lw=0.5, which="both")
ax.tick_params(labelsize=8)
ax.set_title("MOCK - fake numbers", fontsize=8, color="#bb2222")
fig.tight_layout()
for ext in ("png", "pdf"):
    fig.savefig(f"roofline_mock.{ext}", dpi=200)
print("-> roofline_mock.png")
