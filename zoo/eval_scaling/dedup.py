#!/usr/bin/env python3
"""S1b schedule identity check and representative case-list builder.

Scratchpad traces are deduplicated only when the canonical schedule identity
matches.  Cache traces may share that identity, but cache *simulation* points
are always retained in ``cases.txt`` because their cache capacities differ.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CONFIGS = HERE / "configs"
CAPTURE = "loas_vgg16_T4_n500"
ARCHES = ("spinalflow", "ptb", "loas", "prosperity", "gustavsnn")
SIDES = ("single", "multi")
MULTIPLIERS = (1, 2, 4)
SPAD_ARM = "spad_nocsim"
CACHE_ARM = "cache"


def point_name(arch: str, arm: str, side: str, multiplier: int) -> str:
    """Return the case-list point token used by run_case.py."""

    if arm == CACHE_ARM:
        if side != "multi":
            raise ValueError("cache points use the multi-node schedule")
        return f"{arch}_cache_x{multiplier}"
    return f"{arch}_{side}_x{multiplier}"


def canonical_payload(schedule: dict[str, Any]) -> dict[str, Any]:
    result = schedule.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("strategy"), dict):
        raise ValueError("schedule has no result.strategy")
    if "dram_num_steps" not in schedule:
        raise ValueError("schedule has no dram_num_steps")
    if "mode" not in schedule:
        raise ValueError("schedule has no mode")
    return {
        "strategy": result["strategy"],
        "dram_num_steps": schedule["dram_num_steps"],
        "mode": schedule["mode"],
    }


def canonical_key(schedule: dict[str, Any]) -> str:
    """Hash exactly the stable schedule identity, excluding path/bookkeeping fields."""

    encoded = json.dumps(canonical_payload(schedule), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schedule_dir(arch: str, side: str, multiplier: int) -> Path:
    return (
        OUT
        / "s1"
        / arch
        / f"{side}_x{multiplier}"
        / "schedules"
        / arch
        / CAPTURE
    )


def _axes() -> Iterable[tuple[str, str, int]]:
    manifest_path = CONFIGS / "sweep_config.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        points = manifest.get("points", [])
        seen = set()
        for point in points:
            key = (point["arch"], point["side"], int(point["multiplier"]))
            if key not in seen:
                seen.add(key)
                yield key
        if seen:
            return
    for arch in ARCHES:
        for side in SIDES:
            for multiplier in MULTIPLIERS:
                yield arch, side, multiplier


def _noc_product(strategy: dict[str, Any]) -> int:
    loops = (
        strategy.get("NoCLevel", {})
        .get("spatial_splitting", {})
        .get("loops", [])
    )
    product = 1
    for loop in loops:
        product *= int(loop["size"])
    return product


def _entry_id(entry: dict[str, Any]) -> str:
    return (
        f"{entry['arch']}|{entry['arm']}|{entry['side']}|"
        f"{entry['layer']}|x{entry['multiplier']}"
    )


def _load_schedule_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for arch, side, multiplier in _axes():
        directory = _schedule_dir(arch, side, multiplier)
        if not directory.is_dir():
            unavailable.append({
                "arch": arch,
                "side": side,
                "multiplier": multiplier,
                "reason": "schedule directory is missing",
            })
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                schedule = json.loads(path.read_text())
                key = canonical_key(schedule)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                unavailable.append({
                    "arch": arch,
                    "side": side,
                    "multiplier": multiplier,
                    "layer": path.stem,
                    "reason": str(exc),
                })
                continue
            records.append({
                "arch": arch,
                "side": side,
                "multiplier": multiplier,
                "layer": path.stem,
                "schedule_path": str(path),
                "canonical_key": key,
                "noc_product": _noc_product(schedule["result"]["strategy"]),
            })
    return records, unavailable


def build_dedup_map() -> dict[str, Any]:
    records, unavailable = _load_schedule_records()
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for arm in (SPAD_ARM, CACHE_ARM) if record["side"] == "multi" else (SPAD_ARM,):
            grouped[
                (
                    record["arch"],
                    arm,
                    record["side"],
                    record["layer"],
                    record["canonical_key"],
                )
            ].append(record)

    entries: list[dict[str, Any]] = []
    for group_key, group in sorted(grouped.items()):
        arch, arm, side, layer, _ = group_key
        ordered = sorted(group, key=lambda item: item["multiplier"])
        representative = ordered[0]
        for record in ordered:
            point = point_name(arch, arm, side, record["multiplier"])
            # A cache point is intentionally its own representative even when
            # its stream identity matches another capacity point.
            rep_record = record if arm == CACHE_ARM else representative
            rep_point = point_name(
                arch, arm, side, rep_record["multiplier"]
            )
            trace_point = point_name(
                arch, arm, side, representative["multiplier"]
            )
            entries.append({
                "arch": arch,
                "arm": arm,
                "side": side,
                "layer": layer,
                "multiplier": record["multiplier"],
                "point": point,
                "canonical_key": record["canonical_key"],
                "representative": rep_point,
                "representative_multiplier": rep_record["multiplier"],
                "deduped_from": rep_point if rep_point != point else None,
                # Cache simulation remains point-specific, but its stream can
                # use the smallest-multiplier schedule identity in this group.
                "trace_representative": trace_point,
                "trace_deduped_from": trace_point if trace_point != point else None,
                "schedule": record["schedule_path"],
                "noc_product": record["noc_product"],
            })

    mapping = {_entry_id(entry): entry["representative"] for entry in entries}
    representatives = [
        {
            "arch": entry["arch"],
            "arm": entry["arm"],
            "side": entry["side"],
            "layer": entry["layer"],
            "multiplier": entry["multiplier"],
            "point": entry["point"],
        }
        for entry in entries
        if entry["deduped_from"] is None
    ]
    return {
        "schema": 1,
        "capture": CAPTURE,
        "entries": entries,
        "mapping": mapping,
        "representatives": representatives,
        "unavailable": unavailable,
    }


def identity_entries(
    dedup_map: dict[str, Any], *, seed: int = 0
) -> list[dict[str, Any]]:
    """Select one skipped scratchpad point per architecture/side for the gate."""

    candidates = [
        entry
        for entry in dedup_map.get("entries", [])
        if entry.get("arm") != CACHE_ARM and entry.get("deduped_from")
    ]
    by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in candidates:
        by_pair[(entry["arch"], entry["side"])].append(entry)
    rng = random.Random(seed)
    return [
        rng.choice(sorted(by_pair[pair], key=lambda item: item["point"]))
        for pair in sorted(by_pair)
    ]


def write_outputs(dedup_map: dict[str, Any]) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    identity = identity_entries(dedup_map)
    identity_keys = {(entry["point"], entry["layer"]) for entry in identity}
    dedup_map["identity_cases"] = [
        {
            "arch": entry["arch"],
            "side": entry["side"],
            "point": entry["point"],
            "layer": entry["layer"],
            "representative": entry["representative"],
        }
        for entry in identity
    ]
    map_path = OUT / "dedup_map.json"
    map_path.write_text(json.dumps(dedup_map, indent=2) + "\n")

    cases: list[tuple[str, str]] = []
    for entry in dedup_map["entries"]:
        if (
            entry["arm"] == CACHE_ARM
            or entry["deduped_from"] is None
            or (entry["point"], entry["layer"]) in identity_keys
        ):
            cases.append((entry["point"], entry["layer"]))
    cases.sort()
    cases_path = OUT / "cases.txt"
    cases_path.write_text("".join(f"{point} {layer}\n" for point, layer in cases))
    (OUT / "identity_cases.txt").write_text(
        "".join(f"{entry['point']} {entry['layer']}\n" for entry in identity)
    )
    return map_path, cases_path


def _csv_rows(directory: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for path in sorted(directory.glob("*.csv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                point = row.get("point")
                layer = row.get("layer")
                if point and layer:
                    rows[(point, layer)].append(row)
    return rows


def assert_exact_identity(
    representative_rows: list[dict[str, str]],
    skipped_rows: list[dict[str, str]],
) -> None:
    """Assert exact per-sample equality for the dedup identity gate."""

    if not representative_rows or not skipped_rows:
        raise AssertionError("identity check needs non-empty representative and skipped rows")
    byte_columns = sorted(
        {
            key
            for row in representative_rows + skipped_rows
            for key in row
            if key.startswith("dram_bytes_")
        }
    )
    if not byte_columns:
        raise AssertionError("identity check has no dram_bytes_* columns")
    # Q11 is adopted for this campaign, so the second eventsim result is part
    # of the identity proof rather than an optional diagnostic.
    columns = ["total_cycles", "weight_makespan", *byte_columns]

    def index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        result = {}
        for row in rows:
            sample = row.get("sample", row.get("sample_idx"))
            if sample is None:
                raise AssertionError("identity row has no sample index")
            if sample in result:
                raise AssertionError(f"identity sample {sample} occurs more than once")
            result[sample] = row
        return result

    left = index(representative_rows)
    right = index(skipped_rows)
    if set(left) != set(right):
        raise AssertionError(f"identity sample sets differ: {set(left)} != {set(right)}")
    for sample in sorted(left, key=lambda value: str(value)):
        for column in columns:
            if column not in left[sample] or column not in right[sample]:
                raise AssertionError(
                    f"identity sample {sample} is missing required {column}"
                )
            if left[sample].get(column) != right[sample].get(column):
                raise AssertionError(
                    f"dedup identity mismatch at sample {sample}, {column}: "
                    f"{left[sample].get(column)!r} != {right[sample].get(column)!r}"
                )


def verify_identity_gate(
    dedup_map_path: Path = OUT / "dedup_map.json",
    s4_dir: Path = OUT / "s4",
    *,
    seed: int = 0,
) -> list[dict[str, str]]:
    """Check one real skipped-point result per (architecture, side).

    The skipped result must have been produced by re-running that point; this
    function never substitutes a representative row for a missing rerun.
    """

    dedup_map = json.loads(dedup_map_path.read_text())
    rows = _csv_rows(s4_dir)
    checked = []
    for entry in identity_entries(dedup_map, seed=seed):
        pair = (entry["arch"], entry["side"])
        rep_key = (entry["representative"], entry["layer"])
        target_key = (entry["point"], entry["layer"])
        if rep_key not in rows or target_key not in rows:
            raise AssertionError(
                f"identity gate needs real rows for {rep_key} and {target_key}"
            )
        assert_exact_identity(rows[rep_key], rows[target_key])
        checked.append({"arch": pair[0], "side": pair[1], "point": entry["point"]})
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-check", action="store_true")
    parser.add_argument("--dedup-map", type=Path, default=OUT / "dedup_map.json")
    parser.add_argument("--s4-dir", type=Path, default=OUT / "s4")
    args = parser.parse_args(argv)
    if args.identity_check:
        checked = verify_identity_gate(args.dedup_map, args.s4_dir)
        print(f"identity gate passed for {len(checked)} architecture/side pairs")
        return 0

    dedup_map = build_dedup_map()
    if not dedup_map["entries"]:
        raise RuntimeError("S1b found no schedules; refusing to write an empty case list")
    map_path, cases_path = write_outputs(dedup_map)
    geometry = {}
    for arch in ARCHES:
        entries = [e for e in dedup_map["entries"] if e["arch"] == arch and e["arm"] == SPAD_ARM]
        reps = [e for e in entries if e["deduped_from"] is None]
        print(f"{arch}: {len(entries)} scratchpad cases -> {len(reps)} representatives")
        multi = next(
            (e for e in dedup_map["entries"] if e["arch"] == arch and e["arm"] == SPAD_ARM and e["side"] == "multi"),
            None,
        )
        if multi is not None:
            geometry[arch] = multi["noc_product"]
            print(f"{arch}: first multi-node NoC spatial product = {multi['noc_product']}")
    missing_geometry = set(ARCHES) - set(geometry)
    if missing_geometry:
        raise RuntimeError(
            "cache geometry gate has no multi-node schedule for: "
            + ", ".join(sorted(missing_geometry))
        )
    invalid_geometry = {arch: product for arch, product in geometry.items() if product != 16}
    if invalid_geometry:
        raise RuntimeError(
            "cache geometry gate failed; expected 16 NoC-level spatial instances, "
            f"got {invalid_geometry}"
        )
    print(f"wrote {map_path} and {cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
