"""Verify the fixed-grid native sweep against 24 single-config replays."""

import gzip
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, hybrid_config_from_dims  # noqa: E402
from cachesim.native_bridge import native_hierarchical_stats, native_hierarchical_sweep  # noqa: E402


DIMS_BY_NAME = {"KH": 1, "KW": 1, "CIN": 12, "COUT": 8}
EVENTS = {
    "A": [0, 0, 0, 0, 4],
    "B": [0, 0, 0, 4, 8],
    "C": [0, 0, 4, 0, 4],
    "D": [0, 0, 4, 4, 8],
}
TICKS = [
    {0: ["A"], 1: ["B"]},
    {0: ["B"], 1: ["A"]},
    {0: ["C"], 1: ["D"]},
    {0: ["A"], 1: ["B"]},
]


def sample_data():
    return {
        "arch": "handmade",
        "trace_dir": "test17",
        "layer_name": "layer_00",
        "sample_idx": 0,
        "workload_dims": DIMS_BY_NAME,
        "dram_num_steps": 1,
        "noc_num_steps": 1,
        "tiles": [{
            "dram_i": 0,
            "noc_i": 0,
            "mac_cycles": 1,
            "lif_cycles": None,
            "ticks": [
                {
                    "tick": tick_i,
                    "cores": [
                        {"core_id": core_id, "weight_addresses": [EVENTS[name] for name in names]}
                        for core_id, names in sorted(cores.items())
                    ],
                }
                for tick_i, cores in enumerate(TICKS)
            ],
        }],
    }


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sample_00000.json.gz"
        with gzip.open(path, "wt") as output:
            json.dump(sample_data(), output)

        sweep = native_hierarchical_sweep(path, DIMS)
        if len(sweep) != 24:
            failures.append(f"expected 24 sweep points, got {len(sweep)}")

        keys = set()
        for result in sweep:
            key = (result.cache_type, result.associativity, result.l1_size_bytes, result.l2_size_bytes)
            if key in keys:
                failures.append(f"duplicate sweep point {key}")
            keys.add(key)
            l1 = hybrid_config_from_dims(
                DIMS_BY_NAME, result.l1_size_bytes, result.cache_type, result.associativity
            )
            l2 = hybrid_config_from_dims(
                DIMS_BY_NAME, result.l2_size_bytes, result.cache_type, result.associativity
            )
            single = native_hierarchical_stats(
                path, l1, l2, DIMS, l2_prefetch=True, same_tick_pinning=True
            )
            if result.stats != single:
                failures.append(f"{key}: sweep {result.stats} != single {single}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("PASS: all 24 fixed-grid sweep results exactly match the single-config native replay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
