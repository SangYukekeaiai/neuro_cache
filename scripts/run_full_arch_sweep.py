#!/usr/bin/env python3
"""Full arch-sweep × unique-workload sweep with per-sample .txt output.

Enumerates all architecture configs × all unique workloads (deduped by shape
across ResNet-19/34/50, VGG-16, and DeepBench GEMM, expanded over T∈{4,32,128}).

Arch configs:     configs/arch/sweep/**/*.yaml          (1568 files)
Unique workloads: lib.workloads.build_unique_workloads()  (~135 configs)

Output layout::

    outputs/full_arch_sweep/
      <arch_rel_path>/          # mirrors arch sweep directory tree
        <wl_key>.txt
      summary.csv               # aggregated after all tasks finish

SLURM array mode (one arch config per task — recommended on Newton)::

    python scripts/run_full_arch_sweep.py --arch-index $SLURM_ARRAY_TASK_ID

Local run (all arches, parallel workers)::

    python scripts/run_full_arch_sweep.py --jobs 8

Single arch (debugging)::

    python scripts/run_full_arch_sweep.py --arch configs/arch/snn_arch.yaml

Already-solved pairs (non-empty .txt exists) are skipped automatically.
Re-run to resume after a preemption.
"""

from __future__ import annotations

import argparse
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

from lib.workloads import build_unique_workloads  # noqa: E402
from lib.progress import print_progress           # noqa: E402

ARCH_SWEEP_DIR  = PROJECT_ROOT / "configs" / "arch" / "sweep"
WORKLOAD_ROOT   = PROJECT_ROOT / "configs" / "workloads"
MAPSPACE_PATH   = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "full_arch_sweep"

W_U     = 0.1
W_TR    = 1.0
W_DL    = 10.0
MIP_GAP = 0.001


# ---------------------------------------------------------------------------
# Worker (runs in subprocess)
# ---------------------------------------------------------------------------

def _worker(task: Tuple) -> Dict[str, Any]:
    wl_key, wl_dict, arch_path_str, mapspace_str, time_limit, mip_gap = task

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
            mip_gap=mip_gap,
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
            "wl_key":    wl_key,
            "best_mode": None, "best_score": None, "txt": None,
            "error":     str(exc),
        }
    finally:
        os.unlink(wl_tmp)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _txt_path(out_dir: Path, arch_rel: str, wl_key: str) -> Path:
    return out_dir / arch_rel.replace(".yaml", "") / f"{wl_key}.txt"


def _write_txt(out_dir: Path, arch_rel: str, rec: Dict[str, Any]) -> None:
    path = _txt_path(out_dir, arch_rel, rec["wl_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"arch: {arch_rel}\n")
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


# ---------------------------------------------------------------------------
# Per-arch sweep
# ---------------------------------------------------------------------------

def _run_arch(
    arch_path:  Path,
    arch_rel:   str,
    workloads:  List[Tuple[str, Dict]],
    out_dir:    Path,
    jobs:       int,
    time_limit: Optional[float],
    mip_gap:    float,
    dry_run:    bool,
) -> None:
    tasks: List[Tuple] = []
    skipped = 0
    for wl_key, wl_dict in workloads:
        txt = _txt_path(out_dir, arch_rel, wl_key)
        if txt.exists() and txt.stat().st_size > 0:
            skipped += 1
        else:
            tasks.append((wl_key, wl_dict, str(arch_path), str(MAPSPACE_PATH), time_limit, mip_gap))

    if dry_run:
        print(f"[dry-run] arch={arch_rel}  pending={len(tasks)}  skipped={skipped}")
        return

    if not tasks:
        return

    start = time.time()
    total = len(workloads)
    completed = skipped

    def _handle(rec: Dict[str, Any]) -> None:
        nonlocal completed
        _write_txt(out_dir, arch_rel, rec)
        completed += 1
        print_progress(completed, total, start, unit="wl")

    if jobs == 1:
        for t in tasks:
            _handle(_worker(t))
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
                        rec = {"wl_key": t[0], "best_mode": None,
                               "best_score": None, "txt": None, "error": str(exc)}  # t[0]=wl_key
                    _handle(rec)
                    for t2 in task_iter:
                        in_flight[pool.submit(_worker, t2)] = t2
                        break

    elapsed = time.time() - start
    print(f"  arch done in {elapsed:.0f}s  ({arch_rel})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    arch_group = parser.add_mutually_exclusive_group()
    arch_group.add_argument(
        "--arch-index", type=int, default=None,
        help="SLURM array index: process only this arch (0-based into sorted list)",
    )
    arch_group.add_argument(
        "--arch", type=str, default=None,
        help="single arch YAML path (for debugging)",
    )
    parser.add_argument("--arch-dir",   default=str(ARCH_SWEEP_DIR),
                        help="root of generated arch YAMLs")
    parser.add_argument("--out-dir",    default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--jobs",       type=int,   default=1,
                        help="parallel worker processes per arch (default: 1)")
    parser.add_argument("--time-limit", type=float, default=30.0,
                        help="per-mode Gurobi time limit in seconds (default: 30)")
    parser.add_argument("--mip-gap",    type=float, default=MIP_GAP,
                        help=f"Gurobi relative MIP gap (default: {MIP_GAP})")
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    workloads = build_unique_workloads(WORKLOAD_ROOT)
    print(f"Unique workloads: {len(workloads)}  (weights: w_u={W_U} w_tr={W_TR} w_dl={W_DL})")

    arch_dir = Path(args.arch_dir)

    # Determine which arch configs to process
    if args.arch:
        arch_paths = [Path(args.arch)]
    else:
        arch_paths = sorted(arch_dir.rglob("*.yaml"))
        if not arch_paths:
            print(f"No arch YAMLs under {arch_dir} — run generate_arch_sweep.py first",
                  file=sys.stderr)
            return 1
        if args.arch_index is not None:
            if args.arch_index >= len(arch_paths):
                print(f"--arch-index {args.arch_index} out of range "
                      f"(total arches: {len(arch_paths)})", file=sys.stderr)
                return 1
            arch_paths = [arch_paths[args.arch_index]]

    print(f"Arch configs to process: {len(arch_paths)}")
    print(f"Time limit: {args.time_limit}s/mode   MIP gap: {args.mip_gap}   Jobs: {args.jobs}")

    for ap in arch_paths:
        try:
            arch_rel = str(ap.relative_to(arch_dir))
        except ValueError:
            arch_rel = str(ap)
        _run_arch(
            arch_path=ap,
            arch_rel=arch_rel,
            workloads=workloads,
            out_dir=out_dir,
            jobs=args.jobs,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
