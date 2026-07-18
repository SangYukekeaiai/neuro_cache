#!/usr/bin/env python3
"""Stage 1 of the generate-once weight-trace pipeline: solve every
(arch, trace_dir, layer) schedule exactly once and persist it to
outputs/schedules/<arch>/<trace_dir>/<layer_name>.json.

This is the only stage that needs the Gurobi license -- ~140-155 calls
total (5 archs x ~31 layers), a few seconds each. Stage 2
(generate_weight_traces.py) loads these cached schedules and reconstructs
every captured sample against them, with no further solving at all.

See docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import traceback

sys.path.insert(0, "src")

from snn_cosa import tracegen
from snn_cosa.archmodels.trace import valid_layer_names

DEFAULT_TRACE_ROOT = pathlib.Path("/u/yyu9/neuro_cache_trace/input_trace/loas")
DEFAULT_TRACE_DIRS = ["vgg16_T4_all", "resnet19_T4_all"]
DEFAULT_ARCH_YAML = {
    "loas": "configs/arch/loas.yaml",
    "spinalflow": "configs/arch/spinalflow.yaml",
    "ptb": "configs/arch/ptb.yaml",
    "gustavsnn": "configs/arch/gustavsnn.yaml",
    "prosperity": "configs/arch/prosperity.yaml",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace-root", default=str(DEFAULT_TRACE_ROOT))
    p.add_argument("--trace-dirs", nargs="+", default=DEFAULT_TRACE_DIRS)
    p.add_argument("--archs", nargs="+", default=list(DEFAULT_ARCH_YAML))
    p.add_argument("--cache-dir", default="outputs/schedules")
    p.add_argument(
        "--force", action="store_true",
        help="Re-solve and overwrite even if a cached schedule already exists.",
    )
    return p.parse_args()


def _iter_valid_layers(trace_root: pathlib.Path, trace_dir_name: str):
    """Yield (layer_name, meta, next_cin) for every valid layer in
    trace_root/trace_dir_name, in meta.json order."""
    trace_dir = trace_root / trace_dir_name
    with open(trace_dir / "meta.json") as fh:
        meta = json.load(fh)
    names = list(meta["layers"])
    valid = set(valid_layer_names(meta))
    for i, name in enumerate(names):
        if name not in valid:
            continue
        next_cin = meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None
        yield name, meta, next_cin


def main() -> int:
    args = parse_args()
    trace_root = pathlib.Path(args.trace_root)
    cache_dir = pathlib.Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for trace_dir_name in args.trace_dirs:
        layers = list(_iter_valid_layers(trace_root, trace_dir_name))
        for arch_name in args.archs:
            arch_yaml = DEFAULT_ARCH_YAML[arch_name]
            for layer_name, meta, next_cin in layers:
                out_path = cache_dir / arch_name / trace_dir_name / f"{layer_name}.json"
                if out_path.exists() and not args.force:
                    print(f"  skip (exists): {arch_name}/{trace_dir_name}/{layer_name}")
                    rows.append({
                        "arch": arch_name, "trace_dir": trace_dir_name,
                        "layer": layer_name, "status": "SKIPPED",
                    })
                    continue
                print(f"  solve: {arch_name}/{trace_dir_name}/{layer_name} ...")
                row = {"arch": arch_name, "trace_dir": trace_dir_name, "layer": layer_name}
                try:
                    artifact = tracegen.solve_and_cache_schedule(
                        arch_name, arch_yaml, trace_dir_name, layer_name,
                        meta, next_cin, cache_dir,
                    )
                    row["status"] = "OK"
                    row["dram_num_steps"] = artifact.dram_num_steps
                except ValueError as exc:
                    row["status"] = "INFEASIBLE"
                    row["error"] = str(exc)
                except Exception as exc:  # noqa: BLE001 -- sweep: record, don't abort
                    row["status"] = "ERROR"
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    traceback.print_exc()
                rows.append(row)

    summary_path = cache_dir / "summary.csv"
    fieldnames = ["arch", "trace_dir", "layer", "status", "dram_num_steps", "error"]
    with open(summary_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    n_ok = sum(1 for r in rows if r["status"] == "OK")
    n_skip = sum(1 for r in rows if r["status"] == "SKIPPED")
    n_bad = len(rows) - n_ok - n_skip
    print(f"\n{n_ok} solved, {n_skip} skipped (already cached), {n_bad} infeasible/error "
          f"-> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
