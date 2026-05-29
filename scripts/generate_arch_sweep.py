#!/usr/bin/env python3
"""Generate architecture YAMLs for node-count, GB-capacity, and bank splits."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, Tuple

import yaml


NODE_COUNTS = [16, 128, 160, 576, 1024, 4096]
GB_CAPACITIES = [
    ("64KB", 64 * 1024),
    ("128KB", 128 * 1024),
    ("256KB", 256 * 1024),
    ("1024KB", 1024 * 1024),
    ("2MB", 2 * 1024 * 1024),
    ("4MB", 4 * 1024 * 1024),
]
BANK_SPLITS = [
    ("w30_p1_v1", {"weight": 30, "psum": 1, "vmem": 1}),
    ("w28_p2_v2", {"weight": 28, "psum": 2, "vmem": 2}),
    ("w26_p3_v3", {"weight": 26, "psum": 3, "vmem": 3}),
    ("w24_p4_v4", {"weight": 24, "psum": 4, "vmem": 4}),
]
TOTAL_BANKS = 32

DEFAULT_PE_REGISTER_ENTRIES = {"weight": 128, "psum": 128, "vmem": 256}
DEFAULT_PE_REGISTER_BITWIDTHS = {"weight": 8, "psum": 16, "vmem": 32}
DEFAULT_LOCAL_BUFFER_ENTRIES = {"weight": 1024, "psum": 1024, "vmem": 2048}
DEFAULT_ARCH_BITWIDTHS = {
    "BW_WEIGHT": 8,
    "BW_PSUM": 16,
    "BW_VMEM": 32,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="configs/arch/sweep",
        help="directory where generated architecture YAMLs are written",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    count = 0
    for node_count, (gb_label, gb_bytes), (split_name, split) in _sweep_points():
        arch = _build_arch(node_count, gb_bytes, split)
        path = (
            out_dir
            / f"nodes_{node_count}"
            / f"gb_{gb_label.lower()}"
            / f"split_{split_name}.yaml"
        )
        _write_yaml(path, arch)
        count += 1

    print(f"generated {count} architecture configs under {out_dir}")
    return 0


def _sweep_points() -> Iterable[Tuple[int, Tuple[str, int], Tuple[str, Dict[str, int]]]]:
    for node_count in NODE_COUNTS:
        for gb_capacity in GB_CAPACITIES:
            for bank_split in BANK_SPLITS:
                yield node_count, gb_capacity, bank_split


def _build_arch(
    node_count: int,
    gb_bytes: int,
    bank_split: Dict[str, int],
) -> Dict:
    return {
        "arch": {
            "bitwidths": DEFAULT_ARCH_BITWIDTHS,
            "storage": [
                {
                    "name": "NodeLevel",
                    "instances": node_count,
                    "pe": {
                        "num_pes": node_count,
                        "registers": {
                            "entries": DEFAULT_PE_REGISTER_ENTRIES,
                            "bitwidths": DEFAULT_PE_REGISTER_BITWIDTHS,
                        },
                    },
                    "local_buffer": {
                        "entries": DEFAULT_LOCAL_BUFFER_ENTRIES,
                    },
                },
                {
                    "name": "NoCLevel",
                    "entries": _split_gb_capacity(gb_bytes, bank_split),
                    "instances": 1,
                },
                {
                    "name": "OffChip",
                    "instances": 1,
                },
            ],
        }
    }


def _split_gb_capacity(gb_bytes: int, bank_split: Dict[str, int]) -> Dict[str, int]:
    if sum(bank_split.values()) != TOTAL_BANKS:
        raise ValueError(f"bank split must sum to {TOTAL_BANKS}: {bank_split}")
    return {
        var_name: gb_bytes * banks // TOTAL_BANKS
        for var_name, banks in bank_split.items()
    }


def _write_yaml(path: Path, content: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(content, f, sort_keys=False)


if __name__ == "__main__":
    raise SystemExit(main())
