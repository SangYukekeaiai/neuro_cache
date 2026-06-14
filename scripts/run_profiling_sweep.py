#!/usr/bin/env python3
"""Profiling sweep: unique workloads × fixed hardware config × T ∈ {4, 32, 128}.

Deduplicates all layers from resnet19, vgg16, resnet34, and resnet50 by their
shape tuple (KH, KW, CIN, COUT, HO, WO), yielding 35 unique workloads.

Fixed hardware config:
    nodes = 256,  L1 = 8 KB,  L2 = 256 KB,  split = w30:vmem1:psum1,  PE = 64

Each unique workload is profiled at T ∈ {4, 32, 128}.

Workload key format:  cin{CIN}_cout{COUT}_ho{HO}_wo{WO}_kh{KH}_kw{KW}_T{T}

Per-sample output:  outputs/profiling_sweep/{wl_key}.txt
Summary:            outputs/profiling_sweep/summary.txt

Already-solved pairs (txt file exists and is non-empty) are skipped
automatically — re-run the same command to resume.

Usage (from project root, conda activate cosa_snn):
    python scripts/run_profiling_sweep.py
    python scripts/run_profiling_sweep.py --jobs 8
    python scripts/run_profiling_sweep.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.workloads import build_unique_workloads, T_VALUES, shape_key as _shape_key  # noqa: E402
from lib.progress import print_progress  # noqa: E402

WORKLOAD_ROOT   = PROJECT_ROOT / "configs" / "workloads"
MAPSPACE_PATH   = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "profiling_sweep"

# ---------------------------------------------------------------------------
# Fixed hardware config
# ---------------------------------------------------------------------------

FIXED_NODES = 256
FIXED_L1_KB = 8
FIXED_L2_KB = 256
FIXED_PE    = 64
FIXED_SPLIT = {"weight": 30, "psum": 1, "vmem": 1}
TOTAL_BANKS = 32

T_VALUES = [4, 32, 128]

W_U     = 0.1
W_TR    = 1.0
W_DL    = 10.0
MIP_GAP = 0.001

DEFAULT_PE_REGISTER_ENTRIES   = {"weight": 128, "psum": 128, "vmem": 256}
DEFAULT_PE_REGISTER_BITWIDTHS = {"weight": 8,   "psum": 16,  "vmem": 32}
DEFAULT_ARCH_BITWIDTHS        = {"BW_WEIGHT": 8, "BW_PSUM": 16, "BW_VMEM": 32}


# ---------------------------------------------------------------------------
# Arch config (built in-memory, written once to out_dir/arch.yaml)
# ---------------------------------------------------------------------------

def _split_bytes(total_bytes: int, split: Dict[str, int]) -> Dict[str, int]:
    return {k: total_bytes * v // TOTAL_BANKS for k, v in split.items()}


def _build_arch() -> Dict:
    l1_bytes = FIXED_L1_KB * 1024
    l2_bytes = FIXED_L2_KB * 1024
    return {
        "arch": {
            "bitwidths": DEFAULT_ARCH_BITWIDTHS,
            "storage": [
                {
                    "name": "NodeLevel",
                    "instances": FIXED_NODES,
                    "pe": {
                        "num_pes": FIXED_PE,
                        "registers": {
                            "entries": DEFAULT_PE_REGISTER_ENTRIES,
                            "bitwidths": DEFAULT_PE_REGISTER_BITWIDTHS,
                        },
                    },
                    "local_buffer": {"entries": _split_bytes(l1_bytes, FIXED_SPLIT)},
                },
                {
                    "name": "NoCLevel",
                    "entries": _split_bytes(l2_bytes, FIXED_SPLIT),
                    "instances": 1,
                },
                {"name": "OffChip", "instances": 1},
            ],
        }
    }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _worker(task: Tuple) -> Dict[str, Any]:
    wl_key, wl_dict, arch_path_str, mapspace_str, time_limit = task

    from snn_cosa.enumerator import enumerate_modes
    from snn_cosa.cli import format_enumeration_summary

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as wf:
        yaml.safe_dump({"problem": wl_dict}, wf)
        wl_tmp = wf.name

    mapspace = Path(mapspace_str) if mapspace_str and Path(mapspace_str).exists() else None

    try:
        result = enumerate_modes(
            layer_path=wl_tmp,
            arch_path=arch_path_str,
            mapspace_path=mapspace,
            w_u=W_U,
            w_tr=W_TR,
            w_dl=W_DL,
            time_limit=time_limit,
            mip_gap=MIP_GAP,
            output_flag=False,
        )

        return {
            "wl_key":     wl_key,
            "best_mode":  result.get("best_mode"),
            "best_score": result.get("best_comparison_score"),
            "txt":        format_enumeration_summary(result, arch_path_str),
            "error":      None,
        }
    except Exception as exc:
        return {
            "wl_key":     wl_key,
            "best_mode":  None,
            "best_score": None,
            "txt":        None,
            "error":      str(exc),
        }
    finally:
        os.unlink(wl_tmp)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _txt_path(out_dir: Path, wl_key: str) -> Path:
    return out_dir / f"{wl_key}.txt"


def _write_txt(out_dir: Path, rec: Dict[str, Any]) -> None:
    path = _txt_path(out_dir, rec["wl_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"workload: {rec['wl_key']}\n\n")
        if rec["error"]:
            f.write(f"ERROR: {rec['error']}\n")
        else:
            f.write(rec["txt"])


def _parse_txt(path: Path) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    text = path.read_text()
    if "ERROR:" in text:
        for line in text.splitlines():
            if line.startswith("ERROR:"):
                return None, None, line[len("ERROR:"):].strip()
        return None, None, "unknown error"
    best_mode: Optional[str] = None
    best_score: Optional[float] = None
    for line in text.splitlines():
        if line.startswith("best:"):
            parts = line.split()
            if len(parts) >= 2:
                best_mode = parts[1]
            for p in parts:
                if p.startswith("score="):
                    try:
                        best_score = float(p[len("score="):])
                    except ValueError:
                        pass
    return best_mode, best_score, None


def _write_summary(out_dir: Path, workloads: List[Tuple[str, Dict]]) -> None:
    path = out_dir / "summary.txt"
    records = []
    for wl_key, _ in workloads:
        txt = _txt_path(out_dir, wl_key)
        if not txt.exists():
            continue
        best_mode, best_score, error = _parse_txt(txt)
        records.append({
            "wl_key":     wl_key,
            "best_mode":  best_mode,
            "best_score": best_score,
            "error":      error,
        })

    with open(path, "w") as f:
        f.write("Profiling sweep summary\n")
        f.write(
            f"arch: nodes={FIXED_NODES}, l1={FIXED_L1_KB}KB, l2={FIXED_L2_KB}KB, "
            f"pe={FIXED_PE}, split=w30v1p1\n"
        )
        f.write(f"weights: w_u={W_U}  w_tr={W_TR}  w_dl={W_DL}  mip_gap={MIP_GAP}\n")
        f.write(f"{'workload':<50}  {'best_mode':<24}  {'score':>14}\n")
        f.write("-" * 95 + "\n")
        for r in records:
            score_str = f"{r['best_score']:.4e}" if r["best_score"] is not None else "n/a"
            mode_str  = r["best_mode"] or ("ERROR" if r["error"] else "infeasible")
            f.write(f"{r['wl_key']:<50}  {mode_str:<24}  {score_str:>14}\n")

    print(f"\nSummary written to {path}  ({len(records)} workloads)")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def run_sweep(
    workloads:  List[Tuple[str, Dict]],
    arch_path:  Path,
    out_dir:    Path,
    jobs:       int,
    time_limit: float,
    dry_run:    bool,
) -> None:
    # Build task list, skipping already-done txt files
    tasks: List[Tuple] = []
    skipped = 0
    for wl_key, wl_dict in workloads:
        txt = _txt_path(out_dir, wl_key)
        if txt.exists() and txt.stat().st_size > 0:
            skipped += 1
            continue
        tasks.append((wl_key, wl_dict, str(arch_path), str(MAPSPACE_PATH), time_limit))

    total   = len(workloads)
    pending = len(tasks)

    print(f"\nUnique shapes:    {total // len(T_VALUES)}")
    print(f"T values:         {T_VALUES}")
    print(f"Total workloads:  {total}  (x11 modes each = {total * 11} Gurobi solves)")
    print(f"Already done:     {skipped}")
    print(f"Pending:          {pending}")
    print(f"Arch config:      nodes={FIXED_NODES}, l1={FIXED_L1_KB}KB, "
          f"l2={FIXED_L2_KB}KB, pe={FIXED_PE}, split=w30v1p1")
    print(f"Weights:          w_u={W_U}  w_tr={W_TR}  w_dl={W_DL}  mip_gap={MIP_GAP}")
    print(f"Time limit:       {f'{time_limit}s' if time_limit else 'none (unlimited)'} per mode")
    print(f"Jobs:             {jobs}")
    print(f"Output dir:       {out_dir}")

    if dry_run:
        print("\n[dry-run] Workload keys (first 10):")
        for wl_key, _ in workloads[:10]:
            print(f"  {wl_key}")
        if len(workloads) > 10:
            print(f"  ... and {len(workloads) - 10} more")
        print("\n[dry-run] Exiting without solving.")
        return

    if not pending:
        print("\nAll workloads already solved.")
        _write_summary(out_dir, workloads)
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    completed = skipped
    start = time.time()

    def _handle(rec: Dict[str, Any]) -> None:
        _write_txt(out_dir, rec)

    if jobs == 1:
        for task in tasks:
            rec = _worker(task)
            _handle(rec)
            completed += 1
            print_progress(completed, total, start, unit="solves")
    else:
        window = jobs * 2
        task_iter = iter(tasks)
        in_flight: dict = {}
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for t in task_iter:
                in_flight[pool.submit(_worker, t)] = t
                if len(in_flight) >= window:
                    break
            while in_flight:
                done_futs, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for fut in done_futs:
                    t = in_flight.pop(fut)
                    try:
                        rec = fut.result()
                    except Exception as exc:
                        rec = {
                            "wl_key": t[0], "best_mode": None,
                            "best_score": None, "txt": None, "error": str(exc),
                        }
                    _handle(rec)
                    completed += 1
                    print_progress(completed, total, start, unit="solves")
                    for t2 in task_iter:
                        in_flight[pool.submit(_worker, t2)] = t2
                        break

    elapsed = time.time() - start
    print(f"\n\nSweep done in {elapsed/3600:.2f}h  ({elapsed:.0f}s)")
    _write_summary(out_dir, workloads)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir",    default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--jobs",       type=int,   default=1,
                        help="parallel worker processes (default: 1)")
    parser.add_argument("--time-limit", type=float, default=30.0,
                        help="per-mode Gurobi time limit in seconds (default: 30)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="print plan without solving")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write the single arch config once; workers read it by path
    arch_path = out_dir / "arch.yaml"
    with open(arch_path, "w") as f:
        yaml.safe_dump(_build_arch(), f, sort_keys=False)

    workloads = build_unique_workloads(WORKLOAD_ROOT)

    run_sweep(
        workloads=workloads,
        arch_path=arch_path,
        out_dir=out_dir,
        jobs=args.jobs,
        time_limit=args.time_limit,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
