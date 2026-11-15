import json
import subprocess
import sys

import loas_counts
import ptb_counts
import spinalflow_counts as spinal
from capture_counts import validate_replay

spinal.cap_threads(1)
import numpy as np


def test_loas_native_records_and_output_words(tmp_path):
    sys.path.insert(0, str(spinal.SRC))
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.loas import native_bridge as native
    from lays.cachesim.stream import write_stream_header, write_tile_frame, write_stream_trailer
    capture = spinal.ROOT / "examples/input_trace/loas/vgg16_T4_n5"
    meta = json.loads((capture / "meta.json").read_text())
    for layer in ("layer_04_features_14", "layer_07_features_24"):
        trace = np.ascontiguousarray(np.load(capture / f"{layer}.npy", mmap_mode="r")[:, :1])
        cout = meta["layer_params"][layer]["cout"]
        counts = loas_counts.count_sample(trace, 0, cout=cout, kernel=3, cout_n=128, d_out=0.25)
        ptb = ptb_counts.count_sample(trace, 0, cout=cout, kernel=3, cout_n=128, d_out=0.25)
        assert {k: counts[k] for k in ptb} == ptb
        assert counts["W_o"] == 0.25 * trace.shape[3] * trace.shape[4] * cout
        dims = dict(enumerate((3, 3, trace.shape[2], cout, trace.shape[3], trace.shape[4], trace.shape[0])))
        tiles = [NodeTileSpec(i, {**dims, 3: 128, 4: 1, 5: 1}, {3: co, 4: ho, 5: wo}, True)
                 for i, (co, ho, wo) in enumerate((co, ho, wo) for co in range(0, cout, 128)
                                                  for ho in range(trace.shape[3]) for wo in range(trace.shape[4]))]
        (tmp_path / "trace").write_bytes(trace.tobytes())
        (tmp_path / "task").write_bytes(native._pack_task(trace.shape, tiles, [0]))
        subprocess.run([str(native._BINARY), str(tmp_path / "trace"), str(tmp_path / "task"), str(tmp_path / "out")], check=True)
        path = tmp_path / "sample_00000.wcts"
        with path.open("wb") as stream:
            write_stream_header(stream, n_tiles=len(tiles), n_cores=1, weight_bytes=1, burst_dim=3,
                                burst_stride=1, burst_span=128, spatial_factors={}, dims=dims,
                                arch="loas", workload=capture.name, layer=layer, sample_idx=0)
            total = 0
            for tile, _, cycles, ticks in native._unpack_output((tmp_path / "out").read_bytes(), len(tiles), [0]):
                records = [(e["tick"], addr) for e in ticks for addr in e["weight_addresses"]]
                total += write_tile_frame(stream, tile_index=tile, mac_cycles=cycles,
                                          cores=[(0, records)] if records else [], burst_dim=3)
            write_stream_trailer(stream, total)
        assert validate_replay(path, {**counts, "COUT": cout}, "loas", layer, 0) == (counts["B"], "pass")
