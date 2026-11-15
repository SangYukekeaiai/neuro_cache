"""Sample-0 three-arm demo; durable per-case results and bounded worker processes."""
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from energy_driver import CACHE_CONFIGS, ENERGY_TABLE, scientific_files, archx_aggregate_case, check_cache_configs
MANIFEST = ROOT / 'zoo/wt500_fig3cfg/outputs/manifest.json'
CACHESIM = HERE / 'native_build/cachesim_run'
TRACE_ROOT = Path('/work/nvme/bebv/yyu9/input_trace_delta')
ARCHES = ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity')
THREAD_ENV = {key: '1' for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'RAYON_NUM_THREADS')}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_cachesim_fresh(binary, native_root):
    """Reject an executable older than its native source/header inputs."""
    sources=[p for folder in ('include','src','apps') for p in (native_root/folder).rglob('*')
             if p.is_file()]
    newest=max(sources,key=lambda p:p.stat().st_mtime_ns)
    if binary.stat().st_mtime_ns < newest.stat().st_mtime_ns:
        raise RuntimeError(f'stale cachesim binary: {binary}; rebuild after {newest}')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.part')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def select_cases(smoke=False):
    rows = json.loads(MANIFEST.read_text())['schedules']
    feasible = [r for r in rows if r['solver_status'] != 'INFEASIBLE']
    shards=json.loads((ROOT/'zoo/wt500_fig3cfg/stokes/shards/shards.json').read_text())
    estimates={(r['arch'],r['benchmark'],r['layer']):r['estimated_records_per_sample']
               for shard in shards['shards'] for r in shard['pairs']}
    for r in feasible:
        records=estimates.get((r['arch'],r['trace_dir'],r['layer']),0)
        size=(TRACE_ROOT/r['trace_relative_dir']/(r['layer']+'.npy')).stat().st_size
        r['estimated_memory_gib']=(size+records*512)/1024**3+2
    if len(feasible) != 749:
        raise ValueError(f'expected749 feasible pairs, found{len(feasible)}')
    def volume(r):
        p = r['workload']['problem']
        return p['T'] * p['CIN'] * p['HO'] * p['WO'] * p['COUT']
    if smoke:
        sys.path.insert(0,str(HERE.parent))
        from demo.all_bench.layer_scope import kept
        feasible=[r for r in feasible if kept(r['layer'])]
        return [min((r for r in feasible if r['arch'] == arch), key=volume) for arch in ARCHES]
    return sorted(feasible, key=lambda r: (r['estimated_memory_gib'],volume(r)))


def folder_for(case, output):
    return output / 'cases' / case['arch'] / case['trace_relative_dir'] / case['layer'] / 'sample_00000'


def command(args, log, *, stdout=None, timeout=3600):
    with log.open('w') as stream:
        proc = subprocess.Popen(args, stdout=stdout or stream, stderr=stream,
                                env={**os.environ, **THREAD_ENV, 'PYTHONPATH': str(ROOT / 'src'),
                                     'PYTHONDONTWRITEBYTECODE': '1'}, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except BaseException:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            raise
    if code:
        raise subprocess.CalledProcessError(code, args)


def count_case(case, records):
    sys.path[:0] = [str(HERE.parent / 'counts'), str(ROOT / 'src')]
    import numpy as np
    directory = TRACE_ROOT / case['trace_relative_dir']
    meta = json.loads((directory / 'meta.json').read_text())
    layers = list(meta['layers']); position = layers.index(case['layer'])
    density_layer = layers[min(position + 1, len(layers)-1)]
    trace = np.load(directory / (case['layer']+'.npy'), mmap_mode='r')
    following = np.load(directory / (density_layer+'.npy'), mmap_mode='r')
    density = float(np.count_nonzero(following[:, 0]) / following[:, 0].size)
    params = meta['layer_params'][case['layer']]
    options = dict(cout=params['cout'], kernel=params['kernel'], stride=params['stride'])
    module = importlib.import_module(case['arch']+'_counts')
    if case['arch'] == 'prosperity':
        artifact = json.loads((MANIFEST.parent / case['schedule_path']).read_text())
        options.update(tile=module.schedule_tile(case, artifact), records=records,
                       records_source='exact_pipeline_csv', d_out=density)
    elif case['arch'] != 'spinalflow':
        options['d_out'] = density
    counts = module.count_sample(trace, 0, **options)
    if case['arch'] == 'spinalflow':
        counts.update(L=counts['O'], O=counts['O']*density, d_out=density)
    return {**counts, 'COUT': params['cout'], 'kernel': params['kernel'],
            'density_layer': density_layer,
            'O_source': 'final_layer_own_density_proxy' if density_layer == case['layer'] else 'next_layer_input_density'}


def run_case(case, output, memory_gib, energy_table=None):
    os.environ.update(THREAD_ENV)
    sys.path.insert(0,str(HERE.parent))
    from demo.all_bench.layer_scope import kept
    if not kept(case['layer']): raise ValueError('case outside kept workload scope')
    check_cachesim_fresh(CACHESIM, ROOT/'src/lays/cachesim/native')
    if memory_gib:
        limit = int(memory_gib * 1024**3)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    folder = folder_for(case, output); folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (folder / 'case.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (folder/'case.json').exists(): save(folder/'case.json', case)
        table = Path(energy_table) if energy_table is not None else ENERGY_TABLE
        source = TRACE_ROOT / case['trace_relative_dir'] / (case['layer']+'.npy')
        fingerprint = {'table': digest(table), 'schedule': digest(MANIFEST.parent / case['schedule_path']),
                       'configs': [digest(CACHE_CONFIGS / f'production_cache_{a}.json') for a in ('a','b')],
                       'capture_size': source.stat().st_size, 'capture_mtime': source.stat().st_mtime_ns,
                       'sample': 0, 'code': code_digest(), 'cachesim': digest(CACHESIM)}
        result = folder / 'result.json'
        if result.exists() and json.loads(result.read_text())['fingerprint'] == fingerprint:
            return {'status': 'resumed', 'folder': str(folder)}
        trace = folder / 'sample_00000.wcts'; generation = folder / 'generation.json'
        directory = TRACE_ROOT / case['trace_relative_dir']
        args = [sys.executable, '-m', 'lays.weight_trace_gen', 'gen', '--arch', case['arch'],
                '--trace-root', str(directory.parent), '--trace-dir', directory.name,
                '--layer', case['layer'], '--schedule-cache', str(MANIFEST.parent/'schedules'),
                '--stream', '--sample-start', '0', '--sample-count', '1', '--workers', '1']
        if not (trace.exists() and generation.exists()
                and 'generator_command' in json.loads(generation.read_text())):
            partial = trace.with_suffix('.part')
            with partial.open('wb') as sink:
                command(args, folder/'generation.log', stdout=sink)
                sink.flush(); os.fsync(sink.fileno())
            partial.replace(trace)
            with trace.open('rb') as stream:
                stream.seek(-12, 2); marker, records = struct.unpack('<iQ', stream.read())
            if marker != -1:
                raise ValueError('incomplete WCTS trailer')
            save(generation, {'sha256': digest(trace), 'records': records, 'sample': 0,
                              'schedule_sha256': fingerprint['schedule'],
                              'trace_path': str(trace.resolve()), 'capture_path': str(source.resolve()),
                              'generator_command': args, 'generator_cwd': str(Path.cwd()),
                              'schedule_path': str((MANIFEST.parent/case['schedule_path']).resolve()),
                              'format': 'WCTS', 'retention': 'deleted only after durable result.json commit'})
        info = json.loads(generation.read_text())
        if info['sha256'] != digest(trace) or info['schedule_sha256'] != fingerprint['schedule']:
            raise ValueError('trace changed: cannot reuse generation')
        records_path = folder / 'record_count.csv'
        temporary = records_path.with_suffix('.part')
        with temporary.open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(['capture','layer','sample','R_p'])
            writer.writerow([case['trace_relative_dir'],case['layer'],0,info['records']])
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(records_path)
        counts = count_case(case, info['records']); save(folder/'counts.json', counts)
        caches = {}
        for arm in ('a','b'):
            path = folder / f'cache_{arm}.csv'
            command([str(CACHESIM), '--trace',str(trace),
                     '--config',str(CACHE_CONFIGS/f'production_cache_{arm}.json'), '--arm','cache','--header',
                     '--out',str(path)], folder/f'cache_{arm}.log')
            row, = list(csv.DictReader(path.open())); caches['cache'+arm.upper()] = row
        sys.path.insert(0,str(HERE.parent))
        from nocsim.driver import run_case as run_noc
        noc = run_noc(MANIFEST.parent/case['schedule_path'], case['arch'], trace, folder/'noc')
        rows = archx_aggregate_case(case['arch'], folder, table)
        for row in rows:
            row['input_count_provenance'] = {**row['input_count_provenance'], 'trace': dict(info)}
            row.update(arch=case['arch'], capture=case['trace_relative_dir'], layer=case['layer'], sample=0,
                       counts_json=json.dumps(counts,sort_keys=True), trace_sha256=info['sha256'])
            for key,value in counts.items():
                row['count_'+key]=value
        if any(row['energy_table_sha256'] != fingerprint['table'] for row in rows):
            raise ValueError('energy table changed during case; rerun for a consistent table hash')
        save(result, {'fingerprint': fingerprint, 'rows': rows, 'wall_seconds': time.monotonic()-started})
        trace.unlink()
        (folder/'failure.json').unlink(missing_ok=True)
        return {'status':'done','folder':str(folder),'wall_seconds':time.monotonic()-started}


def code_digest():
    paths=[Path(__file__), HERE.parent/'docs/workload_layer_scope.md']
    paths.extend([HERE.parent/'energy_driver.py', HERE/'all_bench/layer_scope.py'])
    for folder in ('counts','nocsim'):
        paths.extend(p for p in (HERE.parent/folder).glob('*.py') if not p.name.startswith('test_'))
    files = {str(p.relative_to(ROOT)): p for p in paths}
    files.update(scientific_files())
    return hashlib.sha256(json.dumps({name:digest(p) for name,p in sorted(files.items())},sort_keys=True).encode()).hexdigest()


def collect(output):
    with (output/'results.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = [r for path in sorted((output/'cases').glob('*/*/*/*/sample_00000/result.json'))
                for r in json.loads(path.read_text())['rows']]
        if not rows:
            return 0
        fields = sorted({k for row in rows for k in row})
        temporary = output/'results.csv.part'
        with temporary.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(output/'results.csv')
        return len(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--output',type=Path,default=HERE)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--shards',type=int,default=1)
    parser.add_argument('--memory-gib',type=float,default=0)
    parser.add_argument('--heavy-memory-gib',type=float,default=54)
    parser.add_argument('--case-json',type=Path)
    parser.add_argument('--energy-table',type=Path,default=ENERGY_TABLE)
    parser.add_argument('--collect-only',action='store_true')
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    os.environ.update(THREAD_ENV)
    if args.collect_only:
        print(collect(args.output)); return
    if args.case_json:
        print(json.dumps(run_case(json.loads(args.case_json.read_text()),args.output,args.memory_gib,args.energy_table))); return
    sys.path.insert(0,str(HERE.parent))
    from demo.all_bench.layer_scope import kept
    cases=[c for c in select_cases(args.smoke) if kept(c['layer'])][args.shard::args.shards]
    save(args.output/f'selection_{args.shard}.json',cases)
    def execute(case, forced_memory=None):
        memory=forced_memory if forced_memory is not None else (args.heavy_memory_gib if args.memory_gib and case['estimated_memory_gib']>args.memory_gib else args.memory_gib)
        folder=folder_for(case,args.output); folder.mkdir(parents=True,exist_ok=True)
        task=folder/'case.json'; save(task,case)
        try:
            command([sys.executable,str(Path(__file__).resolve()),'--case-json',str(task),
                     '--output',str(args.output),'--memory-gib',str(memory),'--energy-table',str(args.energy_table)],folder/'worker.log',timeout=7200)
            return {'status':'done','arch':case['arch'],'layer':case['layer']}
        except Exception as error:
            log=(folder/'worker.log').read_text(errors='replace')[-4000:]
            log += '\n'.join(p.read_text(errors='replace')[-2000:] for p in (folder/'generation.log',folder/'cache_a.log',folder/'cache_b.log') if p.exists())
            oom=isinstance(error,subprocess.CalledProcessError) and (error.returncode in (-9,137) or any(s in log for s in ('MemoryError','bad_alloc','cannot allocate memory','ArrayMemoryError','SIGKILL','bad allocation')))
            report={'status':'skipped_oom' if oom else 'failed','arch':case['arch'],'layer':case['layer'],
                    'error':str(error),'log_tail':log,'memory_limit_gib':memory}
            save(folder/'failure.json',report)
            return report
    small=[c for c in cases if not args.memory_gib or c['estimated_memory_gib']<=args.memory_gib]
    heavy=[c for c in cases if args.memory_gib and c['estimated_memory_gib']>args.memory_gib]
    for batch,workers in ((small,args.workers),(heavy,1)):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(execute,c):c for c in batch}
            retry=[]
            for future in concurrent.futures.as_completed(futures):
                result=future.result()
                print(json.dumps(result),flush=True); collect(args.output)
                if result['status']=='skipped_oom' and workers>1:
                    retry.append(futures[future])
                if args.smoke and result['status']!='done':
                    raise RuntimeError('smoke failed; full wave must not launch')
        for case in retry:
            result=execute(case,forced_memory=args.heavy_memory_gib)
            print(json.dumps(result),flush=True); collect(args.output)
    print(f'result_rows={collect(args.output)}',flush=True)


if __name__=='__main__':
    main()
