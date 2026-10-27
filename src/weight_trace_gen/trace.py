"""Loads real captured spike traces and builds matching workload problem
dicts directly from their metadata.

input_trace/loas/<workload>/ holds one meta.json plus one <layer_name>.npy
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

KH = KW = 3   # every arch model's C++ replay walks 3x3 stride-1 windows
              # (e.g. src/weight_trace_gen/loas/LoASGen.h reads input row ho+kh-pad),
              # so valid_layer_names leaves out any other kernel or stride.
LAYER_PARAM_KEYS = ("cout", "kernel", "stride")
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
              multiprocessing workers -- see weight_trace_gen/cli.py.

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
    its kernel is not KHxKW=3x3 or its stride is not 1, or its Hin/Win give
    no output with PAD=1 (HO=Hin+2*PAD-KH+1<1, same for WO).

    Raises:
        ValueError: from layer_params(), if the layer's entry is incomplete.
    """
    p = layer_params(meta, layer_name)
    if p["kernel"] != KH or p["stride"] != 1:
        return (f"kernel {p['kernel']}x{p['kernel']}, stride {p['stride']}: "
                f"the arch models replay only {KH}x{KW} stride-1 convs")
    _t, _b, _cin, hin, win = meta["layers"][layer_name]
    if hin + 2 * PAD - (KH - 1) < 1 or win + 2 * PAD - (KW - 1) < 1:
        return f"Hin={hin}/Win={win} too small for a {KH}x{KW} conv with PAD={PAD}"
    return None


def valid_layer_names(meta: Dict[str, Any]) -> List[str]:
    """Return meta['layers'] keys the arch models can replay (exclusion_reason
    is None), in meta.json's own order."""
    return [name for name in meta["layers"] if exclusion_reason(meta, name) is None]


def build_workload_from_trace(meta: Dict[str, Any], layer_name: str) -> Dict[str, Any]:
    """Build a {"problem": {...}} dict for one captured layer, derived
    directly from meta.json -- KH=KW=3, stride-1, PAD=1 ("same" padding,
    the standard VGG/ResNet 3x3-conv convention -- HO=Hin, WO=Win exactly),
    COUT from meta["layer_params"].

    Args:
        meta:      the parsed meta.json dict.
        layer_name: e.g. "layer_01_features_3".

    Returns:
        {"problem": {"KH":3, "KW":3, "CIN":.., "COUT":.., "HO":.., "WO":..,
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
    ho, wo = hin + 2 * PAD - (KH - 1), win + 2 * PAD - (KW - 1)
    return {
        "problem": {
            "KH": KH, "KW": KW, "CIN": cin, "COUT": layer_params(meta, layer_name)["cout"],
            "HO": ho, "WO": wo, "T": t, "shape": "snn-layer",
        }
    }
