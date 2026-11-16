"""DRAM payload accounting is separate from packet rounding and on-chip traffic."""
import json
from pathlib import Path

import pytest
import yaml

from lays.nocsim.core.generator import TC_Generator
from lays.nocsim.core.noc import NoC
from lays.nocsim import sim
from lays.parsers.layer import SNNProb
from lays.parsers.bitwidths import SNNBitwidths
from lays.parsers.arch import SNNArch

REPO = Path(__file__).resolve().parents[1]


def test_bytes_both_directions_and_direct_node_paths():
    noc = NoC(2, 2)
    gen = TC_Generator(noc)
    assert gen.dram_bytes == {"weight": 0, "psum": 0, "vmem": 0}
    gen.unicast("weight", 33 * 8, 8, noc.dram_port, noc.gb_port, [], "load")
    gen.unicast("psum", 3 * 8, 8, noc.gb_port, noc.dram_port, [], "store")
    gen.unicast("weight", 8, 8, noc.dram_port, 0, [], "single_load")
    gen.unicast("vmem", 32, 32, 0, noc.dram_port, [], "single_store")
    assert gen.dram_bytes == {"weight": 34, "psum": 3, "vmem": 4}
    assert gen.dram_cost == {"weight": 2, "psum": 1, "vmem": 1}
    gen.unicast("weight", 800, 8, noc.gb_port, 0, [], "local")
    gen.multicast("weight", 800, 8, noc.gb_port, [0, 1], [], "multicast")
    gen.count(100, 0, [], "compute")
    assert gen.dram_bytes == {"weight": 34, "psum": 3, "vmem": 4}
    assert gen.dram_cost == {"weight": 2, "psum": 1, "vmem": 1}


@pytest.mark.parametrize("single_node", [False, True])
def test_cli_bytes_and_unchanged_tuple_api(tmp_path, capsys, single_node):
    layer = tmp_path / "layer.yaml"
    layer.write_text(yaml.safe_dump({"problem": {"shape": "snn-layer", "T": 1,
        "KH": 1, "KW": 1, "CIN": 4, "COUT": 4, "HO": 1, "WO": 1}}))
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps({"has_solution": True, "strategy": {
        "NoCLevel": {"temporal_permutation": {"loops": []}, "spatial_splitting": {"loops": []}},
        "DRAM": {"temporal_permutation": {"loops": []}}}}))
    arch = REPO / "examples/arch" / ("spinalflow.yaml" if single_node else "loas_inst16_node32kb.yaml")
    byte_counts = {}
    args = (schedule, SNNProb(layer), SNNBitwidths(arch), tmp_path / "api.csv")
    legacy = sim.run_from_json(*args, arch=SNNArch(arch))
    current = sim.run_from_json(*args, arch=SNNArch(arch), dram_bytes=byte_counts)
    assert len(current) == 3 and current == legacy
    assert byte_counts == {"weight": 16, "psum": 0, "vmem": 0}
    assert sim.main(["--schedule", str(schedule), "--layer", str(layer),
                     "--arch", str(arch), "--out", str(tmp_path / "cli.csv")]) == 0
    lines = capsys.readouterr().out.splitlines()
    for var, value in byte_counts.items():
        line = next(line for line in lines if line.strip().startswith(var + " "))
        assert f"dram_bytes={value}" in line
        assert f"dram_cost={current[2][var]}" in line
    assert (tmp_path / "cli.csv").read_bytes() == (tmp_path / "api.csv").read_bytes()
