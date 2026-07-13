#!/usr/bin/env python3
"""
analyze_profiling_sweep.py

Analyse outputs/profiling_sweep/*.txt — the fixed-arch workload profiling run.

Fixed arch: nodes=256, L1=8KB, L2=256KB, PE=64, split=w30v1p1
Workload axes swept: (CIN, COUT, HO, WO, KH, KW, T)

Outputs:
  outputs/profiling_sweep/mode_rate_tables.md     — markdown rate tables
  outputs/profiling_sweep/figures/sp_pie.pdf      — spatial-split pie charts per mode

Bold rule in the markdown: a cell is **bold** when its rate exceeds the mode's
overall rate by >5 pp AND >3 % absolute.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.parse_output import (  # noqa: E402
    classify_t_in_loop, extract_best_block, parse_bytes_str,
    parse_traffic_per_var, sp_dims,
)

SWEEP_DIR    = PROJECT_ROOT / "outputs" / "profiling_sweep"
MD_OUT       = SWEEP_DIR / "mode_rate_tables.md"
FIG_OUT      = SWEEP_DIR / "figures" / "sp_pie.pdf"

# ---------------------------------------------------------------------------
# Mode definitions (matching enumerator output)
# ---------------------------------------------------------------------------

BUCKETS = [
    # GB-side (psum+vmem traffic zeroed at GB boundary)
    "gb_oooo", "gb_ooot", "gb_oook", "gb_ootk",
    # DRAM-side (psum+vmem traffic counted only inside GB)
    "dram_oooo", "dram_ooot", "dram_oook",
    # PSUM reuse modes
    "psum_gb_otok", "psum_dram_ootk", "psum_dram_otok",
    # VMEM streaming modes
    "vmem_gb_xxxt", "vmem_dram_xxxt",
    # Unconstrained baseline + catch-all
    "base", "others",
]

MODE_COLOR = {
    "gb_oooo":        "#4c78a8",
    "gb_ooot":        "#6a9fc8",
    "gb_oook":        "#8bbfe8",
    "gb_ootk":        "#2a5a88",
    "dram_oooo":      "#f58518",
    "dram_ooot":      "#f7a44a",
    "dram_oook":      "#f9c37c",
    "psum_gb_otok":   "#54a24b",
    "psum_dram_ootk": "#e45756",
    "psum_dram_otok": "#c03030",
    "vmem_gb_xxxt":   "#e91e63",
    "vmem_dram_xxxt": "#795548",
    "base":           "#9467bd",
    "others":         "#aaaaaa",
}

def bucket(mode: str) -> str:
    return mode if mode in BUCKETS[:-1] else "others"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_file(path: Path) -> dict | None:
    m = re.match(
        r"cin(\d+)_cout(\d+)_ho(\d+)_wo(\d+)_kh(\d+)_kw(\d+)_T(\d+)",
        path.stem,
    )
    if not m:
        return None
    cin, cout, ho, wo, kh, kw, t = (int(x) for x in m.groups())

    text = path.read_text()
    best, block = extract_best_block(text, text.splitlines())
    if not best:
        return None

    dram_l    = next((s for s in block if s.startswith("dram:")), "")
    gb_l      = next((s for s in block if s.startswith("gb:")),   "")
    sp_l      = next((s for s in block if s.startswith("sp:")),   "")
    lat_l     = next((s for s in block if s.startswith("latency=")), "")
    traffic_per_var = parse_traffic_per_var(block)

    total_traffic: float | None = None
    m_tr = re.search(r"traffic=([\d.]+)\s*(B|KB|MB|GB)", lat_l)
    if m_tr:
        total_traffic = parse_bytes_str(f"{m_tr.group(1)} {m_tr.group(2)}")

    return {
        "CIN":             cin,
        "COUT":            cout,
        "HO":              ho,
        "WO":              wo,
        "KH":              kh,
        "KW":              kw,
        "T":               t,
        "spatial":         ho * wo,
        "best":            best,
        "dram_t":          classify_t_in_loop(dram_l),
        "gb_t":            classify_t_in_loop(gb_l),
        "dram_body":       re.sub(r"^\s*dram:\s*", "", dram_l).strip() if dram_l else "none",
        "gb_body":         re.sub(r"^\s*gb:\s*",   "", gb_l).strip()   if gb_l   else "none",
        "sp_pattern":      sp_dims(sp_l),
        "total_traffic":   total_traffic,
        "traffic_per_var": traffic_per_var,
    }


# ---------------------------------------------------------------------------
# Rate helpers
# ---------------------------------------------------------------------------

def overall_rates(records: list[dict]) -> dict[str, float]:
    n  = len(records)
    mc = Counter(bucket(r["best"]) for r in records)
    return {m: mc[m] / n for m in BUCKETS}


def rates_1d(records: list[dict], param: str) -> tuple[list, dict]:
    vals = sorted({r[param] for r in records},
                  key=lambda x: x if isinstance(x, (int, float)) else x)
    out = {}
    for v in vals:
        sub = [r for r in records if r[param] == v]
        n   = len(sub)
        mc  = Counter(bucket(r["best"]) for r in sub)
        out[v] = {m: mc[m] / n for m in BUCKETS}
    return vals, out


PARAM_LABEL = {
    "T":       "T (timesteps)",
    "KH":      "Kernel size (KH=KW)",
    "HO":      "Spatial size (HO=WO)",
    "CIN":     "Input channels (CIN)",
    "COUT":    "Output channels (COUT)",
    "spatial": "Spatial area (HO×WO)",
}

def pval(param: str, v) -> str:
    if param == "T":       return f"T={v}"
    if param == "KH":      return f"{v}×{v}"
    if param == "HO":      return f"{v}×{v}"
    if param == "spatial": return f"{v} ({int(v**0.5)}²)" if int(v**0.5)**2 == v else str(v)
    return str(v)


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def md_overall_table(records: list[dict]) -> str:
    n  = len(records)
    ov = overall_rates(records)
    active = [m for m in BUCKETS if ov[m] > 0]

    lines = [
        "## Overall Mode Distribution\n",
        f"| Mode | Count | Rate |",
        "|:-----|------:|-----:|",
    ]
    for m in active:
        cnt = round(ov[m] * n)
        lines.append(f"| `{m}` | {cnt} | {100*ov[m]:.1f}% |")
    n_shapes = len({(r["CIN"], r["COUT"], r["HO"], r["WO"], r["KH"], r["KW"]) for r in records})
    lines.append(f"\n_Total: {n} workloads ({n_shapes} unique shapes × T ∈ {{4, 32, 128}})_\n")
    return "\n".join(lines)


def _top_body(bodies: list[str]) -> str:
    ctr = Counter(bodies)
    top, cnt = ctr.most_common(1)[0]
    pct = 100 * cnt / len(bodies)
    s   = top if len(top) <= 35 else top[:32] + "…"
    return f"`{s}`" + (f" ({pct:.0f}%)" if pct < 95 else "")


def md_tiling_analysis(records: list[dict]) -> str:
    active = [m for m in BUCKETS if sum(1 for r in records if bucket(r["best"]) == m) > 0]

    lines = ["## Temporal Tiling Analysis\n"]
    lines.append(
        "> T-classification per memory level: "
        "`oooo` = T not tiled (T→spatial);  "
        "`ooot` = T alone;  "
        "`ootk` = T co-tiled with K dim;  "
        "`xxxt` = T outermost.\n"
    )

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
        dram_ex  = _top_body([r["dram_body"] for r in grp])
        gb_ex    = _top_body([r["gb_body"]   for r in grp])

        lines.append(f"| `{m}` | {n} | {dram_str} | {gb_str} | {dram_ex} | {gb_ex} |")
        mode_domtile[m] = (top_dt[0], top_gt[0])

    lines.append("")
    return "\n".join(lines)


def md_section(records: list[dict]) -> str:
    n       = len(records)
    overall = overall_rates(records)
    active  = [m for m in BUCKETS if overall[m] > 0]

    lines: list[str] = []
    lines.append(f"## Per-Workload-Parameter Rate Tables  ({n} workloads)\n")

    overall_parts = [f"`{m}` = {100*overall[m]:.1f}%" for m in active]
    lines.append("**Overall rates**: " + " &nbsp;·&nbsp; ".join(overall_parts) + "\n")
    lines.append("> **Bold** = rate > 5 pp above that mode's overall average (and > 3 %).\n")

    for param in ["T", "KH", "HO", "CIN", "COUT"]:
        vals, row_rates = rates_1d(records, param)
        lines.append(f"### {PARAM_LABEL[param]}\n")

        header = "| Value | n | " + " | ".join(m.replace("_", "\\_") for m in active) + " |"
        sep    = "|:------|--:|" + "|".join("------:" for _ in active) + "|"
        lines.append(header)
        lines.append(sep)

        for v in vals:
            sub = [r for r in records if r[param] == v]
            cells = []
            for m in active:
                r   = row_rates[v][m]
                pct = f"{100*r:.0f}%"
                if r - overall[m] > 0.05 and r > 0.03:
                    pct = f"**{pct}**"
                cells.append(pct)
            lines.append(f"| {pval(param, v)} | {len(sub)} | " + " | ".join(cells) + " |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory traffic breakdown analysis
# ---------------------------------------------------------------------------

TRAFFIC_VARS = ["weight", "psum", "vmem"]


def _autoscale(val: float) -> str:
    for unit, thr in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
        if val >= thr:
            return f"{val / thr:.2f} {unit}"
    return f"{val:.0f} B"


def md_traffic_analysis(records: list[dict]) -> str:
    """Traffic breakdown section: weight / psum / vmem fraction per mode and per parameter."""
    tr_records = [r for r in records if r["traffic_per_var"] is not None]
    lines: list[str] = ["## Memory Traffic Breakdown (weight / psum / vmem)\n"]

    if not tr_records:
        lines.append(
            "_No per-variable traffic data found. Re-run the profiling sweep with the "
            "updated snn_cosa (cli.py now emits `traffic/:` lines) to populate this section._\n"
        )
        return "\n".join(lines)

    n = len(tr_records)
    lines.append(f"_Based on {n} workloads that carry `traffic/:` breakdowns._\n")

    # --- Overall average fractions per mode ---
    active = [m for m in BUCKETS
              if sum(1 for r in tr_records if bucket(r["best"]) == m) > 0]

    lines.append("### Average traffic fractions per mode\n")
    lines.append("| Mode | n | Avg total | weight% | psum% | vmem% |")
    lines.append("|:-----|--:|----------:|--------:|------:|------:|")
    for m in active:
        grp = [r for r in tr_records if bucket(r["best"]) == m]
        if not grp:
            continue
        totals = [sum(r["traffic_per_var"].values()) for r in grp]
        avg_total = np.mean(totals)
        fracs: dict[str, list[float]] = {v: [] for v in TRAFFIC_VARS}
        for r in grp:
            t = r["traffic_per_var"]
            tot = sum(t.values()) or 1.0
            for v in TRAFFIC_VARS:
                fracs[v].append(100 * t.get(v, 0.0) / tot)
        cells = "  ".join(f"{np.mean(fracs[v]):.0f}%" for v in TRAFFIC_VARS)
        lines.append(
            f"| `{m}` | {len(grp)} | {_autoscale(avg_total)} | "
            + " | ".join(f"{np.mean(fracs[v]):.0f}%" for v in TRAFFIC_VARS)
            + " |"
        )
    lines.append("")

    # --- Per-parameter breakdown for ALL workloads ---
    lines.append("### Traffic fraction vs. workload parameter\n")
    lines.append(
        "> Rows show mean weight% / psum% / vmem% across workloads with that parameter value.\n"
    )

    for param in ["T", "KH", "HO", "CIN", "COUT"]:
        vals = sorted({r[param] for r in tr_records},
                      key=lambda x: x if isinstance(x, (int, float)) else x)
        lines.append(f"#### {PARAM_LABEL[param]}\n")
        lines.append("| Value | n | weight% | psum% | vmem% |")
        lines.append("|:------|--:|--------:|------:|------:|")
        for v in vals:
            sub = [r for r in tr_records if r[param] == v]
            fracs = {var: [] for var in TRAFFIC_VARS}
            for r in sub:
                t = r["traffic_per_var"]
                tot = sum(t.values()) or 1.0
                for var in TRAFFIC_VARS:
                    fracs[var].append(100 * t.get(var, 0.0) / tot)
            lines.append(
                f"| {pval(param, v)} | {len(sub)} | "
                + " | ".join(f"{np.mean(fracs[var]):.0f}%" for var in TRAFFIC_VARS)
                + " |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spatial split pie charts
# ---------------------------------------------------------------------------

def fig_sp_pie(records: list[dict]) -> plt.Figure:
    """One pie per mode showing sp: dimension-pattern distribution."""
    active = [m for m in BUCKETS
              if sum(1 for r in records if bucket(r["best"]) == m) > 0]

    # Also add a pie per T value for the dominant mode
    dominant = active[0]
    t_vals   = sorted({r["T"] for r in records})
    t_groups = [(f"{dominant}\nT={t}", [r for r in records
                 if r["T"] == t and bucket(r["best"]) == dominant])
                for t in t_vals]
    t_groups = [(lbl, grp) for lbl, grp in t_groups if grp]

    panels = [(m, [r for r in records if bucket(r["best"]) == m]) for m in active]
    panels += t_groups

    ncols = 2
    nrows = (len(panels) + 1) // 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 5.5 * nrows))
    axes_flat = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for idx, (label, grp) in enumerate(panels):
        ax  = axes_flat[idx]
        ctr = Counter(r["sp_pattern"] for r in grp)
        n   = len(grp)

        top       = ctr.most_common(8)
        other_cnt = sum(c for _, c in ctr.most_common()[8:])
        labels    = [t[0] for t in top]
        sizes     = [t[1] for t in top]
        if other_cnt > 0:
            labels.append("other")
            sizes.append(other_cnt)

        cmap   = plt.colormaps["tab20"].resampled(max(len(labels), 1))
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

        legend_labels = [
            f"{lab}  ({100*sz/n:.0f}%)" for lab, sz in zip(labels, sizes)
        ]
        ax.legend(
            wedges, legend_labels,
            loc="lower center", bbox_to_anchor=(0.5, -0.30),
            fontsize=7, ncol=2, framealpha=0.7,
        )
        mode_key = label.split("\n")[0]
        ax.set_title(
            f"{label}  (n={n})",
            fontsize=9, fontweight="bold",
            color=MODE_COLOR.get(mode_key, "black"),
        )

    for idx in range(len(panels), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle(
        "Profiling sweep — spatial split (sp:) dimension patterns per mode\n"
        "Fixed arch: nodes=256, L1=8KB, L2=256KB, PE=64, split=w30v1p1",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    files   = sorted(SWEEP_DIR.glob("cin*.txt"))
    records = [r for f in files if (r := parse_file(f)) is not None]
    if not records:
        print(f"No profiling sweep txt files found under {SWEEP_DIR}")
        return
    print(f"Loaded {len(records)} profiling sweep results")

    # Markdown
    md = "\n".join([
        "# Profiling Sweep — Mode Selection Analysis\n",
        "> Fixed arch: nodes=256, L1=8 KB, L2=256 KB, PE=64, split=w30:vmem1:psum1\n",
        md_overall_table(records),
        "\n---\n",
        md_tiling_analysis(records),
        "\n---\n",
        md_section(records),
        "\n---\n",
        md_traffic_analysis(records),
    ])
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(md)
    print(f"Markdown → {MD_OUT}")

    # Figures
    FIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(FIG_OUT) as pdf:
        f = fig_sp_pie(records)
        pdf.savefig(f, bbox_inches="tight")
        plt.close(f)
    print(f"Figures  → {FIG_OUT}")


if __name__ == "__main__":
    main()
