"""tracegen.check_schedule_matches_trace: a tracked schedule solved for a
different workload than meta.json now gives is refused."""
import argparse
import dataclasses
import gzip
import json
import pathlib
import sys

import pytest

import tracegen  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import generate_weight_traces as gwt  # noqa: E402

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
    tracegen.check_schedule_matches_trace(schedule(tmp_path, PROBLEM), trace_dir, "b")


def test_a_schedule_solved_for_another_cout_is_refused_by_path(tmp_path, trace_dir):
    path = schedule(tmp_path, {**PROBLEM, "COUT": 64})
    with pytest.raises(ValueError) as e:
        tracegen.check_schedule_matches_trace(path, trace_dir, "b")
    msg = str(e.value)
    assert str(path) in msg and "COUT" in msg and "Gurobi" in msg
    assert "solve_all_layers.py" in msg and "solve_schedules.py --force" in msg


def test_the_refusal_names_the_arch_the_schedule_was_solved_with(tmp_path, trace_dir):
    path = schedule(tmp_path, {**PROBLEM, "COUT": 64}, arch="/x/loas_inst16_pe16.yaml")
    with pytest.raises(ValueError, match="/x/loas_inst16_pe16.yaml"):
        tracegen.check_schedule_matches_trace(path, trace_dir, "b")


def test_a_schedule_for_an_excluded_layer_is_refused(tmp_path, trace_dir):
    meta = json.loads((trace_dir / "meta.json").read_text())
    meta["layer_params"]["b"]["stride"] = 2
    (trace_dir / "meta.json").write_text(json.dumps(meta))
    path = schedule(tmp_path, PROBLEM)
    with pytest.raises(ValueError, match="stride 2") as e:
        tracegen.check_schedule_matches_trace(path, trace_dir, "b")
    assert str(path) in str(e.value)


def test_a_schedule_is_refused_when_meta_has_no_layer_params(tmp_path, trace_dir):
    (trace_dir / "meta.json").write_text(json.dumps({"layers": {"b": [4, 5, 128, 4, 4]}}))
    with pytest.raises(ValueError, match="layer_params"):
        tracegen.check_schedule_matches_trace(schedule(tmp_path, PROBLEM), trace_dir, "b")


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


def small_trace():
    tick = tracegen.TickEntry(tick=0, cores=[tracegen.CoreEntry(core_id=0, weight_addresses=[[0, 0, 0, 0, 4]])])
    return tracegen.LayerWeightTrace(
        arch="loas", trace_dir="t", layer_name="b", sample_idx=3, workload_dims=PROBLEM,
        dram_num_steps=1, noc_num_steps=2,
        tiles=[tracegen.TileWeightTrace(dram_i=0, noc_i=n, mac_cycles=10 + n, lif_cycles=None, ticks=[tick])
               for n in range(2)])


def read_gz(path):
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def test_save_step_cycles_writes_only_what_nocsim_reads(tmp_path):
    path = tmp_path / "sample_00003.json.gz"
    tracegen.save_step_cycles(small_trace(), path)
    doc = read_gz(path)
    assert set(doc) == {"format", "arch", "trace_dir", "layer_name", "sample_idx", "workload_dims",
                        "dram_num_steps", "noc_num_steps", "tiles"}
    assert doc["format"] == "step_cycles_v1"
    assert doc["tiles"] == [{"dram_i": 0, "noc_i": 0, "mac_cycles": 10, "lif_cycles": None},
                            {"dram_i": 0, "noc_i": 1, "mac_cycles": 11, "lif_cycles": None}]


def test_load_step_cycles_reads_the_slim_and_the_old_full_form_the_same(tmp_path):
    slim = tmp_path / "slim.json.gz"
    tracegen.save_step_cycles(small_trace(), slim)
    full = tmp_path / "full.json.gz"
    with gzip.open(full, "wt") as fh:
        json.dump(dataclasses.asdict(small_trace()), fh)
    assert tracegen.load_step_cycles(slim) == tracegen.load_step_cycles(full)
    assert tracegen.load_step_cycles(slim).by_step == {
        (0, 0): tracegen.ComputeCycles(mac_cycles=10, lif_cycles=None),
        (0, 1): tracegen.ComputeCycles(mac_cycles=11, lif_cycles=None)}


def test_load_step_cycles_rejects_an_unknown_format(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"format": "step_cycles_v2"}))
    with pytest.raises(ValueError, match="step_cycles_v2"):
        tracegen.load_step_cycles(path)
