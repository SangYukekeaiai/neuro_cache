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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_CASE_DIR / "manifest.json")
    parser.add_argument("--shard-root", type=Path,
                        help="root containing shard_XXXX/results_XXXX.csv")
    parser.add_argument("--output-dir", type=Path,
                        help="directory for merged results.csv and summary.csv")
    args = parser.parse_args()

    manifest, expected_cases = load_manifest(args.manifest)
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

    expected = set(expected_cases)
    observed = [case_key((row["network"], row["layer"], row["N"], row["sample"])) for row in rows]
    counts = Counter(observed)
    duplicates = sorted((key, count) for key, count in counts.items() if count != 1)
    missing = sorted(expected - counts.keys())
    extra = sorted(counts.keys() - expected)
    if duplicates or missing or extra:
        raise SystemExit(
            "shard coverage validation failed: "
            f"duplicates={duplicates[:5]} missing={missing[:5]} extra={extra[:5]}"
        )
    if len(rows) != len(expected):
        raise SystemExit(f"shard coverage validation failed: {len(rows)} rows for {len(expected)} cases")

    order = {case: index for index, case in enumerate(expected_cases)}
    rows.sort(key=lambda row: order[case_key((row["network"], row["layer"], row["N"], row["sample"]))])
    layer_workloads = run.workloads()
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
