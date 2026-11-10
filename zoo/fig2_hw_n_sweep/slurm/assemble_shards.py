#!/usr/bin/env python3
"""Assemble complete campaign shards from one or more recorded array rounds.

Each source manifest identifies a shard by its exact case set, so rerun shard
indices do not need to match the original array indices. Duplicate source
results must agree; the first source listed supplies the assembled files.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from pathlib import Path
import shlex
import shutil
import sys

from harness import case_key, load_case_file, load_manifest, result_path, shard_tag


def _resolved(path):
    return Path(path).expanduser().resolve()


def _manifest_shards(path):
    path = _resolved(path)
    payload, expected_cases = load_manifest(path)
    expected = Counter(case_key(case) for case in expected_cases)
    entries = []
    observed = Counter()
    for shard in payload["shards"]:
        index = int(shard["index"])
        cases = load_case_file(path.parent / shard["case_file"])
        if len(cases) != int(shard["cases"]):
            raise ValueError(f"{path}: shard {index} case count is inconsistent")
        case_counts = Counter(case_key(case) for case in cases)
        if any(count != 1 for count in case_counts.values()):
            raise ValueError(f"{path}: shard {index} contains duplicate cases")
        observed.update(case_counts)
        entries.append({
            "index": index,
            "cases": tuple(cases),
            "case_set": frozenset(case_counts),
        })
    if observed != expected:
        raise ValueError(f"{path}: shard case files do not cover the manifest exactly")
    return payload, entries


def _result_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_result(path, expected_cases):
    rows = _result_rows(path)
    observed = Counter(case_key((row["network"], row["layer"], row["N"], row["sample"]))
                      for row in rows)
    expected = Counter(expected_cases)
    if observed != expected:
        raise ValueError(f"{path}: result cases do not match its manifest shard")


def _result_signature(path):
    rows = _result_rows(path)
    return tuple(sorted(tuple(sorted(row.items())) for row in rows))


def _copy_support_files(source_dir, target_dir):
    """Copy diagnostics while leaving source-specific result/log names aside."""
    for source in sorted(source_dir.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_dir)
        if relative == Path("slurm.log"):
            continue
        if relative.parent == Path(".") and relative.name.startswith("results_"):
            continue
        if relative.parts and relative.parts[0] == "logs" and relative.name.startswith("commands_"):
            continue
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="complete target manifest whose shard indices define the output")
    parser.add_argument("--source", type=Path, nargs=2, action="append", required=True,
                        metavar=("MANIFEST", "SHARD_ROOT"),
                        help="source manifest and its shard root; repeat for each array/rerun round")
    parser.add_argument("--output-root", type=Path, required=True,
                        help="new root for assembled shard_XXXX directories")
    args = parser.parse_args()

    target_manifest = _resolved(args.manifest)
    output_root = _resolved(args.output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty assembly root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    target_payload, target_shards = _manifest_shards(target_manifest)
    sources = []
    for manifest_arg, root_arg in args.source:
        source_manifest = _resolved(manifest_arg)
        source_root = _resolved(root_arg)
        payload, shards = _manifest_shards(source_manifest)
        by_case_set = {}
        for shard in shards:
            if shard["case_set"] in by_case_set:
                raise ValueError(f"{source_manifest}: duplicate shard case set")
            by_case_set[shard["case_set"]] = shard
        sources.append({
            "manifest": source_manifest,
            "root": source_root,
            "payload": payload,
            "shards": by_case_set,
        })

    assembled = []
    for target in target_shards:
        candidates = []
        for source in sources:
            source_shard = source["shards"].get(target["case_set"])
            if source_shard is None:
                continue
            source_result = result_path(source["root"], source_shard["index"])
            if not source_result.is_file():
                continue
            _validate_result(source_result, target["case_set"])
            candidates.append((source, source_shard, source_result))
        if not candidates:
            raise SystemExit(f"no complete source shard for target {target['index']}")

        selected = candidates[0]
        selected_signature = _result_signature(selected[2])
        for candidate in candidates[1:]:
            if _result_signature(candidate[2]) != selected_signature:
                raise SystemExit(
                    f"conflicting rerun results for target shard {target['index']}: "
                    f"{selected[2]} vs {candidate[2]}"
                )

        target_tag = shard_tag(target["index"])
        target_dir = output_root / f"shard_{target_tag}"
        target_dir.mkdir(parents=True, exist_ok=True)
        source_dir = selected[2].parent
        _copy_support_files(source_dir, target_dir)
        shutil.copy2(selected[2], target_dir / f"results_{target_tag}.csv")

        command_logs = sorted((source_dir / "logs").glob("commands_*.txt"))
        if not command_logs:
            raise SystemExit(f"missing command log for source shard: {source_dir}")
        command_dir = target_dir / "logs"
        command_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(command_logs[0], command_dir / f"commands_{target_tag}.txt")

        assembled.append({
            "target_shard": target["index"],
            "cases": len(target["case_set"]),
            "selected_source": {
                "manifest": str(selected[0]["manifest"]),
                "shard_root": str(selected[0]["root"]),
                "shard": selected[1]["index"],
            },
            "equivalent_sources": [
                {
                    "manifest": str(source["manifest"]),
                    "shard_root": str(source["root"]),
                    "shard": shard["index"],
                }
                for source, shard, _ in candidates
            ],
        })

    metadata = {
        "format": 1,
        "command": shlex.join(sys.argv),
        "target_manifest": str(target_manifest),
        "target_shards": int(target_payload["num_shards"]),
        "output_root": str(output_root),
        "sources": [
            {
                "manifest": str(source["manifest"]),
                "shard_root": str(source["root"]),
                "shards": int(source["payload"]["num_shards"]),
            }
            for source in sources
        ],
        "assembled": assembled,
    }
    (output_root / "assembly.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Assembled {len(assembled)} shards from {len(sources)} source roots")
    print(f"assembly={output_root / 'assembly.json'}")


if __name__ == "__main__":
    main()
