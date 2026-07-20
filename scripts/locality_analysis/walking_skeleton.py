#!/usr/bin/env python3
"""Milestone 2 - walking skeleton (plan Sec 10, "end-to-end before scaling").

Two pieces, both on real trace data, D_A only (D_C / BIT sweep is milestone 3):

  A. Analysis-1 next-occurrence pairing for D_A (plan Sec 4.2), then one ECDF of
     D_A for kernel-window offset (Dkh, Dkw) = (0, 1), pinned on the first
     (cin0, cr0) slice encountered, on one real layer.

  B. Sec 4.5 per-tile access-count heatmap (pairing-free): rows = flattened
     (kh, kw), columns = dram_i tile index, cell = raw access count to that
     row's coordinate within that tile, pinned on (cin0, cr0). Produced for the
     decided 5-sample subset {0,20,40,60,80} on one small layer for two
     contrasting archs (gustavsnn width-8 cr vs prosperity width-128/clamped cr)
     to show the design-space difference.

Usage (from project root):
    python scripts/locality_analysis/walking_skeleton.py
"""
from __future__ import annotations

import argparse
import sys
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.trace_io import load_trace, observed_widths  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "locality_analysis"

# Fixed subset for the Sec 4.5 heatmaps (plan Sec 4.5, decided).
HEATMAP_SAMPLES = [0, 20, 40, 60, 80]
KW_OFFSET = (0, 1)  # (Dkh, Dkw) for the Analysis-1 ECDF


# ── A. D_A next-occurrence pairing + ECDF ───────────────────────────────────────

def build_occ(stream: list) -> dict:
    """coord -> ascending list of stream positions where it occurs."""
    occ = defaultdict(list)
    for t, coord in enumerate(stream):
        occ[coord].append(t)
    return occ


def next_occurrence(positions: list | None, t: int) -> int | None:
    """First position strictly greater than t, or None."""
    if not positions:
        return None
    i = bisect_right(positions, t)
    return positions[i] if i < len(positions) else None


def collect_da(trace, offset=KW_OFFSET) -> dict:
    """Analysis-1 D_A pairing on the first (cin0, cr0) slice encountered."""
    stream = trace.stream
    KW = trace.dims["KW"]
    dkh, dkw = offset
    kh0_a, kw0_a, cin0, cs0, ce0 = stream[0]
    cr0 = (cs0, ce0)
    occ = build_occ(stream)

    da = []
    pairs = []  # (t, s) for each resolved pair, aligned with `da` (milestone 3 reuses this)
    unresolved = 0
    anchors = 0
    for t, (kh, kw, cin, cs, ce) in enumerate(stream):
        if cin != cin0 or (cs, ce) != cr0:
            continue
        nkh, nkw = kh + dkh, kw + dkw
        if not (0 <= nkh < trace.dims["KH"] and 0 <= nkw < KW):
            continue  # neighbor out of kernel bounds: no pair to form
        anchors += 1
        s = next_occurrence(occ.get((nkh, nkw, cin0, cs0, ce0)), t)
        if s is None:
            unresolved += 1
        else:
            da.append(s - t)
            pairs.append((t, s))
    return {
        "slice": (cin0, cr0), "offset": offset,
        "anchors": anchors, "resolved": len(da), "unresolved": unresolved,
        "da": np.array(da), "pairs": pairs,
    }


def plot_da_ecdf(trace, res: dict) -> Path:
    da = res["da"]
    xs = np.sort(da)
    ys = np.arange(1, len(xs) + 1) / len(xs)
    med, p90 = np.percentile(da, [50, 90])

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.step(xs, ys, where="post", color="#4c78a8", lw=1.6)
    ax.axvline(med, color="#e45756", ls="--", lw=1, label=f"median = {med:.0f}")
    ax.axvline(p90, color="#f58518", ls="--", lw=1, label=f"p90 = {p90:.0f}")
    ax.set_xscale("log")
    ax.set_xlabel("D_A  (access-count gap s - t)")
    ax.set_ylabel("empirical CDF")
    ax.set_ylim(0, 1.02)
    ax.set_title(
        f"D_A ECDF - {trace.arch}/{trace.layer}\n"
        f"Analysis 1, offset (Dkh,Dkw)={res['offset']}, "
        f"pinned cin0={res['slice'][0]} cr0={res['slice'][1]}  "
        f"(resolved {res['resolved']}/{res['anchors']})",
        fontsize=9,
    )
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()

    out = OUT_DIR / f"da_ecdf_{trace.arch}_{trace.layer}_offset{KW_OFFSET[0]}-{KW_OFFSET[1]}.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# ── B. Sec 4.5 per-tile access-count heatmap ────────────────────────────────────

def access_count_matrix(trace) -> tuple[np.ndarray, tuple]:
    """rows = flattened (kh,kw), cols = dram_i; cell = raw access count, pinned
    on the first (cin0, cr0) encountered."""
    KH, KW = trace.dims["KH"], trace.dims["KW"]
    _, _, cin0, cs0, ce0 = trace.stream[0]
    cr0 = (cs0, ce0)
    mat = np.zeros((KH * KW, trace.dram_num_steps), dtype=np.int64)
    for (kh, kw, cin, cs, ce), tile in zip(trace.stream, trace.tile_of):
        if cin == cin0 and (cs, ce) == cr0:
            mat[kh * KW + kw, tile] += 1
    return mat, (cin0, cr0)


def plot_heatmaps(arch: str, network: str, layer: str) -> Path:
    fig, axes = plt.subplots(len(HEATMAP_SAMPLES), 1,
                             figsize=(11, 2.1 * len(HEATMAP_SAMPLES)))
    width = None
    for ax, sample_idx in zip(axes, HEATMAP_SAMPLES):
        trace = load_trace(arch, network, layer, sample_idx)
        mat, (cin0, cr0) = access_count_matrix(trace)
        width = sorted(observed_widths(trace))
        KH, KW = trace.dims["KH"], trace.dims["KW"]
        im = ax.imshow(mat, aspect="auto", cmap="viridis",
                       interpolation="nearest")
        ax.set_yticks(range(KH * KW))
        ax.set_yticklabels([f"({r // KW},{r % KW})" for r in range(KH * KW)],
                           fontsize=6)
        ax.set_ylabel("(kh,kw)", fontsize=8)
        ax.set_title(
            f"sample {sample_idx}: pinned cin0={cin0} cr0={cr0}, "
            f"{mat.sum()} accesses over {trace.dram_num_steps} tiles",
            fontsize=8,
        )
        plt.colorbar(im, ax=ax, fraction=0.03, pad=0.01, label="count")
    axes[-1].set_xlabel("tile index (dram_i)", fontsize=8)
    fig.suptitle(
        f"Sec 4.5 access-count heatmap - {arch}/{layer}  "
        f"(COUT={trace.dims['COUT']}, cr width={width})",
        fontsize=10,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = OUT_DIR / f"heatmap_kw_{arch}_{layer}.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# ── main ────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", default="vgg16_T4_all")
    parser.add_argument("--ecdf-arch", default="gustavsnn")
    parser.add_argument("--layer", default="layer_01_features_3")
    parser.add_argument("--ecdf-sample", type=int, default=0)
    parser.add_argument("--heatmap-archs", nargs="+",
                        default=["gustavsnn", "prosperity"])
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── A: D_A ECDF ──────────────────────────────────────────────────────────────
    print("\n=== Milestone 2A: D_A next-occurrence pairing + ECDF ===")
    trace = load_trace(args.ecdf_arch, args.network, args.layer, args.ecdf_sample)
    res = collect_da(trace)
    print(f"layer: {trace.arch}/{trace.layer} sample {trace.sample_idx}")
    print(f"pinned slice cin0={res['slice'][0]} cr0={res['slice'][1]}, "
          f"offset (Dkh,Dkw)={res['offset']}")
    print(f"anchors={res['anchors']} resolved={res['resolved']} "
          f"unresolved={res['unresolved']}")
    if res["resolved"]:
        da = res["da"]
        p50, p90, p99 = np.percentile(da, [50, 90, 99])
        print(f"D_A: min={da.min()} median={p50:.0f} p90={p90:.0f} "
              f"p99={p99:.0f} max={da.max()}  "
              f"P_fire(<=median frac resolved)={res['resolved']/res['anchors']:.3f}")
        ecdf_path = plot_da_ecdf(trace, res)
        print(f"ECDF -> {ecdf_path}")
    else:
        print("no resolved pairs; ECDF skipped")

    # ── B: Sec 4.5 heatmaps ──────────────────────────────────────────────────────
    print(f"\n=== Milestone 2B: Sec 4.5 access-count heatmaps "
          f"(samples {HEATMAP_SAMPLES}) ===")
    for arch in args.heatmap_archs:
        path = plot_heatmaps(arch, args.network, args.layer)
        print(f"heatmap ({arch}) -> {path}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
