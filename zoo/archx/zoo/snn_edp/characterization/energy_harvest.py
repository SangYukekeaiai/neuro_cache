#!/usr/bin/env python3
"""Query one architecture's archx graph and replace only its table rows."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


THREAD_ENV_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS",
    "RAYON_NUM_THREADS", "CARGO_BUILD_JOBS",
)
OPERATIONS = {"adder32": "add", "cmp32": "compare", "reg32": "rmw",
              "min_tree4": "compare"}
PENDING = "pending-ASAP7-synthesis"
SPINE_COUNTS = {"input_spike_buffer": {"read": "R", "write": "R"},
                "output_spike_queue": {"read": "0", "write": "O"}}


def cap_threads():
    for name in THREAD_ENV_VARS:
        os.environ[name] = "1"


def csv_provenance(archx_root, query):
    path = archx_root / "src/archx/interface/csv_cmos/include/csv" / (query["class"] + ".csv")
    with path.open(newline="") as stream:
        rows = [row for row in csv.DictReader(stream)
                if float(row["technology"]) == query["technology"]]
    if len(rows) != 1 or rows[0]["interpolation"] != "linear":
        raise ValueError(f"expected one linearly interpolatable row for {query}: {path}")
    row = rows[0]
    return {
        "source_csv": str(path),
        "reference_width_bits": float(row["width"]),
        "target_width_bits": query["width"],
        "width_scale": query["width"] / float(row["width"]),
        "num_units": query.get("num_instances", 1),
        "reference_technology_nm": query["technology"],
        "reference_frequency_MHz": float(row["frequency"]),
        "interpolation": "linear_from_zero (archx csv_cmos)",
    }


def harvest(energy_root, archx_root, run_dir, design="spinalflow"):
    sys.path.insert(0, str(archx_root / "src"))
    if design == "shared":
        from shared_harvest import harvest as harvest_shared
        return harvest_shared(energy_root, archx_root, run_dir)
    from archx.architecture import create_architecture_dict
    from archx.event import create_event_graph, save_event_graph
    from archx.metric import create_metric_dict, create_event_metrics, query_module_metric
    from archx.performance import simulate_performance_all_events
    from archx.workload import create_workload_dict

    os.environ["ARCHX_INTERFACE_CACHE_DIR"] = str(run_dir / "interface_cache")
    os.environ["ARCHX_DISABLE_PERFORMANCE_CACHE"] = "1"
    cacti_dir = archx_root / "src/archx/interface/cacti_fn/include/cacti_fn"
    binary = cacti_dir / f"cacti-{platform.system()}-{platform.machine()}"
    if not binary.exists():
        subprocess.run(["make", "-j1", "all"], cwd=cacti_dir, check=True)
        (cacti_dir / "cacti").rename(binary)

    architecture = create_architecture_dict(str(energy_root / f"{design}.architecture.yaml"))
    policy = json.loads(Path(__file__).with_name("pricing_policy.json").read_text())
    excluded = {name for name, spec in architecture.items()
                if set(f"{design}.{name}.{op}" for op in spec.get("operations", {}))
                and set(f"{design}.{name}.{op}" for op in spec["operations"]) <= set(policy["excluded_operations"])}
    pending = {name: spec for name, spec in architecture.items()
               if spec.get("placeholder") == PENDING and name not in excluded}
    for name, spec in architecture.items():
        query = spec["query"]
        if query.get("class", "").startswith("tnn_"):
            raise ValueError("retired logic class; use own-RTL pending characterization")
        if query["technology"] != 7 or query["interface"] not in ("cacti_fn", "csv_cmos"):
            raise ValueError(f"module violates the 7 nm tech-mapping rule: {query}")
        if query["interface"] == "csv_cmos" and spec.get("placeholder") != PENDING and name not in excluded:
            raise ValueError("logic prices require own500MHz ASAP7 reports; stage the measured table explicitly")
        if query["interface"] == "cacti_fn" and query["class"] not in ("sram", "cache"):
            raise ValueError(f"on-chip memory must use cacti_fn sram/cache: {query}")
    priced = {name: spec for name, spec in architecture.items() if name not in pending and name not in excluded}
    metrics = create_metric_dict(str(energy_root / "spinalflow.metric.yaml"))
    workload = create_workload_dict(str(energy_root / "spinalflow.workload.yaml"))
    # archx resolves performance paths relative to cwd; resolve the run copy.
    import yaml
    event = yaml.safe_load((energy_root / "spinalflow.event.yaml").read_text())
    event["event"]["spinalflow_stub"]["performance"] = str(energy_root / "spinalflow_performance.py")
    event["event"]["spinalflow_stub"]["subevent"] = list(priced)
    run_dir.mkdir(parents=True, exist_ok=True)
    event_path = run_dir / "event.yaml"
    event_path.write_text(yaml.safe_dump(event))
    graph = create_event_graph(str(event_path))
    graph = create_event_metrics(graph, priced, metrics, str(run_dir))
    graph = simulate_performance_all_events(graph, priced, workload)
    save_event_graph(graph, str(run_dir / "graph.json"))

    rows = {}
    for module, spec in architecture.items():
        query = spec["query"]
        memory = query["interface"] == "cacti_fn"
        operations = spec.get("operations") or ({"read": None, "write": None} if memory
                                               else {OPERATIONS[module]: None})
        metadata = {"physical_instances": spec.get("physical_instances", 1)}
        for key in ("scope", "applies_to"):
            if key in spec:
                metadata[key] = spec[key]
        if "assumption" in spec:
            metadata["assumption"] = spec["assumption"]
        if module in excluded:
            if "assumption" in spec:
                metadata["geometry_assumption"] = spec["assumption"]
            for operation, count in operations.items():
                rows[f"{design}.{module}.{operation}"] = {
                    **metadata, "module": module, "operation": operation,
                    "dynamic_energy_nJ": 0.0, "leakage_power_mW": 0.0, "area_mm2": 0.0,
                    "technology_nm": 7, "frequency_MHz": query["frequency"],
                    "placeholder": False, "source": "excluded_by_decision", "query": dict(query),
                    "assumption": policy["marker"], "pricing_status": policy["marker"],
                    "count_expression": count,
                }
            continue
        if module in pending:
            for operation, count in operations.items():
                rows[f"{design}.{module}.{operation}"] = {
                **metadata, "module": module, "operation": operation,
                "dynamic_energy_nJ": None, "leakage_power_mW": None, "area_mm2": None,
                "technology_nm": 7, "process": "ASAP7", "frequency_MHz": query["frequency"],
                "placeholder": PENDING, "source": PENDING, "query": dict(query),
                "target_width_bits": query["width"], "num_units": query.get("num_instances", 1),
                "synthesis": "auto_syn_pnr", "rtl_source": "characterization/rtl/ (see auto_syn_pnr_worklist.json)",
                "count_expression": count,
                }
            continue
        leakage = query_module_metric(graph, metrics, "leakage_power", module=module)["value"]
        area = query_module_metric(graph, metrics, "area", module=module)["value"]
        for operation in operations:
            dynamic = query_module_metric(graph, metrics, "dynamic_energy", module=module,
                                          operation=operation if memory else None)["value"]
            entry = {
                **metadata,
                "module": module, "operation": operation,
                "dynamic_energy_nJ": dynamic, "leakage_power_mW": leakage,
                "area_mm2": area, "technology_nm": 7, "frequency_MHz": query["frequency"],
                "source": "archx_query_module_metric", "query": dict(query),
                "placeholder": False,
            }
            if memory:
                entry.update({
                    "device": "finfet_7nm_0p7.xml", "voltage_V": 0.7,
                    "voltage_model": "synthetic: 0.45 V XML extrapolated to 0.7 V; alpha-power Ion (alpha=1.3), DIBL Ioff (40 mV/V, 68 mV/dec); replace before publication",
                })
                if design == "spinalflow" and module in SPINE_COUNTS:
                    entry["word_assumption"] = "32-bit spike record: assumed 16-bit timestamp + 16-bit neuron id; 256 records in 1 KiB"
                    entry["count_expression"] = SPINE_COUNTS[module][operation]
            else:
                entry.update(csv_provenance(archx_root, query))
                entry["process"] = "ASAP7"
                entry["characterization"] = "Own-RTL characterization; report provenance required"
            if operations[operation] is not None:
                entry["count_expression"] = operations[operation]
            rows[f"{design}.{module}.{operation}"] = entry
    return rows


def write_table(output, rows, design="spinalflow"):
    existing = json.loads(output.read_text()) if output.exists() else {}
    merged = {key: value for key, value in existing.items() if not key.startswith(design + ".")}
    merged.update(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    cap_threads()
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", default="spinalflow")
    parser.add_argument("--archx-root", type=Path, default=here.parents[2])
    parser.add_argument("--energy-root", type=Path, default=here)
    parser.add_argument("--output", type=Path, default=here.parent / "energy_table.json")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args(argv)
    run_dir = args.run_dir or here / ("archx_stub" if args.design == "spinalflow" else args.design + "_stub")
    rows = harvest(args.energy_root.resolve(), args.archx_root.resolve(), run_dir.resolve(), args.design)
    write_table(args.output, rows, args.design)
    print(f"archx_status=ok; wrote {len(rows)} {args.design} rows ({sum(bool(r['placeholder']) for r in rows.values())} pending synthesis) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
