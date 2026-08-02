"""Stage 3 check: the per-burst hit rate from the native replay path.

Calls cachesim.native_bridge directly (the production path, now counting
one access per burst) and reports the hit rate as the number of record.
No second from-scratch counter here: Stage 1's 05_diff_hit_rate.py
already fills the independent cross-check role.

For a cache config whose hand-derived answer is known (the tiny config
below, worked out access by access in the plan) the exact hit and access
counts are checked too; for any other config the numbers are only
reported. Exits non-zero on a failed check.
"""

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "debug" / "weight_traces" / "loas" / "tiny" / "layer_00" / "sample_00000.json.gz"
# Defaults to the tiny config so the default invocation is the one that
# checks against the hand-derived counts; --cache-config takes any other.
TINY_CACHE_CONFIG = REPO_ROOT / "configs" / "cache" / "cache_config_tiny.yaml"

# Plan lines 262-276: 12 per-burst accesses, 2 of them hits.
EXPECTED_COUNTS = {TINY_CACHE_CONFIG: (2, 12)}

# cache_replay reports its hit rate through a "%.6f" text field, so that
# is the precision that wire carries; the counts are exact.
WIRE_PRECISION = 6

sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, load_cache_config  # noqa: E402
from cachesim.native_bridge import native_sample_hit_counts, native_sample_hit_rate  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", default=str(SAMPLE))
    p.add_argument("--cache-config", default=str(TINY_CACHE_CONFIG))
    args = p.parse_args()

    sample_path = pathlib.Path(args.sample)
    config_path = pathlib.Path(args.cache_config).resolve()
    config = load_cache_config(config_path)
    order = list(DIMS)

    rate = native_sample_hit_rate(sample_path, config, order)
    hits, accesses = native_sample_hit_counts(sample_path, config, order)

    print(f"{sample_path} @ {config_path}")
    print(f"  inner_dim={config.inner_dim} line_size_bytes={config.line_size_bytes} "
          f"cache_type={config.cache_type} capacity_lines={config.capacity_lines} policy={config.policy}")
    print(f"  hits={hits} accesses={accesses}")
    print(f"  hit rate: {hits}/{accesses} = {hits / accesses!r} "
          f"(over the wire, at {WIRE_PRECISION} decimals: {rate})")

    expected = EXPECTED_COUNTS.get(config_path)
    if expected is None:
        print("  no hand-derived expectation for this cache config, reporting only")
        return 0
    if (hits, accesses) != expected:
        print(f"  FAIL: expected hits/accesses {expected[0]}/{expected[1]}, got {hits}/{accesses}")
        return 1
    print(f"  PASSED: exactly {expected[0]}/{expected[1]} as hand-derived in the plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
