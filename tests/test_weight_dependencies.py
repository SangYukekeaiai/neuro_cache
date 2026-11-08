"""Weight banks wait for consumers; every MAC waits for its resident tile."""

from pathlib import Path

import pytest
import yaml

from lays.nocsim.combine import combine
from lays.nocsim.schedule.buf_spatial import BufSpatial
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.steps import StepInfo
from lays.parsers.arch import SNNArch
from lays.parsers.bitwidths import SNNBitwidths
from lays.parsers.layer import SNNProb


def transactions(tmp_path, placement, streaming=False, single_node=True):
    layer = tmp_path / "layer.yaml"
    layer.write_text(yaml.safe_dump({"problem": {
        "KH": 1, "KW": 1, "CIN": 4, "COUT": 4 if single_node else 8,
        "HO": 2, "WO": 1, "T": 1, "shape": "snn-layer",
    }}))
    prob = SNNProb(layer)
    loops = [{"dim": "COUT", "size": 4}, {"dim": "HO", "size": 2}]
    if streaming:
        loops.reverse()
    strategy = {
        "NoCLevel": {
            "temporal_permutation": {"loops": loops if placement == "noc" else []},
            "spatial_splitting": {"loops": [] if single_node else [{"dim": "COUT", "size": 2}]},
        },
        "DRAM": {"temporal_permutation": {"loops": loops if placement == "dram" else []}},
    }
    schedule = schedule_from_strategy(strategy, prob)
    arch_name = "spinalflow.yaml" if single_node else "loas_inst16_node32kb.yaml"
    arch_path = Path(__file__).resolve().parents[1] / "examples/arch" / arch_name
    return combine(schedule, BufSpatial(schedule, prob), StepInfo(schedule, prob),
                   prob, SNNBitwidths(arch_path), arch=SNNArch(arch_path)).tcs


@pytest.mark.parametrize("placement,streaming", [("dram", False), ("noc", False), ("noc", True)])
def test_single_node_weight_dependencies(tmp_path, placement, streaming):
    tcs = transactions(tmp_path, placement, streaming)
    sends = [tc for tc in tcs if tc.annotation.startswith("weight_")]
    macs = [tc for tc in tcs if tc.annotation.startswith("mac_")]
    resident_tiles = list(range(8)) if streaming else [0, 0, 1, 1, 2, 2, 3, 3]
    assert len(macs) == 8
    assert len(sends) == (8 if streaming else 4)

    for tile, send in enumerate(sends):
        # Both initial banks are empty; reuse waits for ALL consumers of m-2.
        expected = [mac.tc_id for mac, resident in zip(macs, resident_tiles)
                    if resident == tile - 2]
        if placement == "noc" and streaming and tile > 0:
            expected.append(sends[tile - 1].tc_id)
        assert send.deps == expected

    for step, (mac, tile) in enumerate(zip(macs, resident_tiles)):
        expected = [sends[tile].tc_id]
        if placement == "noc" and step >= 2:
            expected.append(macs[step - 2].tc_id)
        assert mac.deps == expected


def test_multinode_resident_macs_wait_for_weight_sends(tmp_path):
    tcs = transactions(tmp_path, "dram", single_node=False)
    for tile in range(4):
        sends = [tc.tc_id for tc in tcs
                 if tc.annotation.startswith(f"weight_{2 * tile}_0__")]
        assert len(sends) == 2
        for step in (2 * tile, 2 * tile + 1):
            macs = [tc for tc in tcs if tc.annotation.startswith(f"mac_{step}_0__")]
            assert len(macs) == 2
            assert all(tc.deps == sends for tc in macs)
