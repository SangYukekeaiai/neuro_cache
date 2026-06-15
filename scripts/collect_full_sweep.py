#!/usr/bin/env python3
"""Aggregate per-sample .txt files from run_full_arch_sweep.py into a CSV.

Walks outputs/full_arch_sweep/**/<wl_key>.txt, extracts best_mode and
best_score from each file, and writes:

    outputs/full_arch_sweep/summary.csv   (arch_key, wl_key, best_mode, best_score, error)

Run after all SLURM array tasks complete::

    python scripts/collect_full_sweep.py

Or point at a different sweep dir::

    python scripts/collect_full_sweep.py --sweep-dir outputs/full_arch_sweep
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SWEEP_DIR = PROJECT_ROOT / "outputs" / "full_arch_sweep"


def _parse_txt(path: Path) -> Tuple[str, str, Optional[str], Optional[float], Optional[str]]:
    """Return (arch_rel, wl_key, best_mode, best_score, error) from a txt file."""
    text = path.read_text()
    arch_rel = wl_key = best_mode = error = None
    best_score: Optional[float] = None

    for line in text.splitlines():
        if line.startswith("arch:"):
            arch_rel = line[len("arch:"):].strip()
        elif line.startswith("workload:"):
            wl_key = line[len("workload:"):].strip()
        elif line.startswith("best:"):
            parts = line.split()
            if len(parts) >= 2:
                best_mode = parts[1]
            for p in parts:
                if p.startswith("score="):
                    try:
                        best_score = float(p[len("score="):])
                    except ValueError:
                        pass
        elif line.startswith("ERROR:"):
            error = line[len("ERROR:"):].strip()

    if arch_rel is None:
        arch_rel = str(path.parent.relative_to(path.parent.parent.parent))
    if wl_key is None:
        wl_key = path.stem

    return arch_rel, wl_key, best_mode, best_score, error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep-dir", default=str(DEFAULT_SWEEP_DIR),
                        help="root of the full arch sweep output directory")
    parser.add_argument("--out", default=None,
                        help="output CSV path (default: <sweep-dir>/summary.csv)")
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    out_csv   = Path(args.out) if args.out else sweep_dir / "summary.csv"

    txt_files = sorted(sweep_dir.rglob("*.txt"))
    if not txt_files:
        print(f"No .txt files found under {sweep_dir}", file=sys.stderr)
        return 1

    print(f"Collecting {len(txt_files)} result files ...")
    rows = []
    errors = 0
    for txt in txt_files:
        arch_rel, wl_key, best_mode, best_score, error = _parse_txt(txt)
        rows.append({
            "arch_key":   arch_rel,
            "wl_key":     wl_key,
            "best_mode":  best_mode or "",
            "best_score": f"{best_score:.6e}" if best_score is not None else "",
            "error":      error or "",
        })
        if error:
            errors += 1

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arch_key", "wl_key", "best_mode",
                                               "best_score", "error"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written {len(rows)} rows to {out_csv}")
    print(f"  solved: {len(rows) - errors}   errors: {errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
