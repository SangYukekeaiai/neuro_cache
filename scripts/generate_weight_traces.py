#!/usr/bin/env python3
"""Stage 2 of the generate-once weight-trace pipeline: for one (arch,
trace_dir, layer), load its Stage-1-cached schedule (no re-solving, no
Gurobi) and reconstruct a range of real captured samples against it,
persisting one JSON per sample to
outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/sample_<i5>.json.

This is the embarrassingly-parallel stage: every sample is independent
given the cached schedule, so --workers fans out across local CPU cores
via multiprocessing. Per the design doc's own estimate (~753 CPU-hours
for the full sweep, ~5.2 hours on one 144-core node), this comfortably
fits on a single node -- no slurm array/job-list scaffolding is needed,
just --sample-start/--sample-count if you do want to split work across
multiple jobs by hand.

See docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md.
"""

from __future__ import annotations

import argparse
import multiprocessing
import pathlib
import sys
import traceback
from typing import List, Sequence

sys.path.insert(0, "src")

from snn_cosa import tracegen
from snn_cosa.archmodels.trace import load_layer_trace

DEFAULT_TRACE_ROOT = pathlib.Path("/u/yyu9/neuro_cache_trace/input_trace/loas")

# Populated once per worker process by _init_worker, read by _process_chunk.
# Passing `trace` this way (via Pool initargs, set once per worker) rather
# than as a per-task argument matters: a memmap'd array (see
# archmodels/trace.py's load_layer_trace(mmap=True)) pickles cheaply by
# file/offset/shape, so this happens once per worker, not once per sample.
_STATE = {}


def _init_worker(model_cls, trace, tiles, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps, out_dir):
    _STATE["model"] = model_cls()
    _STATE["trace"] = trace
    _STATE["tiles"] = tiles
    _STATE["arch_name"] = arch_name
    _STATE["trace_dir_name"] = trace_dir_name
    _STATE["layer_name"] = layer_name
    _STATE["workload_dims"] = workload_dims
    _STATE["dram_num_steps"] = dram_num_steps
    _STATE["out_dir"] = out_dir


def _process_chunk(sample_indices: Sequence[int]) -> int:
    layer_traces = tracegen.reconstruct_samples_for_schedule(
        _STATE["model"], _STATE["trace"], _STATE["tiles"], sample_indices,
        _STATE["arch_name"], _STATE["trace_dir_name"], _STATE["layer_name"],
        _STATE["workload_dims"], _STATE["dram_num_steps"],
    )
    for lt in layer_traces:
        out_path = (
            _STATE["out_dir"] / _STATE["arch_name"] / _STATE["trace_dir_name"]
            / _STATE["layer_name"] / f"sample_{lt.sample_idx:05d}.json"
        )
        tracegen.save_weight_trace(lt, out_path)
    return len(layer_traces)


def _chunks(seq: List[int], n_chunks: int) -> List[List[int]]:
    if n_chunks <= 1 or len(seq) <= 1:
        return [seq]
    size = max(1, len(seq) // n_chunks)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arch", required=True, choices=list(tracegen.ARCH_MODELS))
    p.add_argument("--trace-dir", required=True, help="e.g. vgg16_T4_all")
    p.add_argument("--layer", required=True, help="e.g. layer_01_features_3")
    p.add_argument("--trace-root", default=str(DEFAULT_TRACE_ROOT))
    p.add_argument("--schedule-cache", default="outputs/schedules")
    p.add_argument("--out-dir", default="outputs/weight_traces")
    p.add_argument("--sample-start", type=int, default=0)
    p.add_argument("--sample-count", type=int, required=True)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--force", action="store_true", help="Regenerate samples even if already present.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    trace_root = pathlib.Path(args.trace_root)
    schedule_path = pathlib.Path(args.schedule_cache) / args.arch / args.trace_dir / f"{args.layer}.json"
    if not schedule_path.exists():
        print(f"ERROR: no cached schedule at {schedule_path} -- run solve_schedules.py first")
        return 1

    out_dir = pathlib.Path(args.out_dir)
    layer_out_dir = out_dir / args.arch / args.trace_dir / args.layer

    requested = list(range(args.sample_start, args.sample_start + args.sample_count))
    if args.force:
        todo = requested
    else:
        todo = [i for i in requested if not (layer_out_dir / f"sample_{i:05d}.json").exists()]
    n_skipped = len(requested) - len(todo)
    if n_skipped:
        print(f"Skipping {n_skipped} already-generated sample(s)")
    if not todo:
        print("Nothing to do.")
        return 0

    artifact, prob, tiles = tracegen.load_schedule(schedule_path)
    trace = load_layer_trace(trace_root / args.trace_dir, args.layer, mmap=True)
    model_cls = tracegen.ARCH_MODELS[args.arch]

    print(f"Reconstructing {len(todo)} sample(s) of {args.arch}/{args.trace_dir}/{args.layer} "
          f"({len(tiles)} tiles/sample) with {args.workers} worker(s)")

    try:
        if args.workers <= 1:
            _init_worker(model_cls, trace, tiles, args.arch, args.trace_dir, args.layer,
                         artifact.workload["problem"], artifact.dram_num_steps, out_dir)
            n_done = _process_chunk(todo)
        else:
            chunks = _chunks(todo, args.workers)
            with multiprocessing.Pool(
                processes=args.workers,
                initializer=_init_worker,
                initargs=(model_cls, trace, tiles, args.arch, args.trace_dir, args.layer,
                          artifact.workload["problem"], artifact.dram_num_steps, out_dir),
            ) as pool:
                n_done = sum(pool.map(_process_chunk, chunks))
    except Exception:
        traceback.print_exc()
        return 1

    print(f"Wrote {n_done} sample(s) to {layer_out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
