#!/usr/bin/env python3
"""Aggregate eval_scaling rows into whole-model performance and traffic.

Performance is the reciprocal of the sum of scratchpad ``weight_makespan``
over layers (or cache ``total_cycles``), normalized to the architecture's
single-node 1x baseline.  Deduplicated scratchpad rows are expanded from
``dedup_map.json``; cache rows are never expanded because cache capacity
changes the simulation result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pathlib
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

try:
    from scipy.stats import t as student_t
except ImportError:  # pragma: no cover - exercised only in minimal envs
    student_t = None


HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "outputs"
CAPTURE = "loas_vgg16_T4_n500"
SPAD_ARM = "spad_nocsim"
CACHE_ARM = "cache"
# Q11 R1 is adopted: scratchpad row 1 uses the weight-only eventsim pass;
# cachesim already reports a weight-path makespan directly.
PERFORMANCE_COLUMN = "weight_makespan"
CACHE_PERFORMANCE_COLUMN = "total_cycles"


def analytic_traffic(schedules: dict[str, dict[str, Any]]) -> float:
    """Diagnostic only: the old CoSA product, never the plotted metric."""

    total = 0.0
    for schedule in schedules.values():
        metrics = schedule["result"]["metrics"]
        total += metrics["temporal_traffic"]["weight"] * metrics["util"]["weight"]
    return total


def nodes_per_layer(schedules: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Product of the schedule's NoCLevel spatial splitting loop sizes."""

    result = {}
    for layer, schedule in schedules.items():
        strategy = schedule["result"]["strategy"]
        loops = strategy.get("NoCLevel", {}).get("spatial_splitting", {}).get("loops", [])
        product = 1
        for loop in loops:
            product *= int(loop["size"])
        result[layer] = product
    return result


def mean_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        raise ValueError("cannot aggregate an empty sample set")
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    sd = math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))
    return mean, critical_value(len(values)) * sd / math.sqrt(len(values))


def critical_value(sample_count: int) -> float:
    """Return the two-sided 95% critical value for a sample count."""

    if sample_count < 2:
        raise ValueError("a CI needs at least two samples")
    return (
        float(student_t.ppf(0.975, sample_count - 1))
        if student_t is not None
        else 1.96
    )


def read_input(path: pathlib.Path, inputs: list[dict[str, Any]]) -> str:
    """Hash the exact bytes consumed, before parsing or later filesystem changes."""

    data = path.read_bytes()
    repo = HERE.parents[1]
    name = str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path)
    inputs.append({
        "path": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })
    return data.decode("utf-8")


def _parse_point(point: str) -> tuple[str, str, str, int]:
    explicit = re.fullmatch(
        r"(?P<arch>[A-Za-z0-9]+)_(?P<arm>cache|spad_nocsim|spad)_"
        r"(?P<side>single|multi)_x(?P<m>\d+)",
        point,
    )
    if explicit:
        arm = CACHE_ARM if explicit.group("arm") == "cache" else SPAD_ARM
        side = explicit.group("side")
        if arm == CACHE_ARM and side != "multi":
            raise ValueError("cache points use the multi-node schedule")
        return explicit.group("arch"), arm, side, int(explicit.group("m"))
    match = re.fullmatch(
        r"(?:(?P<arch>[A-Za-z0-9]+)_)?"
        r"(?P<kind>cache|spad_nocsim|spad|single|multi)_x(?P<m>\d+)",
        point,
    )
    if not match:
        raise ValueError(f"invalid point token {point!r}")
    arch = match.group("arch") or "loas"
    kind = match.group("kind")
    multiplier = int(match.group("m"))
    if kind == "cache":
        return arch, CACHE_ARM, "multi", multiplier
    if kind in {"single", "multi"}:
        return arch, SPAD_ARM, kind, multiplier
    return arch, SPAD_ARM, "multi", multiplier


def _read_result_rows(inputs: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Read both scratchpad and cache result layouts, validating byte columns."""

    rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    paths: list[tuple[pathlib.Path, str]] = []
    paths.extend((path, SPAD_ARM) for path in sorted((OUT / "s4").glob("*.csv")))
    paths.extend((path, CACHE_ARM) for path in sorted((OUT / "s4c").glob("*.csv")))
    for path, directory_arm in paths:
        reader = csv.DictReader(io.StringIO(read_input(path, inputs)))
        fields = set(reader.fieldnames or [])
        if directory_arm == SPAD_ARM:
            required = {f"dram_bytes_{var}" for var in ("weight", "psum", "vmem")}
        else:
            required = {"dram_bytes", "total_cycles", "tick_base_total"}
        missing = required - fields
        if missing:
            raise ValueError(
                f"{path}: missing required byte columns: {', '.join(sorted(missing))}"
            )
        for line, row in enumerate(reader, start=2):
            point = row.get("point")
            if not point:
                point = path.stem
                row["point"] = point
            arch, arm, side, multiplier = _parse_point(point)
            if row.get("arm") and row["arm"] != directory_arm:
                raise ValueError(f"{path}:{line}: arm disagrees with result directory")
            row["arch"] = row.get("arch") or arch
            row["arm"] = row.get("arm") or directory_arm
            row["side"] = row.get("side") or side
            row["multiplier"] = row.get("multiplier") or str(multiplier)
            layer = row.get("layer")
            if not layer:
                raise ValueError(f"{path}:{line}: result row has no layer")
            if directory_arm == SPAD_ARM:
                for column in sorted(required):
                    try:
                        value = int(row[column])
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"{path}:{line}: invalid {column}") from exc
                    if value < 0:
                        raise ValueError(f"{path}:{line}: negative {column}")
                    row[column] = str(value)
            else:
                for column in sorted(required):
                    try:
                        value = int(float(row[column]))
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"{path}:{line}: invalid {column}") from exc
                    if value < 0:
                        raise ValueError(f"{path}:{line}: negative {column}")
                    row[column] = str(value)
            rows[(point, layer)].append(row)
    return rows


def expand_dedup_rows(
    rows_by_point: dict[tuple[str, str], list[dict[str, str]]],
    dedup_map: dict[str, Any],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Expand representative scratchpad rows, refusing cache re-expansion."""

    entries = dedup_map.get("entries", [])
    if not entries:
        return rows_by_point
    expanded: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for entry in entries:
        point = entry["point"]
        layer = entry["layer"]
        representative = entry.get("representative", point)
        arm = entry.get("arm", SPAD_ARM)
        if arm == CACHE_ARM and (
            representative != point or entry.get("deduped_from")
        ):
            raise ValueError(
                f"cache row {point}/{layer} is marked as deduped from {representative}"
            )
        source = point if arm == CACHE_ARM else representative
        source_rows = rows_by_point.get((source, layer))
        if source_rows is None:
            raise ValueError(
                f"missing result rows for representative {source}/{layer} "
                f"needed by {point}/{layer}"
            )
        for source_row in source_rows:
            row = dict(source_row)
            row.update({
                "point": point,
                "arch": entry["arch"],
                "arm": arm,
                "side": entry["side"],
                "multiplier": str(entry["multiplier"]),
                "layer": layer,
            })
            if arm != CACHE_ARM and point != source:
                row["deduped_from"] = source
            expanded[(point, layer)].append(row)
    # Preserve real result files that were produced outside the current map
    # (for example, a cache point added after S1b).  Map entries still control
    # every deduplicated scratchpad expansion; they must not make unrelated
    # real rows disappear silently.
    for key, source_rows in rows_by_point.items():
        if key not in expanded:
            expanded[key] = source_rows
    return expanded


def _schedule_paths(point: str) -> tuple[pathlib.Path, pathlib.Path]:
    arch, _, side, multiplier = _parse_point(point)
    schedule_token = f"{side}_x{multiplier}"
    new_base = OUT / "s1" / arch / schedule_token
    old_base = OUT / "s1" / schedule_token
    relative_schedule = pathlib.Path("schedules") / arch / CAPTURE
    relative_workload = pathlib.Path("workloads") / CAPTURE
    for base in (new_base, old_base):
        schedule_dir = base / relative_schedule
        workload_dir = base / relative_workload
        if schedule_dir.is_dir():
            return schedule_dir, workload_dir
    return new_base / relative_schedule, new_base / relative_workload


def _load_schedules(
    point: str,
    inputs: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    schedule_dir, workload_dir = _schedule_paths(point)
    schedules: dict[str, dict[str, Any]] = {}
    for path in sorted(schedule_dir.glob("*.json")):
        schedules[path.stem] = json.loads(read_input(path, inputs))
    for path in sorted(workload_dir.glob("*.yaml")):
        read_input(path, inputs)
    return schedules, nodes_per_layer(schedules) if schedules else {}


def _sample_value(row: dict[str, str]) -> str:
    return row.get("sample") or row.get("sample_idx") or ""


def _as_int(row: dict[str, str], key: str) -> int:
    try:
        return int(float(row[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"result row has no integer {key}") from exc


def _point_aggregate(
    point: str,
    rows: list[dict[str, str]],
    inputs: list[dict[str, Any]],
) -> dict[str, Any]:
    arch, arm, side, multiplier = _parse_point(point)
    schedules, nodes = _load_schedules(point, inputs)
    layers = {row["layer"] for row in rows}
    by_sample: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_sample[_sample_value(row)].append(row)
    cycle_samples: dict[str, int] = {}
    whole_cycle_samples: dict[str, int] = {}
    util_samples: list[float] = []
    traffic_samples: dict[str, float] = {}
    for sample, sample_rows in sorted(by_sample.items()):
        if not sample:
            raise ValueError(f"{point}: result row has no sample index")
        if {row["layer"] for row in sample_rows} != layers:
            raise ValueError(f"{point}: sample {sample} does not cover every layer")
        cycle_column = (
            CACHE_PERFORMANCE_COLUMN if arm == CACHE_ARM else PERFORMANCE_COLUMN
        )
        cycle_samples[sample] = sum(_as_int(row, cycle_column) for row in sample_rows)
        whole_cycle_samples[sample] = sum(
            _as_int(row, "total_cycles") for row in sample_rows
        )
        if arm == CACHE_ARM:
            traffic_samples[sample] = sum(_as_int(row, "dram_bytes") for row in sample_rows)
        else:
            traffic_samples[sample] = sum(
                _as_int(row, "dram_bytes_weight") for row in sample_rows
            )
        util_denominator = 0
        for row in sample_rows:
            layer_nodes = nodes.get(row["layer"])
            if layer_nodes is None:
                layer_nodes = _as_int(row, "nodes")
            util_denominator += layer_nodes * _as_int(row, "total_cycles")
        util_samples.append(
            sum(_as_int(row, "count_cycles") for row in sample_rows) / util_denominator
            if arm == SPAD_ARM
            else float("nan")
        )
    cycle_mean, cycle_ci = mean_ci([float(value) for value in cycle_samples.values()])
    whole_cycle_mean, whole_cycle_ci = mean_ci(
        [float(value) for value in whole_cycle_samples.values()]
    )
    traffic_mean, traffic_ci = mean_ci(list(traffic_samples.values()))
    util_values = [value for value in util_samples if not math.isnan(value)]
    util_mean, util_ci = mean_ci(util_values) if util_values else (float("nan"), float("nan"))
    return {
        "point": point,
        "arch": arch,
        "arm": arm,
        "side": side,
        "multiplier": multiplier,
        "nodes": max(nodes.values()) if nodes else max(_as_int(row, "nodes") for row in rows),
        "layers": len(layers),
        "samples": len(cycle_samples),
        "total_cycles_mean": whole_cycle_mean,
        "total_cycles_ci95": whole_cycle_ci,
        "performance_cycles_mean": cycle_mean,
        "performance_cycles_ci95": cycle_ci,
        "perf_mean": float("nan"),
        "perf_ci95": float("nan"),
        "perf_norm": float("nan"),
        "perf_ci": float("nan"),
        "util_mean": util_mean,
        "util_ci95": util_ci,
        "traffic_mean": traffic_mean,
        "traffic_ci95": traffic_ci,
        "counted_dram_bytes_mean": traffic_mean,
        "counted_dram_bytes_ci95": traffic_ci,
        "analytic_traffic_bytes": analytic_traffic(schedules) if schedules else 0.0,
        "_cycle_samples": cycle_samples,
        "_traffic_samples": traffic_samples,
    }


def _apply_normalization(rows: list[dict[str, Any]]) -> None:
    """Normalize each architecture to its single-node 1x total-cycle sample."""

    by_arch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_arch[row["arch"]].append(row)
    for arch, arch_rows in by_arch.items():
        baseline = next(
            (
                row
                for row in arch_rows
                if row["arm"] == SPAD_ARM
                and row["side"] == "single"
                and row["multiplier"] == 1
            ),
            None,
        )
        if baseline is None:
            raise ValueError(f"{arch}: no single-node x1 performance baseline")
        base_cycles = baseline["_cycle_samples"]
        base_traffic = baseline["_traffic_samples"]
        for row in arch_rows:
            samples = row["_cycle_samples"]
            common = sorted(set(base_cycles) & set(samples))
            if not common:
                raise ValueError(f"{row['point']}: no samples shared with its baseline")
            perf_samples = [base_cycles[sample] / samples[sample] for sample in common]
            traffic_samples = row["_traffic_samples"]
            traffic_common = sorted(set(base_traffic) & set(traffic_samples))
            if not traffic_common:
                raise ValueError(f"{row['point']}: no traffic samples shared with its baseline")
            traffic_ratios = [
                traffic_samples[sample] / base_traffic[sample]
                for sample in traffic_common
            ]
            row["perf_mean"], row["perf_ci95"] = mean_ci(perf_samples)
            row["perf_norm"] = row["perf_mean"]
            row["perf_ci"] = row["perf_ci95"]
            row["traffic_norm"], row["traffic_norm_ci95"] = mean_ci(traffic_ratios)
            row["counted_traffic_norm"] = row["traffic_norm"]
            row["counted_traffic_norm_ci95"] = row["traffic_norm_ci95"]
            row["traffic_ci"] = row["traffic_norm_ci95"]
            row["analytic_traffic_norm"] = (
                row["analytic_traffic_bytes"] / baseline["analytic_traffic_bytes"]
                if baseline["analytic_traffic_bytes"]
                else float("nan")
            )
            row.pop("_cycle_samples", None)
            row.pop("_traffic_samples", None)


def _write_provenance(inputs: list[dict[str, Any]], dedup_path: pathlib.Path | None) -> None:
    repo = HERE.parents[1]
    repo_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    dirty_paths = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo, text=True
    ).splitlines()
    if dirty_paths:
        repo_commit += "-dirty"
    provenance = {
        "campaign": "eval_scaling",
        "repo_commit": repo_commit,
        "dirty_paths": dirty_paths,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "dedup_map": str(dedup_path) if dedup_path else None,
        "performance_metric": (
            "1 / sum_l(weight_makespan_l) for spad; "
            "1 / sum_l(total_cycles_l) for cache; normalized to single_x1"
        ),
        "traffic_metric": (
            "Weight DRAM payload bytes (nocsim dram_bytes_weight; "
            "cache dram_bytes)"
        ),
        "floor": "Weights-only compulsory bytes, normalized by single_x1 weight DRAM bytes",
    }
    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def main() -> None:
    inputs: list[dict[str, Any]] = []
    rows_by_point = _read_result_rows(inputs)
    dedup_path = OUT / "dedup_map.json"
    dedup_map = None
    if dedup_path.is_file():
        dedup_map = json.loads(read_input(dedup_path, inputs))
        rows_by_point = expand_dedup_rows(rows_by_point, dedup_map)

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for (point, _), rows in rows_by_point.items():
        grouped[point].extend(rows)
    aggregates = [
        _point_aggregate(point, rows, inputs)
        for point, rows in sorted(grouped.items())
    ]
    if not aggregates:
        raise ValueError("no result rows found under outputs/s4 or outputs/s4c")
    _apply_normalization(aggregates)

    field_order = [
        "point", "arch", "arm", "side", "multiplier", "nodes", "layers", "samples",
        "perf_mean", "perf_ci95", "perf_norm", "perf_ci",
        "traffic_norm", "traffic_norm_ci95", "traffic_ci",
        "total_cycles_mean", "total_cycles_ci95", "util_mean", "util_ci95",
        "performance_cycles_mean", "performance_cycles_ci95",
        "counted_dram_bytes_mean", "counted_dram_bytes_ci95",
        "counted_traffic_norm", "counted_traffic_norm_ci95",
        "analytic_traffic_bytes", "analytic_traffic_norm",
    ]
    output = OUT / "aggregate.csv"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_order, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(aggregates)
    _write_provenance(inputs, dedup_path if dedup_map is not None else None)
    for row in aggregates:
        print(
            row["point"],
            f"P={row['perf_mean']:.3f}+/-{row['perf_ci95']:.3f}",
            f"traffic={row['traffic_norm']:.3f}+/-{row['traffic_norm_ci95']:.3f}",
        )
    print("->", output)


if __name__ == "__main__":
    main()
