#!/usr/bin/env python3
"""Validate and merge per-shard results into campaign results and summary CSVs."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from harness import DEFAULT_CASE_DIR, campaign_modules, case_key, load_manifest, result_path


def read_shard(path, fields):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(fields):
            raise SystemExit(f"{path}: expected CSV fields {fields}, got {reader.fieldnames}")
        return list(reader)


def expected_cases(layer_workloads, networks, hardware_sizes, samples):
    return {
        (network, layer, n, sample)
        for network in networks
        for layer in layer_workloads[network]
        for n in hardware_sizes
        for sample in samples
    }


def validate_rows(rows, expected, label):
    expected = set(expected)
    observed = [case_key((row["network"], row["layer"], row["N"], row["sample"])) for row in rows]
    counts = Counter(observed)
    duplicates = sorted((key, count) for key, count in counts.items() if count != 1)
    missing = sorted(expected - counts.keys())
    extra = sorted(counts.keys() - expected)
    if duplicates or missing or extra or len(rows) != len(expected):
        raise SystemExit(
            f"{label} coverage validation failed: rows={len(rows)} expected={len(expected)} "
            f"duplicates={duplicates[:5]} missing={missing[:5]} extra={extra[:5]}"
        )


def summary_key(row):
    return (row["network"], int(row["N"]), int(row["sample"]))


def validate_summary(rows, summary_rows, layer_workloads, expected, run, label):
    expected_keys = {(network, n, sample) for network, _layer, n, sample in expected}
    observed = [summary_key(row) for row in summary_rows]
    counts = Counter(observed)
    duplicates = sorted((key, count) for key, count in counts.items() if count != 1)
    missing = sorted(expected_keys - counts.keys())
    extra = sorted(counts.keys() - expected_keys)
    if duplicates or missing or extra or len(summary_rows) != len(expected_keys):
        raise SystemExit(
            f"{label} summary validation failed: rows={len(summary_rows)} expected={len(expected_keys)} "
            f"duplicates={duplicates[:5]} missing={missing[:5]} extra={extra[:5]}"
        )
    calculated = run.summarize(rows, layer_workloads, expected=expected)
    actual_values = {
        summary_key(row): tuple(int(row[field]) for field in run.SUMMARY_FIELDS[3:])
        for row in summary_rows
    }
    calculated_values = {
        summary_key(row): tuple(int(row[field]) for field in run.SUMMARY_FIELDS[3:])
        for row in calculated
    }
    if actual_values != calculated_values:
        raise SystemExit(f"{label} summary does not match its results.csv rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_CASE_DIR / "manifest.json")
    parser.add_argument("--shard-root", type=Path,
                        help="root containing shard_XXXX/results_XXXX.csv")
    parser.add_argument("--output-dir", type=Path,
                        help="directory for merged results.csv and summary.csv")
    parser.add_argument("--carry-existing", action="store_true",
                        help="carry the existing resnet19 results and summary into this merge")
    args = parser.parse_args()

    manifest, manifest_cases = load_manifest(args.manifest)
    shard_root = args.shard_root or args.manifest.parent.parent / "runs"
    output_dir = args.output_dir or args.manifest.parent.parent.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    _, run = campaign_modules()

    rows = []
    for index in range(manifest["num_shards"]):
        path = result_path(shard_root, index)
        if not path.is_file():
            raise SystemExit(f"missing shard result: {path}")
        rows.extend(read_shard(path, run.FIELDS))

    expected = set(manifest_cases)
    layer_workloads = run.workloads()
    validate_rows(rows, expected, "shard")
    manifest_order = {case: index for index, case in enumerate(manifest_cases)}
    new_rows = rows

    if args.carry_existing:
        existing_results_path = output_dir / "results.csv"
        existing_summary_path = output_dir / "summary.csv"
        if not existing_results_path.is_file() or not existing_summary_path.is_file():
            raise SystemExit(
                "--carry-existing requires existing results.csv and summary.csv in "
                f"{output_dir}"
            )
        existing_rows = read_shard(existing_results_path, run.FIELDS)
        existing_summary_rows = read_shard(existing_summary_path, run.SUMMARY_FIELDS)
        existing_expected = expected_cases(
            layer_workloads, ("resnet19",), run.HARDWARE_SIZES, run.SAMPLES
        )
        validate_rows(existing_rows, existing_expected, "existing results")
        validate_summary(existing_rows, existing_summary_rows,
                         {"resnet19": layer_workloads["resnet19"]}, existing_expected,
                         run, "existing")
        overlap = set(case_key((row["network"], row["layer"], row["N"], row["sample"]))
                      for row in existing_rows) & expected
        if overlap:
            raise SystemExit(f"--carry-existing overlaps shard cases: {sorted(overlap)[:5]}")
        new_rows.sort(key=lambda row: manifest_order[
            case_key((row["network"], row["layer"], row["N"], row["sample"]))
        ])
        rows = existing_rows + new_rows
        expected |= existing_expected
        validate_rows(rows, expected, "union")
    else:
        existing_results_path = output_dir / "results.csv"
        if existing_results_path.is_file():
            existing_rows = read_shard(existing_results_path, run.FIELDS)
            existing_networks = {row["network"] for row in existing_rows}
            manifest_networks = {case[0] for case in expected}
            absent = sorted(existing_networks - manifest_networks)
            if absent:
                raise SystemExit(
                    "existing results contain networks absent from the shard manifest "
                    f"({', '.join(absent)}); rerun with --carry-existing"
                )

    if not args.carry_existing:
        rows.sort(key=lambda row: manifest_order[
            case_key((row["network"], row["layer"], row["N"], row["sample"]))
        ])
    summary = run.summarize(rows, layer_workloads, expected=expected)

    with (output_dir / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=run.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=run.SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary)
    print(f"Merged {len(rows)} cases from {manifest['num_shards']} shards")
    print(f"results={output_dir / 'results.csv'}")
    print(f"summary={output_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
