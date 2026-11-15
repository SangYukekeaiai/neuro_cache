"""Reprice included memories with bundled CACTI7; never edit the source tree.

Run: conda run -n fig12-archx python -B characterization/nangate45_memory.py
Check retained evidence: append --check. Independently rerun queries: --recheck.
Prices describe CACTI's 45nm ITRS LOP model, not a Nangate SRAM macro library.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CACTI = ROOT.parents[1] / "src/archx/interface/cacti7"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def source_manifest():
    native = CACTI / "include/cacti7"
    binary = native / f"cacti-{platform.system()}-{platform.machine()}"
    if not binary.is_file():
        raise FileNotFoundError(f"Bundled executable required; no build permitted: {binary}")
    files = [CACTI / "sram.cfg", CACTI / "cacti7.py", binary]
    files += sorted(p for p in native.iterdir() if p.suffix in (".cc", ".h"))
    files += sorted((native / "tech_params").glob("*.dat"))
    return {str(p): sha(p) for p in files}, binary


def selected_rows(table, policy):
    excluded = set(policy["excluded_operations"])
    return {key: row for key, row in table.items()
            if key not in excluded and row.get("source") != "excluded_by_decision"
            and row.get("query", {}).get("interface") == "cacti_fn"}


def geometry(query):
    """Mirror cacti_fn's byte/block/bank interpretation without technology reuse."""
    width = query["width"]
    if width % 8:
        raise ValueError("Explicit byte-rounding decision required for non-byte width")
    block = width // 8
    cache = query["class"] == "cache"
    assert query["class"] in ("sram", "cache")
    size = query["size"] // 8 if cache else block * query["depth"] * query["bank"]
    assert not cache or query["size"] % 8 == 0
    return {"class": query["class"], "size_bytes": size, "block_bytes": block,
            "width_bits": width, "bank": query["bank"],
            "depth_per_bank": None if cache else query["depth"],
            "associativity": query["associativity"] if cache else 1,
            "access_mode": query.get("access_mode", "normal") if cache else "normal"}


def config_text(g, base):
    cache = g["class"] == "cache"
    overrides = {
        "-size": f'-size (bytes) {g["size_bytes"]}',
        "-block size": f'-block size (bytes) {g["block_bytes"]}',
        "-technology": '-technology (u) 0.045',
        "-UCA bank count": f'-UCA bank count {g["bank"]}',
        "-output/input bus width": f'-output/input bus width {g["width_bits"]}',
        "-cache type": '-cache type "cache"' if cache else '-cache type "ram"',
        "-associativity": f'-associativity {g["associativity"]}',
        "-read-write port": f'-read-write port {int(cache)}',
        "-exclusive read port": f'-exclusive read port {int(not cache)}',
        "-exclusive write port": f'-exclusive write port {int(not cache)}',
        "-access mode": f'-access mode (normal, sequential, fast) - "{g["access_mode"]}"',
        "-print option": '-print option "debug detail"',
    }
    kept = [line for line in base.splitlines()
            if not any(line.strip().startswith(key + " ") for key in overrides)]
    return "\n".join(kept + ["", "# Per-query geometry and technology; debug exposes actual device voltage."]
                     + list(overrides.values())) + "\n"


def report_number(text, label):
    found = re.findall(r"^\s*" + re.escape(label) + r"\s*:\s*(" + NUMBER + r")\s*$", text, re.M)
    if not found or len(set(map(float, found))) != 1:
        raise ValueError(f"Missing or inconsistent report field {label!r}: {found}")
    value = float(found[0])
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid {label}: {value}")
    return value


def parse_report(text, g):
    expected = {"Cache size": g["size_bytes"], "Block size": g["block_bytes"],
                "Associativity": g["associativity"], "Cache banks (UCA)": g["bank"],
                "Technology": 0.045, "Technology size (nm)": 45, "Temperature": 360,
                "Read write ports": int(g["class"] == "cache"),
                "Read only ports": int(g["class"] == "sram"),
                "Write only ports": int(g["class"] == "sram"),
                "Access mode": {"normal": 0, "sequential": 1, "fast": 2}[g["access_mode"]]}
    for label in ("Data array cell type", "Data array peripheral type",
                  "Tag array cell type", "Tag array peripheral type"):
        expected[label] = 2  # native ITRS LOP column
    for label, value in expected.items():
        if report_number(text, label) != value:
            raise ValueError(f"Report/config mismatch: {label}")
    array = re.findall(r"^array type\s*:\s*(.+)$", text, re.M)
    assert array == ["Cache" if g["class"] == "cache" else "Scratch RAM"]
    voltages = re.findall(r"^-Vdd\[2\]:\s*(" + NUMBER + r")\s*\(V\)", text, re.M)
    assert voltages and set(map(float, voltages)) == {0.7}
    dims = re.findall(r"Cache height x width \(mm\):\s*(" + NUMBER + r")\s*x\s*(" + NUMBER + r")", text)
    assert len(dims) == 1
    height, width = map(float, dims[0])
    cycle = report_number(text, "Cycle time (ns)")
    leakage = report_number(text, "Total leakage power of a bank (mW)")
    gate = report_number(text, "Total gate leakage power of a bank (mW)")
    metrics = {"read_nJ": report_number(text, "Total dynamic read energy per access (nJ)"),
               "write_nJ": report_number(text, "Total dynamic write energy per access (nJ)"),
               "leakage_power_mW": (leakage + gate) * g["bank"],
               "area_mm2": height * width, "height_mm": height, "width_mm": width,
               "leakage_per_bank_mW": leakage, "gate_leakage_per_bank_mW": gate,
               "cycle_time_ns": cycle, "access_time_ns": report_number(text, "Access time (ns)"),
               "fmax_MHz": 1000 / cycle, "voltage_V": 0.7, "temperature_K": 360,
               "technology_nm": 45}
    assert all(math.isfinite(v) and v > 0 for v in metrics.values())
    return metrics


def run_query(directory, cfg, binary, deadline):
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "query.cfg"
    report = directory / "report.txt"
    config.write_text(cfg)
    tech = directory / "tech_params"
    if not tech.exists():
        tech.symlink_to(CACTI / "include/cacti7/tech_params", target_is_directory=True)
    assert tech.resolve() == (CACTI / "include/cacti7/tech_params").resolve()
    remaining = int(deadline - time.monotonic())
    if remaining < 1:
        raise TimeoutError("Serial CACTI budget exhausted")
    limit = min(120, remaining)
    cpu = min(os.sched_getaffinity(0))

    def bound_child():
        os.sched_setaffinity(0, {cpu})
        resource.setrlimit(resource.RLIMIT_CPU, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    start = time.monotonic()
    with report.open("w") as handle:
        process = subprocess.run([str(binary), "-infile", "query.cfg"], cwd=directory,
                                 stdout=handle, stderr=subprocess.STDOUT,
                                 preexec_fn=bound_child, timeout=limit)
    dump(directory / "execution.json", {"command": [str(binary), "-infile", "query.cfg"],
        "cwd": str(directory), "returncode": process.returncode,
        "wall_seconds": time.monotonic() - start, "cpu_affinity": [cpu],
        "cpu_limit_seconds": limit, "binary_sha256": sha(binary)})
    if process.returncode:
        raise RuntimeError(f"CACTI failed ({process.returncode}); retained report: {report}")
    return report


def wire_price(table, source_hashes, voltage_report):
    tech = CACTI / "include/cacti7/tech_params/45nm.dat"
    data = tech.read_text()
    index = 6  # conservative (1) * four wire types + global (2)

    def param(name):
        match = re.search(r"^" + re.escape(name) + r"\s+\([^)]*\)\s+(.+)$", data, re.M)
        assert match
        return float(match[1].split()[index])

    native = CACTI / "include/cacti7"
    epsilon = float(re.search(r"PERMITTIVITY_FREE_SPACE\s*=\s*(" + NUMBER + r")", (native / "const.h").read_text())[1])
    pitch = param("-wire_pitch") * 0.045
    width = pitch / 2
    spacing = pitch - width
    thickness = param("-aspect_ratio") * width
    vertical = 2 * epsilon * param("-vert_dielectric_constant") * width / param("-ild_thickness")
    sidewall = 2 * epsilon * param("-miller_value") * param("-horiz_dielectric_constant") * thickness / spacing
    fringe = param("-fringe_cap")
    cap = vertical + sidewall + fringe
    original = table["shared.link.hop"]
    assert original["packet_bits"] == 320 and original["length_mm"] == 1
    voltage = 0.7  # same actual LOP voltage verified in the native memory reports
    energy = 0.5 * cap * original["length_mm"] * 1000 * voltage**2 * original["packet_bits"] * 1e9
    return {"dynamic_energy_nJ": energy, "leakage_power_mW": 0, "area_mm2": 0,
        "assumption": "CACTI45 conservative global wire, 320 packet bits, 1mm link, one 0.5CV^2 charge per bit at native LOP0.7V; no repeater energy. Zero area/leakage are the retained wire accounting convention. ITRS wire estimate, not Nangate routed-wire characterization.",
        "provenance": {"characterization_technology_nm": 45, "source": "bundled_CACTI7_45nm_global_wire_CV2",
            "voltage_V": voltage, "voltage_report": voltage_report,
            "packet_bits": 320, "length_mm": 1, "wire_projection": "conservative", "wire_type": "global",
            "data_column_index": index, "wire_pitch_um": pitch, "wire_width_um": width,
            "wire_thickness_um": thickness, "wire_spacing_um": spacing,
            "ild_thickness_um": param("-ild_thickness"), "miller_value": param("-miller_value"),
            "horizontal_dielectric_constant": param("-horiz_dielectric_constant"),
            "vertical_dielectric_constant": param("-vert_dielectric_constant"), "epsilon_F_per_um": epsilon,
            "vertical_capacitance_F_per_um": vertical, "sidewall_capacitance_F_per_um": sidewall,
            "fringe_capacitance_F_per_um": fringe, "capacitance_F_per_um": cap,
            "formula_nJ": "0.5 * capacitance_F_per_um * length_mm * 1000 * voltage_V**2 * packet_bits * 1e9",
            "source_sha256": {str(p): source_hashes[str(p)] for p in
                (tech, native / "parameter.cc", native / "basic_circuit.cc", native / "const.h")},
            "physical_instances": original["physical_instances"], "scaling": "none; native45nm data"}}


def assemble(table, policy, queries, source_hashes):
    operations = {}
    for key, row in selected_rows(table, policy).items():
        q = row["query"]
        ident = hashlib.sha256(json.dumps(geometry(q), sort_keys=True).encode()).hexdigest()[:16]
        result = queries[ident]
        metrics = result["metrics"]
        operation = row["operation"]
        assert operation in ("read", "write")
        assumptions = [row.get("assumption", row.get("word_assumption", "")),
            "Exact original memory geometry at native CACTI7 45nm ITRS LOP0.7V/360K; no nearest-geometry or technology scaling. Cache includes tags and uses one RW port; SRAM uses one read and one write port. Per-access dynamic and per-physical-unit area/leakage; standing instances are not multiplied here. ITRS model, not a measured Nangate SRAM macro."]
        operations[key] = {"dynamic_energy_nJ": metrics[operation + "_nJ"],
            "leakage_power_mW": metrics["leakage_power_mW"], "area_mm2": metrics["area_mm2"],
            "assumption": " ".join(s for s in assumptions if s),
            "provenance": {"source": "bundled_cacti7_native45nm", "characterization_technology_nm": 45,
                "original_query": q, "actual_query": {**result["geometry"], "technology_nm": 45,
                    "voltage_V": metrics["voltage_V"], "temperature_K": metrics["temperature_K"],
                    "device_flavor": "itrs-lop", "interface": "cacti7 executable", "frequency_MHz": q["frequency"]},
                "query_id": ident, "config": result["config"], "config_sha256": result["config_sha256"],
                "report": result["report"], "report_sha256": result["report_sha256"],
                "sources_manifest": "sources.json", "source_sha256": source_hashes,
                "reported_metrics": metrics, "requested_frequency_MHz": q["frequency"],
                "meets_requested_frequency": metrics["fmax_MHz"] >= q["frequency"],
                "physical_instances": row.get("physical_instances", 1), "price_basis": "one physical unit, one access",
                "geometry_scaling": 1, "technology_scaling": 1}}
    assert operations
    voltage_basis = next(iter(operations.values()))["provenance"]
    operations["shared.link.hop"] = wire_price(table, source_hashes, voltage_basis["report"])
    operations["shared.link.hop"]["provenance"].update({
        "voltage_report_sha256": voltage_basis["report_sha256"],
        "voltage_config": voltage_basis["config"],
        "voltage_config_sha256": voltage_basis["config_sha256"],
        "voltage_evidence_role": "Native45nm LOP voltage confirmation; global-wire capacitance is derived from hashed45nm technology data and source formula"})
    return operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "nangate45_memory")
    parser.add_argument("--table", type=Path, default=ROOT / "energy_table.json")
    parser.add_argument("--policy", type=Path, default=HERE / "pricing_policy.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Reparse/hash retained evidence; no CACTI execution")
    mode.add_argument("--recheck", action="store_true", help="Rerun every geometry serially and compare metrics")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 1500  # single CPU, serial; below the30-minute CPU scope
    sources, binary = source_manifest()
    base = (CACTI / "sram.cfg").read_text()
    for source, name in ((args.table, "source_table.json"), (args.policy, "source_policy.json")):
        snapshot = output / name
        if not snapshot.exists():
            assert not args.check and not args.recheck
            snapshot.write_bytes(source.read_bytes())
    table = json.loads((output / "source_table.json").read_text())
    policy = json.loads((output / "source_policy.json").read_text())
    rows = selected_rows(table, policy)
    geometries = {hashlib.sha256(json.dumps(geometry(r["query"]), sort_keys=True).encode()).hexdigest()[:16]: geometry(r["query"]) for r in rows.values()}
    queries = {}
    for ident, g in sorted(geometries.items()):
        directory = output / "reports" / ident
        cfg = config_text(g, base)
        if not (directory / "report.txt").exists():
            assert not args.check and not args.recheck
            run_query(directory, cfg, binary, deadline)
        assert (directory / "query.cfg").read_text() == cfg
        metrics = parse_report((directory / "report.txt").read_text(), g)
        if args.recheck:
            repeated = run_query(output / "recheck" / ident, cfg, binary, deadline)
            assert parse_report(repeated.read_text(), g) == metrics, ident
        queries[ident] = {"geometry": g, "metrics": metrics,
            "config": str((directory / "query.cfg").relative_to(output)), "config_sha256": sha(directory / "query.cfg"),
            "report": str((directory / "report.txt").relative_to(output)), "report_sha256": sha(directory / "report.txt")}
        print(ident, g, "fmax_MHz", metrics["fmax_MHz"], flush=True)
    assert source_manifest()[0] == sources, "Bundled CACTI changed during characterization"
    operations = assemble(table, policy, queries, sources)
    assert not set(operations) & set(policy["excluded_operations"])
    assert not any("ddr4" in k for k in operations)
    result = {"operations": operations, "sources": sources, "manifest": {
        "characterization_technology_nm": 45, "backend": "bundled standard CACTI7 native executable",
        "model": "45nm ITRS LOP0.7V/360K; not Nangate SRAM macro characterization",
        "memory_operation_count": len(rows), "unique_memory_queries": len(queries),
        "total_operation_count": len(operations), "excluded_operations_skipped": policy["excluded_operations"],
        "ddr4": "two pinned rows omitted; parent preserves unchanged",
        "source_table": "source_table.json", "source_table_sha256": sha(output / "source_table.json"),
        "source_policy": "source_policy.json", "source_policy_sha256": sha(output / "source_policy.json"),
        "helper_sha256": sha(__file__), "cpu_scope": "serial, one CPU affinity,120s per query,1500s total wall budget per invocation",
        "all_geometries_exact": True, "all_reported_fmax_meet_500MHz": all(q["metrics"]["fmax_MHz"] >= 500 for q in queries.values())}}
    if args.check or args.recheck:
        assert json.loads((output / "memory_prices.json").read_text()) == result
        dump(output / ("recheck_verification.json" if args.recheck else "verification.json"),
             {"passed": True, "mode": "native rerun" if args.recheck else "retained report/hash check",
              "operations": len(operations), "queries": len(queries), "memory_prices_sha256": sha(output / "memory_prices.json")})
    else:
        dump(output / "sources.json", sources)
        dump(output / "queries.json", queries)
        dump(output / "memory_prices.json", result)
    print(f"Verified {len(rows)} memory rows + link; {len(queries)} exact geometries", flush=True)


if __name__ == "__main__":
    main()
