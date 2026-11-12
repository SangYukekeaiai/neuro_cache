import csv
import json
import pathlib
import sys

import pytest


REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "zoo/wt500_fig3cfg/stokes"))

import sim_shard  # noqa: E402


def _shard(tmp_path, wcts_names):
    shard = tmp_path / "shard_0000"
    wcts_dir = shard / "wcts" / "loas" / "trace" / "layer"
    wcts_dir.mkdir(parents=True)
    for name in wcts_names:
        (wcts_dir / name).write_bytes(b"wcts")
    with (shard / "results_0000.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("arch", "trace_dir", "layer", "sample", "step_cycles", "wcts"))
        writer.writeheader()
        writer.writerow({
            "arch": "loas", "trace_dir": "trace", "layer": "layer", "sample": "0",
            "step_cycles": "step_cycles/loas/trace/layer/sample_00000.json.gz",
            "wcts": "wcts/loas/trace/layer/sample_00000.wcts.gz",
        })
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "l1_size_bytes": 32768, "l1_assoc": 8,
        "l2_size_bytes": 2097152, "l2_assoc": 16,
        "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
        "layout": "khkw_split",
    }))
    binary = tmp_path / "cachesim_run"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    return shard, config, binary


def _fake_run(_binary, _config, row, arm, _wcts, expect_header):
    header = ["arm", "sample"]
    data = [arm, row["sample"]]
    return (header if expect_header else None), data


def test_sim_shard_rejects_unreferenced_wcts(tmp_path, monkeypatch):
    shard, config, binary = _shard(
        tmp_path, ["sample_00000.wcts.gz", "sample_00001.wcts.gz"]
    )
    monkeypatch.setattr(sim_shard, "_run_one", _fake_run)

    with pytest.raises(RuntimeError, match="unreferenced WCTS"):
        sim_shard.run_shard(shard_dir=shard, config=config, binary=binary, workers=2)
    assert (shard / "wcts" / "loas" / "trace" / "layer" / "sample_00000.wcts.gz").exists()
    assert (shard / "wcts" / "loas" / "trace" / "layer" / "sample_00001.wcts.gz").exists()


def test_sim_shard_requires_geometry_config(tmp_path):
    shard, config, binary = _shard(tmp_path, ["sample_00000.wcts.gz"])
    config.write_text("{}")

    with pytest.raises(RuntimeError, match="required geometry fields"):
        sim_shard.run_shard(shard_dir=shard, config=config, binary=binary, workers=2)
    assert (shard / "wcts").exists()


def test_sim_shard_deletes_consumed_wcts_and_is_idempotent(tmp_path, monkeypatch):
    shard, config, binary = _shard(tmp_path, ["sample_00000.wcts.gz"])
    monkeypatch.setattr(sim_shard, "_run_one", _fake_run)

    assert sim_shard.run_shard(shard_dir=shard, config=config, binary=binary, workers=2) == 0
    assert not (shard / "wcts").exists()
    with (shard / "cachesim_results.csv").open(newline="") as handle:
        assert len(list(csv.reader(handle))) == 5

    config.unlink()
    binary.unlink()
    assert sim_shard.run_shard(shard_dir=shard, config=config, binary=binary, workers=2) == 0
