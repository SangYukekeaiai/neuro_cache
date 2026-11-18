"""Figure 1 with the PTB panel replaced by SpikingLM on LoAS (user call
2026-11-17): two panels, off-chip segments only, normalized to each panel's
128 KiB off-chip energy, per-bar labels giving the gap to that baseline.
Left: SpikingLM (48 kept attention GEMMs, A07 capture). Right: VGG16
(12 kept convolution layers) - unchanged data from fig1_numbers.csv.

Run: MPLCONFIGDIR=zoo/fig1_energy_profiling/outputs/mplconfig \
  conda run -n base python -B zoo/fig1_energy_profiling/src/plot_energy_spikinglm.py
"""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager as fm
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PANELS = (  # (title, numbers csv, arch filter)
    ('SpikingLM', 'spikinglm_fig1_numbers.csv', 'loas'),
    ('VGG16', 'fig1_numbers.csv', 'loas'),
)
BARS = ('128k', '256k', '512k', '1m', 'ideal')
LABELS = ('$128$K', '$256$K', '$512$K', '$1$M', 'Ideal')
SEGMENTS = ('off_chip_weights', 'off_chip_other')
LEGEND = ('Off-chip weights', 'Off-chip other')
COLORS = ('#D55E00', '#999999')
HATCHES = ('//', 'xx')
BASELINE = '128k'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    data = {}
    for title, name, arch in PANELS:
        rows = list(csv.DictReader((ROOT / 'outputs' / name).open()))
        data[title] = {(r['bar'], r['segment']): float(r['normalized_mean'])
                       for r in rows if r['arch'] == arch}
    available = {f.name for f in fm.fontManager.ttflist}
    # Cantarell's style flags break this matplotlib's PDF embedder; skip it
    textfont = ('Gill Sans' if 'Gill Sans' in available
                else 'Gill Sans MT' if 'Gill Sans MT' in available
                else 'DejaVu Sans')
    plt.rcParams.update({
        'font.family': textfont, 'font.size': 8, 'axes.labelsize': 8,
        'xtick.labelsize': 7, 'ytick.labelsize': 8, 'legend.fontsize': 7,
        'mathtext.fontset': 'custom', 'mathtext.rm': 'DejaVu Sans',
        'mathtext.it': 'DejaVu Sans', 'mathtext.bf': 'DejaVu Sans',
        'mathtext.cal': 'DejaVu Sans', 'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.65), sharey=True)
    handles = []
    tops = {}
    for title, _, _ in PANELS:
        norm = sum(data[title][(BASELINE, s)] for s in SEGMENTS)
        tops[title] = [sum(data[title][(b, s)] for s in SEGMENTS) / norm for b in BARS]
    maximum = max(max(v) for v in tops.values())
    for ai, ((title, _, _), ax) in enumerate(zip(PANELS, axes)):
        norm = sum(data[title][(BASELINE, s)] for s in SEGMENTS)
        x = np.arange(len(BARS))
        bottom = np.zeros(len(BARS))
        for segment, color, hatch, label in zip(SEGMENTS, COLORS, HATCHES, LEGEND):
            values = np.array([data[title][(b, segment)] for b in BARS]) / norm
            bars = ax.bar(x, values, .73, bottom=bottom, color=color, hatch=hatch,
                          edgecolor='#333333', linewidth=.35, label=label)
            if ai == 0:
                handles.append(bars[0])
            bottom += values
        for xi, (b, total) in enumerate(zip(BARS, tops[title])):
            if b == BASELINE:
                continue
            ax.text(xi, total + maximum * .03, f'${(total-1)*100:+.0f}\\%$',
                    ha='center', va='bottom', fontsize=6.5)
        ax.set_xticks(x, LABELS)
        ax.set_title(title, fontweight='bold', fontsize=9, pad=2)
        ax.set_ylim(0, maximum * 1.18)
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis='y', alpha=.15, linewidth=.4)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
        ax.tick_params(axis='x', labelrotation=45)
    axes[0].set_ylabel('Normalized off-chip\nenergy (128 KiB = 1)', fontsize=7)
    fig.legend(handles, LEGEND, loc='upper center', bbox_to_anchor=(.55, 1.06),
               ncol=2, frameon=False)
    fig.subplots_adjust(left=.16, right=.99, bottom=.21, top=.78, wspace=.12)
    for extension in ('pdf', 'png'):
        fig.savefig(ROOT / f'outputs/fig1_energy_profiling_spikinglm.{extension}',
                    dpi=300, bbox_inches='tight')
    plt.close(fig)
    validation = json.loads((ROOT / 'outputs/spikinglm_energy_validation.json').read_text())
    caption = ('Figure 1. Off-chip energy of single-node LoAS on SpikingLM (48 kept '
               'attention GEMMs, bert-base, T=4) and spiking VGG16 (12 kept convolution '
               'layers) as the weight SRAM grows from 128 KiB to 1 MiB, normalized to each '
               'benchmark\'s 128 KiB configuration; labels give the gap to that baseline. '
               'Ideal fetches only spike-selected weights (n = 10 samples; ASAP7 '
               'synthesis-only logic prices, table SHA256 '
               + validation['table_sha256'][:16] + '...).')
    (ROOT / 'outputs/fig1_spikinglm_caption.txt').write_text(caption + '\n')
    provenance = {
        'panels': {t: n for t, n, _ in PANELS},
        'spikinglm_validation_sha256': sha(ROOT / 'outputs/spikinglm_energy_validation.json'),
        'vgg16_numbers_sha256': sha(ROOT / 'outputs/fig1_numbers.csv'),
        'display': 'off-chip segments only, per-panel 128KiB normalization; no CIs drawn',
        'ideal_semantics': {'SpikingLM': validation['ideal_semantics'],
                            'VGG16': 'analytic runtime bracket midpoint (unchanged '
                                     'published numbers)'},
        'font': textfont, 'plot_code_sha256': sha(Path(__file__)),
        'files': {n: sha(ROOT / 'outputs' / n) for n in
                  ('fig1_energy_profiling_spikinglm.pdf',
                   'fig1_energy_profiling_spikinglm.png')}}
    (ROOT / 'outputs/fig1_spikinglm_provenance.json').write_text(
        json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'font': textfont}, indent=2))


if __name__ == '__main__':
    main()
