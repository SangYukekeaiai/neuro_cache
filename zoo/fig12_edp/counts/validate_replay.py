"""Replay section 8's two real captures through native SpinalFlow and WCTS."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import spinalflow_counts as counts


def main():
    counts.cap_threads(1)
    sys.path.insert(0, str(counts.SRC))
    import numpy as np
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.spinalflow.native_bridge import _pack_task, _unpack_output, _BINARY
    from lays.cachesim.stream import write_stream_header, write_tile_frame, write_stream_trailer

    capture = counts.ROOT / "examples/input_trace/loas/vgg16_T4_n5"
    meta = json.loads((capture / "meta.json").read_text())
    results = []
    for layer, expected_bursts in (("layer_04_features_14", 82232),
                                   ("layer_07_features_24", 64728)):
        trace = np.ascontiguousarray(np.load(capture / f"{layer}.npy", mmap_mode="r")[:, :1])
        cout = meta["layer_params"][layer]["cout"]
        analytic = counts.count_sample(trace, 0, cout=cout, kernel=3)
        dims = dict(enumerate((3, 3, trace.shape[2], cout, trace.shape[3], trace.shape[4], trace.shape[0])))
        tiles = [NodeTileSpec(i, {**dims, 3: 128, 4: 1, 5: 1},
                             {3: co, 4: ho, 5: wo}, True)
                 for i, (co, ho, wo) in enumerate(
                     (co, ho, wo) for co in range(0, cout, 128)
                     for ho in range(trace.shape[3]) for wo in range(trace.shape[4]))]
        with tempfile.TemporaryDirectory(prefix="spinalflow_replay_") as tmp:
            root = Path(tmp)
            (root / "trace.bin").write_bytes(trace.tobytes())
            (root / "task.bin").write_bytes(_pack_task(trace.shape, tiles, [0]))
            subprocess.run([str(_BINARY), str(root / "trace.bin"), str(root / "task.bin"),
                            str(root / "out.bin")], check=True)
            stream_path = root / "sample_00000.wcts"
            with stream_path.open("wb") as stream:
                write_stream_header(stream, n_tiles=len(tiles), n_cores=1, weight_bytes=1,
                                    burst_dim=3, burst_stride=1, burst_span=128,
                                    spatial_factors={}, dims=dims, arch="spinalflow",
                                    workload=capture.name, layer=layer, sample_idx=0)
                total = 0
                for tile, _, cycles, ticks in _unpack_output((root / "out.bin").read_bytes(), len(tiles), [0]):
                    records = [(entry["tick"], addr) for entry in ticks for addr in entry["weight_addresses"]]
                    total += write_tile_frame(stream, tile_index=tile, mac_cycles=cycles,
                                              cores=[(0, records)] if records else [], burst_dim=3)
                write_stream_trailer(stream, total)
            summary = counts.read_wcts_summary(stream_path)
            status, detail = counts.validate_wcts(summary, {**analytic, "COUT": cout}, layer, 0)
            assert total == expected_bursts, (layer, total, expected_bursts)
            assert status == "pass_geometry", detail
            assert summary["weights"] // cout == analytic["S_win"]
            results.append({"capture": str(capture.relative_to(counts.ROOT)), "layer": layer,
                            "sample": 0, **analytic, "reference_bursts": expected_bursts,
                            "native_wcts_bursts": total, "status": status, "detail": detail})
    output = Path(__file__).with_name("replay_validation.json")
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
