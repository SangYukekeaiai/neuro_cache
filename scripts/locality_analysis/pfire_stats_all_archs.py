#!/usr/bin/env python3
"""Cross-arch extension of pfire_stats.py: per-offset P_fire across all 5 archs.

Repeats the EXACT milestone-4 point-estimate computation of pfire_stats.py
(same reference layer, network, sample, radius-1 ring, pinned-slice rule) for
every dataflow arch, so the directional-locality pattern can be compared across
the design space. Nothing in the underlying computation is re-derived here: the
per-offset pairing (walking_skeleton.collect_da), D_C BIT sweep
(distinct_distance.dc_bit_sweep), and the P_fire breakdown/plotting helpers
(pfire_stats.offset_dc / offset_breakdown) are imported and reused verbatim.

B* is the plan's fixed-once-reused constant (plan Sec 0, Sec 4.4): B* = 33 =
p90(D_C) of the reference (slice_key, offset) = gustavsnn/layer_01_features_3,
offset (0,1). It is computed ONCE from gustavsnn's reference offset (with the
same assert pfire_stats.py uses), then applied UNCHANGED as the threshold for
every arch/offset - it is NOT recomputed per arch, which would peg
Pr[D_C <= B*] near 0.90 for each arch's own reference distribution and destroy
cross-arch comparability.

Deliverables (task scope):
  1. combined table: rows = arch, cols = 4 ring offsets, cells = Pr[D_C<=B*] %.
  2. grouped bar chart -> pfire_bar_all_archs_layer_01_features_3.pdf
  3. underlying resolved/within/beyond/unresolved counts printed per arch/offset.

Usage (from project root):
    conda run -n base python scripts/locality_analysis/pfire_stats_all_archs.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.pfire_stats import (  # noqa: E402
    REFERENCE_OFFSET, RING, offset_breakdown, offset_dc,
)
from locality_analysis.trace_io import load_trace  # noqa: E402
from locality_analysis.walking_skeleton import OUT_DIR  # noqa: E402

# The 5 dataflow archs (plan Sec 1.2). gustavsnn first so its reference offset
# fixes B* before any other arch is processed.
ARCHS = ["gustavsnn", "loas", "prosperity", "ptb", "spinalflow"]

# Okabe-Ito colorblind-safe palette, one colour per ring offset (also hatched
# below so the four offsets never rely on colour alone).
OFFSET_COLORS = {
    (0, 1): "#0072b2",
    (0, -1): "#e69f00",
    (1, 0): "#009e73",
    (-1, 0): "#cc79a7",
}
OFFSET_HATCH = {(0, 1): "", (0, -1): "//", (1, 0): "..", (-1, 0): "xx"}


def compute_arch(arch: str, network: str, layer: str, sample: int, bstar: float):
    """Full per-offset breakdown for one arch, reusing pfire_stats verbatim.

    Returns (rows, kept, note) where rows is a list of offset_breakdown dicts for
    the in-bounds offsets, or (None, None, note) if the trace is missing/empty.
    The pinned (cin0, cr0) slice is chosen exactly as the reference computation
    does: collect_da pins on stream[0]'s (cin, cr) for this arch's own data.
    """
    try:
        trace = load_trace(arch, network, layer, sample)
    except FileNotFoundError as exc:
        return None, None, f"trace missing ({exc})"

    if not trace.stream:
        return None, None, "empty stream"

    KH, KW = trace.dims["KH"], trace.dims["KW"]
    kept = [(dkh, dkw) for dkh, dkw in RING if abs(dkh) < KH and abs(dkw) < KW]
    if not kept:
        return None, None, f"no in-bounds ring offsets (KH={KH}, KW={KW})"

    dc_by_offset = {off: offset_dc(trace, off) for off in kept}
    rows = [offset_breakdown(res, dc, bstar) for res, dc in
            (dc_by_offset[off] for off in kept)]
    # pinned slice is identical across offsets; read it off the first result.
    slice_key = dc_by_offset[kept[0]][0]["slice"]
    note = f"KH={KH} KW={KW}, pinned cin0={slice_key[0]} cr0={slice_key[1]}"
    return rows, kept, note


def plot_grouped_bar(results: dict, layer: str, bstar: float) -> Path:
    """Grouped bar: x = arch, one bar per ring offset, height = Pr[D_C<=B*]."""
    archs = [a for a in ARCHS if results[a][0] is not None]
    offsets = RING
    n_off = len(offsets)
    x = np.arange(len(archs))
    bar_w = 0.8 / n_off

    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    for j, off in enumerate(offsets):
        vals = []
        for a in archs:
            rows = {tuple(r["offset"]): r for r in results[a][0]}
            vals.append(rows[off]["pfire_dc"] if off in rows else np.nan)
        xpos = x + (j - (n_off - 1) / 2) * bar_w
        bars = ax.bar(xpos, vals, bar_w, label=f"({off[0]},{off[1]})",
                      color=OFFSET_COLORS[off], hatch=OFFSET_HATCH[off],
                      edgecolor="white", linewidth=0.4)
        for bar, v in zip(bars, vals):
            if np.isfinite(v):
                ax.text(bar.get_x() + bar.get_width() / 2, v + 0.015,
                        f"{v * 100:.1f}", ha="center", va="bottom", fontsize=6)

    ax.set_xticks(x)
    ax.set_xticklabels(archs, fontsize=9)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel(f"P_fire = Pr[D_C ≤ B*]   (B* = {bstar:.0f})", fontsize=9)
    ax.set_xlabel("dataflow arch", fontsize=9)
    ax.set_title(
        f"Per-offset firing probability across archs - {layer}\n"
        f"Analysis 1 radius-1 ring, denom = all anchors (⊥ included), "
        f"fixed B*={bstar:.0f}",
        fontsize=9,
    )
    ax.legend(title="offset (Δkh,Δkw)", fontsize=7, title_fontsize=7,
              ncol=4, loc="upper center", frameon=False,
              bbox_to_anchor=(0.5, -0.18))
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()

    out = OUT_DIR / f"pfire_bar_all_archs_{layer}.pdf"
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", default="vgg16_T4_all")
    parser.add_argument("--layer", default="layer_01_features_3")
    parser.add_argument("--sample", type=int, default=0)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== P_fire across archs (plan Sec 2, Sec 4.4 pt 1) ===")
    print(f"layer: {args.layer} sample {args.sample}, network {args.network}")

    # -- B* fixed ONCE from gustavsnn's reference offset, reused as a constant --
    ref_trace = load_trace("gustavsnn", args.network, args.layer, args.sample)
    _, ref_dc = offset_dc(ref_trace, REFERENCE_OFFSET)
    bstar = float(np.percentile(ref_dc, 90))
    assert bstar == 33, f"reference p90(D_C) expected 33, got {bstar}"
    print(f"B* = p90(D_C) of gustavsnn reference offset {REFERENCE_OFFSET} = "
          f"{bstar:.0f} (fixed once, reused unchanged for every arch/offset)\n")

    results = {}
    for arch in ARCHS:
        rows, kept, note = compute_arch(
            arch, args.network, args.layer, args.sample, bstar)
        results[arch] = (rows, kept, note)
        print(f"--- {arch}: {note}")
        if rows is None:
            print("    SKIPPED (no data / out of bounds)\n")
            continue
        hdr = (f"    {'offset':>8} | {'total':>6} {'resolv':>6} {'w/inB*':>6} "
               f"{'beyond':>6} {'unres⊥':>6} | {'Pr[Dc<=B*]':>10}")
        print(hdr)
        print("    " + "-" * (len(hdr) - 4))
        for r in rows:
            print(f"    {str(r['offset']):>8} | {r['total']:>6} "
                  f"{r['resolved']:>6} {r['within_dc']:>6} {r['beyond_dc']:>6} "
                  f"{r['unresolved']:>6} | {r['pfire_dc'] * 100:>9.2f}%")
        print()

    # -- combined table: rows = arch, cols = 4 offsets, cells = Pr[D_C<=B*] % ---
    print("=== Combined table: Pr[D_C <= B*] (%) ===")
    col_hdr = "  " + f"{'arch':>11} | " + " ".join(
        f"{f'({o[0]},{o[1]})':>9}" for o in RING)
    print(col_hdr)
    print("  " + "-" * (len(col_hdr) - 2))
    for arch in ARCHS:
        rows = results[arch][0]
        if rows is None:
            cells = " ".join(f"{'n/a':>9}" for _ in RING)
        else:
            by_off = {tuple(r["offset"]): r for r in rows}
            cells = " ".join(
                (f"{by_off[o]['pfire_dc'] * 100:>8.2f}%" if o in by_off
                 else f"{'oob':>9}") for o in RING)
        print(f"  {arch:>11} | {cells}")

    out = plot_grouped_bar(results, args.layer, bstar)
    print(f"\ngrouped bar chart -> {out}")
    print(f"                png -> {out.with_suffix('.png')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
