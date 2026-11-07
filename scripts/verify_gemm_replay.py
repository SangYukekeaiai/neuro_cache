"""Reproduce T17's real A07 GEMM replay and independent address checks.

Run from the wcache checkout:
    conda run -n base python scripts/verify_gemm_replay.py

Requires built loasgen, ptbgen and spinalflowgen binaries. Replays token 10,
output channels [0, 64), for all five samples of the captured intermediate_dense
layer. Writes full trace JSON, WCTS streams and checksums to outputs/t17/gemm.
This is a tile correctness check, not a solved full-layer performance result.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lays.cachesim.stream import stream_weight_trace
from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
from lays.weight_trace_gen import NodeTileSpec
from lays.weight_trace_gen.trace import build_workload_from_trace, load_layer_trace
from lays.weight_trace_gen.weight_trace import reconstruct_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, default=ROOT / "neuro_cache_bench_trace/out_smoke_i/A07/spikinglm_t4_T4_n5")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/t17/gemm")
    args = parser.parse_args()
    layer = "layer_05_core_bert_encoder_layer_0_intermediate_dense"
    meta = json.loads((args.trace_dir / "meta.json").read_text())
    problem = build_workload_from_trace(meta, layer)["problem"]
    assert problem == dict(KH=1, KW=1, CIN=768, COUT=3072, HO=128, WO=1, T=4, shape="snn-layer")
    trace = load_layer_trace(args.trace_dir, layer, mmap=True)
    assert trace.shape == (4, 5, 768, 128, 1)
    token, cout_stop = 10, 64
    tile = NodeTileSpec(0, {DIM_KH: 1, DIM_KW: 1, DIM_CIN: problem["CIN"], DIM_COUT: cout_stop,
                            DIM_HO: 1, DIM_WO: 1, DIM_T: problem["T"]},
                        {DIM_HO: token, DIM_WO: 0, DIM_CIN: 0, DIM_COUT: 0, DIM_T: 0}, True)
    checks = []
    for arch in ("loas", "ptb", "spinalflow"):
        results = reconstruct_samples(arch, trace, [tile], list(range(5)), args.trace_dir.name,
                                      layer, problem, 1)
        assert len(results) == 5
        for sample, result in enumerate(results):
            assert result.sample_idx == sample and len(result.tiles) == 1
            actual = [a for tick in result.tiles[0].ticks for core in tick.cores for a in core.weight_addresses]
            spikes = trace[:, sample, :, token, 0]
            if arch == "spinalflow":
                channels = [int(c) for timestep in spikes for c in np.flatnonzero(timestep)]
            else:
                channels = [int(c) for c in np.flatnonzero(np.any(spikes, axis=0))]
            assert actual == [(0, 0, c, 0, cout_stop) for c in channels], (arch, sample)
            directory = args.out / arch
            directory.mkdir(parents=True, exist_ok=True)
            stem = f"sample_{sample:05d}"
            (directory / (stem + ".json")).write_text(json.dumps(dataclasses.asdict(result), indent=2) + "\n")
            stream = directory / (stem + ".wcts")
            with stream.open("wb") as fh:
                count = stream_weight_trace(result, fh, n_cores=1, spatial_factors={})
            assert count == len(channels) > 0
            check = dict(arch=arch, sample=sample, expected_addresses=count,
                         mac_cycles=result.tiles[0].mac_cycles,
                         sha256=hashlib.sha256(stream.read_bytes()).hexdigest())
            checks.append(check)
            print(f"PASS {arch} sample={sample}: {count} addresses match NumPy", flush=True)
    summary = dict(layer=layer, problem=problem, token=token, cout_range=[0, cout_stop], checks=checks)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
