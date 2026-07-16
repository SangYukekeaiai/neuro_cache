#!/usr/bin/env python3
"""Visualize the best schedule across the arch × workload sweep.

Loads outputs/weight_sweep/metrics.jsonl and produces three figures:

  Fig 1 – Winner heatmap:   which TrafficMode wins per (arch, workload) pair
  Fig 2 – Score-gap strip:  how much better the winner is vs. runner-up,
                            grouped by winning mode
  Fig 3 – Metric profiles:  normalised delay / traffic / utilisation per mode
                            (mean ± std across all pairs), to show WHY a mode wins

Usage (from project root):
    python scripts/visualize_best_schedule.py
    python scripts/visualize_best_schedule.py --out outputs/figures/best_schedule.pdf

Requires: matplotlib, numpy (both already in the cosa_snn env).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = PROJECT_ROOT / "outputs" / "weight_sweep" / "metrics.jsonl"
RESULTS_PATH = PROJECT_ROOT / "outputs" / "weight_sweep" / "weight_results.json"
DEFAULT_OUT  = PROJECT_ROOT / "outputs" / "weight_sweep" / "best_schedule_vis.pdf"

# Recommended weights (from weight_results.json)
W_U  = 0.0041753189365604
W_TR = 1.0
W_DL = 1.0

# Canonical display order for modes (best → worst typical)
MODE_ORDER = [
    "both_gb_oooo",
    "both_dram_oooo",
    "psum_gb_ootk",
    "both_dram_ootk",
    "psum_boundary",
    "vmem_gb_xxxt",
    "vmem_dram_xxxt",
    "base",
]

MODE_LABELS = {
    "both_gb_oooo":    "both→GB\n(oooo)",
    "both_dram_oooo":  "both→DRAM\n(oooo)",
    "psum_gb_ootk":    "psum→GB\n(ootk)",
    "both_dram_ootk":  "both→DRAM\n(ootk)",
    "psum_boundary":   "psum\nboundary",
    "vmem_gb_xxxt":    "vmem→GB\n(xxxt)",
    "vmem_dram_xxxt":  "vmem→DRAM\n(xxxt)",
    "base":            "base",
}

# Colour palette: one per mode
_PALETTE = plt.cm.tab10.colors
MODE_COLOR = {m: _PALETTE[i % len(_PALETTE)] for i, m in enumerate(MODE_ORDER)}


# ── data loading ──────────────────────────────────────────────────────────────

def _score(m: dict) -> float:
    return W_U * m["util_sum"] + W_TR * m["tr_sum"] + W_DL * m["dl"]


def load_records(path: Path) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            feasible = [m for m in rec.get("modes", []) if isinstance(m.get("feasible"), dict)]
            if len(feasible) < 2:
                continue
            # Annotate with scores and winner
            for m in feasible:
                m["score"] = _score(m)
            feasible.sort(key=lambda m: m["score"])
            rec["feasible"] = feasible
            rec["winner"]   = feasible[0]["mode"]
            records.append(rec)
    return records


# ── figure 1: winner heatmap ──────────────────────────────────────────────────

def _shorten_arch(k: str) -> str:
    # e.g. nodes16_gb64kb_w24_p4_v4 → "N16\nGB64\nw24"
    parts = k.split("_")
    nodes = parts[0].replace("nodes", "N")
    gb    = parts[1].replace("kb", "K")
    split = parts[2]               # e.g. w24
    return f"{nodes}\n{gb}\n{split}"


def _shorten_wl(k: str) -> str:
    # e.g. resnet19_conv1_T4 → "res/c1\nT4"
    if k.startswith("resnet"):
        net = "res"
        rest = k[len("resnet19_"):]
    else:
        net = "vgg"
        rest = k[len("vgg16_"):]
    layer, T = rest.rsplit("_", 1)
    layer_short = layer.replace("conv5_3", "c5").replace("conv1", "c1")
    return f"{net}/{layer_short}\n{T}"


def fig_winner_heatmap(records: list[dict], ax: plt.Axes) -> None:
    # Build arch × wl matrix
    arch_keys = sorted(set(r["arch_key"] for r in records))
    wl_keys   = sorted(set(r["wl_key"]   for r in records))
    winner_mat = np.full((len(arch_keys), len(wl_keys)), -1, dtype=int)
    mode_idx   = {m: i for i, m in enumerate(MODE_ORDER)}

    for rec in records:
        i = arch_keys.index(rec["arch_key"])
        j = wl_keys.index(rec["wl_key"])
        winner_mat[i, j] = mode_idx.get(rec["winner"], len(MODE_ORDER))

    # Discrete colormap
    n_modes = len(MODE_ORDER)
    cmap    = plt.colormaps["tab10"].resampled(n_modes)
    img     = ax.imshow(winner_mat, cmap=cmap, vmin=-0.5, vmax=n_modes - 0.5,
                        aspect="auto", interpolation="nearest")

    ax.set_xticks(range(len(wl_keys)))
    ax.set_xticklabels([_shorten_wl(k) for k in wl_keys], fontsize=7)
    ax.set_yticks(range(len(arch_keys)))
    ax.set_yticklabels([_shorten_arch(k) for k in arch_keys], fontsize=7)
    ax.set_xlabel("Workload  (network/layer, timesteps T)", fontsize=9)
    ax.set_ylabel("Architecture config", fontsize=9)
    ax.set_title("Winning traffic mode per (arch, workload)", fontsize=10, fontweight="bold")

    # Annotate cells with mode abbreviation
    for i in range(len(arch_keys)):
        for j in range(len(wl_keys)):
            idx = winner_mat[i, j]
            if idx >= 0:
                label = MODE_ORDER[idx].split("_")[0]  # "both", "psum", "vmem", "base"
                ax.text(j, i, label, ha="center", va="center", fontsize=6,
                        color="white" if idx in (0, 1) else "black")

    # Legend
    handles = [plt.Rectangle((0, 0), 1, 1, color=cmap(i), label=MODE_LABELS[m])
               for i, m in enumerate(MODE_ORDER)]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1),
              fontsize=7, framealpha=0.9, title="Mode", title_fontsize=8)


# ── figure 2: score-gap strip ─────────────────────────────────────────────────

def fig_score_gap(records: list[dict], ax: plt.Axes) -> None:
    """Show how much headroom the winner has over the runner-up (normalised)."""
    by_winner: dict[str, list[float]] = {m: [] for m in MODE_ORDER}
    for rec in records:
        f = rec["feasible"]
        gap = (f[1]["score"] - f[0]["score"]) / max(f[1]["score"], 1e-12)
        by_winner[rec["winner"]].append(gap)

    xs, ys, cs, sizes = [], [], [], []
    positions = {m: i for i, m in enumerate(MODE_ORDER)}
    for m, gaps in by_winner.items():
        if not gaps:
            continue
        for g in gaps:
            xs.append(g * 100)   # percent
            ys.append(positions[m] + np.random.uniform(-0.2, 0.2))
            cs.append(MODE_COLOR[m])
            sizes.append(40)

    ax.scatter(xs, ys, c=cs, s=sizes, alpha=0.75, zorder=3)
    ax.set_yticks(range(len(MODE_ORDER)))
    ax.set_yticklabels([MODE_LABELS[m] for m in MODE_ORDER], fontsize=8)
    ax.set_xlabel("Score gap to runner-up  (%)", fontsize=9)
    ax.set_title("Winner margin over 2nd-best mode", fontsize=10, fontweight="bold")
    ax.axvline(0, color="grey", lw=0.8, ls="--")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="x", alpha=0.3)


# ── figure 3: normalised metric profiles ─────────────────────────────────────

def fig_metric_profiles(records: list[dict], ax: plt.Axes) -> None:
    """Mean normalised (delay, traffic, util) per mode across all pairs."""
    # For each pair, normalise each metric by its max across modes
    stats: dict[str, list[tuple[float, float, float]]] = {m: [] for m in MODE_ORDER}

    for rec in records:
        modes = {m["mode"]: m for m in rec["feasible"]}
        dl_vals  = [m["dl"]       for m in rec["feasible"]]
        tr_vals  = [m["tr_sum"]   for m in rec["feasible"]]
        ut_vals  = [m["util_sum"] for m in rec["feasible"]]
        dl_max   = max(dl_vals)  or 1
        tr_max   = max(tr_vals)  or 1
        ut_max   = max(ut_vals)  or 1

        for m_name, m in modes.items():
            if m_name in stats:
                stats[m_name].append((
                    m["dl"]       / dl_max,
                    m["tr_sum"]   / tr_max,
                    m["util_sum"] / ut_max,
                ))

    metrics = ["Delay\n(normalised)", "Traffic\n(normalised)", "Utilisation\n(normalised)"]
    n_metrics = len(metrics)
    n_modes   = len(MODE_ORDER)
    x = np.arange(n_metrics)
    bar_w = 0.8 / n_modes

    for i, mode in enumerate(MODE_ORDER):
        vals = stats[mode]
        if not vals:
            continue
        arr  = np.array(vals)
        mean = arr.mean(axis=0)
        std  = arr.std(axis=0)
        offset = (i - n_modes / 2 + 0.5) * bar_w
        bars = ax.bar(x + offset, mean, bar_w * 0.9, yerr=std,
                      color=MODE_COLOR[mode], alpha=0.85,
                      label=MODE_LABELS[mode], capsize=2, error_kw={"lw": 0.8})

    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=9)
    ax.set_ylabel("Normalised value  (1 = worst in pair)", fontsize=9)
    ax.set_title("Mean normalised metrics per mode\n(lower = better; error bars = ±1 std across pairs)",
                 fontsize=10, fontweight="bold")
    ax.legend(fontsize=6.5, ncol=2, loc="upper right", title="Mode", title_fontsize=8)
    ax.set_ylim(0, 1.25)
    ax.grid(axis="y", alpha=0.3)
    ax.axhline(1.0, color="grey", lw=0.8, ls="--", label="_nolegend_")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", default=str(METRICS_PATH))
    parser.add_argument("--out",     default=str(DEFAULT_OUT))
    args = parser.parse_args()

    records = load_records(Path(args.metrics))
    print(f"Loaded {len(records)} pairs with ≥2 feasible modes.")

    winner_counts = {}
    for rec in records:
        winner_counts[rec["winner"]] = winner_counts.get(rec["winner"], 0) + 1
    print("Winner distribution:")
    for m, c in sorted(winner_counts.items(), key=lambda x: -x[1]):
        print(f"  {m:25s}  {c:3d} pairs  ({100*c/len(records):.1f}%)")

    fig = plt.figure(figsize=(18, 14))
    gs  = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.55,
                           left=0.06, right=0.82, top=0.93, bottom=0.07)

    ax_heat  = fig.add_subplot(gs[0, :])
    ax_gap   = fig.add_subplot(gs[1, 0])
    ax_prof  = fig.add_subplot(gs[1, 1])

    fig_winner_heatmap(records, ax_heat)
    fig_score_gap(records, ax_gap)
    fig_metric_profiles(records, ax_prof)

    # Overall title
    w_u, w_tr, w_dl = W_U, W_TR, W_DL
    fig.suptitle(
        f"Best-schedule analysis  ·  weights: w_u={w_u:.4g}, w_tr={w_tr}, w_dl={w_dl}\n"
        f"({len(records)} arch×workload pairs, 8 TrafficModes each)",
        fontsize=11, y=0.98,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nFigure saved to {out}")
    plt.show()


if __name__ == "__main__":
    main()
