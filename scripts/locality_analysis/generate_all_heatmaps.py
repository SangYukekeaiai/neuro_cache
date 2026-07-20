#!/usr/bin/env python3
"""Generate the full plan-Sec-4.5 access-count heatmap sweep across the design space.

Scales the milestone-2 walking skeleton (scripts/locality_analysis/walking_skeleton.py)
heatmap from 2 archs x 1 layer x 1 sample to the full cross-product:

    5 archs x 2 networks x every layer x 5 samples {0,20,40,60,80} x 2 row variants.

Two row variants (plan Sec 4.5), one PDF each, one sample per figure:

  - kw  (Heatmap 1, kernel-window): rows = flattened (kh,kw), cols = dram_i tile index,
        cell = raw access count to (kh,kw,cin0,cr0) within that tile, pinned on the
        first access's (cin0, cr0). Reuses walking_skeleton.access_count_matrix
        unchanged (same construction, same pinned-slice rule).
  - cin (Heatmap 2, adjacent-cin): rows = cin index, cols = dram_i tile index,
        cell = raw access count to (kh0,kw0,cin,cr0) within that tile, pinned on the
        first access's (kh0, kw0, cr0). Mirrors access_count_matrix on the cin axis.

Pinned-slice rule (identical to walking_skeleton): pin on the coordinate components of
trace.stream[0] -- the first access in dram_i order, which is by construction in-bounds.
The cr range width is read from the trace per (arch, layer) via trace_io, so the
COUT-clamp rule (plan Sec 1.1, e.g. prosperity COUT=64 -> width 64) flows through
automatically; no width is hardcoded here.

1x1-kernel layers (KH==KW==1) make Heatmap 1's kernel-window neighbor concept degenerate
(plan Sec 2 radius-grid caveat): the kw variant is skipped and marked
'skipped-degenerate'; the cin variant is still produced. (None occur in the current
dataset, but the guard keeps the sweep from asserting a single-row "kernel window".)

Each sample file is parsed ONCE and both variants are built from that single parse.
Idempotent/resumable: a figure whose PDF already exists is not re-plotted
('skipped-exists') but is still recorded. Every attempted figure is written to
heatmaps_manifest.csv with its chosen pinned indices, so the run is reproducible.

Usage (from project root):
    python scripts/locality_analysis/generate_all_heatmaps.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.trace_io import (  # noqa: E402
    ARCHS, NETWORKS, list_layers, load_trace, observed_widths,
)
from locality_analysis.walking_skeleton import access_count_matrix  # noqa: E402

# Fixed 5-of-100 subset, identical across every (arch, network, layer) (plan Sec 4.5).
HEATMAP_SAMPLES = [0, 20, 40, 60, 80]

OUT_ROOT = PROJECT_ROOT / "outputs" / "locality_analysis"
HEATMAP_ROOT = OUT_ROOT / "heatmaps"
MANIFEST_PATH = OUT_ROOT / "heatmaps_manifest.csv"

MANIFEST_COLUMNS = [
    "arch", "network", "layer", "sample", "variant", "pinned_slice",
    "n_rows", "n_tiles", "n_accesses", "output_path", "status",
]


def cin_access_count_matrix(trace):
    """Heatmap 2: rows = cin index, cols = dram_i; cell = raw access count, pinned on
    the first (kh0, kw0, cr0) encountered. Mirrors walking_skeleton.access_count_matrix
    on the cin axis (same pinned-slice rule: components of trace.stream[0])."""
    CIN = trace.dims["CIN"]
    kh0, kw0, _cin0, cs0, ce0 = trace.stream[0]
    cr0 = (cs0, ce0)
    mat = np.zeros((CIN, trace.dram_num_steps), dtype=np.int64)
    for (kh, kw, cin, cs, ce), tile in zip(trace.stream, trace.tile_of):
        if kh == kh0 and kw == kw0 and (cs, ce) == cr0:
            mat[cin, tile] += 1
    return mat, (kh0, kw0, cr0)


def _sparse_ticks(n: int, target: int = 12) -> list[int]:
    """Row indices to label: all of them if few, else ~target evenly spaced."""
    if n <= target:
        return list(range(n))
    step = max(1, n // target)
    return list(range(0, n, step))


def plot_heatmap(mat, row_labels, ylabel, title, out_path: Path) -> None:
    height = min(6.0, 1.5 + 0.35 * len(row_labels))
    fig, ax = plt.subplots(figsize=(11, height))
    im = ax.imshow(mat, aspect="auto", cmap="viridis", interpolation="nearest")
    ticks = _sparse_ticks(len(row_labels))
    ax.set_yticks(ticks)
    ax.set_yticklabels([row_labels[i] for i in ticks], fontsize=6)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.set_xlabel("tile index (dram_i)", fontsize=8)
    ax.set_title(title, fontsize=8)
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.01, label="access count")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _fmt_pin_kw(cin0, cr0) -> str:
    return f"cin0={cin0} cr0=({cr0[0]},{cr0[1]})"


def _fmt_pin_cin(kh0, kw0, cr0) -> str:
    return f"kh0={kh0} kw0={kw0} cr0=({cr0[0]},{cr0[1]})"


def process_sample(arch, network, layer, sample_idx, writer, counts) -> None:
    """Parse one sample once; build/skip both variants; record both in the manifest."""
    out_dir = HEATMAP_ROOT / network / arch / layer
    kw_path = out_dir / f"sample_{sample_idx:05d}_kw.pdf"
    cin_path = out_dir / f"sample_{sample_idx:05d}_cin.pdf"

    trace = load_trace(arch, network, layer, sample_idx)
    KH, KW = trace.dims["KH"], trace.dims["KW"]
    COUT = trace.dims["COUT"]
    widths = sorted(observed_widths(trace))
    n_tiles = trace.dram_num_steps
    degenerate_kw = (KH == 1 and KW == 1)

    # ── kw variant (Heatmap 1) ──────────────────────────────────────────────────
    _, _, cin0, cs0, ce0 = trace.stream[0]
    pin_kw = _fmt_pin_kw(cin0, (cs0, ce0))
    if degenerate_kw:
        writer.writerow([arch, network, layer, sample_idx, "kw", pin_kw,
                         KH * KW, n_tiles, "", "", "skipped-degenerate"])
        counts["skipped-degenerate"] += 1
    elif kw_path.exists():
        writer.writerow([arch, network, layer, sample_idx, "kw", pin_kw,
                         KH * KW, n_tiles, "", str(kw_path), "skipped-exists"])
        counts["skipped-exists"] += 1
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        mat, (cin0m, cr0) = access_count_matrix(trace)
        labels = [f"({r // KW},{r % KW})" for r in range(KH * KW)]
        title = (f"Sec 4.5 kernel-window heatmap - {arch}/{network}/{layer}  "
                 f"sample {sample_idx}\npinned {_fmt_pin_kw(cin0m, cr0)}  "
                 f"(COUT={COUT}, cr width={widths}, "
                 f"{int(mat.sum())} accesses over {n_tiles} tiles)")
        plot_heatmap(mat, labels, "(kh,kw)", title, kw_path)
        writer.writerow([arch, network, layer, sample_idx, "kw",
                         _fmt_pin_kw(cin0m, cr0), KH * KW, n_tiles,
                         int(mat.sum()), str(kw_path), "generated"])
        counts["generated"] += 1

    # ── cin variant (Heatmap 2) ─────────────────────────────────────────────────
    kh0, kw0, _cin0, cs0, ce0 = trace.stream[0]
    pin_cin = _fmt_pin_cin(kh0, kw0, (cs0, ce0))
    CIN = trace.dims["CIN"]
    if cin_path.exists():
        writer.writerow([arch, network, layer, sample_idx, "cin", pin_cin,
                         CIN, n_tiles, "", str(cin_path), "skipped-exists"])
        counts["skipped-exists"] += 1
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        mat, (kh0m, kw0m, cr0) = cin_access_count_matrix(trace)
        labels = [str(r) for r in range(CIN)]
        title = (f"Sec 4.5 adjacent-cin heatmap - {arch}/{network}/{layer}  "
                 f"sample {sample_idx}\npinned {_fmt_pin_cin(kh0m, kw0m, cr0)}  "
                 f"(COUT={COUT}, cr width={widths}, "
                 f"{int(mat.sum())} accesses over {n_tiles} tiles)")
        plot_heatmap(mat, labels, "cin index", title, cin_path)
        writer.writerow([arch, network, layer, sample_idx, "cin",
                         _fmt_pin_cin(kh0m, kw0m, cr0), CIN, n_tiles,
                         int(mat.sum()), str(cin_path), "generated"])
        counts["generated"] += 1


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    start = time.time()
    counts = {"generated": 0, "skipped-exists": 0, "skipped-degenerate": 0,
              "missing-sample": 0}
    total_attempted = 0

    with open(MANIFEST_PATH, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(MANIFEST_COLUMNS)

        for network in NETWORKS:
            for arch in ARCHS:
                layers = list_layers(arch, network)
                print(f"\n=== {arch}/{network}: {len(layers)} layers ===", flush=True)
                for layer in layers:
                    for sample_idx in HEATMAP_SAMPLES:
                        total_attempted += 2  # two variants attempted per sample
                        try:
                            process_sample(arch, network, layer, sample_idx,
                                           writer, counts)
                        except FileNotFoundError as exc:
                            # Missing sample file: record both variants, don't crash.
                            counts["missing-sample"] += 2
                            for variant in ("kw", "cin"):
                                writer.writerow([arch, network, layer, sample_idx,
                                                 variant, "", "", "", "", "",
                                                 "missing-sample"])
                            print(f"  MISSING {arch}/{network}/{layer} "
                                  f"sample {sample_idx}: {exc}", flush=True)
                    done = counts["generated"] + counts["skipped-exists"]
                    print(f"  {layer}: gen={counts['generated']} "
                          f"skip-exists={counts['skipped-exists']} "
                          f"skip-degen={counts['skipped-degenerate']} "
                          f"(figures done={done})", flush=True)
                    fh.flush()

    elapsed = time.time() - start
    print(f"\n=== done in {elapsed:.1f}s ===", flush=True)
    print(f"attempted={total_attempted} generated={counts['generated']} "
          f"skipped-exists={counts['skipped-exists']} "
          f"skipped-degenerate={counts['skipped-degenerate']} "
          f"missing-sample={counts['missing-sample']}", flush=True)
    print(f"manifest -> {MANIFEST_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
