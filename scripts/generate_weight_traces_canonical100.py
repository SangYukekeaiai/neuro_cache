#!/usr/bin/env python3
"""Regenerate weight-address traces for the canonical, fixed set of 100
samples (configs/sampling/sample_indices.json, seed 0 -- see
tracegen.canonical_sample_indices), all 31 valid layers, one arch at a
time, entirely from already-cached schedules (outputs/schedules/) -- no
Gurobi re-solve needed. Saved to outputs/weight_traces/, the same tree
scripts/generate_weight_traces.py writes the full 10,000-sample sweep
into: this script's 100 canonical samples are a subset of that same
range, so they merge into it rather than living as a separate copy.

Run via srun on a compute node, not directly on the login node: timing
on real data showed 2-5s/sample per (arch, layer), making the full
100-sample x 31-layer x 5-arch run multiple hours of CPU time, well past
NCSA's 30-minute login-node process cap.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from archmodels.trace import load_layer_trace, valid_layer_names
from tracegen import (
    ARCH_MODELS,
    canonical_sample_indices,
    load_schedule,
    reconstruct_samples_for_schedule,
    save_weight_trace,
)

# Archs with a native C++ reconstruction path (src/archmodels/<arch>/native/),
# each verified byte-identical against reconstruct_samples_for_schedule on
# real data before being added here. See generate_weight_traces.py's
# identical registry.
_NATIVE_BRIDGE_MODULES = {
    "gustavsnn": "archmodels.gustavsnn.native_bridge",
    "spinalflow": "archmodels.spinalflow.native_bridge",
    "loas": "archmodels.loas.native_bridge",
    "ptb": "archmodels.ptb.native_bridge",
    "prosperity": "archmodels.prosperity.native_bridge",
}


def _native_reconstruct_fn(arch_name):
    module_name = _NATIVE_BRIDGE_MODULES.get(arch_name)
    if module_name is None:
        return None
    import importlib
    return importlib.import_module(module_name).reconstruct_samples_native


SCHEDULE_DIR = _REPO_ROOT / "outputs" / "schedules"
INPUT_TRACE_ROOT = pathlib.Path("/u/yyu9/neuro_cache_trace/input_trace/loas")
OUT_ROOT = _REPO_ROOT / "outputs" / "weight_traces"
TRACE_DIRS = ["resnet19_T4_all", "vgg16_T4_all"]

# reconstruct_samples_for_schedule holds every requested sample's full
# per-tile weight-address list in memory at once; batching all 100 in one
# call OOM'd on a dense layer (layer_01, 8192 tiles, ~737k addresses/sample).
# Chunking bounds peak memory regardless of layer size.
SAMPLE_CHUNK_SIZE = 10

# First pass covers this many samples across every layer before the second
# pass fills in the rest, so a coverage milestone (some samples for every
# layer) is reached before spending the remaining time going deeper on
# earlier layers.
FIRST_PASS_SAMPLES = 10


def layers_for(trace_dir_name):
    with open(INPUT_TRACE_ROOT / trace_dir_name / "meta.json") as fh:
        meta = json.load(fh)
    return valid_layer_names(meta)


def regenerate_layer(arch_name, model, trace_dir_name, layer_name, indices):
    """Reconstruct and save whichever of `indices` aren't already saved
    for this (arch, trace_dir, layer). Returns (num_done, seconds)."""
    out_dir = OUT_ROOT / arch_name / trace_dir_name / layer_name
    out_dir.mkdir(parents=True, exist_ok=True)

    missing = [i for i in indices if not (out_dir / f"sample_{i:05d}.json.gz").exists()]
    if not missing:
        return 0, 0.0

    sched_path = SCHEDULE_DIR / arch_name / trace_dir_name / f"{layer_name}.json"
    t0 = time.time()
    artifact, prob, tiles = load_schedule(sched_path)
    # mmap=True: trace files run up to 2.6GB each; with up to 16 workers
    # (_run_pass's ProcessPoolExecutor) each potentially loading a
    # different layer's full trace at once, eager loading (the default)
    # OOM-killed a real run (2026-07-26). Matches generate_weight_traces.py's
    # own mmap=True, which never had this bug.
    trace = load_layer_trace(INPUT_TRACE_ROOT / trace_dir_name, layer_name, mmap=True)
    native_fn = _native_reconstruct_fn(arch_name)
    for chunk_start in range(0, len(missing), SAMPLE_CHUNK_SIZE):
        chunk = missing[chunk_start:chunk_start + SAMPLE_CHUNK_SIZE]
        if native_fn is not None:
            # No `model` needed -- the C++ side embeds the arch's
            # algorithm directly, no Protocol dispatch.
            traces = native_fn(
                trace, tiles, chunk, arch_name, trace_dir_name, layer_name,
                artifact.workload["problem"], artifact.dram_num_steps,
            )
        else:
            traces = reconstruct_samples_for_schedule(
                model, trace, tiles, chunk, arch_name, trace_dir_name, layer_name,
                artifact.workload["problem"], artifact.dram_num_steps,
            )
        for t in traces:
            save_weight_trace(t, out_dir / f"sample_{t.sample_idx:05d}.json.gz")
    return len(missing), time.time() - t0


def _all_layer_targets():
    """[(trace_dir_name, layer_name), ...] for every valid layer, both networks."""
    return [
        (trace_dir_name, layer_name)
        for trace_dir_name in TRACE_DIRS
        for layer_name in layers_for(trace_dir_name)
    ]


def _regenerate_one_layer(task):
    """Worker-process entry point: builds its own model instance (a fresh
    ComputeModel per task, not shared across the process pool) and runs
    one (trace_dir, layer) through regenerate_layer."""
    arch_name, trace_dir_name, layer_name, indices = task
    model = ARCH_MODELS[arch_name]()
    n, dt = regenerate_layer(arch_name, model, trace_dir_name, layer_name, indices)
    return trace_dir_name, layer_name, n, dt


def _run_pass(arch_name, indices, label, max_workers):
    targets = _all_layer_targets()
    print(f"=== {arch_name}: {label} ({len(indices)} samples), "
          f"{len(targets)} layers, {max_workers} workers ===", flush=True)
    tasks = [(arch_name, trace_dir_name, layer_name, indices) for trace_dir_name, layer_name in targets]

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_regenerate_one_layer, task): task for task in tasks}
        for future in as_completed(futures):
            _, task_trace_dir_name, task_layer_name, _ = futures[future]
            try:
                trace_dir_name, layer_name, n, dt = future.result()
            except Exception as exc:  # noqa: BLE001 - a real compute-node failure for one layer shouldn't sink the rest
                print(f"  {task_trace_dir_name}/{task_layer_name}: FAILED ({exc!r})", flush=True)
                continue
            if n == 0:
                print(f"  {trace_dir_name}/{layer_name}: already complete, skip", flush=True)
            else:
                print(f"  {trace_dir_name}/{layer_name}: {n} samples in {dt:.1f}s "
                      f"({dt / n:.2f}s/sample)", flush=True)


def regenerate_arch(arch_name, max_workers=None):
    if max_workers is None:
        max_workers = len(os.sched_getaffinity(0))
    indices = canonical_sample_indices()

    _run_pass(arch_name, indices[:FIRST_PASS_SAMPLES], f"pass 1, first {FIRST_PASS_SAMPLES}", max_workers)
    _run_pass(arch_name, indices, "pass 2, remaining", max_workers)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: generate_weight_traces_canonical100.py <arch> [<arch2> ...]")
    for arch_name in sys.argv[1:]:
        regenerate_arch(arch_name)
