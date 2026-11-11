"""Loads real captured spike traces and builds matching workload problem
dicts directly from their metadata.

examples/input_trace/loas/<workload>/ holds one meta.json plus one <layer_name>.npy
per captured layer, binary uint8 (0/1 spikes). meta.json's "layers" maps
layer name -> real input-tensor shape [T, B, Cin, Hin, Win]; its
"layer_params" maps the same names -> {"cout", "kernel", "stride"} of that
captured conv (output channels, square kernel size, stride). No such loader existed before
this -- the 5 arch pilots' own verification scripts each called np.load ad hoc.

Generic per-network workload YAMLs do NOT match these captured layers'
real shapes: the captured vgg16 trace is CIFAR-scale 32x32/CIN-from-64,
matching the source paper's own "VGG 9" figure caption, not ImageNet-scale
224x224/CIN-from-3 VGG16. build_workload_from_trace() therefore derives a
trace-matching workload directly from meta.json.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

import numpy as np

# Native replay infers same-padding as (kernel - 1) // 2 from each tile.
KERNEL_PADDING = {1: 0, 3: 1}
LAYER_PARAM_KEYS = ("cout", "kernel", "stride")


def load_layer_trace(trace_dir: pathlib.Path, layer_name: str, mmap: bool = False) -> np.ndarray:
    """Load one captured layer's trace, e.g. trace_dir=examples/input_trace/loas/vgg16_T4_B1.

    Args:
        trace_dir: directory containing meta.json + <layer_name>.npy.
        layer_name: e.g. "layer_01_features_3" (a meta.json "layers" key).
        mmap: memory-map the .npy instead of reading it fully into RAM. The
              "_all" trace variants (B=10000) can be multi-GB; callers that
              need lazy access can retain this mode. The single-combo
              generation CLI uses mmap=False and reads one complete layer (up
              to about 1.95 GiB in the campaign) in the parent before forking
              workers, so that read-only array is shared copy-on-write instead
              of copied per worker. Its all-layers tasks use the same
              sequential read mode for each layer.

    Returns:
        Binary uint8 array, shape [T, B, Cin, Hin, Win] (per meta.json).

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


def layer_params(meta: Dict[str, Any], layer_name: str) -> Dict[str, int]:
    """meta["layer_params"][layer_name]: {"cout", "kernel", "stride"} of that
    captured conv.

    Raises:
        ValueError: if meta["layer_params"] is not a dict, the entry is
                    missing, or any of the three is not a positive int.
    """
    all_params = meta.get("layer_params", {})
    if not isinstance(all_params, dict):
        raise ValueError(f"layer_params is {type(all_params).__name__}, want a dict "
                         f"(layer name -> {{cout, kernel, stride}})")
    p = all_params.get(layer_name)
    bad = [k for k in LAYER_PARAM_KEYS
           if not (isinstance(p, dict) and isinstance(p.get(k), int)
                   and not isinstance(p[k], bool) and p[k] > 0)]
    if bad:
        raise ValueError(
            f"layer_params[{layer_name!r}] = {p!r} lacks a positive int "
            f"{', '.join(bad)} (meta.json needs cout, kernel and stride for every layer)"
        )
    return p


def exclusion_reason(meta: Dict[str, Any], layer_name: str) -> Optional[str]:
    """Why the arch models cannot replay this layer, or None when they can:
    supported kernels are 1x1 (PAD=0) and 3x3 (PAD=1), with stride 1
    and positive output spatial dimensions.

    Raises:
        ValueError: from layer_params(), if the layer's entry is incomplete.
    """
    p = layer_params(meta, layer_name)
    kernel = p["kernel"]
    if kernel not in KERNEL_PADDING or p["stride"] != 1:
        return (f"kernel {p['kernel']}x{p['kernel']}, stride {p['stride']}: "
                "the arch models replay only 1x1 or 3x3 stride-1 layers")
    pad = KERNEL_PADDING[kernel]
    _t, _b, _cin, hin, win = meta["layers"][layer_name]
    if hin + 2 * pad - (kernel - 1) < 1 or win + 2 * pad - (kernel - 1) < 1:
        return f"Hin={hin}/Win={win} too small for a {kernel}x{kernel} layer with PAD={pad}"
    return None


def valid_layer_names(meta: Dict[str, Any]) -> List[str]:
    """Return meta['layers'] keys the arch models can replay (exclusion_reason
    is None), in meta.json's own order."""
    return [name for name in meta["layers"] if exclusion_reason(meta, name) is None]


def build_workload_from_trace(meta: Dict[str, Any], layer_name: str) -> Dict[str, Any]:
    """Build a {"problem": {...}} dict for one captured layer, derived
    directly from meta.json. Stride-1 kernels use PAD=0 for 1x1 or PAD=1
    for 3x3, so HO=Hin and WO=Win. Captured GEMMs have Cin=K, Hin=M,
    Win=1 and cout=N; pointwise convolutions retain both spatial dimensions.
    Padding is implicit in native replay, not an extra workload dimension.

    Args:
        meta:      the parsed meta.json dict.
        layer_name: e.g. "layer_01_features_3".

    Returns:
        {"problem": {"KH":kernel, "KW":kernel, "CIN":.., "COUT":.., "HO":.., "WO":..,
        "T":.., "shape": "snn-layer"}}, ready to write to a YAML file and
        pass to SNNProb.

    Raises:
        ValueError: if the layer's layer_params entry is incomplete, or the
                    layer is excluded (exclusion_reason; use
                    valid_layer_names() to filter these out first).
    """
    reason = exclusion_reason(meta, layer_name)
    if reason is not None:
        raise ValueError(f"build_workload_from_trace: '{layer_name}' is excluded: {reason}")
    t, _b, cin, hin, win = meta["layers"][layer_name]
    p = layer_params(meta, layer_name)
    kernel = p["kernel"]
    pad = KERNEL_PADDING[kernel]
    ho, wo = hin + 2 * pad - (kernel - 1), win + 2 * pad - (kernel - 1)
    return {
        "problem": {
            "KH": kernel, "KW": kernel, "CIN": cin, "COUT": p["cout"],
            "HO": ho, "WO": wo, "T": t, "shape": "snn-layer",
        }
    }
