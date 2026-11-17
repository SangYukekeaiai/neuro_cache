#!/usr/bin/env python3
"""Render the eval_scaling 2 x 5 performance/traffic figure."""

from __future__ import annotations

import csv
import pathlib
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import yaml


HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "outputs"
CAPTURE = "loas_vgg16_T4_n500"
ARCHES = ("spinalflow", "ptb", "loas", "prosperity", "gustavsnn")
ARCH_LABELS = {
    "spinalflow": "SpinalFlow",
    "ptb": "PTB",
    "loas": "LoAS",
    "prosperity": "Prosperity",
    "gustavsnn": "GustavSNN",
}
SERIES = (
    ("spad_nocsim", "single", "single-node spad", "#4477aa", "o", "-"),
    ("spad_nocsim", "multi", "multi-node spad", "#ee6677", "s", "--"),
    ("cache", "multi", "multi-node cache", "#228833", "^", "-."),
)


def _rows() -> list[dict[str, str]]:
    with (OUT / "aggregate.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def _floor(arch: str, rows: list[dict[str, str]]) -> float | None:
    baseline = next(
        (
            row
            for row in rows
            if row.get("arch", "loas") == arch
            and row.get("arm", "spad_nocsim") == "spad_nocsim"
            and row["side"] == "single"
            and int(row["multiplier"]) == 1
        ),
        None,
    )
    if baseline is None:
        return None
    candidates = [
        OUT / "s1" / arch / "single_x1" / "workloads" / CAPTURE,
        OUT / "s1" / "single_x1" / "workloads" / CAPTURE,
    ]
    workload_dir = next((path for path in candidates if path.is_dir()), None)
    if workload_dir is None:
        return None
    floor_bytes = 0.0
    for path in sorted(workload_dir.glob("*.yaml")):
        problem = yaml.safe_load(path.read_text())["problem"]
        floor_bytes += problem["KH"] * problem["KW"] * problem["CIN"] * problem["COUT"]
    if not floor_bytes:
        return None
    return floor_bytes / float(baseline["counted_dram_bytes_mean"])


def main() -> None:
    rows = _rows()
    by_arch: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_arch[row.get("arch", "loas")].append(row)

    fig, axes = plt.subplots(2, 5, figsize=(13.0, 4.6), sharex=True, sharey="row")
    floor_drawn = False
    for column, arch in enumerate(ARCHES):
        arch_rows = by_arch.get(arch, [])
        for arm, side, label, color, marker, linestyle in SERIES:
            selected = sorted(
                (
                    row
                    for row in arch_rows
                    if row.get("arm", "spad_nocsim") == arm and row["side"] == side
                ),
                key=lambda row: int(row["multiplier"]),
            )
            if not selected:
                continue
            x = [int(row["multiplier"]) for row in selected]
            performance = [
                float(row["perf_norm"]) if "perf_norm" in row else float(row["perf_mean"])
                for row in selected
            ]
            performance_ci = [
                float(row["perf_ci"]) if "perf_ci" in row else float(row["perf_ci95"])
                for row in selected
            ]
            traffic = [
                float(row["traffic_norm"])
                if "traffic_norm" in row
                else float(row["counted_traffic_norm"])
                for row in selected
            ]
            traffic_ci = [
                float(row["traffic_norm_ci95"])
                if "traffic_norm_ci95" in row
                else float(row["counted_traffic_norm_ci95"])
                for row in selected
            ]
            axes[0, column].plot(
                x, performance, color=color, marker=marker, linestyle=linestyle,
                ms=4, lw=1.2, label=label if column == 0 else None,
            )
            axes[0, column].fill_between(
                x,
                [value - ci for value, ci in zip(performance, performance_ci)],
                [value + ci for value, ci in zip(performance, performance_ci)],
                color=color, alpha=0.14, linewidth=0,
            )
            axes[1, column].plot(
                x, traffic, color=color, marker=marker, linestyle=linestyle,
                ms=4, lw=1.2,
            )
            axes[1, column].fill_between(
                x,
                [value - ci for value, ci in zip(traffic, traffic_ci)],
                [value + ci for value, ci in zip(traffic, traffic_ci)],
                color=color, alpha=0.14, linewidth=0,
            )
        axes[0, column].set_title(ARCH_LABELS[arch], fontsize=9)
        floor = _floor(arch, rows)
        if floor is not None:
            floor_drawn = True
            axes[1, column].axhline(
                floor, color="0.35", lw=0.8, linestyle=":",
                label="weights-only compulsory floor" if column == 0 else None,
            )

    for row_axes in axes:
        for axis in row_axes:
            axis.set_xscale("log")
            axis.set_xticks([1, 2, 4])
            axis.set_xticklabels(["1x", "2x", "4x"])
            axis.minorticks_off()
            axis.grid(alpha=0.25, lw=0.5)
            axis.tick_params(labelsize=8)
    for axis in axes[1]:
        axis.set_xlabel("On-chip weight capacity", fontsize=8)
    axes[0, 0].set_ylabel("Performance / single-node 1x", fontsize=9)
    axes[1, 0].set_ylabel("DRAM traffic / single-node 1x", fontsize=9)
    legend_handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    if floor_drawn:
        legend_handles.append(
            Line2D([0], [0], color="0.35", lw=0.8, linestyle=":")
        )
        legend_labels.append("weights-only compulsory floor")
    axes[0, 0].legend(
        legend_handles, legend_labels, fontsize=7, loc="best", framealpha=0.9
    )
    fig.suptitle(
        "Memory scaling at fixed node count; bands are 95% CIs over samples",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for extension in ("pdf", "png"):
        fig.savefig(OUT / f"eval_scaling.{extension}", dpi=200)
    plt.close(fig)
    print("->", OUT / "eval_scaling.pdf")


if __name__ == "__main__":
    main()
