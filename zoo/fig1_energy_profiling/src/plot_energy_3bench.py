"""Figure 1 benchmark panels on LoAS, selectable via --panels (user calls
2026-11-17): any of spikinglm / resnet19 / vgg16, off-chip segments only,
normalized to each panel's 128 KiB off-chip energy, per-bar labels giving
the gap to that baseline.

Run: MPLCONFIGDIR=zoo/fig1_energy_profiling/outputs/mplconfig \
  conda run -n base python -B zoo/fig1_energy_profiling/src/plot_energy_3bench.py \
      [--panels resnet19 vgg16]
"""
import argparse
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
PANEL_DEFS = {  # name -> (title, numbers csv, arch filter)
    'spikinglm': ('SpikingLM', 'spikinglm_fig1_numbers.csv', 'loas'),
    'resnet19': ('ResNet19', 'resnet19_fig1_numbers.csv', 'loas'),
    'vgg16': ('VGG16', 'fig1_numbers.csv', 'loas'),
}
SUFFIX = {('spikinglm', 'resnet19', 'vgg16'): '_3bench',
          ('resnet19', 'vgg16'): '_resnet_vgg'}
CAPTION_PHRASES = {
    'spikinglm': 'SpikingLM (48 kept attention GEMMs, bert-base, T=4)',
    'resnet19': 'spiking ResNet19 (13 replayable stride-1 convolutions, T=4)',
    'vgg16': 'spiking VGG16 (12 kept convolution layers)',
}
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panels', nargs='+', choices=sorted(PANEL_DEFS),
                        default=['spikinglm', 'resnet19', 'vgg16'])
    args = parser.parse_args()
    suffix = SUFFIX[tuple(args.panels)]
    panels = [PANEL_DEFS[name] for name in args.panels]
    data = {}
    for title, name, arch in panels:
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
        'xtick.labelsize': 6.5, 'ytick.labelsize': 8, 'legend.fontsize': 7,
        'mathtext.fontset': 'custom', 'mathtext.rm': 'DejaVu Sans',
        'mathtext.it': 'DejaVu Sans', 'mathtext.bf': 'DejaVu Sans',
        'mathtext.cal': 'DejaVu Sans', 'pdf.fonttype': 42, 'ps.fonttype': 42})
    figsize = {3: (3.5, 1.6), 2: (3.3, 1.55)}[len(panels)]
    fig, axes = plt.subplots(1, len(panels), figsize=figsize, sharey=True)
    handles = []
    tops = {}
    for title, _, _ in panels:
        norm = sum(data[title][(BASELINE, s)] for s in SEGMENTS)
        tops[title] = [sum(data[title][(b, s)] for s in SEGMENTS) / norm for b in BARS]
    maximum = max(max(v) for v in tops.values())
    for ai, ((title, _, _), ax) in enumerate(zip(panels, axes)):
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
        previous = None  # (height, offset) of the last label; stagger near-ties
        for xi, (b, total) in enumerate(zip(BARS, tops[title])):
            if b == BASELINE:
                continue
            offset = maximum * .03
            if previous and abs(total - previous[0]) < maximum * .08:
                offset = maximum * .13 if previous[1] == maximum * .03 else maximum * .03
            ax.text(xi, total + offset, f'${(total-1)*100:+.0f}\\%$',
                    ha='center', va='bottom', fontsize=5.6 if len(panels) > 2 else 6.5)
            previous = (total, offset)
        ax.set_xticks(x, LABELS)
        ax.set_title(title, fontweight='bold',
                     fontsize=8.5 if len(panels) > 2 else 9, pad=2)
        ax.set_ylim(0, maximum * 1.18)
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis='y', alpha=.15, linewidth=.4)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
        ax.tick_params(axis='x', labelrotation=45)
    axes[0].set_ylabel('Normalized off-chip\nenergy (128 KiB = 1)', fontsize=7)
    fig.legend(handles, LEGEND, loc='upper center', bbox_to_anchor=(.55, 1.06),
               ncol=2, frameon=False)
    fig.subplots_adjust(left=.14, right=.995, bottom=.22, top=.76, wspace=.14)
    for extension in ('pdf', 'png'):
        fig.savefig(ROOT / f'outputs/fig1_energy_profiling{suffix}.{extension}',
                    dpi=300, bbox_inches='tight')
    plt.close(fig)
    validation = {n: json.loads((ROOT / f'outputs/{n}_energy_validation.json').read_text())
                  for n in args.panels if n != 'vgg16'}
    any_table = next(iter(validation.values()))['table_sha256']
    caption = ('Figure 1. Off-chip energy of single-node LoAS on '
               + ', '.join(CAPTION_PHRASES[n] for n in args.panels)
               + ' as the weight SRAM grows from 128 KiB to 1 MiB, normalized to '
               'each benchmark\'s 128 KiB configuration; labels give the gap to that '
               'baseline. Ideal fetches only spike-selected weights (n = 10 samples; '
               'ASAP7 synthesis-only logic prices, table SHA256 '
               + any_table[:16] + '...).')
    (ROOT / f'outputs/fig1{suffix}_caption.txt').write_text(caption + '\n')
    provenance = {
        'panels': {PANEL_DEFS[n][0]: PANEL_DEFS[n][1] for n in args.panels},
        **{f'{n}_validation_sha256': sha(ROOT / f'outputs/{n}_energy_validation.json')
           for n in args.panels if n != 'vgg16'},
        'vgg16_numbers_sha256': sha(ROOT / 'outputs/fig1_numbers.csv'),
        'display': 'off-chip segments only, per-panel 128KiB normalization; no CIs drawn',
        'ideal_semantics': {
            **{PANEL_DEFS[n][0]: validation[n]['ideal_semantics'] for n in validation},
            **({'VGG16': 'analytic runtime bracket midpoint (unchanged published numbers)'}
               if 'vgg16' in args.panels else {})},
        'font': textfont, 'plot_code_sha256': sha(Path(__file__)),
        'files': {f'fig1_energy_profiling{suffix}.{e}':
                  sha(ROOT / f'outputs/fig1_energy_profiling{suffix}.{e}')
                  for e in ('pdf', 'png')}}
    (ROOT / f'outputs/fig1{suffix}_provenance.json').write_text(
        json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'font': textfont, 'suffix': suffix}, indent=2))


if __name__ == '__main__':
    main()
