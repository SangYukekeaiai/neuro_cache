#!/usr/bin/env python3
"""Classify and visualize the DRAM-level loop-permutation class of every
finalized (arch, layer) schedule -- see
src/mip_solver/analysis/dram_permutation.py for the M/N/K/T
super-dimension fusion rule.

Produces:
  outputs/figures/dram_permutation.csv    -- one row per (arch, layer): class string
  outputs/figures/dram_permutation.png/.pdf -- 31-layer x 5-arch heatmap,
    color-coded AND text-labeled by class (never color-alone -- some
    layer/arch cells sit on light-mode palette slots below 3:1 contrast,
    so the class string itself, not the color, carries the information).
"""

from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, "src")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from mip_solver.analysis import classify_schedule_file

ARCHS = ["loas", "spinalflow", "ptb", "gustavsnn", "prosperity"]
TRACE_DIRS = ["resnet19_T4_all", "vgg16_T4_all"]  # 19 + 12 = 31 layers
SCHEDULE_DIR = pathlib.Path("outputs/schedules")
OUT_DIR = pathlib.Path("outputs/figures")

# Reference categorical palette (dataviz skill, references/palette.md),
# first 7 of its 8 documented slots, in the skill's fixed light-mode order.
PALETTE = ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a", "#eb6834", "#4a3aa7"]


def _layer_rows():
    """(trace_dir, layer_stem, display_label) for all 31 layers, in
    meta.json order within each trace_dir."""
    rows = []
    for trace_dir in TRACE_DIRS:
        layer_files = sorted((SCHEDULE_DIR / ARCHS[0] / trace_dir).glob("*.json"))
        for f in layer_files:
            short = f.stem.replace("layer_", "").split("_", 1)
            label = f"{trace_dir.split('_')[0]}:{f.stem}"
            rows.append((trace_dir, f.stem, label))
    return rows


def main() -> int:
    rows = _layer_rows()
    classes_grid = []  # [row][col] = class string
    for trace_dir, layer_stem, _label in rows:
        row = []
        for arch in ARCHS:
            path = SCHEDULE_DIR / arch / trace_dir / f"{layer_stem}.json"
            row.append(classify_schedule_file(path))
        classes_grid.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- CSV ---
    csv_path = OUT_DIR / "dram_permutation.csv"
    with open(csv_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["trace_dir", "layer", *ARCHS])
        for (trace_dir, layer_stem, _label), row in zip(rows, classes_grid):
            writer.writerow([trace_dir, layer_stem, *row])
    print(f"wrote {csv_path}")

    # --- fixed class -> color order: first-seen order across the grid,
    # so the legend/color assignment is deterministic and stable run to
    # run (not alphabetical, not frequency-sorted). ---
    class_order: list[str] = []
    for row in classes_grid:
        for cls in row:
            if cls not in class_order:
                class_order.append(cls)
    if len(class_order) > len(PALETTE):
        raise ValueError(f"{len(class_order)} classes found, only {len(PALETTE)} palette slots defined")
    color_of = {cls: PALETTE[i] for i, cls in enumerate(class_order)}
    cmap = ListedColormap([color_of[c] for c in class_order])
    class_index = {c: i for i, c in enumerate(class_order)}

    # --- figure ---
    n_rows, n_cols = len(rows), len(ARCHS)
    fig, ax = plt.subplots(figsize=(1.6 * n_cols + 2, 0.32 * n_rows + 1.5))
    grid = [[class_index[c] for c in row] for row in classes_grid]
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=len(class_order) - 1, aspect="auto")

    # 2px surface-color gridlines between cells (spacer rule)
    ax.set_xticks([x - 0.5 for x in range(1, n_cols)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, n_rows)], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(ARCHS, rotation=30, ha="right")
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([label for _, _, label in rows], fontsize=6)

    # direct labels in every cell -- color is never the sole carrier
    for r in range(n_rows):
        for c in range(n_cols):
            ax.text(c, r, classes_grid[r][c], ha="center", va="center",
                     fontsize=5.5, color="white")

    legend_handles = [Patch(facecolor=color_of[c], label=c) for c in class_order]
    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.02, 1.0),
               fontsize=8, title="DRAM permutation class", title_fontsize=9,
               frameon=False)

    ax.set_title("DRAM-level loop permutation by arch x layer\n"
                  "(M={HO,WO}, N={COUT}, K={KH,KW,CIN}, T={T}; adjacent-superdim fused)")
    fig.tight_layout()

    for ext in ("png", "pdf"):
        out_path = OUT_DIR / f"dram_permutation.{ext}"
        fig.savefig(out_path, dpi=200)
        print(f"wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
