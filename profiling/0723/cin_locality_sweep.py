#!/usr/bin/env python3
"""Cache-size / line-size sweep for the cin-innermost layout, hit rate
specifically: line_size in {16, 32, 64} bytes, cache_size in
{8, 16, 32, 64} KB, all available samples (up to 100), every layer,
one arch at a time. Restricted to "cin" only (not all 4 layouts) to keep
the added sweep dimension tractable.

Shares expand_events() across every (line_size, cache_size) combination
for a given sample (it doesn't depend on either), and shares the tag
list/histogram across every cache_size for a fixed line_size (only cache
capacity changes there) -- the expensive steps run 3 times per sample
instead of 12.
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

from access_pattern import (
    concentration_score,
    effective_tag_count,
    event_line_tags,
    expand_events,
    tag_histogram,
    top_k_mass_fraction,
)
from lru_cache import FullyAssociativeLRUCache, replay
from tracegen import load_weight_trace

TRACE_DIRS = ["resnet19_T4_all", "vgg16_T4_all"]
INNER_DIM = "cin"
LINE_SIZES_BYTES = [16, 32, 64]  # 1 byte/weight (8-bit), so bytes == elements
CACHE_SIZES_BYTES = [8 * 1024, 16 * 1024, 32 * 1024, 64 * 1024]

PER_SAMPLE_FIELDS = [
    "trace_dir", "layer", "sample_idx", "line_size_bytes", "cache_size_bytes",
    "cache_capacity_lines", "hit_rate", "concentration", "effective_tags",
    "top1_frac", "top10_frac", "num_distinct_tags",
]
AGG_FIELDS = [
    "trace_dir", "layer", "line_size_bytes", "cache_size_bytes", "cache_capacity_lines",
    "n_samples", "mean_hit_rate", "median_hit_rate", "mean_concentration", "mean_effective_tags",
]


def _analyze_one_sample_sweep(task):
    trace_dir_name, layer_name, path = task
    trace = load_weight_trace(pathlib.Path(path))
    events = [addr for tile in trace.tiles for addr in tile.weight_addresses]
    elements = expand_events(events)

    rows = []
    for line_size in LINE_SIZES_BYTES:
        hist = tag_histogram(elements, INNER_DIM, line_size)
        tags = [tag for event in events for tag in event_line_tags(event, INNER_DIM, line_size)]
        concentration = concentration_score(hist)
        eff_tags = effective_tag_count(hist)
        top1 = top_k_mass_fraction(hist, 1)
        top10 = top_k_mass_fraction(hist, 10)
        n_distinct = len(hist)

        for cache_size_bytes in CACHE_SIZES_BYTES:
            cache_capacity = max(1, cache_size_bytes // line_size)
            cache = FullyAssociativeLRUCache(cache_capacity)
            hits = replay(cache, tags)
            hit_rate = (sum(hits) / len(hits)) if hits else 0.0
            rows.append({
                "trace_dir": trace_dir_name, "layer": layer_name, "sample_idx": trace.sample_idx,
                "line_size_bytes": line_size, "cache_size_bytes": cache_size_bytes,
                "cache_capacity_lines": cache_capacity, "hit_rate": hit_rate,
                "concentration": concentration, "effective_tags": eff_tags,
                "top1_frac": top1, "top10_frac": top10, "num_distinct_tags": n_distinct,
            })
    return rows


def _build_tasks(arch_name, num_samples, trace_dirs=None):
    weight_traces_root = _HERE / "weight_traces" / arch_name
    tasks = []
    for trace_dir_name in (trace_dirs or TRACE_DIRS):
        layer_root = weight_traces_root / trace_dir_name
        if not layer_root.is_dir():
            continue
        for layer_dir in sorted(layer_root.iterdir()):
            paths = sorted(glob.glob(str(layer_dir / "sample_*.json.gz")))[:num_samples]
            for path in paths:
                tasks.append((trace_dir_name, layer_dir.name, path))
    return tasks


def _sample_idx_from_path(path):
    # "sample_00018.json.gz" -> "sample_00018.json.gz".split(".")[0] ->
    # "sample_00018" -> 18. (Path.stem only strips the last suffix, ".gz",
    # leaving "sample_00018.json" behind, hence the manual split.)
    return int(pathlib.Path(path).name.split(".")[0].split("_")[-1])


_EXPECTED_ROWS_PER_SAMPLE = len(LINE_SIZES_BYTES) * len(CACHE_SIZES_BYTES)


def _load_done_samples(per_sample_path):
    """(trace_dir, layer, sample_idx) keys that already have a full set of
    rows (every line_size x cache_size combo) in an existing checkpoint
    file, so a resumed run skips only genuinely finished samples."""
    if not per_sample_path.exists():
        return set()
    counts = {}
    with open(per_sample_path) as fh:
        for row in csv.DictReader(fh):
            key = (row["trace_dir"], row["layer"], int(row["sample_idx"]))
            counts[key] = counts.get(key, 0) + 1
    return {key for key, n in counts.items() if n >= _EXPECTED_ROWS_PER_SAMPLE}


def run(arch_name, num_samples, out_root, max_workers=None, trace_dirs=None):
    if max_workers is None:
        max_workers = len(os.sched_getaffinity(0))
    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    per_sample_path = out_root / "per_sample_sweep.csv"

    # Resume support: a 1-hour time-limit kill is common for a large arch,
    # and this run has no other checkpointing, so skip whatever a prior,
    # cut-off run already finished (a "done" sample has all 12 rows).
    done = _load_done_samples(per_sample_path)
    all_tasks = _build_tasks(arch_name, num_samples, trace_dirs=trace_dirs)
    tasks = [t for t in all_tasks if (t[0], t[1], _sample_idx_from_path(t[2])) not in done]
    if done:
        print(f"resuming: {len(done)} samples already done, {len(tasks)} remaining "
              f"of {len(all_tasks)} total", flush=True)

    # _build_tasks groups tasks by layer, so submitting them in that order
    # risks every worker grabbing the same huge layer's samples at once
    # (this is exactly what OOM'd: many workers each holding a multi-ten-
    # million-element sample simultaneously). Shuffling spreads big and
    # small layers evenly across the run instead.
    random.shuffle(tasks)
    print(f"=== {arch_name}: {len(tasks)} samples x {len(LINE_SIZES_BYTES)} line sizes x "
          f"{len(CACHE_SIZES_BYTES)} cache sizes, {max_workers} workers ===", flush=True)

    write_header = not per_sample_path.exists()
    completed = 0
    with open(per_sample_path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PER_SAMPLE_FIELDS)
        if write_header:
            writer.writeheader()
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_analyze_one_sample_sweep, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    rows = future.result()
                except Exception as exc:  # noqa: BLE001 - one bad sample shouldn't sink the rest
                    print(f"  FAILED {task}: {exc!r}", flush=True)
                    continue
                # write and flush immediately: this is exactly the progress
                # a time-limit kill or crash must not lose.
                writer.writerows(rows)
                fh.flush()
                completed += 1
                if completed % 100 == 0 or completed == len(tasks):
                    print(f"  progress: {completed}/{len(tasks)} samples analyzed", flush=True)
    print(f"-> {per_sample_path}", flush=True)

    # Recompute the aggregate from the full checkpoint file (old + new
    # rows together), not just this invocation's rows.
    groups = {}
    with open(per_sample_path) as fh:
        for row in csv.DictReader(fh):
            key = (row["trace_dir"], row["layer"], row["line_size_bytes"], row["cache_size_bytes"])
            row["hit_rate"] = float(row["hit_rate"])
            row["concentration"] = float(row["concentration"])
            row["effective_tags"] = float(row["effective_tags"])
            groups.setdefault(key, []).append(row)

    agg_rows = []
    for (trace_dir_name, layer_name, line_size, cache_size), rows in groups.items():
        agg_rows.append({
            "trace_dir": trace_dir_name, "layer": layer_name,
            "line_size_bytes": line_size, "cache_size_bytes": cache_size,
            "cache_capacity_lines": rows[0]["cache_capacity_lines"],
            "n_samples": len(rows),
            "mean_hit_rate": statistics.mean(r["hit_rate"] for r in rows),
            "median_hit_rate": statistics.median(r["hit_rate"] for r in rows),
            "mean_concentration": statistics.mean(r["concentration"] for r in rows),
            "mean_effective_tags": statistics.mean(r["effective_tags"] for r in rows),
        })

    agg_path = out_root / "aggregated_sweep.csv"
    with open(agg_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=AGG_FIELDS)
        writer.writeheader()
        writer.writerows(agg_rows)
    print(f"-> {agg_path} ({len(agg_rows)} rows)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: cin_locality_sweep.py <arch> [num_samples] [out_dir] [trace_dir_name] [max_workers]"
        )
    arch_name = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    out_dir = sys.argv[3] if len(sys.argv) > 3 else str(_HERE / "outputs" / f"cin_sweep_{arch_name}")
    trace_dirs = [sys.argv[4]] if len(sys.argv) > 4 else None
    max_workers = int(sys.argv[5]) if len(sys.argv) > 5 else None
    run(arch_name, num_samples, out_dir, max_workers=max_workers, trace_dirs=trace_dirs)
