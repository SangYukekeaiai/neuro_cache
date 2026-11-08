#!/usr/bin/env python3
"""List incomplete cases and emit a smaller array manifest for rerunning them."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from harness import (
    DEFAULT_CASE_DIR,
    case_key,
    case_stem,
    campaign_modules,
    load_manifest,
    result_path,
    sbatch_command,
    split_cases,
    write_manifest,
)


FAILURE_MARKERS = ("ERROR:", "Traceback (most recent call last):", "Command failed")


def failed_log(shard_root, case):
    pattern = f"{case_stem(case)}_*.log"
    for path in sorted(Path(shard_root).glob(f"shard_*/logs/{pattern}")):
        text = path.read_text(errors="replace")
        if any(marker in text for marker in FAILURE_MARKERS):
            return path
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_CASE_DIR / "manifest.json")
    parser.add_argument("--shard-root", type=Path,
                        help="root containing completed shard directories")
    parser.add_argument("--output-dir", type=Path,
                        help="directory for the rerun manifest and case files")
    parser.add_argument("--new-shard-root", type=Path,
                        help="root for rerun outputs (default: sibling rerun-runs directory)")
    parser.add_argument("--num-shards", type=int, help="rerun array length, at most 250")
    parser.add_argument("--cases-per-shard", type=int,
                        help="maximum rerun cases per shard (default: original value)")
    parser.add_argument("--cpus", type=int, default=4)
    args = parser.parse_args()
    if args.cpus < 1:
        parser.error("--cpus must be positive")

    manifest, expected_cases = load_manifest(args.manifest)
    shard_root = args.shard_root or args.manifest.parent.parent / "runs"
    output_dir = args.output_dir or args.manifest.parent.parent / "rerun-cases"
    new_shard_root = args.new_shard_root or args.manifest.parent.parent / "rerun-runs"

    _, run = campaign_modules()
    counts = Counter()
    for index in range(manifest["num_shards"]):
        path = result_path(shard_root, index)
        if not path.is_file():
            continue
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != tuple(run.FIELDS):
                raise SystemExit(f"{path}: unexpected fields {reader.fieldnames}")
            for row in reader:
                counts[case_key((row["network"], row["layer"], row["N"], row["sample"]))] += 1

    rerun = []
    for case in expected_cases:
        count = counts[case_key(case)]
        if count == 1:
            continue
        log = failed_log(shard_root, case)
        if count == 0 and log is None:
            status = "missing"
        elif count == 0:
            status = f"failed ({log})"
        else:
            status = f"failed/duplicate ({count} rows)"
        print(f"{status}: {case}")
        rerun.append(case)

    if not rerun:
        print("No missing or failed cases; no rerun array emitted.")
        return

    cases_per_shard = args.cases_per_shard or manifest["cases_per_shard"]
    try:
        shards, num_shards, cases_per_shard = split_cases(
            rerun, num_shards=args.num_shards, cases_per_shard=cases_per_shard,
            preserve_groups=manifest.get("batch_samples", False),
        )
    except ValueError as exc:
        parser.error(str(exc))
    new_manifest = write_manifest(
        output_dir,
        rerun,
        shards,
        cases_per_shard,
        source=f"rerun from {args.manifest}",
        batch_samples=manifest.get("batch_samples", False),
    )
    new_shard_root.mkdir(parents=True, exist_ok=True)
    print(f"rerun_manifest={new_manifest}")
    print(f"sbatch={sbatch_command(output_dir, new_shard_root, num_shards, args.cpus, manifest.get('batch_samples', False))}")


if __name__ == "__main__":
    main()
