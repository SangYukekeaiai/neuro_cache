#!/usr/bin/env python3
"""Canonical workload definitions for SNN CoSA profiling sweeps.

Provides the full set of conv-layer shapes drawn from five networks
(ResNet-19, VGG-16, ResNet-34, ResNet-50, DeepBench GEMM), deduplicated
by shape tuple, and expanded across T_VALUES.

Public API:
    build_unique_workloads(workload_root)  →  List[(wl_key, wl_dict)]
    shape_key(dims)                        →  str
    T_VALUES                               →  [4, 32, 128]
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import yaml


T_VALUES: List[int] = [4, 32, 128]


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------

def shape_key(dims: Dict) -> str:
    """Canonical string key from a dims dict — used as file/result name."""
    return (
        f"cin{dims['CIN']}_cout{dims['COUT']}"
        f"_ho{dims['HO']}_wo{dims['WO']}"
        f"_kh{dims['KH']}_kw{dims['KW']}"
    )


def _conv(cin: int, cout: int, ho: int, wo: int, kh: int = 3, kw: int = 3) -> Dict:
    return {"KH": kh, "KW": kw, "CIN": cin, "COUT": cout, "HO": ho, "WO": wo}


def _dedup_key(dims: Dict) -> tuple:
    return (dims["KH"], dims["KW"], dims["CIN"], dims["COUT"], dims["HO"], dims["WO"])


# ---------------------------------------------------------------------------
# Network layer generators
# ---------------------------------------------------------------------------

def _resnet19_layers(workload_root: Path) -> Dict[str, Dict]:
    root = workload_root / "resnet19"
    layers: Dict[str, Dict] = {}
    for yp in sorted(root.glob("*.yaml")):
        with open(yp) as f:
            raw = yaml.safe_load(f)
        prob = raw["problem"]
        layers[yp.stem] = {k: v for k, v in prob.items() if k not in ("T", "shape")}
    return layers


def _vgg16_layers(workload_root: Path) -> Dict[str, Dict]:
    root = workload_root / "vgg16"
    layers: Dict[str, Dict] = {}
    for yp in sorted(root.glob("*.yaml")):
        if "T128" in yp.stem:
            continue
        with open(yp) as f:
            raw = yaml.safe_load(f)
        prob = raw["problem"]
        layers[yp.stem] = {k: v for k, v in prob.items() if k not in ("T", "shape")}
    return layers


def _resnet34_layers() -> Dict[str, Dict]:
    layers: Dict[str, Dict] = {}
    layers["conv1"] = _conv(3, 64, 112, 112, 7, 7)
    for b in range(1, 4):
        layers[f"stage1_block{b}_conv1"] = _conv(64, 64, 56, 56)
        layers[f"stage1_block{b}_conv2"] = _conv(64, 64, 56, 56)
    layers["stage2_block1_conv1"] = _conv(64, 128, 28, 28)
    layers["stage2_block1_conv2"] = _conv(128, 128, 28, 28)
    for b in range(2, 5):
        layers[f"stage2_block{b}_conv1"] = _conv(128, 128, 28, 28)
        layers[f"stage2_block{b}_conv2"] = _conv(128, 128, 28, 28)
    layers["stage3_block1_conv1"] = _conv(128, 256, 14, 14)
    layers["stage3_block1_conv2"] = _conv(256, 256, 14, 14)
    for b in range(2, 7):
        layers[f"stage3_block{b}_conv1"] = _conv(256, 256, 14, 14)
        layers[f"stage3_block{b}_conv2"] = _conv(256, 256, 14, 14)
    layers["stage4_block1_conv1"] = _conv(256, 512, 7, 7)
    layers["stage4_block1_conv2"] = _conv(512, 512, 7, 7)
    for b in range(2, 4):
        layers[f"stage4_block{b}_conv1"] = _conv(512, 512, 7, 7)
        layers[f"stage4_block{b}_conv2"] = _conv(512, 512, 7, 7)
    return layers


def _resnet50_layers() -> Dict[str, Dict]:
    layers: Dict[str, Dict] = {}
    layers["conv1"] = _conv(3, 64, 112, 112, 7, 7)
    layers["stage1_block1_conv1"] = _conv(64, 64, 56, 56, 1, 1)
    layers["stage1_block1_conv2"] = _conv(64, 64, 56, 56, 3, 3)
    layers["stage1_block1_conv3"] = _conv(64, 256, 56, 56, 1, 1)
    for b in range(2, 4):
        layers[f"stage1_block{b}_conv1"] = _conv(256, 64, 56, 56, 1, 1)
        layers[f"stage1_block{b}_conv2"] = _conv(64, 64, 56, 56, 3, 3)
        layers[f"stage1_block{b}_conv3"] = _conv(64, 256, 56, 56, 1, 1)
    layers["stage2_block1_conv1"] = _conv(256, 128, 28, 28, 1, 1)
    layers["stage2_block1_conv2"] = _conv(128, 128, 28, 28, 3, 3)
    layers["stage2_block1_conv3"] = _conv(128, 512, 28, 28, 1, 1)
    for b in range(2, 5):
        layers[f"stage2_block{b}_conv1"] = _conv(512, 128, 28, 28, 1, 1)
        layers[f"stage2_block{b}_conv2"] = _conv(128, 128, 28, 28, 3, 3)
        layers[f"stage2_block{b}_conv3"] = _conv(128, 512, 28, 28, 1, 1)
    layers["stage3_block1_conv1"] = _conv(512, 256, 14, 14, 1, 1)
    layers["stage3_block1_conv2"] = _conv(256, 256, 14, 14, 3, 3)
    layers["stage3_block1_conv3"] = _conv(256, 1024, 14, 14, 1, 1)
    for b in range(2, 7):
        layers[f"stage3_block{b}_conv1"] = _conv(1024, 256, 14, 14, 1, 1)
        layers[f"stage3_block{b}_conv2"] = _conv(256, 256, 14, 14, 3, 3)
        layers[f"stage3_block{b}_conv3"] = _conv(256, 1024, 14, 14, 1, 1)
    layers["stage4_block1_conv1"] = _conv(1024, 512, 7, 7, 1, 1)
    layers["stage4_block1_conv2"] = _conv(512, 512, 7, 7, 3, 3)
    layers["stage4_block1_conv3"] = _conv(512, 2048, 7, 7, 1, 1)
    for b in range(2, 4):
        layers[f"stage4_block{b}_conv1"] = _conv(2048, 512, 7, 7, 1, 1)
        layers[f"stage4_block{b}_conv2"] = _conv(512, 512, 7, 7, 3, 3)
        layers[f"stage4_block{b}_conv3"] = _conv(512, 2048, 7, 7, 1, 1)
    return layers


def _gemm_layers() -> Dict[str, Dict]:
    """DeepBench GEMM workloads as 1×1 conv (KH=KW=1, HO=WO=1).

    Mapping: COUT=M (output features), CIN=K (reduction dim).
    Source: github.com/baidu-research/DeepBench — gemm_problems.h
    Excludes embedding/recommendation workloads (CIN=500000).
    """
    def _fc(cin: int, cout: int) -> Dict:
        return {"KH": 1, "KW": 1, "CIN": cin, "COUT": cout, "HO": 1, "WO": 1}

    return {
        # Square RNN hidden layers
        "rnn_square_1760":     _fc(1760, 1760),
        "rnn_square_2560":     _fc(2560, 2560),
        "fc_square_4096":      _fc(4096, 4096),
        # LSTM 4-gate projections (COUT = 4 × hidden_size)
        "lstm_gate_7680_2560": _fc(2560, 7680),
        "lstm_gate_3072_1024": _fc(1024, 3072),
        "lstm_gate_6144_2048": _fc(2048, 6144),
        # ASR / speech recognition output
        "asr_output_5124":     _fc(2048, 5124),
        "asr_vocab_35":        _fc(2048, 35),
        # Inference-device LSTM gate layers (small input, large gate)
        "device_lstm_4224":    _fc(176, 4224),
        "device_lstm_3072":    _fc(128, 3072),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_unique_workloads(workload_root: Path) -> List[Tuple[str, Dict]]:
    """Return (wl_key, wl_dict) for all unique shapes × T_VALUES.

    Deduplicates layers from resnet19, vgg16, resnet34, resnet50, and the
    DeepBench GEMM set by shape tuple (KH, KW, CIN, COUT, HO, WO).
    Each unique shape is expanded across T_VALUES = [4, 32, 128].

    Args:
        workload_root: Path to configs/workloads/ (for YAML-backed networks).

    Returns:
        List of (wl_key, wl_dict) where wl_key is the canonical shape_key
        suffixed with _T{t}, and wl_dict includes all dims + T + shape fields.
    """
    seen: Dict[tuple, bool] = {}
    unique_dims: List[Dict] = []

    networks = [
        _resnet19_layers(workload_root),
        _vgg16_layers(workload_root),
        _resnet34_layers(),
        _resnet50_layers(),
        _gemm_layers(),
    ]
    for layers in networks:
        for dims in layers.values():
            dk = _dedup_key(dims)
            if dk not in seen:
                seen[dk] = True
                unique_dims.append(dims)

    workloads: List[Tuple[str, Dict]] = []
    for dims in unique_dims:
        base_key = shape_key(dims)
        for t in T_VALUES:
            wl_dict = {**dims, "T": t, "shape": "snn-layer"}
            workloads.append((f"{base_key}_T{t}", wl_dict))

    return workloads


__all__ = ["T_VALUES", "shape_key", "build_unique_workloads"]
