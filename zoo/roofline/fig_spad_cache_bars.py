"""Cross-column bar figure: cacheA vs spad per architecture and benchmark.

Prosperity-fig-8 structure (benchmarks on x, one bar per architecture,
geomean group last) drawn in the cache_dse ten-bar figure's style (two
stacked panels, dashed baseline at 1.0, italic better-direction notes,
group separators, the same five-colour palette).

Single panel (user call 2026-11-16: EDP only, no perf/traffic panels):
whole-model EDP = EDP_cacheA / EDP_spad per input sample (paired), mean.
Performance and traffic ratios are still computed and printed for the
prose geomeans, but not drawn.
Error bars: 95% Student-t CI over the n=23 complete samples.
cacheB is excluded (kept out of the paper's spad-vs-cache comparison).

Run: conda run -n base python fig_spad_cache_bars.py
"""
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.patches import Patch

import csv

import fig12_roofline as base

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
# ASAP7 1 GHz repriced whole-model EDP (zoo/fig12_edp/stokes/asap7_reprice.py)
EDP_DIR = HERE.parent / "fig12_edp/stokes/results_asap7_20261116"

# same palette as zoo/cache_dse/stokes_kit/plot.py GROUP_COLOUR
ARCH_COLOUR = {"gustavsnn": "#444444", "loas": "#4477aa", "prosperity": "#228833",
               "ptb": "#aa3377", "spinalflow": "#ee6677"}
WORKLOADS = [
    ("A02/spikformer_4_384_cifar100_T4_n500", "spikformer\ncifar100"),
    ("A04/sdt_2_512_cifar100_T4_n500", "sdt\ncifar100"),
    ("A07/spikinglm_t4_T4_n500", "spikinglm"),
    ("A08/vgg16_cifar10_loas_T32_n500", "vgg16\nT32"),
    ("B09/loas_resnet19_T4_n500", "resnet19"),
    ("B09/loas_vgg16_T4_n500", "vgg16\nT4"),
    ("C01/sma_azo_vgg_cifar10_dvs_T10_n500", "cifar10\ndvs"),
    ("C01/sma_azo_vgg_dvs128_gesture_T16_n500", "dvs128\ngesture"),
]


def edp_ratios():
    """(arch, workload) -> per-sample model_EDP cacheA / spad, paired on sample."""
    edp = {}
    for path in sorted(EDP_DIR.glob("sample_*/whole_model_asap7.csv")):
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                if row["coverage_complete"] != "True" or row["incomplete"] == "True":
                    continue
                key = (row["arch"], row["arm"], row["benchmark"])
                edp.setdefault(key, {})[row["sample"]] = float(row["model_EDP_nJ_s"])
    out = {}
    for arch in base.ARCHES:
        for wl, _ in WORKLOADS:
            spad = edp.get((arch, "spad", wl))
            cache = edp.get((arch, "cacheA", wl))
            if not spad or not cache:
                continue
            ids = sorted(set(spad) & set(cache))
            out[(arch, wl)] = [cache[i] / spad[i] for i in ids]
    return out


def paired_ratios(samples_by_group):
    """(arch, workload) -> {"perf": [per-sample T_spad/T_cacheA], "traffic": [...]}."""
    out = {}
    for arch in base.ARCHES:
        for wl, _ in WORKLOADS:
            spad = samples_by_group.get((arch, "spad", wl))
            cache = samples_by_group.get((arch, "cacheA", wl))
            if not spad or not cache:
                continue
            s_by_id = {s["sample"]: s for s in spad}
            c_by_id = {s["sample"]: s for s in cache}
            ids = sorted(set(s_by_id) & set(c_by_id))
            if len(ids) != len(s_by_id) or len(ids) != len(c_by_id):
                print(f"note: {arch}/{wl}: paired {len(ids)} of "
                      f"{len(s_by_id)} spad / {len(c_by_id)} cacheA samples")
            out[(arch, wl)] = {
                "perf": [s_by_id[i]["time_s"] / c_by_id[i]["time_s"] for i in ids],
                "traffic": [c_by_id[i]["bytes"] / s_by_id[i]["bytes"] for i in ids],
            }
    return out


def main() -> None:
    wanted = ["Gill Sans", "Gill Sans MT", "Lato", "Source Sans Pro", "DejaVu Sans"]
    installed = {f.name for f in fm.fontManager.ttflist}
    family = next((w for w in wanted if w in installed), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": family, "font.size": 8,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family, "mathtext.bf": family,
    })

    samples_by_group, _ = base.load_extract(OUT / "extract.csv")
    ratios = paired_ratios(samples_by_group)
    for key_wl, vals in edp_ratios().items():
        ratios.setdefault(key_wl, {})["edp"] = vals

    # geomean per arch: per sample, geomean over that arch's covered workloads
    geo = {}
    for arch in base.ARCHES:
        geo[arch] = {}
        for key in ("perf", "traffic", "edp"):
            wls = [wl for wl, _ in WORKLOADS if key in ratios.get((arch, wl), {})]
            n = min(len(ratios[(arch, wl)][key]) for wl in wls)
            geo[arch][key] = [
                math.exp(sum(math.log(ratios[(arch, wl)][key][i]) for wl in wls) / len(wls))
                for i in range(n)]
            if len(wls) != len(WORKLOADS):
                missing = [w for w, _ in WORKLOADS if w not in wls]
                print(f"note: {arch} {key} geomean over {len(wls)} benchmarks; missing: {missing}")

    # geomeans are printed for the prose but not drawn (user call: no geomean group)
    groups = [wl for wl, _ in WORKLOADS]
    labels = [short for _, short in WORKLOADS]
    n_arch = len(base.ARCHES)
    width = 0.8 / n_arch
    fig, axe = plt.subplots(figsize=(7.0, 2.5))
    key, ylabel, better = "edp", "EDP / spad\n(E x t)", "lower is better"
    panel_vals = []
    for ai, arch in enumerate(base.ARCHES):
        xs, means, errs = [], [], []
        for gi, wl in enumerate(groups):
            vals = ratios.get((arch, wl), {}).get(key)
            if not vals:
                continue
            mean, lo, hi = base._ci(vals)
            xs.append(gi + (ai - (n_arch - 1) / 2) * width)
            means.append(mean)
            errs.append(hi - mean)
        panel_vals.extend(means)
        axe.bar(xs, means, width=width * 0.94, color=ARCH_COLOUR[arch],
                edgecolor="0.25", lw=0.5, zorder=3)
        axe.errorbar(xs, means, yerr=errs, fmt="none", ecolor="0.2",
                     elinewidth=0.7, capsize=1.6, zorder=4)
    axe.axhline(1.0, color="0.3", lw=1.0, ls="--", zorder=2)
    axe.text(len(groups) - 0.52, 1.02, "spad", fontsize=6.4, color="0.3",
             ha="right", va="bottom")
    axe.set_yscale("log", base=2)
    lo, hi = min(panel_vals), max(panel_vals)
    axe.set_ylim(lo * 0.7, hi * 1.5)
    ticks = [t for t in (0.004, 0.016, 0.0625, 0.25, 0.5, 1, 2, 4, 8, 16)
             if lo * 0.7 <= t <= hi * 1.5]
    axe.set_yticks(ticks)
    axe.set_yticklabels([f"{t:g}" for t in ticks])
    axe.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    axe.set_ylabel(ylabel, fontsize=8)
    axe.text(0.004, 0.96, better, transform=axe.transAxes, fontsize=6.8,
             color="0.3", style="italic", va="top")
    axe.grid(axis="y", alpha=0.25, lw=0.4, zorder=0)
    axe.tick_params(labelsize=7)
    for sp in ("top", "right"):
        axe.spines[sp].set_visible(False)
    for gi in range(1, len(groups)):
        axe.axvline(gi - 0.5, color="0.85", lw=0.7, zorder=1)
    axe.set_xticks(np.arange(len(groups)))
    axe.set_xticklabels(labels, fontsize=6.8)
    axe.set_xlim(-0.6, len(groups) - 0.4)
    axe.set_xlabel("benchmark (whole model)", fontsize=8)
    axe.legend(handles=[Patch(facecolor=ARCH_COLOUR[a], edgecolor="0.25", label=a)
                        for a in base.ARCHES],
               fontsize=6.8, ncol=5, frameon=False, loc="lower center",
               bbox_to_anchor=(0.5, 1.0), handletextpad=0.4, columnspacing=1.0,
               borderaxespad=0.0)
    fig.tight_layout()
    fig.savefig(OUT / "fig_spad_cache_bars.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_spad_cache_bars.png", bbox_inches="tight", dpi=300)

    print(f"font: {family}")
    for arch in base.ARCHES:
        p, plo, phi = base._ci(geo[arch]["perf"])
        t, tlo, thi = base._ci(geo[arch]["traffic"])
        e, elo, ehi = base._ci(geo[arch]["edp"])
        print(f"{arch:11s} geomean perf x{p:.3f} [{plo:.3f},{phi:.3f}]  "
              f"traffic x{t:.3f} [{tlo:.3f},{thi:.3f}]  "
              f"edp x{e:.3f} [{elo:.3f},{ehi:.3f}]")
    worst = min(((arch, wl, base._ci(r["perf"])[0]) for (arch, wl), r in ratios.items()),
                key=lambda t: t[2])
    print(f"weakest perf case: {worst[0]} on {worst[1]}: x{worst[2]:.3f}")
    print("wrote outputs/fig_spad_cache_bars.pdf / .png")


if __name__ == "__main__":
    main()
