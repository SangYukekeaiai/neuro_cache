import importlib
import json
import subprocess
import sys

import pytest

import ptb_counts as ptb
import spinalflow_counts as spinal
from capture_counts import main, validate_replay

spinal.cap_threads(1)
import numpy as np


def test_or_and_sum_with_padding():
    trace = np.ones((2, 1, 1, 2, 2), dtype=np.uint8)
    result = ptb.count_sample(trace, 0, cout=10, kernel=3, d_out=0.25)
    assert result["cout_n"] == 2
    assert (result["S_or"], result["S_sum"], result["B"], result["A"]) == (16, 32, 80, 320)
    assert (result["L"], result["O"]) == (80, 20)
    with pytest.raises(ValueError, match="d_out is required"):
        ptb.count_sample(trace, 0, cout=10, kernel=3)
    with pytest.raises(ValueError, match="d_out"):
        ptb.count_sample(trace, 0, cout=10, kernel=3, d_out=2)


def test_next_layer_density_and_resume(tmp_path):
    import csv
    directory = tmp_path / "inputs" / "group" / "capture"
    directory.mkdir(parents=True)
    first = np.ones((2, 2, 1, 2, 2), dtype=np.uint8)
    final = np.zeros_like(first)
    final[0, :, 0, 0, 0] = 1
    for name, trace in (("first", first), ("final", final)):
        np.save(directory / (name + ".npy"), trace)
    (directory / "meta.json").write_text(json.dumps({
        "layers": {"first": list(first.shape), "final": list(final.shape)},
        "layer_params": {name: {"cout": 4, "kernel": 1, "stride": 1} for name in ("first", "final")}}))
    output = tmp_path / "counts.csv"
    args = ["--trace-root", str(tmp_path / "inputs"), "--output", str(output)]
    main("ptb", ptb.count_sample, ptb.FIELDS, args)
    rows = list(csv.DictReader(output.open()))
    assert len(rows) == 4
    assert {float(r["d_out"]) for r in rows} == {0.125}
    assert rows[0]["O_source"] == "next_layer_input_density"
    assert rows[-1]["O_source"] == "final_layer_own_density_proxy"
    saved = output.read_bytes()
    with output.open("a") as stream:
        stream.write("group/capture,final,1")
    main("ptb", ptb.count_sample, ptb.FIELDS, args + ["--resume"])
    assert output.read_bytes() == saved


@pytest.mark.parametrize("layer", ["layer_04_features_14", "layer_07_features_24"])
def test_real_ptb_wcts(tmp_path, layer):
    sys.path.insert(0, str(spinal.SRC))
    from lays.weight_trace_gen import NodeTileSpec
    from lays.cachesim.stream import write_stream_header, write_tile_frame, write_stream_trailer
    native = importlib.import_module("lays.weight_trace_gen.ptb.native_bridge")
    capture = spinal.ROOT / "examples/input_trace/loas/vgg16_T4_n5"
    meta = json.loads((capture / "meta.json").read_text())
    trace = np.ascontiguousarray(np.load(capture / f"{layer}.npy", mmap_mode="r")[:, :1])
    cout = meta["layer_params"][layer]["cout"]
    counts = ptb.count_sample(trace, 0, cout=cout, kernel=3, cout_n=128, d_out=0.25)
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
                            arch="ptb", workload=capture.name, layer=layer, sample_idx=0)
        total = 0
        for tile, _, cycles, ticks in native._unpack_output((tmp_path / "out").read_bytes(), len(tiles), [0]):
            records = [(e["tick"], addr) for e in ticks for addr in e["weight_addresses"]]
            total += write_tile_frame(stream, tile_index=tile, mac_cycles=cycles,
                                      cores=[(0, records)] if records else [], burst_dim=3)
        write_stream_trailer(stream, total)
    assert validate_replay(path, {**counts, "COUT": cout}, "ptb", layer, 0) == (counts["B"], "pass")


def test_s_sum_against_delivered_spinalflow_csv():
    import csv
    from pathlib import Path
    with (spinal.ROOT / "zoo/fig12_edp/counts/spinalflow_counts.csv").open(newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["capture"] == "B09/loas_vgg16_T4_n500"
                and r["sample"] == "0" and r["layer"] in ("layer_04_core_features_14", "layer_07_core_features_24")]
    assert len(rows) == 2
    for row in rows:
        trace = np.load(Path("/work/nvme/bebv/yyu9/input_trace_delta") / row["capture"] / (row["layer"] + ".npy"), mmap_mode="r")
        result = ptb.count_sample(trace, 0, cout=int(row["COUT"]), kernel=int(row["kernel"]), d_out=0.25)
        assert result["S_sum"] == int(row["S_win"])
        assert result["A"] == int(row["A"])
