#!/usr/bin/env python3
"""
Analyze shallow_conv and deep_conv subset sweep results.

Parses all outputs/subset_sweep/{shallow,deep}_*.txt files and generates a
3-row × 2-col figure:

  Row 1  Phase diagrams (GB × nodes), colored by winning mode
         left = shallow_conv,  right = deep_conv

  Row 2  T-placement scatter (all configs) showing WHERE T is tiled
         + Spatial split heatmap (dims present in sp: per winning mode)

  Row 3  both_dram_oooo characterisation:
           rate heatmap per (T × nodes) for each workload
         + Weight footprint ratio vs GB size

Key naming note
---------------
"both_dram_oooo" means DRAM temporal = oooo (T NOT in DRAM loops).
BUT its gb: line always has T=2 — so the GB IS doing T tiling.
In this analysis we expose that as 't_placement = GB_ooot' (T alone in GB,
equivalent to the gb-level outer-T pattern the user calls "gb_ooot").

Usage (from project root):
    python scripts/analyze_shallow_sweep.py
    python scripts/analyze_shallow_sweep.py --out outputs/figures/sweep_analysis.pdf
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.parse_output import (  # noqa: E402
    classify_t_in_loop, extract_best_block, kb_str_to_int, parse_bytes_str,
)

SWEEP_DIR    = PROJECT_ROOT / "outputs" / "subset_sweep"
DEFAULT_OUT  = PROJECT_ROOT / "outputs" / "figures" / "sweep_analysis.pdf"

# ── constants ──────────────────────────────────────────────────────────────────

ALL_SP_DIMS = ["T", "COUT", "CIN", "HO", "WO", "KH", "KW"]

# Canonical mode order (best→worst typical)
MODES = [
    "both_gb_oooo",
    "both_dram_oooo",
    "psum_gb_ootk",
    "both_dram_ootk",
    "psum_boundary",
    "vmem_gb_xxxt",
    "vmem_dram_xxxt",
    "base",
]
MODE_COLORS = {
    "both_gb_oooo":    "#2196F3",   # blue
    "both_dram_oooo":  "#FF9800",   # orange
    "psum_gb_ootk":    "#4CAF50",   # green
    "both_dram_ootk":  "#F44336",   # red
    "psum_boundary":   "#9C27B0",   # purple
    "vmem_gb_xxxt":    "#E91E63",   # pink
    "vmem_dram_xxxt":  "#795548",   # brown
    "base":            "#9E9E9E",   # grey
}

# T-placement taxonomy (where T is tiled in the memory hierarchy)
T_PLACEMENTS = [
    "oooo (T→spatial)",   # T not in DRAM or GB → fully spatial
    "GB_ooot",            # T alone in GB   ← both_dram_oooo
    "GB_ootk",            # T first in GB, K-dim follows ← psum_gb_ootk
    "GB_xxxt",            # T outermost in GB ← vmem_gb_xxxt
    "DRAM_ootk",          # T middle in DRAM ← both_dram_ootk, psum_boundary
    "DRAM_xxxt",          # T outermost in DRAM ← vmem_dram_xxxt
]
TPLACE_COLORS = {
    "oooo (T→spatial)": "#2196F3",
    "GB_ooot":          "#FF9800",
    "GB_ootk":          "#4CAF50",
    "GB_xxxt":          "#E91E63",
    "DRAM_ootk":        "#F44336",
    "DRAM_xxxt":        "#795548",
}

T_MARKERS = {4: "o", 32: "s", 128: "^"}
T_LABELS  = {4: "T=4", 32: "T=32", 128: "T=128"}
RNG = np.random.default_rng(0)


# ── parsing ────────────────────────────────────────────────────────────────────

def parse_dim_line(text: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"([A-Z]+\d*)=(\d+)", text)}


def t_placement_label(dram_line: str, gb_line: str) -> str:
    """Combine DRAM and GB T-placement into one label."""
    dt = classify_t_in_loop(dram_line)
    gt = classify_t_in_loop(gb_line)
    if dt == "oooo" and gt == "oooo":
        return "oooo (T→spatial)"
    if dt == "oooo":
        return f"GB_{gt}"          # e.g. 'GB_ooot', 'GB_ootk', 'GB_xxxt'
    return f"DRAM_{dt}"            # e.g. 'DRAM_ootk', 'DRAM_xxxt'


def parse_util_cap(line: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in ("weight", "psum", "vmem"):
        m = re.search(rf"{key}=([\d.]+ (?:B|KB|MB|GB))/", line)
        if m:
            result[key] = parse_bytes_str(m.group(1))
    return result


def parse_file(path: Path) -> dict | None:
    m = re.match(
        r"(shallow|deep)_T(\d+)__nodes_(\d+)__gb_(\w+)__l1_(\w+)__pe_(\d+)__split_(\w+)",
        path.stem,
    )
    if not m:
        return None
    workload, T_val, nodes, gb_str, l1_str, pe, split = m.groups()

    text = path.read_text()
    best_mode, block = extract_best_block(text, text.splitlines())
    if not best_mode or not block:
        return None

    dram_line     = next((s for s in block if s.startswith("dram:")),     "")
    gb_line       = next((s for s in block if s.startswith("gb:")),       "")
    sp_line       = next((s for s in block if s.startswith("sp:")),       "")
    util_cap_line = next((s for s in block if s.startswith("util/cap:")), "")

    t_place  = t_placement_label(dram_line, gb_line)
    sp_dims  = parse_dim_line(sp_line.replace("sp:", "", 1))
    T_sp     = sp_dims.get("T", 0)
    T_total  = int(T_val)

    fp      = parse_util_cap(util_cap_line)
    total   = sum(fp.values())
    w_ratio = fp.get("weight", 0.0) / total if total > 0 else 0.0

    return {
        "workload":    workload,           # 'shallow' | 'deep'
        "T":           T_total,
        "nodes":       int(nodes),
        "gb_bytes":    kb_str_to_int(gb_str),
        "l1_bytes":    kb_str_to_int(l1_str),
        "pe":          int(pe),
        "split":       split,
        "best_mode":   best_mode,
        "t_placement": t_place,
        "sp_dims":     sp_dims,
        "T_sp":        T_sp,
        "T_sp_frac":   T_sp / T_total if T_total > 0 else 0.0,
        "w_ratio":     w_ratio,
    }


# ── figure helpers ─────────────────────────────────────────────────────────────

def _jitter(n: int, scale: float = 0.15) -> np.ndarray:
    return RNG.uniform(-scale, scale, n)


def _phase_scatter(ax: plt.Axes, records: list[dict], title: str) -> None:
    """Scatter log2(gb_kb) vs log2(nodes), colored by best_mode, shaped by T."""
    by_mode: dict[str, dict] = defaultdict(lambda: {"x": [], "y": [], "T": []})
    for r in records:
        mode = r["best_mode"] if r["best_mode"] in MODE_COLORS else "base"
        by_mode[mode]["x"].append(np.log2(r["gb_bytes"] / 1024))
        by_mode[mode]["y"].append(np.log2(r["nodes"]))
        by_mode[mode]["T"].append(r["T"])

    for mode in MODES:
        data = by_mode.get(mode)
        if not data or not data["x"]:
            continue
        xs   = np.array(data["x"])
        ys   = np.array(data["y"])
        Ts   = np.array(data["T"])
        col  = MODE_COLORS.get(mode, "#9E9E9E")
        for T_val, marker in T_MARKERS.items():
            mask = Ts == T_val
            if not mask.any():
                continue
            ax.scatter(xs[mask] + _jitter(mask.sum()),
                       ys[mask] + _jitter(mask.sum()),
                       c=col, marker=marker, s=20, alpha=0.4,
                       linewidths=0, zorder=2)

    present = [m for m in MODES if any(r["best_mode"] == m for r in records)]
    mode_h = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=MODE_COLORS[m], markersize=8, label=m)
               for m in present]
    T_h    = [plt.Line2D([0], [0], marker=mk, color="#555", markersize=7,
                          linestyle="None", label=T_LABELS[t])
               for t, mk in T_MARKERS.items()]
    ax.legend(handles=mode_h + T_h, fontsize=6, loc="upper left",
              framealpha=0.88, title="mode / shape", title_fontsize=6)

    gb_ticks = [6, 7, 8, 9, 10, 11, 12]
    ax.set_xticks(gb_ticks)
    ax.set_xticklabels([f"{2**x}KB" for x in gb_ticks], fontsize=7, rotation=30)
    node_ticks = [4, 5, 6, 7, 8, 9, 10]
    ax.set_yticks(node_ticks)
    ax.set_yticklabels([str(2**y) for y in node_ticks], fontsize=7)
    ax.set_xlabel("GB size  (log₂)", fontsize=9)
    ax.set_ylabel("Nodes  (log₂)", fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.grid(alpha=0.2)


def _t_placement_scatter(ax: plt.Axes, records: list[dict]) -> None:
    """Scatter log2(gb_kb) vs log2(nodes), colored by t_placement label."""
    by_cat: dict[str, dict] = defaultdict(lambda: {"x": [], "y": [], "T": []})
    for r in records:
        cat = r["t_placement"]
        by_cat[cat]["x"].append(np.log2(r["gb_bytes"] / 1024))
        by_cat[cat]["y"].append(np.log2(r["nodes"]))
        by_cat[cat]["T"].append(r["T"])

    for cat in T_PLACEMENTS:
        data = by_cat.get(cat)
        if not data or not data["x"]:
            continue
        xs  = np.array(data["x"])
        ys  = np.array(data["y"])
        Ts  = np.array(data["T"])
        col = TPLACE_COLORS.get(cat, "#9E9E9E")
        for T_val, marker in T_MARKERS.items():
            mask = Ts == T_val
            if not mask.any():
                continue
            ax.scatter(xs[mask] + _jitter(mask.sum()),
                       ys[mask] + _jitter(mask.sum()),
                       c=col, marker=marker, s=20, alpha=0.4,
                       linewidths=0, zorder=2)

    present = [c for c in T_PLACEMENTS if c in by_cat and by_cat[c]["x"]]
    cat_h = [plt.Line2D([0], [0], marker="o", color="w",
                         markerfacecolor=TPLACE_COLORS.get(c, "#9E9E9E"),
                         markersize=8, label=c)
              for c in present]
    T_h   = [plt.Line2D([0], [0], marker=mk, color="#555", markersize=7,
                         linestyle="None", label=T_LABELS[t])
              for t, mk in T_MARKERS.items()]
    ax.legend(handles=cat_h + T_h, fontsize=6, loc="upper left",
              framealpha=0.88, title="T-placement / shape", title_fontsize=6)

    gb_ticks = [6, 7, 8, 9, 10, 11, 12]
    ax.set_xticks(gb_ticks)
    ax.set_xticklabels([f"{2**x}KB" for x in gb_ticks], fontsize=7, rotation=30)
    node_ticks = [4, 5, 6, 7, 8, 9, 10]
    ax.set_yticks(node_ticks)
    ax.set_yticklabels([str(2**y) for y in node_ticks], fontsize=7)
    ax.set_xlabel("GB size  (log₂)", fontsize=9)
    ax.set_ylabel("Nodes  (log₂)", fontsize=9)
    ax.set_title("② Integrate temporal  (where is T tiled?)\nboth_dram_oooo ≡ GB_ooot",
                 fontsize=10, fontweight="bold")
    ax.grid(alpha=0.2)


def _spatial_heatmap(ax: plt.Axes, records: list[dict]) -> None:
    """Heatmap rows=top modes, cols=sp: dims, value=fraction having that dim."""
    top_modes = [m for m in MODES if any(r["best_mode"] == m for r in records)]

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for r in records:
        mode = r["best_mode"]
        if mode not in top_modes:
            continue
        totals[mode] += 1
        for dim in r["sp_dims"]:
            if dim in ALL_SP_DIMS:
                counts[mode][dim] += 1

    data = np.zeros((len(top_modes), len(ALL_SP_DIMS)))
    for i, mode in enumerate(top_modes):
        for j, dim in enumerate(ALL_SP_DIMS):
            data[i, j] = counts[mode][dim] / totals[mode] if totals[mode] else 0.0

    im = ax.imshow(data, vmin=0, vmax=1, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(ALL_SP_DIMS)))
    ax.set_xticklabels(ALL_SP_DIMS, fontsize=9)
    ax.set_yticks(range(len(top_modes)))
    ax.set_yticklabels(
        [f"{m}\n(n={totals[m]})" for m in top_modes], fontsize=7
    )
    ax.set_title("③ Spatial split  (fraction of configs\nwith dimension in sp:)",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Dimension in sp:", fontsize=9)
    for i in range(len(top_modes)):
        for j in range(len(ALL_SP_DIMS)):
            v = data[i, j]
            if totals[top_modes[i]] > 0:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if v > 0.6 else "black")
    plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02, label="Fraction")


def _dram_oooo_heatmap(ax: plt.Axes, records: list[dict]) -> None:
    """
    Heatmap: rate of both_dram_oooo (= GB_ooot) selection per (T, nodes).
    Two sub-blocks side by side: shallow | deep.
    """
    T_vals    = sorted({r["T"]     for r in records})
    node_vals = sorted({r["nodes"] for r in records})
    workloads = ["shallow", "deep"]

    n_T = len(T_vals)
    n_N = len(node_vals)
    n_W = len(workloads)

    # Build rate matrix: shape (n_T, n_N * n_W + gap)
    gap = 1
    mat_w = n_N * n_W + gap * (n_W - 1)
    mat = np.full((n_T, mat_w), np.nan)

    col_labels: list[str] = []
    col_offset = 0
    for wi, wl in enumerate(workloads):
        sub = [r for r in records if r["workload"] == wl]
        for ni, nv in enumerate(node_vals):
            col = col_offset + ni
            for ti, tv in enumerate(T_vals):
                grp = [r for r in sub if r["T"] == tv and r["nodes"] == nv]
                if grp:
                    mat[ti, col] = sum(1 for r in grp if r["best_mode"] == "both_dram_oooo") / len(grp)
            col_labels.append(f"{nv}")
        col_offset += n_N + gap
        if wi < n_W - 1:
            col_labels.append("")   # gap column

    im = ax.imshow(mat, vmin=0, vmax=0.5, cmap="Oranges", aspect="auto")
    ax.set_xticks(range(mat_w))
    ax.set_xticklabels(col_labels, fontsize=7, rotation=45, ha="right")
    ax.set_yticks(range(n_T))
    ax.set_yticklabels([f"T={tv}" for tv in T_vals], fontsize=8)
    ax.set_title("⑤ both_dram_oooo (= GB_ooot) selection rate\nper T × nodes  |  left=shallow, right=deep",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Nodes  (left block = shallow, right block = deep)", fontsize=8)

    # Annotate non-nan cells
    for ti in range(n_T):
        for ci in range(mat_w):
            v = mat[ti, ci]
            if not np.isnan(v):
                ax.text(ci, ti, f"{v:.2f}", ha="center", va="center", fontsize=6,
                        color="white" if v > 0.3 else "black")

    # Draw separator line between shallow and deep blocks
    sep = n_N - 0.5
    ax.axvline(sep, color="white", lw=2, zorder=5)
    ax.text(n_N / 2 - 0.5, -0.7, "shallow", ha="center", va="top",
            fontsize=8, color="#555", transform=ax.transData)
    ax.text(n_N + gap + n_N / 2 - 0.5, -0.7, "deep", ha="center", va="top",
            fontsize=8, color="#555", transform=ax.transData)

    plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02, label="Selection rate")


def _weight_ratio_scatter(ax: plt.Axes, records: list[dict]) -> None:
    """Scatter log2(gb_kb) vs weight-ratio%, per mode, shaped by workload."""
    wl_markers = {"shallow": "o", "deep": "s"}
    for mode in MODES:
        col = MODE_COLORS.get(mode, "#9E9E9E")
        sub = [r for r in records if r["best_mode"] == mode]
        if not sub:
            continue
        for wl, marker in wl_markers.items():
            pts = [r for r in sub if r["workload"] == wl]
            if not pts:
                continue
            xs = np.array([np.log2(r["gb_bytes"] / 1024) for r in pts])
            ys = np.array([r["w_ratio"] * 100 for r in pts])
            ax.scatter(xs + _jitter(len(xs), 0.08),
                       ys + _jitter(len(ys), 0.5),
                       c=col, marker=marker, s=18, alpha=0.35,
                       linewidths=0, zorder=2)

    present = [m for m in MODES if any(r["best_mode"] == m for r in records)]
    mode_h = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=MODE_COLORS[m], markersize=8, label=m)
               for m in present]
    wl_h   = [plt.Line2D([0], [0], marker=mk, color="#555", markersize=7,
                          linestyle="None", label=wl)
               for wl, mk in wl_markers.items()]
    ax.legend(handles=mode_h + wl_h, fontsize=6, loc="upper right",
              framealpha=0.88, title="mode / shape", title_fontsize=6)

    gb_ticks = [6, 7, 8, 9, 10, 11, 12]
    ax.set_xticks(gb_ticks)
    ax.set_xticklabels([f"{2**x}KB" for x in gb_ticks], fontsize=7, rotation=30)
    ax.set_xlabel("GB size  (log₂)", fontsize=9)
    ax.set_ylabel("Weight / total GB footprint  (%)", fontsize=9)
    ax.set_title("④ Weight footprint ratio\nvs. GB size", fontsize=10, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(alpha=0.2)


# ── main ──────────────────────────────────────────────────────────────────────

def _print_summary(records: list[dict]) -> None:
    total = len(records)
    for wl in ("shallow", "deep"):
        sub = [r for r in records if r["workload"] == wl]
        print(f"\n{'─'*50}")
        print(f"  {wl}_conv  ({len(sub)} configs)")
        print(f"{'─'*50}")
        mc = Counter(r["best_mode"] for r in sub)
        for m, c in mc.most_common():
            print(f"  {m:30s}  {c:5d}  ({100*c/len(sub):.1f}%)")
        tc = Counter(r["t_placement"] for r in sub)
        print("  T-placement:")
        for t, c in tc.most_common():
            print(f"    {t:30s}  {c:5d}  ({100*c/len(sub):.1f}%)")

    # dram_oooo common features
    dram_oooo = [r for r in records if r["best_mode"] == "both_dram_oooo"]
    if dram_oooo:
        print(f"\n{'─'*50}")
        print(f"  both_dram_oooo (≡ GB_ooot)  — {len(dram_oooo)} total")
        print(f"{'─'*50}")
        n = len(dram_oooo)
        for key, label, vals in [
            ("workload", "workload", ["shallow", "deep"]),
            ("T",        "T",        [4, 32, 128]),
        ]:
            rates = {v: sum(1 for r in dram_oooo if r[key] == v) / n for v in vals}
            print(f"  {label}:  " + "  ".join(f"{v}→{100*r:.0f}%" for v, r in rates.items()))
        for key, label, sort_fn in [
            ("nodes",    "nodes", int),
            ("gb_bytes", "gb",    int),
            ("pe",       "pe",    int),
            ("split",    "split", str),
        ]:
            vals = sorted({r[key] for r in records}, key=sort_fn)
            all_counts = Counter(r[key] for r in records)
            dram_counts = Counter(r[key] for r in dram_oooo)
            rates = {v: dram_counts[v] / all_counts[v] for v in vals if all_counts[v]}
            top = sorted(rates.items(), key=lambda x: -x[1])
            desc = "  ".join(f"{v}→{100*r:.0f}%" for v, r in top[:4])
            print(f"  {label} rate:  {desc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default=str(SWEEP_DIR))
    parser.add_argument("--out",       default=str(DEFAULT_OUT))
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    files = sorted(sweep_dir.glob("*.txt"))
    print(f"Found {len(files)} files … ", end="", flush=True)

    records, failed = [], 0
    for f in files:
        r = parse_file(f)
        if r:
            records.append(r)
        else:
            failed += 1
    print(f"parsed {len(records)}, failed {failed}")

    _print_summary(records)

    # ── figure layout (3 rows × 2 cols) ────────────────────────────────────────
    fig = plt.figure(figsize=(15, 17))
    gs  = fig.add_gridspec(3, 2, hspace=0.45, wspace=0.38,
                           left=0.07, right=0.97, top=0.95, bottom=0.05)

    ax11 = fig.add_subplot(gs[0, 0])
    ax12 = fig.add_subplot(gs[0, 1])
    ax21 = fig.add_subplot(gs[1, 0])
    ax22 = fig.add_subplot(gs[1, 1])
    ax31 = fig.add_subplot(gs[2, 0])
    ax32 = fig.add_subplot(gs[2, 1])

    _phase_scatter(ax11, [r for r in records if r["workload"] == "shallow"],
                   "① Phase diagram — shallow_conv\n(winning mode per GB × nodes)")
    _phase_scatter(ax12, [r for r in records if r["workload"] == "deep"],
                   "① Phase diagram — deep_conv\n(winning mode per GB × nodes)")
    _t_placement_scatter(ax21, records)
    _spatial_heatmap(ax22, records)
    _dram_oooo_heatmap(ax31, records)
    _weight_ratio_scatter(ax32, records)

    n_shallow = sum(1 for r in records if r["workload"] == "shallow")
    n_deep    = sum(1 for r in records if r["workload"] == "deep")
    fig.suptitle(
        f"Sweep analysis  ·  {len(records)} configs  "
        f"(shallow={n_shallow}, deep={n_deep})\n"
        "Scatter axes: x = log₂(GB size), y = log₂(nodes)   "
        "Note: both_dram_oooo ≡ GB_ooot (T tiled alone at GB level)",
        fontsize=11,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nFigure saved → {out}")
    plt.show()


if __name__ == "__main__":
    main()
