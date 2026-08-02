#!/usr/bin/env python3
"""Solve all LoAS VGG16/ResNet19 layers on the five multi-node configs."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import traceback

sys.path.insert(0, "src")

import tracegen
from archmodels.trace import valid_layer_names


ARCHS = ("loas", "spinalflow", "ptb", "gustavsnn", "prosperity")
TRACE_DIRS = ("vgg16_T4_all", "resnet19_T4_all")
DEFAULT_TRACE_ROOT = pathlib.Path(
    "/u/yyu9/neuro_cache_trace/input_trace/loas"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-root", default=str(DEFAULT_TRACE_ROOT))
    parser.add_argument(
        "--cache-dir", default="outputs/schedules/multinode"
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def iter_layers(trace_root: pathlib.Path, trace_name: str):
    with open(trace_root / trace_name / "meta.json") as file:
        meta = json.load(file)
    names = list(meta["layers"])
    valid = set(valid_layer_names(meta))
    for index, name in enumerate(names):
        if name not in valid:
            continue
        next_cin = (
            meta["layers"][names[index + 1]][2]
            if index + 1 < len(names)
            else None
        )
        yield name, meta, next_cin


def main() -> int:
    args = parse_args()
    trace_root = pathlib.Path(args.trace_root)
    cache_dir = pathlib.Path(args.cache_dir)
    rows = []

    for trace_name in TRACE_DIRS:
        layers = list(iter_layers(trace_root, trace_name))
        for arch in ARCHS:
            arch_yaml = f"configs/arch/{arch}_multinode.yaml"
            dataflow_yaml = f"configs/dataflow/{arch}.yaml"
            for layer_name, meta, next_cin in layers:
                out_path = cache_dir / arch / trace_name / f"{layer_name}.json"
                row = {
                    "arch": arch,
                    "trace_dir": trace_name,
                    "layer": layer_name,
                }
                if out_path.exists() and not args.force:
                    row["status"] = "SKIPPED"
                    rows.append(row)
                    print(f"skip {arch}/{trace_name}/{layer_name}", flush=True)
                    continue

                print(f"solve {arch}/{trace_name}/{layer_name}", flush=True)
                try:
                    artifact = tracegen.solve_and_cache_schedule(
                        arch,
                        arch_yaml,
                        dataflow_yaml,
                        trace_name,
                        layer_name,
                        meta,
                        next_cin,
                        cache_dir,
                    )
                    row["status"] = "OK"
                    row["mode"] = artifact.mode
                    row["dram_num_steps"] = artifact.dram_num_steps
                except ValueError as error:
                    row["status"] = "INFEASIBLE"
                    row["error"] = str(error)
                except Exception as error:
                    row["status"] = "ERROR"
                    row["error"] = f"{type(error).__name__}: {error}"
                    traceback.print_exc()
                rows.append(row)

    cache_dir.mkdir(parents=True, exist_ok=True)
    summary_path = cache_dir / "summary.csv"
    fields = [
        "arch",
        "trace_dir",
        "layer",
        "status",
        "mode",
        "dram_num_steps",
        "error",
    ]
    with open(summary_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    solved = sum(row["status"] == "OK" for row in rows)
    skipped = sum(row["status"] == "SKIPPED" for row in rows)
    failed = len(rows) - solved - skipped
    print(
        f"{solved} solved, {skipped} skipped, {failed} failed -> "
        f"{summary_path}",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
