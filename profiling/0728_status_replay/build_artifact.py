#!/usr/bin/env python3
"""Build the self-contained 2026-07-28 cache-status artifact."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "artifact"


def read_rows(path: Path, default_layout: str) -> list[dict]:
    rows = []
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            rows.append(
                {
                    "workload": row["workload"],
                    "layer": row["layer"],
                    "cache_type": row["cache_type"],
                    "associativity": int(row["associativity"]),
                    "size_kb": int(row["size_bytes"]) // 1024,
                    "layout": row.get("layout", default_layout),
                    "line_size": int(row["line_size"]),
                    "hit_rate": float(row["mean_hit_rate"]),
                    "n": int(row["n_samples"]),
                }
            )
    return rows


def validate(rows: list[dict]) -> None:
    expected = 31 * 4 * 3 * 3
    if len(rows) != expected:
        raise ValueError(f"expected {expected} rows per layout, found {len(rows)}")
    keys = {
        (
            row["workload"],
            row["layer"],
            row["cache_type"],
            row["associativity"],
            row["size_kb"],
            row["line_size"],
        )
        for row in rows
    }
    if len(keys) != expected:
        raise ValueError("duplicate replay configurations")
    if {row["n"] for row in rows} != {5}:
        raise ValueError("artifact requires exactly five samples per row")
    if not all(0 <= row["hit_rate"] <= 1 for row in rows):
        raise ValueError("hit rate outside [0, 1]")


def main() -> None:
    cout = read_rows(ROOT / "loas_cout_only.csv", "cout_only")
    packed = read_rows(ROOT / "loas_cin_cout_2d.csv", "cin_cout_2d")
    validate(cout)
    validate(packed)
    OUT.mkdir(exist_ok=True)
    payload = {
        "generated": "2026-07-28",
        "rows": cout + packed,
    }
    (OUT / "data.js").write_text(
        "window.REPLAY_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    )
    print(f"wrote {OUT / 'data.js'} ({len(payload['rows'])} rows)")


if __name__ == "__main__":
    main()
