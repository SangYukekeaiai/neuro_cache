"""Replay captured layers across hardware sizes and sum sequential network latency."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from gen_inputs import (
    HARDWARE_SIZES, NETWORKS, REPO, ROOT, SAMPLE_COUNT, SAMPLE_SEED, SAMPLE_TOTAL,
    SAMPLES, arch_path, schedule_cache, schedule_path, workloads,
)

FIELDS = ("network", "layer", "N", "sample", "total_cycles", "count_cycles")
SUMMARY_FIELDS = ("network", "N", "sample", "layers", "total_cycles", "count_cycles", "memory_cycles")
DRY_RUN_CASES = (
    ("resnet19", "layer_02_core_layer1_0_conv2", 32, SAMPLES[0]),
    ("resnet19", "layer_04_core_layer1_1_conv1", 32, SAMPLES[1]),
    ("resnet19", "layer_09_core_layer2_0_conv2", 128, SAMPLES[0]),
)


def run_case(case, outputs, generate_weight=True):
    network, layer, n, sample = case
    trace = NETWORKS[network]
    stem = f"{network}_n{n}_{layer}_s{sample:05d}"
    commands = []

    def invoke(command, suffix):
        commands.append(shlex.join(command))
        result = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
        path = outputs / "logs" / f"{stem}_{suffix}.log"
        path.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}): {shlex.join(command)}; see {path}")
        return result.stdout

    weight_root = outputs / "weight_traces" / f"n{n}"
    if generate_weight:
        invoke([
            sys.executable, "-m", "lays.weight_trace_gen", "gen", "--arch", "spinalflow",
            "--trace-root", str(trace.parent), "--trace-dir", trace.name, "--layer", layer,
            "--schedule-cache", str(schedule_cache(n)), "--sample-start", str(sample),
            "--sample-count", "1", "--out-dir", str(weight_root), "--force",
        ], "weight_trace")
    stdout = invoke([
        sys.executable, "-m", "lays.nocsim", "--schedule", str(schedule_path(network, layer, n)),
        "--layer", str(outputs / "layers" / network / f"{layer}.yaml"),
        "--arch", str(arch_path(n)),
        "--weight-trace", str(weight_root / "spinalflow" / trace.name / layer / f"sample_{sample:05d}.json.gz"),
        "--out", str(outputs / "nocsim" / f"{stem}.csv"), "--simulate",
    ], "nocsim")
    row = dict(network=network, layer=layer, N=n, sample=sample)
    for key in ("total_cycles", "count_cycles", "unicast_cycles", "multicast_cycles"):
        match = re.search(rf"^{key}\s*:\s*(\d+)\s*$", stdout, re.MULTILINE)
        if match is None:
            raise ValueError(f"Missing {key}: {stem}")
        value = int(match[1])
        if key in FIELDS:
            row[key] = value
        else:
            assert value == 0, (stem, key, value)
    assert row["total_cycles"] >= row["count_cycles"]
    return row, commands


def run_weight_batch(group, outputs, workers=1):
    """Generate the selected sample set once for one (layer, N) group."""
    network, layer, n = group
    trace = NETWORKS[network]
    weight_root = outputs / "weight_traces" / f"n{n}"
    command = [
        sys.executable, "-m", "lays.weight_trace_gen", "gen", "--arch", "spinalflow",
        "--trace-root", str(trace.parent), "--trace-dir", trace.name, "--layer", layer,
        "--schedule-cache", str(schedule_cache(n)), "--sample-count", str(SAMPLE_COUNT),
        "--sample-total", str(SAMPLE_TOTAL), "--seed", str(SAMPLE_SEED),
        "--out-dir", str(weight_root), "--workers", str(workers),
        "--sample-chunk-size", "1", "--force",
    ]
    result = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
    stem = f"{network}_n{n}_{layer}"
    log_path = outputs / "logs" / f"{stem}_batch_weight_trace.log"
    log_path.write_text(shlex.join(command) + "\n" + result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {shlex.join(command)}; see {log_path}")
    expected = [weight_root / "spinalflow" / trace.name / layer / f"sample_{sample:05d}.json.gz"
                for sample in SAMPLES]
    missing = [path for path in expected if not path.exists()]
    if missing:
        raise RuntimeError(f"Batch generator omitted {len(missing)} samples for {stem}; see {log_path}")
    return command


def expected_cases(layer_workloads):
    return {(network, layer, n, s) for network, layers in layer_workloads.items()
            for layer in layers for n in HARDWARE_SIZES for s in SAMPLES}


def summarize(rows, layer_workloads, expected=None):
    expected = expected_cases(layer_workloads) if expected is None else set(expected)
    assert expected <= expected_cases(layer_workloads)
    assert len(rows) == len(expected)
    assert {(r["network"], r["layer"], int(r["N"]), int(r["sample"])) for r in rows} == expected
    summary = []
    for network, layers in layer_workloads.items():
        for n in HARDWARE_SIZES:
            for sample in SAMPLES:
                group_expected = {(network, layer, n, sample) for layer in layers
                                  if (network, layer, n, sample) in expected}
                if not group_expected:
                    continue
                group = [r for r in rows if r["network"] == network and int(r["N"]) == n
                         and int(r["sample"]) == sample]
                assert len(group) == len(group_expected)
                total = sum(int(r["total_cycles"]) for r in group)
                count = sum(int(r["count_cycles"]) for r in group)
                summary.append(dict(network=network, N=n, sample=sample, layers=len(group_expected),
                                    total_cycles=total, count_cycles=count, memory_cycles=total-count))
    return summary


def load_cases(path):
    payload = json.loads(path.read_text())
    raw_cases = payload["cases"] if isinstance(payload, dict) else payload
    return [(case["network"], case["layer"], int(case["N"]), int(case["sample"]))
            if isinstance(case, dict) else
            (case[0], case[1], int(case[2]), int(case[3])) for case in raw_cases]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Run three representative n500 ResNet19 cases")
    parser.add_argument("--jobs", type=int, default=1, help="Independent replay/simulator subprocess pairs")
    parser.add_argument("--case-file", type=Path, help="JSON list or manifest containing explicit cases")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: zoo/fig3_hw_n_sweep/outputs)")
    parser.add_argument("--results-suffix", default="", help="Suffix inserted before results.csv, summary.csv, and commands.txt")
    parser.add_argument("--no-summary", action="store_true", help="Do not write a summary CSV")
    parser.add_argument("--batch-samples", action="store_true",
                        help="Generate all selected samples once per (layer, N), then run nocsim per sample")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.case_file and args.dry_run:
        parser.error("--case-file and --dry-run are mutually exclusive")
    outputs = args.output_dir or ROOT / "outputs"
    if not outputs.is_absolute():
        outputs = ROOT / outputs
    if args.dry_run:
        outputs /= "smoke"
    logs = outputs / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    layer_workloads = workloads()
    for network, layers in layer_workloads.items():
        for layer, workload in layers.items():
            path = outputs / "layers" / network / f"{layer}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(workload, sort_keys=False))
    cases = [(network, layer, n, sample) for network, layers in layer_workloads.items()
             for n in HARDWARE_SIZES for layer in layers for sample in SAMPLES]
    if args.case_file:
        cases = load_cases(args.case_file)
    elif args.dry_run:
        cases = list(DRY_RUN_CASES)
    if args.batch_samples:
        groups = list(dict.fromkeys((network, layer, n) for network, layer, n, _ in cases))
        for group in groups:
            run_weight_batch(group, outputs, workers=args.jobs)
    rows = []
    suffix = args.results_suffix
    with (outputs / f"results{suffix}.csv").open("w", newline="") as results, (logs / f"commands{suffix}.txt").open("w") as command_log:
        writer = csv.DictWriter(results, fieldnames=FIELDS)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for row, commands in pool.map(
                lambda case: run_case(case, outputs, generate_weight=not args.batch_samples), cases
            ):
                rows.append(row)
                writer.writerow(row)
                results.flush()
                command_log.write("\n".join(commands) + "\n")
                command_log.flush()
                print(f"{len(rows)}/{len(cases)} {row['network']} N={row['N']} {row['layer']} s{row['sample']}: total={row['total_cycles']} count={row['count_cycles']}", flush=True)
    if not args.dry_run and not args.no_summary:
        expected = set(cases) if args.case_file else None
        with (outputs / f"summary{suffix}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            writer.writerows(summarize(rows, layer_workloads, expected=expected))
    print(f"Completed {len(rows)} runs: {outputs / f'results{suffix}.csv'}", flush=True)


if __name__ == "__main__":
    main()
