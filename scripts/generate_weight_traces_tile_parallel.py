#!/usr/bin/env python3
"""Experimental alternate to generate_weight_traces.py: parallelize by
CHUNKING TILES across workers instead of chunking samples. Standalone
script (does not modify generate_weight_traces.py) so the two can be
run side-by-side and their outputs diffed for correctness, and so this
is trivial to delete if the experiment doesn't pan out.

See tracegen.reconstruct_tile_chunk's docstring for the motivation:
GustavSNN's `tiles` list has one entry per tick (up to ~8000 on real
resnet19 layers), and generate_weight_traces.py's sample-chunking
reruns that whole per-tile Python loop once per worker. This script
chunks tiles instead, so each tile's loop iteration happens exactly
once total regardless of worker count -- at the cost of a reduce step
(every worker's partial per-tile results must be gathered and merged
into per-sample traces before writing, instead of each worker writing
its own samples directly).
"""

from __future__ import annotations

import argparse
import multiprocessing
import pathlib
import sys
import time
import traceback
from typing import List, Sequence, Tuple

sys.path.insert(0, "src")

import tracegen
from archmodels.trace import load_layer_trace

DEFAULT_TRACE_ROOT = pathlib.Path("/u/yyu9/neuro_cache_trace/input_trace/loas")

_STATE = {}


def _init_worker(model_cls, trace, sample_indices):
    _STATE["model"] = model_cls()
    _STATE["trace"] = trace
    _STATE["sample_indices"] = sample_indices


def _process_tile_chunk(tile_chunk: Sequence[Tuple[int, object]]):
    return tracegen.reconstruct_tile_chunk(
        _STATE["model"], _STATE["trace"], tile_chunk, _STATE["sample_indices"]
    )


def _chunks(seq: List, n_chunks: int) -> List[List]:
    if n_chunks <= 1 or len(seq) <= 1:
        return [seq]
    size = max(1, len(seq) // n_chunks)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arch", required=True, choices=list(tracegen.ARCH_MODELS))
    p.add_argument("--trace-dir", required=True)
    p.add_argument("--layer", required=True)
    p.add_argument("--trace-root", default=str(DEFAULT_TRACE_ROOT))
    p.add_argument("--schedule-cache", default="outputs/schedules")
    p.add_argument("--out-dir", required=True, help="Separate from production out-dir for this experiment.")
    p.add_argument("--sample-start", type=int, default=0)
    p.add_argument("--sample-count", type=int)
    p.add_argument(
        "--canonical-samples", action="store_true",
        help="Use the fixed canonical 100-sample subset "
             "(configs/sampling/sample_indices.json, seed 0) instead of "
             "--sample-start/--sample-count.",
    )
    p.add_argument(
        "--n-samples", type=int,
        help="Use a fixed, reproducible n-sample subset "
             "(tracegen.random_sample_indices: the canonical 100 plus "
             "n-100 more, seeded by --seed) instead of "
             "--sample-start/--sample-count.",
    )
    p.add_argument("--seed", type=int, default=0, help="Seed for --n-samples.")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--force", action="store_true", help="Regenerate samples even if already present.")
    args = p.parse_args()
    n_modes = sum([args.canonical_samples, args.sample_count is not None, args.n_samples is not None])
    if n_modes != 1:
        p.error("specify exactly one of --canonical-samples, --sample-count, or --n-samples")
    return args


def main() -> int:
    args = parse_args()
    trace_root = pathlib.Path(args.trace_root)
    schedule_path = pathlib.Path(args.schedule_cache) / args.arch / args.trace_dir / f"{args.layer}.json"
    if not schedule_path.exists():
        print(f"ERROR: no cached schedule at {schedule_path} -- run solve_schedules.py first")
        return 1

    out_dir = pathlib.Path(args.out_dir)
    layer_out_dir = out_dir / args.arch / args.trace_dir / args.layer

    if args.canonical_samples:
        requested = tracegen.canonical_sample_indices()
    elif args.n_samples is not None:
        requested = tracegen.random_sample_indices(args.n_samples, seed=args.seed)
    else:
        requested = list(range(args.sample_start, args.sample_start + args.sample_count))
    if args.force:
        sample_indices = requested
    else:
        sample_indices = [i for i in requested if not (layer_out_dir / f"sample_{i:05d}.json.gz").exists()]
    n_skipped = len(requested) - len(sample_indices)
    if n_skipped:
        print(f"Skipping {n_skipped} already-generated sample(s)")
    if not sample_indices:
        print("Nothing to do.")
        return 0

    artifact, prob, tiles = tracegen.load_schedule(schedule_path)
    trace = load_layer_trace(trace_root / args.trace_dir, args.layer, mmap=True)
    model_cls = tracegen.ARCH_MODELS[args.arch]
    indexed_tiles = list(enumerate(tiles))

    print(f"[tile-parallel] Reconstructing {len(sample_indices)} sample(s) of "
          f"{args.arch}/{args.trace_dir}/{args.layer} ({len(tiles)} tiles/sample) "
          f"with {args.workers} worker(s), chunked by TILE")

    t0 = time.time()
    try:
        per_sample_tiles: List[List[object]] = [[None] * len(tiles) for _ in sample_indices]
        if args.workers <= 1:
            _init_worker(model_cls, trace, sample_indices)
            results = [_process_tile_chunk(indexed_tiles)]
        else:
            chunks = _chunks(indexed_tiles, args.workers)
            with multiprocessing.Pool(
                processes=args.workers,
                initializer=_init_worker,
                initargs=(model_cls, trace, sample_indices),
            ) as pool:
                results = pool.map(_process_tile_chunk, chunks)

        for chunk_result in results:
            for orig_idx, per_sample in chunk_result:
                for i, twt in enumerate(per_sample):
                    per_sample_tiles[i][orig_idx] = twt

        for i, sample_idx in enumerate(sample_indices):
            assert all(t is not None for t in per_sample_tiles[i]), "reassembly gap"
            lt = tracegen.LayerWeightTrace(
                arch=args.arch, trace_dir=args.trace_dir, layer_name=args.layer,
                sample_idx=sample_idx, workload_dims=artifact.workload["problem"],
                dram_num_steps=artifact.dram_num_steps, tiles=per_sample_tiles[i],
            )
            out_path = layer_out_dir / f"sample_{sample_idx:05d}.json.gz"
            tracegen.save_weight_trace(lt, out_path)
    except Exception:
        traceback.print_exc()
        return 1

    elapsed = time.time() - t0
    print(f"[tile-parallel] Wrote {len(sample_indices)} sample(s) to {layer_out_dir} in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
