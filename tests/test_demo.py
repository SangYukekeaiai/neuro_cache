"""The pure pieces of scripts/demo.py: the nocsim/wcache join, the speedup,
the per-config geomean summary, and the input checks that refuse a run."""
import json
import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import demo  # noqa: E402


def wc(layer, sample, config, cycles):
    return {"tag": layer, "trace_dir": "t", "layer": layer, "sample": sample,
            "config": config, "l2_banks": "1", "total_cycles": str(cycles)}


def test_speedup_is_nocsim_over_wcache():
    assert demo.speedup(300, 150) == 2.0


def test_geomean_of_two_and_eight_is_four():
    assert math.isclose(demo.geomean([2.0, 8.0]), 4.0)


def test_join_pairs_each_wcache_row_with_its_layer_sample_nocsim_cycles():
    nocsim = {("t", "A", 0): 300, ("t", "A", 1): 400}
    rows = demo.join_results(nocsim, [wc("A", 0, "c0", 150), wc("A", 1, "c0", 100)])
    assert [(r["nocsim_total_cycles"], r["wcache_total_cycles"], r["speedup_vs_nocsim"])
            for r in rows] == [(300, 150, 2.0), (400, 100, 4.0)]
    assert rows[0]["config"] == "c0" and rows[0]["l2_banks"] == "1"
    assert "total_cycles" not in rows[0]


def test_join_refuses_a_wcache_row_without_nocsim_cycles():
    with pytest.raises(KeyError):
        demo.join_results({}, [wc("A", 0, "c0", 150)])


def test_summary_is_geomean_per_config_in_first_seen_order():
    rows = [{"config": "c1", "speedup_vs_nocsim": 2.0},
            {"config": "c0", "speedup_vs_nocsim": 1.0},
            {"config": "c1", "speedup_vs_nocsim": 8.0}]
    assert demo.summarize(rows) == [("c1", pytest.approx(4.0), 2), ("c0", 1.0, 1)]


def write_bench(root, layers=(("layer_01_a", [4, 5, 8, 4, 4]),), npy=True):
    """input_trace/<bench>/t/ under `root`: a meta.json and, if `npy`, one uint8 .npy per layer."""
    d = root / "loas" / "t"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"n_samples": layers[0][1][1], "dtype": "uint8", "layers": dict(layers)}))
    if npy:
        for name, shape in layers:
            np.save(d / f"{name}.npy", np.zeros(shape, dtype=np.uint8))
    return d


@pytest.fixture
def traces(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "INPUT_TRACE", tmp_path)
    return tmp_path


def test_resolve_layers_passes_trace_dir_slash_layer_through():
    assert demo.resolve_layers("loas", ["t/layer_01_a"]) == [("t", "layer_01_a")]


def test_resolve_layers_refuses_an_unknown_tag():
    with pytest.raises(SystemExit, match="unknown layer 'X99'"):
        demo.resolve_layers("loas", ["X99"])


def test_resolve_layers_reads_tags_from_the_given_bench():
    with pytest.raises(SystemExit, match="unknown layer 'V8'"):
        demo.resolve_layers("no_such_bench", ["V8"])


def test_check_inputs_accepts_a_complete_bench(traces):
    write_bench(traces)
    assert demo.check_inputs("loas", [("t", "layer_01_a")], range(0, 5)) == []


def test_check_inputs_refuses_a_missing_bench_dir(traces):
    assert "does not exist" in demo.check_inputs("loas", [("t", "x")], range(1))[0]


def test_check_inputs_refuses_a_missing_meta(traces):
    (traces / "loas").mkdir()
    assert "missing" in demo.check_inputs("loas", [("t", "layer_01_a")], range(1))[0]


def test_check_inputs_refuses_a_layer_not_in_meta(traces):
    write_bench(traces)
    assert "not a valid layer" in demo.check_inputs("loas", [("t", "layer_09_z")], range(1))[0]


def test_check_inputs_refuses_a_missing_npy(traces):
    write_bench(traces, npy=False)
    assert "layer_01_a.npy" in demo.check_inputs("loas", [("t", "layer_01_a")], range(1))[0]


def test_check_inputs_refuses_samples_beyond_the_trace(traces):
    write_bench(traces)
    problems = demo.check_inputs("loas", [("t", "layer_01_a")], range(3, 6))
    assert len(problems) == 1 and "samples 3..5" in problems[0] and "5 samples" in problems[0]


def test_load_grid_refuses_an_empty_grid(tmp_path):
    g = tmp_path / "g.json"
    g.write_text("[]")
    with pytest.raises(SystemExit, match="no configs"):
        demo.load_grid(g)


@pytest.fixture
def no_solver_run(monkeypatch):
    """schedules_for with solve_schedules.py replaced by a no-op that records its commands."""
    calls = []
    monkeypatch.setattr(demo, "run_all", lambda cmds, record, jobs: calls.extend(cmds))
    return calls


def test_schedules_for_refuses_when_the_solver_writes_nothing(tmp_path, monkeypatch, no_solver_run):
    monkeypatch.setattr(demo.wb, "SCHEDULES", tmp_path / "tracked")
    with pytest.raises(SystemExit, match="did not write these schedules") as e:
        demo.schedules_for("loas", [("t", "layer_01_a")], tmp_path / "out", [])
    assert "layer_01_a.json" in str(e.value) and len(no_solver_run) == 1


def test_schedules_for_seeds_the_cache_with_tracked_schedules(tmp_path, monkeypatch, no_solver_run):
    tracked = tmp_path / "tracked"
    (tracked / "loas" / "t").mkdir(parents=True)
    (tracked / "loas" / "t" / "layer_01_a.json").write_text("{}")
    monkeypatch.setattr(demo.wb, "SCHEDULES", tracked)
    with pytest.raises(SystemExit) as e:
        demo.schedules_for("loas", [("t", "layer_01_a"), ("t", "layer_02_b")], tmp_path / "out", [])
    assert (tmp_path / "out/schedules/loas/t/layer_01_a.json").is_file()
    assert "layer_02_b.json" in str(e.value) and "layer_01_a.json" not in str(e.value)


@pytest.mark.parametrize("args", [["--sample-count", "0"], ["--jobs", "0"], ["--sample-start", "-1"]])
def test_main_refuses_counts_below_one(monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["demo.py", *args])
    with pytest.raises(SystemExit):
        demo.main()
    assert "must be at least" in capsys.readouterr().err


def test_demo_does_not_create_out_when_inputs_are_missing(tmp_path, traces, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["demo.py", "--layers", "t/layer_01_a", "--out", str(out)])
    with pytest.raises(SystemExit, match="cannot run the demo"):
        demo.main()
    assert not out.exists()


def test_check_bench_accepts_a_complete_bench(traces):
    write_bench(traces)
    problems, notes = demo.check_bench("loas")
    assert problems == [] and notes == ["loas/t: 1 layers, 1 usable, 0 with a tracked schedule"]


def test_check_bench_lists_what_an_empty_dir_lacks(tmp_path):
    (tmp_path / "nobench").mkdir()
    problems, _ = demo.check_bench(str(tmp_path / "nobench"))
    assert any("no trace dirs" in p for p in problems)
    assert any("configs/arch/nobench.yaml" in p for p in problems)
    assert any("ARCH_NATIVE_BRIDGES" in p for p in problems)


def test_check_bench_main_exits_nonzero_with_the_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["demo.py", "--check-bench", str(tmp_path)])
    assert demo.main() == 1
    assert "no trace dirs" in capsys.readouterr().out


def test_check_bench_refuses_a_wrong_npy_dtype_or_shape(traces):
    d = write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 4, 4])))
    np.save(d / "layer_01_a.npy", np.zeros([4, 5, 8, 4, 4], dtype=np.int8))
    np.save(d / "layer_02_b.npy", np.zeros([4, 4, 8, 4, 4], dtype=np.uint8))
    problems, _ = demo.check_bench("loas")
    assert len(problems) == 2
    assert "want uint8" in problems[0] and "meta.json says (4, 5, 8, 4, 4)" in problems[1]


def test_check_bench_refuses_meta_without_layers_or_n_samples(traces):
    d = traces / "loas" / "t"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"layers": {}}))
    assert "no 'layers'" in demo.check_bench("loas")[0][0]
    (d / "meta.json").write_text(json.dumps({"layers": {"layer_01_a": [4, 5, 8, 4, 4]}}))
    np.save(d / "layer_01_a.npy", np.zeros([4, 5, 8, 4, 4], dtype=np.uint8))
    problems, notes = demo.check_bench("loas")
    assert problems == [f"{d / 'meta.json'}: no 'n_samples' (scripts/subset_input_traces.py reads it)"]


def test_check_bench_notes_layers_too_small_for_a_3x3_conv(traces):
    write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 1, 1])))
    problems, notes = demo.check_bench("loas")
    assert problems == [] and notes[0].startswith("loas/t: 2 layers, 2 usable")
