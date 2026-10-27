"""scripts/profile_all_layers.py without running the tools: the task list read
from meta.json, --task-index and --layer selection, --dry-run output, and the merge step."""
import csv
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import profile_all_layers as pal  # noqa: E402


def capture(root, name, layers, n_samples=5, params=None):
    """A trace dir with a meta.json; `layers` maps name -> [T, B, Cin, Hin, Win],
    each a 3x3 stride-1 conv unless `params` says otherwise."""
    d = root / name
    d.mkdir(parents=True)
    lp = {n: {"cout": s[2], "kernel": 3, "stride": 1} for n, s in layers.items()}
    lp.update(params or {})
    (d / "meta.json").write_text(json.dumps({"n_samples": n_samples, "layers": layers, "layer_params": lp}))


@pytest.fixture
def trace_root(tmp_path):
    root = tmp_path / "traces"
    capture(root, "vgg", {"v1": [4, 5, 64, 8, 8], "v2": [4, 5, 64, 8, 8]})
    # valid_layer_names drops r_bad (Hin = Win = 0 gives no 3x3 output) and the
    # 1x1 stride-2 shortcut r_sc (the arch models replay only 3x3 stride-1 convs).
    capture(root, "res", {"r1": [4, 5, 32, 4, 4], "r_bad": [4, 5, 32, 0, 0], "r_sc": [4, 5, 32, 4, 4]},
            params={"r_sc": {"cout": 64, "kernel": 1, "stride": 2}})
    (root / "notes").mkdir()
    return root


def test_tasks_are_every_valid_layer_in_sorted_trace_dirs_and_meta_order(trace_root):
    assert pal.tasks(trace_root) == [("res", "r1"), ("vgg", "v1"), ("vgg", "v2")]


def run_main(capsys, *argv):
    rc = pal.main(list(argv))
    return rc, capsys.readouterr().out


def test_dry_run_prints_one_array_task_command_per_layer(trace_root, tmp_path, capsys):
    rc, out = run_main(capsys, "--bench", "loas", "--trace-root", str(trace_root),
                       "--out", str(tmp_path / "o"), "--n-samples", "5", "--dry-run")
    lines = [ln for ln in out.splitlines() if ln.startswith("task ")]
    assert rc == 0 and len(lines) == 3
    assert "res/r1" in lines[0] and "--task-index 0" in lines[0]
    assert "vgg/v2" in lines[2] and "--task-index 2" in lines[2]
    assert "--n-samples 5" in lines[2]


def test_dry_run_of_one_task_prints_its_stream_and_sweep_commands(trace_root, tmp_path, capsys):
    rc, out = run_main(capsys, "--bench", "loas", "--trace-root", str(trace_root),
                       "--out", str(tmp_path / "o"), "--n-samples", "2",
                       "--task-index", "1", "--dry-run")
    assert rc == 0
    gens = [ln for ln in out.splitlines() if "generate_weight_traces.py" in ln]
    sweeps = [ln for ln in out.splitlines() if "cachesim_sweep" in ln]
    assert len(gens) == 2 and all("--layer v1" in g for g in gens)
    assert "--sample-start 0" in gens[0] and "--sample-start 1" in gens[1]
    # the default khkw grid is three cin_block groups, so three sweeps per sample
    assert len(sweeps) == 6
    assert str(tmp_path / "o" / "layers" / "vgg" / "v1.csv") in out


def test_task_index_out_of_range_is_refused(trace_root, tmp_path):
    with pytest.raises(SystemExit, match="task index 3"):
        pal.main(["--trace-root", str(trace_root), "--out", str(tmp_path),
                  "--n-samples", "5", "--task-index", "3", "--dry-run"])


def test_layer_selects_the_same_task_as_its_index(trace_root, tmp_path, capsys):
    rc, out = run_main(capsys, "--trace-root", str(trace_root), "--out", str(tmp_path / "o"),
                       "--n-samples", "1", "--layer", "vgg/v2", "--dry-run")
    assert rc == 0 and out.startswith("# task 2: vgg/v2")
    with pytest.raises(SystemExit, match="unknown layer 'vgg/v9'"):
        pal.main(["--trace-root", str(trace_root), "--out", str(tmp_path), "--layer", "vgg/v9", "--dry-run"])


@pytest.mark.parametrize("args", [["--n-samples", "0"], ["--jobs", "0"]])
def test_counts_below_one_are_refused(trace_root, tmp_path, capsys, args):
    with pytest.raises(SystemExit):
        pal.main(["--trace-root", str(trace_root), "--out", str(tmp_path), "--dry-run", *args])
    assert "must be at least 1" in capsys.readouterr().err


def test_more_samples_than_the_capture_has_is_refused(trace_root, tmp_path):
    with pytest.raises(SystemExit, match="6 samples"):
        pal.main(["--trace-root", str(trace_root), "--out", str(tmp_path),
                  "--n-samples", "6", "--task-index", "0", "--dry-run"])


def test_count_prints_the_number_of_tasks(trace_root, tmp_path, capsys):
    rc, out = run_main(capsys, "--trace-root", str(trace_root), "--out", str(tmp_path), "--count")
    assert rc == 0 and out.strip() == "3"


def test_grid_groups_split_on_cin_block_and_keep_grid_index_names():
    grid = [{"cin_block": 4}, {"cin_block": 8}, {"cin_block": 4}]
    assert pal.grid_groups("g", grid) == [
        (["g_00", "g_02"], [{"cin_block": 4}, {"cin_block": 4}]),
        (["g_01"], [{"cin_block": 8}])]


def test_schedule_root_prefers_the_tracked_schedule(tmp_path):
    d, layer = "vgg16_T4_n5", "layer_08_features_27"
    assert pal.schedule_root("loas", d, layer, tmp_path) == (pal.wb.SCHEDULES, True)
    assert pal.schedule_root("loas", d, "no_such_layer", tmp_path) == (tmp_path / "schedules", False)


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_merge_joins_layer_csvs_in_task_order_and_reports_missing(trace_root, tmp_path, capsys):
    out = tmp_path / "o"
    write_csv(out / "layers/vgg/v2.csv", ["config", "total_cycles"], [["c0", "7"]])
    write_csv(out / "layers/res/r1.csv", ["config", "total_cycles"], [["c0", "5"], ["c1", "6"]])
    rc, text = run_main(capsys, "--trace-root", str(trace_root), "--out", str(out), "--merge")
    with open(out / "all_layers.csv", newline="") as f:
        merged = list(csv.reader(f))
    assert merged == [["config", "total_cycles"], ["c0", "5"], ["c1", "6"], ["c0", "7"]]
    assert rc == 1 and "vgg/v1" in text


def test_merge_refuses_layer_csvs_with_different_headers(trace_root, tmp_path):
    out = tmp_path / "o"
    write_csv(out / "layers/res/r1.csv", ["config", "total_cycles"], [["c0", "5"]])
    write_csv(out / "layers/vgg/v1.csv", ["config", "cycles"], [["c0", "5"]])
    with pytest.raises(SystemExit, match="header"):
        pal.main(["--trace-root", str(trace_root), "--out", str(out), "--merge"])


def test_a_trace_root_without_any_meta_json_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="no meta.json"):
        pal.main(["--trace-root", str(tmp_path), "--out", str(tmp_path), "--dry-run"])
