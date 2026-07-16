#!/usr/bin/env python3
"""Sweep all 5 wired arch models against all 28 valid captured trace
layers, solving + live-wiring + running each, and saving one summary CSV
per arch to outputs/archmodel_sweep/ for review.

28 = 9 valid vgg16_T4_B1 layers (3 of the 12 excluded, Hin=Win=2 too
small for a 3x3 no-pad receptive field) + all 19 resnet19_T4_B1 layers.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
import tempfile
import traceback

sys.path.insert(0, "src")

import yaml

from snn_cosa.archmodels.gustavsnn.model import GustavSNNComputeModel
from snn_cosa.archmodels.loas.model import LoASComputeModel
from snn_cosa.archmodels.prosperity.model import ProsperityComputeModel
from snn_cosa.archmodels.ptb.model import PTBComputeModel
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.trace import build_workload_from_trace, load_layer_trace, valid_layer_names
from snn_cosa.nocsim.sim import run_from_json
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.parsers.layer import SNNProb
from snn_cosa.solver import solve_schedule

ARCHS = {
    "spinalflow": ("configs/arch/spinalflow.yaml", SpinalFlowComputeModel),
    "ptb": ("configs/arch/ptb.yaml", PTBComputeModel),
    "loas": ("configs/arch/loas.yaml", LoASComputeModel),
    "gustavsnn": ("configs/arch/gustavsnn.yaml", GustavSNNComputeModel),
    "prosperity": ("configs/arch/prosperity.yaml", ProsperityComputeModel),
}
TRACE_DIRS = ["input_trace/loas/vgg16_T4_B1", "input_trace/loas/resnet19_T4_B1"]
OUT_DIR = pathlib.Path("outputs/archmodel_sweep")


def _sweep_layers():
    """Yield (trace_dir, layer_name, meta) for every valid layer, across
    both captured models, in meta.json order."""
    for trace_dir in TRACE_DIRS:
        trace_dir = pathlib.Path(trace_dir)
        with open(trace_dir / "meta.json") as fh:
            meta = json.load(fh)
        names = list(meta["layers"])
        valid = set(valid_layer_names(meta))
        for i, name in enumerate(names):
            if name not in valid:
                continue
            next_cin = meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None
            yield trace_dir, name, meta, next_cin


def _run_one(arch_name: str, arch_yaml: str, model_cls, trace_dir, layer_name, meta, next_cin):
    row = {"layer": f"{trace_dir.name}/{layer_name}", "status": "ERROR"}
    try:
        workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
        row["workload_dims"] = str(workload["problem"])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(workload, f)
            layer_path = f.name

        prob = SNNProb(pathlib.Path(layer_path))
        arch = SNNArch(pathlib.Path(arch_yaml))
        bitwidths = SNNBitwidths(pathlib.Path(arch_yaml))

        result = solve_schedule(layer_path, arch_yaml)
        if not result.get("has_solution"):
            row["status"] = "INFEASIBLE"
            return row
        schedule = schedule_from_strategy(result["strategy"], prob)
        row["dram_num_steps"] = schedule.dram_num_steps

        trace = load_layer_trace(trace_dir, layer_name)
        model = model_cls()
        tiles = list(iter_node_tiles(schedule, prob))
        per_tile_cycles = []
        total_addresses = 0
        for tile in tiles:
            packed = model.format_input(trace, tile)
            cycles = model.compute_cycles(packed, tile)
            per_tile_cycles.append(cycles.mac_cycles)
            total_addresses += len(model.weight_addresses(packed, tile))

        row["total_mac_cycles"] = sum(per_tile_cycles)
        row["cycles_vary"] = len(set(per_tile_cycles)) > 1
        row["total_weight_addresses"] = total_addresses

        out_csv = OUT_DIR / f"{arch_name}_{trace_dir.name}_{layer_name}_tc.csv"
        strategy_path = pathlib.Path(tempfile.mktemp(suffix=".json"))
        with open(strategy_path, "w") as fh:
            json.dump(result, fh)
        run_from_json(
            strategy_path, prob, bitwidths, out_csv,
            arch=arch, compute_model=model, trace=trace,
        )
        lines = [ln for ln in out_csv.read_text().splitlines() if ln and not ln.startswith("#")]
        row["tc_count"] = len(lines)
        row["status"] = "OK"
    except Exception as exc:  # noqa: BLE001 -- sweep script: record, don't crash the whole sweep
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["status"] = "ERROR"
        traceback.print_exc()
    return row


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = list(_sweep_layers())
    print(f"Sweeping {len(layers)} valid layers x {len(ARCHS)} archs = {len(layers) * len(ARCHS)} runs")

    for arch_name, (arch_yaml, model_cls) in ARCHS.items():
        rows = []
        for trace_dir, layer_name, meta, next_cin in layers:
            print(f"  {arch_name} / {trace_dir.name}/{layer_name} ...")
            rows.append(_run_one(arch_name, arch_yaml, model_cls, trace_dir, layer_name, meta, next_cin))

        summary_path = OUT_DIR / f"{arch_name}_summary.csv"
        fieldnames = [
            "layer", "workload_dims", "status", "dram_num_steps",
            "total_mac_cycles", "cycles_vary", "total_weight_addresses",
            "tc_count", "error",
        ]
        with open(summary_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        n_ok = sum(1 for r in rows if r["status"] == "OK")
        print(f"{arch_name}: {n_ok}/{len(rows)} OK -> {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())