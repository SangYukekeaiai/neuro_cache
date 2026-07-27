"""Driver for the cache-config sweep: for every (arch, workload, layer)
with locally cached weight-trace data, feed all its samples to the
native/cache_sweep C++ binary (one process per layer, so all 288
configs x that layer's samples are computed in one native pass -- see
native/cache_sweep.cpp's header for why: a pure-Python pass over one
config on one sample of the largest layer took 20+ minutes and never
finished, 288 configs x 100 samples x ~31 layers would not complete in
any usable time), then merge every layer's 288-row CSV output into one
results table.

Per-unit results are cached to results/<arch>__<workload>__<layer>.csv;
a unit already on disk is skipped, so a partial run (e.g. cut off by an
srun time limit) resumes for free on the next invocation.
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import pathlib
import struct
import subprocess
import sys
import time
from typing import List, Tuple

import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TRACE_ROOT = REPO_ROOT / "outputs" / "weight_traces"
NATIVE_BIN = pathlib.Path(__file__).resolve().parent / "native" / "cache_sweep"
RESULTS_DIR = pathlib.Path(__file__).resolve().parent / "results"

# overridable via CLI for partial/subset runs (e.g. --struct-ids to skip
# fully_associative, --max-samples to sample a handful instead of all
# 100); left as module globals, not threaded through every call, so
# forked Pool workers just inherit them
STRUCT_IDS: str | None = None
MAX_SAMPLES: int | None = None

ARCHS = ["loas", "ptb", "spinalflow", "prosperity", "gustavsnn"]
WORKLOADS = ["resnet19_T4_all", "vgg16_T4_all"]

CSV_HEADER = "arch,workload,layer,cache_type,associativity,size_bytes,inner_dim,line_size,mean_hit_rate,n_samples\n"


def discover_units() -> List[Tuple[str, str, str]]:
    """(arch, workload, layer) triples for every layer dir that actually
    exists locally under outputs/weight_traces/ -- only archs/workloads
    present on disk are swept, nothing is assumed."""
    units = []
    for arch in ARCHS:
        arch_dir = TRACE_ROOT / arch
        if not arch_dir.is_dir():
            continue
        for workload in WORKLOADS:
            wl_dir = arch_dir / workload
            if not wl_dir.is_dir():
                continue
            for layer_dir in sorted(wl_dir.iterdir()):
                if layer_dir.is_dir():
                    units.append((arch, workload, layer_dir.name))
    return units


def _one_sample_element_count(unit: Tuple[str, str, str]) -> int:
    """Cheap proxy for a unit's total memory/runtime footprint: element
    count of its first sample file. Some layers (SpinalFlow's especially)
    run up to ~14x bigger than others -- sorting units smallest-first
    means the worker pool naturally spreads the huge ones out over time
    instead of several landing on different workers at once (that's what
    triggered the 59-process OOM kill the first time this sweep ran: the
    Python-side payload for one giant unit alone is ~27GB, held for the
    whole subprocess call, and several overlapping blew way past the
    allocation)."""
    arch, workload, layer = unit
    p = TRACE_ROOT / arch / workload / layer / "sample_00018.json.gz"
    try:
        with gzip.open(p, "rt") as fh:
            data = json.load(fh)
    except OSError:
        return 0
    return sum(addr[4] - addr[3] for tile in data["tiles"] for addr in tile["weight_addresses"])


def _build_binary_input(layer_dir: pathlib.Path) -> bytes:
    """Read every sample_*.json.gz in layer_dir and pack them into
    native/cache_sweep's expected binary format, in memory -- never
    touches disk (a layer_01-scale unit's payload is ~250-300MB; with
    dozens of workers writing that to the home-quota-tracked repo tree at
    once, it blew the 103GB home quota the first time this ran, see
    log/2026-07-26-workflow-optimization-plan.md's incident note).
    Reads the raw JSON directly (not tracegen.load_weight_trace) to avoid
    pulling in gurobipy just to flatten weight_addresses."""
    paths = sorted(layer_dir.glob("sample_*.json.gz"))
    if MAX_SAMPLES is not None:
        paths = paths[:MAX_SAMPLES]
    parts = [struct.pack("<I", len(paths))]
    for p in paths:
        with gzip.open(p, "rt") as fh:
            data = json.load(fh)
        events = [addr for tile in data["tiles"] for addr in tile["weight_addresses"]]
        parts.append(struct.pack("<I", len(events)))
        # numpy, not struct.pack(f"<{n}i", *flat) -- the largest layer has
        # ~1M events (~5M ints); unpacking that many positional args into
        # one struct.pack call is needlessly slow and memory-heavy.
        parts.append(np.asarray(events, dtype="<i4").tobytes())
    return b"".join(parts), len(paths)


def run_unit(unit: Tuple[str, str, str]) -> str:
    arch, workload, layer = unit
    result_path = RESULTS_DIR / f"{arch}__{workload}__{layer}.csv"
    if result_path.exists():
        return f"skip (cached): {arch}/{workload}/{layer}"

    layer_dir = TRACE_ROOT / arch / workload / layer
    t0 = time.time()
    payload, n_samples = _build_binary_input(layer_dir)
    if n_samples == 0:
        return f"skip (no samples): {arch}/{workload}/{layer}"

    argv = [str(NATIVE_BIN)] + ([STRUCT_IDS] if STRUCT_IDS is not None else [])
    proc = subprocess.run(argv, input=payload, capture_output=True, text=False)

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
                next(fh)  # skip per-file header
                for line in fh:
                    out.write(line)
                    n_rows += 1
    return n_rows


def main() -> None:
    global NATIVE_BIN, RESULTS_DIR, STRUCT_IDS, MAX_SAMPLES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=mp.cpu_count(),
                         help="parallel worker processes, one native subprocess per unit at a time each")
    parser.add_argument("--merge-only", action="store_true",
                         help="skip the sweep, just merge whatever's already in results/ into cache_sweep_results.csv")
    parser.add_argument("--native-bin", type=pathlib.Path, default=NATIVE_BIN,
                         help="path to the native cache_sweep binary (default: native/cache_sweep)")
    parser.add_argument("--results-dir", type=pathlib.Path, default=RESULTS_DIR,
                         help="per-unit CSV cache dir (default: results/); use a separate dir for subset runs "
                              "so they don't collide with a full-grid run's cached units")
    parser.add_argument("--out", type=pathlib.Path, default=None,
                         help="merged output CSV path (default: cache_sweep_results.csv next to this script)")
    parser.add_argument("--struct-ids", type=str, default=None,
                         help="comma-separated STRUCTS indices to pass to the native binary, e.g. '0,1,3,4' "
                              "for direct_mapped+4/16/32-way (skip 8-way and fully_associative); default: all 6")
    parser.add_argument("--max-samples", type=int, default=None,
                         help="only read the first N sample files per unit instead of all of them")
    args = parser.parse_args()

    NATIVE_BIN = args.native_bin
    RESULTS_DIR = args.results_dir
    STRUCT_IDS = args.struct_ids
    MAX_SAMPLES = args.max_samples

    if not NATIVE_BIN.exists():
        sys.exit(f"native binary not found at {NATIVE_BIN}; run `make` in profiling/0726/native/ first")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.merge_only:
        units = discover_units()
        units = [u for u in units if not (RESULTS_DIR / f"{u[0]}__{u[1]}__{u[2]}.csv").exists()]
        print(f"sizing {len(units)} not-yet-done units for smallest-first scheduling...", flush=True)
        units.sort(key=_one_sample_element_count)
        print(f"{len(units)} (arch, workload, layer) units to run, {args.workers} workers", flush=True)
        with mp.Pool(args.workers) as pool:
            for msg in pool.imap_unordered(run_unit, units):
                print(msg, flush=True)

    merged_path = args.out or pathlib.Path(__file__).resolve().parent / "cache_sweep_results.csv"
    n_rows = merge_results(merged_path)
    print(f"merged {n_rows} rows into {merged_path}", flush=True)


if __name__ == "__main__":
    main()
