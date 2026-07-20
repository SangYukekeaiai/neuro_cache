#!/usr/bin/env python3
"""Full-aggregation combined D_C distributions (plan Sec 2, Sec 4.4 pt 1).

Supersedes the proof-of-concept scope of pfire_stats*.py (single sample, single
hand-picked slice, only the 4 orthogonal ring offsets). Here, per
(arch, network, layer), we pool the distinct-address distance D_C across:

  * ALL anchor positions in the stream (full enumeration, no subsampling),
  * ALL in-bounds neighbor offsets of the locality type, and
  * ALL 100 samples (sample_00000 .. sample_00099),

into ONE combined distribution per locality type:

  kernel-window (Analysis 1): pin (cin0, cr0); N1 = full Chebyshev disk
      {(kh0+dh, kw0+dw, cin0, cr0): 0 < max(|dh|,|dw|) <= r_max, in-bounds},
      r_max = min(2, floor(KH/2), floor(KW/2)).  1x1 layers (KH=KW=1) have an
      empty N1 and are SKIPPED for kernel-window (reported in the manifest).

  adjacent-cin (Analysis 2): pin (kh0, kw0, cr0); N2 = full offset set
      {(kh0, kw0, cin0+dc, cr0): dc in {+-1,+-2,+-4,+-8}, |dc| <= floor(CIN/2),
      in-bounds}.

Distance is D_C (plan Sec 3 primary metric), computed by the verified BIT sweep
distinct_distance.dc_bit_sweep. Per sample, kernel-window and adjacent-cin (t,s)
pairs are batched into a SINGLE dc_bit_sweep call over that sample's stream, then
split back out -- O((N + Q) log N) per sample.

Anchor->neighbor pairing reuses the verified primitives
walking_skeleton.build_occ / next_occurrence (NOT collect_da, whose single-slice
single-offset scope this module deliberately replaces).

Memory: resolved D_C values are folded into an integer count array (np.bincount)
per (layer, locality_type) as samples stream in, so no per-pair value list is
held across samples. From that exact integer histogram we read the p90 (over
RESOLVED pairs only; unresolved/⊥ pairs carry no numeric distance and are
excluded from the percentile itself) and the below-p90 count.

Outputs (plan Sec 7 artifact #1, ECDF/histogram of D_C):
  outputs/locality_analysis/dc_distributions/<network>/<arch>/<layer>_{kw,cin}.pdf
      + matching .png (300 dpi)
  outputs/locality_analysis/dc_distributions/aggregation_manifest.json
      per (network, arch, layer, locality): p90, n_resolved, n_unresolved,
      n_below_p90, degenerate-skip flag -- consumed by fraction_bars.py WITHOUT
      recomputation.

Usage (from project root):
    conda run -n base python scripts/locality_analysis/full_aggregation.py
    conda run -n base python scripts/locality_analysis/full_aggregation.py \
        --time-probe --archs gustavsnn --network vgg16_T4_all \
        --layers layer_01_features_3 --samples 0 1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.distinct_distance import dc_bit_sweep  # noqa: E402
from locality_analysis.trace_io import (  # noqa: E402
    ARCHS, NETWORKS, list_layers, load_trace,
)
from locality_analysis.walking_skeleton import build_occ, next_occurrence  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "locality_analysis" / "dc_distributions"
MANIFEST = OUT_DIR / "aggregation_manifest.json"

N_SAMPLES = 100
CIN_OFFSET_BASE = [1, 2, 4, 8]  # plan Sec 2 adjacent-cin offset magnitudes


# -- neighbor-set offset generators (plan Sec 2) ---------------------------------

def kw_offsets(KH: int, KW: int) -> list[tuple[int, int]]:
    """Full Chebyshev disk N1 of radius r_max = min(2, KH//2, KW//2).

    Empty for a 1x1 kernel (r_max = 0): kernel-window locality is degenerate.
    """
    r = min(2, KH // 2, KW // 2)
    return [(dh, dw)
            for dh in range(-r, r + 1)
            for dw in range(-r, r + 1)
            if 0 < max(abs(dh), abs(dw)) <= r]


def cin_offsets(CIN: int) -> list[int]:
    """Full adjacent-cin offset set: +-{1,2,4,8} capped at floor(CIN/2)."""
    cap = CIN // 2
    return [d for base in CIN_OFFSET_BASE if base <= cap for d in (base, -base)]


# -- per-sample pairing (full enumeration, both locality types) ------------------

def collect_pairs(trace, kw_offs, cin_offs):
    """All resolved (t, s) pairs + unresolved counts for one sample's stream.

    Kernel-window pins (cin0, cr0); adjacent-cin pins (kh0, kw0, cr0). cr is the
    full (cout_start, cout_end) tuple, so the neighbor coordinate carries it and
    occ is keyed on the same 5-tuple the stream stores.
    """
    stream = trace.stream
    occ = build_occ(stream)
    KH, KW, CIN = trace.dims["KH"], trace.dims["KW"], trace.dims["CIN"]

    kw_pairs, kw_unres = [], 0
    cin_pairs, cin_unres = [], 0
    for t, (kh, kw, cin, cs, ce) in enumerate(stream):
        for dh, dw in kw_offs:
            nkh, nkw = kh + dh, kw + dw
            if 0 <= nkh < KH and 0 <= nkw < KW:
                s = next_occurrence(occ.get((nkh, nkw, cin, cs, ce)), t)
                if s is None:
                    kw_unres += 1
                else:
                    kw_pairs.append((t, s))
        for dc in cin_offs:
            ncin = cin + dc
            if 0 <= ncin < CIN:
                s = next_occurrence(occ.get((kh, kw, ncin, cs, ce)), t)
                if s is None:
                    cin_unres += 1
                else:
                    cin_pairs.append((t, s))
    return kw_pairs, kw_unres, cin_pairs, cin_unres


def fold_counts(counts: dict, dc_vals) -> None:
    """Accumulate integer D_C values into a {value: count} sparse histogram."""
    if len(dc_vals) == 0:
        return
    arr = np.asarray(dc_vals, dtype=np.int64)
    vals, cnts = np.unique(arr, return_counts=True)
    for v, c in zip(vals.tolist(), cnts.tolist()):
        counts[v] = counts.get(v, 0) + c


# -- exact percentile / below-count from the integer histogram -------------------

def hist_arrays(counts: dict):
    """Sorted (values, counts) arrays from the sparse histogram."""
    if not counts:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    vals = np.array(sorted(counts), dtype=np.int64)
    cnts = np.array([counts[v] for v in vals.tolist()], dtype=np.int64)
    return vals, cnts


def percentile_from_hist(vals, cnts, q: float) -> float:
    """q-th percentile (0..100) over the integer histogram, linear interpolation.

    Matches numpy.percentile's default ('linear') on the equivalent raw sample,
    so p90 here equals p90 of the pooled resolved-D_C values exactly.
    """
    total = int(cnts.sum())
    if total == 0:
        return float("nan")
    # Rank position (0-indexed) of the q-th percentile in the sorted sample.
    pos = (q / 100.0) * (total - 1)
    lo = int(np.floor(pos))
    frac = pos - lo
    cum = np.cumsum(cnts)
    # value at sorted index `lo` and `lo+1`
    i_lo = int(np.searchsorted(cum, lo + 1, side="left"))
    v_lo = float(vals[i_lo])
    if frac == 0.0 or lo + 1 >= total:
        return v_lo
    i_hi = int(np.searchsorted(cum, lo + 2, side="left"))
    v_hi = float(vals[i_hi])
    return v_lo + frac * (v_hi - v_lo)


def below_count(vals, cnts, thresh: float) -> int:
    """Number of resolved pairs with D_C < thresh (strict, plan point 6)."""
    if vals.size == 0:
        return 0
    mask = vals < thresh
    return int(cnts[mask].sum())


# -- plotting (plan Sec 7 artifact #1) -------------------------------------------

def plot_distribution(vals, cnts, p90, n_resolved, n_unresolved,
                      arch, network, layer, locality, out_path) -> None:
    """Histogram (log-x) + ECDF overlay of the pooled D_C, marker at own p90."""
    fig, ax = plt.subplots(figsize=(7.0, 4.2))

    # Histogram as a step over the integer support (log-x; D_C >= 1).
    edges = np.concatenate([vals, [vals[-1] + 1]]).astype(float)
    ax.stairs(cnts, edges, fill=True, color="#4c78a8", alpha=0.55,
              label="D_C histogram (resolved)")
    ax.set_xscale("log")
    ax.set_xlabel("D_C  (distinct-address distance in (t, s])")
    ax.set_ylabel("resolved-pair count", color="#4c78a8")
    ax.tick_params(axis="y", labelcolor="#4c78a8")

    # ECDF on a twin axis.
    ax2 = ax.twinx()
    cum = np.cumsum(cnts) / cnts.sum()
    ax2.step(vals, cum, where="post", color="#333333", lw=1.4, label="ECDF")
    ax2.set_ylabel("empirical CDF")
    ax2.set_ylim(0, 1.02)

    ax.axvline(p90, color="#e45756", ls="--", lw=1.4,
               label=f"p90 = {p90:.0f}")
    frac_unres = n_unresolved / (n_resolved + n_unresolved) if \
        (n_resolved + n_unresolved) else float("nan")
    loc_name = "kernel-window" if locality == "kw" else "adjacent-cin"
    ax.set_title(
        f"{loc_name} D_C distribution - {arch}/{network}/{layer}\n"
        f"pooled over all anchors/offsets/100 samples; "
        f"resolved={n_resolved:,}  unresolved(⊥)={n_unresolved:,} "
        f"({frac_unres:.1%})  p90 over resolved only",
        fontsize=8.5,
    )
    # merged legend
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5, loc="center right")
    ax.grid(True, which="both", axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


# -- per-layer driver ------------------------------------------------------------

def process_layer(arch, network, layer, samples, make_plots=True):
    """Pool D_C across `samples` for one (arch, network, layer); return manifest
    entries for kernel-window and adjacent-cin (kernel-window may be skipped)."""
    kw_counts, cin_counts = {}, {}
    kw_unres_tot, cin_unres_tot = 0, 0
    kw_offs = cin_offs = None
    dims = None
    n_pairs_total = 0

    for si in samples:
        try:
            trace = load_trace(arch, network, layer, si)
        except FileNotFoundError:
            print(f"    [warn] missing sample {si}; skipped", flush=True)
            continue
        if not trace.stream:
            print(f"    [warn] empty stream sample {si}; skipped", flush=True)
            continue
        if dims is None:
            dims = trace.dims
            kw_offs = kw_offsets(dims["KH"], dims["KW"])
            cin_offs = cin_offsets(dims["CIN"])

        kwp, kwu, cinp, cinu = collect_pairs(trace, kw_offs, cin_offs)
        kw_unres_tot += kwu
        cin_unres_tot += cinu

        # Single BIT sweep for BOTH locality types over this sample's stream.
        combined = kwp + cinp
        n_pairs_total += len(combined) + kwu + cinu
        if combined:
            dc = dc_bit_sweep(trace.stream, combined)
            fold_counts(kw_counts, dc[:len(kwp)])
            fold_counts(cin_counts, dc[len(kwp):])

    degenerate_kw = bool(kw_offs is not None and len(kw_offs) == 0)
    entries = {}
    for locality, counts, unres, offs in (
        ("kw", kw_counts, kw_unres_tot, kw_offs),
        ("cin", cin_counts, cin_unres_tot, cin_offs),
    ):
        vals, cnts = hist_arrays(counts)
        n_resolved = int(cnts.sum()) if cnts.size else 0
        skipped = None
        if locality == "kw" and degenerate_kw:
            skipped = "1x1 kernel (KH=KW=1): N1 empty/degenerate"
        entry = {
            "arch": arch, "network": network, "layer": layer,
            "locality": locality,
            "n_offsets": (len(offs) if offs is not None else 0),
            "n_resolved": n_resolved,
            "n_unresolved": int(unres),
            "p90": None, "n_below_p90": 0,
            "skipped": skipped,
            "dims": ({k: dims[k] for k in ("KH", "KW", "CIN", "COUT")}
                     if dims else None),
        }
        if skipped is None and n_resolved > 0:
            p90 = percentile_from_hist(vals, cnts, 90.0)
            entry["p90"] = float(p90)
            entry["n_below_p90"] = below_count(vals, cnts, p90)
            if make_plots:
                sub = OUT_DIR / network / arch
                sub.mkdir(parents=True, exist_ok=True)
                out_path = sub / f"{layer}_{locality}.pdf"
                plot_distribution(vals, cnts, p90, n_resolved, int(unres),
                                  arch, network, layer, locality, out_path)
                entry["figure"] = str(out_path)
        entries[locality] = entry
    return entries, n_pairs_total


# -- main ------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archs", nargs="+", default=ARCHS)
    ap.add_argument("--networks", nargs="+", default=NETWORKS)
    ap.add_argument("--layers", nargs="+", default=None,
                    help="restrict to these layer names (default: all)")
    ap.add_argument("--samples", type=int, nargs="+", default=None,
                    help="sample indices (default: 0..99)")
    ap.add_argument("--time-probe", action="store_true",
                    help="print per-sample timing and do not write the manifest")
    args = ap.parse_args()

    samples = args.samples if args.samples is not None else list(range(N_SAMPLES))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {}
    t_start = time.time()
    total_pairs = 0
    for network in args.networks:
        for arch in args.archs:
            layers = args.layers or list_layers(arch, network)
            for layer in layers:
                t0 = time.time()
                entries, npairs = process_layer(
                    arch, network, layer, samples,
                    make_plots=not args.time_probe)
                total_pairs += npairs
                dt = time.time() - t0
                kw, cin = entries["kw"], entries["cin"]
                print(
                    f"[{network}/{arch}/{layer}] {dt:.1f}s  "
                    f"kw(res={kw['n_resolved']:,} unres={kw['n_unresolved']:,} "
                    f"p90={kw['p90']}{' SKIP' if kw['skipped'] else ''})  "
                    f"cin(res={cin['n_resolved']:,} unres={cin['n_unresolved']:,} "
                    f"p90={cin['p90']})",
                    flush=True)
                manifest[f"{network}/{arch}/{layer}"] = entries

    elapsed = time.time() - t_start
    print(f"\nTOTAL: {elapsed:.1f}s, ~{total_pairs:,} pairs "
          f"(incl. unresolved) over {len(manifest)} layer-entries", flush=True)

    if not args.time_probe:
        with open(MANIFEST, "w") as fh:
            json.dump(manifest, fh, indent=2)
        print(f"manifest -> {MANIFEST}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
