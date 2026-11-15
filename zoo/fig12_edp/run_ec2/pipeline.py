"""One actual sample: native generation, three arms, durable join, trace deletion."""
import csv
import importlib
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys
import time

from config import (ARMS, GIB, case_inputs, digest, environment, folder, input_files,
                    key, save, schedule, scientific_inputs, sync_dir)


def run_command(argv, log, cfg, scratch, stdout=None):
    with log.open('w') as stream:
        subprocess.run(argv, stdout=stdout or stream, stderr=stream, check=True,
                       env=environment(cfg, scratch), cwd=cfg['repo_root'],
                       timeout=cfg['timeout_seconds'])


def count_case(cfg, case, sample, records):
    import numpy as np
    paths = input_files(cfg, case)
    meta = json.loads(paths['meta'].read_text())
    trace = np.load(paths['capture'], mmap_mode='r')
    following = np.load(paths['density'], mmap_mode='r')
    if sample >= trace.shape[1] or sample >= following.shape[1]:
        raise ValueError('sample is outside the capture')
    density = float(np.count_nonzero(following[:, sample])/following[:, sample].size)
    params = meta['layer_params'][case['layer']]
    options = dict(cout=params['cout'], kernel=params['kernel'], stride=params['stride'])
    module = importlib.import_module(case['arch']+'_counts')
    if case['arch'] == 'prosperity':
        artifact = json.loads(paths['schedule'].read_text())
        options.update(tile=module.schedule_tile(case, artifact), records=records,
                       records_source='exact_pipeline_csv', d_out=density)
    elif case['arch'] != 'spinalflow':
        options['d_out'] = density
    counts = module.count_sample(trace, sample, **options)
    if case['arch'] == 'spinalflow':
        counts.update(L=counts['O'], O=counts['O']*density, d_out=density)
    counts.update(COUT=params['cout'], kernel=params['kernel'], density_layer=paths['density'].stem,
                  O_source='final_layer_own_density_proxy' if paths['density'] == paths['capture'] else 'next_layer_input_density')
    import hashlib
    evidence = {'sample': sample, 'capture_sample_sha256': hashlib.sha256(trace[:, sample].tobytes()).hexdigest(),
                'density_sample_sha256': hashlib.sha256(following[:, sample].tobytes()).hexdigest(), 'd_out': density}
    return counts, evidence


def validate_result(path, expected):
    result = json.loads(path.read_text())
    if result['fingerprint'] != expected:
        raise ValueError(f'stale case inputs; use a new output root: {path}')
    if len(result['rows']) != 3 or {r['arm'] for r in result['rows']} != set(ARMS):
        raise ValueError('incomplete result arms')
    for name, sha in result['artifacts'].items():
        if digest(path.parent/name) != sha:
            raise ValueError(f'durable artifact changed: {path.parent/name}')
    for row in result['rows']:
        if row['sample'] != expected['sample'] or '/'.join((row['arch'], row['capture'], row['layer'])) != expected['case']:
            raise ValueError('result sample/identity mismatch')
    return result


def scratch_for(cfg, case, sample):
    import hashlib
    tag = hashlib.sha256((cfg['output']+'/'+key(case)+f'/{sample}').encode()).hexdigest()[:24]
    return Path(cfg['scratch'])/tag


def cleanup_scratch(cfg, case, sample, expected):
    scratch = scratch_for(cfg, case, sample)
    if not scratch.exists():
        return
    if scratch.is_symlink() or scratch.resolve().parent != Path(cfg['scratch']).resolve():
        raise ValueError('refusing cleanup outside owned case scratch')
    if json.loads((scratch/'owner.json').read_text()) != expected:
        raise ValueError('refusing cleanup of foreign scratch')
    validate_result(folder(cfg, case, sample)/'result.json', expected)
    shutil.rmtree(scratch)
    sync_dir(Path(cfg['scratch']))


def run_case(cfg, task):
    limit = int(task['memory_gib']*GIB)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    os.environ.update(environment(cfg))
    root = Path(cfg['repo_root'])
    sys.path[:0] = [str(root/'src'), str(root/'zoo/fig12_edp'), str(root/'zoo/fig12_edp/counts')]
    case, sample = task['case'], task['sample']
    if scientific_inputs(cfg) != task['fingerprint']['shared']:
        raise ValueError('scientific source/binary/config changed before case')
    expected = case_inputs(cfg, case, sample, task['fingerprint']['shared'])
    if expected != task['fingerprint']:
        raise ValueError('case input changed before execution')
    output = folder(cfg, case, sample); output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    scratch = scratch_for(cfg, case, sample)
    scratch.mkdir(parents=True, exist_ok=True)
    owner = scratch/'owner.json'
    if owner.exists() and json.loads(owner.read_text()) != expected:
        raise ValueError('scratch belongs to different input fingerprints')
    save(owner, expected)
    os.environ.update(environment(cfg, scratch))
    if (output/'result.json').exists():
        validate_result(output/'result.json', expected)
        cleanup_scratch(cfg, case, sample, expected)
        return
    trace = scratch/'trace.wcts'
    generation = output/'generation.json'
    if not (trace.exists() and generation.exists()):
        directory = Path(cfg['capture_root'])/case['trace_relative_dir']
        argv = [sys.executable, '-B', '-m', 'lays.weight_trace_gen', 'gen', '--arch', case['arch'],
                '--trace-root', str(directory.parent), '--trace-dir', directory.name, '--layer', case['layer'],
                '--schedule-cache', str(Path(cfg['manifest']).parent/'schedules'), '--stream',
                '--sample-start', str(sample), '--sample-count', '1', '--workers', '1', '--sample-chunk-size', '1']
        with (scratch/'trace.part').open('wb') as sink:
            run_command(argv, output/'generation.log', cfg, scratch, sink)
            sink.flush(); os.fsync(sink.fileno())
        (scratch/'trace.part').replace(trace); sync_dir(scratch)
        with trace.open('rb') as stream:
            stream.seek(-12, 2); marker, records = struct.unpack('<iQ', stream.read())
        if marker != -1:
            raise ValueError('truncated WCTS trailer')
        save(generation, {'sha256': digest(trace), 'records': records, 'sample': sample,
                          'fingerprint': expected, 'command': argv})
    info = json.loads(generation.read_text())
    if info['fingerprint'] != expected or info['sha256'] != digest(trace):
        raise ValueError('stale generation; refusing reuse')
    record_path = output/'record_count.csv'
    with record_path.with_suffix('.part').open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['capture', 'layer', 'sample', 'R_p'])
        writer.writerow([case['trace_relative_dir'], case['layer'], sample, info['records']])
        stream.flush(); os.fsync(stream.fileno())
    record_path.with_suffix('.part').replace(record_path); sync_dir(output)
    counts, evidence = count_case(cfg, case, sample, info['records'])
    save(output/'counts.json', counts); save(output/'sample_evidence.json', evidence)
    from nocsim.driver import run_case as run_noc
    noc = run_noc(schedule(cfg, case), case['arch'], trace, output/'noc',
                  arch_path=cfg['arch_yaml'], eventsim_binary=cfg['eventsim'])
    if noc['sample_idx'] != sample:
        raise ValueError('NoC read a different WCTS sample')
    caches = {}
    for arm in ('a', 'b'):
        csv_path = output/f'cache_{arm}.csv'
        run_command([cfg['cachesim'], '--trace', str(trace), '--config', cfg['cache_'+arm],
                     '--arm', 'cache', '--header', '--out', str(csv_path)], output/f'cache_{arm}.log', cfg, scratch)
        with csv_path.open() as stream:
            row, = list(csv.DictReader(stream))
        caches['cache'+arm.upper()] = row
    from energy_driver import archx_aggregate_case
    save(output/'case.json', case)
    rows = archx_aggregate_case(case['arch'], output, cfg['energy_table'])
    for row in rows:
        row.update(arch=case['arch'], capture=case['trace_relative_dir'], layer=case['layer'], sample=sample,
                   counts_json=json.dumps(counts, sort_keys=True), trace_sha256=info['sha256'])
        row.update({'count_'+k: v for k, v in counts.items()})
        if row['energy_table_sha256'] != expected['shared']['energy_table']:
            raise ValueError('table changed during join')
    if scientific_inputs(cfg) != expected['shared'] or case_inputs(cfg, case, sample, expected['shared']) != expected:
        raise ValueError('inputs changed during case; result not committed')
    artifacts = {name: digest(output/name) for name in (
        'case.json', 'generation.json', 'record_count.csv', 'counts.json', 'sample_evidence.json',
        'noc/result.json', 'noc/tc.csv', 'cache_a.csv', 'cache_b.csv')}
    for name in artifacts:
        with (output/name).open('rb') as stream:
            os.fsync(stream.fileno())
    save(output/'result.json', {'fingerprint': expected, 'rows': rows, 'artifacts': artifacts,
                              'wall_seconds': time.monotonic()-started})
    cleanup_scratch(cfg, case, sample, expected)
    (output/'failure.json').unlink(missing_ok=True)
