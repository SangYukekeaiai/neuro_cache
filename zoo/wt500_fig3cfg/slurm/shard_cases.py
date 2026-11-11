#!/usr/bin/env python3
"""Freeze wt500 sample cases and split them into Slurm array shards."""

from __future__ import annotations

import argparse
import pathlib

from harness import (
    ARCH_ORDER,
    DEFAULT_CAMPAIGN_MANIFEST,
    DEFAULT_CASE_DIR,
    SAMPLE_COUNT,
    SAMPLE_START,
    SAMPLES,
    campaign_combo_records,
    sbatch_command,
    split_cases,
    write_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=pathlib.Path, default=DEFAULT_CAMPAIGN_MANIFEST,
                        help="gen_inputs.py's frozen schedule/feasibility manifest")
    parser.add_argument("--output-dir", type=pathlib.Path, default=DEFAULT_CASE_DIR,
                        help="directory for manifest.json and cases_XXXX.json")
    parser.add_argument("--shard-root", type=pathlib.Path,
                        help="root for per-shard outputs in the printed sbatch command")
    parser.add_argument("--num-shards", type=int, default=250,
                        help="array length upper bound (at most 250; default: 250)")
    parser.add_argument("--cases-per-shard", type=int,
                        help="maximum cases per shard; defaults to a capacity for --num-shards")
    parser.add_argument("--combo-limit", type=int, help="optional prefix limit on combo groups")
    parser.add_argument("--limit", type=int, help="optional prefix limit on individual sample cases")
    parser.add_argument("--arch", action="append", choices=ARCH_ORDER,
                        help="restrict to one or more architectures")
    parser.add_argument("--trace-dir", action="append", help="restrict to one or more trace directories")
    parser.add_argument("--layer", action="append", help="restrict to one or more layer names")
    parser.add_argument("--cpus", type=int, default=4, help="cpus used in the printed sbatch command")
    parser.add_argument("--trace-root", type=pathlib.Path,
                        help="input trace root passed to run_array.sbatch")
    parser.add_argument("--schedule-cache", type=pathlib.Path,
                        help="schedule cache root passed to run_array.sbatch")
    parser.add_argument("--repo", type=pathlib.Path,
                        help="repository root passed to run_array.sbatch")
    parser.add_argument("--python", help="Python executable passed to run_array.sbatch")
    args = parser.parse_args()
    if args.cpus < 1:
        parser.error("--cpus must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.combo_limit is not None and args.combo_limit < 1:
        parser.error("--combo-limit must be positive")

    try:
        combo_records = campaign_combo_records(args.campaign_manifest, args.arch)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.trace_dir:
        wanted = set(args.trace_dir)
        combo_records = [combo for combo in combo_records if combo["trace_dir"] in wanted]
    if args.layer:
        wanted = set(args.layer)
        combo_records = [combo for combo in combo_records if combo["layer"] in wanted]
    if args.combo_limit is not None:
        combo_records = combo_records[:args.combo_limit]
    if not combo_records:
        parser.error("filters selected no feasible (arch, trace_dir, layer) groups")

    cases = [
        {**record, "sample": sample}
        for record in combo_records for sample in SAMPLES
    ]
    if args.limit is not None:
        cases = cases[:args.limit]
    try:
        shards, num_shards, cases_per_shard = split_cases(
            cases, num_shards=args.num_shards, cases_per_shard=args.cases_per_shard,
            preserve_groups=True,
        )
    except ValueError as exc:
        parser.error(str(exc))
    combo_keys = [(record["arch"], record["trace_dir"], record["layer"])
                  for record in combo_records]
    manifest = write_manifest(args.output_dir, cases, shards, cases_per_shard,
                              source=str(args.campaign_manifest), combos=combo_keys)
    shard_root = args.shard_root or args.output_dir.parent / "runs"
    shard_root.mkdir(parents=True, exist_ok=True)
    print(f"manifest={manifest}")
    print(f"sample_range={SAMPLE_START}:{SAMPLE_START + SAMPLE_COUNT} ({SAMPLE_COUNT} samples)")
    print(f"combos={len(combo_records)} cases={len(cases)} shards={num_shards} cases_per_shard={cases_per_shard}")
    sbatch_line = sbatch_command(args.output_dir, shard_root, num_shards, args.cpus,
                                 args.trace_root, args.schedule_cache, args.repo, args.python)
    print(f"sbatch={sbatch_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
