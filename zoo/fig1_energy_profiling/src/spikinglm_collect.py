"""Collect spikinglm (LoAS) whole-model sample energies from priced_spikinglm.

Mirrors collect_energy.py for the spikinglm extension: 1920 baseline layer
rows + 480 ideal layer rows (256 KiB fill), 48 kept attention GEMMs per
whole-model group, 10 samples. The ideal rows take their runtime from the
whole_run_ideal_spikinglm blocking first-use replay (simulated, not a
bracket): leakage is rescaled from the baseline-duration pricing by
ideal_total_cycles / baseline_cycles, and the off-chip dynamic terms are
re-rounded to the replay's 32B packets / 64B DRAM bursts.

Run from the repo root (numpy only):
  conda run -n base python -B zoo/fig1_energy_profiling/src/spikinglm_collect.py
"""
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np

from collect_energy import ROOT, SEGMENTS, load, save, digest, write_csv

BARS = ('128k', '256k', '512k', '1m', 'ideal')
LAYERS = 48
CRITICAL = 2.2621571628540993  # t(9) 97.5th percentile; fixed ten-sample experiment


def term_price(row, key):
    term = row['breakdown'][key]
    if term['count'] == 0:
        raise ValueError(f'cannot infer unit price for zero-count term {key}')
    return term['E_dyn_nJ'] / term['count']


def main():
    table_sha = digest(ROOT / 'archx_config/energy_table_asap7_syn.json')
    paths = sorted((ROOT / 'outputs/priced_spikinglm').glob('*/*/*/sample_*/*/result.json'))
    if len(paths) != 1920 + 480:
        raise ValueError(f'expected 2400 priced rows, got {len(paths)}')
    groups = defaultdict(list)
    case_rows = []
    identities = set()
    for path in paths:
        row = load(path)
        if row['arch'] != 'loas':
            raise ValueError('unexpected arch')
        identity = (row['bar'], row['sample'], row['layer'])
        if identity in identities:
            raise ValueError('duplicate case')
        identities.add(identity)
        if row['energy_table_sha256'] != table_sha:
            raise ValueError('mixed table hashes')
        for key, term in row['breakdown'].items():
            if '.psum_sram.' in key or '.vmem_sram.' in key:
                if term['count'] != 0 or term['E_dyn_nJ'] != 0:
                    raise ValueError('unapproved state boundary')
        segment_energies = {s: row['segments'][s]['E_dyn_nJ'] + row['segments'][s]['E_leak_nJ']
                            for s in SEGMENTS}
        if not math.isclose(sum(segment_energies.values()), row['E_total_nJ'], rel_tol=1e-12):
            raise ValueError('segment total')
        total_cycles = row['total_cycles']
        t_s = row['T_s']
        if row['bar'] == 'ideal':
            rel = Path('loas/256k') / f'sample_{row["sample"]:03d}' / row['layer']
            replay_root = ROOT / 'outputs/whole_run_ideal_spikinglm/counts' / rel
            receipt = load(replay_root / 'receipt.json')
            uses = load(replay_root / 'first_uses.json')
            if receipt['baseline_cycles'] != total_cycles:
                raise ValueError('replay baseline differs from priced duration')
            scale = receipt['total_cycles'] / receipt['baseline_cycles']
            unique = uses['unique_words']
            payload = unique + uses['packet_padding_bytes']
            burst = payload + uses['energy_burst_padding_bytes']
            # re-round the three ideal override terms to the replay's transfers
            deltas = {'shared.ddr4.read': burst / 64 - unique / 64,
                      'shared.ddr4_io.byte': payload - unique,
                      'loas.l1_weight_spad.write':
                          (payload - unique) * 8 /
                          (unique * 8 / row['breakdown']['loas.l1_weight_spad.write']['count'])}
            for key, delta in deltas.items():
                extra = delta * term_price(row, key)
                seg = row['breakdown'][key]['segment']
                row['segments'][seg]['E_dyn_nJ'] += extra
            for s in SEGMENTS:
                row['segments'][s]['E_leak_nJ'] *= scale
            segment_energies = {s: row['segments'][s]['E_dyn_nJ'] + row['segments'][s]['E_leak_nJ']
                                for s in SEGMENTS}
            total_cycles = receipt['total_cycles']
            t_s = total_cycles / 500e6
        flat = {'arch': 'loas', 'benchmark': 'spikinglm', 'bar': row['bar'],
                'size': row['size'], 'sample': row['sample'], 'layer': row['layer'],
                'E_dyn_nJ': sum(row['segments'][s]['E_dyn_nJ'] for s in SEGMENTS),
                'E_leak_nJ': sum(row['segments'][s]['E_leak_nJ'] for s in SEGMENTS),
                'E_total_nJ': sum(segment_energies.values()),
                'T_s': t_s, 'total_cycles': total_cycles,
                **{s + '_nJ': segment_energies[s] for s in SEGMENTS},
                'table_sha256': table_sha}
        case_rows.append(flat)
        groups[(row['bar'], row['sample'])].append(flat)
    expected = {r['layer'] for r in
                load(ROOT / 'outputs/manifest_spikinglm/loas_256k/manifest.json')['layers']}
    whole = []
    for bar in BARS:
        for sample in range(10):
            rows = groups[(bar, sample)]
            if {r['layer'] for r in rows} != expected or len(rows) != LAYERS:
                raise ValueError(f'incomplete whole model: {bar} sample {sample}')
            whole.append({'arch': 'loas', 'benchmark': 'spikinglm', 'bar': bar,
                          'sample': sample, 'layers': LAYERS,
                          **{k: sum(r[k] for r in rows) for k in
                             ('E_dyn_nJ', 'E_leak_nJ', 'E_total_nJ', 'T_s',
                              *[s + '_nJ' for s in SEGMENTS])},
                          'table_sha256': table_sha})
    numbers = []
    baseline = np.array([r['E_total_nJ'] for r in whole if r['bar'] == '256k'])
    norm = float(baseline.mean())
    for bar in BARS:
        rows = [r for r in whole if r['bar'] == bar]
        for segment in (*SEGMENTS, 'total'):
            values = np.array([r['E_total_nJ' if segment == 'total' else segment + '_nJ']
                               for r in rows])
            mean = float(values.mean())
            ci = float(CRITICAL * values.std(ddof=1) / math.sqrt(10))
            numbers.append({'arch': 'loas', 'benchmark': 'spikinglm', 'bar': bar,
                            'segment': segment, 'n': 10, 'layers': LAYERS,
                            'mean_energy_nJ': mean, 'ci95_halfwidth_nJ': ci,
                            'normalizer_256k_mean_nJ': norm,
                            'normalized_mean': mean / norm,
                            'normalized_ci95_halfwidth': ci / norm,
                            'table_sha256': table_sha})
    write_csv(ROOT / 'outputs/spikinglm_layer_energy.csv', case_rows)
    write_csv(ROOT / 'outputs/spikinglm_whole_model_samples.csv', whole)
    write_csv(ROOT / 'outputs/spikinglm_fig1_numbers.csv', numbers)
    report = {'layer_rows': len(case_rows), 'whole_model_samples': len(whole),
              'bars': len(BARS), 'layers_per_model': LAYERS, 'samples_per_bar': 10,
              'table_sha256': table_sha,
              'ideal_semantics': 'blocking first-use replay (simulated total_cycles); '
                                 'leakage rescaled from baseline-duration pricing; off-chip '
                                 'dynamic re-rounded to 32B packets / 64B DRAM bursts',
              'confidence_interval': 'Student-t 95%, df=9, over ten whole-model sample '
                                     'energies; fixed normalization by the 256KiB mean',
              'all_groups_complete': True,
              'csv_sha256': {n: digest(ROOT / 'outputs' / n) for n in
                             ('spikinglm_layer_energy.csv', 'spikinglm_whole_model_samples.csv',
                              'spikinglm_fig1_numbers.csv')}}
    save(ROOT / 'outputs/spikinglm_energy_validation.json', report)
    print(json.dumps({k: report[k] for k in ('layer_rows', 'whole_model_samples',
                                             'all_groups_complete')}, indent=2))


if __name__ == '__main__':
    main()
