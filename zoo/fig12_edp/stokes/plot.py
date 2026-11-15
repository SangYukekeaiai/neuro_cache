"""Plot collected Stage 2 CSVs; never simulate, aggregate partial totals, or price.

python -B zoo/fig12_edp/stokes/plot.py --input STAGE2/whole_model.csv --out FIGURES
Reads sibling coverage.json. Main runs this only after Stage 1 drains and Stage 2
collection finishes. Outputs an eight-page PDF, eight page PNGs, model-EDP and
sum-layer-EDP overviews (PDF + 300-dpi PNG), and plot_manifest.json.
Use --nangate45-only with whole_model_ng45.csv for only the interim NanGate45
energy and model-EDP overviews (PDF + PNG); no other figures or manifests.
"""
import argparse
from collections import Counter
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import shlex
import sys

ARCHES = ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity')
ARMS = ('spad', 'cacheA', 'cacheB')
ARCH_LABELS = ('SpinalFlow', 'PTB', 'LoAS', 'GustavSNN', 'Prosperity')
METRICS = (('sum_latency_s', 'Latency (ms)', 1e3),
           ('sum_energy_nJ', 'Energy (mJ)*', 1e-6),
           ('model_EDP_nJ_s', 'Model EDP (mJ s)*', 1e-6),
           ('sum_layer_EDP_nJ_s', 'Sum layer EDP (mJ s)*', 1e-6))
WARNING = 'DUMMY PRICES — ENERGY / EDP PLACEHOLDERS'
CAVEAT = '* Every group remains energy-incomplete. Placeholder energy / EDP are NOT lower bounds.'
NG45_CAVEAT = ('NanGate45-characterized prices applied to a 7nm/500MHz performance model; '
               'interim until ASAP7 synthesis')
SCOPE = 'Sample 0, n=1 when any layer completes (otherwise n=0); no error bars. FC / FFN excluded; attention kept.'
NAMES = {
    'spikformer_4_384_cifar100_T4_n500': 'Spikformer / CIFAR100 / T4',
    'sdt_2_512_cifar100_T4_n500': 'SDT / CIFAR100 / T4',
    'spikinglm_t4_T4_n500': 'SpikingLM / T4',
    'vgg16_cifar10_loas_T32_n500': 'VGG16 / CIFAR10 / T32',
    'loas_vgg16_T4_n500': 'LoAS VGG16 / T4',
    'loas_resnet19_T4_n500': 'LoAS ResNet19 / T4',
    'sma_azo_vgg_cifar10_dvs_T10_n500': 'VGG / CIFAR10-DVS / T10',
    'sma_azo_vgg_dvs128_gesture_T16_n500': 'VGG / DVS128 Gesture / T16',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def boolean(value):
    require(value.lower() in ('true', 'false', '1', '0'), 'invalid boolean: '+value)
    return value.lower() in ('true', '1')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_inputs(path, latency_only=False, nangate45_only=False):
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    coverage = json.loads(path.with_name('coverage.json').read_text())
    if nangate45_only:
        require(not latency_only, 'NanGate45 and latency-only modes are mutually exclusive')
        require(coverage['pricing_profile'] == 'nangate45', 'expected nangate45 pricing profile')
        table_sha = coverage['energy_table_sha256']
        require(isinstance(table_sha, str) and len(table_sha) == 64 and
                all(c in '0123456789abcdef' for c in table_sha), 'invalid energy-table SHA256')
        require(coverage['pricing_caveat'] == NG45_CAVEAT, 'NanGate45 pricing caveat differs')
        for row in rows:
            require(not boolean(row['dummy_prices']), 'NanGate45 rows must not use dummy prices')
            require(boolean(row['energy_incomplete']), 'NanGate45 groups must remain energy-incomplete')
            row_sha = row['energy_table_sha256']
            require(row_sha == table_sha or (not int(row['completed_layers']) and row_sha == ''),
                    'CSV/coverage energy-table SHA256 differs')
    scope = coverage['scope']
    require((scope['kept_layers'], scope['kept_feasible_pairs'], scope['kept_infeasible_pairs'])
            == (113, 559, 6), 'expected 113 kept layers, 559 feasible + 6 infeasible pairs')
    states = coverage['case_states']
    require(len(states) == 559 and len(coverage['infeasible']) == 6, 'coverage scope differs')
    captures = sorted({r['benchmark'] for r in rows})
    by = {(r['benchmark'], r['arch'], r['arm']): r for r in rows}
    require(len(captures) == 8 and len(rows) == len(by) == 120 and
            set(by) == set(itertools.product(captures, ARCHES, ARMS)),
            'expected eight benchmarks x five architectures x three arms, without duplicates')
    groups = {}
    for key, state in states.items():
        arch, family, trace, layer = key.split('/')
        require(arch in ARCHES and family+'/'+trace in captures and isinstance(state, str),
                'unknown coverage identity/status: '+key)
        groups.setdefault((family+'/'+trace, arch), []).append(state)
    for capture, arch in itertools.product(captures, ARCHES):
        statuses = groups.get((capture, arch), [])
        completed = statuses.count('complete')
        infeasible = sum(c['arch'] == arch and c['trace_relative_dir'] == capture
                         for c in coverage['infeasible'])
        nominal = len(statuses)+infeasible
        for arm in ARMS:
            row = by[capture, arch, arm]
            require((int(row['completed_layers']), int(row['feasible_layers']),
                     int(row['infeasible_layers']), int(row['expected_layers'])) ==
                    (completed, len(statuses), infeasible, nominal), 'CSV/coverage mismatch')
            complete = completed == nominal
            require(boolean(row['coverage_complete']) == complete and
                    row['coverage'] == f'{completed}/{nominal}', 'coverage flags disagree')
            require(int(row['sample']) == 0 and int(row['n']) == int(completed > 0),
                    'expected sample 0, n=1 for nonempty groups')
            # Empty groups may carry False in the collector; they still have no characterized energy.
            if not latency_only:
                require(not completed or boolean(row['energy_incomplete']),
                        'dummy-price plot expects every populated group to be energy-incomplete')
            for metric, _, _ in (METRICS[:1] if latency_only else METRICS):
                value = row[metric]
                if complete:
                    require(value != '', 'complete group has no total: '+metric)
                    value = float(value)
                    require(math.isfinite(value) and value >= 0, 'invalid total: '+metric)
                    row[metric] = value
                else:
                    require(value == '', 'incomplete group must not expose a numeric total: '+metric)
                    row[metric] = None
            if complete and not latency_only:
                require(math.isclose(row['model_EDP_nJ_s'], row['sum_energy_nJ']*row['sum_latency_s'],
                                     rel_tol=1e-8, abs_tol=1e-12), 'model EDP must be product of sums')
    return captures, by, coverage


def configure_fonts(plt, font_manager):
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    text = next((f for f in ('Gill Sans', 'Gill Sans MT', 'Lato', 'Carlito', 'Cantarell')
                 if f in fonts), 'DejaVu Sans')
    digit = next((f for f in ('Lato', 'Carlito', 'DejaVu Sans') if f in fonts), 'DejaVu Sans')
    # Match numeric tick x-height to the chosen humanist text face, per fonts.md.
    from fontTools.ttLib import TTFont
    def xheight(name):
        with TTFont(font_manager.findfont(name), fontNumber=0) as font:
            height = getattr(font['OS/2'], 'sxHeight', 0)
            if not height:
                height = font['glyf'][font.getBestCmap()[ord('x')]].yMax
            return height/font['head'].unitsPerEm
    digit_pt = 8*xheight(text)/xheight(digit)
    plt.rcParams.update({'font.family': text, 'font.size': 8, 'pdf.fonttype': 42,
                         'mathtext.fontset': 'custom', 'mathtext.rm': digit,
                         'mathtext.it': digit, 'mathtext.bf': digit, 'mathtext.cal': digit,
                         'ytick.labelsize': digit_pt, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.dpi': 300})
    return {'text': text, 'digit': digit, 'text_pt': 8, 'digit_tick_pt': digit_pt,
            'fallback': not text.startswith('Gill Sans')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='whole_model.csv; sibling coverage.json')
    parser.add_argument('--out', type=Path, required=True, help='figure output directory')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--latency-only', action='store_true', help='render only the table-independent latency overview')
    mode.add_argument('--energy-only', action='store_true', help='render only the dummy-priced energy overview')
    mode.add_argument('--nangate45-only', action='store_true',
                      help='render only NanGate45 interim energy and model-EDP overviews')
    args = parser.parse_args()
    source, out = args.input.resolve(), args.out.resolve()
    captures, by, coverage = read_inputs(source, args.latency_only, args.nangate45_only)
    require(out != source.parent, 'use a separate figure directory, not the CSV directory')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Patch, Rectangle
    from matplotlib.ticker import StrMethodFormatter, NullFormatter
    fonts = configure_fonts(plt, font_manager)
    colors, hatches = ('#999999', '#0072B2', '#E69F00'), ('', '///', '..')
    legend = [Patch(facecolor=c, edgecolor='black', hatch=h, label=a)
              for a, c, h in zip(ARMS, colors, hatches)]
    legend.append(Patch(facecolor='white', edgecolor='black', hatch='xxxx', label='Missing layers: no total'))
    statuses = Counter(coverage['case_states'].values())
    unfinished = sum(v for k, v in statuses.items() if k in ('pending', 'running', 'queued', 'not_started'))
    failed = sum(v for k, v in statuses.items() if k not in ('complete', 'pending', 'running', 'queued', 'not_started'))
    oom = sum(v for k, v in statuses.items() if 'oom' in k.lower())
    dynamic = (f"113 layers; 559 feasible + 6 infeasible pairs. Complete {statuses['complete']}/559; "
               f'failed {failed} (OOM {oom}); pending/running {unfinished}.')
    outputs = []

    def title(capture):
        family, trace = capture.split('/')
        return family+' — '+NAMES.get(trace, trace)

    def panel(ax, capture, spec):
        metric, label, factor = spec
        values = [by[capture, arch, arm][metric] for arch in ARCHES for arm in ARMS]
        positive = [v*factor for v in values if v is not None and v > 0]
        log = 'EDP' in metric and bool(positive)
        if log:
            ax.set_yscale('log')
            ax.set_ylim(min(positive)/2.5, max(positive)*3)
        for a, arch in enumerate(ARCHES):
            for index, arm in enumerate(ARMS):
                value = by[capture, arch, arm][metric]
                position = a+(index-1)*.24
                if value is None:
                    ax.add_patch(Rectangle((position-.12, .01), .24, .055,
                                 transform=ax.get_xaxis_transform(), facecolor='white',
                                 edgecolor='black', hatch='xxxx', linewidth=.6, zorder=4))
                elif value == 0:
                    ax.text(position, .025, '$0$', transform=ax.get_xaxis_transform(),
                            ha='center', va='bottom', fontsize=fonts['digit_tick_pt'])
                else:
                    ax.bar(position, value*factor, .24, color=colors[index], hatch=hatches[index],
                           edgecolor='black', linewidth=.45)
                    if metric != 'sum_latency_s':
                        ax.annotate('*', (position, value*factor), xytext=(0, 2),
                                    textcoords='offset points', ha='center', fontsize=8)
        ax.set_xticks(range(5), [name+'\n'+by[capture, arch, 'spad']['coverage']
                                for arch, name in zip(ARCHES, ARCH_LABELS)], rotation=20, ha='right')
        ax.set_xlim(-.6, 4.6)
        ax.set_ylabel(label+(' [log]' if log else ''))
        if not log:
            ax.set_ylim(bottom=0)
            ax.margins(y=.18)
        if not positive:
            ax.set_ylim(0, 1); ax.set_yticks([])
            message = 'No complete model totals' if all(v is None for v in values) else 'Complete totals are zero'
            ax.text(.5, .55, message, transform=ax.transAxes, ha='center', fontsize=8)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.tick_params(axis='x', labelsize=7)

    def decorate(fig, heading, detail):
        fig.suptitle(WARNING+'\n'+heading, y=.985, fontsize=11, fontweight='bold', color='#8B1A1A')
        fig.legend(handles=legend, ncol=4, loc='upper center', bbox_to_anchor=(.5, .91), frameon=False)
        fig.text(.5, .096, CAVEAT, ha='center', fontsize=8, fontweight='bold', color='#8B1A1A')
        fig.text(.5, .065, SCOPE+'\n'+dynamic+'\n'+detail, ha='center', va='top', fontsize=7)

    def save(fig, name, pdf=True):
        if pdf:
            fig.savefig(out/(name+'.pdf'), bbox_inches='tight'); outputs.append(name+'.pdf')
        fig.savefig(out/(name+'.png'), dpi=300, bbox_inches='tight'); outputs.append(name+'.png')
        plt.close(fig)

    out.mkdir(parents=True, exist_ok=True)
    if args.nangate45_only:
        table_sha = coverage['energy_table_sha256']
        complete_groups = sum(r['sum_energy_nJ'] is not None for r in by.values())
        missing_groups = len(by)-complete_groups
        for metric, name, heading, formula in (
            (METRICS[1], 'model_energy_overview_ng45', 'Whole-model energy',
             'Energy = sum of layer (dynamic + leakage energy), in mJ; linear axes.'),
            (METRICS[2], 'model_edp_overview_ng45', 'Whole-model EDP',
             'Model EDP = (sum E) x (sum T), in mJ s; log axes where positive; zeros marked at axis.')):
            fig, axes = plt.subplots(4, 2, figsize=(10.5, 11.5))
            for ax, capture in zip(axes.flat, captures):
                panel(ax, capture, metric); ax.set_title(title(capture), fontsize=9, pad=9)
            fig.suptitle('NanGate45 INTERIM\n'+heading+' across eight benchmarks',
                         y=.985, fontsize=11, fontweight='bold', color='#164B69')
            fig.legend(handles=legend, ncol=4, loc='upper center',
                       bbox_to_anchor=(.5, .94), frameon=False)
            fig.text(.5, .135, NG45_CAVEAT, ha='center', va='top', fontsize=8,
                     fontweight='bold', color='#164B69')
            fig.text(.5, .112, 'Energy table SHA256: '+table_sha, ha='center', va='top', fontsize=7)
            caption = ('* All groups remain energy-incomplete. Complete totals: '+str(complete_groups)
                       +'/'+str(len(by))+'; hatched: '+str(missing_groups)+'. No partial bars.\n'
                       +formula+'\n'+SCOPE+'\n'+dynamic
                       +'\nCoverage labels = completed/nominal kept layers; sequential layer execution assumed.')
            fig.text(.5, .093, caption, ha='center', va='top', fontsize=7)
            fig.tight_layout(rect=(0, .18, 1, .91), h_pad=2.4, w_pad=2.5)
            save(fig, name)
        print(json.dumps({'pricing_profile': 'nangate45', 'energy_table_sha256': table_sha,
                          'pricing_caveat': NG45_CAVEAT, 'dummy_prices': False,
                          'complete_groups': complete_groups, 'hatched_groups': missing_groups,
                          'fonts': fonts, 'outputs': {name: digest(out/name) for name in outputs}}))
        return
    if args.latency_only or args.energy_only:
        metric = METRICS[0] if args.latency_only else METRICS[1]
        name = 'model_latency_overview' if args.latency_only else 'model_energy_overview'
        if args.latency_only:
            heading = 'Whole-model latency across eight benchmarks'
            caption = ('Whole-model latency = sum of layer T = sum of simulated cycles / 500 MHz, assuming sequential layers.\n'
                       'Count-derived and independent of the energy table. Coverage = completed/nominal layers; hatches show no total.')
        else:
            heading = WARNING+'\nWhole-model energy across eight benchmarks'
            caption = ('Whole-model energy = sum of layer (dynamic + leakage energy), shown in mJ.\n'
                       +CAVEAT+'\nDummy table SHA256: '+coverage['dummy_table_sha256'])
        fig, axes = plt.subplots(4, 2, figsize=(10.5, 11.5))
        for ax, capture in zip(axes.flat, captures):
            panel(ax, capture, metric); ax.set_title(title(capture), fontsize=9, pad=9)
        fig.suptitle(heading, y=.985, fontsize=11, fontweight='bold',
                     color='black' if args.latency_only else '#8B1A1A')
        fig.legend(handles=legend, ncol=4, loc='upper center', bbox_to_anchor=(.5, .94), frameon=False)
        fig.text(.5, .10, caption, ha='center', va='top', fontsize=8)
        fig.text(.5, .05, SCOPE+'\n'+dynamic, ha='center', va='top', fontsize=7)
        fig.tight_layout(rect=(0, .14, 1, .91), h_pad=2.4, w_pad=2.5)
        save(fig, name)
        plotted = [{'benchmark': c, 'arch': a, 'arm': arm,
                    metric[0]: by[c, a, arm][metric[0]],
                    'coverage': by[c, a, arm]['coverage']} for c, a, arm in sorted(by)]
        manifest = {'metric': metric[0], 'units': 'ms' if args.latency_only else 'mJ', 'frequency_MHz': 500,
                    'energy_table_read': False, 'energy_table_independent': args.latency_only,
                    'caption': caption, 'sample_scope': SCOPE,
                    'coverage_caption': dynamic, 'group_count': len(by),
                    'complete_groups': sum(r[metric[0]] is not None for r in plotted),
                    'hatched_groups': sum(r[metric[0]] is None for r in plotted),
                    'source_csv': {'path': str(source), 'sha256': digest(source)},
                    'coverage_sha256': digest(source.with_name('coverage.json')),
                    ('latency_data_sha256' if args.latency_only else 'energy_data_sha256'):
                        hashlib.sha256(json.dumps(plotted, sort_keys=True).encode()).hexdigest(),
                    'script_sha256': digest(Path(__file__)), 'fonts': fonts,
                    'outputs': {name: digest(out/name) for name in outputs},
                    'reproduce': shlex.join([sys.executable, '-B', str(Path(__file__).resolve()),
                                            '--input', str(source), '--out', str(out),
                                            '--latency-only' if args.latency_only else '--energy-only'])}
        if args.energy_only:
            manifest.update(dummy_prices=True, dummy_table_sha256=coverage['dummy_table_sha256'],
                            missing_groups='Coverage labels are completed/nominal layers; hatches show no total, never partial sums.')
        (out/(name+'.provenance.json')).write_text(json.dumps(manifest, indent=2)+'\n')
        print(json.dumps({'complete_groups': manifest['complete_groups'],
                          'hatched_groups': manifest['hatched_groups'], 'outputs': outputs}))
        return
    page_detail = 'Coverage labels = completed/nominal layers. Hatching = unavailable total, never a partial sum. Model EDP = (sum E) x (sum T).'
    with PdfPages(out/'whole_model.pdf') as pdf:
        for capture in captures:
            fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.8))
            for i, (ax, spec) in enumerate(zip(axes, METRICS[:3])):
                panel(ax, capture, spec); ax.set_title('('+chr(97+i)+')', loc='left', fontsize=9)
            decorate(fig, title(capture), page_detail)
            fig.tight_layout(rect=(0, .19, 1, .85), w_pad=2)
            pdf.savefig(fig, bbox_inches='tight')
            save(fig, 'whole_model_'+capture.replace('/', '__'), pdf=False)
    outputs.append('whole_model.pdf')
    overview_details = {}
    for metric, name, heading, detail in (
        (METRICS[2], 'model_edp_overview', 'Eight-benchmark model EDP', 'Model EDP = (sum E) x (sum T), assuming sequential layers.'),
        (METRICS[3], 'sum_layer_edp', 'Separate sum of layer EDP', 'Sum(E_layer x T_layer) is a composition statistic, NOT model EDP.')):
        fig, axes = plt.subplots(4, 2, figsize=(10.5, 11.5))
        for ax, capture in zip(axes.flat, captures):
            panel(ax, capture, metric); ax.set_title(title(capture), fontsize=9, pad=9)
        detail += ' Log axes where positive totals exist; zeros marked at the axis. Hatched groups have no total.'
        overview_details[name] = detail
        decorate(fig, heading, detail)
        fig.tight_layout(rect=(0, .14, 1, .88), h_pad=2.4, w_pad=2.5)
        save(fig, name)
    manifest = {'warning': WARNING, 'energy_caveat': CAVEAT, 'all_groups_energy_incomplete': True,
                'sample_scope': SCOPE, 'coverage_caption': dynamic, 'case_states': dict(statuses),
                'group_count': len(by), 'benchmarks': captures, 'fonts': fonts,
                'source_csv': {'path': str(source), 'sha256': digest(source)},
                'coverage_json': {'path': str(source.with_name('coverage.json')),
                                  'sha256': digest(source.with_name('coverage.json'))},
                'script_sha256': digest(Path(__file__)), 'outputs': outputs,
                'captions': {'whole_model': page_detail, **overview_details},
                'reproduce': shlex.join([sys.executable, '-B', str(Path(__file__).resolve()),
                                        '--input', str(source), '--out', str(out)]),
                'source_to_exhibit': 'whole_model.csv + coverage.json -> whole_model.pdf (eight pages), per-page PNGs, model_edp_overview and sum_layer_edp PDF/PNG',
                'limitations': 'Dummy-price visualization only, not characterized energy or priced equivalence. No partial bars, uncertainty estimates, significance claims or cross-group ratios.'}
    (out/'plot_manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'pages': 8, 'groups': len(by), 'font': fonts, 'out': str(out)}))


if __name__ == '__main__':
    main()
