"""The pure pieces of scripts/pipeline.py: the nocsim/wcache join, the speedup,
the per-config geomean summary, the input checks that refuse a run, the
`--layers all` expansion, and the commands a run records."""
import json
import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import pipeline  # noqa: E402


def wc(layer, sample, config, cycles):
    return {"tag": layer, "trace_dir": "t", "layer": layer, "sample": sample,
            "config": config, "l2_banks": "1", "total_cycles": str(cycles)}


def test_speedup_is_nocsim_over_wcache():
    assert pipeline.speedup(300, 150) == 2.0


def test_geomean_of_two_and_eight_is_four():
    assert math.isclose(pipeline.geomean([2.0, 8.0]), 4.0)


def test_join_pairs_each_wcache_row_with_its_layer_sample_nocsim_cycles():
    nocsim = {("t", "A", 0): 300, ("t", "A", 1): 400}
    rows = pipeline.join_results(nocsim, [wc("A", 0, "c0", 150), wc("A", 1, "c0", 100)])
    assert [(r["nocsim_total_cycles"], r["wcache_total_cycles"], r["speedup_vs_nocsim"])
            for r in rows] == [(300, 150, 2.0), (400, 100, 4.0)]
    assert rows[0]["config"] == "c0" and rows[0]["l2_banks"] == "1"
    assert "total_cycles" not in rows[0]


def test_join_refuses_a_wcache_row_without_nocsim_cycles():
    with pytest.raises(KeyError):
        pipeline.join_results({}, [wc("A", 0, "c0", 150)])


def test_summary_is_geomean_per_config_in_first_seen_order():
    rows = [{"config": "c1", "speedup_vs_nocsim": 2.0},
            {"config": "c0", "speedup_vs_nocsim": 1.0},
            {"config": "c1", "speedup_vs_nocsim": 8.0}]
    assert pipeline.summarize(rows) == [("c1", pytest.approx(4.0), 2), ("c0", 1.0, 1)]


def write_bench(root, layers=(("layer_01_a", [4, 5, 8, 4, 4]),), npy=True, params=None):
    """input_trace/<bench>/t/ under `root`: a meta.json and, if `npy`, one uint8 .npy
    per layer. Every layer is a 3x3 stride-1 conv unless `params` says otherwise."""
    d = root / "loas" / "t"
    d.mkdir(parents=True)
    lp = {name: {"cout": 8, "kernel": 3, "stride": 1} for name, _ in layers}
    lp.update(params or {})
    (d / "meta.json").write_text(json.dumps(
        {"n_samples": layers[0][1][1], "dtype": "uint8", "layers": dict(layers), "layer_params": lp}))
    if npy:
        for name, shape in layers:
            np.save(d / f"{name}.npy", np.zeros(shape, dtype=np.uint8))
    return d


@pytest.fixture
def traces(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "INPUT_TRACE", tmp_path)
    return tmp_path


def test_resolve_layers_passes_trace_dir_slash_layer_through():
    assert pipeline.resolve_layers("loas", ["t/layer_01_a"]) == [("t", "layer_01_a")]


def test_resolve_layers_refuses_an_unknown_tag():
    with pytest.raises(SystemExit, match="unknown layer 'X99'"):
        pipeline.resolve_layers("loas", ["X99"])


def test_resolve_layers_reads_tags_from_the_given_bench():
    with pytest.raises(SystemExit, match="unknown layer 'V8'"):
        pipeline.resolve_layers("no_such_bench", ["V8"])


def test_check_inputs_accepts_a_complete_bench(traces):
    write_bench(traces)
    assert pipeline.check_inputs("loas", [("t", "layer_01_a")], range(0, 5)) == []


def test_check_inputs_refuses_a_missing_bench_dir(traces):
    assert "does not exist" in pipeline.check_inputs("loas", [("t", "x")], range(1))[0]


def test_check_inputs_refuses_a_missing_meta(traces):
    (traces / "loas").mkdir()
    assert "missing" in pipeline.check_inputs("loas", [("t", "layer_01_a")], range(1))[0]


def test_check_inputs_refuses_a_layer_not_in_meta(traces):
    write_bench(traces)
    assert "not a valid layer" in pipeline.check_inputs("loas", [("t", "layer_09_z")], range(1))[0]


def test_check_inputs_refuses_a_missing_npy(traces):
    write_bench(traces, npy=False)
    assert "layer_01_a.npy" in pipeline.check_inputs("loas", [("t", "layer_01_a")], range(1))[0]


def test_check_inputs_refuses_an_excluded_layer_with_the_reason(traces):
    write_bench(traces, params={"layer_01_a": {"cout": 8, "kernel": 1, "stride": 2}})
    problems = pipeline.check_inputs("loas", [("t", "layer_01_a")], range(1))
    assert len(problems) == 1 and "kernel 1" in problems[0]


def test_check_inputs_refuses_a_layer_without_layer_params(traces):
    d = write_bench(traces)
    m = json.loads((d / "meta.json").read_text())
    del m["layer_params"]
    (d / "meta.json").write_text(json.dumps(m))
    problems = pipeline.check_inputs("loas", [("t", "layer_01_a")], range(1))
    assert len(problems) == 1 and "layer_params" in problems[0]


def test_check_inputs_refuses_samples_beyond_the_trace(traces):
    write_bench(traces)
    problems = pipeline.check_inputs("loas", [("t", "layer_01_a")], range(3, 6))
    assert len(problems) == 1 and "samples 3..5" in problems[0] and "5 samples" in problems[0]


def test_load_grid_refuses_an_empty_grid(tmp_path):
    g = tmp_path / "g.json"
    g.write_text("[]")
    with pytest.raises(SystemExit, match="no configs"):
        pipeline.load_grid(g)


@pytest.fixture
def no_solver_run(monkeypatch):
    """schedules_for with the solve-trace run replaced by a no-op that records its commands."""
    calls = []
    monkeypatch.setattr(pipeline, "run_all", lambda cmds, record, jobs: calls.extend(cmds))
    return calls


def test_schedules_for_refuses_when_the_solver_writes_nothing(tmp_path, monkeypatch, no_solver_run):
    monkeypatch.setattr(pipeline, "SCHEDULES", tmp_path / "tracked")
    with pytest.raises(SystemExit, match="did not write these schedules") as e:
        pipeline.schedules_for("loas", [("t", "layer_01_a")], tmp_path / "out", [])
    assert "layer_01_a.json" in str(e.value) and len(no_solver_run) == 1


def test_schedules_for_seeds_the_cache_with_tracked_schedules(tmp_path, monkeypatch, no_solver_run):
    tracked = tmp_path / "tracked"
    (tracked / "loas" / "t").mkdir(parents=True)
    (tracked / "loas" / "t" / "layer_01_a.json").write_text("{}")
    monkeypatch.setattr(pipeline, "SCHEDULES", tracked)
    with pytest.raises(SystemExit) as e:
        pipeline.schedules_for("loas", [("t", "layer_01_a"), ("t", "layer_02_b")], tmp_path / "out", [])
    assert (tmp_path / "out/schedules/loas/t/layer_01_a.json").is_file()
    assert "layer_02_b.json" in str(e.value) and "layer_01_a.json" not in str(e.value)


def test_schedules_for_refuses_a_tracked_schedule_solved_for_another_workload(
        tmp_path, traces, monkeypatch, no_solver_run):
    write_bench(traces, npy=False)
    tracked = tmp_path / "tracked"
    sched = tracked / "loas" / "t" / "layer_01_a.json"
    sched.parent.mkdir(parents=True)
    problem = {"KH": 3, "KW": 3, "CIN": 8, "COUT": 8, "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"}
    sched.write_text(json.dumps({"workload": {"problem": problem}}))
    monkeypatch.setattr(pipeline, "SCHEDULES", tracked)
    assert pipeline.schedules_for("loas", [("t", "layer_01_a")], tmp_path / "out", []) == tracked
    sched.write_text(json.dumps({"workload": {"problem": {**problem, "COUT": 4}}}))
    with pytest.raises(SystemExit, match="solve-trace --force") as e:
        pipeline.schedules_for("loas", [("t", "layer_01_a")], tmp_path / "out", [])
    assert str(sched) in str(e.value) and not no_solver_run


@pytest.mark.parametrize("args", [["--sample-count", "0"], ["--jobs", "0"], ["--sample-start", "-1"]])
def test_main_refuses_counts_below_one(monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *args])
    with pytest.raises(SystemExit):
        pipeline.main()
    assert "must be at least" in capsys.readouterr().err


def test_demo_does_not_create_out_when_inputs_are_missing(tmp_path, traces, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "--layers", "t/layer_01_a", "--out", str(out)])
    with pytest.raises(SystemExit, match="cannot run the demo"):
        pipeline.main()
    assert not out.exists()


def test_check_bench_accepts_a_complete_bench(traces):
    write_bench(traces)
    problems, notes = pipeline.check_bench("loas")
    assert problems == [] and notes == ["loas/t: 1 layers, 1 usable, 0 with a tracked schedule, 0 stale"]


def test_check_bench_lists_what_an_empty_dir_lacks(tmp_path):
    (tmp_path / "nobench").mkdir()
    problems, _ = pipeline.check_bench(str(tmp_path / "nobench"))
    assert any("no trace dirs" in p for p in problems)
    assert any("configs/arch/nobench.yaml" in p for p in problems)
    assert any("ARCH_NATIVE_BRIDGES" in p for p in problems)


def test_check_bench_main_exits_nonzero_with_the_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "--check-bench", str(tmp_path)])
    assert pipeline.main() == 1
    assert "no trace dirs" in capsys.readouterr().out


def test_check_bench_refuses_a_wrong_npy_dtype_or_shape(traces):
    d = write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 4, 4])))
    np.save(d / "layer_01_a.npy", np.zeros([4, 5, 8, 4, 4], dtype=np.int8))
    np.save(d / "layer_02_b.npy", np.zeros([4, 4, 8, 4, 4], dtype=np.uint8))
    problems, _ = pipeline.check_bench("loas")
    assert len(problems) == 2
    assert "want uint8" in problems[0] and "meta.json says (4, 5, 8, 4, 4)" in problems[1]


def test_check_bench_refuses_meta_without_layers_or_n_samples(traces):
    d = traces / "loas" / "t"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"layers": {}}))
    assert "no 'layers'" in pipeline.check_bench("loas")[0][0]
    (d / "meta.json").write_text(json.dumps({"layers": {"layer_01_a": [4, 5, 8, 4, 4]},
                                             "layer_params": {"layer_01_a": {"cout": 8, "kernel": 3, "stride": 1}}}))
    np.save(d / "layer_01_a.npy", np.zeros([4, 5, 8, 4, 4], dtype=np.uint8))
    problems, notes = pipeline.check_bench("loas")
    assert problems == [f"{d / 'meta.json'}: no 'n_samples' (the sample count B, see docs/REPRODUCE.md, Input contract)"]


def test_check_bench_refuses_a_layer_without_cout_kernel_or_stride(traces):
    write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 4, 4])),
                params={"layer_02_b": {"cout": 8, "kernel": 3}})
    problems, _ = pipeline.check_bench("loas")
    assert len(problems) == 1 and "'layer_02_b'" in problems[0] and "stride" in problems[0]


def test_check_bench_notes_excluded_layers_with_their_reasons(traces):
    write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_s", [4, 5, 8, 4, 4])),
                params={"layer_02_s": {"cout": 8, "kernel": 1, "stride": 2}})
    problems, notes = pipeline.check_bench("loas")
    assert problems == [] and notes[0].startswith("loas/t: 2 layers, 1 usable")
    assert "layer_02_s" in notes[1] and "kernel 1" in notes[1]


def test_check_bench_notes_layers_too_small_for_a_3x3_conv(traces):
    write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 1, 1])))
    problems, notes = pipeline.check_bench("loas")
    assert problems == [] and notes[0].startswith("loas/t: 2 layers, 2 usable")


def test_check_bench_lists_a_stale_tracked_schedule_as_a_note(tmp_path, traces, monkeypatch):
    write_bench(traces, layers=(("layer_01_a", [4, 5, 8, 4, 4]), ("layer_02_b", [4, 5, 8, 4, 4])))
    tracked = tmp_path / "tracked"
    (tracked / "loas" / "t").mkdir(parents=True)
    problem = {"KH": 3, "KW": 3, "CIN": 8, "COUT": 8, "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"}
    for name, cout in (("layer_01_a", 8), ("layer_02_b", 4)):
        (tracked / "loas" / "t" / f"{name}.json").write_text(
            json.dumps({"workload": {"problem": {**problem, "COUT": cout}}}))
    monkeypatch.setattr(pipeline, "SCHEDULES", tracked)
    problems, notes = pipeline.check_bench("loas")
    assert problems == []
    assert notes[0] == "loas/t: 2 layers, 2 usable, 2 with a tracked schedule, 1 stale"
    assert notes[1].startswith("  stale schedule ") and "layer_02_b.json" in notes[1]


def test_summary_lists_module_commands(tmp_path, traces, monkeypatch):
    """A whole run with every command faked: each command in summary.md's
    Commands block is `<python> -m <module> ...` or `make ...`, and the four
    module CLIs all appear (solve-trace too, as the layer has no tracked schedule)."""
    write_bench(traces, npy=True)
    monkeypatch.setattr(pipeline, "SCHEDULES", tmp_path / "tracked")
    monkeypatch.setattr(pipeline, "can_solve", lambda: True)
    problem = {"KH": 3, "KW": 3, "CIN": 8, "COUT": 8, "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"}

    def fake_run(cmd, capture=False):
        module = cmd[2] if cmd[1:2] == ["-m"] else None
        if module == "snn_scheduler":
            sched = pathlib.Path(cmd[cmd.index("--cache-dir") + 1]) / "loas/t/layer_01_a.json"
            sched.parent.mkdir(parents=True, exist_ok=True)
            sched.write_text(json.dumps({"workload": {"problem": problem}}))
        if module == "nocsim":
            return "total_cycles: 100\n"
        if module == "cachesim":
            n = len(json.loads(pathlib.Path(cmd[cmd.index("--config-grid") + 1]).read_text()))
            fields = [*pipeline.KEY_FIELDS, "total_cycles"]
            return "\n".join([",".join(fields)] + [",".join(["1"] * len(fields))] * n) + "\n"
        return ""

    monkeypatch.setattr(pipeline, "run", fake_run)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "--layers", "t/layer_01_a", "--sample-count", "1",
                                      "--jobs", "1", "--out", str(out)])
    assert pipeline.main() == 0
    block = (out / "summary.md").read_text().split("## Commands")[1].split("```")[1]
    cmds = [json.loads(line) for line in block.strip().splitlines()]
    modules = set()
    for c in cmds:
        if c[0] == "make":
            continue
        assert c[0] == sys.executable and c[1] == "-m", c
        modules.add(c[2])
    assert modules == {"snn_scheduler", "weight_trace_gen", "nocsim", "cachesim"}


def test_layers_all_expands_to_every_valid_layer():
    from weight_trace_gen.trace import valid_layer_names
    got = pipeline.resolve_layers("loas", ["all"])
    want = set()
    for d in ("vgg16_T4_n5", "resnet19_T4_n5"):
        meta = json.loads((pipeline.INPUT_TRACE / "loas" / d / "meta.json").read_text())
        want |= {(d, l) for l in valid_layer_names(meta)}
    assert len(got) == len(pipeline.tags("loas")) == len(want) > 20
    assert set(got) == want
