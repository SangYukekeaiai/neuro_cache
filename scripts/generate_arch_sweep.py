#!/usr/bin/env python3
"""Generate architecture YAMLs sweeping PE count, L1 size, node count, and GB capacity."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, Iterable, Tuple

import yaml


PE_COUNTS = [16, 32, 64, 128]

L1_SIZES_KB = [4, 8, 16, 32]

NODE_COUNTS = [16, 32, 64, 128, 256, 512, 1024]

GB_SIZES_KB = [64, 128, 256, 512, 1024, 2048, 4096]

# Two bank-split options shared by both L1 and GB; must sum to TOTAL_BANKS.
BANK_SPLITS = [
    ("w30_p1_v1", {"weight": 30, "psum": 1, "vmem": 1}),
    ("w24_p4_v4", {"weight": 24, "psum": 4, "vmem": 4}),
]
TOTAL_BANKS = 32

DEFAULT_PE_REGISTER_ENTRIES = {"weight": 128, "psum": 128, "vmem": 256}
DEFAULT_PE_REGISTER_BITWIDTHS = {"weight": 8, "psum": 16, "vmem": 32}
DEFAULT_ARCH_BITWIDTHS = {"BW_WEIGHT": 8, "BW_PSUM": 16, "BW_VMEM": 32}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="configs/arch/sweep",
        help="directory where generated architecture YAMLs are written",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)

    count = 0
    for pe_count, l1_kb, node_count, gb_kb, (split_name, split) in _sweep_points():
        arch = _build_arch(pe_count, l1_kb, node_count, gb_kb, split)
        path = (
            out_dir
            / f"nodes_{node_count}"
            / f"gb_{gb_kb}kb"
            / f"l1_{l1_kb}kb"
            / f"pe_{pe_count}"
            / f"split_{split_name}.yaml"
        )
        _write_yaml(path, arch)
        count += 1

    print(f"generated {count} architecture configs under {out_dir}")
    return 0


def _sweep_points() -> Iterable[Tuple[int, int, int, int, Tuple[str, Dict[str, int]]]]:
    for pe_count in PE_COUNTS:
        for l1_kb in L1_SIZES_KB:
            for node_count in NODE_COUNTS:
                for gb_kb in GB_SIZES_KB:
                    for bank_split in BANK_SPLITS:
                        yield pe_count, l1_kb, node_count, gb_kb, bank_split


def _split_bytes(total_bytes: int, bank_split: Dict[str, int]) -> Dict[str, int]:
    if sum(bank_split.values()) != TOTAL_BANKS:
        raise ValueError(f"bank split must sum to {TOTAL_BANKS}: {bank_split}")
    return {
        var_name: total_bytes * banks // TOTAL_BANKS
        for var_name, banks in bank_split.items()
    }


def _build_arch(
    pe_count: int,
    l1_kb: int,
    node_count: int,
    gb_kb: int,
    bank_split: Dict[str, int],
) -> Dict:
    l1_bytes = l1_kb * 1024
    gb_bytes = gb_kb * 1024
    return {
        "arch": {
            "bitwidths": DEFAULT_ARCH_BITWIDTHS,
            "storage": [
                {
                    "name": "NodeLevel",
                    "instances": node_count,
                    "pe": {
                        "num_pes": pe_count,
                        "registers": {
                            "entries": DEFAULT_PE_REGISTER_ENTRIES,
                            "bitwidths": DEFAULT_PE_REGISTER_BITWIDTHS,
                        },
                    },
                    "local_buffer": {
                        "entries": _split_bytes(l1_bytes, bank_split),
                    },
                },
                {
                    "name": "NoCLevel",
                    "entries": _split_bytes(gb_bytes, bank_split),
                    "instances": 1,
                },
                {
                    "name": "OffChip",
                    "instances": 1,
                },
            ],
        }
    }


def _write_yaml(path: Path, content: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(content, f, sort_keys=False)


if __name__ == "__main__":
    raise SystemExit(main())
