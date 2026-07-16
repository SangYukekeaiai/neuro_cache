#!/usr/bin/env python3
"""Runs the locality analyzer against one real (arch, captured trace
layer): solves that layer's workload for the given arch, walks the
solved schedule's real per-tile weight-address stream (via
iter_node_tiles + the arch's ComputeModel), and saves the reuse-distance
histogram, footprint curve, and TITL/MITL/NISL classification.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any, Dict, Optional, Type

import matplotlib

matplotlib.use("Agg")  # headless -- this runner only ever saves PNGs
import matplotlib.pyplot as plt
import yaml

from snn_cosa.archmodels import ArchComputeModel
from snn_cosa.archmodels.trace import build_workload_from_trace, load_layer_trace
from snn_cosa.locality.classify import classify_schedule
from snn_cosa.locality.stack_distance import (
    footprint_curve,
    reuse_distance_histogram,
    stack_distances,
)
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.layer import SNNProb
from snn_cosa.solver import solve_schedule


def _build_address_stream(
    arch_yaml: str, model_cls: Type[ArchComputeModel],
    trace_dir: pathlib.Path, layer_name: str, meta: Dict[str, Any],
    next_cin: Optional[int],
):
    """Solve this layer's workload for this arch and return
    (schedule, concatenated address stream in dram_i order) or None if
    infeasible."""
    workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(workload, f)
        layer_path = f.name

    prob = SNNProb(pathlib.Path(layer_path))
    result = solve_schedule(layer_path, arch_yaml)
    if not result.get("has_solution"):
        return None

    schedule = schedule_from_strategy(result["strategy"], prob)
    trace = load_layer_trace(trace_dir, layer_name)
    model = model_cls()

    addresses = []
    for tile in iter_node_tiles(schedule, prob):
        packed = model.format_input(trace, tile)
        addresses.extend(model.weight_addresses(packed, tile))

    return schedule, addresses


def analyze_layer(
    arch_name: str, arch_yaml: str, model_cls: Type[ArchComputeModel],
    trace_dir: pathlib.Path, layer_name: str, meta: Dict[str, Any],
    next_cin: Optional[int], out_dir: pathlib.Path,
) -> Dict[str, Any]:
    """Run the full locality analysis for one (arch, layer) and save its
    output (summary.json, reuse_distance_histogram.png,
    footprint_curve.png) under out_dir. Returns the summary dict too."""
    out_dir.mkdir(parents=True, exist_ok=True)
    built = _build_address_stream(arch_yaml, model_cls, trace_dir, layer_name, meta, next_cin)

    if built is None:
        summary = {"arch": arch_name, "layer": layer_name, "status": "INFEASIBLE"}
        with open(out_dir / "summary.json", "w") as fh:
            json.dump(summary, fh, indent=2)
        return summary

    schedule, addresses = built
    distances = stack_distances(addresses)
    hist = reuse_distance_histogram(distances)
    fp_curve = footprint_curve(addresses)
    classification = classify_schedule(schedule)

    finite = [d for d in distances if d is not None]
    summary = {
        "arch": arch_name,
        "layer": layer_name,
        "status": "OK",
        "num_addresses": len(addresses),
        "num_unique_addresses": len(set(addresses)),
        "num_cold_misses": len(distances) - len(finite),
        "mean_reuse_distance": (sum(finite) / len(finite)) if finite else None,
        "max_reuse_distance": max(finite) if finite else None,
        "classification": classification,
    }
    with open(out_dir / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    if hist:
        fig, ax = plt.subplots()
        xs = sorted(hist)
        ax.bar(xs, [hist[x] for x in xs])
        ax.set_xlabel("reuse distance (distinct weight lines)")
        ax.set_ylabel("count")
        ax.set_title(f"{arch_name} / {layer_name}: reuse-distance histogram")
        fig.savefig(out_dir / "reuse_distance_histogram.png")
        plt.close(fig)

    if fp_curve:
        fig, ax = plt.subplots()
        xs = sorted(fp_curve)
        ax.plot(xs, [fp_curve[x] for x in xs])
        ax.set_xlabel("window size (accesses)")
        ax.set_ylabel("avg distinct weight lines")
        ax.set_title(f"{arch_name} / {layer_name}: footprint curve")
        fig.savefig(out_dir / "footprint_curve.png")
        plt.close(fig)

    return summary