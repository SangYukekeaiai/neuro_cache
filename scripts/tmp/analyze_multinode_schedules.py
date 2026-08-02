#!/usr/bin/env python3
"""Plot value-free GB spatial splits and DRAM permutation classes."""

from __future__ import annotations

import csv
import json
import pathlib
import sys

sys.path.insert(0, "src")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from mip_solver.analysis import classify_permutation


ARCHS = ("loas", "spinalflow", "ptb", "gustavsnn", "prosperity")
TRACE_DIRS = ("resnet19_T4_all", "vgg16_T4_all")
SCHEDULE_DIR = pathlib.Path("outputs/schedules/multinode")
OUT_DIR = pathlib.Path("outputs/figures")
SUPER_DIM = {
    "HO": "M",
    "WO": "M",
    "COUT": "N",
    "KH": "K",
    "KW": "K",
    "CIN": "K",
    "T": "T",
}


def gb_split_class(loops) -> str:
    present = {SUPER_DIM[loop["dim"]] for loop in loops}
    tokens = [token for token in ("M", "N", "K", "T") if token in present]
    return "+".join(tokens) if tokens else "-"


def classify(path: pathlib.Path) -> str:
    with open(path) as file:
        strategy = json.load(file)["result"]["strategy"]
    gb_loops = strategy["NoCLevel"]["spatial_splitting"]["loops"]
    dram_loops = strategy["DRAM"]["temporal_permutation"]["loops"]
    dram = classify_permutation(dram_loops) or "-"
    return f"GB={gb_split_class(gb_loops)} | DRAM={dram}"


def layer_rows():
    rows = []
    for trace_name in TRACE_DIRS:
        layer_files = sorted(
            (SCHEDULE_DIR / ARCHS[0] / trace_name).glob("*.json")
        )
        for path in layer_files:
            label = f"{trace_name.split('_')[0]}:{path.stem}"
            rows.append((trace_name, path.stem, label))
    return rows


def main() -> int:
    rows = layer_rows()
    grid = []
    for trace_name, layer_name, _ in rows:
        grid.append(
            [
                classify(
                    SCHEDULE_DIR / arch / trace_name / f"{layer_name}.json"
                )
                for arch in ARCHS
            ]
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "multinode_schedule_splitting.csv"
    with open(csv_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["trace_dir", "layer", *ARCHS])
        for (trace_name, layer_name, _), classes in zip(rows, grid):
            writer.writerow([trace_name, layer_name, *classes])

    classes = []
    for grid_row in grid:
        for value in grid_row:
            if value not in classes:
                classes.append(value)
    palette = plt.get_cmap("tab20").colors
    if len(classes) > len(palette):
        palette = plt.get_cmap("gist_ncar")(
            [index / len(classes) for index in range(len(classes))]
        )
    colors = {value: palette[index] for index, value in enumerate(classes)}
    class_index = {value: index for index, value in enumerate(classes)}
    cmap = ListedColormap([colors[value] for value in classes])

    figure, axis = plt.subplots(
        figsize=(2.8 * len(ARCHS) + 4, 0.42 * len(rows) + 2)
    )
    image_grid = [[class_index[value] for value in row] for row in grid]
    axis.imshow(
        image_grid,
        cmap=cmap,
        vmin=0,
        vmax=max(0, len(classes) - 1),
        aspect="auto",
    )
    axis.set_xticks(range(len(ARCHS)))
    axis.set_xticklabels(ARCHS, rotation=30, ha="right")
    axis.set_yticks(range(len(rows)))
    axis.set_yticklabels([label for _, _, label in rows], fontsize=6)
    for row_index, grid_row in enumerate(grid):
        for column_index, value in enumerate(grid_row):
            axis.text(
                column_index,
                row_index,
                value.replace(" | ", "\n"),
                ha="center",
                va="center",
                fontsize=5,
                color="black",
            )
    handles = [
        Patch(facecolor=colors[value], label=value) for value in classes
    ]
    axis.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        fontsize=6,
        title="Value-free class",
        frameon=False,
    )
    axis.set_title(
        "Multi-node GB spatial splitting and DRAM permutation\n"
        "(M={HO,WO}, N={COUT}, K={KH,KW,CIN}, T={T})"
    )
    figure.tight_layout()
    for extension in ("png", "pdf"):
        figure.savefig(
            OUT_DIR / f"multinode_schedule_splitting.{extension}", dpi=200
        )
    print(f"wrote {csv_path} and multinode_schedule_splitting.png/.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
