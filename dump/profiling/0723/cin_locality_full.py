#!/usr/bin/env python3
"""Full-scale cin-locality diagnostic: every layer of both networks, up
to num_samples each, for one arch, using whatever samples are already
saved locally under profiling/0723/weight_traces/.

Task granularity is per (layer, sample), not per layer: each sample is
its own small already-reconstructed file with no shared per-layer setup
cost to amortize (unlike regeneration, which loads one schedule/trace
per layer and reuses it across samples). A flat process pool over every
(layer, sample) pair load-balances naturally instead of bottlenecking on
whichever single layer happens to be slowest.

If a layer has fewer than num_samples saved, whatever's actually there is
used (Python slicing past the end of a list just returns what's
available) -- this is how a partially-regenerated arch (e.g. gustavsnn
still mid-pass-2) naturally falls back to fewer samples per layer without
any special-casing.
"""

from __future__ import annotations

import csv
import glob
import os
import pathlib
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cin_locality_diagnostic import analyze_sample
from tracegen import load_weight_trace

TRACE_DIRS = ["resnet19_T4_all", "vgg16_T4_all"]

PER_SAMPLE_FIELDS = [
    "trace_dir", "layer", "sample_idx", "inner_dim", "concentration",
    "effective_tags", "top1_frac", "top10_frac", "hit_rate", "num_distinct_tags",
]
AGG_FIELDS = [
    "trace_dir", "layer", "inner_dim", "n_samples", "mean_concentration",
    "median_concentration", "mean_effective_tags", "mean_top1_frac",
    "mean_top10_frac", "mean_hit_rate", "mean_num_distinct_tags",
]


def _analyze_one_sample(task):
    trace_dir_name, layer_name, path = task
    trace = load_weight_trace(pathlib.Path(path))
    events = [addr for tile in trace.tiles for addr in tile.weight_addresses]
    result = analyze_sample(events)
    return trace_dir_name, layer_name, trace.sample_idx, result


def _build_tasks(arch_name, num_samples):
    weight_traces_root = _HERE / "weight_traces" / arch_name
    tasks = []
    for trace_dir_name in TRACE_DIRS:
        layer_root = weight_traces_root / trace_dir_name
        if not layer_root.is_dir():
            continue
        for layer_dir in sorted(layer_root.iterdir()):
            paths = sorted(glob.glob(str(layer_dir / "sample_*.json.gz")))[:num_samples]
            for path in paths:
                tasks.append((trace_dir_name, layer_dir.name, path))
    return tasks


def run(arch_name, num_samples, out_root, max_workers=None):
    if max_workers is None:
        max_workers = len(os.sched_getaffinity(0))
    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    tasks = _build_tasks(arch_name, num_samples)
    # _build_tasks groups tasks by layer; shuffle so concurrent workers
    # don't all land on the same huge layer's samples at once (this is
    # what caused an OOM in the related cin_locality_sweep.py).
    random.shuffle(tasks)
    print(f"=== {arch_name}: {len(tasks)} (layer, sample) tasks, {max_workers} workers ===", flush=True)

    per_sample_rows = []
    completed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_analyze_one_sample, task): task for task in tasks}
        for future in as_completed(futures):
            trace_dir_name, layer_name, path = futures[future]
            try:
                trace_dir_name, layer_name, sample_idx, result = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad sample shouldn't sink the rest
                print(f"  FAILED {trace_dir_name}/{layer_name}/{path}: {exc!r}", flush=True)
                continue
            for inner_dim, r in result.items():
                per_sample_rows.append({
                    "trace_dir": trace_dir_name, "layer": layer_name, "sample_idx": sample_idx,
                    "inner_dim": inner_dim, "concentration": r["concentration"],
                    "effective_tags": r["effective_tags"], "top1_frac": r["top1_frac"],
                    "top10_frac": r["top10_frac"], "hit_rate": r["hit_rate"],
                    "num_distinct_tags": len(r["rank_freq"]),
                })
            completed += 1
            if completed % 100 == 0 or completed == len(tasks):
                print(f"  progress: {completed}/{len(tasks)} (layer, sample) tasks analyzed", flush=True)

    per_sample_path = out_root / "per_sample_summary.csv"
    with open(per_sample_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PER_SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(per_sample_rows)
    print(f"-> {per_sample_path} ({len(per_sample_rows)} rows)", flush=True)

    groups = {}
    for row in per_sample_rows:
        key = (row["trace_dir"], row["layer"], row["inner_dim"])
        groups.setdefault(key, []).append(row)

    agg_rows = []
    for (trace_dir_name, layer_name, inner_dim), rows in groups.items():
        agg_rows.append({
            "trace_dir": trace_dir_name, "layer": layer_name, "inner_dim": inner_dim,
            "n_samples": len(rows),
            "mean_concentration": statistics.mean(r["concentration"] for r in rows),
            "median_concentration": statistics.median(r["concentration"] for r in rows),
            "mean_effective_tags": statistics.mean(r["effective_tags"] for r in rows),
            "mean_top1_frac": statistics.mean(r["top1_frac"] for r in rows),
            "mean_top10_frac": statistics.mean(r["top10_frac"] for r in rows),
            "mean_hit_rate": statistics.mean(r["hit_rate"] for r in rows),
            "mean_num_distinct_tags": statistics.mean(r["num_distinct_tags"] for r in rows),
        })

    agg_path = out_root / "aggregated_summary.csv"
    with open(agg_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=AGG_FIELDS)
        writer.writeheader()
        writer.writerows(agg_rows)
    print(f"-> {agg_path} ({len(agg_rows)} rows)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: cin_locality_full.py <arch> [num_samples] [out_dir]")
    arch_name = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    out_dir = sys.argv[3] if len(sys.argv) > 3 else str(_HERE / "outputs" / f"cin_diagnostic_full_{arch_name}")
    run(arch_name, num_samples, out_dir)
