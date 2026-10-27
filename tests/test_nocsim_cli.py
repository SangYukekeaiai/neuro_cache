"""python -m nocsim: the entry point runs, and the --weight-trace reader
refuses a file whose `format` is not step_cycles_v1."""
import gzip
import json
import subprocess
import sys

import pathlib

import pytest

from nocsim.sim import main
from nocsim.step_cycles import load_step_cycles

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_dash_m_nocsim_help():
    r = subprocess.run([sys.executable, "-m", "nocsim", "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "--weight-trace" in r.stdout


def test_rejects_unknown_format(tmp_path):
    """A `format` other than step_cycles_v1 is refused (a file with no
    `format` key, the old full form, is still read)."""
    path = tmp_path / "sample_00000.json.gz"
    with gzip.open(path, "wt") as fh:
        json.dump({"format": "weight_trace_v1", "tiles": []}, fh)
    with pytest.raises(ValueError, match="weight_trace_v1"):
        load_step_cycles(path)


def test_cli_bad_weight_trace_exits_2(tmp_path, capsys):
    path = tmp_path / "sample_00000.json.gz"
    with gzip.open(path, "wt") as fh:
        json.dump({"format": "weight_trace_v1", "tiles": []}, fh)
    rc = main([
        "--schedule", str(REPO / "configs/schedules/loas/vgg16_T4_n5/layer_08_features_27.json"),
        "--layer", str(REPO / "configs/workloads/sample_snn_layer.yaml"),
        "--arch", str(REPO / "configs/arch/loas_inst16_node32kb.yaml"),
        "--out", str(tmp_path / "out.csv"),
        "--weight-trace", str(path),
    ])
    assert rc == 2
    assert "error loading weight trace" in capsys.readouterr().err
