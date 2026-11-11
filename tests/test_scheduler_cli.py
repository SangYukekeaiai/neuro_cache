import json
import pathlib
import shutil
import sys
from types import SimpleNamespace

from lays.scheduler import cli
from lays.scheduler.artifact import sha256_file

ROOT = pathlib.Path(__file__).resolve().parents[1]
V8 = ROOT / "examples/schedules/loas/vgg16_T4_n5/layer_08_features_27.json"


def test_solve_trace_skips_cached(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "gurobipy", raising=False)
    cached = tmp_path / "loas/vgg16_T4_n5/layer_08_features_27.json"
    cached.parent.mkdir(parents=True)
    shutil.copy(V8, cached)
    artifact = json.loads(cached.read_text())
    artifact["arch_yaml_sha256"] = sha256_file(ROOT / "examples/arch/loas_inst16_node32kb.yaml")
    artifact["mapspace_yaml_sha256"] = sha256_file(ROOT / "examples/node_mapspace/loas.yaml")
    cached.write_text(json.dumps(artifact))
    before = cached.read_bytes()
    rc = cli.main(["solve-trace", "--arch", "loas", "--trace-root", "examples/input_trace/loas",
                   "--trace-dirs", "vgg16_T4_n5", "--layers", "layer_08_features_27",
                   "--cache-dir", str(tmp_path)])
    assert rc == 0
    assert cached.read_bytes() == before
    assert "gurobipy" not in sys.modules


def test_solve_trace_re_solves_when_config_hash_changes(tmp_path, monkeypatch):
    arch_yaml = tmp_path / "arch.yaml"
    mapspace_yaml = tmp_path / "mapspace.yaml"
    arch_yaml.write_text("arch: original\n")
    mapspace_yaml.write_text("mapspace: original\n")

    cached = tmp_path / "loas/vgg16_T4_n5/layer_08_features_27.json"
    cached.parent.mkdir(parents=True)
    artifact = json.loads(V8.read_text())
    artifact["arch_yaml_sha256"] = sha256_file(arch_yaml)
    artifact["mapspace_yaml_sha256"] = sha256_file(mapspace_yaml)
    cached.write_text(json.dumps(artifact))

    calls = []

    def fake_solve(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(dram_num_steps=1)

    monkeypatch.setattr("lays.scheduler.artifact.solve_and_cache_schedule", fake_solve)
    common = [
        "solve-trace", "--arch", "loas", "--trace-root", "examples/input_trace/loas",
        "--trace-dirs", "vgg16_T4_n5", "--layers", "layer_08_features_27",
        "--cache-dir", str(tmp_path), "--arch-yaml", str(arch_yaml),
        "--node-mapspace", str(mapspace_yaml),
    ]

    assert cli.main(common) == 0
    assert calls == []

    mapspace_yaml.write_text("mapspace: edited\n")
    assert cli.main(common) == 0
    assert len(calls) == 1


def test_default_arch_yaml_is_the_16_node_one():
    args = cli._build_parser().parse_args(
        ["solve-trace", "--arch", "loas", "--trace-dirs", "x", "--cache-dir", "c"])
    path = cli._default_arch_yaml(args)
    assert path.as_posix().endswith("examples/arch/loas_inst16_node32kb.yaml")
    assert path.is_file()


def test_solve_trace_applies_layers_only_to_dirs_that_have_them(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "gurobipy", raising=False)
    cached = tmp_path / "loas/vgg16_T4_n5/layer_08_features_27.json"
    cached.parent.mkdir(parents=True)
    shutil.copy(V8, cached)
    artifact = json.loads(cached.read_text())
    artifact["arch_yaml_sha256"] = sha256_file(ROOT / "examples/arch/loas_inst16_node32kb.yaml")
    artifact["mapspace_yaml_sha256"] = sha256_file(ROOT / "examples/node_mapspace/loas.yaml")
    cached.write_text(json.dumps(artifact))
    rc = cli.main(["solve-trace", "--arch", "loas", "--trace-root", "examples/input_trace/loas",
                   "--trace-dirs", "vgg16_T4_n5", "resnet19_T4_n5",
                   "--layers", "layer_08_features_27", "--cache-dir", str(tmp_path)])
    assert rc == 0
    assert "gurobipy" not in sys.modules
    rows = (tmp_path / "summary.csv").read_text().splitlines()[1:]
    assert rows == ["loas,vgg16_T4_n5,layer_08_features_27,SKIPPED,,"]
