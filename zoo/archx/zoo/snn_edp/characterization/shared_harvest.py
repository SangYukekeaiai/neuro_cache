"""Shared SRAM, router/wire estimates and explicitly configured DDR4 costs."""
import csv
import json
import math
import re
from pathlib import Path


def report_value(text, label):
    match = re.search(re.escape(label) + r"\s*[:=]\s*([-+\d.eE]+)", text)
    if not match:
        raise ValueError(f"missing CACTI report field: {label}")
    value = float(match[1])
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid CACTI report value: {label}={value}")
    return value


def row(module, operation, energy, power, area, technology=7, **extra):
    return {"module": module, "operation": operation, "dynamic_energy_nJ": energy,
            "leakage_power_mW": power, "area_mm2": area, "technology_nm": technology,
            "frequency_MHz": 500, "placeholder": False, "scope": "system", **extra}


def harvest(energy_root, archx_root, run_dir):
    import yaml
    from archx.interface.cacti_fn.cacti_fn import query as sram_query
    from archx.interface.cacti7.cacti7 import cacti7_run, parse_report_dram
    run_dir.mkdir(parents=True, exist_ok=True)
    modules = yaml.safe_load((energy_root / "shared.architecture.yaml").read_text())["architecture"]["module"]
    rows = {}
    gb = modules["gb"]
    query = dict(gb["query"])
    query.pop("interface")
    metrics = sram_query("gb", "cacti_fn", query, output_dir=str(run_dir))
    for operation, count in gb["operations"].items():
        rows[f"shared.gb.{operation}"] = row("gb", operation,
            metrics["dynamic_energy"][operation]["value"], metrics["leakage_power"]["value"], metrics["area"]["value"],
            source="cacti_fn", query=gb["query"], physical_instances=1, count_expression=count,
            assumption="Synthetic7nm0.7V device; replace before publication", applies_to=["spad"])

    router = modules["router"]
    path = archx_root / "src/archx/interface/csv_cmos_32nm/include/csv/noc_router.csv"
    source, = list(csv.DictReader(path.open()))
    v32, v7 = router["reference_voltage"], router["target_voltage"]
    scale = (0.1776*v7*v7 - 0.09097*v7 + 0.02447) / (0.9559*v32*v32 - 0.7823*v32 + 0.471)
    energy = float(source["dynamic_uw"]) / float(source["frequency"]) * router["packet_bits"] / float(source["bandwidth"]) * scale
    rows["shared.router.hop"] = row("router", "hop", None, None, None, source="scaled_archx_router_csv", physical_instances=16,
        count_expression="packet_hops", applies_to=["spad", "cacheA", "cacheB"], source_csv=str(path),
        placeholder="pending-ASAP7-synthesis", unvalidated_dynamic_energy_nJ=energy,
        reference_technology_nm=32, dynamic_scale=scale, area_scale=0.13, leakage_scale=1,
        scaling_citation=router["scaling_citation"], packet_bits=router["packet_bits"],
        assumption="Source follows archx mW/MHz convention but is extremely small; published-router range validation unresolved. Source zero leakage is unavailable characterization, not proof of zero physical leakage.")

    link = modules["link"]
    # FN-CACTI technology.cc ASAP7 global wire geometry and wire_capacitance().
    eps = 8.854e-18  # F/um
    c_per_um = 2*eps*3.9*0.04/0.130 + 2*eps*1.5*0.864*0.08/0.032 + 0.115e-15
    energy = 0.5 * c_per_um * link["length_mm"] * 1000 * link["voltage"]**2 * link["packet_bits"] * 1e9
    rows["shared.link.hop"] = row("link", "hop", energy, 0, 0, source="ASAP7_global_wire_CV2",
        count_expression="packet_hops", physical_instances=48, applies_to=["spad", "cacheA", "cacheB"],
        capacitance_F_per_um=c_per_um, length_mm=link["length_mm"], packet_bits=link["packet_bits"],
        assumption=link["assumption"] + " 0.5CV2 per bit, no repeater energy; wire leakage and area set to zero by modeling convention.",
        source_file=str(archx_root / "src/archx/interface/cacti_fn/include/cacti_fn/technology.cc"))

    dram = modules["ddr4"]
    original = (archx_root / "src/archx/interface/cacti7/ddr4.cfg").read_text()
    # The shipped template uses underscore keys that io.cc does not recognize.
    # Correct only our run copy, and assert the actual reported interface below.
    original = "\n".join(line for line in original.splitlines()
                         if not line.startswith(("-dram_type", "-iostate", "-num_dq", "-num_dqs", "-bus_freq")))
    reports = {}
    query = {k: v for k, v in dram["query"].items() if k not in ("interface", "class", "technology", "frequency")}
    for state in ("READ", "IDLE"):
        base = run_dir / f"ddr4_{state}.base.cfg"
        base.write_text(original + f'\n-dram type "DDR4"\n-io state "{state}"\n-num_dq {dram["data_pins"]}\n-num_dqs 16\n-bus_freq {dram["bus_frequency_MHz"]}\n')
        report = run_dir / f"ddr4_{state}.rpt"
        cacti7_run("ddr4", "22", query, str(base), str(run_dir / f"ddr4_{state}.cfg"), str(report))
        reports[state] = report.read_text()
        if not re.search(r"io_type\s*:\s*DDR4", reports[state]):
            raise ValueError("CACTI did not model DDR4")
    act, rd, wr, pre, closed, opened, internal_io, refresh, area, freq = parse_report_dram(str(run_dir / "ddr4_READ.rpt"))
    access_energy = act + pre + rd * dram["burst_bytes"] / dram["array_read_bytes"]
    idle_dynamic = report_value(reports["IDLE"], "IO Dynamic Power (mW)")
    read_dynamic = report_value(reports["READ"], "IO Dynamic Power (mW)")
    io_byte = (read_dynamic - idle_dynamic) / (2 * dram["bus_frequency_MHz"] * dram["data_pins"]) * 8
    if io_byte < 0:
        raise ValueError("negative incremental DDR4 IO energy")
    idle_power = idle_dynamic + report_value(reports["IDLE"], "PHY Power (mW)") + report_value(reports["IDLE"], "IO Termination and Bias Power (mW)")
    standing = 8 * (closed + internal_io + refresh) + idle_power
    rows["shared.ddr4.read"] = row("ddr4", "read", access_energy, standing, area, technology=22,
        source="cacti7_ddr4_report", count_expression="dram_accesses", physical_instances=1,
        query=dram["query"], burst_bytes=dram["burst_bytes"], activate_nJ=act, precharge_nJ=pre,
        array_read_nJ=rd, array_read_bytes=dram["array_read_bytes"],
        assumption="Closed-page64-byte read: one activate/precharge plus eight8-byte array transfers;8-bank leakage/refresh plus external idle IO/PHY.")
    rows["shared.ddr4_io.byte"] = row("ddr4_io", "byte", io_byte, 0, 0, technology=22,
        source="cacti7_ddr4_external_io", count_expression="dram_bytes", physical_instances=0,
        assumption="Incremental READ minus IDLE IO dynamic power over DDR data rate; standing IO already charged in ddr4.read; zero leakage/area here is a modeling convention, not missing characterization.")
    return rows
