#!/usr/bin/env python3
"""Milestone 3 - distinct-address distance D_C (plan Sec 3, Sec 4.3, Sec 8).

Adds the plan's PRIMARY metric D_C alongside the milestone-2 companion D_A, on
the SAME Analysis-1 (t, s) pairs milestone 2 already forms. No pairing or parsing
is re-derived: this reuses walking_skeleton.collect_da for the pairs (which reuses
trace_io for parsing/width) and distinct_distance for the BIT sweep.

Three parts:

  A. Sec 8 known-answer check: on a toy trace (length <= 1e3), the BIT-sweep D_C
     must match the brute-force len(set(a[t+1:s+1])) for EVERY pair.

  B. Real-layer pairing: take milestone 2's resolved (t, s) pairs on the same
     offset/slice, compute D_C, assert the Sec 8 invariant D_A >= D_C per pair,
     and report D_C percentiles beside D_A.

  C. One ECDF overlaying D_A and D_C for that offset/slice (extends the milestone-2
     figure), rendered to outputs/locality_analysis/ (NOT the heatmaps subdir).

Usage (from project root):
    conda run -n base python scripts/locality_analysis/distinct_skeleton.py
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.distinct_distance import dc_bit_sweep, dc_bruteforce  # noqa: E402
from locality_analysis.trace_io import load_trace  # noqa: E402
from locality_analysis.walking_skeleton import KW_OFFSET, OUT_DIR, collect_da  # noqa: E402


# -- A. Sec 8 known-answer check: BIT sweep vs brute force ----------------------

def check_bruteforce(n: int = 200, seed: int = 0) -> tuple[bool, str]:
    """Every (t, s) pair, t < s, on a toy trace: BIT-sweep D_C == brute force."""
    rng = random.Random(seed)
    # Small alphabet so intervals contain plenty of repeats (exercises the
    # decrement-then-increment path); coords are (kh,kw,cin,cs,ce) 5-tuples like
    # the real stream, so equality/hashing matches the real code path.
    alphabet = [tuple(rng.randrange(4) for _ in range(5)) for _ in range(12)]
    stream = [rng.choice(alphabet) for _ in range(n)]
    pairs = [(t, s) for t in range(n) for s in range(t + 1, n)]
    got = dc_bit_sweep(stream, pairs)
    mismatches = 0
    for (t, s), dc in zip(pairs, got):
        if dc != dc_bruteforce(stream, t, s):
            mismatches += 1
    ok = mismatches == 0
    detail = (f"toy trace n={n}, {len(pairs)} pairs (all t<s), "
              f"{len(set(stream))} distinct coords; mismatches: {mismatches}")
    return ok, detail


# -- C. Overlaid D_A / D_C ECDF -------------------------------------------------

def _ecdf(vals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xs = np.sort(vals)
    ys = np.arange(1, len(xs) + 1) / len(xs)
    return xs, ys


def plot_da_dc_ecdf(trace, res: dict, dc: np.ndarray) -> Path:
    da = res["da"]
    xa, ya = _ecdf(da)
    xc, yc = _ecdf(dc)
    med_a, p90_a = np.percentile(da, [50, 90])
    med_c, p90_c = np.percentile(dc, [50, 90])

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.step(xa, ya, where="post", color="#4c78a8", lw=1.6,
            label=f"D_A (raw gap)  median={med_a:.0f}")
    ax.step(xc, yc, where="post", color="#54a24b", lw=1.6,
            label=f"D_C (distinct)  median={med_c:.0f}")
    ax.axvline(med_a, color="#4c78a8", ls="--", lw=0.8, alpha=0.7)
    ax.axvline(med_c, color="#54a24b", ls="--", lw=0.8, alpha=0.7)
    ax.set_xscale("log")
    ax.set_xlabel("distance (access counts): D_A = s - t  vs  D_C = distinct coords in (t,s]")
    ax.set_ylabel("empirical CDF")
    ax.set_ylim(0, 1.02)
    ax.set_title(
        f"D_A vs D_C ECDF - {trace.arch}/{trace.layer}\n"
        f"Analysis 1, offset (Dkh,Dkw)={res['offset']}, "
        f"pinned cin0={res['slice'][0]} cr0={res['slice'][1]}  "
        f"(resolved {res['resolved']}/{res['anchors']})",
        fontsize=9,
    )
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()

    out = OUT_DIR / (f"da_dc_ecdf_{trace.arch}_{trace.layer}"
                     f"_offset{KW_OFFSET[0]}-{KW_OFFSET[1]}.pdf")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# -- main -----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", default="vgg16_T4_all")
    parser.add_argument("--arch", default="gustavsnn")
    parser.add_argument("--layer", default="layer_01_features_3")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--toy-n", type=int, default=200,
                        help="toy-trace length for the Sec 8 brute-force check")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    # -- A. Sec 8 brute-force known-answer check --------------------------------
    print("\n=== Milestone 3A: Sec 8 brute-force distinct-count check ===")
    ok_bf, detail_bf = check_bruteforce(n=args.toy_n)
    print(f"{'PASS' if ok_bf else 'FAIL'}  BIT sweep == len(set(a[t+1:s+1]))")
    print(f"        {detail_bf}")
    results.append(ok_bf)

    # -- B. Real-layer D_C on milestone-2 pairs ---------------------------------
    print("\n=== Milestone 3B: D_C on milestone-2 Analysis-1 pairs ===")
    trace = load_trace(args.arch, args.network, args.layer, args.sample)
    res = collect_da(trace)  # reuse milestone-2 pairing (D_A + (t,s) pairs)
    print(f"layer: {trace.arch}/{trace.layer} sample {trace.sample_idx}")
    print(f"pinned slice cin0={res['slice'][0]} cr0={res['slice'][1]}, "
          f"offset (Dkh,Dkw)={res['offset']}")
    print(f"anchors={res['anchors']} resolved={res['resolved']} "
          f"unresolved={res['unresolved']}")
    if not res["resolved"]:
        print("no resolved pairs; nothing to do")
        return 0 if all(results) else 1

    dc = np.array(dc_bit_sweep(trace.stream, res["pairs"]))
    da = res["da"]

    # Sec 8 invariant: D_A >= D_C for every resolved pair.
    n_viol = int(np.sum(da < dc))
    ok_inv = n_viol == 0
    print(f"{'PASS' if ok_inv else 'FAIL'}  invariant D_A >= D_C "
          f"(violations: {n_viol}/{len(dc)})")
    results.append(ok_inv)

    pa = np.percentile(da, [50, 90, 99])
    pc = np.percentile(dc, [50, 90, 99])
    print(f"  D_A: median={pa[0]:.0f} p90={pa[1]:.0f} p99={pa[2]:.0f} "
          f"(min={da.min()} max={da.max()})")
    print(f"  D_C: median={pc[0]:.0f} p90={pc[1]:.0f} p99={pc[2]:.0f} "
          f"(min={dc.min()} max={dc.max()})")

    # -- C. Overlaid ECDF -------------------------------------------------------
    ecdf_path = plot_da_dc_ecdf(trace, res, dc)
    print(f"\n=== Milestone 3C: overlaid D_A/D_C ECDF ===")
    print(f"ECDF -> {ecdf_path}")

    all_ok = all(results)
    print(f"\n=== {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'} ===\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
