#!/usr/bin/env python3
"""Validate the Milestone 4 CSV and build the Milestone 5 data payload."""

from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "hierarchical_cache_results.csv"
OUT = ROOT / "artifact"
REPO_ROOT = ROOT.parents[1]
SCHEDULE_SOURCE = REPO_ROOT / "outputs" / "schedules" / "multinode_sweep" / "classification.csv"
TRACE_ROOT = Path("/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/loas")
COUNT_FIELDS = ("l1_hits", "l1_accesses", "l2_hits", "l2_accesses")
EXPECTED_ARCHS = {
    "inst16_node32kb_noc512kb", "inst16_node32kb_noc4096kb",
    "inst1024_node32kb_noc512kb", "inst1024_node32kb_noc4096kb",
}


def read_rows() -> list[dict]:
    with SOURCE.open(newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 14_880:
        raise ValueError(f"expected 14,880 source rows, found {len(rows)}")

    parsed = []
    keys = set()
    for row in rows:
        item = {
            "arch": row["arch_config"],
            "workload": row["workload"],
            "layer": row["layer"],
            "sample": int(row["sample_idx"]),
            "structure": row["cache_type"],
            "assoc": int(row["associativity"]),
            "l1_kb": int(row["l1_size_bytes"]) // 1024,
            "l2_kb": int(row["l2_size_bytes"]) // 1024,
            **{field: int(row[field]) for field in COUNT_FIELDS},
        }
        key = tuple(item[field] for field in (
            "arch", "workload", "layer", "sample", "structure", "assoc", "l1_kb", "l2_kb"
        ))
        if key in keys:
            raise ValueError(f"duplicate source row: {key}")
        keys.add(key)
        if item["l2_accesses"] != item["l1_accesses"] - item["l1_hits"]:
            raise ValueError(f"L2 access invariant failed: {key}")
        parsed.append(item)

    if {row["arch"] for row in parsed} != EXPECTED_ARCHS:
        raise ValueError("unexpected arch-config coverage")
    if {row["workload"] for row in parsed} != {"resnet19_T4_all", "vgg16_T4_all"}:
        raise ValueError("unexpected workload coverage")
    if {row["sample"] for row in parsed} != set(range(5)):
        raise ValueError("artifact requires samples 0-4")

    # L1 does not depend on L2 capacity. Catch a sweep/orchestration bug
    # before the artifact silently displays one of four disagreeing rows.
    l1_by_key = defaultdict(set)
    for row in parsed:
        key = tuple(row[field] for field in (
            "arch", "workload", "layer", "sample", "structure", "assoc", "l1_kb"
        ))
        l1_by_key[key].add((row["l1_hits"], row["l1_accesses"]))
    if any(len(values) != 1 for values in l1_by_key.values()):
        raise ValueError("L1 counts changed across L2 sizes")
    return parsed


def read_schedule_rows() -> list[dict]:
    with SCHEDULE_SOURCE.open(newline="") as source:
        source_rows = list(csv.DictReader(source))

    rows = []
    for row in source_rows:
        if row["arch"] != "loas" or int(row["node_size"]) != 32 * 1024:
            continue
        arch = f"inst{row['instances']}_node32kb_noc{int(row['noc_size']) // 1024}kb"
        if arch not in EXPECTED_ARCHS:
            continue
        if row["trace_dir"] not in {"resnet19_T4_all", "vgg16_T4_all"}:
            continue
        rows.append({
            "arch": arch,
            "workload": row["trace_dir"],
            "layer": row["layer"],
            "noc_s": row["noc_spatial_class"],
            "noc_t": row["noc_temporal_order"],
            "dram_t": row["dram_order_class"],
        })

    keys = {(row["arch"], row["workload"], row["layer"]) for row in rows}
    if len(rows) != 124 or len(keys) != 124:
        raise ValueError(f"expected 124 unique schedule-class rows, found {len(rows)}")
    if {row["arch"] for row in rows} != EXPECTED_ARCHS:
        raise ValueError("schedule classes do not cover the artifact architecture grid")
    return sorted(rows, key=lambda row: (row["arch"], row["workload"], row["layer"]))


def read_trace_example() -> dict:
    relative_path = Path(
        "inst16_node32kb_noc512kb/resnet19_T4_all/"
        "layer_01_layer1_0_conv1/sample_00000.json.gz"
    )
    with gzip.open(TRACE_ROOT / relative_path, "rt") as source:
        trace = json.load(source)
    tile = trace["tiles"][0]
    tick = tile["ticks"][0]
    return {
        "path": str(relative_path),
        "arch": trace["arch"],
        "workload": trace["trace_dir"],
        "layer": trace["layer_name"],
        "sample": trace["sample_idx"],
        "workload_dims": trace["workload_dims"],
        "dram_num_steps": trace["dram_num_steps"],
        "noc_num_steps": trace["noc_num_steps"],
        "tile_count": len(trace["tiles"]),
        "tile": {
            "dram_i": tile["dram_i"],
            "noc_i": tile["noc_i"],
            "mac_cycles": tile["mac_cycles"],
            "lif_cycles": tile["lif_cycles"],
        },
        "tick": tick["tick"],
        "core_count": len(tick["cores"]),
        "cores": tick["cores"][:4],
    }


def aggregate(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    groups = defaultdict(lambda: {field: 0 for field in COUNT_FIELDS})
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        for field in COUNT_FIELDS:
            groups[key][field] += row[field]

    output = []
    for key, counts in sorted(groups.items()):
        item = dict(zip(key_fields, key))
        item.update(counts)
        item.update({
            "l1_rate": counts["l1_hits"] / counts["l1_accesses"] if counts["l1_accesses"] else 0.0,
            "l2_rate": counts["l2_hits"] / counts["l2_accesses"] if counts["l2_accesses"] else 0.0,
            "effective_rate": (
                (counts["l1_hits"] + counts["l2_hits"]) / counts["l1_accesses"]
                if counts["l1_accesses"] else 0.0
            ),
        })
        output.append(item)
    return output


def main() -> None:
    rows = read_rows()
    schedules = read_schedule_rows()
    trace_example = read_trace_example()
    config_fields = ("arch", "workload", "structure", "assoc", "l1_kb", "l2_kb")
    overall = aggregate(rows, config_fields)
    layers = aggregate(rows, config_fields + ("layer",))
    if len(overall) != 4 * 2 * 24:
        raise ValueError(f"expected 192 overall rows, found {len(overall)}")
    if len(layers) != 4 * 24 * 31:
        raise ValueError(f"expected 2,976 layer rows, found {len(layers)}")

    payload = {
        "generated": "2026-08-03",
        "aggregation": "pooled hit and access counts",
        "archs": sorted({row["arch"] for row in rows}),
        "workloads": sorted({row["workload"] for row in rows}),
        "samples": sorted({row["sample"] for row in rows}),
        "sweep": {
            "structures": sorted({(row["structure"], row["assoc"]) for row in rows}),
            "l1_kb": sorted({row["l1_kb"] for row in rows}),
            "l2_kb": sorted({row["l2_kb"] for row in rows}),
            "line_size_bytes": 16,
        },
        "trace_example": trace_example,
        "schedules": schedules,
        "overall": overall,
        "layers": layers,
    }
    OUT.mkdir(exist_ok=True)
    destination = OUT / "data.js"
    destination.write_text("window.HIERARCHY_DATA=" + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(
        f"wrote {destination} ({len(overall)} overall rows, {len(layers)} layer rows, "
        f"{len(schedules)} schedule rows)"
    )


if __name__ == "__main__":
    main()
