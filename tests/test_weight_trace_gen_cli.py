"""python -m lays.weight_trace_gen: the gen CLI, its schedule/trace consistency
check, and its --stream output."""
import argparse
import dataclasses
import gzip
import hashlib
import io
import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest

from lays.nocsim.step_cycles import load_step_cycles, save_step_cycles  # noqa: E402
from lays.scheduler.artifact import check_schedule_matches_trace  # noqa: E402
from lays.weight_trace_gen import ComputeCycles  # noqa: E402
from lays.weight_trace_gen.weight_trace import (CoreEntry, LayerWeightTrace, TickEntry,  # noqa: E402
                                           TileWeightTrace)
import lays.weight_trace_gen.cli as gwt  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]

PROBLEM = {"KH": 3, "KW": 3, "CIN": 128, "COUT": 128, "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"}


@pytest.fixture
def trace_dir(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "layers": {"b": [4, 5, 128, 4, 4]},
        "layer_params": {"b": {"cout": 128, "kernel": 3, "stride": 1}}}))
    return d


def schedule(tmp_path, problem, arch=None):
    p = tmp_path / "b.json"
    doc = {"workload": {"problem": problem}}
    if arch:
        doc["result"] = {"configs": {"arch": arch}}
    p.write_text(json.dumps(doc))
    return p


def test_a_schedule_solved_for_the_current_workload_passes(tmp_path, trace_dir):
    check_schedule_matches_trace(schedule(tmp_path, PROBLEM), trace_dir, "b")


def test_a_schedule_solved_for_another_cout_is_refused_by_path(tmp_path, trace_dir):
    path = schedule(tmp_path, {**PROBLEM, "COUT": 64})
    with pytest.raises(ValueError) as e:
        check_schedule_matches_trace(path, trace_dir, "b")
    msg = str(e.value)
    assert str(path) in msg and "COUT" in msg and "Gurobi" in msg
    assert "solve-trace --force" in msg


def test_the_refusal_names_the_arch_the_schedule_was_solved_with(tmp_path, trace_dir):
    path = schedule(tmp_path, {**PROBLEM, "COUT": 64}, arch="/x/loas_inst16_pe16.yaml")
    with pytest.raises(ValueError, match="/x/loas_inst16_pe16.yaml"):
        check_schedule_matches_trace(path, trace_dir, "b")


def test_a_schedule_for_an_excluded_layer_is_refused(tmp_path, trace_dir):
    meta = json.loads((trace_dir / "meta.json").read_text())
    meta["layer_params"]["b"]["stride"] = 2
    (trace_dir / "meta.json").write_text(json.dumps(meta))
    path = schedule(tmp_path, PROBLEM)
    with pytest.raises(ValueError, match="stride 2") as e:
        check_schedule_matches_trace(path, trace_dir, "b")
    assert str(path) in str(e.value)


def test_a_schedule_is_refused_when_meta_has_no_layer_params(tmp_path, trace_dir):
    (trace_dir / "meta.json").write_text(json.dumps({"layers": {"b": [4, 5, 128, 4, 4]}}))
    with pytest.raises(ValueError, match="layer_params"):
        check_schedule_matches_trace(schedule(tmp_path, PROBLEM), trace_dir, "b")


@pytest.fixture
def stale_with_outputs(tmp_path, trace_dir):
    """A schedule cache whose schedule for t/b is stale, and an output dir that
    already holds sample 0 for it (in both the combo and --all-layers layouts)."""
    sched = tmp_path / "cache" / "loas" / "t" / "b.json"
    sched.parent.mkdir(parents=True)
    sched.write_text(json.dumps({"workload": {"problem": {**PROBLEM, "COUT": 64}}}))
    out = tmp_path / "out"
    (out / "loas" / "t" / "b").mkdir(parents=True)
    (out / "loas" / "t" / "b" / "sample_00000.json.gz").write_bytes(b"")
    return tmp_path / "cache", out


def test_generate_refuses_a_stale_schedule_even_when_outputs_exist(tmp_path, stale_with_outputs, capsys):
    cache, out = stale_with_outputs
    args = argparse.Namespace(
        trace_root=str(tmp_path), schedule_cache=str(cache), arch="loas", trace_dir="t", layer="b",
        out_dir=str(out), combo_tag=None, sample_start=0, sample_count=1, force=False, workers=1)
    assert gwt.run_one_combo(args) == 1
    assert "stale schedule" in capsys.readouterr().out


def test_all_layers_refuses_a_stale_schedule_even_when_outputs_exist(tmp_path, stale_with_outputs):
    cache, out = stale_with_outputs
    with pytest.raises(ValueError, match="stale schedule"):
        gwt._regenerate_layer("loas", tmp_path, cache, out, "t", "b", [0])


def test_worker_initializer_receives_a_parent_resident_trace(tmp_path):
    trace = np.arange(12, dtype=np.uint8).reshape(2, 1, 2, 3, 1)
    (tmp_path / "meta.json").write_text(json.dumps({"layers": {"b": list(trace.shape)}}))
    np.save(tmp_path / "b.npy", trace)
    parent_trace = gwt.load_layer_trace(tmp_path, "b", mmap=False)
    assert isinstance(parent_trace, np.ndarray)
    assert not isinstance(parent_trace, np.memmap)

    gwt._init_worker(parent_trace, [], "loas", "t", "b", {}, 1, tmp_path)

    assert gwt._STATE["trace"] is parent_trace
    assert gwt._STATE["trace"].flags.c_contiguous
    assert gwt._STATE["trace"].flags.owndata


def small_trace():
    tick = TickEntry(tick=0, cores=[CoreEntry(core_id=0, weight_addresses=[[0, 0, 0, 0, 4]])])
    return LayerWeightTrace(
        arch="loas", trace_dir="t", layer_name="b", sample_idx=3, workload_dims=PROBLEM,
        dram_num_steps=1, noc_num_steps=2,
        tiles=[TileWeightTrace(dram_i=0, noc_i=n, mac_cycles=10 + n, lif_cycles=None, ticks=[tick])
               for n in range(2)])


def read_gz(path):
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def test_save_step_cycles_writes_only_what_nocsim_reads(tmp_path):
    path = tmp_path / "sample_00003.json.gz"
    save_step_cycles(small_trace(), path)
    doc = read_gz(path)
    assert set(doc) == {"format", "arch", "trace_dir", "layer_name", "sample_idx", "workload_dims",
                        "dram_num_steps", "noc_num_steps", "tiles"}
    assert doc["format"] == "step_cycles_v1"
    assert doc["tiles"] == [{"dram_i": 0, "noc_i": 0, "mac_cycles": 10, "lif_cycles": None},
                            {"dram_i": 0, "noc_i": 1, "mac_cycles": 11, "lif_cycles": None}]


def test_load_step_cycles_reads_the_slim_and_the_old_full_form_the_same(tmp_path):
    slim = tmp_path / "slim.json.gz"
    save_step_cycles(small_trace(), slim)
    full = tmp_path / "full.json.gz"
    with gzip.open(full, "wt") as fh:
        json.dump(dataclasses.asdict(small_trace()), fh)
    assert load_step_cycles(slim) == load_step_cycles(full)
    assert load_step_cycles(slim).by_step == {
        (0, 0): ComputeCycles(mac_cycles=10, lif_cycles=None),
        (0, 1): ComputeCycles(mac_cycles=11, lif_cycles=None)}


def test_load_step_cycles_rejects_an_unknown_format(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"format": "step_cycles_v2"}))
    with pytest.raises(ValueError, match="step_cycles_v2"):
        load_step_cycles(path)


R9_SAMPLE0_STREAM_SHA256 = "2a2c582ae38d78e29ad89f45eec6df4ee2089864d2be0fa0b1ab8c01d5aa083e"


def test_stream_is_byte_identical_to_snapshot(tmp_path):
    """`gen --stream` on R9 sample 0 writes the same bytes as the tracked
    stream: the hash equals `sha256sum
    data/demo/loas/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts`."""
    if not (REPO / "src/lays/weight_trace_gen/loas/loasgen").exists():
        pytest.skip("loasgen not built")
    out = tmp_path / "stream.wcts"
    with open(out, "wb") as fh:
        r = subprocess.run(
            [sys.executable, "-m", "lays.weight_trace_gen", "gen", "--arch", "loas",
             "--trace-root", "examples/input_trace/loas", "--trace-dir", "resnet19_T4_n5",
             "--layer", "layer_09_layer2_0_conv2", "--schedule-cache", "examples/schedules",
             "--sample-start", "0", "--sample-count", "1", "--stream"],
            cwd=REPO, stdout=fh, stderr=subprocess.PIPE, text=False)
    assert r.returncode == 0, r.stderr.decode()
    assert hashlib.sha256(out.read_bytes()).hexdigest() == R9_SAMPLE0_STREAM_SHA256


def test_prosperity_sorts_and_reuses_rows_across_t():
    bridge = pathlib.Path(gwt.__file__).parent / "prosperity" / "prosperitygen"
    if not bridge.exists():
        pytest.skip("prosperitygen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_COUT, DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((2, 1, 1, 4, 4), np.uint8)  # [T, B, Cin, Hin, Win]
    trace[0, 0, 0, 0, 0] = trace[0, 0, 0, 1, 1] = 1  # t=0 row: bits {4, 8}
    trace[1, 0, 0, 1, 1] = 1                         # t=1 row: bits {8}
    tile = NodeTileSpec(0, {DIM_HO: 1, DIM_WO: 1, DIM_KH: 3, DIM_KW: 3, DIM_CIN: 1, DIM_COUT: 8, DIM_T: 2},
                        {DIM_T: 0, DIM_HO: 0, DIM_WO: 0}, True)

    result = reconstruct_samples("prosperity", trace, [tile], [0], "x", "y", {}, 1)[0].tiles[0]

    # t=1 has fewer spikes, so it runs first, then t=0 reuses it and fetches only bit 4.
    addresses = [a[:2] for e in result.ticks for c in e.cores for a in c.weight_addresses]
    assert addresses == [(2, 2), (1, 1)]
    assert result.mac_cycles == 2


def test_prosperity_replays_all_resident_cin_channels():
    bridge = pathlib.Path(gwt.__file__).parent / "prosperity" / "prosperitygen"
    if not bridge.exists():
        pytest.skip("prosperitygen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((1, 1, 2, 3, 3), np.uint8)
    trace[0, 0, 0, 1, 1] = 1
    trace[0, 0, 1, 0, 0] = 1
    tile = NodeTileSpec(
        0,
        {DIM_HO: 1, DIM_WO: 1, DIM_KH: 3, DIM_KW: 3, DIM_CIN: 2, DIM_COUT: 8, DIM_T: 1},
        {DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0}, True,
    )

    result = reconstruct_samples(
        "prosperity", trace, [tile], [0], "x", "y",
        {"KH": 3, "KW": 3, "CIN": 2, "COUT": 8, "HO": 1, "WO": 1, "T": 1}, 1,
    )[0].tiles[0]
    addresses = [a for entry in result.ticks for core in entry.cores for a in core.weight_addresses]
    assert addresses == [(2, 2, 0, 0, 8), (1, 1, 1, 0, 8)]
    assert result.mac_cycles == 2


def test_prosperity_section3_hand_example_keeps_popcount_order():
    bridge = pathlib.Path(gwt.__file__).parent / "prosperity" / "prosperitygen"
    if not bridge.exists():
        pytest.skip("prosperitygen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((1, 1, 1, 4, 4), np.uint8)
    for hin, win in ((0, 2), (1, 1), (1, 2), (2, 0), (2, 1)):
        trace[0, 0, 0, hin, win] = 1
    tile = NodeTileSpec(
        0,
        {DIM_HO: 2, DIM_WO: 2, DIM_KH: 3, DIM_KW: 3, DIM_CIN: 1, DIM_COUT: 8, DIM_T: 1},
        {DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0}, True,
    )

    result = reconstruct_samples(
        "prosperity", trace, [tile], [0], "x", "y",
        {"KH": 3, "KW": 3, "CIN": 1, "COUT": 8, "HO": 2, "WO": 2, "T": 1}, 1,
    )[0].tiles[0]
    addresses = [a for entry in result.ticks for core in entry.cores for a in core.weight_addresses]
    assert addresses == [
        (2, 2, 0, 0, 8), (1, 2, 0, 0, 8), (2, 1, 0, 0, 8),
        (0, 2, 0, 0, 8), (1, 1, 0, 0, 8), (1, 2, 0, 0, 8),
        (2, 0, 0, 0, 8), (2, 1, 0, 0, 8),
    ]
    assert result.mac_cycles == 8


def test_gustavsnn_section4_example1_streams_same_tick_bursts_in_one_core():
    """The 17-fetch/10-cycle docs example exercises the native v3 path."""
    binary = pathlib.Path(gwt.__file__).parent / "gustavsnn" / "gustavgen"
    if not binary.exists():
        pytest.skip("gustavgen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.cachesim.stream import stream_weight_trace
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((1, 1, 2, 4, 4), np.uint8)
    for hin, win in ((0, 2), (1, 1), (1, 2), (2, 0), (2, 1)):
        trace[0, 0, 0, hin, win] = 1
    for hin, win in ((0, 0), (1, 1)):
        trace[0, 0, 1, hin, win] = 1
    tile = NodeTileSpec(
        0,
        {DIM_HO: 2, DIM_WO: 2, DIM_KH: 3, DIM_KW: 3, DIM_CIN: 2, DIM_COUT: 8, DIM_T: 1},
        {}, True,
    )

    layer_result = reconstruct_samples(
        "gustavsnn", trace, [tile], [0], "x", "y",
        {"KH": 3, "KW": 3, "CIN": 2, "COUT": 8, "HO": 2, "WO": 2, "T": 1}, 1,
        wave_width=8,
    )[0]
    result = layer_result.tiles[0]
    expected = [
        [(1, 0, 1, 0, 8), (0, 0, 1, 0, 8)],
        [(1, 1, 1, 0, 8), (0, 1, 1, 0, 8)],
        [(1, 2, 0, 0, 8), (0, 2, 0, 0, 8)],
        [(2, 1, 0, 0, 8), (1, 1, 0, 0, 8)],
        [(2, 1, 1, 0, 8), (1, 1, 1, 0, 8)],
        [(2, 2, 0, 0, 8), (1, 2, 0, 0, 8)],
        [(2, 2, 1, 0, 8), (1, 2, 1, 0, 8)],
        [(2, 0, 0, 0, 8)],
        [(2, 1, 0, 0, 8)],
        [(2, 2, 0, 0, 8)],
    ]
    assert result.mac_cycles == 10
    assert sum(len(c.weight_addresses) for e in result.ticks for c in e.cores) == 17
    assert [[a for c in e.cores for a in c.weight_addresses] for e in result.ticks] == expected
    assert [entry.tick for entry in result.ticks] == list(range(10))
    assert [len(entry.cores) for entry in result.ticks] == [1] * 10
    assert [entry.cores[0].core_id for entry in result.ticks] == [0] * 10
    assert [len(entry.cores[0].weight_addresses) for entry in result.ticks] == [2] * 7 + [1] * 3
    stream = io.BytesIO()
    assert stream_weight_trace(layer_result, stream, n_cores=1, spatial_factors={}) == 17
    assert int.from_bytes(stream.getvalue()[8:12], "little") == 3


def test_gustavsnn_section4_example2_streams_wave2_in_one_core():
    """The nine-row example pins the duplicate and the second-wave offset."""
    binary = pathlib.Path(gwt.__file__).parent / "gustavsnn" / "gustavgen"
    if not binary.exists():
        pytest.skip("gustavgen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.cachesim.stream import stream_weight_trace
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((1, 1, 1, 9, 3), np.uint8)
    for win in (0, 1):
        trace[0, 0, 0, 0, win] = 1
    trace[0, 0, 0, 3, 0] = 1
    for win in (0, 1, 2):
        trace[0, 0, 0, 8, win] = 1
    tile = NodeTileSpec(
        0,
        {DIM_HO: 9, DIM_WO: 1, DIM_KH: 1, DIM_KW: 3, DIM_CIN: 1, DIM_COUT: 8, DIM_T: 1},
        {DIM_WO: 1}, True,
    )
    layer_result = reconstruct_samples(
        "gustavsnn", trace, [tile], [0], "x", "y",
        {"KH": 1, "KW": 3, "CIN": 1, "COUT": 8, "HO": 9, "WO": 1, "T": 1}, 1,
        wave_width=8,
    )[0]
    result = layer_result.tiles[0]
    assert result.mac_cycles == 5
    assert sum(len(c.weight_addresses) for e in result.ticks for c in e.cores) == 6
    assert [entry.tick for entry in result.ticks] == [0, 1, 2, 3, 4]
    assert [len(entry.cores) for entry in result.ticks] == [1] * 5
    assert [entry.cores[0].core_id for entry in result.ticks] == [0] * 5
    assert [len(entry.cores[0].weight_addresses) for entry in result.ticks] == [2, 1, 1, 1, 1]
    assert result.ticks[0].cores[0].weight_addresses == [
        (0, 0, 0, 0, 8), (0, 0, 0, 0, 8),
    ]
    stream = io.BytesIO()
    assert stream_weight_trace(layer_result, stream, n_cores=1, spatial_factors={}) == 6
    assert int.from_bytes(stream.getvalue()[8:12], "little") == 3


def test_gustavsnn_campaign_width_four_regroups_waves_from_schedule_shape():
    """A campaign-shaped 4-PE schedule changes the wave-2 start tick."""
    binary = pathlib.Path(gwt.__file__).parent / "gustavsnn" / "gustavgen"
    if not binary.exists():
        pytest.skip("gustavgen not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.cachesim.stream import stream_weight_trace
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.weight_trace import node_level_spatial_product, reconstruct_samples

    strategy = {
        "NodeLevel": {
            "spatial_split": {
                "factors": [{"dim": "COUT", "size": 2}, {"dim": "HO", "size": 2}]
            }
        }
    }
    wave_width = node_level_spatial_product(strategy)
    assert wave_width == 4

    trace = np.zeros((1, 1, 1, 9, 3), np.uint8)
    for win in (0, 1):
        trace[0, 0, 0, 0, win] = 1
    trace[0, 0, 0, 3, 0] = 1
    trace[0, 0, 0, 4, 0] = 1  # gives the {4-7} campaign wave one line
    for win in (0, 1, 2):
        trace[0, 0, 0, 8, win] = 1
    tile = NodeTileSpec(
        0,
        {DIM_HO: 9, DIM_WO: 1, DIM_KH: 1, DIM_KW: 3, DIM_CIN: 1, DIM_COUT: 8, DIM_T: 1},
        {DIM_WO: 1}, True,
    )

    layer_result = reconstruct_samples(
        "gustavsnn", trace, [tile], [0], "x", "y",
        {"KH": 1, "KW": 3, "CIN": 1, "COUT": 8, "HO": 9, "WO": 1, "T": 1}, 1,
        wave_width=4,
    )[0]
    result = layer_result.tiles[0]

    # Derive expected ticks from the wave rule, rather than copying the
    # width-8 example's numbers.  Rows 0-3, 4-7, and 8 are separate waves.
    row_lines = [
        [(0, 0, 0), (0, 1, 0)], [], [], [(0, 0, 0)],
        [(0, 0, 0)], [], [], [],
        [(0, 0, 0), (0, 1, 0), (0, 2, 0)],
    ]
    expected_ticks = []
    wave_starts = []
    wave_start = 0
    for wave_begin in (0, 4, 8):
        wave_end = min(wave_begin + 4, len(row_lines))
        wave_len = max((len(row_lines[row]) for row in range(wave_begin, wave_end)), default=0)
        wave_starts.append(wave_start)
        for line_idx in range(wave_len):
            expected_ticks.append([
                (*row_lines[row][line_idx], 0, 8)
                for row in range(wave_begin, wave_end)
                if line_idx < len(row_lines[row])
            ])
        wave_start += wave_len

    actual_ticks = [[a for c in entry.cores for a in c.weight_addresses]
                    for entry in result.ticks]
    assert wave_starts == [0, 2, 3]
    assert result.mac_cycles == wave_start == 6
    assert sum(map(len, actual_ticks)) == 7
    assert [entry.tick for entry in result.ticks] == list(range(wave_start))
    assert actual_ticks == expected_ticks

    # Carry the schedule-derived width through the real bridge call and stream.
    campaign_stream = io.BytesIO()
    assert stream_weight_trace(layer_result, campaign_stream, n_cores=1, spatial_factors={}) == 7
    assert int.from_bytes(campaign_stream.getvalue()[8:12], "little") == 3
    with pytest.raises(ValueError, match="wave_width is required"):
        reconstruct_samples(
            "gustavsnn", trace, [tile], [0], "x", "y",
            {"KH": 1, "KW": 3, "CIN": 1, "COUT": 8, "HO": 9, "WO": 1, "T": 1}, 1,
        )


def test_reconstruct_samples_rejects_wave_width_for_other_architectures():
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    with pytest.raises(ValueError, match="only valid for gustavsnn"):
        reconstruct_samples("loas", None, [], [], "x", "y", {}, 1, wave_width=4)


@pytest.mark.parametrize("arch,exe,bursts,cycles", [
    ("loas", "loasgen", 1, 1), ("spinalflow", "spinalflowgen", 2, 2),
    ("ptb", "ptbgen", 1, 8), ("gustavsnn", "gustavgen", 1, 1),
    ("prosperity", "prosperitygen", 1, 1),
])
def test_native_1x1_uses_zero_padding_and_the_selected_token(arch, exe, bursts, cycles):
    binary = pathlib.Path(gwt.__file__).parent / arch / exe
    if not binary.exists():
        pytest.skip(f"{exe} not built")
    np = pytest.importorskip("numpy")
    from lays.parsers.layer import DIM_COUT, DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.trace import build_workload_from_trace
    from lays.weight_trace_gen.weight_trace import reconstruct_samples

    trace = np.zeros((2, 1, 1, 3, 1), np.uint8)
    trace[:, 0, 0, 1, 0] = 1
    meta = {"layers": {"fc": list(trace.shape)},
            "layer_params": {"fc": {"cout": 4, "kernel": 1, "stride": 1}}}
    problem = build_workload_from_trace(meta, "fc")["problem"]
    tile = NodeTileSpec(0, {DIM_HO: 1, DIM_WO: 1, DIM_KH: problem["KH"], DIM_KW: problem["KW"],
                            DIM_CIN: 1, DIM_COUT: 4, DIM_T: 1 if arch == "gustavsnn" else 2},
                        {DIM_T: 0, DIM_HO: 1, DIM_WO: 0}, True)
    result = reconstruct_samples(
        arch, trace, [tile], [0], "tokens", "fc", problem, 1,
        wave_width=1 if arch == "gustavsnn" else None,
    )[0].tiles[0]
    addresses = [a for tick in result.ticks for core in tick.cores for a in core.weight_addresses]
    assert addresses == [(0, 0, 0, 0, 4)] * bursts
    assert result.mac_cycles == cycles
