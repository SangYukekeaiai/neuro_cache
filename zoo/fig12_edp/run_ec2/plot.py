"""Render a sample-0 checkpoint, with missing totals and subsets labelled."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    out = parser.parse_args().checkpoint
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Patch, Rectangle
    from config import ARCHES, ARMS
    with (out/'whole_model.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    coverage = json.loads((out/'coverage.json').read_text())
    plt.rcParams.update({'font.size': 8, 'font.family': 'DejaVu Sans', 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False})
    colors = ('#999999', '#0072B2', '#E69F00'); hatches = ('', '//', '..')
    legend = [Patch(facecolor=c, hatch=h, edgecolor='black', label=a) for a, c, h in zip(ARMS, colors, hatches)]
    title = f"SUBSET: {coverage['selected_pairs']}/749 feasible pairs" if coverage['subset'] else 'All 749 feasible pairs attempted'
    with PdfPages(out/'draft.pdf') as pdf:
        for capture in dict.fromkeys(r['capture'] for r in rows):
            by = {(r['arch'], r['arm']): r for r in rows if r['capture'] == capture}
            fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
            for ax, metric, ylabel, factor in zip(axes,
                    ('sum_latency_s', 'sum_energy_nJ', 'model_EDP_nJ_s'),
                    ('Latency (ms)', 'Energy (mJ)*', 'Model EDP (mJ s)*'), (1e3, 1e-6, 1e-6)):
                for a, arch in enumerate(ARCHES):
                    for i, arm in enumerate(ARMS):
                        value = by[(arch, arm)][metric]; x = a+(i-1)*.24
                        if value:
                            ax.bar(x, float(value)*factor, .24, color=colors[i], hatch=hatches[i], edgecolor='black', linewidth=.4)
                        else:
                            ax.add_patch(Rectangle((x-.12, 0), .24, .06, transform=ax.get_xaxis_transform(),
                                         facecolor='white', edgecolor=colors[i], hatch='xxxx'))
                    r = by[(arch, 'spad')]
                    ax.text(a, 1.03, r['completed_layers']+'/'+r['nominal_layers'], transform=ax.get_xaxis_transform(), ha='center', fontsize=6)
                ax.set_xticks(range(5), ARCHES, rotation=25, ha='right')
                ax.set_xlim(-.6, 4.6); ax.set_ylim(bottom=0); ax.set_ylabel(ylabel)
                if not any(r[metric] for r in by.values()):
                    ax.set_ylim(0, 1); ax.set_yticks([])
                    ax.text(.5, .5, 'No complete totals', transform=ax.transAxes, ha='center')
            fig.suptitle(capture+'\n'+title, fontsize=9)
            fig.legend(handles=legend, ncol=3, frameon=False, loc='upper center', bbox_to_anchor=(.5, .88))
            fig.text(.5, .01, 'Sample 0: n=1 per completed layer. No variance. Hatched markers = missing/infeasible/OOM.\n* Null characterization costs contribute zero; energy/EDP are lower bounds. EDP = (sum E)(sum T).', ha='center', fontsize=7)
            fig.tight_layout(rect=(0, .14, 1, .80)); pdf.savefig(fig, bbox_inches='tight')
            fig.savefig(out/(capture.replace('/', '__')+'.png'), dpi=300, bbox_inches='tight'); plt.close(fig)
    (out/'caption.txt').write_text(title+'. Sample 0 only (n=1 per completed layer, no variance). '
        'Latency and energy sum nominal model layers; EDP is their product. Coverage above groups counts '
        'completed/nominal layers, including six infeasible Prosperity schedules. Missing totals are blank, never partial bars. '
        'Null characterization remains an incomplete lower bound. Source: results.csv and whole_model.csv. '
        'Font: DejaVu Sans. Reproduce with plot.py --checkpoint this_directory.\n')
    print(json.dumps({'draft_pages': 8, 'subset': coverage['subset'], 'rows': coverage['result_rows']}), flush=True)


if __name__ == '__main__':
    main()
