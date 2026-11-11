import importlib.util
import json
import pathlib
import sys
from types import SimpleNamespace


REPO = pathlib.Path(__file__).resolve().parents[1]
GEN_PATH = REPO / "zoo/wt500_fig3cfg/gen_inputs.py"
SPEC = importlib.util.spec_from_file_location("wt500_gen_inputs", GEN_PATH)
GEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = GEN
SPEC.loader.exec_module(GEN)


def _loas_tile(tile_offset=None):
    from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
    from lays.weight_trace_gen import NodeTileSpec

    return NodeTileSpec(
        dram_i=0,
        node_bound={
            DIM_HO: 1, DIM_WO: 1, DIM_KH: 1, DIM_KW: 1,
            DIM_CIN: 3, DIM_COUT: 4, DIM_T: 2,
        },
        tile_offset=tile_offset or {DIM_CIN: 0, DIM_T: 0},
        is_last_K=True,
    )


def test_bridge_gate_allows_missing_output_offsets_for_one_by_one_problem():
    problem = {
        "KH": 1, "KW": 1, "CIN": 3, "COUT": 4,
        "HO": 1, "WO": 1, "T": 2,
    }
    assert GEN._bridge_tile_violations("loas", _loas_tile(), problem, 0) == []


def test_bridge_gate_rejects_missing_output_offset_when_problem_is_split():
    problem = {
        "KH": 1, "KW": 1, "CIN": 3, "COUT": 4,
        "HO": 1, "WO": 2, "T": 2,
    }
    violations = GEN._bridge_tile_violations("loas", _loas_tile(), problem, 0)
    assert any(v["code"] == "missing_pixel_offset" and v["dimension"] == "WO"
               for v in violations)


def test_schedule_cache_uses_config_content_hashes(tmp_path):
    arch_yaml = tmp_path / "arch.yaml"
    mapspace_yaml = tmp_path / "mapspace.yaml"
    arch_yaml.write_text("arch: one\n")
    mapspace_yaml.write_text("mapspace: one\n")
    capture = SimpleNamespace(name="capture")
    workload = {"problem": {"KH": 3}}
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps({
        "arch": "loas",
        "trace_dir": "capture",
        "layer_name": "layer",
        "workload": workload,
        "result": {
            "has_solution": True,
            "strategy": {},
            "configs": {"arch": str(arch_yaml), "dataflow": str(mapspace_yaml)},
        },
        "arch_yaml_sha256": GEN.sha256_file(arch_yaml),
        "mapspace_yaml_sha256": GEN.sha256_file(mapspace_yaml),
    }))

    assert GEN._artifact_matches(
        path, "loas", capture, "layer", workload, arch_yaml, mapspace_yaml,
    )
    mapspace_yaml.write_text("mapspace: changed\n")
    assert not GEN._artifact_matches(
        path, "loas", capture, "layer", workload, arch_yaml, mapspace_yaml,
    )


def test_solve_pair_caches_unchanged_configs_and_resolves_after_edit(tmp_path, monkeypatch):
    arch_yaml = tmp_path / "arch.yaml"
    mapspace_yaml = tmp_path / "mapspace.yaml"
    arch_yaml.write_text("arch: one\n")
    mapspace_yaml.write_text("mapspace: one\n")
    output_dir = tmp_path / "out"
    workload = {"problem": {"KH": 3}}
    capture = SimpleNamespace(
        name="capture", relative_dir="capture", workloads={"layer": workload},
    )
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        out_path = pathlib.Path(command[command.index("--out") + 1])
        out_path.write_text(json.dumps({
            "status": "OPTIMAL",
            "has_solution": True,
            "strategy": {},
            "configs": {"arch": str(arch_yaml.resolve()), "dataflow": str(mapspace_yaml.resolve())},
        }))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    def fake_artifact(arch, cap, layer, current_workload, result, current_arch, current_mapspace):
        return {
            "arch": arch,
            "trace_dir": cap.name,
            "layer_name": layer,
            "workload": current_workload,
            "result": result,
            "dram_num_steps": 1,
            "mode": "base",
            "arch_yaml_sha256": GEN.sha256_file(current_arch),
            "mapspace_yaml_sha256": GEN.sha256_file(current_mapspace),
        }

    monkeypatch.setattr(GEN.subprocess, "run", fake_run)
    monkeypatch.setattr(GEN, "_make_artifact", fake_artifact)

    kwargs = {
        "arch": "loas", "capture": capture, "layer_name": "layer",
        "workload": workload, "output_dir": output_dir,
        "arch_yaml": arch_yaml, "mapspace_yaml": mapspace_yaml,
        "conda_env": "base", "conda_exe": "conda", "force": False,
        "dry_run": False,
    }
    assert GEN._solve_pair(**kwargs)["status"] == "SOLVED"
    assert GEN._solve_pair(**kwargs)["status"] == "CACHED"
    assert len(calls) == 1

    mapspace_yaml.write_text("mapspace: changed\n")
    assert GEN._solve_pair(**kwargs)["status"] == "SOLVED"
    assert len(calls) == 2
