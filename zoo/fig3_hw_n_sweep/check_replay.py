"""Compare native replay with independently indexed convolution windows."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
from lays.weight_trace_gen import NodeTileSpec
from lays.weight_trace_gen.spinalflow.native_bridge import reconstruct_samples_native
from lays.weight_trace_gen.trace import exclusion_reason

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
TRACE = REPO / "examples/input_trace/loas/resnet19_T4_n5"


def reference_counts(sample, kernel, stride):
    """Raw [T,C,H,W] input, same padding, actual convolution stride."""
    pad = (kernel - 1) // 2
    height = (sample.shape[-2] + 2 * pad - kernel) // stride + 1
    width = (sample.shape[-1] + 2 * pad - kernel) // stride + 1
    padded = np.pad(sample, ((0, 0), (0, 0), (pad, pad), (pad, pad)))
    counts = np.empty((height, width), dtype=np.int64)
    for ho in range(height):
        for wo in range(width):
            # A 1x1 shortcut uses one input pixel; a 3x3 conv uses nine.
            # Both start at stride-scaled input coordinates in padded space.
            window = padded[:, :, ho * stride:ho * stride + kernel,
                            wo * stride:wo * stride + kernel]
            counts[ho, wo] = np.count_nonzero(window)
    return counts


def main():
    out = ROOT / "outputs/feasibility"
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((TRACE / "meta.json").read_text())
    reports = []
    # Layer 09 is a stride-1 control for the same independent reference.
    for name in ("layer_08_layer2_0_conv1", "layer_10_layer2_0_shortcut_0", "layer_09_layer2_0_conv2"):
        trace = np.load(TRACE / f"{name}.npy")
        params = meta["layer_params"][name]
        kernel, stride, cout = (params[key] for key in ("kernel", "stride", "cout"))
        t, _, cin, _, _ = trace.shape
        reference = reference_counts(trace[:, 0], kernel, stride)
        height, width = reference.shape
        active = min(128, cout)
        tiles = []
        for ho in range(height):
            for wo in range(width):
                for co in range(0, cout, active):
                    tiles.append(NodeTileSpec(
                        len(tiles),
                        {DIM_KH: kernel, DIM_KW: kernel, DIM_CIN: cin, DIM_COUT: active,
                         DIM_HO: 1, DIM_WO: 1, DIM_T: t},
                        {DIM_KH: 0, DIM_KW: 0, DIM_CIN: 0, DIM_COUT: co,
                         DIM_HO: ho, DIM_WO: wo, DIM_T: 0},
                        True,
                    ))
        dimensions = dict(KH=kernel, KW=kernel, CIN=cin, COUT=cout, HO=height, WO=width, T=t)
        # Call the native bridge directly to assess replay itself: the public
        # workload loader already excludes non-3x3/stride-1 layers.
        result = reconstruct_samples_native(trace, tiles, [0], "spinalflow", TRACE.name,
                                            name, dimensions, len(tiles))[0]
        rows = []
        for tile, native in zip(tiles, result.tiles, strict=True):
            ho, wo = tile.tile_offset[DIM_HO], tile.tile_offset[DIM_WO]
            ref = int(reference[ho, wo])
            rows.append(dict(dram_i=tile.dram_i, ho=ho, wo=wo,
                             cout_start=tile.tile_offset[DIM_COUT],
                             reference_mac_cycles=ref, native_mac_cycles=native.mac_cycles,
                             delta=native.mac_cycles - ref))
        with (out / f"{name}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        mismatches = [row for row in rows if row["delta"] != 0]
        report = dict(layer=name, sample=0, hardware_N=128, kernel=kernel, stride=stride,
                      padding=(kernel - 1) // 2, output_shape=[height, width],
                      tiles=len(rows), mismatches=len(mismatches),
                      reference_total=sum(row["reference_mac_cycles"] for row in rows),
                      native_total=sum(row["native_mac_cycles"] for row in rows),
                      first_mismatch=mismatches[0] if mismatches else None,
                      public_loader_exclusion=exclusion_reason(meta, name),
                      input_sha256=hashlib.sha256((TRACE / f"{name}.npy").read_bytes()).hexdigest())
        reports.append(report)
        print(json.dumps(report), flush=True)
    assert reports[2]["mismatches"] == 0, "Stride-1 control disagrees with reference"
    document = {
        "reference": "Raw [T,C,H,W] sample, pad=(kernel-1)//2; count_nonzero of each kernel-by-kernel window beginning at (ho*stride, wo*stride) in padded input. No generator window function is used.",
        "stride2_supported": all(r["mismatches"] == 0 for r in reports[:2]),
        "cases": reports,
    }
    (out / "report.json").write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
