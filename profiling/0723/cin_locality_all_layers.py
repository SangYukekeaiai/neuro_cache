#!/usr/bin/env python3
"""Run the cin-locality diagnostic (cin_locality_diagnostic.py) across
every layer of one network for one arch, using whatever samples are
already saved locally under profiling/0723/weight_traces/. Merges the
per-layer summaries into one CSV for cross-layer comparison.
"""

from __future__ import annotations

import csv
import glob
import os
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import cin_locality_diagnostic as cld

FIELDNAMES = [
    "layer", "sample_idx", "inner_dim", "concentration", "effective_tags",
    "top1_frac", "top10_frac", "hit_rate", "num_distinct_tags",
]


def _process_one_layer(task):
    """Worker-process entry point: runs the single-layer diagnostic and
    reads its own CSV back so the merge happens in the parent process."""
    layer_name, paths, out_dir = task
    cld.main(paths, out_dir)
    rows = []
    with open(out_dir / "cin_locality_summary.csv") as fh:
        for row in csv.DictReader(fh):
            row["layer"] = layer_name
            rows.append(row)
    return layer_name, rows


def run(arch_name, trace_dir_name, num_samples, out_root, max_workers=None, sample_offset=0):
    if max_workers is None:
        max_workers = len(os.sched_getaffinity(0))
    out_root = pathlib.Path(out_root)
    weight_traces_root = _HERE / "weight_traces" / arch_name / trace_dir_name

    tasks = []
    for layer_dir in sorted(weight_traces_root.iterdir()):
        layer_name = layer_dir.name
        all_paths = sorted(glob.glob(str(layer_dir / "sample_*.json.gz")))
        paths = all_paths[sample_offset:sample_offset + num_samples]
        if not paths:
            print(f"skip {layer_name}: no samples", flush=True)
            continue
        tasks.append((layer_name, paths, out_root / layer_name))

    print(f"=== {arch_name}/{trace_dir_name}: {len(tasks)} layers, "
          f"{num_samples} samples each, {max_workers} workers ===", flush=True)

    merged_rows = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process_one_layer, task): task for task in tasks}
        for future in as_completed(futures):
            layer_name, paths, out_dir = futures[future]
            try:
                _, rows = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad layer shouldn't sink the rest
                print(f"  {layer_name}: FAILED ({exc!r})", flush=True)
                continue
            merged_rows.extend(rows)
            print(f"  {layer_name}: done ({len(paths)} samples)", flush=True)

    merged_path = out_root / "merged_summary.csv"
    with open(merged_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(merged_rows)
    print(f"-> {merged_path} ({len(merged_rows)} rows)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: cin_locality_all_layers.py <arch> <trace_dir_name> "
            "[num_samples] [out_dir] [sample_offset]"
        )
    arch_name = sys.argv[1]
    trace_dir_name = sys.argv[2]
    num_samples = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    out_dir = sys.argv[4] if len(sys.argv) > 4 else str(_HERE / "outputs" / f"cin_diagnostic_{arch_name}_{trace_dir_name}")
    sample_offset = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    run(arch_name, trace_dir_name, num_samples, out_dir, sample_offset=sample_offset)
