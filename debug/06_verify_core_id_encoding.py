"""Hand-made test 6 (log/2026-08-02-multinode-core-driven-weight-trace-plan.md):
encode_core_id/decode_core_id round-trip, plus the specific worked example
against the real loas multinode schedule's spatial_factors
(outputs/schedules/multinode/loas/resnet19_T4_all/layer_01_layer1_0_conv1.json:
NoCLevel.spatial_splitting.loops = COUT=8, HO=8, WO=2).
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from nocsim.schedule.tiles import decode_core_id, encode_core_id  # noqa: E402
from parsers.layer import DIM_COUT, DIM_HO, DIM_WO  # noqa: E402

# Real loas spatial_factors, cross-checked 2026-08-02 against the actual
# solved schedule (see the plan doc): product = 8*8*2 = 128 = NodeLevel.instances.
LOAS_SPATIAL = {DIM_COUT: 8, DIM_HO: 8, DIM_WO: 2}


def main() -> int:
    failures = []

    # Round trip every core_id in [0, 128).
    n_cores = LOAS_SPATIAL[DIM_COUT] * LOAS_SPATIAL[DIM_HO] * LOAS_SPATIAL[DIM_WO]
    for core_id in range(n_cores):
        idx = decode_core_id(core_id, LOAS_SPATIAL)
        back = encode_core_id(idx, LOAS_SPATIAL)
        if back != core_id:
            failures.append(f"round-trip failed: core_id={core_id} -> {idx} -> {back}")

    # Every decoded index must be in range for its own dim.
    for core_id in range(n_cores):
        idx = decode_core_id(core_id, LOAS_SPATIAL)
        for dim, radix in LOAS_SPATIAL.items():
            if not (0 <= idx[dim] < radix):
                failures.append(f"core_id={core_id}: idx[{dim}]={idx[dim]} out of range [0,{radix})")

    # Every (cout_idx, ho_idx, wo_idx) triple must be hit exactly once across
    # all 128 core_ids -- confirms the encoding is a real bijection onto the
    # full coordinate space, not just a round-trip on the values it happens
    # to produce.
    seen = set()
    for core_id in range(n_cores):
        idx = decode_core_id(core_id, LOAS_SPATIAL)
        key = (idx[DIM_COUT], idx[DIM_HO], idx[DIM_WO])
        if key in seen:
            failures.append(f"coordinate {key} hit more than once (core_id={core_id})")
        seen.add(key)
    if len(seen) != n_cores:
        failures.append(f"only {len(seen)}/{n_cores} distinct coordinates covered")

    # The specific worked example from planning: core_id=57.
    expected = {DIM_WO: 1, DIM_HO: 4, DIM_COUT: 3}
    got = decode_core_id(57, LOAS_SPATIAL)
    for dim, exp_val in expected.items():
        if got[dim] != exp_val:
            failures.append(f"core_id=57: expected {dim}={exp_val}, got {got[dim]}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASS: {n_cores}/{n_cores} core_ids round-trip, bijective onto "
          f"(cout_idx, ho_idx, wo_idx), core_id=57 decodes to "
          f"wo_idx=1, ho_idx=4, cout_idx=3 as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
