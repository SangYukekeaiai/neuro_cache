#!/usr/bin/env python3
"""Load weight-access trace files and build the ordered access stream.

Real traces live at:
    <TRACE_ROOT>/<arch>/<network>/<layer>/sample_NNNNN.json.gz

Each file's `tiles` are pre-segmented by `dram_i`. Concatenating tiles in file
order (which the sanity check confirms is `dram_i` order), then within-tile
order, yields the ordered stream the locality analysis consumes (plan Sec 1.1):

    a[t] = (kh, kw, cin, cout_start, cout_end)

The active output-channel range is `cr = (cout_start, cout_end)`; its width is
`cout_end - cout_start`. Width depends on BOTH arch and layer
(`width(arch, layer) = min(nominal_width(arch), COUT(layer))`, plan Sec 1.1),
so analysis code always reads it from the trace and never caches a per-arch
value. `NOMINAL_WIDTH` below exists only so the sanity check can verify that
clamping rule holds; it is not used by the analysis path.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

TRACE_ROOT = Path(
    "/projects/bebv/yyu9/neuro_cache_outputs/weight_traces_100demo_snapshot"
)

ARCHS = ["gustavsnn", "loas", "prosperity", "ptb", "spinalflow"]
NETWORKS = ["resnet19_T4_all", "vgg16_T4_all"]

# Unclamped cout-range width per arch. Used ONLY to check the clamping rule in
# the sanity check; the analysis path derives the effective width from the trace.
NOMINAL_WIDTH = {
    "gustavsnn": 8,
    "loas": 16,
    "ptb": 16,
    "prosperity": 128,
    "spinalflow": 128,
}


@dataclass
class Trace:
    arch: str
    network: str
    layer: str
    sample_idx: int
    dims: dict          # workload_dims: KH, KW, CIN, COUT, HO, WO, T, ...
    dram_num_steps: int
    stream: list        # a[t] = (kh, kw, cin, cout_start, cout_end), issue order
    tile_of: list       # tile_of[t] = dram_i of stream position t


def sample_path(arch: str, network: str, layer: str, sample_idx: int) -> Path:
    return TRACE_ROOT / arch / network / layer / f"sample_{sample_idx:05d}.json.gz"


def list_layers(arch: str, network: str) -> list[str]:
    root = TRACE_ROOT / arch / network
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def load_raw(arch: str, network: str, layer: str, sample_idx: int) -> dict:
    """Return the parsed JSON dict exactly as stored (file/tile order preserved)."""
    with gzip.open(sample_path(arch, network, layer, sample_idx), "rt") as fh:
        return json.load(fh)


def load_trace(arch: str, network: str, layer: str, sample_idx: int) -> Trace:
    """Load a sample and flatten its tiles into the ordered access stream."""
    raw = load_raw(arch, network, layer, sample_idx)
    stream: list = []
    tile_of: list = []
    for tile in raw["tiles"]:
        dram_i = tile["dram_i"]
        for kh, kw, cin, cout_start, cout_end in tile["weight_addresses"]:
            stream.append((kh, kw, cin, cout_start, cout_end))
            tile_of.append(dram_i)
    return Trace(
        arch=raw["arch"],
        network=network,
        layer=raw["layer_name"],
        sample_idx=raw["sample_idx"],
        dims=raw["workload_dims"],
        dram_num_steps=raw["dram_num_steps"],
        stream=stream,
        tile_of=tile_of,
    )


def observed_widths(trace: Trace) -> set[int]:
    """Effective cr widths present in this trace (derived, never cached)."""
    return {ce - cs for (_kh, _kw, _cin, cs, ce) in trace.stream}
