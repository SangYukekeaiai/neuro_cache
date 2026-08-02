#!/usr/bin/env python3
"""Kernel-window locality, POOLED "cross" variant, for LoAS: for a fixed
(cin, cout range), does an accessed weight have AT LEAST ONE of its 4
axis-aligned kernel-window neighbors -- (kh-1,kw), (kh+1,kw), (kh,kw-1),
(kh,kw+1), i.e. up/down/left/right, excluding the 4 diagonal corners --
also accessed within the same tile? A single POOLED statistic per layer
(contrast with kernel_window_locality.py's 8 SEPARATE per-offset
statistics, which this script does not modify or overwrite).

Per (trace_dir, layer), using up to --max-samples LoAS samples:
  1. Per tile: cross_local_count(t) / len(set(t.weight_addresses)) -- an
     address counts as cross-local if >=1 of its 4 axis-aligned neighbors
     (boundary-clipped to the KHxKW window) is also in that tile's address
     set.
  2. Per sample: mean of the per-tile fraction across all tiles.
  3. Per layer: mean of the per-sample value across all samples used.

Produces:
  outputs/locality/kernel_window_locality_cross_summary_loas.csv (31 rows)
  outputs/figures/locality/kernel_window_locality_cross_loas.{png,pdf}
    (1 panel, 2 subplots, one bar per layer)
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
CROSS_OFFSETS: List[Offset] = [(-1, 0), (1, 0), (0, -1), (0, 1)]

COLOR = "#2a78d6"


def tile_kernel_window_locality_fraction_pooled(
    weight_addresses: List[Any], KH: int, KW: int, offsets: List[Offset] = CROSS_OFFSETS
) -> Optional[float]:
    """Fraction of this tile's distinct addresses that have >=1 of the
    given offsets' (kh+dkh, kw+dkw) neighbor (boundary-clipped, same
    cin/cout range) also present in the same tile -- pooled across all
    offsets (any match counts), not one stat per offset. None for an empty
    tile (excluded upstream)."""
    addr_set = set(weight_addresses)
    if not addr_set:
        return None
    local = 0
    for addr in addr_set:
        kh, kw, cin, cout_s, cout_e = addr
        for dkh, dkw in offsets:
            nkh, nkw = kh + dkh, kw + dkw
            if 0 <= nkh < KH and 0 <= nkw < KW and (nkh, nkw, cin, cout_s, cout_e) in addr_set:
                local += 1
                break
    return local / len(addr_set)


def sample_kernel_window_locality_pooled(
    trace: "tracegen.LayerWeightTrace", offsets: List[Offset] = CROSS_OFFSETS
) -> Optional[float]:
    KH, KW = trace.workload_dims["KH"], trace.workload_dims["KW"]
    fractions = []
    for tile in trace.tiles:
        f = tile_kernel_window_locality_fraction_pooled(tile.weight_addresses, KH, KW, offsets)
        if f is not None:
            fractions.append(f)
    if not fractions:
        return None
    return sum(fractions) / len(fractions)


def _process_one_sample(path: pathlib.Path, offsets: List[Offset] = CROSS_OFFSETS) -> Optional[float]:
    if not path.exists():
        return None
    trace = tracegen.load_weight_trace(path)
    return sample_kernel_window_locality_pooled(trace, offsets)


def layer_kernel_window_locality_pooled(
    arch: str, trace_dir: str, layer: str, max_samples: int = 100, workers: int = 1,
    offsets: List[Offset] = CROSS_OFFSETS,
) -> Dict[str, Any]:
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

    per_sample_values = [v for v in raw if v is not None]
    mean_fraction = sum(per_sample_values) / len(per_sample_values) if per_sample_values else None
    return {
        "trace_dir": trace_dir,
        "layer": layer,
        "n_samples_used": len(per_sample_values),
        "mean_fraction": mean_fraction,
        "per_sample_values": per_sample_values,
    }


def _layers_for(arch: str, trace_dir: str) -> List[str]:
    return sorted(f.stem for f in (SCHEDULE_DIR / arch / trace_dir).glob("*.json"))


def main(arch: str = "loas", max_samples: int = 100, workers: int = 1) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary_path = pathlib.Path(f"outputs/locality/kernel_window_locality_cross_summary_{arch}.csv")
    results_by_trace_dir: Dict[str, List[Dict[str, Any]]] = {}
    summary_rows = []

    for trace_dir in TRACE_DIRS:
        layers = _layers_for(arch, trace_dir)
        results = []
        for layer in layers:
            print(f"  {arch}/{trace_dir}/{layer} (cross) ...")
            result = layer_kernel_window_locality_pooled(
                arch, trace_dir, layer, max_samples=max_samples, workers=workers
            )
            results.append(result)
            summary_rows.append(
                {
                    "trace_dir": trace_dir,
                    "layer": layer,
                    "layer_index": layer.replace("layer_", "").split("_", 1)[0],
                    "n_samples_used": result["n_samples_used"],
                    "mean_fraction": result["mean_fraction"],
                }
            )
        results_by_trace_dir[trace_dir] = results

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="") as fh:
        fieldnames = ["trace_dir", "layer", "layer_index", "n_samples_used", "mean_fraction"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"wrote {len(summary_rows)} rows -> {summary_path}")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, trace_dir in zip(axes, TRACE_DIRS):
        results = results_by_trace_dir[trace_dir]
        labels = [r["layer"].replace("layer_", "").split("_", 1)[0] for r in results]
        values = [r["mean_fraction"] or 0.0 for r in results]
        xs = list(range(len(results)))
        ax.bar(xs, values, color=COLOR)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=90, fontsize=6)
        ax.set_title(trace_dir.split("_")[0])
        ax.set_xlabel("layer")

    axes[0].set_ylabel("kernel-window locality fraction (cross, pooled)")
    axes[0].set_ylim(0, 1.02)
    fig.suptitle(
        f"{arch}: kernel-window locality fraction by layer (pooled cross: "
        "(-1,0),(1,0),(0,-1),(0,1))\n"
        "(fraction of accessed weights per tile with >=1 axis-aligned neighbor also accessed, "
        "averaged over tiles then over samples)"
    )
    fig.tight_layout()

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(FIG_DIR / f"kernel_window_locality_cross_{arch}.{ext}", dpi=200)
    plt.close(fig)
    print(f"wrote {FIG_DIR / f'kernel_window_locality_cross_{arch}.png'} / .pdf")

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
