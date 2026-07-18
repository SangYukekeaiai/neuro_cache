#!/usr/bin/env python3
"""Temporary script: find (w_u, w_tr, w_dl) satisfying the three winner constraints.

Target constraints (see enumerator.py):
  1. Latency:  Dl_winner <= 1.05 * min_mode(Dl)
  2. Traffic:  Tr_winner == min_mode(Tr)   [Tr = sum_v Util_v * SpatialCost_v * TemporalTraffic_v]
  3. Relaxed:  If constraint 2 cannot be satisfied, Tr_winner <= 1.05 * min_mode(Tr)

A "valid winner" is any mode satisfying both active constraints simultaneously.
Constraint 2 is preferred (exact min traffic); constraint 3 is the fallback when
no weight combo can produce a winner with exact min traffic.

Strategy:
  - Solve all TrafficModes once and collect raw metrics (Dl, Tr_sum, Util_sum).
  - Determine which modes are "valid winners" under constraints 1+2, then 1+3.
  - Pre-check: at least one valid winner must exist; abort if none do.
  - Grid-search (w_u, w_dl) with w_tr=1 fixed: a grid point passes if the
    scoring-function winner is a valid winner.
  - Report valid ranges and recommend a single clean triple.

Defaults match similarity_probe: shallow=resnet19/conv1, deep=vgg16/conv5_3,
arch from configs/arch/sweep/ (nodes=16, gb=64kb, l1=16kb, pe=64, w30_p1_v1).

Usage (from project root):
    python scripts/find_weights.py
    python scripts/find_weights.py --layer configs/workloads/vgg16/conv5_3.yaml
    python scripts/find_weights.py --arch configs/arch/sweep/nodes_1024/gb_4096kb/l1_16kb/pe_64/split_w24_p4_v4.yaml
    python scripts/find_weights.py --latency-slack 0.05 --traffic-slack 0.05 --steps 40
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from snn_cosa.mip_solver.solve import TrafficMode, solve_schedule  # noqa: E402


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ARCH     = PROJECT_ROOT / "configs/arch/sweep/nodes_16/gb_64kb/l1_16kb/pe_64/split_w30_p1_v1.yaml"
DEFAULT_LAYER    = PROJECT_ROOT / "configs/workloads/resnet19/conv1.yaml"
DEFAULT_MAPSPACE = PROJECT_ROOT / "configs/mapspace/mapspace.yaml"

LATENCY_SLACK = 0.05
TRAFFIC_SLACK = 0.05
GRID_STEPS    = 30
W_MIN, W_MAX  = 1e-3, 1e3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solve_all_modes(
    layer: Path,
    arch: Path,
    mapspace: Optional[Path],
    time_limit: Optional[float],
    mip_gap: Optional[float],
) -> List[Dict[str, Any]]:
    candidates = []
    for mode in TrafficMode:
        print(f"  solving mode={mode.value} ...", end="", flush=True)
        result = solve_schedule(
            layer_path=layer,
            arch_path=arch,
            mapspace_path=mapspace,
            time_limit=time_limit,
            mip_gap=mip_gap,
            output_flag=False,
            traffic_mode=mode,
            return_metrics=True,
        )
        ok = result["has_solution"] and result.get("metrics")
        print(f" {'OK' if ok else 'INFEASIBLE'}")

        m = result.get("metrics") or {}
        tr_sum: Optional[float] = None
        if ok:
            util   = m["util"]
            sp     = m["spatial_cost"]
            tt     = m["temporal_traffic"]
            tr_sum = sum(util[v] * sp[v] * tt[v] for v in util)

        candidates.append({
            "mode":     mode.value,
            "feasible": ok,
            "dl":       m.get("delay") if ok else None,
            "tr_sum":   tr_sum,
            "util_sum": sum(m["util"].values()) if ok else None,
        })
    return candidates


def comparison_score(c: Dict, w_u: float, w_tr: float, w_dl: float) -> float:
    return w_u * c["util_sum"] + w_tr * c["tr_sum"] + w_dl * c["dl"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch",          default=str(DEFAULT_ARCH))
    parser.add_argument("--layer",         default=str(DEFAULT_LAYER))
    parser.add_argument("--mapspace",      default=str(DEFAULT_MAPSPACE))
    parser.add_argument("--latency-slack", type=float, default=LATENCY_SLACK,
                        help="max latency overhead above best mode (default 0.05 = 5%%)")
    parser.add_argument("--traffic-slack", type=float, default=TRAFFIC_SLACK,
                        help="max traffic overhead for fallback constraint 3 (default 0.05 = 5%%)")
    parser.add_argument("--steps",         type=int,   default=GRID_STEPS,
                        help="grid points per weight axis in log-space search")
    parser.add_argument("--time-limit",    type=float, default=None)
    parser.add_argument("--mip-gap",       type=float, default=None)
    args = parser.parse_args()

    arch     = Path(args.arch)
    layer    = Path(args.layer)
    mapspace = Path(args.mapspace) if Path(args.mapspace).exists() else None
    lat_sl   = args.latency_slack
    tr_sl    = args.traffic_slack

    print(f"\narch:     {arch}")
    print(f"layer:    {layer}")
    print(f"mapspace: {mapspace}\n")

    # ── Step 1: solve all modes ──────────────────────────────────────────────
    print("=== Solving all TrafficModes ===")
    candidates = solve_all_modes(layer, arch, mapspace, args.time_limit, args.mip_gap)

    feasible = [c for c in candidates if c["feasible"]]
    if not feasible:
        print("ERROR: no feasible mode found.")
        return 1

    # ── Step 2: compute bests and classify valid winners ─────────────────────
    best_dl = min(c["dl"]     for c in feasible)
    best_tr = min(c["tr_sum"] for c in feasible)

    # Constraint 1: latency within slack of best
    def passes_latency(c):
        return c["dl"] <= (1 + lat_sl) * best_dl

    # Constraint 2: exact minimum traffic
    def passes_exact_traffic(c):
        return c["tr_sum"] == best_tr

    # Constraint 3 (fallback): traffic within slack of best
    def passes_relaxed_traffic(c):
        return c["tr_sum"] <= (1 + tr_sl) * best_tr

    print(f"\n=== Feasible modes ===")
    print(f"{'mode':<25} {'Dl':>12} {'Tr_sum':>16} {'Util_sum':>12}  constraints")
    print("-" * 80)
    for c in feasible:
        tags = []
        if c["dl"]     == best_dl: tags.append("min-Dl")
        if c["tr_sum"] == best_tr: tags.append("min-Tr")
        c1 = passes_latency(c)
        c2 = passes_exact_traffic(c)
        c3 = passes_relaxed_traffic(c)
        ck = f"[1]{'✓' if c1 else '✗'} [2]{'✓' if c2 else '✗'} [3]{'✓' if c3 else '✗'}"
        tag_str = f"  ({', '.join(tags)})" if tags else ""
        print(f"{c['mode']:<25} {c['dl']:>12.3f} {c['tr_sum']:>16.3f} {c['util_sum']:>12.3f}"
              f"  {ck}{tag_str}")

    # Determine which constraint tier applies
    # Tier A: modes satisfying constraints 1 AND 2 (preferred)
    tier_a = [c for c in feasible if passes_latency(c) and passes_exact_traffic(c)]
    # Tier B: modes satisfying constraints 1 AND 3 (fallback)
    tier_b = [c for c in feasible if passes_latency(c) and passes_relaxed_traffic(c)]

    if tier_a:
        valid_winners = tier_a
        active_tier   = "A"
        print(f"\nActive constraints: [1] + [2] (exact min traffic)  — {len(tier_a)} valid winner(s)")
    elif tier_b:
        valid_winners = tier_b
        active_tier   = "B"
        print(f"\nConstraint [2] unachievable — falling back to [1] + [3] "
              f"(traffic within {tr_sl*100:.0f}% of min)  — {len(tier_b)} valid winner(s)")
    else:
        print(f"\nERROR: no mode satisfies even the relaxed constraints "
              f"([1] latency <={lat_sl*100:.0f}% + [3] traffic <={tr_sl*100:.0f}%).")
        return 1

    valid_winner_names = {c["mode"] for c in valid_winners}
    print(f"Valid winner(s): {sorted(valid_winner_names)}")

    # ── Step 3: grid search over (w_u, w_dl) ────────────────────────────────
    grid  = np.logspace(np.log10(W_MIN), np.log10(W_MAX), args.steps)
    valid: List[Tuple[float, float, float]] = []

    for w_u in grid:
        for w_dl in grid:
            w_tr   = 1.0
            scores = [(comparison_score(c, w_u, w_tr, w_dl), c) for c in feasible]
            winner = min(scores, key=lambda x: x[0])[1]
            if winner["mode"] in valid_winner_names:
                valid.append((w_u, w_tr, w_dl))

    print(f"\n=== Grid search (w_tr=1 fixed, steps={args.steps}) ===")
    print(f"Valid (w_u, w_dl) pairs: {len(valid)} / {args.steps**2}")

    if not valid:
        print("No valid weights found in grid. Try increasing --steps or widening W_MIN/W_MAX.")
        return 1

    w_u_vals  = [v[0] for v in valid]
    w_dl_vals = [v[2] for v in valid]
    print(f"  w_u  range: [{min(w_u_vals):.4g}, {max(w_u_vals):.4g}]")
    print(f"  w_dl range: [{min(w_dl_vals):.4g}, {max(w_dl_vals):.4g}]")

    # ── Step 4: recommend and verify ─────────────────────────────────────────
    rec_w_u  = float(np.exp(np.mean(np.log(w_u_vals))))
    rec_w_dl = float(np.exp(np.mean(np.log(w_dl_vals))))
    rec_w_tr = 1.0

    rec_scores = [(comparison_score(c, rec_w_u, rec_w_tr, rec_w_dl), c) for c in feasible]
    rec_scores.sort(key=lambda x: x[0])
    rec_winner = rec_scores[0][1]

    c1_pass = passes_latency(rec_winner)
    c2_pass = passes_exact_traffic(rec_winner)
    c3_pass = passes_relaxed_traffic(rec_winner)

    print(f"\n=== Recommended weights ===")
    print(f"  w_u  = {rec_w_u:.4g}")
    print(f"  w_tr = {rec_w_tr:.4g}")
    print(f"  w_dl = {rec_w_dl:.4g}")
    print(f"  -> winner: {rec_winner['mode']}")
    print(f"     Dl={rec_winner['dl']:.3f}  (best={best_dl:.3f}, "
          f"+{(rec_winner['dl']/best_dl-1)*100:.2f}%)")
    print(f"     Tr={rec_winner['tr_sum']:.3f}  (best={best_tr:.3f}, "
          f"+{(rec_winner['tr_sum']/best_tr-1)*100:.2f}%)")
    print(f"  [1] latency within {lat_sl*100:.0f}%:          {'PASS' if c1_pass else 'FAIL'}")
    print(f"  [2] traffic is exact minimum:    {'PASS' if c2_pass else 'FAIL'}")
    print(f"  [3] traffic within {tr_sl*100:.0f}% of min:  {'PASS' if c3_pass else 'FAIL'}")
    print(f"  Active tier: {active_tier}  ({'constraints 1+2' if active_tier=='A' else 'constraints 1+3'})")

    print(f"\n  Full ranking with recommended weights:")
    for score, c in rec_scores:
        tag = " <-- winner" if c["mode"] == rec_winner["mode"] else ""
        print(f"    {c['mode']:<25}  score={score:.4g}  "
              f"Dl={c['dl']:.3f}  Tr={c['tr_sum']:.3f}{tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
