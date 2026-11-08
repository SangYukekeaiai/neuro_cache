"""Replay captured layers across hardware sizes and sum sequential network latency."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import re
import shlex
import subprocess
import sys

import yaml

from gen_inputs import HARDWARE_SIZES, NETWORKS, REPO, ROOT, SAMPLES, arch_path, schedule_cache, schedule_path, workloads

FIELDS = ("network", "layer", "N", "sample", "total_cycles", "count_cycles")
SUMMARY_FIELDS = ("network", "N", "sample", "layers", "total_cycles", "count_cycles", "memory_cycles")


def run_case(case, outputs):
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


def summarize(rows, layer_workloads):
    expected = {(network, layer, n, s) for network, layers in layer_workloads.items()
                for layer in layers for n in HARDWARE_SIZES for s in SAMPLES}
    assert len(rows) == len(expected)
    assert {(r["network"], r["layer"], int(r["N"]), int(r["sample"])) for r in rows} == expected
    summary = []
    for network, layers in layer_workloads.items():
        for n in HARDWARE_SIZES:
            for sample in SAMPLES:
                group = [r for r in rows if r["network"] == network and int(r["N"]) == n
                         and int(r["sample"]) == sample]
                assert len(group) == len(layers)
                total = sum(int(r["total_cycles"]) for r in group)
                count = sum(int(r["count_cycles"]) for r in group)
                summary.append(dict(network=network, N=n, sample=sample, layers=len(layers),
                                    total_cycles=total, count_cycles=count, memory_cycles=total-count))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sample 0: VGG layer 02 at N=32, VGG layer 01 at N=128, ResNet layer 02 at N=128")
    parser.add_argument("--jobs", type=int, default=1, help="Independent replay/simulator subprocess pairs")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    outputs = ROOT / "outputs"
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
    if args.dry_run:
        cases = [("vgg16", "layer_02_features_7", 32, 0),
                 ("vgg16", "layer_01_features_3", 128, 0),
                 ("resnet19", "layer_02_layer1_0_conv2", 128, 0)]
    rows = []
    with (outputs / "results.csv").open("w", newline="") as results, (logs / "commands.txt").open("w") as command_log:
        writer = csv.DictWriter(results, fieldnames=FIELDS)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for row, commands in pool.map(lambda case: run_case(case, outputs), cases):
                rows.append(row)
                writer.writerow(row)
                results.flush()
                command_log.write("\n".join(commands) + "\n")
                command_log.flush()
                print(f"{len(rows)}/{len(cases)} {row['network']} N={row['N']} {row['layer']} s{row['sample']}: total={row['total_cycles']} count={row['count_cycles']}", flush=True)
    if not args.dry_run:
        with (outputs / "summary.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            writer.writerows(summarize(rows, layer_workloads))
    print(f"Completed {len(rows)} runs: {outputs / 'results.csv'}", flush=True)


if __name__ == "__main__":
    main()
