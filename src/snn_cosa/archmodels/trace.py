"""Loads real captured spike traces and builds matching workload problem
dicts directly from their metadata.

input_trace/loas/<workload>/ holds one meta.json (layer name -> real
input-tensor shape [T, B, Cin, Hin, Win]) plus one <layer_name>.npy per
captured layer, binary float32. No such loader existed before this -- the
5 arch pilots' own verification scripts each called np.load ad hoc.

The pre-existing configs/workloads/generated/{vgg16,resnet19}/T4/*.yaml
workloads do NOT match these captured layers' real shapes (checked
directly: vgg16's generated YAMLs are ImageNet-scale 224x224/CIN-from-3,
while the captured trace is CIFAR-scale 32x32/CIN-from-64, matching the
source paper's own "VGG 9" figure caption, not full VGG16; resnet19's
generated YAMLs use a different channel-width base than the trace too).
build_workload_from_trace() replaces resolving against that directory --
it derives a fresh, trace-matching workload directly from meta.json.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

import numpy as np

KH = KW = 3  # blanket assumption, matching every archmodel's own
             # reconstruct_tile_sequence docstring: stride-1, no padding.


def load_layer_trace(trace_dir: pathlib.Path, layer_name: str) -> np.ndarray:
    """Load one captured layer's trace, e.g. trace_dir=input_trace/loas/vgg16_T4_B1.

    Args:
        trace_dir: directory containing meta.json + <layer_name>.npy.
        layer_name: e.g. "layer_01_features_3" (a meta.json "layers" key).

    Returns:
        Binary float32 array, shape [T, B, Cin, Hin, Win] (per meta.json).

    Raises:
        FileNotFoundError: if meta.json or the .npy file is missing.
        ValueError: if the loaded array's shape doesn't match meta.json.
    """
    trace_dir = pathlib.Path(trace_dir)
    meta_path = trace_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"load_layer_trace: no meta.json at {meta_path}")
    with open(meta_path) as fh:
        meta = json.load(fh)
    if layer_name not in meta["layers"]:
        raise ValueError(
            f"load_layer_trace: '{layer_name}' not in {meta_path}'s layers "
            f"(available: {sorted(meta['layers'])})"
        )
    npy_path = trace_dir / f"{layer_name}.npy"
    if not npy_path.exists():
        raise FileNotFoundError(f"load_layer_trace: no .npy at {npy_path}")
    trace = np.load(npy_path)
    expected_shape = tuple(meta["layers"][layer_name])
    if trace.shape != expected_shape:
        raise ValueError(
            f"load_layer_trace: {npy_path} has shape {trace.shape}, "
            f"meta.json declares {expected_shape}"
        )
    return trace


def valid_layer_names(meta: Dict[str, Any]) -> List[str]:
    """Return meta['layers'] keys whose Hin/Win support a KHxKW=3x3 no-pad
    receptive field (HO=Hin-2>=1, WO=Win-2>=1), in meta.json's own order.

    Excludes any layer too spatially small for this project's blanket
    convolution-shape assumption (e.g. vgg16_T4_B1's last 3 layers,
    Hin=Win=2) -- a real incompatibility, not a bug to work around.
    """
    names = []
    for name, (_t, _b, _cin, hin, win) in meta["layers"].items():
        if hin - (KH - 1) >= 1 and win - (KW - 1) >= 1:
            names.append(name)
    return names


def build_workload_from_trace(
    meta: Dict[str, Any], layer_name: str, next_cin: Optional[int] = None
) -> Dict[str, Any]:
    """Build a {"problem": {...}} dict for one captured layer, derived
    directly from meta.json -- KH=KW=3, stride-1, no padding.

    Args:
        meta:      the parsed meta.json dict.
        layer_name: e.g. "layer_01_features_3".
        next_cin:  the NEXT captured layer's CIN (this layer's real COUT,
                   since meta.json's "layers" dict is network-sequential --
                   layer i's output channels = layer i+1's input channels).
                   None (the last captured layer in a model) falls back to
                   reusing this layer's own CIN as COUT.

    Returns:
        {"problem": {"KH":3, "KW":3, "CIN":.., "COUT":.., "HO":.., "WO":..,
        "T":.., "shape": "snn-layer"}}, ready to write to a YAML file and
        pass to SNNProb.

    Raises:
        ValueError: if this layer's Hin/Win are too small for KH=KW=3
                    (use valid_layer_names() to filter these out first).
    """
    t, _b, cin, hin, win = meta["layers"][layer_name]
    ho, wo = hin - (KH - 1), win - (KW - 1)
    if ho < 1 or wo < 1:
        raise ValueError(
            f"build_workload_from_trace: '{layer_name}' has Hin={hin}/Win={win}, "
            f"too small for a {KH}x{KW} no-pad receptive field (HO={ho}, WO={wo})"
        )
    cout = next_cin if next_cin is not None else cin
    return {
        "problem": {
            "KH": KH, "KW": KW, "CIN": cin, "COUT": cout,
            "HO": ho, "WO": wo, "T": t, "shape": "snn-layer",
        }
    }