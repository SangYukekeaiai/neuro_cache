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
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
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
ARCHS_FILTER: List[str] | None = None
INNER_DIMS: str | None = None  # comma-separated indices (0=kh,1=kw,2=cin,3=cout), see native/cache_sweep.cpp argv[3]
SIZES: str | None = None       # comma-separated byte values, see native/cache_sweep.cpp argv[4]
LAYOUT: str | None = None      # "cout_only" (default) or "cin_cout_2d", see native/cache_sweep.cpp argv[5]

_INNER_DIM_TO_INDEX = {"kh": "0", "kw": "1", "cin": "2", "cout": "3"}

ARCHS = ["loas", "ptb", "spinalflow", "prosperity", "gustavsnn"]
WORKLOADS = ["resnet19_T4_all", "vgg16_T4_all"]

CSV_HEADER = "arch,workload,layer,cache_type,associativity,size_bytes,inner_dim,layout,line_size,mean_hit_rate,n_samples\n"


def discover_units() -> List[Tuple[str, str, str]]:
    """(arch, workload, layer) triples for every layer dir that actually
    exists locally under outputs/weight_traces/ -- only archs/workloads
    present on disk are swept, nothing is assumed."""
    units = []
    for arch in (ARCHS_FILTER if ARCHS_FILTER is not None else ARCHS):
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

    # Positional argv beyond the binary path: struct_ids, persample-flag
    # (always empty from this mean-only driver), inner_dims, sizes, layout
    # -- see native/cache_sweep.cpp's argv[1..5] docstrings. Trailing
    # empties are trimmed so an old-style struct-ids-only invocation still
    # gets the short argv it always has (native/cache_sweep.cpp's own argc
    # checks don't care either way, but this keeps `ps`/logs readable).
    argv = [str(NATIVE_BIN), STRUCT_IDS or "", "", INNER_DIMS or "", SIZES or "", LAYOUT or ""]
    while len(argv) > 1 and argv[-1] == "":
        argv.pop()
    proc = subprocess.run(argv, input=payload, capture_output=True, text=False)

    if proc.returncode != 0:
        return f"FAILED: {arch}/{workload}/{layer}: {proc.stderr.decode(errors='replace').strip()}"

    with open(result_path, "w") as out:
        out.write(CSV_HEADER)
        for line in proc.stdout.decode().splitlines():
            out.write(f"{arch},{workload},{layer},{line}\n")

    elapsed = time.time() - t0
    return f"done: {arch}/{workload}/{layer} ({n_samples} samples, {elapsed:.1f}s)"


MAX_POOL_RESTARTS = 5


def _run_units(units: List[Tuple[str, str, str]], workers: int) -> None:
    """Run every unit, restarting the executor if a worker dies without
    reporting back. A native binary getting OOM-killed is handled inside
    run_unit() itself (subprocess.run just sees a bad returncode) -- but
    if system-wide memory pressure kills a *worker process*, the plain
    multiprocessing.Pool used previously would hang forever waiting on a
    result that will never arrive (a known stdlib gap: Pool doesn't
    detect a SIGKILL'd worker). ProcessPoolExecutor does detect it and
    raises BrokenProcessPool on the surviving futures instead, so this
    catches that and resumes with a fresh pool rather than hanging (this
    is exactly what happened twice during the 2026-07-27 sweep runs, see
    log/2026-07-26-workflow-optimization-plan.md)."""
    remaining = list(units)
    restarts = 0
    while remaining:
        broken = False
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_unit, u): u for u in remaining}
            for future in as_completed(futures):
                try:
                    print(future.result(), flush=True)
                except BrokenProcessPool:
                    broken = True
                    break

        remaining = [
            u for u in remaining
            if not (RESULTS_DIR / f"{u[0]}__{u[1]}__{u[2]}.csv").exists()
        ]
        if not broken or not remaining:
            break
        restarts += 1
        if restarts > MAX_POOL_RESTARTS:
            print(f"giving up after {MAX_POOL_RESTARTS} pool restarts; "
                  f"{len(remaining)} units still unfinished: "
                  f"{[' / '.join(u) for u in remaining]}", flush=True)
            break
        print(f"pool broke (a worker was likely OOM-killed); restarting "
              f"({len(remaining)} units left, restart {restarts}/{MAX_POOL_RESTARTS})", flush=True)


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
    global NATIVE_BIN, RESULTS_DIR, STRUCT_IDS, MAX_SAMPLES, ARCHS_FILTER, INNER_DIMS, SIZES, LAYOUT

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
    parser.add_argument("--archs", nargs="+", default=None,
                         help="restrict discover_units() to these archs instead of all archs with local "
                              "weight-trace data, e.g. --archs loas")
    parser.add_argument("--inner-dims", nargs="+", default=None, choices=list(_INNER_DIM_TO_INDEX),
                         help="restrict the native binary's sweep to these inner_dims (default: all 4); "
                              "matters for speed, not just row count -- see native/cache_sweep.cpp's argv[3] note")
    parser.add_argument("--sizes", nargs="+", type=int, default=None,
                         help="restrict to these cache_size_bytes values, each one of 8192/16384/32768/65536 "
                              "(default: all 4), e.g. --sizes 16384 32768 65536")
    parser.add_argument("--layout", choices=["cout_only", "cin_cout_2d"], default=None,
                         help="cache-line layout to sweep (default: cout_only, today's behavior); "
                              "cin_cout_2d is Stage 2 Path A of "
                              "log/2026-07-28-set-index-and-cin-cout-layout-plan.md, only affects "
                              "inner_dim=cout, see native/cache_sweep.cpp's argv[5] note")
    args = parser.parse_args()

    NATIVE_BIN = args.native_bin
    RESULTS_DIR = args.results_dir
    STRUCT_IDS = args.struct_ids
    MAX_SAMPLES = args.max_samples
    ARCHS_FILTER = args.archs
    INNER_DIMS = ",".join(_INNER_DIM_TO_INDEX[d] for d in args.inner_dims) if args.inner_dims else None
    SIZES = ",".join(str(s) for s in args.sizes) if args.sizes else None
    LAYOUT = args.layout

    if not NATIVE_BIN.exists():
        sys.exit(f"native binary not found at {NATIVE_BIN}; run `make` in profiling/0726/native/ first")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.merge_only:
        units = discover_units()
        units = [u for u in units if not (RESULTS_DIR / f"{u[0]}__{u[1]}__{u[2]}.csv").exists()]
        print(f"sizing {len(units)} not-yet-done units for smallest-first scheduling...", flush=True)
        units.sort(key=_one_sample_element_count)
        print(f"{len(units)} (arch, workload, layer) units to run, {args.workers} workers", flush=True)
        _run_units(units, args.workers)

    merged_path = args.out or pathlib.Path(__file__).resolve().parent / "cache_sweep_results.csv"
    n_rows = merge_results(merged_path)
    print(f"merged {n_rows} rows into {merged_path}", flush=True)


if __name__ == "__main__":
    main()
