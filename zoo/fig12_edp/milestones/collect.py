"""Read committed Stage-B products; freeze and summarize the first 100 full samples."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np

TABLE_SHA = '2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3'
TARGET = 100
ARMS = ('spad', 'cacheA', 'cacheB')
CASE_METRICS = ('T_s', 'E_dyn_nJ', 'E_leak_nJ', 'energy_nJ', 'EDP_nJ_s', 'total_cycles')
MODEL_METRICS = ('sum_latency_s', 'sum_energy_nJ', 'model_EDP_nJ_s', 'sum_layer_EDP_nJ_s')
CAVEAT = ('NanGate45-characterized prices applied to a 7nm/500MHz performance model; '
          'interim until ASAP7 synthesis')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.part')
    with tmp.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_csv(path):
    csv.field_size_limit(sys.maxsize)
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    require(bool(rows), 'empty statistics')
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def same(actual, expected, label):
    require(math.isfinite(actual) and actual >= 0, 'invalid numeric value: ' + label)
    require(actual == 0 if expected == 0 else math.isclose(actual, expected, rel_tol=1e-9, abs_tol=0),
            'arithmetic mismatch: ' + label)


def verify_commit(folder, entry):
    require(digest(folder / 'commit.json') == entry['commit_sha256'], 'commit changed')
    commit = load(folder / 'commit.json')
    require(commit['sample'] == entry['sample'] and commit['rows'] == 1677,
            'only full 559-case commits count toward 100')
    require(commit['table_sha256'] == TABLE_SHA, 'wrong table')
    required = {'results_ng45.csv', 'whole_model_ng45.csv', 'coverage.json',
                'immutability.json', 'counts_before.json', 'counts_after.json', 'accounting.json'}
    require(required <= set(commit['artifacts']), 'missing durable artifacts')
    for name, sha in commit['artifacts'].items():
        require(Path(name).name == name and name not in ('.', '..'), 'unsafe artifact name')
        require(digest(folder / name) == sha, 'artifact changed: ' + name)
    immutable = load(folder / 'immutability.json')
    require(immutable['unchanged'] is True and immutable['files'] > 0 and
            immutable['before_sha256'] == immutable['after_sha256'] ==
            commit['artifacts']['counts_before.json'] == commit['artifacts']['counts_after.json'],
            'Stage-A immutability mismatch')
    return commit


def read_sample(folder, sample):
    coverage = load(folder / 'coverage.json')
    require(coverage['report_complete'] is True and coverage['completed_cases'] == 559 and
            coverage['failed_cases'] == 0 and not coverage['errors'], 'partial sample')
    require(coverage['energy_table_sha256'] == TABLE_SHA and coverage['pricing_profile'] == 'nangate45',
            'coverage table/profile mismatch')
    require(tuple(coverage['scope'][k] for k in
                  ('kept_layers', 'kept_feasible_pairs', 'kept_infeasible_pairs')) == (113, 559, 6),
            'wrong workload scope')
    states = coverage['case_states']
    require(len(states) == 559 and set(states.values()) == {'complete'} and
            len(coverage['infeasible']) == 6, 'unfinished case or wrong infeasible set')
    expected = set()
    for key in states:
        arch, family, capture, layer = key.split('/')
        expected.update((arch, family + '/' + capture, layer, arm) for arm in ARMS)
    rows = read_csv(folder / 'results_ng45.csv')
    cases, groups = {}, defaultdict(list)
    for row in rows:
        key = tuple(row[k] for k in ('arch', 'capture', 'layer', 'arm'))
        require(key not in cases, 'duplicate case row')
        require(int(row['sample']) == sample and row['energy_table_sha256'] == TABLE_SHA,
                'row sample/table mismatch')
        require(row['pricing_status'] == 'NG45_INTERIM' and row['dummy_prices'].lower() == 'false',
                'incorrect price label')
        values = {k: float(row[k]) for k in CASE_METRICS if k != 'energy_nJ'}
        values['energy_nJ'] = values['E_dyn_nJ'] + values['E_leak_nJ']
        require(all(math.isfinite(v) and v >= 0 for v in values.values()), 'invalid case value')
        same(values['T_s'], values['total_cycles'] / 500e6, 'latency')
        same(values['EDP_nJ_s'], values['energy_nJ'] * values['T_s'], 'case EDP')
        cases[key] = values
        groups[row['capture'], row['arch'], row['arm']].append(values)
    require(len(rows) == 1677 and set(cases) == expected, 'case coverage mismatch')
    models = {}
    for row in read_csv(folder / 'whole_model_ng45.csv'):
        key = tuple(row[k] for k in ('benchmark', 'arch', 'arm'))
        require(key not in models and key in groups, 'duplicate/unknown whole-model group')
        values = groups[key]
        infeasible = sum(c['arch'] == key[1] and c['trace_relative_dir'] == key[0]
                         for c in coverage['infeasible'])
        complete = infeasible == 0
        expected_layers = len(values) + infeasible
        require(int(row['completed_layers']) == len(values) and
                int(row['expected_layers']) == expected_layers and
                int(row['infeasible_layers']) == infeasible and
                (row['coverage_complete'].lower() == 'true') == complete,
                'whole-model completeness mismatch')
        energy = math.fsum(v['energy_nJ'] for v in values)
        latency = math.fsum(v['T_s'] for v in values)
        totals = dict(zip(MODEL_METRICS, (latency, energy, energy * latency,
                                        math.fsum(v['EDP_nJ_s'] for v in values))))
        for metric, value in totals.items():
            if complete:
                same(float(row[metric]), value, metric)
            else:
                require(row[metric] == '', 'partial whole-model bar')
        models[key] = {'completed_layers': len(values), 'expected_layers': expected_layers,
                       'infeasible_layers': infeasible, 'coverage_complete': complete,
                       **{k: v if complete else None for k, v in totals.items()}}
    require(len(models) == len(groups) == 120 and
            sum(m['coverage_complete'] for m in models.values()) == 117,
            'expected 117 complete groups and three infeasible hatches')
    return rows, cases, models, coverage['scope']['sha256']


def select_entries(entries, target=TARGET):
    full = [e for e in entries if e['rows'] == 1677]
    require(len({e['sample'] for e in full}) == len(full), 'duplicate sample across fronts')
    require(all(0 <= e['sample'] < 500 and math.isfinite(e['committed_unix']) for e in full),
            'invalid sample identity/time')
    return sorted(full, key=lambda e: (e['committed_unix'], e['sample'], e['front']))[:target]


def freeze(path, entries):
    chosen = select_entries(entries)
    require(len(chosen) == TARGET, '100 complete samples not yet available')
    document = {'samples': chosen, 'target': TARGET, 'energy_table_sha256': TABLE_SHA,
                'selection': 'first 100 full commits ordered by committed_unix, sample, front',
                'frozen_unix': time.time(), 'quarantined_partials_included': False}
    if path.exists():
        old = load(path)
        require(old['samples'] == chosen, 'frozen cohort cannot change')
        return old
    save(path, document)
    return document


def bootstrap_weights(n, repetitions=2000, seed=100):
    require(n >= 2, 'CI requires at least two samples')
    return np.random.default_rng(seed).multinomial(n, np.full(n, 1 / n), size=repetitions) / n


def summarize(keys, matrices, weights, key_names, metadata=None):
    """Same sample resampling weights for every metric, architecture, arm and layer."""
    result = [dict(zip(key_names, key)) for key in keys]
    for index, row in enumerate(result):
        row.update(n=weights.shape[1], energy_table_sha256=TABLE_SHA,
                   pricing_status='NG45_INTERIM', energy_incomplete=True)
        if metadata:
            row.update(metadata[keys[index]])
            row['n_complete_samples'] = weights.shape[1] if row['coverage_complete'] else 0
    for metric, values in matrices.items():
        values = np.asarray(values, dtype=float)
        valid = np.isfinite(values).all(axis=0)
        require(np.all(valid | np.isnan(values).all(axis=0)), 'missing samples within a group')
        means = values[:, valid].mean(axis=0)
        low, high = np.quantile(weights @ values[:, valid], [0.025, 0.975], axis=0)
        j = 0
        for i, row in enumerate(result):
            for suffix in ('mean', 'ci95_low', 'ci95_high'):
                row[metric + '_' + suffix] = None
            if valid[i]:
                row.update({metric + '_mean': float(means[j]), metric + '_ci95_low': float(low[j]),
                            metric + '_ci95_high': float(high[j])})
                j += 1
    return result


def collect(snapshot, out):
    cohort = load(snapshot)
    entries = cohort['samples']
    require(len(entries) == TARGET and len({e['sample'] for e in entries}) == TARGET,
            'milestone requires 100 distinct samples')
    require(cohort['energy_table_sha256'] == TABLE_SHA, 'snapshot table mismatch')
    out.mkdir(parents=True, exist_ok=True)
    case_matrices = {k: [] for k in CASE_METRICS}
    model_matrices = {k: [] for k in MODEL_METRICS}
    case_keys = model_keys = fields = scope_sha = metadata = None
    raw_path = out / 'results_partial100.csv'
    with raw_path.open('w', newline='') as stream:
        for entry in entries:
            folder = Path(entry['mirror'])
            verify_commit(folder, entry)
            rows, cases, models, scope = read_sample(folder, entry['sample'])
            if case_keys is None:
                case_keys, model_keys, fields, scope_sha = sorted(cases), sorted(models), list(rows[0]), scope
                metadata = {k: {field: models[k][field] for field in
                            ('completed_layers', 'expected_layers', 'infeasible_layers', 'coverage_complete')}
                            for k in model_keys}
                writer = csv.DictWriter(stream, fieldnames=fields + ['front', 'source_commit_sha256'])
                writer.writeheader()
            require(sorted(cases) == case_keys and sorted(models) == model_keys and scope == scope_sha,
                    'samples have different workload coverage')
            require(list(rows[0]) == fields, 'result schema differs between fronts')
            require(all(all(models[k][f] == v for f, v in metadata[k].items()) for k in model_keys),
                    'sample completeness differs')
            for row in rows:
                writer.writerow({**row, 'front': entry['front'], 'source_commit_sha256': entry['commit_sha256']})
            for metric in CASE_METRICS:
                case_matrices[metric].append([cases[k][metric] for k in case_keys])
            for metric in MODEL_METRICS:
                model_matrices[metric].append([models[k][metric] for k in model_keys])
    weights = bootstrap_weights(TARGET)
    write_csv(out / 'case_statistics_partial100.csv', summarize(
        case_keys, case_matrices, weights, ('arch', 'capture', 'layer', 'arm')))
    write_csv(out / 'whole_model_partial100.csv', summarize(
        model_keys, model_matrices, weights, ('benchmark', 'arch', 'arm'), metadata))
    save(out / 'collection.json', {
        'snapshot_sha256': digest(snapshot), 'energy_table_sha256': TABLE_SHA,
        'analysis_sources': {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
        'scope_sha256': scope_sha, 'samples': TARGET, 'result_rows': len(entries) * len(case_keys),
        'case_groups': len(case_keys), 'whole_model_groups': len(model_keys),
        'complete_groups': sum(v['coverage_complete'] for v in metadata.values()),
        'statistics': 'mean and paired sample bootstrap percentile 95% CI; 2000 resamples, seed 100',
        'edp': 'sum layer energy times sum layer latency within each sample, then mean/CI across samples',
        'selection_caveat': 'Completion-selected interim cohort; excludes quarantined partial samples. '
                            'CIs measure sample variation, not energy-model uncertainty or completion-selection bias.',
        'pricing_caveat': CAVEAT, 'stage_a_accessed': False, 'repriced': False,
        'artifacts': {p.name: digest(p) for p in out.glob('*.csv')}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    collect(args.snapshot, args.out)
