#!/usr/bin/env python3
"""Build the RQ4 cache-DSE configs and the 120-trace/1200-case manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import struct
from typing import Any


KIT = Path(__file__).resolve().parent
REPO_DEFAULT = KIT.parents[2]
TRACE_ROOT_DEFAULT = Path.home() / "loas10_20261116"
ARCH = "loas"
WORKLOAD = "loas_vgg16_T4_n500"
SAMPLE_COUNT = 10
LAYER_NAMES = [
    "layer_01_core_features_3",
    "layer_02_core_features_7",
    "layer_03_core_features_10",
    "layer_04_core_features_14",
    "layer_05_core_features_17",
    "layer_06_core_features_20",
    "layer_07_core_features_24",
    "layer_08_core_features_27",
    "layer_09_core_features_30",
    "layer_10_core_features_34",
    "layer_11_core_features_37",
    "layer_12_core_features_40",
]


BASE_CONFIG: dict[str, Any] = {
    "cin_block": 16,
    "cout_block": 4,
    "weight_bytes": 1,
    "layout": "khkw_split",
    "l1_size_bytes": 16384,
    "l1_assoc": 8,
    "l2_size_bytes": 524288,
    "l2_assoc": 16,
    "l1_mshrs": 16,
    "l1_tgts_per_mshr": 20,
    "l2_mshrs": 32,
    "l2_tgts_per_mshr": 12,
    "l1_demand_reserve": 1,
    "l2_demand_reserve": 1,
    "prefetch_policy": "next_access",
    "prefetch_distance": 4,
    "l1_latency": 0,
    "l1_ii": 1,
    "l2_latency": 2,
    "l2_to_l1_latency": 0,
    "l2_miss_latency": 24,
    "l2_banks": 1,
    "l2_ii": 1,
    "dram_ii": 1,
    "core_accept_ii": 1,
    "inclusion": "non_inclusive",
    "policy": "lru",
    "rrip_bits": 2,
    "l2_policy": "pf_lru",
    "l2_prefetch_policy": "distance_aware",
    "l2_prefetch_axis": "cin",
    "l2_prefetch_distance": 1,
    "l2_prefetch_up": 1,
    "l2_prefetch_down": 1,
    "l2_prefetch_min_touches": 9,
    "l2_prefetch_trigger": "touch",
}


VARIANTS = [
    {"id": "V0", "label": "cacheA", "short_label": "cacheA\n(V0)", "group": "base", "changes": {}},
    {"id": "V1a", "label": "L2 256 KiB", "short_label": "L2 256K\n(V1a)", "group": "capacity", "changes": {"l2_size_bytes": 262144}},
    {"id": "V1b", "label": "L2 1 MiB", "short_label": "L2 1M\n(V1b)", "group": "capacity", "changes": {"l2_size_bytes": 1048576}},
    {"id": "V2a", "label": "L1 8 KiB", "short_label": "L1 8K\n(V2a)", "group": "capacity", "changes": {"l1_size_bytes": 8192}},
    {"id": "V2b", "label": "L1 32 KiB", "short_label": "L1 32K\n(V2b)", "group": "capacity", "changes": {"l1_size_bytes": 32768}},
    {"id": "V3a", "label": "pure LRU", "short_label": "pure LRU\n(V3a)", "group": "replacement", "changes": {"policy": "lru", "l2_policy": "lru"}},
    {"id": "V3b", "label": "pure LFU", "short_label": "pure LFU\n(V3b)", "group": "replacement", "changes": {"policy": "lfu", "l2_policy": "lfu"}},
    {"id": "V4", "label": "Belady L2", "short_label": "Belady (demand-only)\n(V4)", "group": "bound", "changes": {"l2_policy": "belady"}, "belady": True},
    {"id": "V5", "label": "L1 next-line", "short_label": "L1 next-line\n(V5)", "group": "prefetch", "changes": {"prefetch_policy": "next_line", "prefetch_distance": 1}},
    {"id": "V6", "label": "L1+L2 next-line", "short_label": "L1+L2 n-l\n(V6)", "group": "prefetch", "changes": {"prefetch_policy": "next_line", "prefetch_distance": 1, "l2_prefetch_policy": "next_line", "l2_prefetch_distance": 1}, "remove": ["l2_prefetch_trigger"]},
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(partial, path)


def trailer(path: Path) -> tuple[int, int]:
    if path.stat().st_size < 12:
        raise SystemExit(f"WCTS is shorter than its trailer: {path}")
    with path.open("rb") as stream:
        stream.seek(-12, os.SEEK_END)
        marker, records = struct.unpack("<iQ", stream.read(12))
    if marker != -1:
        raise SystemExit(f"WCTS trailer marker is {marker}, expected -1: {path}")
    return marker, records


def trace_artifact(trace_root: Path, sample: int, layer: str) -> tuple[Path, Path]:
    sample_name = f"sample_{sample:03d}"
    return (trace_root / "wcts" / sample_name / f"{layer}.wcts",
            trace_root / "receipts" / sample_name / f"{layer}.json")


def validate_traces(trace_root: Path) -> list[dict[str, Any]]:
    traces = []
    for sample in range(SAMPLE_COUNT):
        for layer_index, layer in enumerate(LAYER_NAMES):
            wcts, receipt_path = trace_artifact(trace_root, sample, layer)
            if not wcts.is_file() or not receipt_path.is_file():
                raise SystemExit(f"missing retained trace or receipt: {wcts}")
            _, records = trailer(wcts)
            receipt = load_json(receipt_path)
            wcts_sha = digest(wcts)
            if receipt.get("status") != "complete":
                raise SystemExit(f"trace receipt is not complete: {receipt_path}")
            if receipt.get("wcts_sha256") != wcts_sha:
                raise SystemExit(f"trace digest differs from receipt: {wcts}")
            if receipt.get("sample") != sample or receipt.get("layer") != layer:
                raise SystemExit(f"trace identity differs from receipt: {receipt_path}")
            if receipt.get("wcts_bytes") != wcts.stat().st_size or receipt.get("records") != records:
                raise SystemExit(f"trace size/trailer differs from receipt: {wcts}")
            traces.append({
                "trace_index": len(traces), "sample": sample,
                "sample_name": f"sample_{sample:03d}", "layer_index": layer_index,
                "layer": layer, "path": str(wcts.resolve()), "sha256": wcts_sha,
                "records": records, "schedule_sha256": receipt.get("schedule_sha256"),
            })
    return traces


def baseline_row(path: Path) -> dict[str, str]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise SystemExit(f"baseline cacheA reference must contain one row: {path}")
    row = rows[0]
    required = {
        "arch": ARCH, "arm": "cache", "workload": WORKLOAD,
        "layer": "layer_08_core_features_27", "sample_idx": "0",
        "l1_size_bytes": "16384", "l2_size_bytes": "524288",
        "line_size_bytes": "64", "layout": "khkw_split",
    }
    for key, expected in required.items():
        if row.get(key) != expected:
            raise SystemExit(f"baseline reference {key}={row.get(key)!r}, expected {expected!r}")
    if row.get("max_wait_depth") != "0":
        raise SystemExit("baseline reference has nonzero max_wait_depth")
    return row


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).expanduser().resolve()
    trace_root = Path(args.trace_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    binary = Path(args.binary).expanduser().resolve()
    baseline = Path(args.baseline_csv).expanduser().resolve()
    energy_table = Path(args.energy_table).expanduser().resolve()
    for path, label in ((binary, "cachesim binary"), (baseline, "baseline CSV"), (energy_table, "energy table")):
        if not path.is_file():
            raise SystemExit(f"{label} is missing: {path}")
    traces = validate_traces(trace_root)
    reference = baseline_row(baseline)
    configs_dir = KIT / "configs"
    configs = []
    for spec in VARIANTS:
        config = dict(BASE_CONFIG)
        config.update(spec.get("changes", {}))
        for key in spec.get("remove", []):
            config.pop(key, None)
        line_bytes = config["cin_block"] * config["cout_block"] * config["weight_bytes"]
        for level in ("l1", "l2"):
            size = config[f"{level}_size_bytes"]
            assoc = config[f"{level}_assoc"]
            if size % (line_bytes * assoc):
                raise SystemExit(f"{spec['id']} {level} geometry is not an integral set")
        config_path = configs_dir / f"{spec['id']}.json"
        atomic_json(config_path, config)
        configs.append({
            "id": spec["id"], "label": spec["label"], "short_label": spec["short_label"],
            "group": spec["group"], "belady": bool(spec.get("belady", False)),
            "changes": spec.get("changes", {}), "removed": spec.get("remove", []),
            "config_path": str(config_path.resolve()), "config_sha256": digest(config_path),
            "l1_size_bytes": config["l1_size_bytes"], "l2_size_bytes": config["l2_size_bytes"],
        })
    cases = []
    for config in configs:
        for trace in traces:
            cases.append({
                "case_index": len(cases), "variant": config["id"],
                "sample": trace["sample"], "sample_name": trace["sample_name"],
                "layer_index": trace["layer_index"], "layer": trace["layer"],
                "trace_index": trace["trace_index"], "trace_path": trace["path"],
                "trace_sha256": trace["sha256"], "schedule_sha256": trace["schedule_sha256"],
            })
    source_hashes = {
        "baseline_csv_sha256": digest(baseline), "energy_table_sha256": digest(energy_table),
        "make_sweep_manifest_sha256": digest(Path(__file__).resolve()),
    }
    return {
        "schema": "stokes_cache_dse_manifest/v1",
        "repo": str(repo),
        "benchmark": {"arch": ARCH, "workload": WORKLOAD, "layers": LAYER_NAMES,
                      "sample_count": SAMPLE_COUNT, "layer_count": len(LAYER_NAMES)},
        "trace_root": str(trace_root), "output_root": str(output_root),
        "binary": str(binary), "binary_sha256": digest(binary),
        "baseline_csv": str(baseline), "energy_table": str(energy_table),
        "source_hashes": source_hashes,
        "config_count": len(configs), "trace_count": len(traces), "case_count": len(cases),
        "expected_rows": len(cases), "expected_variants": [c["id"] for c in configs],
        "configs": configs, "traces": traces, "cases": cases,
        "gates_path": str(output_root / "gates" / "gates.json"),
        "raw_root": str(output_root / "raw"), "oracle_root": str(output_root / "oracles"),
        "prepass_root": str(output_root / "prepass"),
        "aggregate_csv": str(output_root / "cache_dse.csv"),
        "summary_csv": str(output_root / "summary.csv"),
        "plot_png": str(output_root / "cache_dse.png"), "plot_pdf": str(output_root / "cache_dse.pdf"),
        "reference_identity": {"layer": reference["layer"], "sample_idx": reference["sample_idx"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO_DEFAULT))
    parser.add_argument("--trace-root", default=str(TRACE_ROOT_DEFAULT))
    parser.add_argument("--output-root")
    parser.add_argument("--binary")
    parser.add_argument("--baseline-csv", default=str(KIT / "configs/reference_cache_a.csv"))
    parser.add_argument("--energy-table")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    trace_root = Path(args.trace_root).expanduser().resolve()
    args.output_root = args.output_root or str(trace_root / "cache_dse")
    args.binary = args.binary or str(repo / "zoo/fig12_edp/demo/native_build/cachesim_run")
    args.energy_table = args.energy_table or str(repo / "zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json")
    args.manifest = args.manifest or str(Path(args.output_root) / "manifest.json")
    manifest = build(args)
    atomic_json(Path(args.manifest).expanduser().resolve(), manifest)
    print(json.dumps({"manifest": args.manifest, "configs": manifest["config_count"],
                      "traces": manifest["trace_count"], "cases": manifest["case_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
