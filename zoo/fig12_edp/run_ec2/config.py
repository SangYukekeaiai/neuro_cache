"""Explicit machine configuration and fail-closed scientific fingerprints."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ARCHES = ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity')
ARMS = ('spad', 'cacheA', 'cacheB')
GIB = 1024**3
THREADS = dict.fromkeys(('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'NUMEXPR_MAX_THREADS', 'RAYON_NUM_THREADS', 'BLIS_NUM_THREADS',
    'VECLIB_MAXIMUM_THREADS', 'POLARS_MAX_THREADS', 'TBB_NUM_THREADS', 'GOTO_NUM_THREADS'), '1')
PATHS = ('capture_root', 'manifest', 'arch_yaml', 'cachesim', 'eventsim', 'energy_table',
         'cache_a', 'cache_b', 'record_estimates', 'scratch', 'output')


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.part')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path); sync_dir(path.parent)


def load(path):
    cfg = json.loads(Path(path).read_text())
    cfg['repo_root'] = str((REPO/Path(cfg['repo_root'])).resolve())
    for key in PATHS:
        cfg[key] = str((Path(cfg['repo_root'])/Path(cfg[key])).resolve())
    for key in ('shard_manifest', 'global_unlock'):
        if cfg.get(key):
            cfg[key] = str((Path(cfg['repo_root'])/Path(cfg[key])).resolve())
    if bool(cfg.get('shard_manifest')) != bool(cfg.get('shard_id')):
        raise ValueError('shard_manifest and shard_id must be supplied together')
    if not 0 <= cfg['sample_start'] < cfg['sample_stop'] <= 500:
        raise ValueError('samples must lie in [0, 500), with an exclusive stop')
    tiers = cfg['memory_tiers_gib']
    if not tiers or tiers != sorted(set(tiers)) or tiers[0] <= 0:
        raise ValueError('memory tiers must be increasing positive limits')
    if cfg['workers'] < 1 or cfg['memory_budget_gib'] <= cfg['driver_reserve_gib']:
        raise ValueError('invalid worker count or memory budget')
    if cfg['case_limit'] < 0 or cfg['timeout_seconds'] <= 0 or cfg['scratch_min_free_gib'] < 0:
        raise ValueError('invalid case limit, timeout or disk reserve')
    scratch, output = Path(cfg['scratch']), Path(cfg['output'])
    if scratch == output or scratch.is_relative_to(output) or output.is_relative_to(scratch):
        raise ValueError('durable output and scratch must be separate directory trees')
    protected = [Path(cfg['capture_root']), Path(cfg['manifest']).parent,
                 Path(cfg['repo_root'])/'src', HERE.parent/'demo',
                 Path(cfg['repo_root'])/'zoo/wt500_fig3cfg/stokes']
    for destination in (scratch, output):
        if any(destination == p or destination.is_relative_to(p) or p.is_relative_to(destination) for p in protected):
            raise ValueError(f'output/scratch overlaps a protected input: {destination}')
    return cfg


def environment(cfg, temporary=None):
    return {**os.environ, **THREADS, 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONPATH': str(Path(cfg['repo_root'])/'src'),
            'TMPDIR': str(temporary or cfg['scratch'])}


def key(case):
    return '/'.join((case['arch'], case['trace_relative_dir'], case['layer']))


def folder(cfg, case, sample):
    return Path(cfg['output'])/'cases'/key(case)/f'sample_{sample:05d}'


def schedule(cfg, case):
    return Path(cfg['manifest']).parent/case['schedule_path']


def input_files(cfg, case):
    directory = Path(cfg['capture_root'])/case['trace_relative_dir']
    meta_path = directory/'meta.json'
    meta = json.loads(meta_path.read_text())
    layers = list(meta['layers']); pos = layers.index(case['layer'])
    following = layers[min(pos+1, len(layers)-1)]
    return {'capture': directory/(case['layer']+'.npy'), 'density': directory/(following+'.npy'),
            'meta': meta_path, 'schedule': schedule(cfg, case)}


def scientific_inputs(cfg):
    root = Path(cfg['repo_root'])
    sys.path.insert(0, str(root/'zoo/fig12_edp'))
    from energy_driver import check_cache_configs, scientific_files
    check_cache_configs(cfg['cache_a'], cfg['cache_b'])
    a = json.loads(Path(cfg['cache_a']).read_text())
    if (a['l1_prefetch_policy'], a['l1_prefetch_distance'], a['l2_prefetch_policy'],
        a['l2_prefetch_distance'], a['l2_prefetch_min_touches']) != ('next_access', 4, 'distance_aware', 1, 9):
        raise ValueError('cache A must remain L1 d4 / L2 d1 / min_touches9')
    files = {name: Path(cfg[name]) for name in ('manifest', 'arch_yaml', 'cachesim', 'eventsim',
             'energy_table', 'cache_a', 'cache_b')}
    for arch, binary in zip(ARCHES, ('spinalflowgen', 'ptbgen', 'loasgen', 'gustavgen', 'prosperitygen')):
        files['generator_'+arch] = root/'src/lays/weight_trace_gen'/arch/binary
    paths = [p for p in (root/'src/lays').rglob('*')
             if p.is_file() and p.suffix in ('.py', '.cpp', '.h', '.hpp', '.c')]
    for area in ('counts', 'nocsim'):
        paths += list((root/'zoo/fig12_edp'/area).glob('*.py'))
    files.update(scientific_files())
    paths += [root/'zoo/fig12_edp/energy_driver.py', root/'zoo/fig12_edp/docs/workload_layer_scope.md']
    files.update({str(p.relative_to(root)): p for p in paths if not p.name.startswith('test_')})
    files.update({'runner/'+name: HERE/name for name in (
        'pipeline.py', 'config.py', 'collect.py', 'run.py', 'plot.py',
        'shards.py', 'shard_cases.py', 'merge_results.py')})
    if cfg.get('shard_manifest'):
        files['shard_manifest'] = Path(cfg['shard_manifest'])
    return {name: digest(path) for name, path in sorted(files.items())}


def case_inputs(cfg, case, sample, shared):
    return {'shared': shared, 'sample': sample, 'case': key(case),
            'inputs': {name: digest(path) for name, path in input_files(cfg, case).items()}}


def select(cfg):
    manifest = json.loads(Path(cfg['manifest']).read_text())
    feasible = [r for r in manifest['schedules'] if r['solver_status'] != 'INFEASIBLE']
    infeasible = [r for r in manifest['schedules'] if r['solver_status'] == 'INFEASIBLE']
    if len(feasible) != 749 or len(infeasible) != 6 or len({key(c) for c in feasible}) != 749:
        raise ValueError('manifest must contain 749 unique feasible + 6 infeasible cases')
    estimates = json.loads(Path(cfg['record_estimates']).read_text())
    for case in feasible:
        artifact = schedule(cfg, case)
        if digest(artifact) != case['schedule_sha256']:
            raise ValueError(f'schedule digest differs: {artifact}')
        if case['arch_yaml_sha256'] != digest(cfg['arch_yaml']):
            raise ValueError('architecture YAML differs from solved schedules')
        records = estimates[key(case)]
        size = input_files(cfg, case)['capture'].stat().st_size
        case['estimated_records'] = records
        case['estimated_memory_gib'] = 2+(size+records*512)/GIB
    feasible.sort(key=lambda c: (c['estimated_memory_gib'], key(c)))
    shard = None
    if cfg.get('shard_manifest'):
        from shards import read_partition
        plan, assignments = read_partition(Path(cfg['shard_manifest']), Path(cfg['manifest']))
        if cfg['case_keys'] or cfg['case_limit']:
            raise ValueError('shard selection cannot be combined with local case filters')
        if cfg['shard_id'] not in assignments:
            raise ValueError('unknown shard_id')
        feasible = [c for c in feasible if key(c) in assignments[cfg['shard_id']]]
        shard = {'id': cfg['shard_id'], 'partition_sha256': digest(cfg['shard_manifest']),
                 'global_subset': plan['subset'], 'selected_global_pairs': len(plan['selected_case_keys'])}
    if cfg['case_keys']:
        wanted = set(cfg['case_keys'])
        feasible = [c for c in feasible if key(c) in wanted]
        if {key(c) for c in feasible} != wanted:
            raise ValueError('unknown requested case key')
    if cfg['case_limit']:
        feasible = feasible[:cfg['case_limit']]
    return {'cases': feasible, 'infeasible': infeasible, 'nominal_feasible': 749,
            'subset': len(feasible) != 749, 'captures': manifest['capture_order'], 'shard': shard}
