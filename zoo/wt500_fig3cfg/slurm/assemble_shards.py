#!/usr/bin/env python3
"""Assemble complete target shards from initial and rerun array rounds."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import gzip
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import sys

from harness import (
    RESULT_FIELDS,
    case_key,
    load_case_file,
    load_manifest,
    result_path,
    shard_tag,
    validate_result_row,
)


def _resolved(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(path).expanduser().resolve()


def _read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RESULT_FIELDS:
            raise ValueError(f"{path}: expected fields {RESULT_FIELDS}, got {reader.fieldnames}")
        return list(reader)


def _manifest_shards(path: pathlib.Path) -> tuple[dict, list[dict]]:
    path = _resolved(path)
    payload, expected_cases = load_manifest(path)
    expected = Counter(case_key(case) for case in expected_cases)
    entries = []
    observed = Counter()
    by_index = {}
    for shard in payload["shards"]:
        index = int(shard["index"])
        if index in by_index:
            raise ValueError(f"{path}: duplicate shard index {index}")
        cases = load_case_file(path.parent / shard["case_file"])
        if len(cases) != int(shard["cases"]):
            raise ValueError(f"{path}: shard {index} case count is inconsistent")
        case_counts = Counter(case_key(case) for case in cases)
        if any(count != 1 for count in case_counts.values()):
            raise ValueError(f"{path}: shard {index} contains duplicate cases")
        observed.update(case_counts)
        entry = {"index": index, "cases": tuple(cases), "case_set": frozenset(case_counts)}
        entries.append(entry)
        by_index[index] = entry
    if observed != expected:
        raise ValueError(f"{path}: shard case files do not cover the manifest exactly")
    return payload, entries


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows_equal(first: tuple[pathlib.Path, dict], second: tuple[pathlib.Path, dict]) -> bool:
    first_dir, first_row = first
    second_dir, second_row = second
    return all(_file_hash(first_dir / first_row[field]) == _file_hash(second_dir / second_row[field])
               for field in ("step_cycles", "wcts"))


def _collect_source_rows(manifest_path: pathlib.Path, root: pathlib.Path) -> dict:
    _, shards = _manifest_shards(manifest_path)
    expected = {case_key(case) for shard in shards for case in shard["cases"]}
    rows_by_case = {}
    for shard in shards:
        source_result = result_path(root, shard["index"])
        if not source_result.is_file():
            continue
        source_dir = source_result.parent
        for row in _read_rows(source_result):
            key = case_key(row)
            if key not in expected:
                raise ValueError(f"{source_result}: result case is outside its manifest: {key}")
            try:
                validate_result_row(row, source_dir, key)
            except ValueError:
                # A source round may contain a row written immediately before
                # a later output was lost or a task was interrupted.  The
                # complete row from another round can still repair it.
                continue
            if key in rows_by_case:
                raise ValueError(f"duplicate case within source round {manifest_path}: {key}")
            rows_by_case[key] = (source_dir, row)
    return rows_by_case


def _copy_case(source_dir: pathlib.Path, source_row: dict, target_dir: pathlib.Path) -> None:
    for field in ("step_cycles", "wcts"):
        source = source_dir / source_row[field]
        destination = target_dir / source_row[field]
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            # WCTS is the dominant campaign storage cost.  The source and
            # assembled roots are expected to share Stokes' filesystem, so a
            # hardlink gives the canonical tree without a second full copy.
            os.link(source, destination)
        except OSError as exc:
            raise SystemExit(
                f"cannot hardlink {source} into {destination}; keep source and "
                "assembled roots on the same filesystem to avoid duplicating WCTS"
            ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True,
                        help="complete target manifest whose shard indices define the output")
    parser.add_argument("--source", type=pathlib.Path, nargs=2, action="append", required=True,
                        metavar=("MANIFEST", "SHARD_ROOT"),
                        help="source manifest and shard root; repeat for initial/rerun rounds")
    parser.add_argument("--output-root", type=pathlib.Path, required=True,
                        help="new root for assembled shard_XXXX directories")
    args = parser.parse_args()

    target_manifest = _resolved(args.manifest)
    output_root = _resolved(args.output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty assembly root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    target_payload, target_shards = _manifest_shards(target_manifest)

    source_rounds = []
    for manifest_arg, root_arg in args.source:
        source_manifest = _resolved(manifest_arg)
        source_root = _resolved(root_arg)
        source_payload, _ = _manifest_shards(source_manifest)
        source_rounds.append({"manifest": source_manifest, "root": source_root,
                              "payload": source_payload,
                              "rows": _collect_source_rows(source_manifest, source_root)})

    all_source_cases = {}
    for source in source_rounds:
        for key, value in source["rows"].items():
            all_source_cases.setdefault(key, []).append(value)

    assembled = []
    for target in target_shards:
        target_dir = output_root / f"shard_{shard_tag(target['index'])}"
        target_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for case in target["cases"]:
            key = case_key(case)
            candidates = all_source_cases.get(key, [])
            if not candidates:
                raise SystemExit(f"no complete source result for target case {key}")
            selected = candidates[0]
            if any(not _rows_equal(selected, candidate) for candidate in candidates[1:]):
                raise SystemExit(f"conflicting rerun outputs for target case {key}")
            _copy_case(selected[0], selected[1], target_dir)
            rows.append(selected[1])
        order = {case_key(case): index for index, case in enumerate(target["cases"])}
        rows.sort(key=lambda row: order[case_key(row)])
        result_file = target_dir / f"results_{shard_tag(target['index'])}.csv"
        with result_file.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        log_dir = target_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        command_logs = []
        for source in source_rounds:
            for source_dir in sorted({value[0] for value in source["rows"].values()}, key=str):
                command_logs.extend(sorted(source_dir.glob("logs/commands_*.txt")))
        if command_logs:
            shutil.copy2(command_logs[0], log_dir / f"commands_{shard_tag(target['index'])}.txt")
        assembled.append({"target_shard": target["index"], "cases": len(rows)})

    metadata = {
        "format": 1,
        "command": shlex.join(sys.argv),
        "target_manifest": str(target_manifest),
        "target_shards": int(target_payload["num_shards"]),
        "output_root": str(output_root),
        "sources": [{"manifest": str(source["manifest"]), "shard_root": str(source["root"]),
                     "shards": int(source["payload"]["num_shards"])} for source in source_rounds],
        "assembled": assembled,
    }
    (output_root / "assembly.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Assembled {len(assembled)} shards from {len(source_rounds)} source roots")
    print(f"assembly={output_root / 'assembly.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
