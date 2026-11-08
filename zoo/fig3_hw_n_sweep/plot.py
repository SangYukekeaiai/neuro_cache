"""Whole-network latency distributions across hardware node sizes."""

import csv
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator

ROOT = Path(__file__).resolve().parent
COLORS = {"vgg16": "#648FFF", "resnet19": "#FFB000"}
LABELS = {"vgg16": "VGG16", "resnet19": "ResNet19 (13/19)"}


def load_summary():
    manifest = json.loads((ROOT / "inputs/manifest.json").read_text())
    with (ROOT / "outputs/results.csv").open(newline="") as f:
        layers = list(csv.DictReader(f))
    with (ROOT / "outputs/summary.csv").open(newline="") as f:
        rows = [{key: value if key == "network" else int(value) for key, value in row.items()}
                for row in csv.DictReader(f)]
    expected = {(network, layer, n, s) for network, info in manifest["networks"].items()
                for layer in info["included_layers"] for n in manifest["hardware_sizes"]
                for s in manifest["samples"]}
    assert len(layers) == len(expected) == 625
    assert {(r["network"], r["layer"], int(r["N"]), int(r["sample"])) for r in layers} == expected
    keys = {(network, n, s) for network in manifest["networks"]
            for n in manifest["hardware_sizes"] for s in manifest["samples"]}
    assert len(rows) == len(keys) == 50
    assert {(r["network"], r["N"], r["sample"]) for r in rows} == keys
    for row in rows:
        group = [r for r in layers if (r["network"], int(r["N"]), int(r["sample"]))
                 == (row["network"], row["N"], row["sample"])]
        assert row["layers"] == len(group) == len(manifest["networks"][row["network"]]["included_layers"])
        assert row["total_cycles"] == sum(int(r["total_cycles"]) for r in group)
        assert row["count_cycles"] == sum(int(r["count_cycles"]) for r in group)
        assert row["memory_cycles"] == row["total_cycles"] - row["count_cycles"] >= 0
    return manifest, rows


def paper_style():
    plt.rcParams.update({
        "font.family": "Gill Sans MT", "font.size": 8,
        "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "figure.titlesize": 8,
        "hatch.color": "black", "hatch.linewidth": 0.5,
        "mathtext.default": "regular", "mathtext.fontset": "cm",
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fonts = sorted(p for p in ROOT.iterdir() if p.is_file()
                   and p.name.upper().startswith("GIL") and p.suffix.lower() == ".ttf")
    for font in fonts:
        font_manager.fontManager.addfont(str(font))
    if fonts:
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(fonts[0])).get_name()
    else:
        plt.rcParams["font.family"] = matplotlib.rcParamsDefault["font.family"]
        print("WARNING: no GIL*.TTF/ttf in campaign folder; using Matplotlib's default font (DejaVu Sans).")


def main():
    manifest, rows = load_summary()
    paper_style()
    width = 243.91125 / 72.27
    fig, ax = plt.subplots(figsize=(width, width * 0.65))
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.23, top=0.82)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="-", alpha=0.5)
    handles = []
    for network, offset, marker in (("vgg16", -0.16, "o"), ("resnet19", 0.16, "s")):
        positions = [i + offset for i in range(len(manifest["hardware_sizes"]))]
        data = [[r["total_cycles"] for r in rows if r["network"] == network and r["N"] == n]
                for n in manifest["hardware_sizes"]]
        assert all(len(group) == 5 for group in data)
        color = COLORS[network]
        ax.boxplot(data, positions=positions, widths=0.25, whis=(0, 100), showfliers=False,
                   manage_ticks=False, patch_artist=True,
                   boxprops={"facecolor": color, "edgecolor": color, "alpha": 0.35, "linewidth": 0.7},
                   whiskerprops={"color": color, "linewidth": 0.7},
                   capprops={"color": color, "linewidth": 0.7},
                   medianprops={"color": color, "linewidth": 1})
        medians = [median(group) for group in data]
        ax.plot(positions, medians, color=color, marker=marker, markersize=3, linewidth=1)
        handles.append(Line2D([], [], color=color, marker=marker, markersize=3,
                              linewidth=1, label=LABELS[network]))
        for n, group in zip(manifest["hardware_sizes"], data):
            print(json.dumps(dict(network=network, N=n, median=median(group), min=min(group), max=max(group))))
    ax.set_xticks(range(5), [str(n) for n in manifest["hardware_sizes"]])
    ax.set_xlim(-0.6, 4.6)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Node size N (PEs)", labelpad=2)
    ax.set_ylabel("Latency (cycles)", labelpad=2)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1e6:g}M"))
    ax.tick_params(pad=1)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=2,
               frameon=False, borderpad=0.17, handletextpad=0.4, columnspacing=0.6, handlelength=0.5)
    for suffix in ("pdf", "png"):
        path = ROOT / f"fig3_hw_n_sweep.{suffix}"
        fig.savefig(path, dpi=300, metadata={"CreationDate": None} if suffix == "pdf" else None)
        print(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
