"""Compare native replay with independently indexed convolution windows."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
from lays.weight_trace_gen import NodeTileSpec
from lays.weight_trace_gen.spinalflow.native_bridge import reconstruct_samples_native
from lays.weight_trace_gen.trace import exclusion_reason, valid_layer_names
from gen_inputs import NETWORKS

ROOT = Path(__file__).resolve().parent


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


def check_layer(trace, meta, name, output_dir):
    trace_array = np.load(trace / f"{name}.npy")
    params = meta["layer_params"][name]
    kernel, stride, cout = (params[key] for key in ("kernel", "stride", "cout"))
    t, _, cin, _, _ = trace_array.shape
    reference = reference_counts(trace_array[:, 0], kernel, stride)
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
    # workload loader already excludes unsupported layers.
    result = reconstruct_samples_native(trace_array, tiles, [0], "spinalflow", trace.name,
                                        name, dimensions, len(tiles))[0]
    rows = []
    for tile, native in zip(tiles, result.tiles, strict=True):
        ho, wo = tile.tile_offset[DIM_HO], tile.tile_offset[DIM_WO]
        ref = int(reference[ho, wo])
        rows.append(dict(dram_i=tile.dram_i, ho=ho, wo=wo,
                         cout_start=tile.tile_offset[DIM_COUT],
                         reference_mac_cycles=ref, native_mac_cycles=native.mac_cycles,
                         delta=native.mac_cycles - ref))
    with (output_dir / f"{name}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    mismatches = [row for row in rows if row["delta"] != 0]
    return dict(layer=name, sample=0, hardware_N=128, kernel=kernel, stride=stride,
                padding=(kernel - 1) // 2, output_shape=[height, width],
                tiles=len(rows), mismatches=len(mismatches),
                reference_total=sum(row["reference_mac_cycles"] for row in rows),
                native_total=sum(row["native_mac_cycles"] for row in rows),
                first_mismatch=mismatches[0] if mismatches else None,
                public_loader_exclusion=exclusion_reason(meta, name),
                input_sha256=hashlib.sha256((trace / f"{name}.npy").read_bytes()).hexdigest())


def checked_layers(meta):
    valid = valid_layer_names(meta)
    if not valid:
        raise ValueError("trace has no replayable layers")
    excluded = [name for name in meta["layers"] if name not in valid]
    stride2 = [name for name in excluded if meta["layer_params"][name]["stride"] != 1]
    names = list(stride2[:2])
    names.append(valid[0])
    gemm = next((name for name in valid if meta["layer_params"][name]["kernel"] == 1), None)
    if gemm is not None and gemm not in names:
        names.append(gemm)
    return valid, excluded, names


def main():
    out = ROOT / "outputs/feasibility"
    out.mkdir(parents=True, exist_ok=True)
    for network, trace in NETWORKS.items():
        meta = json.loads((trace / "meta.json").read_text())
        valid, excluded, names = checked_layers(meta)
        network_out = out if network == "resnet19" else out / network
        network_out.mkdir(parents=True, exist_ok=True)
        reports = [check_layer(trace, meta, name, network_out) for name in names]
        for report in reports:
            report["network"] = network
            print(json.dumps(report), flush=True)
        controls = [report for report in reports if report["stride"] == 1]
        assert controls and all(report["mismatches"] == 0 for report in controls), (
            f"{network}: stride-1 control disagrees with reference"
        )
        stride2_reports = [report for report in reports if report["stride"] != 1]
        document = {
            "network": network,
            "trace": str(trace),
            "arch": meta["arch"],
            "n_samples": meta["n_samples"],
            "valid_layers": valid,
            "excluded_layers": {name: exclusion_reason(meta, name) for name in excluded},
            "reference": "Raw [T,C,H,W] sample, pad=(kernel-1)//2; count_nonzero of each kernel-by-kernel window beginning at (ho*stride, wo*stride) in padded input. No generator window function is used.",
            "stride2_supported": bool(stride2_reports) and all(
                report["mismatches"] == 0 for report in stride2_reports
            ),
            "cases": reports,
        }
        report_path = out / "report.json" if network == "resnet19" else network_out / "report.json"
        report_path.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
