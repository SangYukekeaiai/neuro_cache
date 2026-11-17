#!/usr/bin/env python3
"""Re-harvest FN-CACTI for the four cache geometries changed by RQ4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


KIT = Path(__file__).resolve().parent
GEOMETRIES = {
    "l2_262144": {"level": "l2", "size_bytes": 262144, "assoc": 16},
    "l2_1048576": {"level": "l2", "size_bytes": 1048576, "assoc": 16},
    "l1_8192": {"level": "l1", "size_bytes": 8192, "assoc": 8},
    "l1_32768": {"level": "l1", "size_bytes": 32768, "assoc": 8},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(partial, path)


def harvest_one(repo: Path, output_dir: Path, name: str, geometry: dict[str, Any]) -> dict[str, Any]:
    sys.path[:0] = [str(repo / "zoo/archx/zoo"), str(repo / "zoo/archx/src"), str(repo / "src")]
    from archx.interface.cacti_fn.cacti_fn import query

    output_dir.mkdir(parents=True, exist_ok=True)
    query_value = {
        "interface": "cacti_fn", "class": "cache",
        "size": geometry["size_bytes"] * 8, "width": 512,
        "associativity": geometry["assoc"], "bank": 1,
        "technology": 7, "frequency": 500,
    }
    result = query(name, "cacti_fn", query_value, output_dir=str(output_dir))
    return {
        "name": name, **geometry, "query": query_value,
        "dynamic_energy_read_nJ": result["dynamic_energy"]["read"]["value"],
        "dynamic_energy_write_nJ": result["dynamic_energy"]["write"]["value"],
        "leakage_power_mW": result["leakage_power"]["value"],
        "area_mm2": result["area"]["value"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pilot", action="store_true", help="harvest only the L1 8 KiB pilot")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).expanduser().read_text())
    repo = Path(manifest["repo"])
    output_root = Path(manifest["output_root"])
    result_path = output_root / "cacti" / "harvest.json"
    if result_path.exists() and not args.force:
        prior = json.loads(result_path.read_text())
        needed = {"l1_8192"} if args.pilot else set(GEOMETRIES)
        if prior.get("status") == "complete" and needed <= set(prior.get("geometries", {})):
            print(f"CACTI harvest already complete: {result_path}")
            return
    names = ["l1_8192"] if args.pilot else list(GEOMETRIES)
    output_dir = output_root / "cacti" / "reports"
    geometries = {}
    for name in names:
        geometries[name] = harvest_one(repo, output_dir, name, GEOMETRIES[name])
    previous = {}
    if result_path.exists():
        previous = json.loads(result_path.read_text()).get("geometries", {})
    previous.update(geometries)
    save(result_path, {
        "schema": "stokes_cache_dse_cacti/v1", "status": "complete",
        "mode": "pilot" if args.pilot and len(previous) == 1 else "full",
        "geometries": previous,
        "source": "archx.interface.cacti_fn.cacti_fn.query",
    })
    print(json.dumps({"harvest": str(result_path), "geometries": sorted(previous)}, sort_keys=True))


if __name__ == "__main__":
    main()
