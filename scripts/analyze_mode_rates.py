#!/usr/bin/env python3
"""
analyze_mode_rates.py

For each hardware parameter value (and key pairs), compute the fraction of configs
choosing each mode — the inverse of within-mode distributions.

Outputs
  outputs/mode_rate_tables.md             — markdown rate tables (both workloads)
  outputs/figures/mode_rate_heatmaps.pdf  — 2-D heatmap panels (both workloads)

Bold rule in the markdown: a cell is **bold** when its rate exceeds the mode's
overall rate by >5 percentage points AND >3 % absolute.

Heatmap border rule: thick border on cells where rate > 1.5 × overall.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.parse_output import (  # noqa: E402
    classify_t_in_loop, extract_best_block, kb_str_to_int, sp_dims,
)

SWEEP_DIR    = PROJECT_ROOT / "outputs" / "subset_sweep"
MD_OUT       = PROJECT_ROOT / "outputs" / "mode_rate_tables.md"
FIG_OUT      = PROJECT_ROOT / "outputs" / "figures" / "mode_rate_heatmaps.pdf"

# ── parse ──────────────────────────────────────────────────────────────────────

def t_place(dram_t: str, gb_t: str) -> str:
    if dram_t == "oooo" and gb_t == "oooo":
        return "T→spatial"
    if dram_t == "oooo":
        return f"GB\\_{gb_t}"
    return f"DRAM\\_{dram_t}"

def parse_file(path: Path) -> dict | None:
    m = re.match(
        r"(shallow|deep)_T(\d+)__nodes_(\d+)__gb_(\w+)__l1_(\w+)__pe_(\d+)__split_(\w+)",
        path.stem,
    )
    if not m:
        return None
    workload, T, nodes, gb, l1, pe, split = m.groups()
    text = path.read_text()
    best, block = extract_best_block(text, text.splitlines())
    if not best:
        return None

    dram_l = next((s for s in block if s.startswith("dram:")), "")
    gb_l   = next((s for s in block if s.startswith("gb:")),   "")
    sp_l   = next((s for s in block if s.startswith("sp:")),   "")

    return {
        "workload":   workload,
        "T":          int(T),
        "nodes":      int(nodes),
        "gb_bytes":   kb_str_to_int(gb),
        "l1_bytes":   kb_str_to_int(l1),
        "pe":         int(pe),
        "split":      split,
        "best":       best,
        "dram_t":     classify_t_in_loop(dram_l),
        "gb_t":       classify_t_in_loop(gb_l),
        "dram_body":  re.sub(r"^\s*dram:\s*", "", dram_l).strip() if dram_l else "none",
        "gb_body":    re.sub(r"^\s*gb:\s*",   "", gb_l).strip()   if gb_l   else "none",
        "sp_pattern": sp_dims(sp_l),
    }

# ── constants ──────────────────────────────────────────────────────────────────

BUCKETS = ["both_gb_oooo", "both_dram_oooo", "both_dram_ootk", "psum_gb_ootk", "others"]

def bucket(mode: str) -> str:
    return mode if mode in BUCKETS[:-1] else "others"

def bstr(b: int) -> str:
    if b >= 2**20: return f"{b >> 20}MB"
    if b >= 1024:  return f"{b >> 10}KB"
    return f"{b}B"

ALL_PARAMS = ["T", "nodes", "gb_bytes", "l1_bytes", "pe", "split"]

PARAM_LABEL = {
    "T":        "T (timesteps)",
    "nodes":    "nodes",
    "gb_bytes": "GB size",
    "l1_bytes": "L1 size",
    "pe":       "PEs/node",
    "split":    "mem split",
}

def pval(param: str, v) -> str:
    if param in ("gb_bytes", "l1_bytes"): return bstr(v)
    if param == "T":     return f"T={v}"
    if param == "nodes": return f"N={v}"
    if param == "pe":    return f"PE={v}"
    return str(v)

def param_vals(records: list[dict], param: str) -> list:
    return sorted({r[param] for r in records},
                  key=lambda x: x if isinstance(x, (int, float)) else x)

# ── rate helpers ───────────────────────────────────────────────────────────────

def rates_1d(records: list[dict], param: str) -> tuple[list, dict]:
    """Returns (values, {value: {mode: rate}})."""
    vals = param_vals(records, param)
    out  = {}
    for v in vals:
        sub = [r for r in records if r[param] == v]
        n   = len(sub)
        mc  = Counter(bucket(r["best"]) for r in sub)
        out[v] = {m: mc[m] / n for m in BUCKETS}
    return vals, out

def rates_2d(records: list[dict], pa: str, pb: str, mode: str
             ) -> tuple[list, list, np.ndarray]:
    """Returns (vals_a, vals_b, matrix[len_a × len_b]) of mode rate per cell."""
    va = param_vals(records, pa)
    vb = param_vals(records, pb)
    mat = np.full((len(va), len(vb)), np.nan)
    for i, a in enumerate(va):
        for j, b in enumerate(vb):
            sub = [r for r in records if r[pa] == a and r[pb] == b]
            if sub:
                mat[i, j] = sum(1 for r in sub if bucket(r["best"]) == mode) / len(sub)
    return va, vb, mat

def overall_rates(records: list[dict]) -> dict[str, float]:
    n  = len(records)
    mc = Counter(bucket(r["best"]) for r in records)
    return {m: mc[m] / n for m in BUCKETS}

# ── markdown output ────────────────────────────────────────────────────────────

def md_overall_table(deep: list[dict], shallow: list[dict]) -> str:
    all_r  = deep + shallow
    n_all, n_d, n_s = len(all_r), len(deep), len(shallow)
    ov_all = overall_rates(all_r)
    ov_d   = overall_rates(deep)
    ov_s   = overall_rates(shallow)
    active = [m for m in BUCKETS if max(ov_all[m], ov_d[m], ov_s[m]) > 0]

    lines = [
        "## Overall Mode Distribution\n",
        f"| Mode | All ({n_all}) | deep\\_conv ({n_d}) | shallow\\_conv ({n_s}) |",
        "|:-----|-----:|-----:|-----:|",
    ]
    for m in active:
        lines.append(
            f"| `{m}` | {100*ov_all[m]:.1f}% "
            f"| {100*ov_d[m]:.1f}% "
            f"| {100*ov_s[m]:.1f}% |"
        )
    lines.append("")
    return "\n".join(lines)


def _top_body(bodies: list[str]) -> str:
    """Return 'most-common-example (pct%)'; shows 'none' if that is most common."""
    ctr = Counter(bodies)
    top, cnt = ctr.most_common(1)[0]
    pct = 100 * cnt / len(bodies)
    s   = top if len(top) <= 30 else top[:27] + "…"
    return f"`{s}`" + (f" ({pct:.0f}%)" if pct < 95 else "")


def md_tiling_analysis(records: list[dict], heading: str) -> str:
    active = [m for m in BUCKETS if sum(1 for r in records if bucket(r["best"]) == m) > 0]

    lines = [f"## Temporal Tiling Similarity — {heading}\n"]
    lines.append(
        "> T-classification per memory level: "
        "`oooo` = T not tiled (T→spatial);  "
        "`ooot` = T alone;  "
        "`ootk` = T co-tiled with K dim;  "
        "`xxxt` = T outermost.\n"
    )

    # ── per-mode T-placement table ─────────────────────────────────────────────
    lines.append("### T-placement per mode\n")
    lines.append("| Mode | N | DRAM | GB | Typical DRAM body | Typical GB body |")
    lines.append("|:-----|--:|:----:|:--:|:------------------|:----------------|")

    mode_domtile: dict[str, tuple[str, str]] = {}
    for m in active:
        grp = [r for r in records if bucket(r["best"]) == m]
        n   = len(grp)

        dram_ctr = Counter(r["dram_t"] for r in grp)
        gb_ctr   = Counter(r["gb_t"]   for r in grp)
        top_dt   = dram_ctr.most_common(1)[0]
        top_gt   = gb_ctr.most_common(1)[0]

        def fmt_pat(top, ctr, total):
            s = top[0]
            if len(ctr) > 1:
                s += f" ({100*top[1]/total:.0f}%)"
            return s

        dram_str = fmt_pat(top_dt, dram_ctr, n)
        gb_str   = fmt_pat(top_gt, gb_ctr, n)

        dram_ex = _top_body([r["dram_body"] for r in grp])
        gb_ex   = _top_body([r["gb_body"]   for r in grp])

        lines.append(f"| `{m}` | {n} | {dram_str} | {gb_str} | {dram_ex} | {gb_ex} |")
        mode_domtile[m] = (top_dt[0], top_gt[0])

    lines.append("")

    # ── taxonomy grid ──────────────────────────────────────────────────────────
    lines.append("### T-placement taxonomy (similarity structure)\n")
    lines.append(
        "Modes are arranged by *which memory level* tiles T, revealing which modes "
        "are structurally similar to each other.\n"
    )
    lines.append("| | **T not in GB** | **T in GB (ooot, alone)** | **T in GB (ootk, with K)** |")
    lines.append("|:---|:---:|:---:|:---:|")

    no_dram: dict[str, list[str]] = {"not_gb": [], "ooot": [], "ootk": []}
    yes_dram: dict[str, list[str]] = {"not_gb": [], "ooot": [], "ootk": []}

    for m in active:
        if m == "others":
            continue
        dt, gt = mode_domtile.get(m, ("oooo", "oooo"))
        cell   = f"`{m}`"
        bucket_row = yes_dram if dt != "oooo" else no_dram
        col = "not_gb" if gt == "oooo" else ("ooot" if gt == "ooot" else "ootk")
        bucket_row[col].append(cell)

    def cell(lst): return " ".join(lst) if lst else "—"

    lines.append(
        f"| **T not in DRAM** | {cell(no_dram['not_gb'])} "
        f"| {cell(no_dram['ooot'])} | {cell(no_dram['ootk'])} |"
    )
    lines.append(
        f"| **T in DRAM** | {cell(yes_dram['not_gb'])} "
        f"| {cell(yes_dram['ooot'])} | {cell(yes_dram['ootk'])} |"
    )
    lines.append("")
    return "\n".join(lines)


def md_section(records: list[dict], heading: str) -> str:
    n       = len(records)
    overall = overall_rates(records)
    active  = [m for m in BUCKETS if overall[m] > 0]

    lines: list[str] = []
    lines.append(f"## {heading}  ({n} configs)\n")

    overall_parts = [f"`{m}` = {100*overall[m]:.1f}%" for m in active]
    lines.append("**Overall rates**: " + " &nbsp;·&nbsp; ".join(overall_parts) + "\n")
    lines.append("> **Bold** = rate > 5 pp above that mode's overall average (and > 3 %).\n")

    for param in ALL_PARAMS:
        vals, row_rates = rates_1d(records, param)
        lines.append(f"### {PARAM_LABEL[param]}\n")

        header = "| Value | " + " | ".join(m.replace("_", "\\_") for m in active) + " |"
        sep    = "|:------|" + "|".join("------:" for _ in active) + "|"
        lines.append(header)
        lines.append(sep)

        for v in vals:
            cells = []
            for m in active:
                r   = row_rates[v][m]
                pct = f"{100*r:.0f}%"
                if r - overall[m] > 0.05 and r > 0.03:
                    pct = f"**{pct}**"
                cells.append(pct)
            lines.append(f"| {pval(param, v)} | " + " | ".join(cells) + " |")
        lines.append("")

    return "\n".join(lines)

# ── heatmap helpers ────────────────────────────────────────────────────────────

MODE_CMAP = {
    "both_dram_oooo": "Oranges",
    "both_dram_ootk": "Reds",
    "psum_gb_ootk":   "Greens",
    "both_gb_oooo":   "Blues",
}

def heatmap(ax: plt.Axes, records: list[dict],
            pa: str, pb: str, mode: str,
            title: str, vmax: float | None = None) -> None:
    va, vb, mat = rates_2d(records, pa, pb, mode)
    ov = overall_rates(records)[mode]

    vm  = vmax if vmax else max(float(np.nanmax(mat)), ov * 2, 0.10)
    im  = ax.imshow(mat, cmap=MODE_CMAP.get(mode, "Blues"),
                    vmin=0, vmax=vm, aspect="auto")

    ax.set_xticks(range(len(vb)))
    ax.set_xticklabels([pval(pb, v) for v in vb], fontsize=7, rotation=40, ha="right")
    ax.set_yticks(range(len(va)))
    ax.set_yticklabels([pval(pa, v) for v in va], fontsize=7)
    ax.set_xlabel(PARAM_LABEL[pb], fontsize=8)
    ax.set_ylabel(PARAM_LABEL[pa], fontsize=8)
    ax.set_title(title, fontsize=9, fontweight="bold")

    for i in range(len(va)):
        for j in range(len(vb)):
            v = mat[i, j]
            if not np.isnan(v):
                col = "white" if v > vm * 0.6 else "black"
                ax.text(j, i, f"{100*v:.0f}%", ha="center", va="center",
                        fontsize=6.5, color=col)
                if v > 1.5 * ov:
                    ax.add_patch(plt.Rectangle(
                        (j - 0.5, i - 0.5), 1, 1,
                        fill=False, edgecolor="black", lw=2, zorder=4,
                    ))

    plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02,
                 label=f"rate  (avg={100*ov:.1f}%)")

# ── figure builders ────────────────────────────────────────────────────────────

def fig_deep(records: list[dict]) -> plt.Figure:
    fig, axes = plt.subplots(3, 2, figsize=(13, 15))
    fig.suptitle(
        "deep_conv — mode selection rate per hardware parameter pair\n"
        "(thick border = cell rate > 1.5 × mode average)",
        fontsize=11,
    )
    # Row 1: both_dram_oooo — driven by small T / small nodes / large GB
    heatmap(axes[0, 0], records, "T", "nodes",    "both_dram_oooo",
            "both_dram_oooo: T × nodes")
    heatmap(axes[0, 1], records, "T", "gb_bytes", "both_dram_oooo",
            "both_dram_oooo: T × GB size")

    # Row 2: both_dram_ootk — driven sharply by L1=4KB + w30 split
    heatmap(axes[1, 0], records, "T",        "l1_bytes", "both_dram_ootk",
            "both_dram_ootk: T × L1 size")
    heatmap(axes[1, 1], records, "l1_bytes", "split",    "both_dram_ootk",
            "both_dram_ootk: L1 size × mem split")

    # Row 3: psum_gb_ootk — driven by large nodes + large GB
    heatmap(axes[2, 0], records, "nodes", "gb_bytes", "psum_gb_ootk",
            "psum_gb_ootk: nodes × GB size")
    heatmap(axes[2, 1], records, "T",     "nodes",    "psum_gb_ootk",
            "psum_gb_ootk: T × nodes")

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def fig_shallow(records: list[dict]) -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        "shallow_conv — both_dram_oooo selection rate per hardware parameter pair\n"
        "(only non-trivial mode; thick border = rate > 1.5 × avg 1.7%)",
        fontsize=11,
    )
    heatmap(axes[0], records, "T", "nodes",    "both_dram_oooo",
            "both_dram_oooo: T × nodes")
    heatmap(axes[1], records, "T", "gb_bytes", "both_dram_oooo",
            "both_dram_oooo: T × GB size")
    heatmap(axes[2], records, "nodes", "gb_bytes", "both_dram_oooo",
            "both_dram_oooo: nodes × GB size")

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    return fig

MODE_COLOR = {
    "both_gb_oooo":   "#4c78a8",
    "both_dram_oooo": "#f58518",
    "both_dram_ootk": "#e45756",
    "psum_gb_ootk":   "#54a24b",
    "others":         "#aaaaaa",
}

def fig_sp_pie(records: list[dict], workload_label: str) -> plt.Figure:
    """One pie chart per mode showing sp: dimension-pattern distribution."""
    main_modes = [m for m in BUCKETS[:-1]
                  if sum(1 for r in records if bucket(r["best"]) == m) > 0]

    ncols = 2
    nrows = (len(main_modes) + 1) // 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 5.5 * nrows))
    axes_flat  = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for idx, m in enumerate(main_modes):
        ax  = axes_flat[idx]
        grp = [r for r in records if bucket(r["best"]) == m]
        ctr = Counter(r["sp_pattern"] for r in grp)
        n   = len(grp)

        top       = ctr.most_common(8)
        other_cnt = sum(c for _, c in ctr.most_common()[8:])
        labels    = [t[0] for t in top]
        sizes     = [t[1] for t in top]
        if other_cnt > 0:
            labels.append("other")
            sizes.append(other_cnt)

        # Build colors: cycle through tab20 but keep dim palette consistent
        cmap   = plt.colormaps["tab20"].resampled(len(labels))
        colors = [cmap(i) for i in range(len(labels))]

        wedges, _, autotexts = ax.pie(
            sizes,
            autopct=lambda p: f"{p:.0f}%" if p >= 3 else "",
            startangle=90,
            colors=colors,
            wedgeprops={"edgecolor": "white", "linewidth": 0.8},
        )
        for at in autotexts:
            at.set_fontsize(7)

        # Legend below the pie
        legend_labels = [
            f"{lab}  ({100*sz/n:.0f}%)" for lab, sz in zip(labels, sizes)
        ]
        ax.legend(
            wedges, legend_labels,
            loc="lower center", bbox_to_anchor=(0.5, -0.30),
            fontsize=7, ncol=2, framealpha=0.7,
        )
        ax.set_title(
            f"{m}  (n={n})",
            fontsize=9, fontweight="bold",
            color=MODE_COLOR.get(m, "black"),
        )

    # Hide any unused subplot
    for idx in range(len(main_modes), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle(
        f"{workload_label} — spatial split (sp:) dimension patterns per mode\n"
        "Pattern = sorted dimension names in the winning sp: line",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    return fig


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    files   = sorted(SWEEP_DIR.glob("*.txt"))
    records = [r for f in files if (r := parse_file(f)) is not None]
    shallow = [r for r in records if r["workload"] == "shallow"]
    deep    = [r for r in records if r["workload"] == "deep"]
    print(f"Loaded {len(records)} total  (shallow={len(shallow)}, deep={len(deep)})")

    # ── markdown ────────────────────────────────────────────────────────────────
    md = "\n".join([
        "# Mode Selection Rate Analysis\n",
        md_overall_table(deep, shallow),
        "\n---\n",
        md_tiling_analysis(deep,    "deep\\_conv"),
        "\n---\n",
        md_tiling_analysis(shallow, "shallow\\_conv"),
        "\n---\n",
        "# Per-Parameter Rate Tables\n",
        "For each parameter value: fraction of configs choosing each mode.",
        "**Bold** = rate > 5 pp above that mode's overall average (and > 3 %).",
        "Tells you which hardware knob values push configs away from `both_gb_oooo`.\n",
        "---\n",
        md_section(deep,    "deep\\_conv"),
        "\n---\n",
        md_section(shallow, "shallow\\_conv"),
    ])
    MD_OUT.write_text(md)
    print(f"Markdown → {MD_OUT}")

    # ── figures ─────────────────────────────────────────────────────────────────
    FIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(FIG_OUT) as pdf:
        for fig_fn, records, label in [
            (fig_deep,    deep,    "deep_conv"),
            (fig_shallow, shallow, "shallow_conv"),
        ]:
            f = fig_fn(records)
            pdf.savefig(f, bbox_inches="tight")
            plt.close(f)

        for records, label in [(deep, "deep_conv"), (shallow, "shallow_conv")]:
            f = fig_sp_pie(records, label)
            pdf.savefig(f, bbox_inches="tight")
            plt.close(f)

    print(f"Figures  → {FIG_OUT}")


if __name__ == "__main__":
    main()
