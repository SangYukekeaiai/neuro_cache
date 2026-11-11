#!/usr/bin/env python3
"""Run the exact once-only coverage check and merge shard result rows."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
import pathlib

from harness import (
    DEFAULT_CASE_DIR,
    RESULT_FIELDS,
    case_key,
    load_case_file,
    load_manifest,
    output_relpaths,
    result_path,
    validate_result_row,
)


def _read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RESULT_FIELDS:
            raise SystemExit(f"{path}: expected fields {RESULT_FIELDS}, got {reader.fieldnames}")
        return list(reader)


def _actual_outputs(shard_dir: pathlib.Path, subdir: str, suffix: str) -> set[str]:
    root = shard_dir / subdir
    if not root.exists():
        return set()
    return {path.relative_to(shard_dir).as_posix()
            for path in root.rglob(f"*{suffix}") if path.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_CASE_DIR / "manifest.json")
    parser.add_argument("--shard-root", type=pathlib.Path,
                        help="root containing shard_XXXX/results_XXXX.csv")
    parser.add_argument("--output-dir", type=pathlib.Path,
                        help="directory for results.csv and coverage.json")
    args = parser.parse_args()

    manifest, manifest_cases = load_manifest(args.manifest)
    shard_root = args.shard_root or args.manifest.parent.parent / "runs"
    output_dir = args.output_dir or args.manifest.parent.parent / "merged"
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = set(case_key(case) for case in manifest_cases)
    rows = []

    shards_by_index = {int(shard["index"]): shard for shard in manifest["shards"]}
    for index in range(manifest["num_shards"]):
        path = result_path(shard_root, index)
        if not path.is_file():
            raise SystemExit(f"missing shard result: {path}")
        shard_dir = path.parent
        case_file = args.manifest.parent / shards_by_index[index]["case_file"]
        shard_cases = [case_key(case) for case in load_case_file(case_file)]
        shard_expected = set(shard_cases)
        shard_rows = _read_rows(path)
        observed = Counter(case_key(row) for row in shard_rows)
        if set(observed) != shard_expected or any(count != 1 for count in observed.values()):
            raise SystemExit(
                f"{path} coverage failed: rows={len(shard_rows)} expected={len(shard_expected)} "
                f"duplicates={[key for key, count in observed.items() if count != 1][:3]} "
                f"missing={sorted(shard_expected - set(observed))[:3]}"
            )
        for row in shard_rows:
            try:
                validate_result_row(row, shard_dir, case_key(row))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        cycle_expected = {output_relpaths(case)[0].as_posix() for case in shard_cases}
        wcts_expected = {output_relpaths(case)[1].as_posix() for case in shard_cases}
        cycle_actual = _actual_outputs(shard_dir, "step_cycles", ".json.gz")
        wcts_actual = _actual_outputs(shard_dir, "wcts", ".wcts.gz")
        if cycle_actual != cycle_expected or wcts_actual != wcts_expected:
            raise SystemExit(
                f"{path} output coverage failed: cycles missing={sorted(cycle_expected-cycle_actual)[:3]} "
                f"extra={sorted(cycle_actual-cycle_expected)[:3]} "
                f"wcts missing={sorted(wcts_expected-wcts_actual)[:3]} "
                f"extra={sorted(wcts_actual-wcts_expected)[:3]}"
            )
        rows.extend(shard_rows)

    counts = Counter(case_key(row) for row in rows)
    duplicates = sorted((key, count) for key, count in counts.items() if count != 1)
    missing = sorted(expected - counts.keys())
    extra = sorted(counts.keys() - expected)
    if duplicates or missing or extra or len(rows) != len(expected):
        raise SystemExit(
            f"exact coverage failed: rows={len(rows)} expected={len(expected)} "
            f"duplicates={duplicates[:3]} missing={missing[:3]} extra={extra[:3]}"
        )

    order = {case_key(case): index for index, case in enumerate(manifest_cases)}
    rows.sort(key=lambda row: order[case_key(row)])
    results_path = output_dir / "results.csv"
    with results_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    coverage = {
        "format": 1,
        "manifest": str(args.manifest.resolve()),
        "shard_root": str(pathlib.Path(shard_root).resolve()),
        "sample_start": manifest.get("sample_start", 0),
        "sample_count": manifest.get("sample_count", 500),
        "cases": len(rows),
        "step_cycles": len(rows),
        "wcts": len(rows),
        "exact_once": True,
    }
    coverage_path = output_dir / "coverage.json"
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"Exact coverage: {len(rows)}/{len(expected)} cases; step-cycles={len(rows)} WCTS={len(rows)}")
    print(f"results={results_path}")
    print(f"coverage={coverage_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
