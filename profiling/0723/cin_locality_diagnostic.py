#!/usr/bin/env python3
"""Cache-line tag diagnostic for cin locality (plan section 1, `cin`, in
log/2026-07-23-input-driven-weight-locality-plan.md). For one or more
already-generated LayerWeightTrace samples of one (arch, layer), computes
the four inner-dim tag histograms per sample, their normalized-entropy
concentration scores, and the fully-associative LRU cache's hit rate
under each layout. Saves a CSV and two figures for review.
"""

from __future__ import annotations

import csv
import glob
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO_ROOT / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from access_pattern import (
    INNER_DIMS,
    concentration_score,
    effective_tag_count,
    event_line_tags,
    expand_events,
    rank_frequency,
    tag_histogram,
    top_k_mass_fraction,
)
from lru_cache import FullyAssociativeLRUCache, replay
from tracegen import load_weight_trace

LINE_SIZE = 16        # elements of the innermost dim packed per line, a realistic width at 8-bit weights, not yet swept
CACHE_CAPACITY = 256   # lines; a fixed illustrative starting point, capacity/associativity are deferred design questions


def analyze_sample(events):
    """events: one sample's weight-address events, in dram_i order.
    Returns {inner_dim: {"concentration", "hit_rate", "rank_freq"}}."""
    elements = expand_events(events)
    result = {}
    for inner_dim in INNER_DIMS:
        hist = tag_histogram(elements, inner_dim, LINE_SIZE)
        tags = [tag for event in events for tag in event_line_tags(event, inner_dim, LINE_SIZE)]
        cache = FullyAssociativeLRUCache(CACHE_CAPACITY)
        hits = replay(cache, tags)
        result[inner_dim] = {
            "concentration": concentration_score(hist),
            "effective_tags": effective_tag_count(hist),
            "top1_frac": top_k_mass_fraction(hist, 1),
            "top10_frac": top_k_mass_fraction(hist, 10),
            "hit_rate": (sum(hits) / len(hits)) if hits else 0.0,
            "rank_freq": rank_frequency(hist),
        }
    return result


def main(trace_paths, out_dir):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_sample = []
    for p in trace_paths:
        trace = load_weight_trace(pathlib.Path(p))
        events = [addr for tile in trace.tiles for addr in tile.weight_addresses]
        per_sample.append((trace.sample_idx, analyze_sample(events)))
        print(f"  sample {trace.sample_idx}: {len(events)} events, {len(expand_events(events))} elements")

    csv_path = out_dir / "cin_locality_summary.csv"
    with open(csv_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "sample_idx", "inner_dim", "concentration", "effective_tags",
            "top1_frac", "top10_frac", "hit_rate", "num_distinct_tags",
        ])
        for sample_idx, result in per_sample:
            for inner_dim, r in result.items():
                writer.writerow([
                    sample_idx, inner_dim, r["concentration"], r["effective_tags"],
                    r["top1_frac"], r["top10_frac"], r["hit_rate"], len(r["rank_freq"]),
                ])
    print(f"-> {csv_path} ({len(per_sample) * len(INNER_DIMS)} rows)")

    fig, ax = plt.subplots()
    data = [[r[d]["concentration"] for _, r in per_sample] for d in INNER_DIMS]
    ax.boxplot(data, tick_labels=list(INNER_DIMS))
    ax.set_ylabel("concentration score (1 - normalized entropy)")
    ax.set_title("cin-locality diagnostic: concentration by innermost-dim choice")
    fig.savefig(out_dir / "concentration_by_layout.png")
    plt.close(fig)
    print(f"-> {out_dir / 'concentration_by_layout.png'}")

    sample_idx, result = per_sample[0]
    fig, ax = plt.subplots()
    for inner_dim in INNER_DIMS:
        freqs = result[inner_dim]["rank_freq"]
        ax.plot(range(1, len(freqs) + 1), freqs, label=inner_dim)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("tag rank")
    ax.set_ylabel("access count")
    ax.set_title(f"rank-frequency, sample {sample_idx}")
    ax.legend()
    fig.savefig(out_dir / "rank_frequency_sample.png")
    plt.close(fig)
    print(f"-> {out_dir / 'rank_frequency_sample.png'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: cin_locality_diagnostic.py <trace_glob> [num_samples] [out_dir]\n"
            "example: cin_locality_diagnostic.py "
            "'/projects/bebv/yyu9/neuro_cache_outputs/weight_traces/loas/resnet19_T4_all/"
            "layer_01_layer1_0_conv1/sample_*.json.gz'"
        )

    trace_glob = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    out_dir = sys.argv[3] if len(sys.argv) > 3 else str(_HERE / "outputs" / "cin_diagnostic")

    paths = sorted(glob.glob(trace_glob))[:num_samples]
    if not paths:
        raise SystemExit(f"no trace files matched: {trace_glob}")
    print(f"Analyzing {len(paths)} samples...")
    main(paths, out_dir)
