#!/usr/bin/env python3
"""Price cache rows and aggregate RQ4 metrics before forming ratios."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
from pathlib import Path
import operator
import statistics
from typing import Any

try:
    from scipy.stats import t as student_t
except ImportError:  # pragma: no cover - exercised only in minimal Stokes envs
    student_t = None


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv}
FREQUENCY_MHZ = 500.0
REQUIRED_CACTI = {"l2_262144", "l2_1048576", "l1_8192", "l1_32768"}
EXPECTED_OPERATION_KEYS = frozenset({
    "cache.distance_logic.step", "cache.distance_metadata.read",
    "cache.distance_metadata.write", "cache.l1.read", "cache.l1.write",
    "cache.l1_tags.read", "cache.l2.read", "cache.l2.write",
    "cache.l2_tags.read", "cache.mshr_cam_l1.search",
    "cache.mshr_cam_l2.search", "cache.mshr_targets_l1.write",
    "cache.mshr_targets_l2.write", "cache.next_access_logic.step",
    "cache.next_access_state.rmw", "shared.ddr4.read", "shared.ddr4_io.byte",
    "shared.link.hop", "shared.router.hop",
})


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def eval_expr(expression: str, values: dict[str, str]) -> float:
    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values or values[node.id] in (None, ""):
                raise ValueError(f"raw row lacks {node.id} for {expression}")
            return float(values[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return float(OPS[type(node.op)](visit(node.left), visit(node.right)))
        raise ValueError(f"unsupported count expression: {expression}")
    result = visit(ast.parse(expression, mode="eval").body)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"invalid count {result} from {expression}")
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    partial = path.with_name(path.name + ".part")
    with partial.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(partial, path)


def cacti_prices(manifest: dict[str, Any]) -> dict[str, Any]:
    harvest_path = Path(manifest["output_root"]) / "cacti" / "harvest.json"
    if not harvest_path.is_file():
        raise SystemExit(f"full cacti_fn harvest is missing: {harvest_path}")
    value = load(harvest_path)
    if not REQUIRED_CACTI <= set(value.get("geometries", {})):
        raise SystemExit(f"cacti_fn harvest lacks all four changed geometries: {harvest_path}")
    return value["geometries"]


def read_row(path: Path) -> dict[str, str]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise SystemExit(f"expected one raw row in {path}, found {len(rows)}")
    row = rows[0]
    if row.get("max_wait_depth") != "0":
        raise SystemExit(f"max_wait_depth is not zero in {path}")
    return row


def table_for_variant(manifest: dict[str, Any], variant: dict[str, Any], table: dict[str, Any], harvest: dict[str, Any]) -> dict[str, Any]:
    table = {key: dict(value) for key, value in table.items()}
    if variant["l1_size_bytes"] != 16384:
        item = harvest[f"l1_{variant['l1_size_bytes']}"]
        for operation, metric in (("read", "dynamic_energy_read_nJ"), ("write", "dynamic_energy_write_nJ")):
            table[f"cache.l1.{operation}"]["dynamic_energy_nJ"] = item[metric]
        table["cache.l1.read"]["leakage_power_mW"] = item["leakage_power_mW"]
        table["cache.l1.write"]["leakage_power_mW"] = item["leakage_power_mW"]
        table["cache.l1.read"]["area_mm2"] = item["area_mm2"]
        table["cache.l1.write"]["area_mm2"] = item["area_mm2"]
    if variant["l2_size_bytes"] != 524288:
        item = harvest[f"l2_{variant['l2_size_bytes']}"]
        for operation, metric in (("read", "dynamic_energy_read_nJ"), ("write", "dynamic_energy_write_nJ")):
            table[f"cache.l2.{operation}"]["dynamic_energy_nJ"] = item[metric]
        table["cache.l2.read"]["leakage_power_mW"] = item["leakage_power_mW"]
        table["cache.l2.write"]["leakage_power_mW"] = item["leakage_power_mW"]
        table["cache.l2.read"]["area_mm2"] = item["area_mm2"]
        table["cache.l2.write"]["area_mm2"] = item["area_mm2"]
    return table


def energy_for_row(row: dict[str, str], table: dict[str, Any], hardware: dict[str, Any]) -> tuple[float, float, float, list[str]]:
    dynamic = 0.0
    area = 0.0
    used = []
    # Leakage and area are properties of the physical module, not of each
    # operation on it, so they are charged once per unique physical module
    # (pricing.py:57-58 convention: cache.l1.read and cache.l1.write share
    # the l1 array). Inconsistent per-module metrics are an error.
    modules: dict[str, dict[str, float]] = {}
    for key, spec in hardware.items():
        if not (key.startswith("cache.") or key in {"shared.ddr4.read", "shared.ddr4_io.byte", "shared.router.hop", "shared.link.hop"}):
            continue
        applies = spec.get("applies_to")
        if applies and "cacheA" not in applies:
            continue
        price = table.get(key)
        if price is None:
            raise ValueError(f"energy table lacks expected operation {key}")
        instances = int(price.get("physical_instances", spec.get("physical_instances", 1)) or 0)
        value = price.get("dynamic_energy_nJ")
        expression = spec.get("count_expression")
        if value is not None and expression:
            try:
                dynamic += eval_expr(expression, row) * float(value)
            except ValueError:
                # Cache-only rows do not carry the NOC packet-hop counters;
                # their shared link/router dynamic terms are zero in the
                # production cacheA breakdown and are omitted here.
                if key not in {"shared.router.hop", "shared.link.hop"}:
                    raise
        namespace, module = key.split(".")[:2]
        physical = f"{namespace}.{spec.get('physical_module', module)}"
        entry = {
            "leakage_power_mW": price.get("leakage_power_mW"),
            "area_mm2": price.get("area_mm2"),
            "instances": instances,
        }
        known = modules.setdefault(physical, entry)
        if known != entry:
            raise ValueError(f"inconsistent per-module metrics for {physical}: {known} vs {entry} ({key})")
        used.append(key)
    power = sum(float(m["leakage_power_mW"]) * m["instances"]
                for m in modules.values() if m["leakage_power_mW"] is not None)
    area = sum(float(m["area_mm2"]) * m["instances"]
               for m in modules.values() if m["area_mm2"] is not None)
    return dynamic, power, area, used


def incomplete_reasons(table: dict[str, Any], used: list[str]) -> tuple[str, list[str]]:
    statuses = {str(table[key].get("pricing_status")) for key in used
                if table[key].get("pricing_status")}
    reasons: set[str] = set()
    for key in used:
        price = table[key]
        if price.get("pricing_status") == "NG45_INTERIM":
            reasons.add("NG45_INTERIM: interim until ASAP7 synthesis")
        if price.get("placeholder"):
            reasons.add(f"{key}:incomplete/placeholder")
        for field in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"):
            if price.get(field) is None:
                reasons.add(f"{key}:{field}=null")
    status = ";".join(sorted(statuses)) if statuses else ""
    return status, sorted(reasons)


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    critical = (float(student_t.ppf(0.975, len(values) - 1))
                if student_t is not None else 1.96)
    return critical * statistics.stdev(values) / math.sqrt(len(values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    manifest = load(Path(args.manifest).expanduser().resolve())
    if manifest.get("schema") != "stokes_cache_dse_manifest/v1":
        raise SystemExit(f"unsupported manifest schema: {manifest.get('schema')!r}")
    table = load(Path(manifest["energy_table"]))
    hardware = load(Path(manifest["repo"]) / "zoo/archx/zoo/snn_edp/hardware.json")
    hardware_operations = frozenset(
        key for key, spec in hardware.items()
        if (key.startswith("cache.") or key in {"shared.ddr4.read", "shared.ddr4_io.byte",
                                                   "shared.router.hop", "shared.link.hop"})
        and not (spec.get("applies_to") and "cacheA" not in spec["applies_to"])
    )
    if hardware_operations != EXPECTED_OPERATION_KEYS:
        missing = sorted(EXPECTED_OPERATION_KEYS - hardware_operations)
        extra = sorted(hardware_operations - EXPECTED_OPERATION_KEYS)
        raise SystemExit(f"cache energy operation set changed: missing={missing}, extra={extra}")
    missing_table = sorted(EXPECTED_OPERATION_KEYS - set(table))
    if missing_table:
        raise SystemExit(f"energy table lacks expected operations: {missing_table}")
    harvest = cacti_prices(manifest)
    variants = {item["id"]: item for item in manifest["configs"]}
    layer_rows: list[dict[str, Any]] = []
    by_variant_sample: dict[tuple[str, int], list[dict[str, Any]]] = {}
    expected = 0
    for case in manifest["cases"]:
        expected += 1
        variant = variants[case["variant"]]
        raw_path = Path(manifest["raw_root"]) / case["variant"] / case["sample_name"] / f"{case['layer']}.csv"
        receipt_path = raw_path.with_suffix(".json")
        if not raw_path.is_file() or not receipt_path.is_file():
            raise SystemExit(f"missing raw result for case {case['case_index']}: {raw_path}")
        receipt = load(receipt_path)
        if receipt.get("status") != "complete" or receipt.get("csv_sha256") != __import__("hashlib").sha256(raw_path.read_bytes()).hexdigest():
            raise SystemExit(f"raw receipt mismatch: {raw_path}")
        raw = read_row(raw_path)
        row_table = table_for_variant(manifest, variant, table, harvest)
        dynamic, power, area, used = energy_for_row(raw, row_table, hardware)
        energy_status, reasons = incomplete_reasons(row_table, used)
        cycles = float(raw["total_cycles"])
        t_s = cycles / (FREQUENCY_MHZ * 1e6)
        leakage = power * t_s * 1e6
        total_energy = dynamic + leakage
        layer = {
            "row_type": "layer", "variant": case["variant"], "label": variant["label"],
            "group": variant["group"], "sample": case["sample"], "sample_name": case["sample_name"],
            "layer": case["layer"], "layer_index": case["layer_index"],
            "total_cycles": cycles, "T_s": t_s, "E_dyn_nJ": dynamic,
            "E_leak_nJ": leakage, "E_total_nJ": total_energy,
            "EDP_nJ_s": total_energy * t_s, "area_mm2": area,
            "l1_hit_rate": raw.get("l1_hit_rate"), "l2_hit_rate": raw.get("l2_hit_rate"),
            "dram_accesses": raw.get("dram_accesses"), "dram_bytes": raw.get("dram_bytes"),
            "max_wait_depth": raw.get("max_wait_depth"), "raw_csv": str(raw_path),
            "energy_status": energy_status,
            "incomplete": bool(reasons),
            "incomplete_reasons": json.dumps(reasons),
            "energy_operations": ";".join(used),
        }
        layer_rows.append(layer)
        by_variant_sample.setdefault((case["variant"], case["sample"]), []).append(layer)
    if expected != manifest["expected_rows"]:
        raise SystemExit(f"expected {manifest['expected_rows']} rows, aggregated {expected}")
    if len(layer_rows) != 1200:
        raise SystemExit(f"expected 1200 layer rows, found {len(layer_rows)}")

    sample_models: dict[tuple[str, int], dict[str, float]] = {}
    for key, rows in by_variant_sample.items():
        sample_models[key] = {
            "sum_cycles": sum(float(row["total_cycles"]) for row in rows),
            "sum_T_s": sum(float(row["T_s"]) for row in rows),
            "sum_E_dyn_nJ": sum(float(row["E_dyn_nJ"]) for row in rows),
            "sum_E_leak_nJ": sum(float(row["E_leak_nJ"]) for row in rows),
            "sum_E_total_nJ": sum(float(row["E_total_nJ"]) for row in rows),
        }
        sample_models[key]["model_EDP_nJ_s"] = sample_models[key]["sum_E_total_nJ"] * sample_models[key]["sum_T_s"]
    summaries = []
    for variant_id, variant in variants.items():
        ratios_p, ratios_e = [], []
        for sample in range(manifest["benchmark"]["sample_count"]):
            base = sample_models[("V0", sample)]
            current = sample_models[(variant_id, sample)]
            ratios_p.append(base["sum_cycles"] / current["sum_cycles"])
            ratios_e.append(current["model_EDP_nJ_s"] / base["model_EDP_nJ_s"])
        own = [sample_models[(variant_id, sample)] for sample in range(manifest["benchmark"]["sample_count"])]
        own_rows = [row for row in layer_rows if row["variant"] == variant_id]
        reasons = sorted({reason for row in own_rows
                          for reason in json.loads(row["incomplete_reasons"])})
        statuses = sorted({row["energy_status"] for row in own_rows if row["energy_status"]})
        summaries.append({
            "row_type": "summary", "variant": variant_id, "label": variant["label"],
            "short_label": variant["short_label"], "group": variant["group"],
            "n_samples": len(ratios_p), "performance_norm": statistics.mean(ratios_p),
            "performance_ci95": ci95(ratios_p), "edp_norm": statistics.mean(ratios_e),
            "edp_ci95": ci95(ratios_e), "sum_cycles_mean": statistics.mean(x["sum_cycles"] for x in own),
            "sum_T_s_mean": statistics.mean(x["sum_T_s"] for x in own),
            "sum_E_total_nJ_mean": statistics.mean(x["sum_E_total_nJ"] for x in own),
            "model_EDP_nJ_s_mean": statistics.mean(x["model_EDP_nJ_s"] for x in own),
            "sample_performance_norm": json.dumps(ratios_p), "sample_edp_norm": json.dumps(ratios_e),
            "energy_status": ";".join(statuses), "incomplete": bool(reasons),
            "incomplete_reasons": json.dumps(reasons),
            "aggregate_rule": "sum(E_total_nJ) * sum(T_s) per sample, then mean ratio over samples",
        })
    all_rows = layer_rows + summaries
    write_csv(Path(manifest["aggregate_csv"]), all_rows)
    write_csv(Path(manifest["summary_csv"]), summaries)
    print(json.dumps({"layer_rows": len(layer_rows), "summary_rows": len(summaries),
                      "aggregate": manifest["aggregate_csv"], "summary": manifest["summary_csv"]}, sort_keys=True))


if __name__ == "__main__":
    main()
