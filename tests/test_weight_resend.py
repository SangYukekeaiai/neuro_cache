#!/usr/bin/env python3
"""The weight tile is sent once per reload the schedule calls for, no more.

Weights are indexed by {KH, KW, CIN, COUT} and not by {HO, WO, T}, so a step
that advances only the latter reuses the tile already on the node. The schedule
says how many reloads that leaves: `metrics.temporal_traffic.weight`.

This is a regression test. `StepInfo.weight_changes` used to take noc_i alone
and return True unconditionally at noc_i == 0, which is once per DRAM step, so
any schedule whose DRAM loop carried a weight-invariant dim re-sent the whole
tile on every one of that dim's iterations. The over-send was the product of the
DRAM loop's HO/WO/T factors, which is 1x on some layers and 8x on others, so it
read as a per-layer anomaly in the results rather than as a bug in the sender.

Two tests:

  test_campaign   the four campaign schedules: emitted sends == reloads
                  owed, and the tile count actually streamed == the
                  layer's weight count.
  test_synthetic  a synthetic loop nest, so the property is pinned without
                  the corpus. The DRAM loop carries a weight-invariant dim
                  on purpose: that is the case the old code got wrong, and
                  a nest without one passes either way.
"""
import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

from nocsim.schedule.decode import LoopItem, Schedule, schedule_from_strategy
from nocsim.schedule.steps import StepInfo
from parsers.layer import SNNProb
from weight_trace_gen.trace import build_workload_from_trace

SCHED = ROOT / "configs/schedules/loas"
TRACES = ROOT / "input_trace/loas"

CASES = [
    ("V8",  SCHED / "vgg16_T4_n5/layer_08_features_27.json",        9 * 512 * 512),
    ("V9",  SCHED / "vgg16_T4_n5/layer_09_features_30.json",        9 * 512 * 512),
    ("R9",  SCHED / "resnet19_T4_n5/layer_09_layer2_0_conv2.json",  9 * 256 * 256),
    ("R16", SCHED / "resnet19_T4_n5/layer_16_layer3_0_conv2.json",  9 * 512 * 512),
]


def sends(si, schedule):
    return sum(1
               for d in range(schedule.dram_num_steps)
               for n in range(schedule.noc_num_steps)
               if si.weight_changes(d, n))


def test_campaign(tmp_path):
    failures = []
    for tag, path, weights in CASES:
        meta = json.load(open(TRACES / path.parent.name / "meta.json"))
        layer_yaml = tmp_path / f"{tag}.yaml"
        layer_yaml.write_text(yaml.safe_dump(build_workload_from_trace(meta, path.stem)))
        prob = SNNProb(layer_yaml)
        res = json.load(open(path))["result"]
        schedule = schedule_from_strategy(res["strategy"], prob)
        si = StepInfo(schedule, prob)

        owed = int(res["metrics"]["temporal_traffic"]["weight"])
        got = sends(si, schedule)
        tile = int(res["metrics"]["util"]["weight"])

        if got != owed:
            failures.append(f"{tag}: {got} sends for {owed} reloads "
                            f"({got / owed:.0f}x over)")
        elif tile * got != weights:
            failures.append(f"{tag}: streamed {tile * got:,} elements for a "
                            f"{weights:,}-element layer")
    assert not failures, failures


# A DRAM loop of COUT x 2 outside HO x 2 outside WO x 2. Weights change only
# when COUT ticks, so 2 sends are owed and the old code emitted 8.
def test_synthetic():
    from parsers.layer import DIM_COUT, DIM_HO, DIM_WO

    class FakeProb:
        pass

    # LoopItems are listed inner -> outer, which is what StepInfo consumes.
    dram = [LoopItem(dim=DIM_WO,   dim_name="WO",   factor=2, level=1),
            LoopItem(dim=DIM_HO,   dim_name="HO",   factor=2, level=2),
            LoopItem(dim=DIM_COUT, dim_name="COUT", factor=2, level=3)]
    schedule = Schedule(spatial_factors={}, noc_temporal_loops=[],
                        dram_temporal_loops=dram, data_size={},
                        gb_start=1, dram_start=1, perm_levels=0)
    si = StepInfo(schedule, FakeProb())

    got = sends(si, schedule)
    assert got == 2, f"synthetic: {got} sends for a nest owing 2"
