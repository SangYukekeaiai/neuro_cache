"""Stage 1 parity check: packed-Python vs native-C++ hit rate.

Replays one persisted weight-trace sample through the packed pure-Python
cache.py/layout.py/sweep.py path in dump/python_reference/ and through
cachesim.native_bridge, then diffs the exact hit and access counts.
Exits non-zero on any difference.
"""

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WEIGHT_TRACE_ROOT = REPO_ROOT / "debug" / "weight_traces"
CACHE_CONFIG = REPO_ROOT / "configs" / "cache" / "cache_config.yaml"

sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, load_cache_config  # noqa: E402
from cachesim.native_bridge import native_sample_hit_counts  # noqa: E402
from python_reference.cachesim.sweep import sample_hit_counts  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", required=True, help=f"a sample_*.json.gz under {WEIGHT_TRACE_ROOT}")
    p.add_argument("--cache-config", default=str(CACHE_CONFIG))
    args = p.parse_args()

    sample_path = pathlib.Path(args.sample)
    config = load_cache_config(pathlib.Path(args.cache_config))
    order = list(DIMS)

    py_hits, py_accesses = sample_hit_counts(sample_path, config, order)
    native_hits, native_accesses = native_sample_hit_counts(sample_path, config, order)

    print(f"{sample_path} @ {args.cache_config}")
    print(f"  python: hits={py_hits} accesses={py_accesses}")
    print(f"  native: hits={native_hits} accesses={native_accesses}")
    if (py_hits, py_accesses) != (native_hits, native_accesses):
        print("DIFF: hit and access counts disagree")
        return 1
    rate = (py_hits / py_accesses) if py_accesses else 0.0
    print(f"DIFF EMPTY: hit rate {py_hits}/{py_accesses} = {rate:.6f} from both paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
