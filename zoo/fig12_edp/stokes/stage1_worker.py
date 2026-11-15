"""One sample-0 case: native replay, simulator measurements, durable event counts."""
import argparse
import csv
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GIB = 1024**3
TIERS = ((16, 25), (64, 45), (120, 60))
SHUTDOWN_RESERVE_SECONDS = 30
THREAD_ENV = dict.fromkeys(('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'RAYON_NUM_THREADS', 'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
    'NUMEXPR_MAX_THREADS', 'POLARS_MAX_THREADS', 'TBB_NUM_THREADS', 'GOTO_NUM_THREADS'), '1')


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.part')
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    sync_dir(path.parent)


def identity(case):
    parts = (case['arch'], case['trace_relative_dir'], case['layer'])
    if any(Path(p).is_absolute() or '..' in Path(p).parts for p in parts):
        raise ValueError('unsafe case identity')
    return '/'.join(parts)


def configure(path):
    cfg = load(path)
    repo = Path(cfg.get('repo', REPO)).resolve()
    paths = ('capture_root', 'schedule_manifest', 'schedule_cache', 'selection',
             'cachesim', 'eventsim', 'cache_a', 'cache_b', 'output_root', 'scratch_root')
    for key in paths:
        value = Path(cfg[key])
        cfg[key] = value.resolve() if value.is_absolute() else (repo/value).resolve()
    cfg['repo'] = repo
    cfg['arch_yaml'] = {arch: (repo/Path(p)).resolve() for arch, p in cfg['arch_yaml'].items()}
    for output in (cfg['output_root'], cfg['scratch_root']):
        for protected in (cfg['capture_root'], cfg['schedule_manifest'].parent, cfg['schedule_cache']):
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise ValueError('output/scratch overlaps read-only input tree')
    if cfg['output_root'].is_relative_to(cfg['scratch_root']) or cfg['scratch_root'].is_relative_to(cfg['output_root']):
        raise ValueError('durable output and scratch must be separate trees')
    sys.path[:0] = [str(repo/'src'), str(repo/'zoo/fig12_edp'),
                   str(repo/'zoo/fig12_edp/counts'), str(repo/'zoo/archx/zoo')]
    os.environ.update(THREAD_ENV)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONPATH'] = os.pathsep.join(sys.path[:4])
    os.environ['ARCHX_DISABLE_PERFORMANCE_CACHE'] = '1'
    return cfg


def selection(cfg):
    from demo.all_bench.layer_scope import kept
    rows = load(cfg['schedule_manifest'])['schedules']
    keys = [identity(c) for c in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate schedule keys')
    feasible = {identity(c): c for c in rows if c['solver_status'] != 'INFEASIBLE' and kept(c['layer'])}
    plan = load(cfg['selection'])
    entries = plan['cases']
    selected = [r['key'] for r in entries]
    if len(selected) != len(set(selected)) or not set(selected) <= feasible.keys():
        raise ValueError('duplicate, excluded, infeasible or unknown selected case')
    if not plan.get('mini', False) and (len(feasible) != 559 or set(selected) != feasible.keys()):
        raise ValueError('full selection must cover exactly 559 kept feasible cases')
    for entry in entries:
        initial_tier(entry)
    return [(feasible[e['key']], e) for e in entries]


def initial_tier(entry):
    proxy = entry['record_memory_proxy_gib']
    if not isinstance(proxy, (int, float)) or not math.isfinite(proxy) or proxy < 0:
        raise ValueError('invalid planning memory proxy')
    if entry.get('tier') == 'historical_oom':
        if not entry['key'].startswith('spinalflow/'):
            raise ValueError('historical SF OOM annotation on another architecture')
        return 2
    return 1 if proxy > 16 else 0


def resources(entry, attempt):
    tier = initial_tier(entry) + attempt
    if attempt not in (0, 1) or tier >= len(TIERS):
        raise ValueError('no further resource tier; at most one retry')
    memory, minutes = TIERS[tier]
    return {'tier': tier, 'memory_gib': memory, 'timeout_seconds': minutes*60}


def paths(cfg, case):
    suffix = Path(identity(case))/'sample_00000'
    return cfg['output_root']/suffix, cfg['scratch_root']/suffix


def input_files(cfg, case):
    directory = cfg['capture_root']/case['trace_relative_dir']
    meta = load(directory/'meta.json')
    layers = list(meta['layers']); position = layers.index(case['layer'])
    density_layer = layers[min(position+1, len(layers)-1)]
    schedule = (cfg['schedule_manifest'].parent/case['schedule_path']).resolve()
    generator_schedule = cfg['schedule_cache']/case['arch']/directory.name/(case['layer']+'.json')
    if digest(schedule) != digest(generator_schedule):
        raise ValueError('generator schedule differs from selected manifest artifact')
    expected_arch = load(schedule).get('arch_yaml_sha256')
    if expected_arch and digest(cfg['arch_yaml'][case['arch']]) != expected_arch:
        raise ValueError('architecture YAML hash differs from schedule')
    native = {'gustavsnn': 'gustavgen'}.get(case['arch'], case['arch']+'gen')
    files = {'schedule': schedule, 'meta': directory/'meta.json',
             'capture': directory/(case['layer']+'.npy'),
             'density_capture': directory/(density_layer+'.npy'),
             'arch_yaml': cfg['arch_yaml'][case['arch']],
             'generator': cfg['repo']/f"src/lays/weight_trace_gen/{case['arch']}/{native}"}
    files.update({key: cfg[key] for key in ('cachesim', 'eventsim', 'cache_a', 'cache_b')})
    return files, density_layer


def inputs(cfg, case):
    files, _ = input_files(cfg, case)
    repo = cfg['repo']
    source_paths = [Path(__file__), repo/'zoo/fig12_edp/docs/workload_layer_scope.md',
                    repo/'zoo/fig12_edp/demo/all_bench/layer_scope.py']
    for root in (repo/'src/lays', repo/'zoo/fig12_edp/counts', repo/'zoo/fig12_edp/nocsim'):
        source_paths.extend(p for p in root.rglob('*') if p.is_file()
            and p.suffix in ('.py', '.cpp', '.h', '.hpp')
            and not {'build', 'tests', '__pycache__'}.intersection(p.parts)
            and not p.name.startswith('test_'))
    from snn_edp.model import HERE as model_root, backend_fingerprint
    source_paths.extend(model_root/p for p in ('__init__.py', 'model.py', 'run.py', 'hardware.json',
        'performance.py', 'designs/snn/description.py', 'interfaces/counts.py', 'runtime/sitecustomize.py'))
    return {'case': case, 'sample': 0, 'files': {name: digest(p) for name, p in files.items()},
            'source': {str(p.relative_to(repo)): digest(p) for p in sorted(set(source_paths))},
            'archx': backend_fingerprint()}


def commit_step(base, name, artifacts):
    hashes = {str(p.relative_to(base)): digest(p) for p in artifacts}
    for p in artifacts:
        with p.open('rb') as stream:
            os.fsync(stream.fileno())
        sync_dir(p.parent)
    save(base/'steps'/f'{name}.json', hashes)


def valid_step(base, name):
    receipt = base/'steps'/f'{name}.json'
    if not receipt.exists():
        return False
    for name, expected in load(receipt).items():
        path = (base/name).resolve()
        if not path.is_relative_to(base.resolve()) or digest(path) != expected:
            raise ValueError('durable stage artifact changed: '+name)
    return True


def command(argv, log, stdout=None):
    # All descendants inherit the worker session, owned by supervise().
    with log.open('w') as stream:
        subprocess.run(argv, stdout=stdout or stream, stderr=stream, check=True)


def count_sample(cfg, case, records):
    # Same sample/density convention as demo.run.count_case; underlying count modules are shared.
    import numpy as np
    directory = cfg['capture_root']/case['trace_relative_dir']
    files, density_layer = input_files(cfg, case)
    meta = load(directory/'meta.json')
    trace = np.load(files['capture'], mmap_mode='r')
    following = np.load(files['density_capture'], mmap_mode='r')
    density = float(np.count_nonzero(following[:, 0])/following[:, 0].size)
    params = meta['layer_params'][case['layer']]
    options = dict(cout=params['cout'], kernel=params['kernel'], stride=params['stride'])
    module = importlib.import_module(case['arch']+'_counts')
    if case['arch'] == 'prosperity':
        options.update(tile=module.schedule_tile(case, load(files['schedule'])), records=records,
                       records_source='exact_pipeline_csv', d_out=density)
    elif case['arch'] != 'spinalflow':
        options['d_out'] = density
    counts = module.count_sample(trace, 0, **options)
    if case['arch'] == 'spinalflow':
        counts.update(L=counts['O'], O=counts['O']*density, d_out=density)
    return {**counts, 'COUT': params['cout'], 'kernel': params['kernel'],
            'density_layer': density_layer, 'O_source': 'final_layer_own_density_proxy'
            if density_layer == case['layer'] else 'next_layer_input_density'}


def checkpoint(base):
    from snn_edp.model import validate_artifacts, count_fingerprint
    directory = base/'counts'
    manifest = validate_artifacts(directory)
    if manifest['fingerprint'] != count_fingerprint(base/'case'):
        raise ValueError('count checkpoint inputs/model changed')
    if set(manifest['graphs']) != {'spad', 'cacheA', 'cacheB'}:
        raise ValueError('count checkpoint missing arms')
    return directory, manifest


def completed(base, fingerprint):
    receipt = base/'complete.json'
    if not receipt.exists():
        return False
    if load(receipt)['inputs'] != fingerprint:
        raise ValueError('completed case inputs changed; refusing recomputation')
    if not valid_step(base, 'checkpoint'):
        raise ValueError('completed case missing checkpoint receipt')
    checkpoint(base)
    return True


def cleanup_trace(scratch):
    (scratch/'sample_00000.wcts').unlink(missing_ok=True)
    if scratch.exists():
        sync_dir(scratch)


def pipeline(cfg, case):
    from nocsim.driver import run_case as run_noc
    from snn_edp.run import count
    base, scratch = paths(cfg, case)
    fingerprint = inputs(cfg, case)
    if completed(base, fingerprint):
        cleanup_trace(scratch)
        return 'resumed'
    saved = base/'inputs.json'
    if saved.exists() and load(saved) != fingerprint:
        raise ValueError('partial case inputs changed; refusing stale reuse')
    save(saved, fingerprint)
    folder = base/'case'; folder.mkdir(exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch/'tmp').mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(scratch/'tmp')
    import tempfile
    tempfile.tempdir = None
    save(folder/'case.json', case)
    trace = scratch/'sample_00000.wcts'
    generation = folder/'generation.json'
    if not valid_step(base, 'generation'):
        directory = cfg['capture_root']/case['trace_relative_dir']
        args = [sys.executable, '-m', 'lays.weight_trace_gen', 'gen', '--arch', case['arch'],
                '--trace-root', str(directory.parent), '--trace-dir', directory.name,
                '--layer', case['layer'], '--schedule-cache', str(cfg['schedule_cache']),
                '--stream', '--sample-start', '0', '--sample-count', '1', '--workers', '1']
        partial = trace.with_suffix('.part')
        with partial.open('wb') as stream:
            command(args, base/'generation.log', stream)
            stream.flush(); os.fsync(stream.fileno())
        with partial.open('rb') as stream:
            stream.seek(-12, 2); marker, records = struct.unpack('<iQ', stream.read())
        if marker != -1:
            raise ValueError('incomplete WCTS trailer')
        partial.replace(trace); sync_dir(scratch)
        save(generation, {'sha256': digest(trace), 'records': records, 'sample': 0,
                          'trace_path': str(trace), 'generator_command': args})
        commit_step(base, 'generation', [generation])
    info = load(generation)
    if not trace.exists() or digest(trace) != info['sha256']:
        raise ValueError('pending case trace missing or changed')
    if not valid_step(base, 'numpy_counts'):
        save(folder/'counts.json', count_sample(cfg, case, info['records']))
        record_path = folder/'record_count.csv'
        with record_path.open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(['capture', 'layer', 'sample', 'R_p'])
            writer.writerow([case['trace_relative_dir'], case['layer'], 0, info['records']])
        commit_step(base, 'numpy_counts', [folder/'counts.json', record_path])
    for arm in ('a', 'b'):
        if not valid_step(base, 'cache_'+arm):
            output = folder/f'cache_{arm}.csv'
            command([str(cfg['cachesim']), '--trace', str(trace), '--config', str(cfg['cache_'+arm]),
                     '--arm', 'cache', '--header', '--out', str(output)], base/f'cache_{arm}.log')
            with output.open() as stream:
                row, = list(csv.DictReader(stream))
            if not row or int(row['sample_idx']) != 0:
                raise ValueError('cache CSV must describe sample 0')
            commit_step(base, 'cache_'+arm, [output])
    if not valid_step(base, 'noc'):
        files, _ = input_files(cfg, case)
        run_noc(files['schedule'], case['arch'], trace, folder/'noc',
                arch_path=cfg['arch_yaml'][case['arch']], eventsim_binary=cfg['eventsim'])
        commit_step(base, 'noc', [folder/'noc/result.json', folder/'noc/tc.csv'])
    if not (base/'counts/manifest.json').exists():
        count(folder, base/'counts')
    directory, manifest = checkpoint(base)
    if inputs(cfg, case) != fingerprint:
        raise ValueError('inputs changed while running')
    artifacts = [directory/'manifest.json', *(directory/name for name in manifest['artifacts']),
                 folder/'case.json', generation, folder/'counts.json', folder/'record_count.csv',
                 folder/'cache_a.csv', folder/'cache_b.csv', folder/'noc/result.json', folder/'noc/tc.csv']
    commit_step(base, 'checkpoint', artifacts)
    save(base/'complete.json', {'inputs': fingerprint, 'sample': 0, 'status': 'complete',
                              'checkpoint': str(directory), 'arms': list(manifest['graphs'])})
    cleanup_trace(scratch)
    return 'complete'


def terminate_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The session may still contain a native descendant after its Python parent exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def failure_status(outcome, entry, attempt):
    status = {'status': outcome, 'attempt': attempt, **resources(entry, attempt), 'retry': None}
    if outcome in ('oom', 'timeout', 'killed_or_oom') and attempt == 0 and initial_tier(entry) < 2:
        status['retry'] = {'attempt': 1, **resources(entry, 1)}
    return status


def actual_limits():
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    return {'rlimit_as_soft_bytes': None if soft == resource.RLIM_INFINITY else soft,
            'rlimit_as_hard_bytes': None if hard == resource.RLIM_INFINITY else hard,
            'slurm_mem_per_node': os.environ.get('SLURM_MEM_PER_NODE'),
            'slurm_job_id': os.environ.get('SLURM_JOB_ID')}


def supervise(config_path, cfg, case, entry, index, attempt):
    base, scratch = paths(cfg, case)
    base.mkdir(parents=True, exist_ok=True)
    with (base/'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fingerprint = inputs(cfg, case)
        if completed(base, fingerprint):
            cleanup_trace(scratch)
            return {'status': 'resumed', 'checkpoint': str(base/'counts')}
        limits = resources(entry, attempt)
        status_path = base/f'attempt_{attempt}.json'
        if status_path.exists() and load(status_path)['status'] != 'resource_unavailable':
            raise ValueError('attempt already used; inspect its status instead of rerunning')
        if attempt:
            previous = load(base/'attempt_0.json')
            if previous.get('retry') != {'attempt': attempt, **limits}:
                raise ValueError('retry requires recorded OOM/timeout and the next resource tier')
        observed = actual_limits()
        hard = observed['rlimit_as_hard_bytes']
        status = {'status': 'running', 'attempt': attempt, 'case': identity(case),
                  'started_unix': time.time(), 'actual_limits': observed,
                  'shutdown_reserve_seconds': SHUTDOWN_RESERVE_SECONDS, **limits}
        if hard is not None and hard < limits['memory_gib']*GIB:
            status.update(status='resource_unavailable', retry=None,
                          reason='inherited RLIMIT_AS hard limit below requested allocation; use --propagate=NONE')
            save(status_path, status)
            return status
        save(status_path, status)
        command_line = [sys.executable, str(Path(__file__).resolve()), '--config', str(config_path),
                        '--case-index', str(index), '--attempt', str(attempt), '--execute']
        with (base/f'attempt_{attempt}.log').open('w') as log:
            process = subprocess.Popen(command_line, stdout=log, stderr=log, start_new_session=True)
            def interrupted(signum, frame):
                raise InterruptedError(f'received signal {signum}')
            previous_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
            try:
                code = process.wait(timeout=limits['timeout_seconds']-SHUTDOWN_RESERVE_SECONDS)
                outcome = {0: 'complete', 42: 'oom', 43: 'timeout', 44: 'killed_or_oom',
                           -9: 'killed_or_oom'}.get(code, 'failed')
            except subprocess.TimeoutExpired:
                outcome = 'timeout'; terminate_group(process)
            except InterruptedError:
                outcome = 'interrupted'; terminate_group(process)
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
        if outcome == 'complete' and not completed(base, inputs(cfg, case)):
            outcome = 'failed'
        status.update(failure_status(outcome, entry, attempt), finished_unix=time.time())
        save(status_path, status)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--case-index', type=int, required=True)
    parser.add_argument('--attempt', type=int, choices=(0, 1), default=0)
    parser.add_argument('--execute', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    cfg = configure(args.config)
    cases = selection(cfg)
    if args.case_index < 0 or args.case_index >= len(cases):
        parser.error('case index outside selection')
    case, entry = cases[args.case_index]
    if args.execute:
        memory = resources(entry, args.attempt)['memory_gib']*GIB
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        try:
            print(pipeline(cfg, case), flush=True)
        except MemoryError:
            return 42
        except subprocess.TimeoutExpired:
            return 43
        except subprocess.CalledProcessError as exc:
            print(str(exc), file=sys.stderr)
            base, _ = paths(cfg, case)
            logs = '\n'.join(p.read_text(errors='replace')[-16000:] for p in base.glob('*.log'))
            if any(marker in logs for marker in ('std::bad_alloc', 'MemoryError', 'Cannot allocate memory')):
                return 42
            if exc.returncode == -9 or 'SIGKILL' in logs:
                return 44
            return 1
        return 0
    status = supervise(args.config.resolve(), cfg, case, entry, args.case_index, args.attempt)
    print(json.dumps(status, sort_keys=True), flush=True)
    return 0 if status['status'] in ('complete', 'resumed') else 75 if status.get('retry') else 1


if __name__ == '__main__':
    sys.exit(main())
