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

Two checks:

  A  the four campaign schedules: emitted sends == reloads owed, and the tile
     count actually streamed == the layer's weight count.
  B  a synthetic loop nest, so the property is pinned without the corpus. The
     DRAM loop carries a weight-invariant dim on purpose: that is the case the
     old code got wrong, and a nest without one passes either way.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nocsim.schedule.decode import LoopItem, Schedule, schedule_from_strategy
from nocsim.schedule.steps import StepInfo
from parsers.layer import SNNProb

CAMPAIGN = ROOT / "profiling/0823_stagewise_verify"
SCHED = CAMPAIGN / "stage2_weight_trace/inputs/schedules/loas"
LAYERS = CAMPAIGN / "stage3_nocsim/inputs/layers"

CASES = [
    ("V8",  SCHED / "vgg16_T4_n5/layer_08_features_27.json",        9 * 512 * 512),
    ("V9",  SCHED / "vgg16_T4_n5/layer_09_features_30.json",        9 * 512 * 512),
    ("R9",  SCHED / "resnet19_T4_n5/layer_09_layer2_0_conv2.json",  9 * 256 * 128),
    ("R16", SCHED / "resnet19_T4_n5/layer_16_layer3_0_conv2.json",  9 * 512 * 256),
]


def sends(si, schedule):
    return sum(1
               for d in range(schedule.dram_num_steps)
               for n in range(schedule.noc_num_steps)
               if si.weight_changes(d, n))


def check_campaign():
    failures = []
    for tag, path, weights in CASES:
        if not path.exists():
            print(f"check A  {tag}: SKIP, no schedule at {path}")
            continue
        prob = SNNProb(LAYERS / f"{tag}.yaml")
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
        else:
            print(f"check A  {tag}: {got} sends, {tile:,} elements each, "
                  f"{tile * got:,} streamed == layer weights   OK")
    return failures


# A DRAM loop of COUT x 2 outside HO x 2 outside WO x 2. Weights change only
# when COUT ticks, so 2 sends are owed and the old code emitted 8.
def check_synthetic():
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
    if got != 2:
        return [f"synthetic: {got} sends for a nest owing 2"]
    print(f"check B  synthetic COUTx2 -> HOx2 -> WOx2: "
          f"{schedule.dram_num_steps} steps, {got} sends   OK")
    return []


def main():
    failures = check_campaign() + check_synthetic()
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
