"""Record the completed hardware-N campaign's inputs and output artifacts."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys

import matplotlib
from matplotlib import font_manager
import numpy as np
import yaml

import plot

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def record(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    name = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
    return dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def main():
    manifest, rows = plot.load_summary()
    plot.paper_style()
    font = font_manager.findfont(font_manager.FontProperties(family=matplotlib.rcParams["font.family"]))
    inputs = sorted((ROOT / "inputs").rglob("*.json")) + sorted((ROOT / "inputs").rglob("*.yaml"))
    for info in manifest["networks"].values():
        trace = REPO / info["trace"]
        inputs.append(trace / "meta.json")
        inputs.extend(trace / f"{name}.npy" for name in info["included_layers"])
    feasibility = json.loads((ROOT / "outputs/feasibility/report.json").read_text())
    for case in feasibility["cases"]:
        inputs.append(REPO / "examples/input_trace/loas/resnet19_T4_n5" / f"{case['layer']}.npy")
    statistics = []
    for network in manifest["networks"]:
        for n in manifest["hardware_sizes"]:
            group = [r for r in rows if r["network"] == network and r["N"] == n]
            statistics.append(dict(network=network, N=n, samples=len(group), **{
                key: dict(median=median(r[key] for r in group), min=min(r[key] for r in group),
                          max=max(r[key] for r in group))
                for key in ("total_cycles", "count_cycles", "memory_cycles")
            }))
    python = "/u/yyu9/miniconda3/envs/gurobi/bin/python"
    prefix = "zoo/fig3_hw_n_sweep"
    document = {
        "campaign": "fig3_hw_n_sweep", "samples_per_network_and_N": 5,
        "repo_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_completed_at_utc": datetime.fromtimestamp((ROOT / "outputs/results.csv").stat().st_mtime, timezone.utc).isoformat(),
        "working_tree_note": "Campaign files are untracked. combine.py is modified relative to repo_commit; its exact source and patch are recorded. The working tree also has an unrelated docs/weight_trace_gen_archs.md modification.",
        "architecture": {"name": "spinalflow", "single_node": True, "hardware_sizes": manifest["hardware_sizes"],
                         "node_instances": 1, "physical_global_buffer": False,
                         "buffer_bytes": {"weight": "3*3*512*N", "psum": "144*N", "vmem": "144*N"},
                         "buffer_note": "Psum/vmem sizes preserve the N=128 reference allocation, not a computed requirement; per-tile psum need is 2*min(N,COUT) bytes. nocsim does not enforce capacities.",
                         "bitwidths": {"weight": 8, "psum": 16, "vmem": 32}, "dram_cycles_per_32byte_packet": 0.25},
        "mapping": {"active_PEs": "min(N,COUT)", "node_temporal": ["KH", "KW", "CIN", "T"],
                    "NoC_loops": [], "DRAM_outer_to_inner": ["HO", "WO", "COUT"],
                    "dram_num_steps": "HO*WO*COUT/min(N,COUT)", "idle_lanes": "N-min(N,COUT)"},
        "workloads": manifest["networks"],
        "capture_sample_indices": [2697, 3078, 5110, 6367, 8502],
        "metric": "For each network/N/sample, sum included layer total_cycles and count_cycles separately; memory_cycles is their difference. Layers execute sequentially without overlap.",
        "coverage": "VGG16 includes all 12 captured convolutions. ResNet19 is a 13-of-19-convolution partial sum: 01,03,08,10,15,17 are omitted because stride-2 replay is unsupported. These are the spatial-downsampling convolutions, so omission is not uniform across network depth. Uncaptured operations are outside the metric.",
        "feasibility": feasibility,
        "feasibility_artifacts": [record(p) for p in sorted((ROOT / "outputs/feasibility").iterdir()) if p.is_file()],
        "commands": [
            "make -C src/lays/weight_trace_gen/spinalflow", "make -C src/lays/nocsim/eventsim",
            f"PYTHONPATH=src {python} {prefix}/check_replay.py",
            f"PYTHONPATH=src {python} {prefix}/gen_inputs.py",
            f"setsid env PYTHONPATH=src {python} {prefix}/run.py --dry-run --jobs 2",
            f"setsid env PYTHONPATH=src {python} {prefix}/run.py --jobs 4 > {prefix}/outputs/full_run.log 2>&1",
            f"{python} {prefix}/plot.py", f"{python} {prefix}/record_provenance.py",
        ],
        "command_logs": [record(ROOT / "outputs/logs/commands.txt"), record(ROOT / "outputs/smoke/logs/commands.txt")],
        "inputs": [record(p) for p in sorted(set(inputs))],
        "scripts": [record(ROOT / name) for name in ("gen_inputs.py", "check_replay.py", "run.py", "plot.py", "record_provenance.py")],
        "source_files": [record(REPO / name) for name in (
            "src/lays/nocsim/combine.py", "tests/test_weight_dependencies.py",
            "src/lays/weight_trace_gen/spinalflow/SpinalFlowGen.h",
            "src/lays/weight_trace_gen/spinalflow/native_bridge.py", "src/lays/weight_trace_gen/trace.py")],
        "source_patch": record(ROOT / "outputs/combine.patch"),
        "binaries": [record(REPO / name) for name in ("src/lays/weight_trace_gen/spinalflow/spinalflowgen", "src/lays/nocsim/eventsim/eventsim")],
        "outputs": [record(ROOT / name) for name in ("outputs/results.csv", "outputs/summary.csv", "outputs/full_run.log",
                    "outputs/smoke/results.csv", "fig3_hw_n_sweep.pdf", "fig3_hw_n_sweep.png", "README.md")],
        "artifact_counts": {"layer_runs": 625, "network_sample_totals": 50, "layer_schedules": 125, "architectures": 5},
        "statistics": statistics,
        "figure": {"width_inches": 3.375, "height_to_width_ratio": 0.65, "text_size_pt": 8,
                   "x_axis": "Node size N (PEs)", "y_axis": "Latency (cycles)", "y_tick_unit": "millions of cycles",
                   "boxes": "Q1-Q3 of five per-sample network totals; median center; min-max whiskers; linear NumPy percentile interpolation",
                   "lines": "Per-network medians across hardware sizes", "colors": plot.COLORS, "labels": plot.LABELS,
                   "font_requested": "Gill Sans MT", "font_used": font_manager.FontProperties(fname=font).get_name(),
                   "font_file": record(font), "font_fallback": not any(p.is_file() and p.name.upper().startswith("GIL")
                       and p.suffix.lower() == ".ttf" for p in ROOT.iterdir()),
                   "pdf_graphics": "vector", "pdf_creation_date": None, "png_dpi": 300},
        "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                        "numpy": np.__version__, "PyYAML": yaml.__version__, "matplotlib": matplotlib.__version__,
                        "parallel_jobs": 4, "process_isolation": "setsid; systemd user bus unavailable"},
        "future_capture_repository": {"path": "neuro_cache_bench_trace", "url": "git@github.com:SangYukekeaiai/neuro_cache_bench_trace.git",
            "commit": subprocess.check_output(["git", "-C", str(REPO / "neuro_cache_bench_trace"), "rev-parse", "HEAD"], text=True).strip(),
            "used_for_demo": False, "submodule": False, "ignore_file": record(REPO / ".gitignore")},
        "limitations": ["Five captured samples per network; no confidence intervals.",
                        "ResNet19 coverage is a 13-of-19 partial convolution sum with nonuniform omission of spatial-downsampling layers.",
                        "Network sums assume sequential execution with no inter-layer overlap.",
                        "Manual mappings; no solver optimization or buffer-capacity enforcement.",
                        "Lanes above a layer's COUT remain idle; fixed bandwidth and replay model determine latency."],
    }
    path = ROOT / "provenance.json"
    path.write_text(json.dumps(document, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
