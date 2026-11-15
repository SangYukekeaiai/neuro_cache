"""Shared paths, fingerprints and durable case validation for the sample-0 demo."""
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fig12_parent_demo', HERE.parent/'run.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
sys.path[:0] = [str(demo.ROOT/'src'), str(demo.HERE.parent)]
ARMS = ('spad', 'cacheA', 'cacheB')
THREAD_ENV = {**demo.THREAD_ENV, **dict.fromkeys((
    'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_MAX_THREADS',
    'POLARS_MAX_THREADS', 'TBB_NUM_THREADS', 'GOTO_NUM_THREADS'), '1'),
    'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(demo.ROOT/'src')}
GIB = 1024**3
SMALL_GIB = 8
HEAVY_GIB = 54


def identity(case):
    return '/'.join((case['arch'], case['trace_relative_dir'], case['layer']))


def current_inputs():
    from nocsim.driver import _source_hash, DEFAULT_EVENTSIM
    demo.check_cachesim_fresh(demo.CACHESIM, demo.ROOT/'src/lays/cachesim/native')
    demo.check_cache_configs(*(demo.CACHE_CONFIGS/f'production_cache_{arm}.json' for arm in ('a', 'b')))
    paths = [p for p in (demo.ROOT/'src/lays').rglob('*')
             if p.is_file() and p.suffix in ('.py', '.h', '.hpp', '.c', '.cpp', '.yaml', '.json')
             and '__pycache__' not in p.parts]
    source_hash = hashlib.sha256(json.dumps(
        {str(p.relative_to(demo.ROOT)): demo.digest(p) for p in sorted(paths)},
        sort_keys=True).encode()).hexdigest()
    return {'table': demo.digest(demo.ENERGY_TABLE),
            'configs': [demo.digest(demo.CACHE_CONFIGS/f'production_cache_{a}.json') for a in ('a', 'b')],
            'code': demo.code_digest(), 'cachesim': demo.digest(demo.CACHESIM),
            'manifest': demo.digest(demo.MANIFEST), 'noc_source': _source_hash(),
            'eventsim': demo.digest(DEFAULT_EVENTSIM), 'source_tree': source_hash}


def expected_fingerprint(case, inputs):
    source = demo.TRACE_ROOT/case['trace_relative_dir']/(case['layer']+'.npy')
    stat = source.stat()
    return {**{key: inputs[key] for key in ('table', 'configs', 'code', 'cachesim')},
            'schedule': demo.digest(demo.MANIFEST.parent/case['schedule_path']),
            'capture_size': stat.st_size, 'capture_mtime': stat.st_mtime_ns, 'sample': 0}


def durable_hashes(folder):
    return {str(p.relative_to(folder)): demo.digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.name not in ('receipt.json', 'case.lock', '.lock', 'worker.log')
            and p.suffix not in ('.part', '.wcts')}


def validate_case(case, folder, inputs, receipt=True):
    if receipt:
        saved_inputs = json.loads((folder/'receipt.json').read_text())['inputs']
        if saved_inputs != inputs:
            raise ValueError('receipt fingerprint differs from campaign inputs')
    result = json.loads((folder/'result.json').read_text())
    if result['fingerprint'] != expected_fingerprint(case, inputs):
        raise ValueError('case fingerprint differs from current table/config/native/source/schedule/input metadata')
    rows = result['rows']
    if len(rows) != 3 or {r['arm'] for r in rows} != set(ARMS):
        raise ValueError('expected exactly three arms')
    generation = json.loads((folder/'generation.json').read_text())
    noc = json.loads((folder/'noc/result.json').read_text())
    ni = noc['inputs']
    if ni['source_sha256'] != inputs['noc_source'] or ni['eventsim']['sha256'] != inputs['eventsim']:
        raise ValueError('NoC source/native fingerprint mismatch')
    if ni['arch_config']['sha256'] != demo.digest(ni['arch_config']['path']):
        raise ValueError('NoC architecture config fingerprint mismatch')
    if ni['schedule']['sha256'] != result['fingerprint']['schedule']:
        raise ValueError('NoC schedule differs')
    if noc['tc_sha256'] != demo.digest(folder/'noc/tc.csv'):
        raise ValueError('NoC traffic digest mismatch')
    if generation['schedule_sha256'] != result['fingerprint']['schedule'] or ni['sample']['sha256'] != generation['sha256']:
        raise ValueError('generation / NoC provenance mismatch')
    for row in rows:
        if (row['arch'], row['capture'], row['layer'], row['sample']) != (
                case['arch'], case['trace_relative_dir'], case['layer'], 0):
            raise ValueError('row identity mismatch')
        if row['energy_table_sha256'] != inputs['table'] or row['trace_sha256'] != generation['sha256']:
            raise ValueError('row digest mismatch')
        values = [float(row[k]) for k in ('T_s', 'E_dyn_nJ', 'E_leak_nJ', 'EDP_nJ_s')]
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('invalid metric')
        if not math.isclose(values[3], values[0]*(values[1]+values[2]), rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError('layer EDP disagrees with energy times latency')
    for arm in ('a', 'b'):
        with (folder/f'cache_{arm}.csv').open() as stream:
            if len(list(csv.DictReader(stream))) != 1:
                raise ValueError('cache CSV must have one row')
    if receipt:
        saved = json.loads((folder/'receipt.json').read_text())
        if saved['inputs'] != inputs or saved['files'] != durable_hashes(folder):
            raise ValueError('receipt fingerprint or durable artifact digest mismatch')
    return rows


def write_receipt(folder, inputs, provenance):
    provenance = {**provenance, 'configuration_snapshots': {
        arm: {'path': str(demo.CACHE_CONFIGS/f'production_cache_{arm}.json'), 'sha256': inputs['configs'][i]}
        for i, arm in enumerate(('a', 'b'))}}
    demo.save(folder/'receipt.json', {'inputs': inputs, 'files': durable_hashes(folder),
                                     'provenance': provenance})


def memory_state():
    mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    available = int(mem['MemAvailable'].split()[0])*1024
    limits = []
    cg = Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().split('::', 1)[1].strip().lstrip('/')
    for path in (cg, *cg.parents):
        if path == Path('/sys/fs'):
            break
        if not (path/'memory.max').exists():
            continue
        maximum = (path/'memory.max').read_text().strip()
        used = int((path/'memory.current').read_text())
        pidmax = (path/'pids.max').read_text().strip() if (path/'pids.max').exists() else 'max'
        pids = int((path/'pids.current').read_text()) if (path/'pids.current').exists() else 0
        limits.append({'path': str(path), 'memory_max': maximum, 'memory_current': used,
                       'pids_max': pidmax, 'pids_current': pids})
        if maximum != 'max':
            available = min(available, max(0, int(maximum)-used))
    return {'host_available_gib': int(mem['MemAvailable'].split()[0])/1024**2,
            'effective_available_gib': available/GIB, 'cgroups': limits}


def write_csv(path, rows, fields=None):
    fields = fields or sorted({k for row in rows for k in row})
    temporary = path.with_suffix(path.suffix+'.part')
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
