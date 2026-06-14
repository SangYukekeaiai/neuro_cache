#!/usr/bin/env python3
"""Run enumerate_modes over all generated arch × workload pairs.

Arch configs:     configs/arch/sweep/**/*.yaml          (1792 files)
Workload configs: configs/workloads/generated/**/*.yaml  (690 files)

Each (arch, workload) pair is solved across all 8 TrafficModes and the
globally optimal schedule is selected by the comparison score:

    score = w_u * util_sum + w_tr * tr_sum + w_dl * delay

Default weights: w_u=0.1, w_tr=1.0, w_dl=10.0  (CoSA defaults)
Default mip_gap: 0.001

Results are written to a JSONL checkpoint (one line per pair) that supports
resuming interrupted runs with --skip-existing.

Usage (from project root, conda activate cosa_snn):

    # Serial run — smallest overhead per solve
    python scripts/run_full_sweep.py

    # Parallel run with 8 workers
    python scripts/run_full_sweep.py --jobs 8

    # Resume a previously interrupted run
    python scripts/run_full_sweep.py --skip-existing

    # Dry-run: list pairs without solving
    python scripts/run_full_sweep.py --dry-run

    # Override weights or gap
    python scripts/run_full_sweep.py --w-u 0.1 --w-tr 1.0 --w-dl 10.0 --mip-gap 0.001
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.progress import print_progress as _print_progress  # noqa: E402

ARCH_SWEEP_DIR    = PROJECT_ROOT / "configs" / "arch" / "sweep"
WORKLOAD_GEN_DIR  = PROJECT_ROOT / "configs" / "workloads" / "generated"
MAPSPACE_PATH     = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
DEFAULT_OUT_DIR   = PROJECT_ROOT / "outputs" / "full_sweep"

DEFAULT_W_U    = 0.1
DEFAULT_W_TR   = 1.0
DEFAULT_W_DL   = 10.0
DEFAULT_MIP_GAP = 0.001


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

def _discover_yamls(root: Path) -> List[Path]:
    return sorted(root.rglob("*.yaml"))


def _rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base))


# ---------------------------------------------------------------------------
# Worker (runs in a subprocess for parallelism)
# ---------------------------------------------------------------------------

def _worker(task: Tuple) -> Dict[str, Any]:
    (arch_key, arch_path_str,
     wl_key,   wl_path_str,
     mapspace_str,
     w_u, w_tr, w_dl,
     time_limit, mip_gap) = task

    from snn_cosa.enumerator import enumerate_modes

    mapspace = Path(mapspace_str) if mapspace_str and Path(mapspace_str).exists() else None

    try:
        result = enumerate_modes(
            layer_path=wl_path_str,
            arch_path=arch_path_str,
            mapspace_path=mapspace,
            w_u=w_u,
            w_tr=w_tr,
            w_dl=w_dl,
            time_limit=time_limit,
            mip_gap=mip_gap,
            output_flag=False,
        )
        return {
            "arch_key":   arch_key,
            "wl_key":     wl_key,
            "best_mode":  result.get("best_mode"),
            "best_score": result.get("best_comparison_score"),
            "candidates": result.get("candidates", []),
            "weights":    result.get("weights", {}),
        }
    except Exception as exc:
        return {
            "arch_key": arch_key,
            "wl_key":   wl_key,
            "error":    str(exc),
        }


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def _build_tasks(
    arch_yamls: List[Path],
    wl_yamls:   List[Path],
    checkpoint: Path,
    skip_existing: bool,
    w_u: float, w_tr: float, w_dl: float,
    time_limit: Optional[float],
    mip_gap:    Optional[float],
) -> List[Tuple]:
    """Load already-solved pairs and build the remaining task list."""
    done: set = set()
    if skip_existing and checkpoint.exists():
        with open(checkpoint) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if "error" not in rec:
                        done.add((rec["arch_key"], rec["wl_key"]))
                except Exception:
                    pass
        print(f"  Resuming: {len(done)} pairs already done.")

    tasks = []
    for ap in arch_yamls:
        ak = _rel(ap, ARCH_SWEEP_DIR)
        for wp in wl_yamls:
            wk = _rel(wp, WORKLOAD_GEN_DIR)
            if (ak, wk) not in done:
                tasks.append((
                    ak, str(ap),
                    wk, str(wp),
                    str(MAPSPACE_PATH),
                    w_u, w_tr, w_dl,
                    time_limit, mip_gap,
                ))
    return tasks


def _run_tasks(
    tasks:       List[Tuple],
    checkpoint:  Path,
    jobs:        int,
    total_pairs: int,
    completed:   int,
    start:       float,
) -> None:
    """Dispatch tasks to _worker — serial (jobs=1) or bounded-window parallel."""
    with open(checkpoint, "a") as out_f:
        if jobs == 1:
            for task in tasks:
                rec = _worker(task)
                out_f.write(json.dumps(rec) + "\n")
                out_f.flush()
                completed += 1
                _print_progress(completed, total_pairs, start)
        else:
            # Bounded window: keep at most 2*jobs futures in flight so the
            # executor queue never grows to millions of entries.
            window    = jobs * 2
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
                            rec = {"arch_key": t[0], "wl_key": t[2], "error": str(exc)}
                        out_f.write(json.dumps(rec) + "\n")
                        out_f.flush()
                        completed += 1
                        _print_progress(completed, total_pairs, start)
                        for t2 in task_iter:
                            in_flight[pool.submit(_worker, t2)] = t2
                            break


def run_sweep(
    arch_yamls:    List[Path],
    wl_yamls:      List[Path],
    checkpoint:    Path,
    jobs:          int,
    skip_existing: bool,
    w_u:           float,
    w_tr:          float,
    w_dl:          float,
    time_limit:    Optional[float],
    mip_gap:       Optional[float],
    dry_run:       bool,
) -> None:
    tasks       = _build_tasks(arch_yamls, wl_yamls, checkpoint, skip_existing,
                               w_u, w_tr, w_dl, time_limit, mip_gap)
    total_pairs = len(arch_yamls) * len(wl_yamls)
    remaining   = len(tasks)

    print(f"\nArch configs:     {len(arch_yamls)}")
    print(f"Workload configs: {len(wl_yamls)}")
    print(f"Total pairs:      {total_pairs}  (x8 modes each)")
    print(f"Already done:     {total_pairs - remaining}")
    print(f"Remaining:        {remaining}")
    print(f"Weights:          w_u={w_u}  w_tr={w_tr}  w_dl={w_dl}")
    print(f"mip_gap:          {mip_gap}")
    print(f"Jobs:             {jobs}")
    print(f"Checkpoint:       {checkpoint}")

    if dry_run:
        print("\n[dry-run] Exiting without solving.")
        return
    if not remaining:
        print("\nAll pairs already solved.")
        return

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    _run_tasks(tasks, checkpoint, jobs, total_pairs, total_pairs - remaining, start)

    elapsed = time.time() - start
    print(f"\n\nSweep done in {elapsed/3600:.2f}h  ({elapsed:.0f}s)")
    print(f"Results written to {checkpoint}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch-dir",   default=str(ARCH_SWEEP_DIR),
                        help="directory of generated arch YAMLs")
    parser.add_argument("--wl-dir",     default=str(WORKLOAD_GEN_DIR),
                        help="directory of generated workload YAMLs")
    parser.add_argument("--out-dir",    default=str(DEFAULT_OUT_DIR),
                        help="output directory for checkpoint JSONL")
    parser.add_argument("--jobs",       type=int,   default=1,
                        help="parallel worker processes (default: 1)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="resume: skip pairs already present in checkpoint")
    parser.add_argument("--mip-gap",    type=float, default=DEFAULT_MIP_GAP,
                        help=f"Gurobi relative MIP gap (default: {DEFAULT_MIP_GAP})")
    parser.add_argument("--time-limit", type=float, default=None,
                        help="per-mode Gurobi time limit in seconds (default: none)")
    parser.add_argument("--w-u",        type=float, default=DEFAULT_W_U,
                        help=f"utilization weight (default: {DEFAULT_W_U})")
    parser.add_argument("--w-tr",       type=float, default=DEFAULT_W_TR,
                        help=f"traffic weight (default: {DEFAULT_W_TR})")
    parser.add_argument("--w-dl",       type=float, default=DEFAULT_W_DL,
                        help=f"delay weight (default: {DEFAULT_W_DL})")
    parser.add_argument("--dry-run",    action="store_true",
                        help="print plan without running any solves")
    args = parser.parse_args()

    arch_yamls = _discover_yamls(Path(args.arch_dir))
    wl_yamls   = _discover_yamls(Path(args.wl_dir))

    if not arch_yamls:
        print(f"No arch YAMLs found under {args.arch_dir}", file=sys.stderr)
        print("Run: python scripts/generate_arch_sweep.py", file=sys.stderr)
        return 1
    if not wl_yamls:
        print(f"No workload YAMLs found under {args.wl_dir}", file=sys.stderr)
        print("Run: python scripts/generate_workload_sweep.py", file=sys.stderr)
        return 1

    checkpoint = Path(args.out_dir) / "results.jsonl"

    run_sweep(
        arch_yamls=arch_yamls,
        wl_yamls=wl_yamls,
        checkpoint=checkpoint,
        jobs=args.jobs,
        skip_existing=args.skip_existing,
        w_u=args.w_u,
        w_tr=args.w_tr,
        w_dl=args.w_dl,
        time_limit=args.time_limit,
        mip_gap=args.mip_gap,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
