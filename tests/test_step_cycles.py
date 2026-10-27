from types import SimpleNamespace

import pytest

from nocsim.step_cycles import load_step_cycles, save_step_cycles
from weight_trace_gen import ComputeCycles
from weight_trace_gen.weight_trace import (CoreEntry, LayerWeightTrace, TickEntry,
                                           TileWeightTrace)

DIMS = {"KH": 3, "KW": 3, "CIN": 8, "COUT": 4, "HO": 2, "WO": 2, "T": 4,
        "shape": "snn-layer"}


def two_tile_trace():
    ticks = [TickEntry(tick=0, cores=[CoreEntry(core_id=0, weight_addresses=[0, 1])])]
    return LayerWeightTrace(
        arch="loas", trace_dir="vgg16_T4_n5", layer_name="layer_08_features_27",
        sample_idx=3, workload_dims=DIMS, dram_num_steps=2, noc_num_steps=1,
        tiles=[TileWeightTrace(dram_i=0, noc_i=0, mac_cycles=100, lif_cycles=7, ticks=ticks),
               TileWeightTrace(dram_i=1, noc_i=0, mac_cycles=250, lif_cycles=None, ticks=ticks)])


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "sample_00003.json.gz"
    save_step_cycles(two_tile_trace(), path)
    sc = load_step_cycles(path)
    assert sc.by_step == {(0, 0): ComputeCycles(mac_cycles=100, lif_cycles=7),
                          (1, 0): ComputeCycles(mac_cycles=250, lif_cycles=None)}
    assert (sc.arch, sc.trace_dir, sc.layer_name, sc.sample_idx) == (
        "loas", "vgg16_T4_n5", "layer_08_features_27", 3)
    assert sc.workload_dims == DIMS
    assert (sc.dram_num_steps, sc.noc_num_steps) == (2, 1)


def test_check_against_mismatch_raises(tmp_path):
    path = tmp_path / "sample_00003.json.gz"
    save_step_cycles(two_tile_trace(), path)
    sc = load_step_cycles(path)
    artifact = SimpleNamespace(arch="loas", trace_dir="vgg16_T4_n5",
                               layer_name="layer_09_features_30", workload={"problem": DIMS})
    schedule = SimpleNamespace(dram_num_steps=2, noc_num_steps=1)
    with pytest.raises(ValueError, match="layer_name: trace=layer_08_features_27 "
                                         "schedule=layer_09_features_30"):
        sc.check_against(artifact, schedule)
