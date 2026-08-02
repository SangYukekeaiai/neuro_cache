#!/usr/bin/env python3
"""Per-sample normalized-entropy locality diagnostic for the raw input
spike trace's hin, win, t, and cin dimensions (plan section 2, `hin, win,
t`, in log/2026-07-23-input-driven-weight-locality-plan.md; cin added
here as a direct check on the raw spike trace, complementing the
weight-side cin diagnostic). Loads one already-captured layer's spike
trace directly (T, N, CIN, Hin, Win) and scores concentration, effective
tag count, and top-20 mass fraction per sample, per dimension,
independent of the weight-access pipeline.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import numpy as np

from access_pattern import concentration_score, effective_tag_count, top_k_mass_fraction

# axes of one sample's (T, CIN, Hin, Win) array to sum over (marginalize)
# to get the firing-count histogram for each dimension
_MARGINALIZE_AXES = {"t": (1, 2, 3), "hin": (0, 1, 3), "win": (0, 1, 2), "cin": (0, 2, 3)}
DIMS = ("hin", "win", "t", "cin")
TOP_K = 20


def per_sample_stats(sample, dim):
    """sample: (T, CIN, Hin, Win) spike array for one sample. Returns
    concentration, effective tag count, and top-20 mass fraction for the
    firing-count histogram over dim, marginalizing the other three axes."""
    counts = sample.sum(axis=_MARGINALIZE_AXES[dim])
    histogram = {i: int(c) for i, c in enumerate(counts) if c > 0}
    return {
        "concentration": concentration_score(histogram),
        "effective_tags": effective_tag_count(histogram),
        "num_distinct": len(histogram),
        f"top{TOP_K}_frac": top_k_mass_fraction(histogram, TOP_K),
    }


def marked_sample_indices():
    """The same 100 marked random sample indices used by
    regenerate_weight_traces.py, so this raw-spike check and the
    weight-side diagnostic are computed over identical images."""
    with open(_HERE / "sample_indices.json") as fh:
        return json.load(fh)["sample_indices"]


def main(npy_path, out_path, num_samples):
    spikes = np.load(npy_path, mmap_mode="r")  # (T, N, CIN, Hin, Win)
    indices = marked_sample_indices()[:num_samples]

    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sample_idx", "dim", "concentration", "effective_tags", "num_distinct", f"top{TOP_K}_frac"])
        for sample_idx in indices:
            sample = np.asarray(spikes[:, sample_idx])  # materialize: (T, CIN, Hin, Win)
            for dim in DIMS:
                stats = per_sample_stats(sample, dim)
                writer.writerow([
                    sample_idx, dim, stats["concentration"], stats["effective_tags"],
                    stats["num_distinct"], stats[f"top{TOP_K}_frac"],
                ])
    print(f"-> {out_path} ({len(indices) * len(DIMS)} rows)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: input_spike_locality.py <layer.npy> [num_samples] [out_csv]\n"
            "example: input_spike_locality.py "
            "/u/yyu9/neuro_cache_trace/input_trace/loas/resnet19_T4_all/layer_01_layer1_0_conv1.npy"
        )

    npy_path = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    out_path = (
        sys.argv[3]
        if len(sys.argv) > 3
        else str(_HERE / "outputs" / "input_spike_diagnostic" / (pathlib.Path(npy_path).stem + ".csv"))
    )

    main(npy_path, out_path, num_samples)
