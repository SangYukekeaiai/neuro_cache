"""Render the frozen milestone CSV means and sample CIs; never price or simulate."""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FuncFormatter

from collect import CAVEAT, TABLE_SHA, TARGET, digest, load, require, save
# Import the campaign's existing font and label helpers without its sample-0 reader.
import importlib.util
spec = importlib.util.spec_from_file_location('campaign_plot', Path(__file__).parents[1] / 'stokes/plot.py')
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def render(root):
    report = load(root / 'collection.json')
    require(report['samples'] == TARGET and report['energy_table_sha256'] == TABLE_SHA,
            'expected frozen 100-sample NG45 statistics')
    path = root / 'whole_model_partial100.csv'
    require(digest(path) == report['artifacts'][path.name], 'statistics changed')
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    by = {(r['benchmark'], r['arch'], r['arm']): r for r in rows}
    captures = sorted({k[0] for k in by})
    require(len(by) == len(rows) == 120 and len(captures) == 8, 'wrong figure coverage')
    fonts = campaign.configure_fonts(plt, font_manager)
    out = root / 'figures'
    out.mkdir(exist_ok=True)
    colors = ('#999999', '#0072B2', '#E69F00')
    hatches = ('', '///', '..')
    captions = {}
    for name, metric, label, scale in (
        ('latency', 'sum_latency_s', 'Whole-model latency (ms)', 1e3),
        ('energy', 'sum_energy_nJ', 'Whole-model energy (mJ)', 1e-6),
        ('edp', 'model_EDP_nJ_s', 'Whole-model EDP (mJ s; log scale)', 1e-6)):
        fig, axes = plt.subplots(4, 2, figsize=(10, 11))
        for ax, capture in zip(axes.flat, captures):
            for a, arm in enumerate(campaign.ARMS):
                for i, arch in enumerate(campaign.ARCHES):
                    row = by[capture, arch, arm]
                    require(int(row['n']) == TARGET, 'wrong sample count')
                    x = i + (a - 1) * .24
                    if row['coverage_complete'].lower() != 'true':
                        require(all(row[metric + suffix] == '' for suffix in
                                    ('_mean', '_ci95_low', '_ci95_high')), 'partial bar')
                        ax.add_patch(Rectangle((x - .11, .01), .22, .10,
                                               transform=ax.get_xaxis_transform(), facecolor='white',
                                               edgecolor=colors[a], hatch='xxxx', linewidth=.8))
                        if a == 1:
                            ax.text(i, .13, f"{row['completed_layers']}/{row['expected_layers']}\ninfeasible",
                                    transform=ax.get_xaxis_transform(), ha='center', fontsize=7)
                        continue
                    mean, lo, hi = [float(row[metric + s]) * scale for s in ('_mean', '_ci95_low', '_ci95_high')]
                    require(0 <= lo <= hi and mean >= 0, 'invalid interval')
                    ax.bar(x, mean, .22, color=colors[a], hatch=hatches[a], edgecolor='black', linewidth=.4)
                    # Draw interval endpoints directly: percentile CIs need not contain the point estimate.
                    ax.vlines(x, lo, hi, color='black', linewidth=.7)
                    ax.hlines([lo, hi], x - .035, x + .035, color='black', linewidth=.7)
            ax.set_title(campaign.NAMES.get(capture.split('/')[-1], capture), fontsize=9)
            ax.set_xticks(range(5), campaign.ARCH_LABELS, rotation=15, ha='right', fontsize=8)
            if name == 'edp':
                ax.set_yscale('log')
            else:
                ax.set_ylim(bottom=0)
                ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: '$' + f'{value:g}' + '$'))
            ax.set_ylabel(label, fontsize=8)
            ax.grid(axis='y', alpha=.2)
            ax.set_axisbelow(True)
        caption = (f'First {TARGET} fully committed samples (completion-selected preview); quarantined partial samples excluded. '
                   'Bars: mean of per-sample whole-model totals. Whiskers: paired-sample bootstrap percentile 95% CI '
                   f'(2,000 resamples, seed 100); n={TARGET}. CNN/GEMM kept scope. Hatches: incomplete nominal layer coverage; no partial bars. '
                   'CIs quantify sample variation, not selection bias or model uncertainty.')
        if name == 'latency':
            caption += ' Latency = sum(layer cycles)/500 MHz; independent of the energy table.'
        else:
            caption += ' ' + CAVEAT + '.\nTable SHA256: ' + TABLE_SHA
        if name == 'edp':
            caption += '\nEDP computed as (sum layer energy) x (sum layer latency) within each sample, then averaged.'
        import textwrap
        caption_lines = '\n'.join(textwrap.fill(line, 145) for line in caption.split('\n'))
        fig.suptitle(f'{TARGET}-sample preview — ' + ('count-derived latency' if name == 'latency' else 'NanGate45 INTERIM ' + name.upper()), fontsize=13)
        fig.legend(handles=[Patch(facecolor=c, edgecolor='black', hatch=h, label=a)
                           for c, h, a in zip(colors, hatches, campaign.ARMS)],
                   loc='upper center', bbox_to_anchor=(.5, .972), ncol=3)
        fig.text(.04, .01, caption_lines, fontsize=7, va='bottom')
        fig.tight_layout(rect=(0, .15 if name != 'latency' else .12, 1, .94))
        for ext in ('pdf', 'png'):
            fig.savefig(out / f'model_{name}_overview_partial100.{ext}', dpi=300, bbox_inches='tight')
        plt.close(fig)
        captions[name] = caption
    save(out / 'plot_manifest.json', {'fonts': fonts, 'captions': captions,
        'input_sha256': digest(path), 'sample_count': TARGET,
        'artifacts': {p.name: digest(p) for p in sorted(out.glob('*')) if p.suffix in ('.pdf', '.png')}})
    (out / 'caption.txt').write_text('\n\n'.join(f'{k}: {v}' for k, v in captions.items()) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    render(parser.parse_args().input)
