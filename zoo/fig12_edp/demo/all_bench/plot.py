"""Eight whole-model pages and a separate sum-layer-EDP composition exhibit."""
import argparse
import csv
import json
from pathlib import Path
from common import ARMS, HERE, demo
from layer_scope import scope_rule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=HERE/'whole_model.csv')
    args = parser.parse_args()
    coverage = json.loads((args.input.parent/'coverage.json').read_text())
    if coverage.get('scope', {}).get('sha256') != scope_rule()[2]:
        raise ValueError('collect with the current workload scope before plotting')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.ticker import StrMethodFormatter
    import numpy as np
    rows = list(csv.DictReader(args.input.open()))
    by = {(r['benchmark'], r['arch'], r['arm']): r for r in rows}
    captures = list(dict.fromkeys(r['benchmark'] for r in rows))
    if len(rows) != 120 or len(by) != 120 or len(captures) != 8:
        raise ValueError('expected eight benchmarks x five architectures x three arms')
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ('Gill Sans', 'Gill Sans MT', 'Carlito', 'Lato', 'Cantarell', 'DejaVu Sans') if f in fonts), 'DejaVu Sans')
    # Lato has a flagged 1 and uses the same x-height for text and math digits.
    plt.rcParams.update({'font.family': font, 'font.size': 8, 'pdf.fonttype': 42,
                         'mathtext.fontset': 'custom', 'mathtext.rm': font,
                         'mathtext.it': font, 'mathtext.bf': font, 'mathtext.cal': font,
                         'axes.spines.top': False, 'axes.spines.right': False})
    colors, hatches = ('#999999', '#0072B2', '#E69F00'), ('', '//', '..')
    labels = ('SpinalFlow', 'PTB', 'LoAS', 'GustavSNN', 'Prosperity')
    x, width = np.arange(5), .24
    def panel(ax, capture, metric, ylabel, factor=1):
        for index, arm in enumerate(ARMS):
            for a, arch in enumerate(demo.ARCHES):
                row = by[(capture, arch, arm)]
                position = a+(index-1)*width
                if row[metric] != '':
                    value = float(row[metric])*factor
                    ax.bar(position, value, width, color=colors[index], hatch=hatches[index],
                           edgecolor='black', linewidth=.45)
                    if row['energy_incomplete'] == 'True' and metric != 'sum_latency_s':
                        ax.annotate('*', (position, value), ha='center', va='bottom', fontsize=8)
                else:
                    # A hatch at axis height is a missing marker, never a partial numeric total.
                    from matplotlib.patches import Rectangle
                    ax.add_patch(Rectangle((position-width/2, 0), width, .06,
                                 transform=ax.get_xaxis_transform(), facecolor='white',
                                 edgecolor=colors[index], hatch='xxxx', linewidth=.6))
        ax.set_xticks(x, labels, rotation=25, ha='right')
        ax.set_ylabel(ylabel); ax.set_ylim(bottom=0); ax.set_xlim(-.6, 4.6)
        if not any(by[(capture, a, arm)][metric] for a in demo.ARCHES for arm in ARMS):
            ax.set_ylim(0, 1); ax.set_yticks([])
            ax.text(.5, .6, 'No complete model totals', transform=ax.transAxes, ha='center', fontsize=8)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
        for a, arch in enumerate(demo.ARCHES):
            r = by[(capture, arch, 'spad')]
            coverage = r['coverage']
            suffix = ('; infeas '+r['infeasible_layers']) if int(r['infeasible_layers']) else ''
            suffix += ('; OOM '+r['oom_layers']) if int(r['oom_layers']) else ''
            ax.text(a, 1.03, coverage+suffix, transform=ax.get_xaxis_transform(),
                    ha='center', fontsize=6, rotation=0)
    from matplotlib.patches import Patch
    legend = [Patch(facecolor=c, hatch=h, edgecolor='black', label=a) for a, c, h in zip(ARMS, colors, hatches)]
    legend.append(Patch(facecolor='white', hatch='xxxx', edgecolor='black', label='missing layers'))
    figure_dir = HERE/'figures'; figure_dir.mkdir(exist_ok=True)
    with PdfPages(figure_dir/'whole_model.pdf') as pdf:
        for capture in captures:
            fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
            for ax, (metric, label, factor) in zip(axes, (
                ('sum_latency_s', '(a) Sum latency (ms)', 1e3),
                ('sum_energy_nJ', '(b) Sum energy (mJ)*', 1e-6),
                ('model_EDP_nJ_s', '(c) Model EDP (mJ s)*', 1e-6))):
                panel(ax, capture, metric, label, factor)
            fig.suptitle(capture+' — CNN/GEMM scope', y=1.01, fontsize=10)
            fig.legend(handles=legend, ncol=4, loc='upper center', bbox_to_anchor=(.5, .965), frameon=False)
            fig.text(.5, .015, 'CNN/GEMM layers only; fully connected/FFN layers excluded; attention projections retained. Sample 0, n=1; no variance.\n* Null costs = 0. Coverage uses kept layers; missing/OOM/infeasible scopes have no total bar. EDP = (sum energy) × (sum latency).',
                     ha='center', fontsize=7)
            fig.tight_layout(rect=(0, .13, 1, .88))
            name = capture.replace('/', '__')
            pdf.savefig(fig, bbox_inches='tight')
            fig.savefig(figure_dir/(name+'.pdf'), bbox_inches='tight')
            fig.savefig(figure_dir/(name+'.png'), dpi=300, bbox_inches='tight')
            plt.close(fig)
    fig, axes = plt.subplots(4, 2, figsize=(10.5, 12))
    for ax, capture in zip(axes.flat, captures):
        panel(ax, capture, 'sum_layer_EDP_nJ_s', 'Sum layer EDP (mJ s)*', 1e-6)
        ax.set_title(capture.split('/')[-1], fontsize=8, pad=25)
    fig.legend(handles=legend, ncol=4, loc='upper center', frameon=False)
    fig.text(.5, .01, 'CNN/GEMM scope: sum(E_layer × T_layer), distinct from product-of-sums EDP. FC/FFN excluded; attention retained.\nSample 0, n=1; * incomplete energy lower bounds. Hatched markers mean missing kept layers, not zero.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .05, 1, .965), h_pad=3)
    fig.savefig(figure_dir/'sum_layer_edp.pdf', bbox_inches='tight')
    fig.savefig(figure_dir/'sum_layer_edp.png', dpi=300, bbox_inches='tight'); plt.close(fig)
    caption = (
        'All-benchmark sample-0 demo: eight benchmark pages, five architectures and three arms per page. '
        'Each complete group sums only the kept spiking-CNN/spiking-GEMM layers, not the entire neural network. '
        'The canonical docs/workload_layer_scope.md rule excludes fully connected classifiers and transformer FFN/MLP; '
        'attention projections are retained with keep precedence. Scope: 113 of 151 captured layers, '
        '559 feasible architecture/layer pairs plus six kept infeasible pairs. '
        'Latency is the sum of kept-layer runtimes at 500 MHz; '
        'energy is the sum of dynamic plus leakage energy. Whole-model EDP is (sum E)*(sum T), assuming sequential layers. '
        'The separate sum_layer_edp exhibit shows sum(E_layer*T_layer), a layer composition statistic, not model EDP. '
        'Absolute units are ms, mJ and mJ s; each panel starts at zero and has its own scale. '
        'No ratios compare architectures with missing layers. Cross-hatched axis markers mean a model total is unavailable; '
        'coverage is completed/nominal kept layers and infeasible/OOM counts are printed when present. All six infeasible '
        'Prosperity A08 schedules remain in nominal coverage. Partial sums exist only in explicitly named CSV fields. '
        'Asterisks denote incomplete characterization: null costs contribute zero, so energy and EDP are lower bounds. '
        'Fully covered models can still have incomplete energy. Sample 0 only (n=1 when any layer exists, n=0 for empty groups); '
        'no error bars, variance estimate or significance claims. A and B are production configs; A uses L2 distance 1.\n'
        f'Font: {font}; '+('Gill Sans unavailable; installed humanist sans fallback.\n' if not font.startswith('Gill') else '\n')+
        'Source: validated cases -> results.csv -> whole_model.csv -> figures/*.pdf and *.png (300 dpi).\n'
        'Reproduce CSV: PYTHONDONTWRITEBYTECODE=1 conda run -n fig12-archx python -B zoo/fig12_edp/demo/all_bench/run.py --collect-only\n'
        'Reproduce figures: PYTHONDONTWRITEBYTECODE=1 conda run -n gurobi python -B zoo/fig12_edp/demo/all_bench/plot.py\n')
    (HERE/'caption.txt').write_text(caption)
    print(f'pages=8 groups={len(rows)} font={font} outputs={figure_dir}')


if __name__ == '__main__':
    main()
