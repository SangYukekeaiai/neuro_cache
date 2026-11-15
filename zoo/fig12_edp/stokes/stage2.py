"""Price immutable Stage-A checkpoints and collect labeled pricing profiles."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ARMS = ('spad', 'cacheA', 'cacheB')
DUMMY_CAVEAT = 'DUMMY PRICES: illustrative values, not characterized hardware energy; n=1.'
NG45_CAVEAT = 'NanGate45-characterized prices applied to a 7nm/500MHz performance model; interim until ASAP7 synthesis'
PRICING_PROFILES = ('dummy', 'nangate45')
THREAD_ENV = dict.fromkeys(('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'RAYON_NUM_THREADS', 'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
    'NUMEXPR_MAX_THREADS', 'POLARS_MAX_THREADS', 'TBB_NUM_THREADS', 'GOTO_NUM_THREADS'), '1')


def profile_fields(profile, table_sha):
    if profile not in PRICING_PROFILES:
        raise ValueError('unknown pricing profile: '+profile)
    dummy = profile == 'dummy'
    fields = {'pricing_profile': profile, 'energy_table_sha256': table_sha,
              'pricing_status': 'DUMMY' if dummy else 'NG45_INTERIM',
              'pricing_caveat': DUMMY_CAVEAT if dummy else NG45_CAVEAT,
              'dummy_prices': dummy}
    if dummy:
        fields['dummy_table_sha256'] = table_sha
    else:
        fields.update(incomplete=True, approximation=True,
                      approximation_reason='mixed_technology_and_neighbor_technology_proxy')
    return fields


def check_ng45_table(table):
    model = REPO/'zoo/archx/zoo/snn_edp'
    baseline = load(model/'energy_table.json')
    policy = load(model/'characterization/pricing_policy.json')
    excluded = set(policy['excluded_operations'])
    ddr = {'shared.ddr4.read', 'shared.ddr4_io.byte'}
    metrics = ('dynamic_energy_nJ', 'leakage_power_mW', 'area_mm2')
    if len(table) != 98 or set(table) != set(baseline) or len(excluded) != 9:
        raise ValueError('NG45 requires the 98-operation table and nine exclusions')
    for name, row in table.items():
        if not isinstance(row, dict) or row.get('placeholder') is not False or row.get('dummy'):
            raise ValueError('NG45 placeholder/dummy row: '+name)
        for metric in metrics:
            value = row.get(metric)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('NG45 requires finite nonnegative metrics: '+name+'.'+metric)
        if name in excluded:
            if row.get('pricing_status') != policy['marker'] or any(row[m] != 0 for m in metrics):
                raise ValueError('NG45 excluded row must retain its marker and zero metrics: '+name)
        elif name in ddr:
            if row != baseline[name]:
                raise ValueError('NG45 DDR row differs from baseline: '+name)
        else:
            if row.get('pricing_status') != 'NG45_INTERIM' or row.get('characterization_technology_nm') != 45:
                raise ValueError('NG45 requires 45nm characterization provenance: '+name)
            if not isinstance(row.get('price_basis'), dict) or not row['price_basis']:
                raise ValueError('NG45 requires structured price_basis: '+name)
            if not isinstance(row.get('assumption'), str) or NG45_CAVEAT not in row['assumption']:
                raise ValueError('NG45 missing exact interim caveat: '+name)


def check_output_profile(output, profile):
    # Keep both completed and partially collected T97 outputs untouched.
    for parent in (output, *output.parents):
        receipt = parent/'coverage.json'
        if receipt.exists():
            saved = load(receipt)
            if 'dummy_prices' in saved and saved.get('pricing_profile', 'dummy') != profile:
                raise ValueError('pricing profile requires a separate output root')
    if profile == 'nangate45' and output.exists() and any(output.iterdir()):
        receipt = output/'coverage.json'
        if not receipt.exists() or load(receipt).get('pricing_profile') != profile:
            raise ValueError('NG45 requires a new output root or matching NG45 receipt')


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix+'.part')
    with partial.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    partial.replace(path)


def write_csv(path, rows, fallback):
    fields = sorted({key for row in rows for key in row}) if rows else fallback
    partial = path.with_suffix('.csv.part')
    with partial.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
        stream.flush(); os.fsync(stream.fileno())
    partial.replace(path)


def key(case):
    result = '/'.join((case['arch'], case['trace_relative_dir'], case['layer']))
    if Path(result).is_absolute() or '..' in Path(result).parts:
        raise ValueError('unsafe case key')
    return result


def collector():
    # Only whole_model is called: collect() would read simulator cases.
    sys.path.insert(0, str(REPO/'zoo/fig12_edp/demo/all_bench'))
    from report import whole_model
    from layer_scope import kept, scope_summary
    return whole_model, kept, scope_summary


def campaign(stage1_root):
    cfg = load(stage1_root/'config.json')
    repo = Path(cfg.get('repo', REPO)).resolve()
    resolve = lambda name: (repo/Path(cfg[name])).resolve()
    manifest_path, selection_path = resolve('schedule_manifest'), resolve('selection')
    manifest, plan = load(manifest_path), load(selection_path)
    _, kept, _ = collector()
    cases = manifest['schedules']
    identifiers = [key(c) for c in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('duplicate scheduled case')
    feasible = {key(c): c for c in cases if kept(c['layer']) and c['solver_status'] != 'INFEASIBLE'}
    infeasible = [c for c in cases if kept(c['layer']) and c['solver_status'] == 'INFEASIBLE']
    selected = [c['key'] for c in plan['cases']]
    if len(selected) != len(set(selected)) or not set(selected) <= feasible.keys():
        raise ValueError('invalid Stage-1 selection')
    mini = plan.get('mini', False)
    if not mini and (len(selected) != 559 or set(selected) != feasible.keys() or len(infeasible) != 6):
        raise ValueError('expected 559 kept feasible and six infeasible cases')
    selection = {'feasible': [feasible[k] for k in selected], 'infeasible': infeasible,
                 'captures': manifest.get('capture_order') or sorted({c['trace_relative_dir'] for c in cases})}
    return resolve('output_root'), selection, {'mini': mini,
        'schedule_manifest': str(manifest_path), 'schedule_sha256': digest(manifest_path),
        'selection_manifest': str(selection_path), 'selection_sha256': digest(selection_path)}


def contained(directory, relative):
    path = (directory/relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError('artifact leaves checkpoint directory')
    return path


def validate_artifacts(directory):
    manifest = load(directory/'manifest.json')
    if not manifest['artifacts']:
        raise ValueError('empty artifact manifest')
    for name, expected in manifest['artifacts'].items():
        if digest(contained(directory, name)) != expected:
            raise ValueError('artifact checksum differs: '+name)
    return manifest


def count_snapshot(root):
    result = {}
    # Include committed and partial count directories, including unselected leftovers.
    for directory in sorted(root.rglob('counts')):
        if not directory.is_dir() or directory.parent.name != 'sample_00000':
            continue
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                contained(directory, path.relative_to(directory))
                result[str(path.relative_to(root))] = digest(path)
    return result


def stage1_state(base):
    attempts = [load(p) for p in sorted(base.glob('attempt_*.json'))]
    if attempts and attempts[-1]['status'] == 'running':
        raise ValueError('Stage 1 has a running attempt: '+str(base))
    if (base/'complete.json').exists():
        return 'complete'
    if not attempts:
        raise ValueError('Stage 1 has an unresolved case: '+str(base))
    status = attempts[-1]['status']
    if status in ('oom', 'killed_or_oom'):
        return 'skipped_oom'
    if status in ('timeout', 'failed', 'interrupted', 'resource_unavailable'):
        return 'failed'
    raise ValueError('Stage 1 case lacks a terminal receipt: '+str(base))


def count_checkpoint(base, case):
    complete = load(base/'complete.json')
    if complete['status'] != 'complete' or complete['sample'] != 0 or set(complete['arms']) != set(ARMS):
        raise ValueError('invalid completion receipt')
    if key(complete['inputs']['case']) != key(case):
        raise ValueError('completion identity differs')
    directory = base/'counts'
    manifest = validate_artifacts(directory)
    receipt = load(base/'steps/checkpoint.json')
    for name in ('manifest.json', *manifest['artifacts']):
        if receipt['counts/'+name] != digest(contained(directory, name)):
            raise ValueError('count artifact differs from Stage-1 completion receipt')
    if set(manifest['graphs']) != set(ARMS):
        raise ValueError('count checkpoint missing arms')
    metadata = load(directory/'counts.json')
    if key(metadata['identity']) != key(case) or metadata['arch'] != case['arch']:
        raise ValueError('saved count identity differs from selection')
    if metadata['provenance']['noc']['sample_idx'] != 0:
        raise ValueError('saved counts are not sample 0')
    return directory, metadata


def stop_owned(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def price_case(case, counts, metadata, table, table_sha, output, stop, pricing_profile='dummy'):
    directory = output/'cases'/key(case)/'sample_00000'/table_sha
    directory.parent.mkdir(parents=True, exist_ok=True)
    log_path = directory.parent/(table_sha+'.log')
    argv = [sys.executable, '-m', 'snn_edp.run', 'price', '--counts', str(counts),
            '--table', str(table), '--out', str(directory)]
    env = {**os.environ, **THREAD_ENV, 'PYTHONDONTWRITEBYTECODE': '1',
           'ARCHX_DISABLE_PERFORMANCE_CACHE': '1',
           'PYTHONPATH': os.pathsep.join(map(str, (REPO/'zoo/archx/zoo', REPO/'zoo/archx/src', REPO/'src')))}
    if stop.is_set():
        raise InterruptedError('coordinator stopping')
    with log_path.open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=REPO, env=env, start_new_session=True)
        deadline = time.monotonic()+600
        try:
            while True:
                if stop.is_set():
                    raise InterruptedError('coordinator stopping')
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv, 600)
                try:
                    code = process.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if code:
                raise subprocess.CalledProcessError(code, argv)
        except BaseException:
            stop_owned(process)
            raise
    manifest = validate_artifacts(directory)
    fingerprint = manifest['fingerprint']
    if fingerprint['energy_table_sha256'] != table_sha or fingerprint['count_manifest_sha256'] != digest(counts/'manifest.json'):
        raise ValueError('price fingerprint differs from pinned inputs')
    rows = load(directory/'result.json')['rows']
    if len(rows) != 3 or {r['arm'] for r in rows} != set(ARMS):
        raise ValueError('pricing did not return exactly three arms')
    labels = profile_fields(pricing_profile, table_sha)
    reason = 'DUMMY_PRICES' if pricing_profile == 'dummy' else 'NG45_INTERIM_MIXED_TECHNOLOGY_NEIGHBOR_APPROXIMATION'
    saved_counts = metadata['provenance']['counts']
    for row in rows:
        if row['arch'] != case['arch'] or row['energy_table_sha256'] != table_sha:
            raise ValueError('priced row identity differs')
        for field in ('T_s', 'E_dyn_nJ', 'E_leak_nJ', 'EDP_nJ_s'):
            if not math.isfinite(row[field]) or row[field] < 0:
                raise ValueError('invalid priced metric')
        if not math.isclose(row['EDP_nJ_s'], (row['E_dyn_nJ']+row['E_leak_nJ'])*row['T_s'], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError('layer EDP differs from energy times latency')
        row.update(capture=case['trace_relative_dir'], layer=case['layer'], sample=0, n=1,
                   incomplete=True, counts_json=json.dumps(saved_counts, sort_keys=True))
        row.update(labels)
        trace_sha = metadata['provenance']['noc'].get('inputs', {}).get('sample', {}).get('sha256')
        if trace_sha is not None:
            row['trace_sha256'] = trace_sha
        row['caveats'] = sorted(set(row.get('caveats', [])) | {labels['pricing_caveat']})
        row['incomplete_reasons'] = sorted(set(row.get('incomplete_reasons', [])) | {reason})
        row.update({'count_'+name: value for name, value in saved_counts.items()})
    return rows


def totals(selection, rows, states, table_sha, pricing_profile='dummy'):
    whole_model, _, _ = collector()
    result = whole_model(selection, rows, states)
    labels = profile_fields(pricing_profile, table_sha)
    complete_status = 'complete_dummy_prices' if pricing_profile == 'dummy' else 'complete_ng45_interim'
    for group in result:
        complete = group['coverage_complete'] and group['expected_layers'] > 0
        group.update(coverage_complete=complete, comparable_complete=False, energy_incomplete=True,
                     caveats=labels['pricing_caveat'],
                     status=complete_status if complete else 'missing_layers')
        group.update(labels)
        if not complete:
            for name in ('sum_energy_nJ', 'sum_latency_s', 'model_EDP_nJ_s', 'sum_layer_EDP_nJ_s'):
                group[name] = None
    return result


def run(stage1_root, table, output, *, confirmed_drained=False, workers=2, pricing_profile='dummy'):
    if not confirmed_drained:
        raise ValueError('main must confirm Stage-1 drain before pricing')
    if workers not in (1, 2):
        raise ValueError('workers must be 1 or 2')
    profile_fields(pricing_profile, '')
    started_unix, started_clock = time.time(), time.monotonic()
    stage1_root, table, output = (Path(p).resolve() for p in (stage1_root, table, output))
    check_output_profile(output, pricing_profile)
    root, selection, provenance = campaign(stage1_root)
    if output.is_relative_to(root) or root.is_relative_to(output) or output.is_relative_to(stage1_root):
        raise ValueError('Stage-2 output must be separate from Stage-1 data')
    states = {key(c): stage1_state(root/key(c)/'sample_00000') for c in selection['feasible']}
    table_bytes = table.read_bytes(); table_sha = hashlib.sha256(table_bytes).hexdigest()
    if pricing_profile == 'nangate45':
        check_ng45_table(json.loads(table_bytes))
    labels = profile_fields(pricing_profile, table_sha)
    output.mkdir(parents=True, exist_ok=True)
    pinned = output/(('dummy_table_' if pricing_profile == 'dummy' else 'nangate45_table_')+table_sha+'.json')
    if pinned.exists() and pinned.read_bytes() != table_bytes:
        raise ValueError('pinned table changed')
    if not pinned.exists():
        with pinned.open('wb') as stream:
            stream.write(table_bytes); stream.flush(); os.fsync(stream.fileno())
    before = count_snapshot(root)
    save(output/'coverage.json', {'status': 'running', 'report_complete': False,
        'started_unix': started_unix, 'finished_unix': None,
        'wall_seconds': time.monotonic()-started_clock,
        **labels})
    save(output/'counts_before.json', before)
    jobs, errors, rows = [], {}, []
    for case in selection['feasible']:
        identity = key(case)
        if states[identity] != 'complete':
            errors[identity] = 'terminal Stage-1 failure'
            continue
        try:
            counts, metadata = count_checkpoint(root/identity/'sample_00000', case)
            jobs.append((case, counts, metadata))
        except (OSError, ValueError, KeyError) as error:
            states[identity] = 'failed'; errors[identity] = str(error)
    stop = threading.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {}
    try:
        futures = {executor.submit(price_case, case, counts, metadata, pinned, table_sha, output, stop, pricing_profile): key(case)
                   for case, counts, metadata in jobs}
        for finished, future in enumerate(concurrent.futures.as_completed(futures), 1):
            identity = futures[future]
            try:
                rows.extend(future.result())
            except Exception as error:
                states[identity] = 'failed'; errors[identity] = str(error)
            if finished % 25 == 0 or finished == len(futures):
                print(json.dumps({'event': 'stage2_progress', 'finished_cases': finished,
                    'total_price_cases': len(futures), 'result_rows': len(rows),
                    'failed_cases': len(errors), 'wall_seconds': time.monotonic()-started_clock},
                    sort_keys=True), flush=True)
    finally:
        stop.set()
        executor.shutdown(wait=True, cancel_futures=True)
        after = count_snapshot(root)
        save(output/'counts_after.json', after)
        save(output/'immutability.json', {'unchanged': before == after, 'files': len(before),
             'before_sha256': digest(output/'counts_before.json'), 'after_sha256': digest(output/'counts_after.json')})
    drift = (before != after or digest(table) != table_sha or digest(pinned) != table_sha
             or digest(provenance['schedule_manifest']) != provenance['schedule_sha256']
             or digest(provenance['selection_manifest']) != provenance['selection_sha256'])
    if drift:
        save(output/'coverage.json', {'status': 'input_drift', 'report_complete': False,
             'started_unix': started_unix, 'finished_unix': time.time(),
             'wall_seconds': time.monotonic()-started_clock, 'count_artifacts_unchanged': before == after, **labels})
        raise ValueError('count artifacts, table or selection changed during pricing; collection refused')
    rows.sort(key=lambda r: (r['capture'], r['arch'], r['layer'], r['arm']))
    models = totals(selection, rows, states, table_sha, pricing_profile)
    _, _, scope_summary = collector()
    coverage = {**provenance, 'status': 'collected', 'stage1_root': str(stage1_root), 'main_confirmed_drained': True,
        **labels, 'table_source': str(table),
        'caveats': [labels['pricing_caveat']], 'sample': 0, 'n': 1, 'workers': workers,
        'case_states': states, 'errors': errors, 'infeasible': selection['infeasible'],
        'scope': scope_summary(selection), 'result_rows': len(rows), 'whole_model_groups': len(models),
        'count_artifacts_unchanged': True, 'count_artifact_files': len(before),
        'completed_cases': sum(v == 'complete' for v in states.values()),
        'failed_cases': sum(v != 'complete' for v in states.values()),
        'report_complete': not provenance['mini'] and all(v == 'complete' for v in states.values())}
    suffix = '_ng45' if pricing_profile == 'nangate45' else ''
    write_csv(output/('results'+suffix+'.csv'), rows, ['arch', 'capture', 'layer', 'sample', 'arm', 'T_s',
              'E_dyn_nJ', 'E_leak_nJ', 'EDP_nJ_s', 'incomplete', 'energy_table_sha256'])
    write_csv(output/('whole_model'+suffix+'.csv'), models, ['benchmark', 'arch', 'arm', 'status'])
    coverage.update(started_unix=started_unix, finished_unix=time.time(),
                    wall_seconds=time.monotonic()-started_clock)
    save(output/'coverage.json', coverage)
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage1-root', type=Path, required=True)
    parser.add_argument('--table', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--confirmed-drained', action='store_true')
    parser.add_argument('--pricing-profile', choices=PRICING_PROFILES, default='dummy')
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError(f'coordinator received signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    print(json.dumps(run(args.stage1_root, args.table, args.output,
                         confirmed_drained=args.confirmed_drained, workers=args.workers,
                         pricing_profile=args.pricing_profile), sort_keys=True))


if __name__ == '__main__':
    main()
