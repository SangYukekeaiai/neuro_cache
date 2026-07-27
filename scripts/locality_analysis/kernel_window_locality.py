#!/usr/bin/env python3
"""Kernel-window locality profiling for LoAS: for a fixed (cin, cout range),
does an accessed weight's spatial kernel-window neighbor (kh+dkh, kw+dkw)
also get accessed within the same tile? Computed SEPARATELY for each of the
8 offsets in the 3x3 kernel window (excluding the center):
(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1) -- 8 independent
statistics per layer, NOT pooled/cumulative.

Per (trace_dir, layer, offset), using up to --max-samples LoAS samples:
  1. Per tile: kernel_local_count(t) / len(set(t.weight_addresses)) -- an
     address counts as kernel-local for offset (dkh,dkw) if its single
     (kh+dkh, kw+dkw, cin, cout range) neighbor (boundary-clipped to the
     KHxKW window) is also in that tile's address set. All 8 offsets are
     computed in ONE pass per tile.
  2. Per sample: mean of the per-tile fraction across all tiles.
  3. Per layer: mean of the per-sample value across all samples used.

Produces:
  outputs/locality/kernel_window_locality_summary_loas.csv (31 layers x 8
    offsets = 248 rows)
  outputs/figures/locality/kernel_window_locality_loas.{png,pdf} (1 panel,
    2 subplots, grouped bars: 8 offsets side by side per layer)
"""

from __future__ import annotations

import argparse
import csv
import functools
import multiprocessing
import pathlib
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "src")

import tracegen

TRACE_ROOT = pathlib.Path("/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces")
SCHEDULE_DIR = pathlib.Path("outputs/schedules")
TRACE_DIRS = ["resnet19_T4_all", "vgg16_T4_all"]
FIG_DIR = pathlib.Path("outputs/figures/locality")

Offset = Tuple[int, int]
KERNEL_OFFSETS: List[Offset] = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
]


def tile_kernel_window_locality_fractions_multi(
    weight_addresses: List[Any], KH: int, KW: int, offsets: List[Offset] = KERNEL_OFFSETS
) -> Dict[Offset, Optional[float]]:
    """Fraction of this tile's distinct addresses that have their (kh+dkh,
    kw+dkw) neighbor (boundary-clipped to the KHxKW window, same cin/cout
    range) also present in the same tile, computed SEPARATELY for each
    offset in one pass over the tile. None per offset for an empty tile."""
    addr_set = set(weight_addresses)
    if not addr_set:
        return {off: None for off in offsets}
    counts = {off: 0 for off in offsets}
    for addr in addr_set:
        kh, kw, cin, cout_s, cout_e = addr
        for dkh, dkw in offsets:
            nkh, nkw = kh + dkh, kw + dkw
            if 0 <= nkh < KH and 0 <= nkw < KW and (nkh, nkw, cin, cout_s, cout_e) in addr_set:
                counts[(dkh, dkw)] += 1
    n = len(addr_set)
    return {off: counts[off] / n for off in offsets}


def sample_kernel_window_locality(
    trace: "tracegen.LayerWeightTrace", offsets: List[Offset] = KERNEL_OFFSETS
) -> Dict[Offset, Optional[float]]:
    KH, KW = trace.workload_dims["KH"], trace.workload_dims["KW"]
    per_offset: Dict[Offset, List[float]] = {off: [] for off in offsets}
    for tile in trace.tiles:
        fracs = tile_kernel_window_locality_fractions_multi(tile.weight_addresses, KH, KW, offsets)
        for off in offsets:
            if fracs[off] is not None:
                per_offset[off].append(fracs[off])
    return {off: (sum(v) / len(v) if v else None) for off, v in per_offset.items()}


def _process_one_sample(
    path: pathlib.Path, offsets: List[Offset] = KERNEL_OFFSETS
) -> Optional[Dict[Offset, Optional[float]]]:
    """Picklable multiprocessing worker: load one sample once, return its
    per-offset sample_kernel_window_locality values, or None if missing."""
    if not path.exists():
        return None
    trace = tracegen.load_weight_trace(path)
    return sample_kernel_window_locality(trace, offsets)


def layer_kernel_window_locality(
    arch: str,
    trace_dir: str,
    layer: str,
    max_samples: int = 100,
    workers: int = 1,
    offsets: List[Offset] = KERNEL_OFFSETS,
) -> Dict[Offset, Dict[str, Any]]:
    paths = [
        TRACE_ROOT / arch / trace_dir / layer / f"sample_{i:05d}.json.gz"
        for i in range(max_samples)
    ]
    worker_fn = functools.partial(_process_one_sample, offsets=offsets)

    if workers <= 1:
        raw = [worker_fn(p) for p in paths]
    else:
        with multiprocessing.Pool(processes=workers) as pool:
            raw = pool.map(worker_fn, paths)

    per_offset_values: Dict[Offset, List[float]] = {off: [] for off in offsets}
    for r in raw:
        if r is None:
            continue
        for off in offsets:
            if r[off] is not None:
                per_offset_values[off].append(r[off])

    out = {}
    for off in offsets:
        vals = per_offset_values[off]
        out[off] = {
            "n_samples_used": len(vals),
            "mean_fraction": sum(vals) / len(vals) if vals else None,
            "per_sample_values": vals,
        }
    return out


def _layers_for(arch: str, trace_dir: str) -> List[str]:
    return sorted(f.stem for f in (SCHEDULE_DIR / arch / trace_dir).glob("*.json"))


def main(arch: str = "loas", max_samples: int = 100, workers: int = 1) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.cm as cm
    import matplotlib.pyplot as plt

    offsets = KERNEL_OFFSETS
    colors = [cm.tab10(i) for i in range(len(offsets))]
    color_by_offset = dict(zip(offsets, colors))
    summary_path = pathlib.Path(f"outputs/locality/kernel_window_locality_summary_{arch}.csv")

    results_by_trace_dir: Dict[str, Dict[Offset, List[Dict[str, Any]]]] = {}
    summary_rows = []

    for trace_dir in TRACE_DIRS:
        layers = _layers_for(arch, trace_dir)
        results_by_trace_dir[trace_dir] = {off: [] for off in offsets}
        for layer in layers:
            print(f"  {arch}/{trace_dir}/{layer} ...")
            per_offset = layer_kernel_window_locality(
                arch, trace_dir, layer, max_samples=max_samples, workers=workers, offsets=offsets
            )
            for off in offsets:
                result = per_offset[off]
                results_by_trace_dir[trace_dir][off].append({"layer": layer, **result})
                summary_rows.append(
                    {
                        "trace_dir": trace_dir,
                        "layer": layer,
                        "layer_index": layer.replace("layer_", "").split("_", 1)[0],
                        "dkh": off[0],
                        "dkw": off[1],
                        "n_samples_used": result["n_samples_used"],
                        "mean_fraction": result["mean_fraction"],
                    }
                )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="") as fh:
        fieldnames = ["trace_dir", "layer", "layer_index", "dkh", "dkw", "n_samples_used", "mean_fraction"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"wrote {len(summary_rows)} rows -> {summary_path}")

    fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
    bar_width = 0.85 / len(offsets)
    for ax, trace_dir in zip(axes, TRACE_DIRS):
        off_results = results_by_trace_dir[trace_dir]
        n_layers = len(off_results[offsets[0]])
        labels = [r["layer"].replace("layer_", "").split("_", 1)[0] for r in off_results[offsets[0]]]
        xs = list(range(n_layers))
        for i, off in enumerate(offsets):
            values = [r["mean_fraction"] or 0.0 for r in off_results[off]]
            offset_x = (i - (len(offsets) - 1) / 2) * bar_width
            ax.bar(
                [x + offset_x for x in xs], values, width=bar_width,
                color=color_by_offset[off], label=f"({off[0]:+d},{off[1]:+d})",
            )
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=90, fontsize=6)
        ax.set_title(trace_dir.split("_")[0])
        ax.set_xlabel("layer")

    axes[0].set_ylabel("kernel-window locality fraction")
    axes[0].set_ylim(0, 1.02)
    axes[-1].legend(
        loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False, fontsize=8, title="(dkh,dkw)"
    )
    fig.suptitle(
        f"{arch}: kernel-window locality fraction by layer\n"
        "(fraction of accessed weights per tile whose (kh+dkh, kw+dkw) neighbor is also "
        "accessed, one bar per offset, averaged over tiles then over samples)"
    )
    fig.tight_layout()

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(FIG_DIR / f"kernel_window_locality_{arch}.{ext}", dpi=200)
    plt.close(fig)
    print(f"wrote {FIG_DIR / f'kernel_window_locality_{arch}.png'} / .pdf")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arch", default="loas")
    p.add_argument("--max-samples", type=int, default=100)
    p.add_argument("--workers", type=int, default=1)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(arch=args.arch, max_samples=args.max_samples, workers=args.workers))
