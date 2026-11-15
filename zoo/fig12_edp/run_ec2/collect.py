"""Sample checkpoints with explicit coverage; CSV serialization matches the demo."""
import csv
import json
import os
from pathlib import Path

from config import ARMS, ARCHES, folder, key, save, sync_dir
from pipeline import validate_result


def write_csv(path, rows):
    fields = sorted({k for r in rows for k in r}) or ['arch', 'capture', 'layer', 'sample', 'arm']
    temporary = path.with_suffix('.csv.part')
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path); sync_dir(path.parent)


def collect_sample(cfg, selection, sample, fingerprints):
    out = Path(cfg['output'])/('demo' if sample == 0 else f'samples/sample_{sample:05d}')
    out.mkdir(parents=True, exist_ok=True)
    rows, states = [], {}
    from config import key
    for case in selection['cases']:
        location = folder(cfg, case, sample)
        if (location/'result.json').exists():
            rows.extend(validate_result(location/'result.json', fingerprints[key(case)])['rows'])
            states[key(case)] = 'complete'
        elif (location/'failure.json').exists():
            states[key(case)] = json.loads((location/'failure.json').read_text())['status']
        else:
            states[key(case)] = 'pending'
    nominal = json.loads(Path(cfg['manifest']).read_text())['schedules']
    write_summary(out, nominal, selection, sample, rows, states)
    return out


def write_summary(out, nominal, selection, sample, rows, states):
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out/'results.csv', rows)
    totals = []
    for capture in selection['captures']:
        for arch in ARCHES:
            expected = sum(c['arch'] == arch and c['trace_relative_dir'] == capture for c in nominal)
            infeasible = sum(c['arch'] == arch and c['trace_relative_dir'] == capture for c in selection['infeasible'])
            for arm in ARMS:
                group = [r for r in rows if (r['capture'], r['arch'], r['arm']) == (capture, arch, arm)]
                complete = len(group) == expected
                energy = sum(r['E_dyn_nJ']+r['E_leak_nJ'] for r in group)
                latency = sum(r['T_s'] for r in group)
                totals.append({'capture': capture, 'arch': arch, 'arm': arm, 'sample': sample,
                    'completed_layers': len(group), 'nominal_layers': expected, 'infeasible_layers': infeasible,
                    'missing_layers': expected-len(group),
                    'oom_layers': sum(states.get(key(c)) == 'skipped_oom' for c in nominal
                                      if c['arch'] == arch and c['trace_relative_dir'] == capture),
                    'failed_layers': sum(states.get(key(c)) in ('failed', 'timeout', 'skipped_budget') for c in nominal
                                         if c['arch'] == arch and c['trace_relative_dir'] == capture),
                    'coverage_complete': complete, 'energy_incomplete': any(r['incomplete'] for r in group),
                    'sum_energy_nJ': energy if complete else None, 'sum_latency_s': latency if complete else None,
                    'model_EDP_nJ_s': energy*latency if complete else None,
                    'sum_layer_EDP_nJ_s': sum(r['EDP_nJ_s'] for r in group) if complete else None,
                    'partial_sum_energy_nJ': energy if group else None, 'partial_sum_latency_s': latency if group else None})
    write_csv(out/'whole_model.csv', totals)
    save(out/'coverage.json', {'sample': sample, 'states': states, 'subset': selection['subset'],
                              'selected_pairs': len(selection['cases']), 'nominal_feasible_pairs': 749,
                              'infeasible_pairs': 6, 'result_rows': len(rows),
                              'full_sample_complete': len(rows) == 749*3 and not selection['subset']})
