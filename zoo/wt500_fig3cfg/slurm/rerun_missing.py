#!/usr/bin/env python3
"""Find incomplete wt500 outputs and emit a replacement array manifest."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import pathlib

from harness import (
    DEFAULT_CASE_DIR,
    RESULT_FIELDS,
    case_key,
    case_stem,
    combo_key,
    load_manifest,
    result_path,
    sbatch_command,
    split_cases,
    validate_result_row,
    write_manifest,
)


def _read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RESULT_FIELDS:
            raise ValueError(f"{path}: expected fields {RESULT_FIELDS}, got {reader.fieldnames}")
        return list(reader)


def _failed_log(shard_root: pathlib.Path, case: tuple[str, str, str, int]) -> pathlib.Path | None:
    stem = case_stem(case)
    for path in sorted(pathlib.Path(shard_root).glob(f"shard_*/logs/{stem}_*.log")):
        if path.is_file():
            text = path.read_text(errors="replace").lower()
            if "failed" in text or "traceback" in text or "error" in text:
                return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_CASE_DIR / "manifest.json")
    parser.add_argument("--shard-root", type=pathlib.Path,
                        help="root containing the completed shard_XXXX directories")
    parser.add_argument("--output-dir", type=pathlib.Path,
                        help="directory for the rerun manifest and case files")
    parser.add_argument("--new-shard-root", type=pathlib.Path,
                        help="root for rerun outputs (default: sibling rerun-runs)")
    parser.add_argument("--num-shards", type=int, help="rerun array length, at most 250")
    parser.add_argument("--cases-per-shard", type=int,
                        help="maximum rerun cases per shard (default: original value)")
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--trace-root", type=pathlib.Path,
                        help="input trace root for the emitted sbatch command")
    parser.add_argument("--schedule-cache", type=pathlib.Path,
                        help="schedule cache root for the emitted sbatch command")
    parser.add_argument("--repo", type=pathlib.Path,
                        help="repository root for the emitted sbatch command")
    parser.add_argument("--python", help="Python executable for the emitted sbatch command")
    args = parser.parse_args()
    if args.cpus < 1:
        parser.error("--cpus must be positive")

    manifest, expected_cases = load_manifest(args.manifest)
    expected_set = {case_key(case) for case in expected_cases}
    shard_root = args.shard_root or args.manifest.parent.parent / "runs"
    output_dir = args.output_dir or args.manifest.parent.parent / "rerun-cases"
    new_shard_root = args.new_shard_root or args.manifest.parent.parent / "rerun-runs"

    observed: Counter[tuple[str, str, str, int]] = Counter()
    valid: Counter[tuple[str, str, str, int]] = Counter()
    for index in range(manifest["num_shards"]):
        path = result_path(shard_root, index)
        if not path.is_file():
            continue
        shard_dir = path.parent
        for row in _read_rows(path):
            key = case_key(row)
            if key not in expected_set:
                raise SystemExit(f"{path}: result case is not in the manifest: {key}")
            observed[key] += 1
            try:
                validate_result_row(row, shard_dir, key)
            except ValueError:
                continue
            valid[key] += 1

    rerun = []
    for case in expected_cases:
        key = case_key(case)
        if observed[key] == 1 and valid[key] == 1:
            continue
        log = _failed_log(shard_root, case)
        if observed[key] == 0 and log is None:
            status = "missing"
        elif observed[key] == 0:
            status = f"failed ({log})"
        else:
            status = f"failed/duplicate ({observed[key]} rows)"
        print(f"{status}: {case}")
        rerun.append(case)

    if not rerun:
        print("No missing or failed cases; no rerun array emitted.")
        return 0

    cases_per_shard = args.cases_per_shard or manifest["cases_per_shard"]
    try:
        shards, num_shards, cases_per_shard = split_cases(
            rerun, num_shards=args.num_shards, cases_per_shard=cases_per_shard,
            preserve_groups=True,
        )
    except ValueError as exc:
        parser.error(str(exc))
    combos = []
    seen = set()
    for case in rerun:
        combo = combo_key(case)
        if combo not in seen:
            seen.add(combo)
            combos.append(combo)
    new_manifest = write_manifest(
        output_dir, rerun, shards, cases_per_shard,
        source=f"rerun from {args.manifest}", combos=combos,
    )
    pathlib.Path(new_shard_root).mkdir(parents=True, exist_ok=True)
    print(f"rerun_manifest={new_manifest}")
    print(f"sbatch={sbatch_command(output_dir, new_shard_root, num_shards, args.cpus,
                                  args.trace_root, args.schedule_cache, args.repo, args.python)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
