#!/usr/bin/env python3
"""Generate workload YAMLs for ResNet-19/34/50 and VGG-16, swept over T values.

Output hierarchy::

    configs/workloads/generated/
      <network>/
        T<t>/
          <layer>.yaml
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

# ---------------------------------------------------------------------------
# Sweep parameters
# ---------------------------------------------------------------------------

T_VALUES: List[int] = [4, 8, 16, 32, 64, 128]
DEFAULT_OUT_ROOT = "configs/workloads/generated"

# ---------------------------------------------------------------------------
# Layer-shape helpers
# ---------------------------------------------------------------------------

def _conv(cin: int, cout: int, ho: int, wo: int, kh: int = 3, kw: int = 3) -> Dict:
    return {"KH": kh, "KW": kw, "CIN": cin, "COUT": cout, "HO": ho, "WO": wo}


# ---------------------------------------------------------------------------
# ResNet-34  (ImageNet, basic blocks: 3-4-6-3)
# ---------------------------------------------------------------------------

def _resnet34_layers() -> Dict[str, Dict]:
    layers: Dict[str, Dict] = {}

    layers["conv1"] = _conv(3, 64, 112, 112, 7, 7)

    # stage1 — 3 basic blocks, 56×56, 64→64
    for b in range(1, 4):
        layers[f"stage1_block{b}_conv1"] = _conv(64, 64, 56, 56)
        layers[f"stage1_block{b}_conv2"] = _conv(64, 64, 56, 56)

    # stage2 — 4 basic blocks, 28×28, 64→128 / 128→128
    layers["stage2_block1_conv1"] = _conv(64, 128, 28, 28)
    layers["stage2_block1_conv2"] = _conv(128, 128, 28, 28)
    for b in range(2, 5):
        layers[f"stage2_block{b}_conv1"] = _conv(128, 128, 28, 28)
        layers[f"stage2_block{b}_conv2"] = _conv(128, 128, 28, 28)

    # stage3 — 6 basic blocks, 14×14, 128→256 / 256→256
    layers["stage3_block1_conv1"] = _conv(128, 256, 14, 14)
    layers["stage3_block1_conv2"] = _conv(256, 256, 14, 14)
    for b in range(2, 7):
        layers[f"stage3_block{b}_conv1"] = _conv(256, 256, 14, 14)
        layers[f"stage3_block{b}_conv2"] = _conv(256, 256, 14, 14)

    # stage4 — 3 basic blocks, 7×7, 256→512 / 512→512
    layers["stage4_block1_conv1"] = _conv(256, 512, 7, 7)
    layers["stage4_block1_conv2"] = _conv(512, 512, 7, 7)
    for b in range(2, 4):
        layers[f"stage4_block{b}_conv1"] = _conv(512, 512, 7, 7)
        layers[f"stage4_block{b}_conv2"] = _conv(512, 512, 7, 7)

    return layers


# ---------------------------------------------------------------------------
# ResNet-50  (ImageNet, bottleneck blocks: 3-4-6-3)
# ---------------------------------------------------------------------------

def _resnet50_layers() -> Dict[str, Dict]:
    layers: Dict[str, Dict] = {}

    layers["conv1"] = _conv(3, 64, 112, 112, 7, 7)

    # stage1 — 3 bottleneck blocks, 56×56
    #   block1: 64 → 64 → 64 → 256
    layers["stage1_block1_conv1"] = _conv(64, 64, 56, 56, 1, 1)
    layers["stage1_block1_conv2"] = _conv(64, 64, 56, 56, 3, 3)
    layers["stage1_block1_conv3"] = _conv(64, 256, 56, 56, 1, 1)
    #   block2-3: 256 → 64 → 64 → 256
    for b in range(2, 4):
        layers[f"stage1_block{b}_conv1"] = _conv(256, 64, 56, 56, 1, 1)
        layers[f"stage1_block{b}_conv2"] = _conv(64, 64, 56, 56, 3, 3)
        layers[f"stage1_block{b}_conv3"] = _conv(64, 256, 56, 56, 1, 1)

    # stage2 — 4 bottleneck blocks, 28×28
    #   block1: 256 → 128 → 128 → 512
    layers["stage2_block1_conv1"] = _conv(256, 128, 28, 28, 1, 1)
    layers["stage2_block1_conv2"] = _conv(128, 128, 28, 28, 3, 3)
    layers["stage2_block1_conv3"] = _conv(128, 512, 28, 28, 1, 1)
    #   block2-4: 512 → 128 → 128 → 512
    for b in range(2, 5):
        layers[f"stage2_block{b}_conv1"] = _conv(512, 128, 28, 28, 1, 1)
        layers[f"stage2_block{b}_conv2"] = _conv(128, 128, 28, 28, 3, 3)
        layers[f"stage2_block{b}_conv3"] = _conv(128, 512, 28, 28, 1, 1)

    # stage3 — 6 bottleneck blocks, 14×14
    #   block1: 512 → 256 → 256 → 1024
    layers["stage3_block1_conv1"] = _conv(512, 256, 14, 14, 1, 1)
    layers["stage3_block1_conv2"] = _conv(256, 256, 14, 14, 3, 3)
    layers["stage3_block1_conv3"] = _conv(256, 1024, 14, 14, 1, 1)
    #   block2-6: 1024 → 256 → 256 → 1024
    for b in range(2, 7):
        layers[f"stage3_block{b}_conv1"] = _conv(1024, 256, 14, 14, 1, 1)
        layers[f"stage3_block{b}_conv2"] = _conv(256, 256, 14, 14, 3, 3)
        layers[f"stage3_block{b}_conv3"] = _conv(256, 1024, 14, 14, 1, 1)

    # stage4 — 3 bottleneck blocks, 7×7
    #   block1: 1024 → 512 → 512 → 2048
    layers["stage4_block1_conv1"] = _conv(1024, 512, 7, 7, 1, 1)
    layers["stage4_block1_conv2"] = _conv(512, 512, 7, 7, 3, 3)
    layers["stage4_block1_conv3"] = _conv(512, 2048, 7, 7, 1, 1)
    #   block2-3: 2048 → 512 → 512 → 2048
    for b in range(2, 4):
        layers[f"stage4_block{b}_conv1"] = _conv(2048, 512, 7, 7, 1, 1)
        layers[f"stage4_block{b}_conv2"] = _conv(512, 512, 7, 7, 3, 3)
        layers[f"stage4_block{b}_conv3"] = _conv(512, 2048, 7, 7, 1, 1)

    return layers


# ---------------------------------------------------------------------------
# Load existing YAML-based networks (resnet19, vgg16)
# ---------------------------------------------------------------------------

def _load_existing_network(src_dir: Path) -> Dict[str, Dict]:
    """Load base layer dimensions from per-layer YAMLs, stripping T and shape."""
    layers: Dict[str, Dict] = {}
    for yaml_path in sorted(src_dir.glob("*.yaml")):
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        prob = dict(raw["problem"])
        prob.pop("T", None)
        prob.pop("shape", None)
        layers[yaml_path.stem] = prob
    return layers


# ---------------------------------------------------------------------------
# YAML writer
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, dims: Dict, t: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    problem = {**dims, "T": t, "shape": "snn-layer"}
    with open(path, "w") as f:
        yaml.safe_dump({"problem": problem}, f, sort_keys=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workload-root",
        default="configs/workloads",
        help="root containing hand-crafted per-network workload YAMLs",
    )
    parser.add_argument(
        "--out-root",
        default=DEFAULT_OUT_ROOT,
        help="root for generated workload YAMLs",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove and recreate --out-root before generating",
    )
    args = parser.parse_args()

    workload_root = Path(args.workload_root)
    out_root = Path(args.out_root)

    if args.clean and out_root.exists():
        shutil.rmtree(out_root)

    networks: List[Tuple[str, Dict[str, Dict]]] = [
        ("resnet19", _load_existing_network(workload_root / "resnet19")),
        ("resnet34", _resnet34_layers()),
        ("resnet50", _resnet50_layers()),
        ("vgg16",   _load_existing_network(workload_root / "vgg16")),
    ]

    total = 0
    for net_name, layers in networks:
        for t in T_VALUES:
            for layer_name, dims in layers.items():
                out_path = out_root / net_name / f"T{t}" / f"{layer_name}.yaml"
                _write_yaml(out_path, dims, t)
                total += 1
        layer_count = len(layers)
        print(f"{net_name}: {layer_count} layers × {len(T_VALUES)} T values = {layer_count * len(T_VALUES)} configs")

    print(f"\ntotal: {total} workload configs under {out_root}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
