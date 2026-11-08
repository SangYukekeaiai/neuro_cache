"""Record the completed hardware-N campaign's inputs and output artifacts."""

import hashlib
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import platform
import shlex
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


def read_csv(path):
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        return [{key: value if key == "network" or key == "layer" else int(value)
                 for key, value in row.items()} for row in csv.DictReader(handle)]


def expected_keys(manifest):
    layer_keys = {(network, layer, n, sample)
                  for network, info in manifest["networks"].items()
                  for layer in info["included_layers"]
                  for n in manifest["hardware_sizes"]
                  for sample in manifest["samples"]}
    summary_keys = {(network, n, sample)
                    for network in manifest["networks"]
                    for n in manifest["hardware_sizes"]
                    for sample in manifest["samples"]}
    return layer_keys, summary_keys


def validate_partial_outputs(manifest, layer_rows, summary_rows):
    layer_keys, summary_keys = expected_keys(manifest)
    observed_layers = {(row["network"], row["layer"], row["N"], row["sample"])
                       for row in layer_rows}
    observed_summaries = {(row["network"], row["N"], row["sample"])
                          for row in summary_rows}
    if not observed_layers <= layer_keys or not observed_summaries <= summary_keys:
        raise RuntimeError("results contain cases outside the current n500 manifest")
    groups = {}
    for row in layer_rows:
        groups.setdefault((row["network"], row["N"], row["sample"]), []).append(row)
    if set(groups) != observed_summaries:
        raise RuntimeError("summary.csv does not cover exactly the available results.csv cases")
    for summary in summary_rows:
        group = groups[(summary["network"], summary["N"], summary["sample"])]
        if summary["layers"] != len(group):
            raise RuntimeError("summary.csv layer count disagrees with results.csv")
        if summary["total_cycles"] != sum(row["total_cycles"] for row in group):
            raise RuntimeError("summary.csv total_cycles disagrees with results.csv")
        if summary["count_cycles"] != sum(row["count_cycles"] for row in group):
            raise RuntimeError("summary.csv count_cycles disagrees with results.csv")
        if summary["memory_cycles"] != summary["total_cycles"] - summary["count_cycles"]:
            raise RuntimeError("summary.csv memory_cycles is inconsistent")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "outputs",
                        help="directory containing merged results.csv and summary.csv")
    parser.add_argument("--shard-root", type=Path, default=ROOT / "outputs/slurm/n500-assembled-runs",
                        help="campaign shard root containing shard_*/logs/commands_*.txt")
    parser.add_argument("--output", type=Path, default=ROOT / "provenance.json",
                        help="provenance JSON destination")
    return parser.parse_args()


def resolve_cli_path(path):
    path = Path(path)
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def main():
    args = parse_args()
    results_dir = resolve_cli_path(args.results_dir)
    result_path = results_dir / "results.csv"
    summary_path = results_dir / "summary.csv"
    manifest = json.loads((ROOT / "inputs/manifest.json").read_text())
    layer_rows = read_csv(result_path)
    summary_rows = read_csv(summary_path)
    default_results = result_path.resolve() == (ROOT / "outputs/results.csv").resolve()
    if summary_path.is_file():
        validate_partial_outputs(manifest, layer_rows, summary_rows)
    if default_results:
        if not result_path.is_file() or not summary_path.is_file():
            raise RuntimeError("default results directory is incomplete; refusing provenance record")
        try:
            manifest, rows = plot.load_summary()
        except (AssertionError, KeyError, ValueError, FileNotFoundError) as exc:
            raise RuntimeError(
                "default results do not match the n500 manifest; refusing contradictory provenance"
            ) from exc
        campaign_complete = True
        stats_rows = rows
    else:
        campaign_complete = len(layer_rows) == 6500 and len(summary_rows) == 500
        stats_rows = summary_rows
    plot.paper_style()
    font = font_manager.findfont(font_manager.FontProperties(family=matplotlib.rcParams["font.family"]))
    inputs = sorted((ROOT / "inputs").rglob("*.json")) + sorted((ROOT / "inputs").rglob("*.yaml"))
    for info in manifest["networks"].values():
        trace = Path(info["trace"])
        if not trace.is_absolute():
            trace = REPO / trace
        inputs.append(trace / "meta.json")
        inputs.extend(trace / f"{name}.npy" for name in info["included_layers"])
    feasibility = json.loads((ROOT / "outputs/feasibility/report.json").read_text())
    for case in feasibility["cases"]:
        inputs.append(Path(feasibility["trace"]) / f"{case['layer']}.npy")
    statistics = []
    groups = {(r["network"], r["N"]) for r in stats_rows}
    for network, n in sorted(groups):
        group = [r for r in stats_rows if r["network"] == network and r["N"] == n]
        statistics.append(dict(network=network, N=n, samples=len(group), **{
            key: dict(median=median(r[key] for r in group), min=min(r[key] for r in group),
                      max=max(r[key] for r in group))
            for key in ("total_cycles", "count_cycles", "memory_cycles")
        }))
    python = "/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python"
    prefix = "zoo/fig3_hw_n_sweep"
    shard_root = resolve_cli_path(args.shard_root)
    command_logs = sorted(shard_root.glob("shard_*/logs/commands_*.txt"))
    command_logs = [path for path in command_logs if path.is_file()]
    output_paths = [result_path, summary_path]
    if campaign_complete:
        output_paths.extend(ROOT / f"fig3_hw_n_sweep.{suffix}" for suffix in ("pdf", "png"))
    output_paths.append(ROOT / "README.md")
    output_paths = [path for path in output_paths if path.is_file()]
    future_repo = REPO / "neuro_cache_bench_trace"
    future_commit = None
    if future_repo.is_dir():
        future_commit = subprocess.check_output(
            ["git", "-C", str(future_repo), "rev-parse", "HEAD"], text=True
        ).strip()
    assembly_path = shard_root / "assembly.json"
    assembly = json.loads(assembly_path.read_text()) if assembly_path.is_file() else None
    if assembly_path.is_file():
        output_paths.append(assembly_path)

    def repo_path(path):
        path = Path(path)
        return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)

    if assembly:
        assembly_args = ["--manifest", repo_path(assembly["target_manifest"])]
        for source in assembly["sources"]:
            assembly_args.extend(("--source", repo_path(source["manifest"]), repo_path(source["shard_root"])))
        assembly_args.extend(("--output-root", repo_path(assembly["output_root"])))
    else:
        assembly_args = [
            "--manifest", "zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases/manifest.json",
            "--source", "zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases/manifest.json",
            "zoo/fig3_hw_n_sweep/outputs/slurm/n500-runs",
            "--output-root", "zoo/fig3_hw_n_sweep/outputs/slurm/n500-assembled-runs",
        ]
    assembly_command = (
        f"PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm {python} {prefix}/slurm/assemble_shards.py "
        f"{shlex.join(assembly_args)}"
    )
    document = {
        "campaign": "fig3_hw_n_sweep", "samples_per_network_and_N": len(manifest["samples"]),
        "campaign_complete": campaign_complete,
        "results_dir": str(results_dir.relative_to(REPO) if results_dir.is_relative_to(REPO) else results_dir),
        "shard_root": str(shard_root.relative_to(REPO) if shard_root.is_relative_to(REPO) else shard_root),
        "repo_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_completed_at_utc": (datetime.fromtimestamp(result_path.stat().st_mtime, timezone.utc).isoformat()
                                 if campaign_complete else None),
        "working_tree_note": "Campaign harness/configuration files may be uncommitted at capture time. "
                             "src/lays/nocsim/combine.py is already part of repo_commit; no external patch is required.",
        "architecture": {"name": "spinalflow", "single_node": True, "hardware_sizes": manifest["hardware_sizes"],
                         "node_instances": 1, "physical_global_buffer": False,
                         "buffer_bytes": {"weight": "3*3*512*N", "psum": "144*N", "vmem": "144*N"},
                         "buffer_note": "Psum/vmem sizes preserve the N=128 reference allocation, not a computed requirement; per-tile psum need is 2*min(N,COUT) bytes. nocsim does not enforce capacities.",
                         "bitwidths": {"weight": 8, "psum": 16, "vmem": 32}, "dram_cycles_per_32byte_packet": 0.25},
        "mapping": {"active_PEs": "min(N,COUT)", "node_temporal": ["KH", "KW", "CIN", "T"],
                    "NoC_loops": [], "DRAM_outer_to_inner": ["HO", "WO", "COUT"],
                    "dram_num_steps": "HO*WO*COUT/min(N,COUT)", "idle_lanes": "N-min(N,COUT)"},
        "workloads": manifest["networks"],
        "capture_sample_indices": manifest["samples"],
        "metric": "For each network/N/sample, sum included layer total_cycles and count_cycles separately; memory_cycles is their difference. Layers execute sequentially without overlap.",
        "coverage": "ResNet19 includes 13 of 19 captured convolutions. Layers 01,03,08,10,15,17 are omitted because stride-2 replay is unsupported. These are the spatial-downsampling convolutions, so omission is not uniform across network depth. Uncaptured operations are outside the metric.",
        "feasibility": feasibility,
        "feasibility_artifacts": [record(p) for p in sorted((ROOT / "outputs/feasibility").iterdir()) if p.is_file()],
        "commands": [
            "make -C src/lays/weight_trace_gen/spinalflow", "make -C src/lays/nocsim/eventsim",
            f"PYTHONPATH=src {python} {prefix}/check_replay.py",
            f"PYTHONPATH=src {python} {prefix}/gen_inputs.py",
            f"PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm {python} {prefix}/slurm/shard_cases.py --batch-samples --num-shards 250 --cases-per-shard 100",
            f"sbatch --partition=normal --time=90:00 --cpus-per-task=4 --array=0-64%65 {prefix}/slurm/run_array.sbatch --batch-samples",
            assembly_command,
            f"PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm {python} {prefix}/slurm/merge_results.py --shard-root {repo_path(shard_root)}",
            f"{python} {prefix}/plot.py", f"{python} {prefix}/record_provenance.py",
        ],
        "command_logs": [record(path) for path in command_logs],
        "shard_assembly": record(assembly_path) if assembly_path.is_file() else None,
        "inputs": [record(p) for p in sorted(set(inputs))],
        "scripts": [record(ROOT / name) for name in (
            "gen_inputs.py", "check_replay.py", "run.py", "plot.py", "record_provenance.py",
            "slurm/harness.py", "slurm/shard_cases.py", "slurm/run_array.sbatch",
            "slurm/merge_results.py", "slurm/rerun_missing.py", "slurm/assemble_shards.py")],
        "source_files": [record(REPO / name) for name in (
            "src/lays/nocsim/combine.py", "tests/test_weight_dependencies.py",
            "src/lays/weight_trace_gen/cli.py",
            "src/lays/weight_trace_gen/spinalflow/SpinalFlowGen.h",
            "src/lays/weight_trace_gen/spinalflow/native_bridge.py", "src/lays/weight_trace_gen/trace.py")],
        "source_patch": None,
        "binaries": [record(REPO / name) for name in ("src/lays/weight_trace_gen/spinalflow/spinalflowgen", "src/lays/nocsim/eventsim/eventsim")],
        "outputs": [record(path) for path in output_paths],
        "artifact_counts": {"layer_runs": 6500, "network_sample_totals": 500, "layer_schedules": 65, "architectures": 5},
        "statistics": statistics,
        "figure": {"width_inches": 3.375, "height_to_width_ratio": 0.65, "text_size_pt": 8,
                   "x_axis": "Node size N (PEs)", "y_axis": "Latency (cycles)", "y_scale": "log",
                   "y_limits_cycles": [2000000, 25000000],
                   "y_major_ticks_cycles": [2000000, 5000000, 10000000, 20000000],
                   "y_tick_unit": "millions of cycles",
                   "boxes": "Q1-Q3 of 100 per-sample network totals; median center; min-max whiskers; linear NumPy percentile interpolation",
                   "lines": "Per-network medians across hardware sizes",
                   "colors": {"boxes_whiskers": plot.COLORS, "median_line_markers_legend": plot.MEDIAN_COLOR},
                   "median_color": plot.MEDIAN_COLOR, "labels": plot.LABELS,
                   "font_requested": "Gill Sans MT", "font_used": font_manager.FontProperties(fname=font).get_name(),
                   "font_file": record(font), "font_fallback": not any(p.is_file() and p.name.upper().startswith("GIL")
                       and p.suffix.lower() == ".ttf" for p in ROOT.iterdir()),
                   "pdf_graphics": "vector", "pdf_creation_date": None, "png_dpi": 300},
        "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                        "numpy": np.__version__, "PyYAML": yaml.__version__, "matplotlib": matplotlib.__version__,
                        "parallel_jobs": 4, "process_isolation": "setsid; systemd user bus unavailable"},
        "future_capture_repository": {"path": "neuro_cache_bench_trace", "url": "git@github.com:SangYukekeaiai/neuro_cache_bench_trace.git",
            "commit": future_commit,
            "used_for_demo": False, "submodule": False, "ignore_file": record(REPO / ".gitignore")},
        "limitations": ["100 selected captured samples from the 500-sample trace; no confidence intervals.",
                        "ResNet19 coverage is a 13-of-19 partial convolution sum with nonuniform omission of spatial-downsampling layers.",
                        "Network sums assume sequential execution with no inter-layer overlap.",
                        "Manual mappings; no solver optimization or buffer-capacity enforcement.",
                        "Lanes above a layer's COUT remain idle; fixed bandwidth and replay model determine latency."],
    }
    path = resolve_cli_path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
