"""Stage 3 debugging aid: every element and cache-line tag, per burst.

Uses the packed pure-Python layout.py in dump/python_reference/ purely as
a debugging aid. This is NOT the production path (production replay runs
through src/cachesim's native cache_replay binary); it exists so a human
can read, one burst at a time, which expanded (kh, kw, cin, cout)
elements collapse to the same cache-line tag before deduplication.
"""

import argparse
import gzip
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "debug" / "weight_traces" / "loas" / "tiny" / "layer_00" / "sample_00000.json.gz"
CACHE_CONFIG = REPO_ROOT / "configs" / "cache" / "cache_config.yaml"

sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, load_cache_config  # noqa: E402
from python_reference.cachesim.layout import element_tags, expand_events  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", default=str(SAMPLE))
    p.add_argument("--cache-config", default=str(CACHE_CONFIG))
    args = p.parse_args()

    config = load_cache_config(pathlib.Path(args.cache_config))
    order = list(DIMS)
    with gzip.open(args.sample, "rt") as fh:
        data = json.load(fh)

    print(f"{args.sample} @ {args.cache_config}")
    print(f"  inner_dim={config.inner_dim} line_size_bytes={config.line_size_bytes} "
          f"cache_type={config.cache_type} capacity_lines={config.capacity_lines} policy={config.policy}")

    event_i = 0
    total_elements = 0
    total_accesses = 0
    for tile_i, tile in enumerate(data["tiles"]):
        for addr in tile["weight_addresses"]:
            elements = expand_events([tuple(addr)], order)
            tags = element_tags(elements, config)
            deduped = [t for i, t in enumerate(tags) if i == 0 or t != tags[i - 1]]
            total_elements += len(elements)
            total_accesses += len(deduped)
            print(f"  burst {event_i} (tile {tile_i}, address {tuple(addr)}): "
                  f"{len(elements)} elements -> {len(deduped)} access(es)")
            for e, t in zip(elements, tags):
                print(f"    element (kh={e.kh}, kw={e.kw}, cin={e.cin}, cout={e.cout}) -> tag {t}")
            print(f"    deduplicated tags: {deduped}")
            event_i += 1

    print(f"  totals: {event_i} bursts, {total_elements} elements, {total_accesses} accesses after dedup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
