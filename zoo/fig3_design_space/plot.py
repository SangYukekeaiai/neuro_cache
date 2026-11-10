#!/usr/bin/env python3
"""Paper Figure 3: latency distribution of every valid multi-node schedule.

Reads outputs/schedules.csv (one row per valid schedule, written by
enumerate.py), bins the latencies into 24 log-spaced bins, and marks where the
five published architectures land according to outputs/baselines.json (the
real Gurobi scheduler's delay term).  Writes fig3_design_space.pdf,
fig3_design_space.png (300 dpi), caption.txt and provenance.json.

Style follows ../fig2_hw_n_sweep/plot.py: 3.375 in column width, 8 pt text,
Gill Sans from the TTFs in that folder (with a reported fallback), y axis from
zero, no decoration that is not data.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import subprocess
from collections import Counter
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
FONT_DIR = REPO / "zoo" / "fig2_hw_n_sweep"
N_BINS = 24
BAR_COLOR = "#648FFF"
MARK_COLOR = "#DC267F"
DISPLAY = {
    "loas_t4": "LoAS",
    "ptb_t4": "PTB",
    "gustavsnn_fig3": "GustavSNN",
    "prosperity_fig3": "Prosperity",
    "spinalflow_fig3": "SpinalFlow",
}


def paper_style() -> str:
    """8 pt Gill Sans; returns the font family actually used."""
    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
        "figure.titlesize": 8, "mathtext.default": "regular",
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fonts = sorted(
        p for p in FONT_DIR.iterdir()
        if p.is_file() and p.name.upper().startswith("GIL")
        and p.suffix.lower() == ".ttf"
    ) if FONT_DIR.is_dir() else []
    for font in fonts:
        font_manager.fontManager.addfont(str(font))
    if fonts:
        family = font_manager.FontProperties(fname=str(fonts[0])).get_name()
    else:
        family = "DejaVu Sans"
        print("WARNING: no GIL*.TTF in "
              f"{FONT_DIR}; falling back to {family} (humanist-sans "
              "substitute; the figure is not in the paper's Gill Sans).")
    plt.rcParams["font.family"] = family
    return family


def load_latencies(csv_path: pathlib.Path) -> Counter:
    counts: Counter = Counter()
    with open(csv_path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        col = header.index("latency")
        for row in reader:
            counts[int(row[col])] += 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schedules", default=str(HERE / "outputs" / "schedules.csv"))
    ap.add_argument("--summary", default=str(HERE / "outputs" / "summary.json"))
    ap.add_argument("--baselines", default=str(HERE / "outputs" / "baselines.json"))
    ap.add_argument("--stem", default="fig3_design_space")
    ap.add_argument("--commit", default=_head_commit(),
                    help="commit recorded in provenance.json (default: git HEAD)")
    args = ap.parse_args()

    summary = json.loads(pathlib.Path(args.summary).read_text())
    baselines = json.loads(pathlib.Path(args.baselines).read_text())
    counts = load_latencies(pathlib.Path(args.schedules))

    # The CSV is the figure's own input, so it must agree with the summary
    # enumerate.py wrote beside it.
    n_sched = sum(counts.values())
    assert n_sched == summary["n_schedules"], (n_sched, summary["n_schedules"])
    assert len(counts) == summary["n_distinct_latencies"]
    assert min(counts) == summary["best_latency"]
    assert max(counts) == summary["worst_latency"]

    lo, hi = summary["best_latency"], summary["worst_latency"]
    edges = np.logspace(np.log10(lo), np.log10(hi), N_BINS + 1)
    # Nudge the outer edges off the data so float rounding cannot drop the
    # best or the worst latency out of the first/last bin.
    edges[0] = lo / 1.000001
    edges[-1] = hi * 1.000001
    latencies = np.array(sorted(counts), dtype=float)
    weights = np.array([counts[int(v)] for v in latencies], dtype=float)
    heights, _ = np.histogram(latencies, bins=edges, weights=weights)
    assert heights.sum() == n_sched

    family = paper_style()
    width = 243.91125 / 72.27          # 3.375 in single-column width
    fig, ax = plt.subplots(figsize=(width, width * 0.65))
    fig.subplots_adjust(left=0.17, right=0.98, bottom=0.21, top=0.97)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="-", alpha=0.5)
    ax.set_xscale("log")
    ax.bar(edges[:-1], heights, width=np.diff(edges), align="edge",
           color=BAR_COLOR, edgecolor=BAR_COLOR, linewidth=0.3)

    # Architecture markers: one dashed line per distinct solver delay, labelled
    # with every architecture that lands on it.
    by_delay: dict[int, list[str]] = {}
    for row in baselines["baselines"]:
        if not row["has_solution"]:
            continue
        by_delay.setdefault(row["delay"], []).append(DISPLAY.get(row["name"], row["name"]))
    ymax = heights.max() * 1.08
    for delay, names in sorted(by_delay.items()):
        ax.axvline(delay, color=MARK_COLOR, linestyle="--", linewidth=0.8)
        ax.text(delay * 1.06, ymax * 0.97, ", ".join(sorted(names)),
                rotation=90, ha="left", va="top", color=MARK_COLOR, fontsize=8,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.75, "pad": 0.5})

    ax.set_xlim(edges[0] / 1.15, edges[-1] * 1.15)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("Schedule latency (temporal iterations)", labelpad=2)
    ax.set_ylabel("Valid schedules", labelpad=2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e3:g}k"))
    ax.tick_params(pad=1)

    outputs = []
    for suffix in ("pdf", "png"):
        path = HERE / f"{args.stem}.{suffix}"
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.02,
                    metadata={"CreationDate": None} if suffix == "pdf" else None)
        outputs.append(path)
        print(path)
    plt.close(fig)

    marker_text = "; ".join(
        f"{', '.join(sorted(names))} at {delay:,}"
        for delay, names in sorted(by_delay.items())
    )
    gap_text = " and ".join(
        f"{delay // summary['best_latency']}x"
        for delay in sorted(by_delay)
    )
    bounds = summary["bounds"]
    caption = (
        "Figure 3: The multi-node scheduling design space for one layer. "
        f"Workload: ResNet-19 layer3_0_conv2 (layer 16) -- KH={bounds['KH']}, "
        f"KW={bounds['KW']}, CIN={bounds['CIN']}, COUT={bounds['COUT']}, "
        f"HO={bounds['HO']}, WO={bounds['WO']}, T={bounds['T']}, "
        f"{summary['total_work']:,} loop iterations of work. "
        "Hardware: one fixed LAYS configuration -- 16 nodes, 8 PEs x 4 "
        "T-lanes per node (num_pes 32), per-node local buffer "
        f"{summary['lb_byte_caps']['weight']}/{summary['lb_byte_caps']['psum']}/"
        f"{summary['lb_byte_caps']['vmem']} B for weight/psum/vmem, shared "
        f"global buffer {summary['glb_byte_caps']['weight']}/"
        f"{summary['glb_byte_caps']['psum']}/{summary['glb_byte_caps']['vmem']} B, "
        "inter-node fanout at most 16. Bars: the "
        f"{n_sched:,} valid schedules found by exhaustive enumeration "
        f"({summary['n_node_assignments']:,} local-buffer-valid per-dimension "
        "node assignments, each crossed with every legal NoC partition), "
        f"counted into {N_BINS} log-spaced latency bins; "
        f"{summary['n_distinct_latencies']} distinct latencies span "
        f"{summary['best_latency']:,} to {summary['worst_latency']:,} "
        f"iterations, a {summary['spread']}x spread. Latency is the "
        "scheduler's own delay term: the product of every temporally "
        "assigned loop factor, equal to the total work divided by the "
        "schedule's PE, T-lane and node parallelism. Dashed lines: where the "
        "five published architectures land when the real MIP scheduler is "
        "run on this same hardware and layer with each architecture's node "
        f"mapspace ({marker_text} iterations), i.e. {gap_text} the best "
        "schedule this hardware admits.\n"
    )
    (HERE / "caption.txt").write_text(caption)

    provenance = {
        "figure": args.stem,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_commit": args.commit,
        "repo": str(REPO),
        "command": "conda run -n gurobi python zoo/fig3_design_space/plot.py",
        "regenerate_all": [
            "conda run -n gurobi python zoo/fig3_design_space/enumerate.py",
            "python3 zoo/fig3_design_space/run_baselines.py",
            "python3 zoo/fig3_design_space/check_consistency.py",
            "conda run -n gurobi python zoo/fig3_design_space/plot.py",
        ],
        "inputs": {
            "arch": "zoo/fig3_design_space/arch.yaml",
            "layer": "zoo/fig3_design_space/layer.yaml",
            "mapspaces": sorted(
                str(p.relative_to(REPO))
                for p in (HERE / "mapspaces").glob("*.yaml")
            ),
            "schedules_csv": str(pathlib.Path(args.schedules).relative_to(REPO)),
            "summary_json": str(pathlib.Path(args.summary).relative_to(REPO)),
            "baselines_json": str(pathlib.Path(args.baselines).relative_to(REPO)),
            "consistency_json": "zoo/fig3_design_space/outputs/consistency.json",
            "fonts": str(FONT_DIR.relative_to(REPO)),
        },
        "font_family_used": family,
        "n_schedules": n_sched,
        "n_node_assignments": summary["n_node_assignments"],
        "n_distinct_latencies": summary["n_distinct_latencies"],
        "best_latency": summary["best_latency"],
        "worst_latency": summary["worst_latency"],
        "spread": summary["spread"],
        "n_bins": N_BINS,
        "n_occupied_bins": int((heights > 0).sum()),
        "bin_edges": [float(e) for e in edges],
        "bin_heights": [int(h) for h in heights],
        "markers": {str(k): sorted(v) for k, v in sorted(by_delay.items())},
        "baselines_all_feasible": baselines["n_feasible"] == baselines["n_mapspaces"],
        "outputs": [str(p.relative_to(REPO)) for p in outputs],
        "git_status_clean_for_inputs": _git_status(),
    }
    (HERE / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(HERE / "caption.txt")
    print(HERE / "provenance.json")
    print(f"{n_sched:,} schedules, {int((heights > 0).sum())}/{N_BINS} bins occupied, "
          f"markers: {marker_text}")
    return 0


def _head_commit() -> str:
    """Short git HEAD of the repo, for provenance; 'unknown' off a checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _git_status() -> str:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", "zoo/fig3_design_space"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "clean"
    except Exception as exc:          # provenance should never fail the plot
        return f"unavailable: {exc}"


if __name__ == "__main__":
    raise SystemExit(main())
