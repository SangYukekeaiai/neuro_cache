#!/usr/bin/env python3
"""Subset sweep: all arch configs × 2 representative workloads.

Workloads (matching similarity_probe conventions):
  shallow  —  resnet19/conv1   T=4
  deep     —  vgg16/conv5_3    T=128

Arch space: all 1568 configs under configs/arch/sweep/

Per-pair output: outputs/subset_sweep/{shallow|deep}/<arch-path>.txt
Summary:         outputs/subset_sweep/summary.txt

Already-solved pairs (txt file exists and is non-empty) are skipped
automatically — re-run the same command to resume.

Usage (from project root, conda activate cosa_snn):

    python scripts/run_subset_sweep.py
    python scripts/run_subset_sweep.py --jobs 8
    python scripts/run_subset_sweep.py --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.progress import print_progress as _print_progress  # noqa: E402

ARCH_SWEEP_DIR = PROJECT_ROOT / "configs" / "arch" / "sweep"
MAPSPACE_PATH  = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "subset_sweep"

WORKLOADS = [
    ("shallow_T4",   PROJECT_ROOT / "configs/workloads/generated/resnet19/T4/conv1.yaml"),
    ("shallow_T32",  PROJECT_ROOT / "configs/workloads/generated/resnet19/T32/conv1.yaml"),
    ("shallow_T128", PROJECT_ROOT / "configs/workloads/generated/resnet19/T128/conv1.yaml"),
    ("deep_T4",      PROJECT_ROOT / "configs/workloads/generated/vgg16/T4/conv5_3.yaml"),
    ("deep_T32",     PROJECT_ROOT / "configs/workloads/generated/vgg16/T32/conv5_3.yaml"),
    ("deep_T128",    PROJECT_ROOT / "configs/workloads/generated/vgg16/T128/conv5_3.yaml"),
]

W_U    = 0.1
W_TR   = 1.0
W_DL   = 10.0
MIP_GAP = 0.001


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _worker(task: Tuple) -> Dict[str, Any]:
    wl_label, wl_path_str, arch_key, arch_path_str, mapspace_str, time_limit = task

    from snn_cosa.enumerator import enumerate_modes
    from snn_cosa.cli import _print_enumeration_summary

    mapspace = Path(mapspace_str) if mapspace_str and Path(mapspace_str).exists() else None

    try:
        result = enumerate_modes(
            layer_path=wl_path_str,
            arch_path=arch_path_str,
            mapspace_path=mapspace,
            w_u=W_U,
            w_tr=W_TR,
            w_dl=W_DL,
            time_limit=time_limit,
            mip_gap=MIP_GAP,
            output_flag=False,
        )

        # Capture _print_enumeration_summary output as a string
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _print_enumeration_summary(result, Path(arch_path_str))
        finally:
            sys.stdout = old_stdout

        return {
            "wl_label":  wl_label,
            "arch_key":  arch_key,
            "best_mode": result.get("best_mode"),
            "best_score": result.get("best_comparison_score"),
            "txt":       buf.getvalue(),
            "error":     None,
        }
    except Exception as exc:
        return {
            "wl_label":  wl_label,
            "arch_key":  arch_key,
            "best_mode": None,
            "best_score": None,
            "txt":       None,
            "error":     str(exc),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _txt_path(out_dir: Path, wl_label: str, arch_key: str) -> Path:
    # arch_key is like "nodes_16/gb_64kb/l1_4kb/pe_16/split_w30_p1_v1.yaml"
    # → flatten hierarchy into a single filename: shallow__nodes_16__gb_64kb__...txt
    stem = arch_key.replace(".yaml", "").replace("/", "__")
    return out_dir / f"{wl_label}__{stem}.txt"


def _write_txt(path: Path, rec: Dict[str, Any], arch_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"arch: {arch_key}\n")
        f.write(f"workload: {rec['wl_label']}\n\n")
        if rec["error"]:
            f.write(f"ERROR: {rec['error']}\n")
        else:
            f.write(rec["txt"])


def _write_summary(out_dir: Path, records: List[Dict[str, Any]]) -> None:
    path = out_dir / "summary.txt"
    records_sorted = sorted(records, key=lambda r: (r["wl_label"], r["arch_key"]))

    with open(path, "w") as f:
        f.write(f"Subset sweep summary\n")
        f.write(f"weights: w_u={W_U}  w_tr={W_TR}  w_dl={W_DL}  mip_gap={MIP_GAP}\n")
        f.write(f"{'workload':<10}  {'arch':<55}  {'best_mode':<24}  {'score':>14}\n")
        f.write("-" * 110 + "\n")
        for r in records_sorted:
            score_str = f"{r['best_score']:.4e}" if r["best_score"] is not None else "n/a"
            mode_str  = r["best_mode"] or ("ERROR" if r["error"] else "infeasible")
            f.write(f"{r['wl_label']:<10}  {r['arch_key']:<55}  {mode_str:<24}  {score_str:>14}\n")

    print(f"\nSummary written to {path}  ({len(records_sorted)} pairs)")


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def run_subset_sweep(
    out_dir:    Path,
    jobs:       int,
    time_limit: Optional[float],
    dry_run:    bool,
) -> None:
    arch_yamls = sorted(ARCH_SWEEP_DIR.rglob("*.yaml"))
    if not arch_yamls:
        print(f"No arch YAMLs found under {ARCH_SWEEP_DIR}", file=sys.stderr)
        return

    # Build tasks, skipping pairs whose txt already exists and is non-empty
    tasks: List[Tuple] = []
    skipped = 0
    for wl_label, wl_path in WORKLOADS:
        if not wl_path.exists():
            print(f"WARNING: workload not found: {wl_path}", file=sys.stderr)
            continue
        for ap in arch_yamls:
            arch_key = str(ap.relative_to(ARCH_SWEEP_DIR))
            txt = _txt_path(out_dir, wl_label, arch_key)
            if txt.exists() and txt.stat().st_size > 0:
                skipped += 1
                continue
            tasks.append((
                wl_label, str(wl_path),
                arch_key, str(ap),
                str(MAPSPACE_PATH),
                time_limit,
            ))

    total   = len(arch_yamls) * len(WORKLOADS)
    pending = len(tasks)

    print(f"Arch configs:  {len(arch_yamls)}")
    print(f"Workloads:     {len(WORKLOADS)}  ({', '.join(l for l,_ in WORKLOADS)})")
    print(f"Total pairs:   {total}")
    print(f"Already done:  {skipped}")
    print(f"Pending:       {pending}")
    print(f"Weights:       w_u={W_U}  w_tr={W_TR}  w_dl={W_DL}  mip_gap={MIP_GAP}")
    print(f"Jobs:          {jobs}")
    print(f"Output dir:    {out_dir}")

    if dry_run:
        print("\n[dry-run] Exiting without solving.")
        return

    if not pending:
        print("\nAll pairs already solved.")
        _rebuild_summary(out_dir, arch_yamls)
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    completed = skipped
    start = time.time()
    all_records: List[Dict[str, Any]] = []

    def _handle(rec: Dict[str, Any]) -> None:
        arch_key = rec["arch_key"]
        txt = _txt_path(out_dir, rec["wl_label"], arch_key)
        _write_txt(txt, rec, arch_key)
        all_records.append(rec)

    if jobs == 1:
        for task in tasks:
            rec = _worker(task)
            _handle(rec)
            completed += 1
            _print_progress(completed, total, start)
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
                            "wl_label": t[0], "arch_key": t[2],
                            "best_mode": None, "best_score": None,
                            "txt": None, "error": str(exc),
                        }
                    _handle(rec)
                    completed += 1
                    _print_progress(completed, total, start)
                    for t2 in task_iter:
                        in_flight[pool.submit(_worker, t2)] = t2
                        break

    elapsed = time.time() - start
    print(f"\n\nSweep done in {elapsed/3600:.2f}h  ({elapsed:.0f}s)")

    # Build summary from all results (newly solved + previously done)
    _rebuild_summary(out_dir, arch_yamls)


def _rebuild_summary(out_dir: Path, arch_yamls: List[Path]) -> None:
    """Read all existing txt files and regenerate summary.txt."""
    records: List[Dict[str, Any]] = []
    for wl_label, _ in WORKLOADS:
        for ap in arch_yamls:
            arch_key = str(ap.relative_to(ARCH_SWEEP_DIR))
            txt = _txt_path(out_dir, wl_label, arch_key)
            if not txt.exists():
                continue
            best_mode, best_score, error = _parse_txt(txt)
            records.append({
                "wl_label":   wl_label,
                "arch_key":   arch_key,
                "best_mode":  best_mode,
                "best_score": best_score,
                "error":      error,
            })
    _write_summary(out_dir, records)


def _parse_txt(path: Path) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """Extract best_mode and best_score from a written txt file."""
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
            # "best: both_gb_oooo  score=8.7291e+07"
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir",    default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--jobs",       type=int,   default=1,
                        help="parallel worker processes (default: 1)")
    parser.add_argument("--time-limit", type=float, default=30.0,
                        help="per-mode Gurobi time limit in seconds (default: 30)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="print plan without running any solves")
    args = parser.parse_args()

    run_subset_sweep(
        out_dir=Path(args.out_dir),
        jobs=args.jobs,
        time_limit=args.time_limit,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
