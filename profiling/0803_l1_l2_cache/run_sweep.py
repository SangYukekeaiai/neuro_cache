#!/usr/bin/env python3
"""Run the approved five-sample LoAS L1/L2 hierarchy sweep."""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import pathlib
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cachesim.config import DIMS  # noqa: E402
from cachesim.native_bridge import native_hierarchical_sweep  # noqa: E402


DEFAULT_TRACE_ROOT = pathlib.Path("/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/loas")
HERE = pathlib.Path(__file__).resolve().parent
ARCH_CONFIGS = (
    "inst16_node32kb_noc512kb",
    "inst16_node32kb_noc4096kb",
    "inst1024_node32kb_noc512kb",
    "inst1024_node32kb_noc4096kb",
)
WORKLOADS = ("resnet19_T4_all", "vgg16_T4_all")
EXPECTED_LAYERS = {"resnet19_T4_all": 19, "vgg16_T4_all": 12}
SAMPLE_NAMES = tuple(f"sample_{sample_idx:05d}.json.gz" for sample_idx in range(5))
STRUCTURES = (
    ("fully_associative", 0),
    ("set_associative", 32),
    ("set_associative", 4),
)
L1_SIZES = (16 * 1024, 32 * 1024)
L2_SIZES = (128 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024)
GRID = {
    (cache_type, associativity, l1_size, l2_size)
    for cache_type, associativity in STRUCTURES
    for l1_size in L1_SIZES
    for l2_size in L2_SIZES
}

SUMMARY_FIELDS = (
    "arch_config", "workload", "layer", "sample_idx", "cache_type", "associativity",
    "l1_size_bytes", "l2_size_bytes", "l1_hits", "l1_accesses", "l1_hit_rate",
    "l2_hits", "l2_accesses", "l2_hit_rate", "overall_hit_rate", "n_cores",
)
PER_CORE_FIELDS = (
    "arch_config", "workload", "layer", "sample_idx", "cache_type", "associativity",
    "l1_size_bytes", "l2_size_bytes", "core_id", "l1_hits", "l1_accesses", "l1_hit_rate",
)


def discover_units(trace_root: pathlib.Path) -> list[tuple[str, str, str, pathlib.Path]]:
    units = []
    reference_layers = {}
    for arch_config in ARCH_CONFIGS:
        for workload in WORKLOADS:
            workload_dir = trace_root / arch_config / workload
            if not workload_dir.is_dir():
                raise FileNotFoundError(f"missing workload directory: {workload_dir}")
            layers = tuple(sorted(path.name for path in workload_dir.iterdir() if path.is_dir()))
            expected_count = EXPECTED_LAYERS[workload]
            if len(layers) != expected_count:
                raise ValueError(f"{workload_dir}: expected {expected_count} layers, found {len(layers)}")
            if workload in reference_layers and layers != reference_layers[workload]:
                raise ValueError(f"{arch_config}/{workload}: layer set differs from the first arch config")
            reference_layers.setdefault(workload, layers)
            for layer in layers:
                layer_dir = workload_dir / layer
                samples = tuple(sorted(path.name for path in layer_dir.glob("sample_*.json.gz")))
                if samples != SAMPLE_NAMES:
                    raise ValueError(f"{layer_dir}: expected samples {SAMPLE_NAMES}, found {samples}")
                units.append((arch_config, workload, layer, layer_dir))
    if len(units) != 124:
        raise ValueError(f"expected 124 arch/workload/layer units, found {len(units)}")
    return units


def print_preview(units: list[tuple[str, str, str, pathlib.Path]], trace_root: pathlib.Path,
                  results_dir: pathlib.Path, out_path: pathlib.Path) -> None:
    input_bytes = sum(path.stat().st_size for *_, layer_dir in units for path in layer_dir.glob("sample_*.json.gz"))
    print(f"trace root: {trace_root}")
    print(f"input: {len(units)} units x 5 samples = {len(units) * 5} files ({input_bytes / 2**30:.1f} GiB compressed)")
    print("cache grid: 3 structures x 2 L1 sizes x 4 L2 sizes = 24 configurations")
    for cache_type, associativity in STRUCTURES:
        label = cache_type if associativity == 0 else f"{cache_type}/{associativity}-way"
        for l1_size in L1_SIZES:
            pairs = ", ".join(f"({l1_size // 1024}KB,{l2_size // 1024}KB)" for l2_size in L2_SIZES)
            print(f"  {label}: {pairs}")
    print(f"total replays: {len(units) * len(SAMPLE_NAMES) * len(GRID):,}")
    print(f"unit results: {results_dir}")
    print(f"per-core results: {results_dir.parent / 'per_core'}")
    print(f"merged results: {out_path}")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def run_unit(task: tuple[str, str, str, pathlib.Path, pathlib.Path, pathlib.Path]) -> str:
    arch_config, workload, layer, layer_dir, summary_path, per_core_path = task
    if summary_path.exists() and per_core_path.exists():
        return f"skip (cached): {arch_config}/{workload}/{layer}"

    summary_tmp = summary_path.with_name(f".{summary_path.name}.{os.getpid()}.tmp")
    per_core_tmp = per_core_path.with_name(f".{per_core_path.name}.{os.getpid()}.tmp")
    started = time.monotonic()
    try:
        with summary_tmp.open("w", newline="") as summary_output, gzip.open(per_core_tmp, "wt", newline="") as core_output:
            summary_writer = csv.DictWriter(summary_output, fieldnames=SUMMARY_FIELDS)
            core_writer = csv.DictWriter(core_output, fieldnames=PER_CORE_FIELDS)
            summary_writer.writeheader()
            core_writer.writeheader()

            for sample_idx, sample_name in enumerate(SAMPLE_NAMES):
                sample_path = layer_dir / sample_name
                results = native_hierarchical_sweep(sample_path, DIMS)
                keys = {
                    (result.cache_type, result.associativity or 0, result.l1_size_bytes, result.l2_size_bytes)
                    for result in results
                }
                if len(results) != 24 or keys != GRID:
                    raise ValueError(f"{sample_path}: native sweep returned an unexpected grid")

                for result in results:
                    stats = result.stats
                    if stats.l2_accesses != stats.l1_accesses - stats.l1_hits:
                        raise ValueError(f"{sample_path}: L2 access count does not equal L1 misses")
                    associativity = result.associativity or 0
                    common = {
                        "arch_config": arch_config,
                        "workload": workload,
                        "layer": layer,
                        "sample_idx": sample_idx,
                        "cache_type": result.cache_type,
                        "associativity": associativity,
                        "l1_size_bytes": result.l1_size_bytes,
                        "l2_size_bytes": result.l2_size_bytes,
                    }
                    summary_writer.writerow({
                        **common,
                        "l1_hits": stats.l1_hits,
                        "l1_accesses": stats.l1_accesses,
                        "l1_hit_rate": _rate(stats.l1_hits, stats.l1_accesses),
                        "l2_hits": stats.l2_hits,
                        "l2_accesses": stats.l2_accesses,
                        "l2_hit_rate": _rate(stats.l2_hits, stats.l2_accesses),
                        "overall_hit_rate": _rate(stats.l1_hits + stats.l2_hits, stats.l1_accesses),
                        "n_cores": len(stats.per_core_l1),
                    })
                    for core_id, hits, accesses in stats.per_core_l1:
                        core_writer.writerow({
                            **common,
                            "core_id": core_id,
                            "l1_hits": hits,
                            "l1_accesses": accesses,
                            "l1_hit_rate": _rate(hits, accesses),
                        })

        os.replace(per_core_tmp, per_core_path)
        os.replace(summary_tmp, summary_path)
    except BaseException:
        summary_tmp.unlink(missing_ok=True)
        per_core_tmp.unlink(missing_ok=True)
        raise
    return f"done: {arch_config}/{workload}/{layer} ({time.monotonic() - started:.1f}s)"


def merge_results(results_dir: pathlib.Path, out_path: pathlib.Path) -> int:
    paths = sorted(results_dir.glob("*.csv"))
    if len(paths) != 124:
        raise ValueError(f"expected 124 completed unit CSVs, found {len(paths)}")

    rows = []
    for path in paths:
        with path.open(newline="") as source:
            unit_rows = list(csv.DictReader(source))
        if len(unit_rows) != 120:
            raise ValueError(f"{path}: expected 120 rows, found {len(unit_rows)}")
        rows.extend(unit_rows)

    expected_rows = 124 * 5 * 24
    if len(rows) != expected_rows:
        raise ValueError(f"expected {expected_rows} rows, found {len(rows)}")
    keys = {
        (
            row["arch_config"], row["workload"], row["layer"], row["sample_idx"],
            row["cache_type"], row["associativity"], row["l1_size_bytes"], row["l2_size_bytes"],
        )
        for row in rows
    }
    if len(keys) != expected_rows:
        raise ValueError("duplicate summary rows")
    if Counter(row["sample_idx"] for row in rows) != Counter({str(i): 124 * 24 for i in range(5)}):
        raise ValueError("merged sample coverage is incomplete")
    for row in rows:
        if int(row["l2_accesses"]) != int(row["l1_accesses"]) - int(row["l1_hits"]):
            raise ValueError("merged result violates l2_accesses == l1_accesses - l1_hits")
        for field in ("l1_hit_rate", "l2_hit_rate", "overall_hit_rate"):
            if not 0.0 <= float(row[field]) <= 1.0:
                raise ValueError(f"{field} outside [0,1]")

    tmp = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    with tmp.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, out_path)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="execute the sweep; without this flag, print the preview only")
    parser.add_argument("--workers", type=int, default=1, help="parallel layer units (default: 1)")
    parser.add_argument("--unit-index", type=int, default=None,
                        help="run one deterministic unit index (0-123)")
    parser.add_argument("--merge-only", action="store_true", help="validate and merge cached unit results")
    parser.add_argument("--trace-root", type=pathlib.Path, default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--results-dir", type=pathlib.Path, default=HERE / "results")
    parser.add_argument("--out", type=pathlib.Path, default=HERE / "hierarchical_cache_results.csv")
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.unit_index is not None and not 0 <= args.unit_index < 124:
        parser.error("--unit-index must be between 0 and 123")

    units = discover_units(args.trace_root)
    print_preview(units, args.trace_root, args.results_dir, args.out)
    if not args.run and not args.merge_only:
        return

    args.results_dir.mkdir(parents=True, exist_ok=True)
    per_core_dir = args.results_dir.parent / "per_core"
    per_core_dir.mkdir(parents=True, exist_ok=True)

    if not args.merge_only:
        tasks = []
        for arch_config, workload, layer, layer_dir in units:
            stem = f"{arch_config}__{workload}__{layer}"
            tasks.append((
                arch_config, workload, layer, layer_dir,
                args.results_dir / f"{stem}.csv",
                per_core_dir / f"{stem}.csv.gz",
            ))
        if args.unit_index is not None:
            print(run_unit(tasks[args.unit_index]), flush=True)
            return
        tasks = [task for task in tasks if not (task[4].exists() and task[5].exists())]
        tasks.sort(key=lambda task: sum(path.stat().st_size for path in task[3].glob("sample_*.json.gz")))
        print(f"running {len(tasks)} not-yet-cached units with {args.workers} worker(s)", flush=True)
        failures = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_unit, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    print(future.result(), flush=True)
                except BaseException as error:
                    failures.append((task[:3], error))
                    print(f"FAILED: {'/'.join(task[:3])}: {error}", flush=True)
        if failures:
            raise RuntimeError(f"{len(failures)} unit(s) failed; rerun to resume")

    n_rows = merge_results(args.results_dir, args.out)
    print(f"merged and validated {n_rows:,} rows -> {args.out}")


if __name__ == "__main__":
    main()
