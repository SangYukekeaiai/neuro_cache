#!/usr/bin/env python3
"""Milestone 4 (core point estimate only) - per-offset firing probability P_fire.

Computes the plan's headline conditional-firing statistic (plan Sec 2, Sec 4.4
pt 1) for the kernel-window radius-1 ring, as a point estimate. NOT the full
Sec 4.4 aggregation ladder (many slice_keys, anchor- vs equal-weighting) and NOT
the Sec 5 bootstrap CIs - both deferred.

  B* / W (plan Sec 0, per user): B* = p90(D_C) of a fixed REFERENCE
  (slice_key, offset), computed ONCE and reused as a CONSTANT threshold across
  every other offset/arch/layer. It is NOT recomputed per slice - doing that
  would peg Pr[D_C <= B*] at ~0.90 for whichever distribution it came from and
  destroy cross-slice comparability. Reference here: the (Δkh,Δkw)=(0,1) slice
  on this layer, whose D_C p90 is 33. Access-count units, matching D_A / D_C.

  P_fire (plan Sec 2, Sec 4.4 pt 1, Sec 8): per offset,
      P_fire(offset) = #{resolved pairs with D <= W} / #anchors_in_slice
  where the denominator is ALL anchors in the slice (resolved + unresolved).
  Unresolved (no forward firing, ⊥) anchors stay in the denominator as
  beyond-window; dropping them is the Sec 8 guard's forbidden higher number.

Reuses walking_skeleton.collect_da for the (t, s) pairing and
distinct_distance.dc_bit_sweep for D_C; no pairing or distance logic is
re-derived here.

Usage (from project root):
    conda run -n base python scripts/locality_analysis/pfire_stats.py
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

from locality_analysis.distinct_distance import dc_bit_sweep  # noqa: E402
from locality_analysis.trace_io import load_trace  # noqa: E402
from locality_analysis.walking_skeleton import OUT_DIR, collect_da  # noqa: E402

# Radius-1 axis-aligned ring around the pinned anchor (task scope: these four
# offsets only, not the full 8-connected Chebyshev ring of plan Sec 2).
RING = [(0, 1), (0, -1), (1, 0), (-1, 0)]

# Reference (slice_key, offset) whose D_C p90 defines the fixed B* constant.
REFERENCE_OFFSET = (0, 1)


def offset_dc(trace, offset) -> tuple[dict, np.ndarray]:
    """Reuse milestone-2 pairing + milestone-3 D_C for one offset.

    Returns (collect_da result, D_C array aligned with the resolved pairs).
    """
    res = collect_da(trace, offset)
    dc = (np.array(dc_bit_sweep(trace.stream, res["pairs"]))
          if res["resolved"] else np.array([], dtype=np.int64))
    return res, dc


def offset_breakdown(res: dict, dc: np.ndarray, bstar: float) -> dict:
    """Full auditable P_fire breakdown for one neighbor offset.

    Denominator is #anchors_in_slice = resolved + unresolved (plan Sec 4.4 pt 1):
    unresolved anchors are counted as beyond-window, never dropped.
    """
    offset = res["offset"]
    total = res["anchors"]
    resolved = res["resolved"]
    unresolved = res["unresolved"]
    da = res["da"]

    within_dc = int(np.sum(dc <= bstar))
    within_da = int(np.sum(da <= bstar))
    beyond_dc = resolved - within_dc  # resolved but fired too late (D > B*)
    beyond_da = resolved - within_da

    # Self-check: total decomposes exactly (within + fired-too-late + never-fired).
    assert within_dc + beyond_dc + unresolved == total, (
        f"D_C decomposition broke: {within_dc}+{beyond_dc}+{unresolved} != {total}")
    assert within_da + beyond_da + unresolved == total, (
        f"D_A decomposition broke: {within_da}+{beyond_da}+{unresolved} != {total}")
    assert resolved + unresolved == total, "anchors != resolved + unresolved"

    return {
        "offset": offset,
        "total": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "within_dc": within_dc,
        "beyond_dc": beyond_dc,
        "within_da": within_da,
        "beyond_da": beyond_da,
        # Sec 8 guard: denominator is total anchors, NOT resolved-only.
        "pfire_dc": within_dc / total if total else float("nan"),
        "pfire_da": within_da / total if total else float("nan"),
        "pfire_dc_dropcheck": within_dc / resolved if resolved else float("nan"),
    }


def plot_pfire_bar(arch: str, layer: str, rows: list[dict], bstar: float) -> Path:
    """Plan Sec 7 artifact #4: per-offset Pr[D_C <= B*] bar chart (small version)."""
    labels = [f"({o[0]},{o[1]})" for o in (r["offset"] for r in rows)]
    vals = [r["pfire_dc"] for r in rows]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, vals, color="#54a24b", width=0.6)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.3f}",
                ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("kernel-window offset (Δkh, Δkw)")
    ax.set_ylabel(f"P_fire = Pr[D_C ≤ B*]   (B* = {bstar:.1f})")
    ax.set_title(
        f"Per-offset firing probability - {arch}/{layer}\n"
        f"Analysis 1 radius-1 ring, denom = all anchors (⊥ included)",
        fontsize=9,
    )
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()

    out = OUT_DIR / f"pfire_bar_{arch}_{layer}.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", default="vgg16_T4_all")
    parser.add_argument("--arch", default="gustavsnn")
    parser.add_argument("--layer", default="layer_01_features_3")
    parser.add_argument("--sample", type=int, default=0)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== P_fire point estimate (plan Sec 2, Sec 4.4 pt 1) ===")
    print(f"layer: {args.arch}/{args.layer} sample {args.sample}")

    trace = load_trace(args.arch, args.network, args.layer, args.sample)
    KH, KW = trace.dims["KH"], trace.dims["KW"]

    # -- ring offsets: keep only those in-bounds for this layer's kernel --------
    kept, dropped = [], []
    for dkh, dkw in RING:
        if abs(dkh) < KH and abs(dkw) < KW:
            kept.append((dkh, dkw))
        else:
            dropped.append((dkh, dkw))
    print(f"kernel KH={KH} KW={KW}: in-bounds offsets {kept}; dropped {dropped}")

    # D_A / D_C for every in-bounds offset (pairing + BIT sweep reused).
    dc_by_offset = {off: offset_dc(trace, off) for off in kept}

    # -- B* fixed ONCE as p90(D_C) of the reference offset, reused for all ------
    # Fixed-once-reused: recomputing p90 per slice would peg Pr[D_C<=B*] at ~0.90
    # for each slice and destroy cross-slice comparability (plan Sec 0).
    ref_dc = dc_by_offset[REFERENCE_OFFSET][1]
    bstar = float(np.percentile(ref_dc, 90))
    assert bstar == 33, f"reference p90(D_C) expected 33, got {bstar}"
    print(f"B* = p90(D_C) of reference offset {REFERENCE_OFFSET} = {bstar:.0f} "
          f"(fixed once, reused as a constant threshold for every offset)")

    rows = [offset_breakdown(res, dc, bstar) for res, dc in
            (dc_by_offset[off] for off in kept)]

    # -- per-offset auditable table --------------------------------------------
    print("\nPer-offset breakdown (denominator = total anchors, ⊥ included):")
    hdr = (f"  {'offset':>8} | {'total':>6} {'resolv':>6} {'w/inB*':>6} "
           f"{'beyond':>6} {'unres⊥':>6} | {'Pr[Dc<=B*]':>10} {'Pr[Da<=B*]':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        print(f"  {str(r['offset']):>8} | {r['total']:>6} {r['resolved']:>6} "
              f"{r['within_dc']:>6} {r['beyond_dc']:>6} {r['unresolved']:>6} | "
              f"{r['pfire_dc']:>10.4f} {r['pfire_da']:>10.4f}")

    # -- Sec 8 unresolved-in-denominator guard ---------------------------------
    # Correct denominator is total anchors (resolved + ⊥); dropping ⊥ can only
    # raise P_fire, and does so strictly whenever some pair is within-window and
    # some anchor is unresolved. (With within=0 both versions are 0 - no gap.)
    print("\nSec 8 guard - unresolved (⊥) anchors are in the DENOMINATOR:")
    for r in rows:
        drop = r["pfire_dc_dropcheck"]
        assert drop >= r["pfire_dc"], "guard failed: dropping ⊥ must not lower P_fire"
        if r["unresolved"] == 0:
            note = "same (no ⊥)"
        elif r["within_dc"] == 0:
            note = f"dropping ⊥ -> {drop:.4f} (unchanged: 0 within-window pairs)"
        else:
            assert drop > r["pfire_dc"], "guard failed: dropping ⊥ should raise P_fire"
            note = f"dropping ⊥ -> {drop:.4f} (HIGHER, wrong)"
        print(f"  offset {str(r['offset']):>8}: correct Pr[Dc<=B*]={r['pfire_dc']:.4f}"
              f" (denom={r['total']}); {note}")

    # decode of the "without spatial locality" fraction
    print("\n'Without locality' decomposition (1 - Pr[Dc<=B*]):")
    for r in rows:
        without = 1 - r["pfire_dc"]
        print(f"  offset {str(r['offset']):>8}: {without:.4f} total = "
              f"fired-too-late {r['beyond_dc']}/{r['total']}={r['beyond_dc']/r['total']:.4f}"
              f" + never-fired-again {r['unresolved']}/{r['total']}={r['unresolved']/r['total']:.4f}")

    # -- bar chart (plan Sec 7 artifact #4) ------------------------------------
    out = plot_pfire_bar(args.arch, args.layer, rows, bstar)
    print(f"\nbar chart -> {out}")

    print("\nDEFERRED (not implemented here): Sec 5 bootstrap CIs and the full "
          "Sec 4.4 aggregation ladder (multi-slice, anchor- vs equal-weighted).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
