import pathlib
import shutil
import sys

from snn_scheduler import cli

ROOT = pathlib.Path(__file__).resolve().parents[1]
V8 = ROOT / "configs/schedules/loas/vgg16_T4_n5/layer_08_features_27.json"


def test_solve_trace_skips_cached(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "gurobipy", raising=False)
    cached = tmp_path / "loas/vgg16_T4_n5/layer_08_features_27.json"
    cached.parent.mkdir(parents=True)
    shutil.copy(V8, cached)
    before = cached.read_bytes()
    rc = cli.main(["solve-trace", "--arch", "loas", "--trace-root", "input_trace/loas",
                   "--trace-dirs", "vgg16_T4_n5", "--layers", "layer_08_features_27",
                   "--cache-dir", str(tmp_path)])
    assert rc == 0
    assert cached.read_bytes() == before
    assert "gurobipy" not in sys.modules


def test_default_arch_yaml_is_the_16_node_one():
    args = cli._build_parser().parse_args(
        ["solve-trace", "--arch", "loas", "--trace-dirs", "x", "--cache-dir", "c"])
    path = cli._default_arch_yaml(args)
    assert path.as_posix().endswith("configs/arch/loas_inst16_node32kb.yaml")
    assert path.is_file()
