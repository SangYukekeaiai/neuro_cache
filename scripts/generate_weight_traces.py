#!/usr/bin/env python3
"""Stage 2 of the generate-once weight-trace pipeline: load a Stage-1-cached
schedule (no re-solving, no Gurobi) and reconstruct real captured samples
against it through the arch's native C++ bridge, persisting one JSON per
sample to outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/sample_<i5>.json.gz.

Two modes:

  One explicit combo (default): reconstructs --n-samples (or an explicit
  --sample-start/--sample-count range) for one --arch/--trace-dir/--layer.
  Parallelizes by chunking SAMPLES across --workers -- the trace for that
  one layer is loaded once per worker (via Pool initargs, not per task) and
  every worker reconstructs a different slice of the same sample list.

  --all-layers: reconstructs the same sample selection across every valid
  layer of both trace dirs for one --arch. Parallelizes by TASK (one
  (trace_dir, layer) per worker) instead, in two passes -- the first
  FIRST_PASS_SAMPLES samples across every layer, then the rest -- so a
  coverage milestone (some samples for every layer) lands before spending
  remaining time going deeper on earlier layers. Each task chunks its own
  samples into SAMPLE_CHUNK_SIZE-sized groups to bound peak memory (a dense
  layer's full per-tile weight-address list for many samples at once can
  OOM); run via srun on a compute node, not the login node, timing on real
  data showed 2-5s/sample per (arch, layer).

Neither mode contains any native-bridge dispatch of its own -- both call
tracegen.reconstruct_samples, the single consolidated dispatcher, and
tracegen.save_weight_trace for persistence. This script owns only CLI
parsing, which combos/samples to iterate, and worker-pool setup.

See dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Sequence

sys.path.insert(0, "src")

import tracegen
from archmodels import ARCH_NATIVE_BRIDGES
from archmodels.trace import load_layer_trace, valid_layer_names

# The sibling capture repo this used to point at, /u/yyu9/neuro_cache_trace,
# was deleted between the 2026-08-11 and 2026-08-12 home snapshots. The
# in-repo traces are a 5-sample subset of the same capture, cut by
# scripts/subset_input_traces.py; pass --trace-root to use a full capture.
DEFAULT_TRACE_ROOT = pathlib.Path("input_trace/loas")
DEFAULT_TRACE_DIRS = ["resnet19_T4_n5", "vgg16_T4_n5"]

# --all-layers only: chunk size for regenerate_layer's inner loop (bounds
# peak memory -- the native call holds every requested sample's full
# per-tile weight-address list in memory at once; a dense layer at
# chunk_size=100 OOM'd on real data, see log/2026-07-26-workflow-optimization-plan.md).
SAMPLE_CHUNK_SIZE = 10
# --all-layers only: samples covered in the first pass across every layer,
# before the second pass fills in the rest of the requested samples.
FIRST_PASS_SAMPLES = 10


# ----------------------------------------------------------------------
# Shared: sample selection
# ----------------------------------------------------------------------

def _resolve_samples(args: argparse.Namespace) -> List[int]:
    if args.sample_count is not None:
        return list(range(args.sample_start, args.sample_start + args.sample_count))
    return tracegen.sample_indices(n=args.n_samples, seed=args.seed)


# ----------------------------------------------------------------------
# Mode 1: one explicit (arch, trace_dir, layer) combo, sample-chunked workers
# ----------------------------------------------------------------------

# Populated once per worker process by _init_worker, read by _process_chunk.
# Passing `trace` this way (via Pool initargs, set once per worker) rather
# than as a per-task argument matters: a memmap'd array (see
# archmodels/trace.py's load_layer_trace(mmap=True)) pickles cheaply by
# file/offset/shape, so this happens once per worker, not once per sample.
_STATE = {}


def _init_worker(trace, tiles, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps, out_dir, combo_tag=""):
    _STATE["trace"] = trace
    _STATE["tiles"] = tiles
    _STATE["arch_name"] = arch_name
    _STATE["trace_dir_name"] = trace_dir_name
    _STATE["layer_name"] = layer_name
    _STATE["workload_dims"] = workload_dims
    _STATE["dram_num_steps"] = dram_num_steps
    _STATE["out_dir"] = out_dir
    _STATE["combo_tag"] = combo_tag


def _process_chunk(sample_indices: Sequence[int]) -> int:
    layer_traces = tracegen.reconstruct_samples(
        _STATE["arch_name"], _STATE["trace"], _STATE["tiles"], sample_indices,
        _STATE["trace_dir_name"], _STATE["layer_name"],
        _STATE["workload_dims"], _STATE["dram_num_steps"],
    )
    for lt in layer_traces:
        out_path = (
            _STATE["out_dir"] / _STATE["arch_name"] / _STATE["combo_tag"] / _STATE["trace_dir_name"]
            / _STATE["layer_name"] / f"sample_{lt.sample_idx:05d}.json.gz"
        )
        tracegen.save_weight_trace(lt, out_path)
    return len(layer_traces)


def _chunks(seq: List[int], n_chunks: int) -> List[List[int]]:
    if n_chunks <= 1 or len(seq) <= 1:
        return [seq]
    size = max(1, len(seq) // n_chunks)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def run_one_combo(args: argparse.Namespace) -> int:
    trace_root = pathlib.Path(args.trace_root)
    schedule_path = pathlib.Path(args.schedule_cache) / args.arch / args.trace_dir / f"{args.layer}.json"
    if not schedule_path.exists():
        print(f"ERROR: no cached schedule at {schedule_path} -- run solve_schedules.py first")
        return 1

    out_dir = pathlib.Path(args.out_dir)
    combo_tag = args.combo_tag or ""
    layer_out_dir = out_dir / args.arch / combo_tag / args.trace_dir / args.layer

    requested = _resolve_samples(args)
    if args.force:
        todo = requested
    else:
        todo = [i for i in requested if not (layer_out_dir / f"sample_{i:05d}.json.gz").exists()]
    n_skipped = len(requested) - len(todo)
    if n_skipped:
        print(f"Skipping {n_skipped} already-generated sample(s)")
    if not todo:
        print("Nothing to do.")
        return 0

    artifact, prob, tiles = tracegen.load_schedule(schedule_path)
    trace = load_layer_trace(trace_root / args.trace_dir, args.layer, mmap=True)

    print(f"Reconstructing {len(todo)} sample(s) of {args.arch}/{combo_tag}/{args.trace_dir}/{args.layer} "
          f"({len(tiles)} tiles/sample) with {args.workers} worker(s)")

    try:
        if args.workers <= 1:
            _init_worker(trace, tiles, args.arch, args.trace_dir, args.layer,
                         artifact.workload["problem"], artifact.dram_num_steps, out_dir, combo_tag)
            n_done = _process_chunk(todo)
        else:
            chunks = _chunks(todo, args.workers)
            with multiprocessing.Pool(
                processes=args.workers,
                initializer=_init_worker,
                initargs=(trace, tiles, args.arch, args.trace_dir, args.layer,
                          artifact.workload["problem"], artifact.dram_num_steps, out_dir, combo_tag),
            ) as pool:
                n_done = sum(pool.map(_process_chunk, chunks))
    except Exception:
        traceback.print_exc()
        return 1

    print(f"Wrote {n_done} sample(s) to {layer_out_dir}")
    return 0


# ----------------------------------------------------------------------
# Mode 2: --all-layers, task-chunked workers (one (trace_dir, layer) each)
# ----------------------------------------------------------------------

def _layers_for(trace_root: pathlib.Path, trace_dir_name: str) -> List[str]:
    with open(trace_root / trace_dir_name / "meta.json") as fh:
        meta = json.load(fh)
    return valid_layer_names(meta)


def _all_layer_targets(trace_root: pathlib.Path, trace_dirs: Sequence[str]):
    return [
        (trace_dir_name, layer_name)
        for trace_dir_name in trace_dirs
        for layer_name in _layers_for(trace_root, trace_dir_name)
    ]


def _regenerate_layer(arch_name, trace_root, schedule_cache, out_root, trace_dir_name, layer_name, indices):
    """Reconstruct and save whichever of `indices` aren't already saved for
    this (arch, trace_dir, layer). Returns (num_done, seconds)."""
    out_dir = out_root / arch_name / trace_dir_name / layer_name
    out_dir.mkdir(parents=True, exist_ok=True)

    missing = [i for i in indices if not (out_dir / f"sample_{i:05d}.json.gz").exists()]
    if not missing:
        return 0, 0.0

    sched_path = schedule_cache / arch_name / trace_dir_name / f"{layer_name}.json"
    t0 = time.time()
    artifact, prob, tiles = tracegen.load_schedule(sched_path)
    trace = load_layer_trace(trace_root / trace_dir_name, layer_name, mmap=True)
    for chunk_start in range(0, len(missing), SAMPLE_CHUNK_SIZE):
        chunk = missing[chunk_start:chunk_start + SAMPLE_CHUNK_SIZE]
        traces = tracegen.reconstruct_samples(
            arch_name, trace, tiles, chunk, trace_dir_name, layer_name,
            artifact.workload["problem"], artifact.dram_num_steps,
        )
        for t in traces:
            tracegen.save_weight_trace(t, out_dir / f"sample_{t.sample_idx:05d}.json.gz")
    return len(missing), time.time() - t0


def _regenerate_one_layer_task(task) -> tuple:
    arch_name, trace_root, schedule_cache, out_root, trace_dir_name, layer_name, indices = task
    n, dt = _regenerate_layer(arch_name, trace_root, schedule_cache, out_root, trace_dir_name, layer_name, indices)
    return trace_dir_name, layer_name, n, dt


def _run_pass(arch_name, trace_root, schedule_cache, out_root, trace_dirs, indices, label, max_workers):
    targets = _all_layer_targets(trace_root, trace_dirs)
    print(f"=== {arch_name}: {label} ({len(indices)} samples), "
          f"{len(targets)} layers, {max_workers} workers ===", flush=True)
    tasks = [
        (arch_name, trace_root, schedule_cache, out_root, trace_dir_name, layer_name, indices)
        for trace_dir_name, layer_name in targets
    ]

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_regenerate_one_layer_task, task): task for task in tasks}
        for future in as_completed(futures):
            _, task_trace_dir_name, task_layer_name, _, _, _, _ = futures[future]
            try:
                trace_dir_name, layer_name, n, dt = future.result()
            except Exception as exc:  # noqa: BLE001 -- a real compute-node failure for one layer shouldn't sink the rest
                print(f"  {task_trace_dir_name}/{task_layer_name}: FAILED ({exc!r})", flush=True)
                continue
            if n == 0:
                print(f"  {trace_dir_name}/{layer_name}: already complete, skip", flush=True)
            else:
                print(f"  {trace_dir_name}/{layer_name}: {n} samples in {dt:.1f}s "
                      f"({dt / n:.2f}s/sample)", flush=True)


def run_all_layers(args: argparse.Namespace) -> int:
    import os

    trace_root = pathlib.Path(args.trace_root)
    schedule_cache = pathlib.Path(args.schedule_cache)
    out_root = pathlib.Path(args.out_dir)
    max_workers = args.workers if args.workers > 0 else len(os.sched_getaffinity(0))

    indices = _resolve_samples(args)
    first_pass = indices[:FIRST_PASS_SAMPLES]
    _run_pass(args.arch, trace_root, schedule_cache, out_root, args.trace_dirs,
              first_pass, f"pass 1, first {len(first_pass)}", max_workers)
    _run_pass(args.arch, trace_root, schedule_cache, out_root, args.trace_dirs,
              indices, "pass 2, remaining", max_workers)
    return 0


# ----------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arch", required=True, choices=sorted(ARCH_NATIVE_BRIDGES))
    p.add_argument("--all-layers", action="store_true",
                   help="Reconstruct every valid layer of --trace-dirs instead of one --trace-dir/--layer combo.")
    p.add_argument("--trace-dir", help="e.g. vgg16_T4_n5 (single-combo mode only)")
    p.add_argument("--layer", help="e.g. layer_01_features_3 (single-combo mode only)")
    p.add_argument("--trace-dirs", nargs="+", default=DEFAULT_TRACE_DIRS,
                   help="--all-layers mode only (default: both).")
    p.add_argument("--trace-root", default=str(DEFAULT_TRACE_ROOT))
    p.add_argument("--schedule-cache", default="outputs/schedules")
    p.add_argument("--out-dir", default="outputs/weight_traces")
    p.add_argument("--combo-tag", default="",
                   help="Optional path segment inserted as <out-dir>/<arch>/<combo-tag>/<trace-dir>/<layer>/ "
                        "(single-combo mode only). Disambiguates output across arch-config sweeps (e.g. "
                        "different instances/node/noc sizes) that reuse the same --schedule-cache directory "
                        "structure otherwise. Empty (default) reproduces the original "
                        "<out-dir>/<arch>/<trace-dir>/<layer>/ layout exactly.")
    p.add_argument("--sample-start", type=int, default=0)
    p.add_argument("--sample-count", type=int,
                   help="Explicit sample range (single-combo mode only); mutually exclusive with --n-samples.")
    p.add_argument("--n-samples", type=int, default=100,
                   help="Fixed, reproducible n-sample subset (tracegen.sample_indices); "
                        "n=100 (the default) is the canonical subset. Default: 100.")
    p.add_argument("--seed", type=int, default=0, help="Seed for the samples beyond the canonical 100.")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--force", action="store_true", help="Regenerate samples even if already present.")
    args = p.parse_args()

    if args.sample_count is not None and args.n_samples != 100:
        p.error("specify --sample-count or --n-samples, not both")
    if args.all_layers:
        if args.sample_count is not None:
            p.error("--sample-count is not supported with --all-layers; use --n-samples")
        if args.trace_dir or args.layer:
            p.error("--trace-dir/--layer are not used with --all-layers; use --trace-dirs")
    else:
        if not args.trace_dir or not args.layer:
            p.error("--trace-dir and --layer are required unless --all-layers is set")
    return args


def main() -> int:
    args = parse_args()
    if args.all_layers:
        return run_all_layers(args)
    return run_one_combo(args)


if __name__ == "__main__":
    raise SystemExit(main())
