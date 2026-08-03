"""Hand-made test 5 (log/2026-08-02-multinode-core-driven-weight-trace-plan.md):
tracegen.assemble_layer_traces must set a tile's mac_cycles to the MAX over
its cores' own local cycle counts, not the sum, average, or first-seen
value -- consistent with the lock-step assumption (the tile can't finish
before its slowest core does).

Fixture: one (dram_i=0, noc_i=0) tile, 2 cores -- core 0 reports
mac_cycles=4, core 1 reports mac_cycles=3 (finishes earlier, matching the
"core absent at later ticks" case already covered by debug/08).
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from archmodels import NodeTileSpec  # noqa: E402
from tracegen import assemble_layer_traces  # noqa: E402

TILES = [
    NodeTileSpec(dram_i=0, noc_i=0, core_id=0, node_bound={}, tile_offset={}, is_last_K=True),
    NodeTileSpec(dram_i=0, noc_i=0, core_id=1, node_bound={}, tile_offset={}, is_last_K=True),
]

# (tile_idx, local_sample_idx, mac_cycles, ticks) -- tile_idx 0 is core 0
# (TILES[0]), tile_idx 1 is core 1 (TILES[1]), both at the same (dram_i, noc_i).
UNPACKED = [
    (0, 0, 4, [{"tick": 0, "weight_addresses": [[1, 1, 0, 0, 4]]},
               {"tick": 1, "weight_addresses": [[1, 1, 1, 0, 4], [1, 1, 1, 4, 8]]},
               {"tick": 3, "weight_addresses": [[1, 1, 2, 0, 4]]}]),
    (1, 0, 3, [{"tick": 0, "weight_addresses": [[1, 1, 0, 4, 8]]},
               {"tick": 2, "weight_addresses": [[1, 1, 2, 4, 8]]}]),
]


def main() -> int:
    result = assemble_layer_traces(
        TILES, sample_indices=[42], unpacked=UNPACKED,
        arch_name="loas", trace_dir_name="tiny", layer_name="layer_00",
        workload_dims={}, dram_num_steps=1,
    )

    failures = []
    if len(result) != 1:
        failures.append(f"expected 1 LayerWeightTrace (1 sample), got {len(result)}")
    else:
        layer = result[0]
        if layer.sample_idx != 42:
            failures.append(f"expected sample_idx=42, got {layer.sample_idx}")
        if len(layer.tiles) != 1:
            failures.append(f"expected 1 merged tile (both cores share (dram_i=0,noc_i=0)), got {len(layer.tiles)}")
        else:
            tile = layer.tiles[0]
            if tile.mac_cycles != 4:
                failures.append(f"expected mac_cycles=max(4,3)=4, got {tile.mac_cycles}")
            if len(tile.ticks) != 4:
                failures.append(f"expected 4 tick groups (0,1,2,3), got {len(tile.ticks)}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: merged tile's mac_cycles = max(4, 3) = 4, not sum (7) or first-seen (4 by luck)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
