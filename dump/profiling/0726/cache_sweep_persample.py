"""One-off driver for the per-sample hit-rate variant: same (arch,
workload, layer) units and same 4/16/32-way + direct-mapped config subset
as cache_sweep.py's subset run, but native/cache_sweep_persample streams
one row per (config, sample) instead of collapsing to a mean -- needed
for a per-sample distribution view (boxplot per tag-dimension, mirroring
profiling/0723's concentration boxplots) that the mean-only pipeline
can't produce. Kept fully separate from cache_sweep.py's results/ and
results_subset/ dirs and from native/cache_sweep(_subset) so it can't
interact with the full-sweep job or the completed subset run.

Reuses cache_sweep.py's discover_units/_build_binary_input/_run_units by
import and monkeypatching its module globals (same pattern as this
session's test scripts) rather than duplicating that logic.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cache_sweep as cs

HERE = pathlib.Path(__file__).resolve().parent
NATIVE_BIN = HERE / "native" / "cache_sweep_persample"
RESULTS_DIR = HERE / "results_persample"
STRUCT_IDS = "0,1,3,4"
CSV_HEADER = "arch,workload,layer,cache_type,associativity,size_bytes,inner_dim,line_size,sample_idx,hit_rate\n"


def run_unit(unit):
    arch, workload, layer = unit
    result_path = RESULTS_DIR / f"{arch}__{workload}__{layer}.csv"
    if result_path.exists():
        return f"skip (cached): {arch}/{workload}/{layer}"

    layer_dir = cs.TRACE_ROOT / arch / workload / layer
    t0 = time.time()
    payload, n_samples = cs._build_binary_input(layer_dir)
    if n_samples == 0:
        return f"skip (no samples): {arch}/{workload}/{layer}"

    proc = subprocess.run([str(NATIVE_BIN), STRUCT_IDS, "persample"], input=payload, capture_output=True)
    if proc.returncode != 0:
        return f"FAILED: {arch}/{workload}/{layer}: {proc.stderr.decode(errors='replace').strip()}"

    with open(result_path, "w") as out:
        out.write(CSV_HEADER)
        for line in proc.stdout.decode().splitlines():
            out.write(f"{arch},{workload},{layer},{line}\n")

    elapsed = time.time() - t0
    return f"done: {arch}/{workload}/{layer} ({n_samples} samples, {elapsed:.1f}s)"


def merge_results(out_path: pathlib.Path) -> int:
    csvs = sorted(RESULTS_DIR.glob("*.csv"))
    n_rows = 0
    with open(out_path, "w") as out:
        out.write(CSV_HEADER)
        for p in csvs:
            with open(p) as fh:
                next(fh)
                for line in fh:
                    out.write(line)
                    n_rows += 1
    return n_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--max-samples", type=int, default=5)
    args = parser.parse_args()

    if not NATIVE_BIN.exists():
        sys.exit(f"native binary not found at {NATIVE_BIN}; build it first (see native/Makefile)")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    cs.MAX_SAMPLES = args.max_samples
    cs.RESULTS_DIR = RESULTS_DIR  # only used by _run_units' remaining-units recheck
    cs.run_unit = run_unit

    units = cs.discover_units()
    units = [u for u in units if not (RESULTS_DIR / f"{u[0]}__{u[1]}__{u[2]}.csv").exists()]
    print(f"sizing {len(units)} not-yet-done units for smallest-first scheduling...", flush=True)
    units.sort(key=cs._one_sample_element_count)
    print(f"{len(units)} units to run, {args.workers} workers, persample mode", flush=True)
    cs._run_units(units, args.workers)

    merged_path = HERE / "cache_sweep_results_persample.csv"
    n_rows = merge_results(merged_path)
    print(f"merged {n_rows} rows into {merged_path}", flush=True)


if __name__ == "__main__":
    main()
