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

KH = KW = 3   # blanket assumption, matching every archmodel's own
              # reconstruct_tile_sequence docstring: stride-1 convolution.
PAD = 1       # "same" padding for a 3x3/stride-1 conv (the standard VGG/
              # ResNet convention) -- HO = Hin + 2*PAD - KH + 1 = Hin when
              # PAD=1, KH=3. PAD=0 ("valid" convolution, HO=Hin-2) was this
              # project's original assumption; changed to 1 by explicit
              # user direction (2026-07-16) since real VGG/ResNet 3x3 convs
              # use same-padding to preserve spatial resolution between
              # layers, not valid-padding.


def load_layer_trace(trace_dir: pathlib.Path, layer_name: str, mmap: bool = False) -> np.ndarray:
    """Load one captured layer's trace, e.g. trace_dir=input_trace/loas/vgg16_T4_B1.

    Args:
        trace_dir: directory containing meta.json + <layer_name>.npy.
        layer_name: e.g. "layer_01_features_3" (a meta.json "layers" key).
        mmap: memory-map the .npy instead of reading it fully into RAM.
              The "_all" trace variants (B=10000) are multi-GB; reconstruction
              only ever needs a handful of (t, batch, cin, hin, win) slices
              per tile, not the whole array resident at once. A memmap'd
              array also pickles cheaply (by file/offset/shape, not by
              copying its contents), which matters for handing it to
              multiprocessing workers -- see generate_weight_traces.py.

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
    trace = np.load(npy_path, mmap_mode="r" if mmap else None)
    expected_shape = tuple(meta["layers"][layer_name])
    if trace.shape != expected_shape:
        raise ValueError(
            f"load_layer_trace: {npy_path} has shape {trace.shape}, "
            f"meta.json declares {expected_shape}"
        )
    return trace


def valid_layer_names(meta: Dict[str, Any]) -> List[str]:
    """Return meta['layers'] keys whose Hin/Win support a KHxKW=3x3,
    PAD=1 receptive field (HO=Hin+2*PAD-KH+1>=1, same for WO), in
    meta.json's own order.

    With PAD=1 ("same" padding, HO=Hin exactly for a 3x3/stride-1 conv),
    this is vacuous in practice for this project's real captured layers
    (every Hin/Win>=1 already gives HO/WO>=1) -- kept as a real check
    rather than assumed, since a future differently-shaped capture could
    still violate it, and past behavior with PAD=0 did exclude 3 real
    vgg16 layers on exactly this condition.
    """
    names = []
    for name, (_t, _b, _cin, hin, win) in meta["layers"].items():
        ho = hin + 2 * PAD - (KH - 1)
        wo = win + 2 * PAD - (KW - 1)
        if ho >= 1 and wo >= 1:
            names.append(name)
    return names


def build_workload_from_trace(
    meta: Dict[str, Any], layer_name: str, next_cin: Optional[int] = None
) -> Dict[str, Any]:
    """Build a {"problem": {...}} dict for one captured layer, derived
    directly from meta.json -- KH=KW=3, stride-1, PAD=1 ("same" padding,
    the standard VGG/ResNet 3x3-conv convention -- HO=Hin, WO=Win exactly).

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
        ValueError: if this layer's Hin/Win are too small for KH=KW=3 even
                    with PAD=1 (use valid_layer_names() to filter these
                    out first -- vacuous in practice for real captures).
    """
    t, _b, cin, hin, win = meta["layers"][layer_name]
    ho, wo = hin + 2 * PAD - (KH - 1), win + 2 * PAD - (KW - 1)
    if ho < 1 or wo < 1:
        raise ValueError(
            f"build_workload_from_trace: '{layer_name}' has Hin={hin}/Win={win}, "
            f"too small for a {KH}x{KW} receptive field even with PAD={PAD} "
            f"(HO={ho}, WO={wo})"
        )
    cout = next_cin if next_cin is not None else cin
    return {
        "problem": {
            "KH": KH, "KW": KW, "CIN": cin, "COUT": cout,
            "HO": ho, "WO": wo, "T": t, "shape": "snn-layer",
        }
    }