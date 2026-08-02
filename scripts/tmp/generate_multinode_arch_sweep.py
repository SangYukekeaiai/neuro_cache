#!/usr/bin/env python3
"""Generate the NodeLevel.instances x NodeLevel-size x NoCLevel-size
multi-node arch YAML sweep, for all 5 archs.

Per log/2026-07-30-tracegen-refactor-and-multinode-sweep-plan.md Part B.1
(sizes per 2026-07-30 follow-up: swept, not fixed):
  - NodeLevel.instances swept over INSTANCE_COUNTS, for every arch.
  - NodeLevel.entries (weight/psum/vmem) sized in a fixed 30:1:1 ratio,
    total swept over NODE_TOTAL_BYTES_OPTIONS (2/4/8/16/32 KiB) -- the
    32 KiB top end is a rounding of the Timeloop "Eyeriss-like reference"
    per-PE scratchpad total (4KB weight + 8KB input + 2KB psum = 14KB --
    survey-output/dnn-noc-buffer-sizes/phase6_report/report.md's own
    words: "the single most-used benchmark geometry in the
    hardware-mapping research community").
  - NoCLevel.entries, same 30:1:1 ratio, total swept over
    NOC_TOTAL_BYTES_OPTIONS (512 KiB/1/2/4 MiB) -- the 1 MiB point matches
    both this repo's existing 128-node baseline fixtures and MAESTRO's
    canonical L2 shared-buffer reference from the same survey.
  - num_pes and bitwidths are read from each arch's existing
    configs/arch/<arch>_multinode.yaml (the 128-instance baseline) rather
    than re-hardcoded here, so this sweep never silently drifts from that
    single source of truth.

Output: configs/arch/multinode_sweep/<arch>_inst<N>_node<X>kb_noc<Y>kb.yaml
(a new subdirectory, not configs/arch/ itself, so the sweep's files don't
mix in with the single 128-node baseline file each arch already has).
5 archs x 4 instance counts x 5 node sizes x 4 noc sizes = 400 files.

This only writes config files -- no solving. Run scripts/tmp/
sweep_multinode_arch_sweep.py separately (and only after reviewing what
this generates) to actually run the schedules through the solver.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ARCHS = ("loas", "spinalflow", "ptb", "gustavsnn", "prosperity")
INSTANCE_COUNTS = (16, 64, 256, 1024)
RATIO = {"weight": 30, "psum": 1, "vmem": 1}  # parts, must sum to a power of 2

KB = 1024
MB = 1024 * KB
NODE_TOTAL_BYTES_OPTIONS = (2 * KB, 4 * KB, 8 * KB, 16 * KB, 32 * KB)
NOC_TOTAL_BYTES_OPTIONS = (512 * KB, 1 * MB, 2 * MB, 4 * MB)

BASELINE_DIR = REPO_ROOT / "configs" / "arch"
OUT_DIR = REPO_ROOT / "configs" / "arch" / "multinode_sweep"


def _split(total_bytes: int) -> dict:
    parts = sum(RATIO.values())
    if total_bytes % parts != 0:
        raise ValueError(f"{total_bytes} bytes doesn't split evenly into ratio parts={parts}")
    unit = total_bytes // parts
    return {tensor: unit * share for tensor, share in RATIO.items()}


def load_baseline(arch: str) -> dict:
    path = BASELINE_DIR / f"{arch}_multinode.yaml"
    with open(path) as fh:
        return yaml.safe_load(fh)


def build_variant(baseline: dict, instances: int, node_total: int, noc_total: int) -> dict:
    node_level = next(lvl for lvl in baseline["arch"]["storage"] if lvl["name"] == "NodeLevel")
    return {
        "arch": {
            "bitwidths": baseline["arch"]["bitwidths"],
            "single_node": False,
            "storage": [
                {
                    "name": "NodeLevel",
                    "instances": instances,
                    "pe": {"num_pes": node_level["pe"]["num_pes"]},
                    "local_buffer": {"entries": _split(node_total)},
                },
                {
                    "name": "NoCLevel",
                    "entries": _split(noc_total),
                    "instances": 1,
                },
                {"name": "OffChip", "instances": 1},
            ],
        }
    }


def _size_tag(n: int) -> str:
    return f"{n // KB}kb"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for arch in ARCHS:
        baseline = load_baseline(arch)
        num_pes = next(lvl for lvl in baseline["arch"]["storage"] if lvl["name"] == "NodeLevel")["pe"]["num_pes"]
        for instances in INSTANCE_COUNTS:
            for node_total in NODE_TOTAL_BYTES_OPTIONS:
                for noc_total in NOC_TOTAL_BYTES_OPTIONS:
                    variant = build_variant(baseline, instances, node_total, noc_total)
                    out_path = (
                        OUT_DIR
                        / f"{arch}_inst{instances}_node{_size_tag(node_total)}_noc{_size_tag(noc_total)}.yaml"
                    )
                    with open(out_path, "w") as fh:
                        yaml.safe_dump(variant, fh, sort_keys=False)
                    rows.append((arch, instances, num_pes, node_total, noc_total, out_path))

    print(f"{len(ARCHS)} archs x {len(INSTANCE_COUNTS)} instance counts x "
          f"{len(NODE_TOTAL_BYTES_OPTIONS)} node sizes x {len(NOC_TOTAL_BYTES_OPTIONS)} noc sizes "
          f"= {len(rows)} arch YAML(s)")
    print(f"instance counts: {INSTANCE_COUNTS}")
    print(f"node sizes (bytes, 30:1:1 split): {NODE_TOTAL_BYTES_OPTIONS}")
    print(f"noc sizes (bytes, 30:1:1 split):  {NOC_TOTAL_BYTES_OPTIONS}")
    print(f"\nWrote {len(rows)} arch YAML(s) to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
