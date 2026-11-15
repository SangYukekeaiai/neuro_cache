import csv
import json
import struct
import sys
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).parent))
import spinalflow_counts as counts


def _write_wcts(path: Path, *, layer: str, sample: int, cout: int, bursts: int, span: int):
    identity = f"spinalflow\0synthetic\0{layer}\0{sample}\0".encode()
    dims = [(0, 3), (1, 3), (2, 1), (3, cout), (4, 3), (5, 3), (6, 2)]
    header_bytes = 56 + 20 + 8 * len(dims) + len(identity)
    fixed = struct.pack(
        "<IIiiiiiiiiii", 2, header_bytes, 1, 1, 1, 3, 1, span, 5, 0,
        len(dims), len(identity)
    )
    frame_payload = 8 + 28 * bursts
    frame = struct.pack("<iiqQ", 0, 1, bursts, frame_payload)
    frame += struct.pack("<ii", 0, bursts)
    frame += b"".join(struct.pack("<q5i", tick, 0, 0, 0, 0, span)
                       for tick in range(bursts))
    path.write_bytes(
        b"WCTRACE1" + fixed + struct.pack("<5i", 0, 1, 2, 3, 4)
        + b"".join(struct.pack("<ii", dim, extent) for dim, extent in dims)
        + identity + frame + struct.pack("<iQ", -1, bursts)
    )


def test_window_counts_and_effective_cout_width():
    trace = np.zeros((2, 1, 1, 3, 3), dtype=np.uint8)
    trace[0, 0, 0, 0, 0] = 1       # padded 3x3 multiplicity 4
    trace[1, 0, 0, 1, 1] = 1       # center multiplicity 9
    result = counts.count_sample(trace, 0, cout=4, kernel=3)
    assert result == {
        "T": 2, "CIN": 1, "Hin": 3, "Win": 3, "HO": 3, "WO": 3,
        "cout_n": 4, "S_win": 13, "A": 52, "R": 13, "O": 72,
    }
    assert counts.effective_cout_n(10) == 2


def test_wcts_summary_and_replay_check(tmp_path):
    path = tmp_path / "sample_00000.wcts"
    _write_wcts(path, layer="layer", sample=0, cout=4, bursts=13, span=4)
    summary = counts.read_wcts_summary(path)
    assert summary["bursts"] == 13
    status, detail = counts.validate_wcts(
        summary, {"COUT": 4, "R": 13, "A": 52, "cout_n": 4}, "layer", 0
    )
    assert status == "pass"
    assert "13" in detail


def test_wcts_index_accepts_architecture_directory(tmp_path):
    capture = tmp_path / "G" / "synthetic"
    layer_dir = capture / "spinalflow" / "layer"
    layer_dir.mkdir(parents=True)
    (capture / "meta.json").write_text("{}")
    path = layer_dir / "sample_00000.wcts"
    _write_wcts(path, layer="layer", sample=0, cout=4, bursts=1, span=4)
    index = counts.index_wcts(tmp_path)
    assert counts._find_wcts(index, "G/synthetic", "layer", 0) == path


def test_cli_is_bounded_and_resume_safe(tmp_path, capsys):
    capture = tmp_path / "G" / "synthetic"
    capture.mkdir(parents=True)
    meta = {
        "layers": {"layer": [2, 1, 1, 3, 3], "filtered_layer": [2, 1, 1, 3, 3]},
        "layer_params": {name: {"cout": 4, "kernel": 3, "stride": 1}
                         for name in ("layer", "filtered_layer")},
        "subset": {"sample_indices": [17]},
    }
    (capture / "meta.json").write_text(json.dumps(meta))
    trace = np.zeros((2, 1, 1, 3, 3), dtype=np.uint8)
    trace[0, 0, 0, 0, 0] = 1
    np.save(capture / "layer.npy", trace)
    output = tmp_path / "counts.csv"
    arguments = [
        "--trace-root", str(tmp_path), "--capture", "G/synthetic",
        "--max-layers", "1", "--max-samples", "1", "--threads", "1",
        "--output", str(output),
    ]
    assert counts.main(arguments) == 0
    assert counts.main(arguments + ["--resume"]) == 0
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["S_win"] == "4"
    assert rows[0]["source_sample"] == "17"
    output_text = capsys.readouterr().out
    assert "skipped 1" in output_text
    assert "unsupported_layers 0" in output_text


def test_reference_capture_counts():
    capture = counts.ROOT / "examples/input_trace/loas/vgg16_T4_n5"
    meta = json.loads((capture / "meta.json").read_text())
    for layer, spikes, lane_ops, bursts in (
        ("layer_04_features_14", 41116, 10525696, 82232),
        ("layer_07_features_24", 16182, 8285184, 64728),
    ):
        trace = np.load(capture / f"{layer}.npy", mmap_mode="r")
        result = counts.count_sample(trace, 0, cout=meta["layer_params"][layer]["cout"], kernel=3)
        assert result["S_win"] == spikes
        assert result["A"] == lane_ops
        assert result["A"] // 128 == bursts


def test_replay_different_width_and_partial_rejection(tmp_path):
    path = tmp_path / "sample_00000.wcts"
    expected = {"COUT": 256, "cout_n": 4, "A": 10525696, "R": 2631424}
    _write_wcts(path, layer="layer", sample=0, cout=256, bursts=82232, span=128)
    assert counts.validate_wcts(counts.read_wcts_summary(path), expected, "layer", 0)[0] == "pass_geometry"
    _write_wcts(path, layer="layer", sample=0, cout=256, bursts=41116, span=128)
    assert counts.validate_wcts(counts.read_wcts_summary(path), expected, "layer", 0)[0] == "mismatch"
