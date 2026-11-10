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
from matplotlib.ticker import FuncFormatter, MultipleLocator

ROOT = Path(__file__).resolve().parent
COLORS = {
    "resnet19": "#FFB000",
    "vgg16": "#785EF0",
    "sdt": "#DC267F",
    "vgg8dvs": "#648FFF",
}
MARKERS = {"resnet19": "s", "vgg16": "o", "sdt": "^", "vgg8dvs": "D"}
DISPLAY_NAMES = {"resnet19": "ResNet$19$", "vgg16": "VGG$16$", "sdt": "SDT", "vgg8dvs": "VGG$8$-DVS"}


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
    assert len(layers) == len(expected)
    assert {(r["network"], r["layer"], int(r["N"]), int(r["sample"])) for r in layers} == expected
    keys = {(network, n, s) for network in manifest["networks"]
            for n in manifest["hardware_sizes"] for s in manifest["samples"]}
    assert len(rows) == len(keys)
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
    digits = ROOT / "DIGITS.ttf"
    if digits.is_file():
        font_manager.fontManager.addfont(str(digits))
        family = font_manager.FontProperties(fname=str(digits)).get_name()
        plt.rcParams.update({"mathtext.fontset": "custom", "mathtext.default": "rm",
                             "mathtext.rm": family, "mathtext.it": family,
                             "mathtext.bf": family, "mathtext.cal": family})
    else:
        print("WARNING: DIGITS.ttf missing (run make_digit_font.py); numbers fall back to Computer Modern.")
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
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.23, top=0.97)
    ax.yaxis.set_major_locator(MultipleLocator(5e6))
    ax.yaxis.set_minor_locator(MultipleLocator(1e6))
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="-", alpha=0.5)
    handles = []
    networks = list(manifest["networks"])
    sample_count = len(manifest["samples"])
    network_offsets = {
        network: (index - (len(networks) - 1) / 2) * 0.18
        for index, network in enumerate(networks)
    }
    box_width = min(0.16, 0.7 / max(1, len(networks)))
    all_values = []
    for network in networks:
        marker = MARKERS[network]
        positions = list(range(len(manifest["hardware_sizes"])))
        data = [[r["total_cycles"] for r in rows if r["network"] == network and r["N"] == n]
                for n in manifest["hardware_sizes"]]
        assert all(len(group) == sample_count for group in data)
        all_values.extend(value for group in data for value in group)
        color = COLORS[network]
        offset = network_offsets[network]
        ax.boxplot(data, positions=[position + offset for position in positions], widths=box_width,
                   whis=(0, 100), showfliers=False,
                   manage_ticks=False, patch_artist=True,
                   boxprops={"facecolor": color, "edgecolor": color, "alpha": 0.35, "linewidth": 0.7},
                   whiskerprops={"color": color, "linewidth": 0.7},
                   capprops={"color": color, "linewidth": 0.7},
                   medianprops={"color": color, "linewidth": 1})
        medians = [median(group) for group in data]
        ax.plot([position + offset for position in positions], medians,
                color=color, marker=marker, markersize=3, linewidth=1)
        info = manifest["networks"][network]
        included = len(info["included_layers"])
        total = included + len(info.get("excluded_layers", {}))
        label = f"{DISPLAY_NAMES[network]} (${included}/{total}$)"
        handles.append(Line2D([], [], color=color, marker=marker, markersize=3,
                              linewidth=1, label=label))
        for n, group in zip(manifest["hardware_sizes"], data):
            print(json.dumps(dict(network=network, N=n, median=median(group), min=min(group), max=max(group))))
    ax.set_ylim(0, max(all_values) * 1.05)
    ax.set_xticks(range(len(manifest["hardware_sizes"])), [f"${n}$" for n in manifest["hardware_sizes"]])
    ax.set_xlim(-0.5, len(manifest["hardware_sizes"]) - 0.5)
    ax.set_xlabel("Node size N (PEs)", labelpad=2)
    ax.set_ylabel("Latency (cycles)", labelpad=2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value / 1e6:g}$M"))
    ax.tick_params(pad=1)
    ax.legend(handles=handles, loc="upper right", frameon=False, borderpad=0.3,
              handletextpad=0.4, labelspacing=0.3, handlelength=0.5)
    for suffix in ("pdf", "png"):
        path = ROOT / f"fig2_hw_n_sweep.{suffix}"
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.02,
                    metadata={"CreationDate": None} if suffix == "pdf" else None)
        print(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
