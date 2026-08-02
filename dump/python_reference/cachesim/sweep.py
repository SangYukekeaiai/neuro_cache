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
from typing import Any, Dict, List, Sequence, Tuple

from .cache import Cache, hit_rate, replay
from cachesim.config import CacheConfig
from .layout import element_tags, expand_events, pack_tags


def _burst_hits(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> List[bool]:
    """One hit/miss bool per access for one persisted sample: expand its
    weight_addresses across every tile, tag them under `config`'s layout,
    replay through a FRESH Cache (one cache per sample -- a real cache
    starts empty every time this layer is computed, samples don't share
    cache state).

    Counted PER BURST, not per individual weight value: one
    weight_addresses event is one physical memory transaction, so its
    expanded elements collapse to the DISTINCT consecutive line tags that
    burst touches (a burst spanning several lines still costs one access
    per line). Dedup never crosses an event boundary, even when two
    bursts share a tag."""
    from tracegen import load_weight_trace  # deferred: avoid importing gurobipy-pulling tracegen at module load

    trace = load_weight_trace(trace_path)
    events = [addr for tile in trace.tiles for addr in tile.weight_addresses]

    tags: List[Tuple[int, int, int, int]] = []
    for event in events:
        prev = None
        for tag in element_tags(expand_events([event], order), config):
            if tag != prev:
                tags.append(tag)
                prev = tag

    cache = Cache(config)
    return replay(cache, pack_tags(tags))


def sample_hit_rate(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> float:
    """Hit rate for one persisted sample, counted per burst."""
    return hit_rate(_burst_hits(trace_path, config, order))


def sample_hit_counts(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> Tuple[int, int]:
    """(hits, accesses) behind sample_hit_rate's ratio, exact instead of
    rounded -- the Python-side counterpart of
    cachesim.native_bridge.native_sample_hit_counts."""
    hits = _burst_hits(trace_path, config, order)
    return sum(hits), len(hits)


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
