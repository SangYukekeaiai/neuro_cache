#!/usr/bin/env python3
"""Mock of the redefined RQ4 figure (zoo/cache_dse/docs/plan.md) - FAKE numbers.

Shape per plan ("Figure form: a bar chart, two panels"):
  one categorical x-axis of ten configs (cacheA + nine variants);
  top panel    = performance, normalized to cacheA, HIGHER is better;
  bottom panel = EDP,         normalized to cacheA, LOWER  is better;
  bars from zero on both - these are ratios of non-negative quantities with
  a meaningful zero, so bar length is proportional to the quantity. If a
  later revision truncates either y-axis, bars stop being honest here.

Belady (V4) is a BOUND, not a buildable design: hatched open bar plus a band
back to the 1.0 rule, so it cannot be read as the eighth design point.

Config names, config keys, the benchmark and the metric definitions are REAL
(zoo/cache_dse/docs/plan.md; B09/loas_vgg16_T4_n500, arch loas).
  performance = 1 / T_s, normalized -> total_cycles(V0) / total_cycles(V)
  EDP_nJ_s    = (E_dyn_nJ + E_leak_nJ) * T_s
Every plotted number is invented.
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---- the ten configs, in plan order, grouped by what the knob touches -----
# (short label, config keys changed, group)
CONFIGS = [
    ("cacheA\n(V0)",      "",                              "base"),
    ("L2 256K\n(V1a)",    "l2_size_bytes=262144",          "capacity"),
    ("L2 1M\n(V1b)",      "l2_size_bytes=1048576",         "capacity"),
    ("L1 8K\n(V2a)",      "l1_size_bytes=8192",            "capacity"),
    ("L1 32K\n(V2b)",     "l1_size_bytes=32768",           "capacity"),
    ("pure LRU\n(V3a)",   "l2_policy=lru",                 "replacement"),
    ("pure LFU\n(V3b)",   "policy=lfu, l2_policy=lfu",     "replacement"),
    ("Belady\n(V4)",      "l2_policy=belady",              "bound"),
    ("L1 next-line\n(V5)", "prefetch_policy=next_line",    "prefetch"),
    ("L1+L2 n-l\n(V6)",   "+ l2_prefetch_policy=next_line", "prefetch"),
]
BELADY = 7
N = len(CONFIGS)

# ---- FAKE whole-model ratios to cacheA ------------------------------------
# Invented to illustrate the reading the plan expects:
#   - the prefetch variants cost the most (the L1 prefetcher is what makes
#     the design work, so replacing next_access with next_line hurts);
#   - the capacity variants move less, because the L1 prefetcher leaves the
#     L2 only 1,152 demand accesses (plan, "the L2 sees almost no demand");
#   - Belady sits just past 1.0: little headroom left in replacement.
# Performance: higher is better.  EDP: lower is better.
PERF = np.array([1.00, 0.93, 1.04, 0.78, 1.11, 0.94, 0.90, 1.03, 0.62, 0.66])
EDP  = np.array([1.00, 1.16, 0.93, 1.47, 0.86, 1.13, 1.22, 0.95, 1.94, 1.78])

# Fake per-config spread over the 5 samples x 12 layers (plan Q5).
ERR_P = np.array([.02, .03, .02, .05, .03, .03, .04, .02, .06, .05])
ERR_E = np.array([.03, .05, .04, .08, .04, .05, .06, .03, .11, .09])

GROUP_COLOUR = {"base": "#444444", "capacity": "#4477aa",
                "replacement": "#228833", "bound": "#aa3377",
                "prefetch": "#ee6677"}

x = np.arange(N)
fig, (axp, axe) = plt.subplots(2, 1, figsize=(7.6, 5.4), sharex=True)

for ax, vals, errs, label, better in (
        (axp, PERF, ERR_P, "performance / cacheA\n(1 / latency)", "higher is better"),
        (axe, EDP,  ERR_E, "EDP / cacheA\n(E x t)",               "lower is better")):

    colours = [GROUP_COLOUR[c[2]] for c in CONFIGS]
    bars = ax.bar(x, vals, width=0.68, color=colours, edgecolor="0.25", lw=0.6,
                  zorder=3)
    ax.errorbar(x, vals, yerr=errs, fmt="none", ecolor="0.2", elinewidth=0.8,
                capsize=2.5, zorder=4)

    # The bound: hollow + hatched, and a band back to the operating point.
    b = bars[BELADY]
    b.set_facecolor("none")
    b.set_hatch("///")
    b.set_edgecolor(GROUP_COLOUR["bound"])
    b.set_linewidth(1.2)
    lo, hi = sorted((1.0, vals[BELADY]))
    ax.axhspan(lo, hi, color=GROUP_COLOUR["bound"], alpha=0.10, zorder=0)

    ax.axhline(1.0, color="0.3", lw=1.0, ls="--", zorder=2)
    ax.text(N - 0.42, 1.015, "cacheA", fontsize=6.4, color="0.3",
            ha="right", va="bottom")

    ax.set_ylabel(label, fontsize=8)
    ax.set_ylim(0, max(vals + errs) * 1.22)
    ax.text(0.004, 0.94, better, transform=ax.transAxes, fontsize=6.8,
            color="0.3", style="italic", va="top")
    ax.grid(axis="y", alpha=0.25, lw=0.4, zorder=0)
    ax.tick_params(labelsize=7)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    # Group separators: the ranking claim is between groups, not neighbours.
    for i in range(1, N):
        if CONFIGS[i][2] != CONFIGS[i - 1][2]:
            ax.axvline(i - 0.5, color="0.8", lw=0.7, zorder=1)

# Annotated on the EDP panel: its upper-left is the only region of either
# panel with no bar, no rule and no group caption in it.
axe.annotate("bound, not a design:\nheadroom left to L2 replacement",
             xy=(BELADY - 0.3, EDP[BELADY]), xytext=(0.65, 2.18),
             fontsize=6.2, color=GROUP_COLOUR["bound"], ha="left",
             arrowprops=dict(arrowstyle="->", color=GROUP_COLOUR["bound"],
                             lw=0.8, connectionstyle="arc3,rad=-0.15"))

axe.set_xticks(x)
axe.set_xticklabels([c[0] for c in CONFIGS], fontsize=6.8)
axe.set_xlim(-0.7, N - 0.3)

# The changed config keys, under the tick labels.
for i, (_, keys, _) in enumerate(CONFIGS):
    axe.text(i, -0.30, keys if keys else "operating point", fontsize=4.9,
             color="0.4", ha="center", va="top", rotation=90,
             transform=axe.get_xaxis_transform(), family="monospace")

# Group captions, ABOVE the top panel: the ranking claim is between groups,
# and below the axis they collide with the rotated config keys.
seen, start = CONFIGS[0][2], 0
for i in range(1, N + 1):
    g = CONFIGS[i][2] if i < N else None
    if g != seen:
        axp.text((start + i - 1) / 2.0, 1.012, seen, fontsize=6.8,
                 color=GROUP_COLOUR[seen], ha="center", va="bottom",
                 transform=axp.get_xaxis_transform(), weight="bold")
        seen, start = g, i

fig.suptitle("MOCK - fake numbers (configs, config keys, benchmark and "
             "metric definitions are real)", fontsize=8.5, color="#bb2222",
             y=0.995)
fig.text(0.5, 0.955, "RQ4 cache design space - B09/loas_vgg16_T4_n500, "
                     "arch loas, 12 conv layers x 5 samples",
         fontsize=7.8, color="0.3", ha="center")

fig.subplots_adjust(left=0.105, right=0.985, top=0.875, bottom=0.30, hspace=0.12)
for ext in ("png", "pdf"):
    fig.savefig(f"cache_dse_mock.{ext}", dpi=200)
print("-> cache_dse_mock.png / .pdf")
