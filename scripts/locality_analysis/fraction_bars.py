#!/usr/bin/env python3
"""Stacked below-/at-or-above-p90 bar charts (plan point 6, Sec 0 decision rule).

Consumes full_aggregation.py's aggregation_manifest.json WITHOUT recomputing any
distance. For each (arch, network, locality_type) it draws ONE stacked bar chart:

  * x-axis = that network's layers in natural (file) order,
  * y-axis = fraction in [0, 1],
  * two stacked segments per bar:
        below p90    = n_below_p90 / n_total
        at-or-above  = 1 - below   = (resolved-not-below + unresolved) / n_total
    where n_total = n_resolved + n_unresolved (ALL pairs; unresolved/⊥ pairs are
    counted in the at-or-above segment, never dropped -- plan Sec 4.4/Sec 8 guard,
    task point 5).

Each layer uses its OWN p90 (from the resolved-only distribution, task point 1) as
the threshold, so the split is generally NOT a flat ~90/10: the ⊥ pairs are scored
against a threshold calibrated only on resolved pairs (task point 6).

1x1-degenerate kernel-window layers (empty N1) carry no bar and are annotated on
the kernel-window charts.

Output (plan Sec 7 artifact #4):
  outputs/locality_analysis/pfire_fraction_bars/<network>/<arch>_{kw,cin}.pdf + png

Usage (from project root, AFTER full_aggregation.py has written the manifest):
    conda run -n base python scripts/locality_analysis/fraction_bars.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.trace_io import ARCHS, NETWORKS, list_layers  # noqa: E402

OUT_ROOT = PROJECT_ROOT / "outputs" / "locality_analysis"
MANIFEST = OUT_ROOT / "dc_distributions" / "aggregation_manifest.json"
BAR_DIR = OUT_ROOT / "pfire_fraction_bars"

# Okabe-Ito colorblind-safe pair; the two segments also differ by hatch so the
# split never relies on colour alone.
COL_BELOW = "#0072b2"    # below p90 (spatial reuse captured at B* = own p90)
COL_ABOVE = "#e69f00"    # at-or-above p90, incl. unresolved (⊥) -> not captured
HATCH_ABOVE = "//"

LOC_NAME = {"kw": "kernel-window", "cin": "adjacent-cin"}


def plot_bars(manifest, network, arch, locality, layers, out_path) -> dict:
    """One stacked bar chart for (network, arch, locality). Returns a small summary."""
    labels, below, above, skipped = [], [], [], []
    for layer in layers:
        key = f"{network}/{arch}/{layer}"
        entry = manifest.get(key, {}).get(locality)
        labels.append(layer)
        if entry is None or entry.get("skipped") or entry["n_resolved"] == 0:
            below.append(0.0)
            above.append(0.0)
            skipped.append(True)
            continue
        total = entry["n_resolved"] + entry["n_unresolved"]
        b = entry["n_below_p90"] / total if total else 0.0
        below.append(b)
        above.append(1.0 - b)
        skipped.append(False)

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(max(6.0, 0.5 * len(labels) + 2.0), 4.2))
    ax.bar(x, below, color=COL_BELOW, label="D_C < p90  (captured)")
    ax.bar(x, above, bottom=below, color=COL_ABOVE, hatch=HATCH_ABOVE,
           edgecolor="white", linewidth=0.3,
           label="D_C ≥ p90 + unresolved(⊥)  (not captured)")

    for xi, (b, sk) in enumerate(zip(below, skipped)):
        if sk:
            ax.text(xi, 0.5, "1×1\nskip", ha="center", va="center",
                    fontsize=6, color="#888888", rotation=0)
        else:
            ax.text(xi, b, f"{b:.2f}", ha="center", va="bottom", fontsize=6)

    # short x tick labels: strip the "layer_NN_" prefix where present
    short = [lbl.split("_", 2)[-1] if lbl.startswith("layer_") else lbl
             for lbl in labels]
    ax.set_xticks(x)
    ax.set_xticklabels(short, rotation=45, ha="right", fontsize=6.5)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("fraction of all anchor→neighbor pairs")
    ax.set_xlabel("layer (network file order)")
    ax.set_title(
        f"{LOC_NAME[locality]} locality capture at own-p90 threshold - "
        f"{arch}/{network}\n"
        f"segments over ALL pairs (unresolved ⊥ counted at-or-above); "
        f"each layer uses its own p90",
        fontsize=8.5,
    )
    ax.legend(fontsize=7, loc="lower center", ncol=2, frameon=False,
              bbox_to_anchor=(0.5, -0.42))
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"n_layers": len(labels), "n_skipped": int(sum(skipped))}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archs", nargs="+", default=ARCHS)
    ap.add_argument("--networks", nargs="+", default=NETWORKS)
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()

    with open(args.manifest) as fh:
        manifest = json.load(fh)

    made = 0
    for network in args.networks:
        for arch in args.archs:
            # layer order: prefer the manifest's own layers for this (net,arch),
            # falling back to the on-disk directory order.
            layers = [k.split("/", 2)[2] for k in manifest
                      if k.startswith(f"{network}/{arch}/")]
            if not layers:
                try:
                    layers = list_layers(arch, network)
                except FileNotFoundError:
                    continue
            for locality in ("kw", "cin"):
                out_path = BAR_DIR / network / f"{arch}_{locality}.pdf"
                summary = plot_bars(manifest, network, arch, locality,
                                    layers, out_path)
                made += 1
                print(f"[{network}/{arch}/{locality}] -> {out_path} "
                      f"({summary['n_layers']} layers, "
                      f"{summary['n_skipped']} skipped)", flush=True)
    print(f"\n{made} stacked bar charts written under {BAR_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
