#!/usr/bin/env python3
"""Aggregate the Fig. 12 EDP rows and draw the RQ3 roofline.

The row fetch is deliberately kept outside the repository.  A complete run is
therefore reproducible with, for example::

    conda run --no-capture-output -n base python \
      zoo/roofline/fig12_roofline.py \
      /work/hdd/bebv/yyu9/neuro_cache_figs_20261116/fig12_edp/stokes/\
      full500_rows_fetch_20261116/rows

The input's ``sample_XXX`` directory is the sample identity.  The CSV sample
field is checked against that directory name; the directory remains the
authoritative identity because each file is a one-sample report.

The first invocation parses the large raw rows into ``outputs/extract.csv``;
later invocations reuse that compact extract.  Pass ``--refresh`` to rebuild
it from the raw fetch.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ARCHES = ("gustavsnn", "loas", "prosperity", "ptb", "spinalflow")
ARMS = ("spad", "cacheA", "cacheB")
SAMPLE_RE = re.compile(r"sample_(\d+)$")
DRAM_PACKET_BYTES = 32.0
DEFAULT_ARCH_CONFIG = Path(__file__).resolve().parents[1] / "wt500_fig3cfg" / "arch.yaml"
DEFAULT_ROWS_DIR = Path(
    "/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/fig12_edp/stokes/"
    "full500_rows_fetch_20261116/rows"
)
DEFAULT_ARCHX_DIR = Path(__file__).resolve().parents[1] / "archx" / "zoo" / "snn_edp" / "characterization"
DEFAULT_MAPSPACE_DIR = Path(__file__).resolve().parents[1] / "wt500_fig3cfg" / "mapspaces"

EXTRACT_FIELDS = [
    "record_type", "sample", "arch", "arm", "workload", "layer",
    "ops", "dram_bytes", "dram_accesses", "dram_line_bytes", "breakdown_bytes",
    "cycles", "T_s", "frequency_MHz", "complete", "status", "incomplete",
    "comparable_complete", "coverage_complete", "coverage", "expected_layers",
    "completed_layers", "feasible_layers", "infeasible_layers", "failed_layers",
    "oom_layers", "byte_source",
]


def _csv_rows(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError(f"malformed CSV row in {path}")
    return rows


def _number(value: str, field: str, path: Path) -> float:
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing {field} in {path}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {field} in {path}: {value!r}")
    return result


def _boolean(value: str, field: str, path: Path) -> bool:
    text = str(value).strip().lower()
    if text not in {"true", "false", "1", "0"}:
        raise ValueError(f"invalid {field} in {path}: {value!r}")
    return text in {"true", "1"}


def _sample_id(path: Path) -> int:
    match = SAMPLE_RE.fullmatch(path.name)
    if not match:
        raise ValueError(f"unexpected sample directory name: {path}")
    return int(match.group(1))


def _complete_model(row: dict[str, str], path: Path) -> bool:
    """Return whether layer coverage, rather than energy pricing, is complete.

    NG45 whole-model files intentionally mark energy as incomplete and
    non-comparable.  ``status`` and ``coverage_complete`` still distinguish
    complete layer sets from missing-layer sets, which is the relevant gate for
    this operation/latency roofline.
    """

    status = row.get("status", "").strip().lower()
    coverage_complete = _boolean(row.get("coverage_complete", ""), "coverage_complete", path)
    expected = int(_number(row.get("expected_layers", ""), "expected_layers", path))
    completed = int(_number(row.get("completed_layers", ""), "completed_layers", path))
    return status.startswith("complete") and coverage_complete and expected > 0 and completed == expected


def _literal_mapping(value: str, field: str, path: Path) -> dict[str, Any]:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"invalid {field} in {path}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} is not a mapping in {path}")
    return parsed


def _bytes_for_row(row: dict[str, str], path: Path) -> tuple[float, str, float, float, float]:
    """Derive physical off-chip bytes from the per-arm energy breakdown.

    ``shared.ddr4.read`` is the off-chip transaction count.  The archived
    NoC provenance gives the physical DRAM burst size (64 B), and
    ``shared.ddr4_io.byte`` is an independent byte-count cross-check.  This is
    deliberately arm-local: cacheA/cacheB and spad have different DRAM miss
    counts even when their count-pass weight bytes are identical.
    """

    breakdown = _literal_mapping(row.get("breakdown", ""), "breakdown", path)
    read = breakdown.get("shared.ddr4.read")
    if not isinstance(read, dict) or "count" not in read:
        raise ValueError(
            f"missing shared.ddr4.read DRAM component for {row.get('arch')}, "
            f"{row.get('arm')} row ({row.get('capture')}, {row.get('layer')}) in {path}"
        )
    accesses = float(read["count"])
    if not math.isfinite(accesses) or accesses < 0:
        raise ValueError(f"invalid shared.ddr4.read count in {path}: {accesses!r}")
    if read.get("count_expression") != "dram_accesses":
        raise ValueError(f"shared.ddr4.read is not dram_accesses in {path}")

    provenance = _literal_mapping(row.get("input_count_provenance", ""), "input_count_provenance", path)
    noc = provenance.get("noc", {})
    units = noc.get("units", {}) if isinstance(noc, dict) else {}
    if not isinstance(units, dict) or "dram_burst_bytes" not in units:
        raise ValueError(f"missing noc.units.dram_burst_bytes in {path}")
    line_bytes = float(units["dram_burst_bytes"])
    if not math.isfinite(line_bytes) or line_bytes <= 0:
        raise ValueError(f"invalid DRAM burst size in {path}: {line_bytes!r}")

    computed = accesses * line_bytes
    io = breakdown.get("shared.ddr4_io.byte")
    if not isinstance(io, dict) or "count" not in io:
        raise ValueError(f"missing shared.ddr4_io.byte cross-check in {path}")
    breakdown_bytes = float(io["count"])
    if not math.isclose(computed, breakdown_bytes, rel_tol=0.0, abs_tol=0.0):
        raise ValueError(
            f"DRAM bytes disagree in {path}: {accesses:g} * {line_bytes:g} = "
            f"{computed:g}, breakdown has {breakdown_bytes:g}"
        )
    if io.get("count_expression") != "dram_bytes":
        raise ValueError(f"shared.ddr4_io.byte is not dram_bytes in {path}")
    return computed, "breakdown.shared.ddr4.read*dram_burst_bytes", accesses, line_bytes, breakdown_bytes


def _verify_counts_json(row: dict[str, str], path: Path, op_count: float,
                        byte_count: float, byte_source: str) -> None:
    """Cross-check the flattened count columns against counts_json."""

    text = row.get("counts_json", "").strip()
    if not text:
        raise ValueError(f"missing counts_json in {path}")
    try:
        counts = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid counts_json in {path}") from exc
    if not isinstance(counts, dict) or "A" not in counts:
        raise ValueError(f"counts_json has no A in {path}")
    if not math.isclose(float(counts["A"]), op_count, rel_tol=0.0, abs_tol=0.0):
        raise ValueError(f"count_A disagrees with counts_json.A in {path}")


def _check_sample_column(rows: Iterable[dict[str, str]], path: Path, expected: set[str]) -> None:
    values = {row.get("sample", "") for row in rows}
    if values != expected:
        raise ValueError(f"expected archived sample field {sorted(expected)} in {path}, got {sorted(values)}")


def _model_reason(model: dict[str, str]) -> dict[str, str]:
    return {
        "status": model.get("status", ""),
        "incomplete": model.get("incomplete", ""),
        "comparable_complete": model.get("comparable_complete", ""),
        "coverage_complete": model.get("coverage_complete", ""),
        "coverage": model.get("coverage", ""),
        "expected_layers": model.get("expected_layers", ""),
        "completed_layers": model.get("completed_layers", ""),
        "feasible_layers": model.get("feasible_layers", ""),
        "infeasible_layers": model.get("infeasible_layers", ""),
        "failed_layers": model.get("failed_layers", ""),
        "oom_layers": model.get("oom_layers", ""),
    }


def _extract_record(record_type: str, sample: int, arch: str, arm: str,
                    workload: str, *, layer: str = "", complete: bool,
                    reason: dict[str, str] | None = None, **values: Any) -> dict[str, Any]:
    reason = reason or {}
    record = {field: "" for field in EXTRACT_FIELDS}
    record.update({
        "record_type": record_type,
        "sample": sample,
        "arch": arch,
        "arm": arm,
        "workload": workload,
        "layer": layer,
        "complete": int(complete),
    })
    record.update(reason)
    record.update(values)
    return record


def extract_rows(rows_dir: Path, extract_path: Path) -> None:
    """Parse the large raw rows once into a compact, reproducible extract."""

    sample_dirs = sorted(
        path for path in rows_dir.glob("sample_*")
        if path.is_dir() and SAMPLE_RE.fullmatch(path.name)
    )
    if not sample_dirs:
        raise ValueError(f"no sample_XXX directories under {rows_dir}")
    extract_path.parent.mkdir(parents=True, exist_ok=True)
    with extract_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXTRACT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for sample_dir in sample_dirs:
            sample = _sample_id(sample_dir)
            result_path = sample_dir / "results_ng45.csv"
            whole_path = sample_dir / "whole_model_ng45.csv"
            result_rows = _csv_rows(result_path)
            whole_rows = _csv_rows(whole_path)
            _check_sample_column(result_rows, result_path, {str(sample)})
            _check_sample_column(whole_rows, whole_path, {"0"})

            results_by_key: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
            for row in result_rows:
                arch = row.get("arch", "")
                arm = row.get("arm", "")
                workload = row.get("capture", "")
                if arch not in ARCHES or arm not in ARMS or not workload:
                    raise ValueError(f"unexpected per-layer identity in {result_path}: {arch}, {arm}, {workload}")
                results_by_key[(arch, arm, workload, sample)].append(row)

            seen_whole: set[tuple[str, str, str, int]] = set()
            for model in whole_rows:
                arch = model.get("arch", "")
                arm = model.get("arm", "")
                workload = model.get("benchmark", "")
                key = (arch, arm, workload, sample)
                if arch not in ARCHES or arm not in ARMS or not workload:
                    raise ValueError(f"unexpected whole-model identity in {whole_path}: {key}")
                if key in seen_whole:
                    raise ValueError(f"duplicate whole-model identity in {whole_path}: {key}")
                seen_whole.add(key)
                complete = _complete_model(model, whole_path)
                reason = _model_reason(model)
                writer.writerow(_extract_record("model", sample, arch, arm, workload,
                                                complete=complete, reason=reason))
                if not complete:
                    continue

                rows = results_by_key.get(key, [])
                expected = int(_number(model["expected_layers"], "expected_layers", whole_path))
                if len(rows) != expected:
                    raise ValueError(
                        f"complete model {key} has {len(rows)} per-layer rows, expected {expected}"
                    )
                layers = [row.get("layer", "") for row in rows]
                if len(set(layers)) != len(layers) or any(not layer for layer in layers):
                    raise ValueError(f"duplicate/missing layer in complete model {key}")

                for row in rows:
                    op_count = _number(row.get("count_A", ""), "count_A", result_path)
                    byte_count, source, accesses, line_bytes, breakdown_bytes = _bytes_for_row(row, result_path)
                    _verify_counts_json(row, result_path, op_count, byte_count, source)
                    ts = _number(row.get("T_s", ""), "T_s", result_path)
                    row_cycles = _number(row.get("total_cycles", ""), "total_cycles", result_path)
                    frequency_mhz = _number(row.get("frequency_MHz", ""), "frequency_MHz", result_path)
                    if op_count <= 0 or byte_count <= 0 or ts <= 0 or row_cycles <= 0 or frequency_mhz <= 0:
                        raise ValueError(f"non-positive operation/byte/time value in {result_path}")
                    expected_ts = row_cycles / (frequency_mhz * 1e6)
                    if not math.isclose(ts, expected_ts, rel_tol=2e-6, abs_tol=1e-12):
                        raise ValueError(
                            f"T_s disagrees with total_cycles/frequency in {result_path}: "
                            f"{ts} vs {expected_ts}"
                        )
                    writer.writerow(_extract_record(
                        "layer", sample, arch, arm, workload, layer=row["layer"],
                        complete=True, reason=reason, ops=op_count, dram_bytes=byte_count,
                        dram_accesses=accesses, dram_line_bytes=line_bytes,
                        breakdown_bytes=breakdown_bytes, cycles=row_cycles, T_s=ts,
                        frequency_MHz=frequency_mhz, byte_source=source,
                    ))


def load_extract(extract_path: Path) -> tuple[dict[tuple[str, str, str], list[dict[str, float]]], dict[str, Any]]:
    """Return sample-level points grouped by (arch, arm, workload)."""

    rows = _csv_rows(extract_path)
    if not rows:
        raise ValueError(f"empty extract: {extract_path}")
    model_rows: dict[tuple[str, str, str, int], dict[str, str]] = {}
    layer_rows: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        kind = row.get("record_type", "")
        arch, arm, workload = row.get("arch", ""), row.get("arm", ""), row.get("workload", "")
        sample = int(_number(row.get("sample", ""), "sample", extract_path))
        if arch not in ARCHES or arm not in ARMS or not workload:
            raise ValueError(f"unexpected extract identity in {extract_path}: {arch}, {arm}, {workload}")
        key = (arch, arm, workload, sample)
        if kind == "model":
            if key in model_rows:
                raise ValueError(f"duplicate model record in {extract_path}: {key}")
            model_rows[key] = row
        elif kind == "layer":
            if row.get("complete") != "1":
                raise ValueError(f"incomplete layer record in {extract_path}: {key}")
            layer_rows[key].append(row)
        else:
            raise ValueError(f"unknown extract record_type in {extract_path}: {kind!r}")

    samples_by_group: dict[tuple[str, str, str], list[dict[str, float]]] = defaultdict(list)
    frequencies: set[float] = set()
    bytes_sources: defaultdict[str, int] = defaultdict(int)
    excluded_groups: dict[tuple[str, str, str], dict[str, str]] = {}
    model_reasons: dict[tuple[str, str, str], dict[str, str]] = {}
    complete_keys: set[tuple[str, str, str, int]] = set()
    complete_models = 0
    excluded_models = 0
    hand_check: dict[str, Any] | None = None
    for key, model in sorted(model_rows.items()):
        arch, arm, workload, sample = key
        reason = {field: model.get(field, "") for field in (
            "status", "incomplete", "comparable_complete", "coverage_complete", "coverage",
            "expected_layers", "completed_layers", "feasible_layers", "infeasible_layers",
            "failed_layers", "oom_layers",
        )}
        group = (arch, arm, workload)
        previous = model_reasons.setdefault(group, reason)
        if previous != reason:
            raise ValueError(f"inconsistent completeness flags across samples for {group}")
        complete = model.get("complete") == "1"
        if not complete:
            excluded_models += 1
            excluded_groups[group] = reason
            continue

        complete_models += 1
        complete_keys.add(key)
        sample_layers = layer_rows.get(key, [])
        expected = int(_number(model.get("expected_layers", ""), "expected_layers", extract_path))
        if len(sample_layers) != expected:
            raise ValueError(f"complete model {key} has {len(sample_layers)} extract rows, expected {expected}")
        layers = [row.get("layer", "") for row in sample_layers]
        if len(set(layers)) != len(layers) or any(not layer for layer in layers):
            raise ValueError(f"duplicate/missing layer in complete extract model {key}")

        ops = payload_bytes = time_s = cycles = 0.0
        model_frequencies: set[float] = set()
        for row in sample_layers:
            op_count = _number(row.get("ops", ""), "ops", extract_path)
            byte_count = _number(row.get("dram_bytes", ""), "dram_bytes", extract_path)
            ts = _number(row.get("T_s", ""), "T_s", extract_path)
            row_cycles = _number(row.get("cycles", ""), "cycles", extract_path)
            frequency_mhz = _number(row.get("frequency_MHz", ""), "frequency_MHz", extract_path)
            if op_count <= 0 or byte_count <= 0 or ts <= 0 or row_cycles <= 0 or frequency_mhz <= 0:
                raise ValueError(f"non-positive operation/byte/time value in {extract_path}: {key}")
            expected_ts = row_cycles / (frequency_mhz * 1e6)
            if not math.isclose(ts, expected_ts, rel_tol=2e-6, abs_tol=1e-12):
                raise ValueError(f"extract T_s disagrees with cycles/frequency in {extract_path}: {key}")
            ops += op_count
            payload_bytes += byte_count
            time_s += ts
            cycles += row_cycles
            model_frequencies.add(frequency_mhz)
            frequencies.add(frequency_mhz)
            bytes_sources[row.get("byte_source", "")] += 1
            if hand_check is None:
                hand_check = {
                    "sample": sample, "arch": arch, "arm": arm, "workload": workload,
                    "layer": row.get("layer", ""), "dram_accesses": row.get("dram_accesses", ""),
                    "dram_line_bytes": row.get("dram_line_bytes", ""),
                    "computed_bytes": row.get("dram_bytes", ""),
                    "breakdown_bytes": row.get("breakdown_bytes", ""),
                }
        if len(model_frequencies) != 1:
            raise ValueError(f"mixed frequencies in complete model {key}: {model_frequencies}")
        frequency_hz = next(iter(model_frequencies)) * 1e6
        if not math.isclose(time_s, cycles / frequency_hz, rel_tol=2e-6, abs_tol=1e-12):
            raise ValueError(f"summed T_s disagrees with summed cycles in complete model {key}")
        samples_by_group[group].append({
            "sample": float(sample), "ops": ops, "bytes": payload_bytes,
            "time_s": time_s, "frequency_hz": frequency_hz,
            "P": ops / time_s, "OI": ops / payload_bytes,
        })

    if not frequencies:
        raise ValueError("no complete models found in extract")
    metadata = {
        "sample_dirs": len({key[3] for key in model_rows}),
        "sample_ids": sorted({key[3] for key in model_rows}),
        "complete_models": complete_models,
        "excluded_models": excluded_models,
        "bytes_sources": dict(bytes_sources),
        "frequencies_MHz": sorted(frequencies),
        "complete_groups": len(samples_by_group),
        "excluded_groups": excluded_groups,
        "hand_check": hand_check or {},
    }
    return samples_by_group, metadata


def _ci(values: list[float]) -> tuple[float, float, float]:
    """Return mean and two-sided 95% Student-t confidence limits."""

    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean, mean, mean
    try:
        from scipy.stats import t as student_t

        critical = float(student_t.ppf(0.975, len(values) - 1))
    except ImportError:
        critical = 1.96
    margin = critical * statistics.stdev(values) / math.sqrt(len(values))
    return mean, max(0.0, mean - margin), mean + margin


def aggregate(samples_by_group: dict[tuple[str, str, str], list[dict[str, float]]]) -> list[dict[str, Any]]:
    points = []
    for (arch, arm, workload), samples in sorted(samples_by_group.items(), key=lambda item: item[0]):
        oi, oi_low, oi_high = _ci([sample["OI"] for sample in samples])
        performance, p_low, p_high = _ci([sample["P"] for sample in samples])
        points.append({
            "point": f"{workload}:{arch}",
            "arch": arch,
            "arm": arm,
            "workload": workload,
            "OI": oi,
            "P": performance,
            "OI_ci95_low": oi_low,
            "OI_ci95_high": oi_high,
            "P_ci95_low": p_low,
            "P_ci95_high": p_high,
            "n_samples": len(samples),
        })
    return points


def _spatial_product(mapspace_path: Path, pes_per_node: float) -> tuple[float, dict[str, float]]:
    import yaml

    config = yaml.safe_load(mapspace_path.read_text())
    try:
        dimensions = config["dataflow"]["node_dim_capacity"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"cannot derive spatial mapspace from {mapspace_path}") from exc
    factors: dict[str, float] = {}
    product = 1.0
    for dimension, value in dimensions.items():
        if isinstance(value, dict) and "spatial" in value:
            factor = float(value["spatial"])
            if factor <= 0:
                raise ValueError(f"non-positive spatial factor in {mapspace_path}: {dimension}")
            factors[dimension] = factor
            product *= factor
    if not math.isclose(product, pes_per_node, rel_tol=0.0, abs_tol=0.0):
        raise ValueError(
            f"mapspace spatial product {product:g} disagrees with {pes_per_node:g} PEs in {mapspace_path}"
        )
    return product, factors


def _module_instances(path: Path, module_name: str) -> float | None:
    import yaml

    config = yaml.safe_load(path.read_text())
    module = config.get("architecture", {}).get("module", {}).get(module_name, {})
    value = module.get("physical_instances")
    return None if value is None else float(value)


def _ptb_backend_lanes(path: Path) -> tuple[float, str]:
    text = path.read_text()
    rows = re.search(r"PE_ROWS_MAX\s*=\s*(\d+)", text)
    columns = re.search(r"PE_COLS_MAX\s*=\s*(\d+)", text)
    if not rows or not columns:
        raise ValueError(f"cannot derive PTB array capacity from {path}")
    lanes = float(int(rows.group(1)) * int(columns.group(1)))
    return lanes, f"{path} PE_ROWS_MAX*PE_COLS_MAX"


def _roof_config(path: Path, frequency_hz: float, archx_dir: Path,
                 mapspace_dir: Path, repo_root: Path) -> dict[str, Any]:
    import yaml

    config = yaml.safe_load(path.read_text())
    try:
        arch_config = config["arch"]
        node_level = next(level for level in arch_config["storage"] if level["name"] == "NodeLevel")
        nodes = float(node_level["instances"])
        pes = float(node_level["pe"]["num_pes"])
        dram_latency = float(arch_config["bitwidths"]["DRAM_LATENCY"])
    except (KeyError, TypeError, StopIteration) as exc:
        raise ValueError(f"cannot derive roof parameters from {path}") from exc
    if nodes <= 0 or pes <= 0 or dram_latency <= 0:
        raise ValueError(f"non-positive roof parameter in {path}")

    compute: dict[str, dict[str, Any]] = {}
    for arch_name in ARCHES:
        archx_path = archx_dir / f"{arch_name}.architecture.yaml"
        mapspace_path = mapspace_dir / f"{arch_name}.yaml"
        if not archx_path.is_file() or not mapspace_path.is_file():
            raise ValueError(f"missing roof source for {arch_name}: {archx_path}, {mapspace_path}")
        spatial, spatial_factors = _spatial_product(mapspace_path, pes)
        adder = _module_instances(archx_path, "adder16")
        if adder is None:
            adder = _module_instances(archx_path, "adder32")
        registers = _module_instances(archx_path, "reg16")
        if registers is None:
            registers = _module_instances(archx_path, "reg32")
        backend_lanes = None
        backend_source = ""
        if arch_name == "ptb":
            backend_lanes, backend_source = _ptb_backend_lanes(
                repo_root / "src" / "lays" / "weight_trace_gen" / "ptb" / "PTBGen.h"
            )
            if registers is not None and not math.isclose(backend_lanes, registers, rel_tol=0.0, abs_tol=0.0):
                raise ValueError(f"PTB backend lanes disagree with archx register inventory")
        # The operation roof is the largest simultaneous accumulator inventory
        # declared by the vendored backend/config.  For SpinalFlow the mapspace
        # is the executable declaration: one COUT lane per PE.
        lanes_per_node = max(value for value in (spatial, adder, registers, backend_lanes) if value is not None)
        if lanes_per_node <= 0:
            raise ValueError(f"no defensible compute parallelism for {arch_name}")
        ops_per_cycle = nodes * lanes_per_node
        compute[arch_name] = {
            "archx_path": archx_path,
            "mapspace_path": mapspace_path,
            "spatial_factors": spatial_factors,
            "spatial_lanes_per_node": spatial,
            "adder_lanes_per_node": adder if adder is not None else "not declared",
            "register_lanes_per_node": registers if registers is not None else "not declared",
            "backend_lanes_per_node": backend_lanes if backend_lanes is not None else "not declared",
            "backend_source": backend_source,
            "lanes_per_node": lanes_per_node,
            "ops_per_cycle": ops_per_cycle,
            "compute_roof_ops_s": ops_per_cycle * frequency_hz,
        }
    dram_bytes_per_cycle = DRAM_PACKET_BYTES / dram_latency
    return {
        "nodes": nodes,
        "pes_per_node": pes,
        "dram_latency": dram_latency,
        "dram_bw_bytes_s": dram_bytes_per_cycle * frequency_hz,
        "dram_bw_bytes_cycle": dram_bytes_per_cycle,
        "frequency_hz": frequency_hz,
        "compute": compute,
    }


def _workload_label(workload: str) -> str:
    return workload.rsplit("/", 1)[-1]


def _repo_display_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def write_csv(points: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "point", "arch", "arm", "workload", "OI", "P",
        "OI_ci95_low", "OI_ci95_high", "P_ci95_low", "P_ci95_high", "n_samples",
    ]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for point in points:
            writer.writerow({field: point[field] for field in fields})


def _rate_label(rate: float) -> str:
    if rate >= 1e12:
        return f"{rate / 1e12:.3g}e12"
    return f"{rate / 1e9:.3g}e9"


def validate_roofs(points: list[dict[str, Any]], roofs: dict[str, Any]) -> None:
    offending = []
    for point in points:
        roof = roofs["compute"][point["arch"]]["compute_roof_ops_s"]
        for field in ("P", "P_ci95_high"):
            if point[field] > roof * 1.02:
                offending.append((point, field, roof))
    if offending:
        print("compute-roof sanity check failed (limit is roof * 1.02):", file=sys.stderr)
        for point, field, roof in offending:
            print(
                f"  {point['point']} arm={point['arm']} field={field} "
                f"value={point[field]:.9g} roof={roof:.9g} ratio={point[field] / roof:.6g}",
                file=sys.stderr,
            )
        raise ValueError(f"{len(offending)} points exceed their architecture compute roof")


def plot(points: list[dict[str, Any]], roofs: dict[str, Any], path_png: Path, path_pdf: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import numpy as np

    workloads = sorted({point["workload"] for point in points})
    colors = {workload: plt.get_cmap("tab10")(index % 10) for index, workload in enumerate(workloads)}
    markers = {arch: marker for arch, marker in zip(ARCHES, ("o", "s", "^", "D", "P"))}

    x_values = [value for point in points for value in (point["OI_ci95_low"], point["OI_ci95_high"])]
    y_values = [value for point in points for value in (point["P_ci95_low"], point["P_ci95_high"])]
    x_values = [value for value in x_values if value > 0]
    y_values = [value for value in y_values if value > 0]
    if not x_values or not y_values:
        raise ValueError("no positive values available for log-log axes")
    x_min = min(x_values) * 0.65
    x_max = max(x_values) * 1.6
    compute_roofs = roofs["compute"]
    ridges = {
        arch: detail["compute_roof_ops_s"] / roofs["dram_bw_bytes_s"]
        for arch, detail in compute_roofs.items()
    }
    x_min = min(x_min, min(ridges.values()) * 1e-2)
    x_max = max(x_max, max(ridges.values()) * 1e2)
    y_min = min(min(y_values) * 0.65, min(detail["compute_roof_ops_s"] for detail in compute_roofs.values()) * 1e-3)
    y_max = max(max(y_values) * 1.6, max(detail["compute_roof_ops_s"] for detail in compute_roofs.values()) * 1.6)
    dram_x = np.logspace(math.log10(x_min), math.log10(max(max(ridges.values()), x_min)), 200)

    fig, axes = plt.subplots(1, 3, figsize=(14.0, 6.3), sharex=True, sharey=True)
    roof_colors = {arch: color for arch, color in zip(ARCHES, ("#222222", "#6a3d9a", "#1b9e77", "#b15928", "#4d4d4d"))}
    roof_groups: dict[float, list[str]] = defaultdict(list)
    for arch in ARCHES:
        roof_groups[compute_roofs[arch]["compute_roof_ops_s"]].append(arch)
    for ax, arm in zip(axes, ARMS):
        dram_line, = ax.plot(
            dram_x, roofs["dram_bw_bytes_s"] * dram_x,
            color="#555555", lw=1.2, ls="--",
            label=f"DRAM bandwidth {roofs['dram_bw_bytes_s'] / 1e9:.0f} GB/s",
            zorder=1,
        )
        compute_lines = []
        for roof, roof_arches in roof_groups.items():
            ridge = roof / roofs["dram_bw_bytes_s"]
            arch_label = ", ".join(roof_arches)
            line, = ax.plot(
                [ridge, x_max], [roof, roof], color=roof_colors[roof_arches[0]], lw=0.9,
                ls=(0, (3, 2)), label=f"Compute roof {arch_label} {_rate_label(roof)} Operations/s",
                zorder=1,
            )
            compute_lines.append(line)
        for point in points:
            if point["arm"] != arm:
                continue
            xerr = np.array([[point["OI"] - point["OI_ci95_low"]], [point["OI_ci95_high"] - point["OI"]]])
            yerr = np.array([[point["P"] - point["P_ci95_low"]], [point["P_ci95_high"] - point["P"]]])
            ax.errorbar(
                point["OI"], point["P"], xerr=xerr, yerr=yerr,
                fmt=markers[point["arch"]], ms=6.5,
                color=colors[point["workload"]], markeredgecolor="white", markeredgewidth=0.6,
                markerfacecolor="none" if point["arch"] == "loas" else colors[point["workload"]],
                ecolor=colors[point["workload"]], elinewidth=0.8, capsize=2.2,
                zorder=4 if point["arch"] == "loas" else 3,
            )
        ax.set_title(arm)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.grid(which="both", alpha=0.2, lw=0.5)
        if arm == "spad":
            ax.legend(handles=[dram_line, *compute_lines], loc="lower right", fontsize=7, frameon=True)

    axes[0].set_ylabel("Performance [Operations/s]")
    axes[1].set_xlabel("Operational intensity [Operations/byte]")
    workload_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=colors[workload],
               markeredgecolor="white", markersize=7, label=_workload_label(workload))
        for workload in workloads
    ]
    arch_handles = [
        Line2D([0], [0], marker=markers[arch], color="#444444", linestyle="none",
               markersize=7, label=arch)
        for arch in ARCHES
    ]
    fig.legend(handles=workload_handles, title="Workload (color)", loc="upper center",
               bbox_to_anchor=(0.5, 0.945), ncol=4, fontsize=8, title_fontsize=9, frameon=False)
    fig.legend(handles=arch_handles, title="Architecture (marker)", loc="upper center",
               bbox_to_anchor=(0.5, 0.845), ncol=5, fontsize=8, title_fontsize=9, frameon=False)
    fig.suptitle("Fig. 12 EDP roofline", y=0.995, fontsize=13)
    fig.tight_layout(rect=(0.02, 0.03, 0.99, 0.74))
    path_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_png, dpi=300)
    fig.savefig(path_pdf)
    plt.close(fig)


def write_provenance(path: Path, rows_dir: Path, metadata: dict[str, Any], roofs: dict[str, Any],
                     points: list[dict[str, Any]], arch_config: Path, extract_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extract_display = _repo_display_path(extract_path)
    arch_config_display = _repo_display_path(arch_config)
    repo_root = Path(__file__).resolve().parents[2]
    sample_ids = ", ".join(f"{int(sample):03d}" for sample in metadata["sample_ids"])
    sources = ", ".join(f"{name} ({count:,})" for name, count in sorted(metadata["bytes_sources"].items()))
    observed_arches = sorted({point["arch"] for point in points} | {
        arch for arch, _, _ in metadata["excluded_groups"]
    })
    observed_arms = sorted({point["arm"] for point in points} | {
        arm for _, arm, _ in metadata["excluded_groups"]
    })
    workloads = sorted({point["workload"] for point in points} | {
        workload for _, _, workload in metadata["excluded_groups"]
    })
    expected_points = len(workloads) * len(observed_arches) * len(observed_arms)
    missing_groups = sorted(metadata["excluded_groups"])
    missing_rows = []
    for arch, arm, workload in missing_groups:
        reason = metadata["excluded_groups"][(arch, arm, workload)]
        missing_rows.append(
            f"| `{arch}` | `{arm}` | `{workload}` | `{reason['status']}` | "
            f"`{reason['coverage']}` ({reason['completed_layers']}/{reason['expected_layers']}) | "
            f"`{reason['infeasible_layers']}` infeasible; `{reason['failed_layers']}` failed; "
            f"`{reason['oom_layers']}` OOM |"
        )
    missing_table = "\n".join(missing_rows) or "| (none) | | | | | |"
    hand = metadata.get("hand_check", {})
    hand_line = (
        f"For example, sample `{int(float(hand['sample'])):03d}` `{hand['arch']}`/`{hand['arm']}` "
        f"`{hand['workload']}` `{hand['layer']}` has "
        f"`{hand['dram_accesses']}` DRAM reads × `{hand['dram_line_bytes']}` B = "
        f"`{hand['computed_bytes']}` B, matching the breakdown byte count "
        f"`{hand['breakdown_bytes']}`."
        if hand else "The extract did not contain a byte cross-check row."
    )
    roof_rows = []
    for arch in ARCHES:
        detail = roofs["compute"][arch]
        spatial = ", ".join(f"{dim}={value:g}" for dim, value in detail["spatial_factors"].items())
        backend = (
            f"; backend `{detail['backend_source'].replace(str(repo_root) + '/', '')}` gives "
            f"{detail['backend_lanes_per_node']:g}/node"
            if isinstance(detail["backend_lanes_per_node"], (int, float)) else ""
        )
        roof_rows.append(
            f"- **{arch}:** mapspace spatial factors ({spatial}) = "
            f"{detail['spatial_lanes_per_node']:g}/node; archx adder inventory = "
            f"{detail['adder_lanes_per_node']}/node; register/accumulator inventory = "
            f"{detail['register_lanes_per_node']}/node{backend}; selected peak = "
            f"{detail['lanes_per_node']:g}/node × {roofs['nodes']:g} nodes = "
            f"{detail['ops_per_cycle']:g} Operations/cycle = "
            f"{detail['compute_roof_ops_s']:.6g} Operations/s."
        )
    gesture_workloads = [workload for workload in workloads if "gesture" in workload.lower()]
    gesture_missing = [
        (arch, arm, workload) for arch, arm, workload in missing_groups if workload in gesture_workloads
    ]
    gesture_note = (
        f"The gesture workload is missing {len(gesture_missing)} combinations in this extract."
        if gesture_missing else
        "The gesture workload has complete coverage for every architecture and arm in this extract."
    )
    text = f"""# Fig. 12 EDP roofline provenance

Generated by `zoo/roofline/fig12_roofline.py` from the read-only row fetch
`{rows_dir}`. Stage 1 stores the compact extract at `{extract_display}`; Stage 2
reads that extract. The output contains {len(points)} aggregate points from
{metadata['sample_dirs']} archived sample directories ({sample_ids}).

## Input and completeness

- Each `sample_XXX/results_ng45.csv` is joined to its sibling
  `whole_model_ng45.csv` by `(arch, arm, benchmark, sample-directory-id)`;
  the CSV `sample` field is checked against that directory id during Stage 1.
- A model is retained when `status` starts with `complete`,
  `coverage_complete=True`, and `completed_layers == expected_layers`; this
  excludes {metadata['excluded_models']} incomplete model records. The NG45
  files intentionally set `incomplete=True` and `comparable_complete=False`
  for energy pricing, so those flags are retained in the extract and recorded
  as a caveat rather than used to discard otherwise complete operation/latency rows.
- For each retained sample, `Ops = sum(count_A)`,
  `DRAM_bytes = sum(per-arm DRAM bytes)`, and `T_total = sum(T_s)` over layers.
  Then `P = Ops/T_total` and `OI = Ops/DRAM_bytes`; the aggregate is the
  arithmetic mean of sample points, never a mean of layer ratios. Whiskers are
  two-sided 95% Student-t confidence intervals across samples. Every CSV row
  is one whole-model `(arch, arm, workload)` aggregate; no per-layer point is emitted.

## Missing whole-model points

The expected point count is computed from the data as
`{len(workloads)} workloads × {len(observed_arches)} architectures × {len(observed_arms)} arms = {expected_points}`.
The {len(missing_groups)} missing combinations are:

| arch | arm | workload | status | coverage | layer outcome |
|---|---|---|---|---|---|
{missing_table}

These rows are excluded by the whole-model completeness flags, not by a
Stage-2 filter accident. The flags and layer counts above are computed from
the archived records; no missing-combo prose is hardcoded. {gesture_note}
The delivered point count is therefore `{len(points)}`.

## Counter choices and byte verification

- **Operations:** `count_A`, because the Fig. 12 count pass defines `A =
  S_win * COUT`, the spike-window-gated MAC/accumulate count. The Stage-1
  parser checks the flattened field against `counts_json.A` for every retained
  layer row.
- **DRAM bytes:** the per-arm energy breakdown component
  `shared.ddr4.read.count` is the physical off-chip transaction count. Stage 1
  multiplies it by the row's provenance `noc.units.dram_burst_bytes` (64 B in
  this fetch), and checks the result against
  `shared.ddr4_io.byte.count`. This makes OI reflect cacheA/cacheB/spad DRAM
  traffic separately. Observed source counts: {sources}.
- No `counts_json` fallback was used: every retained row had both DRAM
  breakdown components and a burst-size provenance field. A future extract
  missing those fields fails rather than silently using an arm-independent
  weight counter.

{hand_line}

## Roof derivation

The shared campaign configuration `{arch_config_display}` supplies `{roofs['nodes']:g}`
NodeLevel instances, `{roofs['pes_per_node']:g}` PEs/node, frequency
`{roofs['frequency_hz'] / 1e6:g}` MHz, and `DRAM_LATENCY={roofs['dram_latency']:g}`.
The DRAM roof is shared because
`{DRAM_PACKET_BYTES:g} B / {roofs['dram_latency']:g} cycles = `
`{roofs['dram_bw_bytes_cycle']:g} B/cycle = {roofs['dram_bw_bytes_s']:.6g} B/s`
(`{roofs['dram_bw_bytes_s'] / 1e9:.0f} GB/s`).

Compute roofs are per architecture. The script reads the vendored archx
inventories and the wt500 mapspaces at generation time, and uses the largest
declared simultaneous accumulator-lane inventory (with the mapspace spatial
product as the PE-level lower bound):
{chr(10).join(roof_rows)}

The hard generation-time sanity check rejects every point or upper CI whisker
above `1.02 ×` its architecture roof and prints the offending rows; therefore
the figure never plots data over a selected compute ceiling. Labels use
per-second units, including `Performance [Operations/s]` and
`DRAM bandwidth {roofs['dram_bw_bytes_s'] / 1e9:.0f} GB/s`.

## Generated files

- `{extract_display}`
- `zoo/roofline/outputs/roofline.csv`
- `zoo/roofline/outputs/fig12_roofline.png`
- `zoo/roofline/outputs/fig12_roofline.pdf`
"""
    path.write_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows_dir", type=Path, nargs="?", default=DEFAULT_ROWS_DIR,
                        help=f"read-only directory containing sample_XXX rows (default: {DEFAULT_ROWS_DIR})")
    parser.add_argument("--arch-config", type=Path, default=DEFAULT_ARCH_CONFIG,
                        help=f"shared campaign arch YAML (default: {DEFAULT_ARCH_CONFIG})")
    parser.add_argument("--archx-dir", type=Path, default=DEFAULT_ARCHX_DIR,
                        help=f"vendored archx characterization directory (default: {DEFAULT_ARCHX_DIR})")
    parser.add_argument("--mapspace-dir", type=Path, default=DEFAULT_MAPSPACE_DIR,
                        help=f"wt500 mapspace directory (default: {DEFAULT_MAPSPACE_DIR})")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "outputs")
    parser.add_argument("--provenance", type=Path,
                        default=Path(__file__).resolve().parent / "docs" / "fig12_provenance.md")
    parser.add_argument("--refresh", action="store_true",
                        help="reparse raw rows into extract.csv before Stage 2")
    args = parser.parse_args(argv)

    rows_dir = args.rows_dir.resolve()
    extract_path = args.output_dir / "extract.csv"
    if args.refresh or not extract_path.is_file():
        extract_rows(rows_dir, extract_path)
        stage1 = "; refreshed extract"
    else:
        stage1 = "; reused extract"
    samples_by_group, metadata = load_extract(extract_path)
    points = aggregate(samples_by_group)
    if not points:
        raise ValueError("no aggregate points after completeness filtering")
    frequencies = metadata["frequencies_MHz"]
    if len(frequencies) != 1:
        raise ValueError(f"roof frequency is not shared by the rows: {frequencies}")
    repo_root = Path(__file__).resolve().parents[2]
    roofs = _roof_config(
        args.arch_config.resolve(), frequencies[0] * 1e6,
        args.archx_dir.resolve(), args.mapspace_dir.resolve(), repo_root,
    )
    validate_roofs(points, roofs)

    write_csv(points, args.output_dir / "roofline.csv")
    plot(points, roofs, args.output_dir / "fig12_roofline.png", args.output_dir / "fig12_roofline.pdf")
    write_provenance(
        args.provenance, rows_dir, metadata, roofs, points,
        args.arch_config.resolve(), extract_path,
    )
    print(
        f"wrote {len(points)} points from {metadata['sample_dirs']} samples{stage1}; "
        f"compute roofs="
        f"{', '.join(f'{arch}:{roofs["compute"][arch]["compute_roof_ops_s"]:.6g}' for arch in ARCHES)} Operations/s, "
        f"DRAM roof={roofs['dram_bw_bytes_s']:.6g} B/s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
