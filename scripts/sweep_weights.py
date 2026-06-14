#!/usr/bin/env python3
"""Temporary sweep: find (w_u, w_tr, w_dl) satisfying winner constraints across
the arch × workload space used by similarity_probe.

Arch space (8 configs) — fixed L1=16 kb, PE=64; sweep:
    nodes  ∈ {16, 1024}
    gb     ∈ {64, 4096} kb
    split  ∈ {w24_p4_v4, w30_p1_v1}

Workload space (12 configs) — 2 representative layers × 6 T values:
    layers ∈ {resnet19/conv1 (shallow), vgg16/conv5_3 (deep)}
    T      ∈ {4, 8, 16, 32, 64, 128}

Winner constraints:
  1. Dl_winner  <= (1 + slack) * min_mode(Dl)     [default slack = 5%]
  2. Tr_winner  == min_mode(Tr)

Strategy:
  Phase 1 – Solve: for each (arch, workload) pair solve every TrafficMode,
             save raw metrics to a JSONL checkpoint.  Supports resume.
  Phase 2 – Search: grid-search (w_u, w_dl) with w_tr=1 fixed; find which
             combos satisfy both constraints across the most pairs.

Arch configs are built in-memory from the same parameters as the sweep YAML
generator; no pre-generated files are needed.  Workloads are loaded from the
existing per-layer YAMLs under configs/workloads/.

Usage (from project root, in cosa_snn env):
    python scripts/sweep_weights.py                   # all 96 pairs, serial
    python scripts/sweep_weights.py --jobs 4          # 4 parallel workers
    python scripts/sweep_weights.py --time-limit 60   # 60 s per Gurobi solve
    python scripts/sweep_weights.py --search-only     # skip Phase 1

Outputs:
    outputs/weight_sweep/metrics.jsonl       checkpoint
    outputs/weight_sweep/weight_results.json summary
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ---------------------------------------------------------------------------
# Constants matching similarity_probe.py
# ---------------------------------------------------------------------------

FIXED_L1_KB = 16
FIXED_PE    = 64

ARCH_NODES  = [16, 1024]
ARCH_GB_KB  = [64, 4096]
ARCH_SPLITS = [
    ("w24_p4_v4", {"weight": 24, "psum": 4,  "vmem": 4}),
    ("w30_p1_v1", {"weight": 30, "psum": 1,  "vmem": 1}),
]
TOTAL_BANKS = 32

LAYERS = [
    ("resnet19", "conv1"),       # shallow
    ("vgg16",    "conv5_3"),     # deep
]
T_VALUES = [4, 8, 16, 32, 64, 128]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

WORKLOAD_ROOT = PROJECT_ROOT / "configs" / "workloads"
MAPSPACE_PATH = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
OUT_DIR       = PROJECT_ROOT / "outputs" / "weight_sweep"

LATENCY_SLACK = 0.05
TRAFFIC_SLACK = 0.05
GRID_STEPS    = 30
W_MIN, W_MAX  = 1e-3, 1e3

# CoSA's original default weights (w_compute=10, w_traffic=1, w_utilization=0.1)
COSA_REF_WEIGHTS = (0.1, 1.0, 10.0)   # (w_u, w_tr, w_dl)

DEFAULT_PE_REGISTER_ENTRIES   = {"weight": 128, "psum": 128, "vmem": 256}
DEFAULT_PE_REGISTER_BITWIDTHS = {"weight": 8,   "psum": 16,  "vmem": 32}
DEFAULT_ARCH_BITWIDTHS        = {"BW_WEIGHT": 8, "BW_PSUM": 16, "BW_VMEM": 32}

# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def _split_bytes(total_bytes: int, split: Dict[str, int]) -> Dict[str, int]:
    return {k: total_bytes * v // TOTAL_BANKS for k, v in split.items()}


def _build_arch_dict(nodes: int, gb_kb: int, split: Dict[str, int]) -> Dict:
    l1_bytes = FIXED_L1_KB * 1024
    gb_bytes = gb_kb * 1024
    return {
        "arch": {
            "bitwidths": DEFAULT_ARCH_BITWIDTHS,
            "storage": [
                {
                    "name": "NodeLevel",
                    "instances": nodes,
                    "pe": {
                        "num_pes": FIXED_PE,
                        "registers": {
                            "entries": DEFAULT_PE_REGISTER_ENTRIES,
                            "bitwidths": DEFAULT_PE_REGISTER_BITWIDTHS,
                        },
                    },
                    "local_buffer": {"entries": _split_bytes(l1_bytes, split)},
                },
                {
                    "name": "NoCLevel",
                    "entries": _split_bytes(gb_bytes, split),
                    "instances": 1,
                },
                {"name": "OffChip", "instances": 1},
            ],
        }
    }


def all_arch_configs() -> List[Tuple[str, Dict]]:
    """8 arch configs matching similarity_probe's sweep axes."""
    configs = []
    for nodes in ARCH_NODES:
        for gb_kb in ARCH_GB_KB:
            for split_name, split in ARCH_SPLITS:
                key = f"nodes{nodes}_gb{gb_kb}kb_{split_name}"
                configs.append((key, _build_arch_dict(nodes, gb_kb, split)))
    return configs


def all_workload_configs() -> List[Tuple[str, Dict]]:
    """12 workload configs: 2 layers × 6 T values."""
    configs = []
    for network, layer in LAYERS:
        src = WORKLOAD_ROOT / network / f"{layer}.yaml"
        with open(src) as f:
            raw = yaml.safe_load(f)
        base_dims = {k: v for k, v in raw["problem"].items() if k not in ("T", "shape")}
        for t in T_VALUES:
            key = f"{network}_{layer}_T{t}"
            configs.append((key, {**base_dims, "T": t, "shape": "snn-layer"}))
    return configs


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _worker(task: Tuple) -> Dict[str, Any]:
    arch_key, arch_dict, wl_key, wl_dict, mapspace_str, time_limit, mip_gap = task

    from snn_cosa.solver import TrafficMode, solve_schedule

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as af:
        yaml.safe_dump(arch_dict, af)
        arch_tmp = af.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as wf:
        yaml.safe_dump({"problem": wl_dict}, wf)
        wl_tmp = wf.name

    mapspace = Path(mapspace_str) if mapspace_str and Path(mapspace_str).exists() else None

    modes_out = []
    try:
        for mode in TrafficMode:
            result = solve_schedule(
                layer_path=wl_tmp,
                arch_path=arch_tmp,
                mapspace_path=mapspace,
                time_limit=time_limit,
                mip_gap=mip_gap,
                output_flag=False,
                traffic_mode=mode,
                return_metrics=True,
            )
            ok = result["has_solution"] and result.get("metrics")
            entry: Dict[str, Any] = {"mode": mode.value, "feasible": ok}
            if ok:
                m    = result["metrics"]
                util = m["util"]
                sp   = m["spatial_cost"]
                tt   = m["temporal_traffic"]
                entry["dl"]       = m["delay"]
                entry["tr_sum"]   = sum(util[v] * sp[v] * tt[v] for v in util)
                entry["util_sum"] = sum(util.values())
            modes_out.append(entry)
    finally:
        os.unlink(arch_tmp)
        os.unlink(wl_tmp)

    return {"arch_key": arch_key, "wl_key": wl_key, "modes": modes_out}


# ---------------------------------------------------------------------------
# Phase 1: solve all pairs
# ---------------------------------------------------------------------------

def phase1_solve(
    arch_configs: List[Tuple[str, Dict]],
    wl_configs:   List[Tuple[str, Dict]],
    checkpoint:   Path,
    jobs:         int,
    time_limit:   Optional[float],
    mip_gap:      Optional[float],
) -> None:
    done: set = set()
    if checkpoint.exists():
        with open(checkpoint) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if "error" not in rec:
                        done.add((rec["arch_key"], rec["wl_key"]))
                except Exception:
                    pass

    tasks = [
        (ak, ad, wk, wd, str(MAPSPACE_PATH), time_limit, mip_gap)
        for ak, ad in arch_configs
        for wk, wd in wl_configs
        if (ak, wk) not in done
    ]

    total     = len(arch_configs) * len(wl_configs)
    remaining = len(tasks)
    print(f"\nPhase 1: {total} total pairs, {total - remaining} already done, "
          f"{remaining} remaining")
    if not remaining:
        print("  All pairs already solved. Skipping Phase 1.")
        return

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    completed = total - remaining
    start = time.time()

    with open(checkpoint, "a") as out_f:
        if jobs == 1:
            for task in tasks:
                rec = _worker(task)
                out_f.write(json.dumps(rec) + "\n")
                out_f.flush()
                completed += 1
                _print_progress(completed, total, start)
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                futures = {pool.submit(_worker, t): t for t in tasks}
                for fut in as_completed(futures):
                    try:
                        rec = fut.result()
                    except Exception as e:
                        t = futures[fut]
                        rec = {"arch_key": t[0], "wl_key": t[2], "modes": [], "error": str(e)}
                    out_f.write(json.dumps(rec) + "\n")
                    out_f.flush()
                    completed += 1
                    _print_progress(completed, total, start)

    print(f"\nPhase 1 done in {(time.time()-start)/60:.1f} min")


def _print_progress(done: int, total: int, start: float) -> None:
    elapsed = time.time() - start
    rate    = done / elapsed if elapsed > 0 else 0
    eta     = (total - done) / rate if rate > 0 else float("inf")
    print(
        f"\r  [{done}/{total}] {100*done/total:5.1f}%  "
        f"{rate:.2f} pairs/s  ETA {eta:.0f}s  ",
        end="", flush=True,
    )


# ---------------------------------------------------------------------------
# Phase 2: weight grid search
# ---------------------------------------------------------------------------

def _score(dl, tr_sum, util_sum, w_u, w_tr, w_dl) -> float:
    return w_u * util_sum + w_tr * tr_sum + w_dl * dl


def _eval_weights(
    constrained: List[Dict],
    w_u: float,
    w_tr: float,
    w_dl: float,
) -> Dict[str, Any]:
    """Return pass statistics for a specific (w_u, w_tr, w_dl) triple."""
    n = len(constrained)
    failing_a, failing_b = [], []
    for pair in constrained:
        modes         = pair["modes"]
        valid_winners = pair["valid_winners"]
        scores = [(_score(m["dl"], m["tr_sum"], m["util_sum"], w_u, w_tr, w_dl), m)
                  for m in modes]
        winner = min(scores, key=lambda x: x[0])[1]
        if winner["mode"] not in valid_winners:
            (failing_a if pair["tier"] == "A" else failing_b).append(pair)
    pass_count = n - len(failing_a) - len(failing_b)
    return {
        "pass_count": pass_count,
        "pass_pct":   100 * pass_count / n if n else 0.0,
        "failing_a":  failing_a,
        "failing_b":  failing_b,
    }


def _report_weight_check(
    constrained: List[Dict],
    w_u: float,
    w_tr: float,
    w_dl: float,
    lat_slack: float,
    tr_slack:  float,
    label: str = "",
) -> None:
    n   = len(constrained)
    res = _eval_weights(constrained, w_u, w_tr, w_dl)
    failing_a = res["failing_a"]
    failing_b = res["failing_b"]
    total_failing = len(failing_a) + len(failing_b)

    print(f"\n=== Weight check: {label} ===")
    print(f"  Pass rate: {res['pass_count']}/{n} ({res['pass_pct']:.1f}%)")
    print(f"  [1] latency within {lat_slack*100:.0f}%:         applied to all pairs")
    print(f"  [2] exact min traffic (Tier A): "
          f"{'PASS' if not failing_a else f'FAIL on {len(failing_a)} pairs'}")
    print(f"  [3] traffic within {tr_slack*100:.0f}% (Tier B): "
          f"{'PASS' if not failing_b else f'FAIL on {len(failing_b)} pairs'}")
    if total_failing:
        print(f"  Failing pairs (up to 10):")
        for p in (failing_a + failing_b)[:10]:
            print(f"    [{p['tier']}] arch={p['arch_key']}  wl={p['wl_key']}"
                  f"  valid={sorted(p['valid_winners'])}")


def phase2_search(
    checkpoint:   Path,
    results_path: Path,
    lat_slack:    float,
    tr_slack:     float,
    steps:        int,
) -> None:
    """Three-constraint weight search matching find_weights.py logic.

    For each pair, determine valid winner modes via two tiers:
      Tier A (preferred): mode satisfies [1] latency + [2] exact min traffic
      Tier B (fallback):  mode satisfies [1] latency + [3] traffic within tr_slack

    The grid point passes for a pair if the scoring winner is in that pair's
    valid winner set.  Pairs with no valid winner in either tier are skipped.
    """
    print(f"\nPhase 2: loading metrics from {checkpoint} ...")

    pairs_data: List[Dict] = []
    with open(checkpoint) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            feasible = [m for m in rec.get("modes", []) if m.get("feasible")]
            if len(feasible) < 2:
                continue
            pairs_data.append({
                "arch_key": rec["arch_key"],
                "wl_key":   rec["wl_key"],
                "modes":    feasible,
            })

    print(f"  {len(pairs_data)} pairs with >=2 feasible modes")

    # Classify each pair into a tier and build its valid-winner set
    constrained: List[Dict] = []
    n_tier_a, n_tier_b, n_no_winner = 0, 0, 0

    for pair in pairs_data:
        modes   = pair["modes"]
        best_dl = min(m["dl"]     for m in modes)
        best_tr = min(m["tr_sum"] for m in modes)

        tier_a = {m["mode"] for m in modes
                  if m["dl"] <= (1 + lat_slack) * best_dl
                  and m["tr_sum"] == best_tr}
        tier_b = {m["mode"] for m in modes
                  if m["dl"] <= (1 + lat_slack) * best_dl
                  and m["tr_sum"] <= (1 + tr_slack) * best_tr}

        if tier_a:
            valid_winners = tier_a
            tier          = "A"
            n_tier_a     += 1
        elif tier_b:
            valid_winners = tier_b
            tier          = "B"
            n_tier_b     += 1
        else:
            n_no_winner += 1
            continue

        constrained.append({
            "arch_key":     pair["arch_key"],
            "wl_key":       pair["wl_key"],
            "modes":        modes,
            "best_dl":      best_dl,
            "best_tr":      best_tr,
            "valid_winners": valid_winners,
            "tier":         tier,
        })

    print(f"  {n_tier_a} pairs → Tier A ([1]+[2] exact min traffic)")
    print(f"  {n_tier_b} pairs → Tier B ([1]+[3] traffic within {tr_slack*100:.0f}% of min)")
    print(f"  {n_no_winner} pairs skipped (no mode satisfies even relaxed constraints)")
    print(f"  {len(constrained)} pairs used for weight search")

    if not constrained:
        print("  Nothing to search. Try increasing --latency-slack or --traffic-slack.")
        return

    # Grid search: fix w_tr=1, sweep (w_u, w_dl) in log-space
    grid        = np.logspace(np.log10(W_MIN), np.log10(W_MAX), steps)
    n           = len(constrained)
    pass_counts = np.zeros((steps, steps), dtype=np.int32)

    for pair in constrained:
        modes         = pair["modes"]
        valid_winners = pair["valid_winners"]
        for i_u, w_u in enumerate(grid):
            for i_dl, w_dl in enumerate(grid):
                scores = [(_score(m["dl"], m["tr_sum"], m["util_sum"], w_u, 1.0, w_dl), m)
                          for m in modes]
                winner = min(scores, key=lambda x: x[0])[1]
                if winner["mode"] in valid_winners:
                    pass_counts[i_u, i_dl] += 1

    best_count = int(pass_counts.max())
    best_pct   = 100 * best_count / n
    best_idx   = np.argwhere(pass_counts == best_count)
    best_w_u   = [grid[i[0]] for i in best_idx]
    best_w_dl  = [grid[i[1]] for i in best_idx]

    rec_w_u  = float(np.exp(np.mean(np.log(best_w_u))))
    rec_w_dl = float(np.exp(np.mean(np.log(best_w_dl))))
    rec_w_tr = 1.0

    print(f"\n=== Weight search results ===")
    print(f"  Grid: {steps}x{steps}, w_tr=1 fixed")
    print(f"  Best pass rate: {best_count}/{n} pairs ({best_pct:.1f}%)")
    print(f"  w_u  range at best: [{min(best_w_u):.4g}, {max(best_w_u):.4g}]")
    print(f"  w_dl range at best: [{min(best_w_dl):.4g}, {max(best_w_dl):.4g}]")
    print(f"\n=== Recommended weights ===")
    print(f"  w_u  = {rec_w_u:.4g}")
    print(f"  w_tr = {rec_w_tr:.4g}")
    print(f"  w_dl = {rec_w_dl:.4g}")

    # Verify recommended weights
    _report_weight_check(constrained, rec_w_u, rec_w_tr, rec_w_dl,
                         lat_slack, tr_slack,
                         label=f"Recommended  (w_u={rec_w_u:.4g}, w_tr={rec_w_tr:.4g}, w_dl={rec_w_dl:.4g})")

    # --- Reference-weight check (CoSA defaults) ---
    ref_w_u, ref_w_tr, ref_w_dl = COSA_REF_WEIGHTS
    _report_weight_check(constrained, ref_w_u, ref_w_tr, ref_w_dl,
                         lat_slack, tr_slack,
                         label=f"CoSA defaults  (w_u={ref_w_u}, w_tr={ref_w_tr}, w_dl={ref_w_dl})")

    # Save
    cosa_check = _eval_weights(constrained, ref_w_u, ref_w_tr, ref_w_dl)
    results = {
        "n_pairs_with_2plus_modes": len(pairs_data),
        "n_tier_a":                 n_tier_a,
        "n_tier_b":                 n_tier_b,
        "n_no_winner":              n_no_winner,
        "n_constrained_pairs":      n,
        "best_pass_count":          best_count,
        "best_pass_pct":            best_pct,
        "w_u_range":                [float(min(best_w_u)), float(max(best_w_u))],
        "w_dl_range":               [float(min(best_w_dl)), float(max(best_w_dl))],
        "recommended":              {"w_u": rec_w_u, "w_tr": rec_w_tr, "w_dl": rec_w_dl},
        "cosa_defaults_check":      {
            "w_u": ref_w_u, "w_tr": ref_w_tr, "w_dl": ref_w_dl,
            "pass_count": cosa_check["pass_count"],
            "pass_pct":   cosa_check["pass_pct"],
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results saved to {results_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs",         type=int,   default=1,
                        help="parallel workers (default: 1)")
    parser.add_argument("--time-limit",   type=float, default=None,
                        help="Gurobi time limit per mode in seconds")
    parser.add_argument("--mip-gap",      type=float, default=0.001)
    parser.add_argument("--latency-slack", type=float, default=LATENCY_SLACK,
                        help="latency overhead allowed (default 0.05 = 5%%)")
    parser.add_argument("--traffic-slack", type=float, default=TRAFFIC_SLACK,
                        help="traffic overhead for Tier B fallback (default 0.05 = 5%%)")
    parser.add_argument("--steps",        type=int,   default=GRID_STEPS,
                        help="grid points per weight axis (default 30)")
    parser.add_argument("--search-only",  action="store_true",
                        help="skip Phase 1, run weight search on existing checkpoint")
    parser.add_argument("--out-dir",      default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir      = Path(args.out_dir)
    checkpoint   = out_dir / "metrics.jsonl"
    results_path = out_dir / "weight_results.json"

    arch_configs = all_arch_configs()
    wl_configs   = all_workload_configs()

    print(f"Arch configs:     {len(arch_configs)}  "
          f"(nodes={ARCH_NODES}, gb={ARCH_GB_KB}kb, splits={[s for s,_ in ARCH_SPLITS]})")
    print(f"Workload configs: {len(wl_configs)}  "
          f"(layers={[f'{n}/{l}' for n,l in LAYERS]}, T={T_VALUES})")
    print(f"Total pairs:      {len(arch_configs)*len(wl_configs)}  "
          f"(x8 modes = {len(arch_configs)*len(wl_configs)*8} Gurobi solves)")
    print(f"Checkpoint:       {checkpoint}")

    if not args.search_only:
        phase1_solve(arch_configs, wl_configs, checkpoint,
                     args.jobs, args.time_limit, args.mip_gap)

    if checkpoint.exists():
        phase2_search(checkpoint, results_path, args.latency_slack, args.traffic_slack, args.steps)
    else:
        print("\nNo checkpoint found. Run Phase 1 first (remove --search-only).")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
