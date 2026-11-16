#!/usr/bin/env python3
"""S6 for eval_scaling: render the figure from outputs/aggregate.csv.

Two series (boss 2026-11-16: cache series dropped from this figure).
Left: compute utilization (mean +/- 95% CI over samples).
Right: off-chip traffic normalized to single_x1 - solid markers = analytic
CoSA traffic (no CI, schedule-determined); open markers = nocsim-counted
DRAM words (with CI). Compulsory floor = analytic traffic with every
tensor fetched once (weight repeat count forced to 1).
"""

import csv
import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "outputs"
CAPTURE = "loas_vgg16_T4_n500"
C_SPAD, C_MULTI = "#4477aa", "#ee6677"
STYLE = {"single": ("single node, grown spad", C_SPAD, "o", "-"),
         "multi": ("multi-node, equal total", C_MULTI, "s", "--")}


def main() -> None:
    rows = list(csv.DictReader((OUT / "aggregate.csv").open()))
    base_w = float(next(r for r in rows if r["point"] == "single_x1")["analytic_traffic_bytes"])
    # compulsory floor: weight footprint fetched once, per layer, summed
    floor_bytes = 0.0
    for path in sorted((OUT / "s1" / "single_x1" / "schedules" / "loas" / CAPTURE).glob("*.json")):
        m = json.loads(path.read_text())["result"]["metrics"]
        floor_bytes += m["util"]["weight"]
    floor = floor_bytes / base_w

    fig, (ax_u, ax_t) = plt.subplots(1, 2, figsize=(8.0, 3.1))
    for side in ("single", "multi"):
        sub = sorted((r for r in rows if r["side"] == side),
                     key=lambda r: int(r["multiplier"]))
        x = [int(r["multiplier"]) for r in sub]
        lbl, c, mk, ls = STYLE[side]
        ax_u.errorbar(x, [float(r["util_mean"]) for r in sub],
                      yerr=[float(r["util_ci95"]) for r in sub],
                      fmt=mk, ls=ls, color=c, capsize=2, label=lbl)
        ax_t.plot(x, [float(r["analytic_traffic_norm"]) for r in sub],
                  marker=mk, ls=ls, color=c, label=lbl)
        ax_t.errorbar(x, [float(r["counted_traffic_norm"]) for r in sub],
                      yerr=[float(r["counted_traffic_norm_ci95"]) for r in sub],
                      fmt=mk, ls="", color=c, capsize=2,
                      markerfacecolor="none", alpha=0.8)

    ax_u.set(ylim=(0, 1.05), ylabel="Compute utilization U",
             xlabel="Total on-chip capacity (x base)", xscale="log")
    ax_t.axhline(floor, color="0.4", lw=.8, ls=":")
    ax_t.text(1.05, floor * 1.05, "compulsory floor", fontsize=7, color="0.35")
    ax_t.set(ylabel="Off-chip traffic / single x1",
             xlabel="Total on-chip capacity (x base)", xscale="log", yscale="log")
    for ax in (ax_u, ax_t):
        ax.set_xticks([1, 2, 4, 8, 16])
        ax.set_xticklabels([f"{v}x" for v in (1, 2, 4, 8, 16)])
        ax.minorticks_off()
        ax.grid(alpha=.25, lw=.5)
        ax.tick_params(labelsize=8)
    ax_u.legend(fontsize=7, loc="lower left", framealpha=.9)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"eval_scaling.{ext}", dpi=200)
    print("->", OUT / "eval_scaling.pdf")


if __name__ == "__main__":
    main()
