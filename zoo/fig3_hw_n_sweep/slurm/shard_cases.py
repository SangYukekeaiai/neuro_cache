#!/usr/bin/env python3
"""Create a deterministic case manifest and per-shard case files."""

from __future__ import annotations

import argparse
from pathlib import Path

from harness import DEFAULT_CASE_DIR, config_cases, sbatch_command, split_cases, write_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CASE_DIR,
                        help="directory for manifest.json and cases_XXXX.json")
    parser.add_argument("--num-shards", type=int, help="array length K (at most 250)")
    parser.add_argument("--cases-per-shard", type=int, help="maximum cases assigned to each shard")
    parser.add_argument("--limit", type=int, help="optional prefix limit for a small validation campaign")
    parser.add_argument("--network", help="restrict a validation manifest to one network")
    parser.add_argument("--hardware-size", type=int, action="append",
                        help="restrict cases to one or more hardware sizes")
    parser.add_argument("--layer", action="append", help="restrict cases to one or more layers")
    parser.add_argument("--cpus", type=int, default=4, help="cpus used in the printed sbatch command")
    parser.add_argument("--batch-samples", action="store_true",
                        help="keep each (layer, N) sample group together and batch generator work")
    parser.add_argument("--shard-root", type=Path,
                        help="root for per-shard outputs in the printed sbatch command")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.cpus < 1:
        parser.error("--cpus must be positive")

    cases = config_cases()
    if args.network:
        cases = [case for case in cases if case[0] == args.network]
    if args.hardware_size:
        cases = [case for case in cases if case[2] in args.hardware_size]
    if args.layer:
        cases = [case for case in cases if case[1] in args.layer]
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        parser.error("case filters selected no cases")
    try:
        shards, num_shards, cases_per_shard = split_cases(
            cases, num_shards=args.num_shards, cases_per_shard=args.cases_per_shard,
            preserve_groups=args.batch_samples,
        )
    except ValueError as exc:
        parser.error(str(exc))
    manifest = write_manifest(args.output_dir, cases, shards, cases_per_shard,
                              batch_samples=args.batch_samples)
    shard_root = args.shard_root or args.output_dir.parent / "runs"
    shard_root.mkdir(parents=True, exist_ok=True)
    print(f"manifest={manifest}")
    print(f"cases={len(cases)} shards={num_shards} cases_per_shard={cases_per_shard}")
    print(f"sbatch={sbatch_command(args.output_dir, shard_root, num_shards, args.cpus, args.batch_samples)}")


if __name__ == "__main__":
    main()
