#!/usr/bin/env python3
"""One-off visualization for the loas cout-inner-dim hit-rate test (not
part of log/2026-07-28-debug-pipeline-plan.md): reads cache_sweep.py's
merged CSV, filters to inner_dim=cout and cache sizes {16,32,64}KB, and
renders one PNG per (workload, layer) -- a 3-panel figure (one panel per
line_size_bytes: 16/32/64B), x-axis = cache size, one line per
associativity (4/16/32-way). Mirrors profiling/0723's per-layer PNG-per-
directory convention (e.g. cin_diagnostic_*/<layer>/*.png).

Uses the corrected per-burst hit rate (native/cache_sweep.cpp's dedup
fix), not the old per-weight-value one.
"""

from __future__ import annotations

import argparse
import csv
import pathlib
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIZES_KB = [16384, 32768, 65536]
LINE_SIZES = [16, 32, 64]
ASSOCIATIVITIES = [4, 16, 32]


def load_rows(csv_path: pathlib.Path):
    rows = []
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            if row["inner_dim"] != "cout":
                continue
            if int(row["size_bytes"]) not in SIZES_KB:
                continue
            if row["cache_type"] != "set_associative":
                continue
            if int(row["associativity"]) not in ASSOCIATIVITIES:
                continue
            rows.append(row)
    return rows


def plot_layer(rows, out_path: pathlib.Path, title: str) -> None:
    by_line_assoc = defaultdict(dict)  # (line_size, assoc) -> {size_bytes: hit_rate}
    for row in rows:
        key = (int(row["line_size"]), int(row["associativity"]))
        by_line_assoc[key][int(row["size_bytes"])] = float(row["mean_hit_rate"])

    fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    for ax, line_size in zip(axes, LINE_SIZES):
        for assoc in ASSOCIATIVITIES:
            sizes_present = sorted(by_line_assoc.get((line_size, assoc), {}))
            if not sizes_present:
                continue
            y = [by_line_assoc[(line_size, assoc)][s] for s in sizes_present]
            ax.plot([s / 1024 for s in sizes_present], y, marker="o", label=f"{assoc}-way")
        ax.set_title(f"line_size={line_size}B")
        ax.set_xlabel("cache size (KB)")
        ax.set_xticks([s / 1024 for s in SIZES_KB])
    axes[0].set_ylabel("mean hit rate (per-burst)")
    axes[0].legend()
    fig.suptitle(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=pathlib.Path, required=True,
                    help="merged CSV from cache_sweep.py, e.g. cache_sweep_results_cout_test.csv")
    p.add_argument("--out-dir", type=pathlib.Path, default=pathlib.Path("outputs_cout_test"))
    args = p.parse_args()

    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit(f"no matching rows in {args.csv} (expected inner_dim=cout, "
                          f"size_bytes in {SIZES_KB}, associativity in {ASSOCIATIVITIES})")

    by_layer = defaultdict(list)
    for row in rows:
        by_layer[(row["workload"], row["layer"])].append(row)

    for (workload, layer), layer_rows in sorted(by_layer.items()):
        out_path = args.out_dir / workload / f"{layer}.png"
        plot_layer(layer_rows, out_path, title=f"loas / {workload} / {layer} (cout inner-dim)")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
