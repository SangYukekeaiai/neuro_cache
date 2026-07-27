"""Average hit-rate analysis: replay every cached weight-trace sample for
one (arch, trace_dir, layer) through a Cache built from a given
CacheConfig, and report the mean hit rate across samples. This is the
2026-07-22 plan's actual deliverable: "A sweep harness over cache size
and set-associativity... the real cache-line-level trace this produces
is meant to let us observe the locality feature we're looking for."
"""

from __future__ import annotations

import pathlib
import statistics
from typing import Any, Dict, List, Sequence

from .cache import Cache, hit_rate, replay
from .config import CacheConfig
from .layout import expand_events, element_tags


def sample_hit_rate(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> float:
    """Hit rate for one persisted sample: expand its weight_addresses
    across every tile, tag them under `config`'s layout, replay through a
    FRESH Cache (one cache per sample -- a real cache starts empty every
    time this layer is computed, samples don't share cache state)."""
    from tracegen import load_weight_trace  # deferred: avoid importing gurobipy-pulling tracegen at module load

    trace = load_weight_trace(trace_path)
    events = [addr for tile in trace.tiles for addr in tile.weight_addresses]
    elements = expand_events(events, order)
    tags = element_tags(elements, config)

    cache = Cache(config)
    hits = replay(cache, tags)
    return hit_rate(hits)


def average_hit_rate(
    layer_dir: pathlib.Path, config: CacheConfig, order: Sequence[str]
) -> Dict[str, Any]:
    """layer_dir: outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/,
    containing sample_*.json.gz files (however many were generated --
    the canonical 100, the full 4000, whatever's on disk). Returns
    per-sample rates plus their mean/median, not just the mean alone, so
    a caller can see the spread, not only a single summary number."""
    paths = sorted(layer_dir.glob("sample_*.json.gz"))
    rates: List[float] = [sample_hit_rate(p, config, order) for p in paths]

    return {
        "layer_dir": str(layer_dir),
        "n_samples": len(rates),
        "mean_hit_rate": statistics.mean(rates) if rates else 0.0,
        "median_hit_rate": statistics.median(rates) if rates else 0.0,
        "min_hit_rate": min(rates) if rates else 0.0,
        "max_hit_rate": max(rates) if rates else 0.0,
        "per_sample_hit_rates": rates,
    }
