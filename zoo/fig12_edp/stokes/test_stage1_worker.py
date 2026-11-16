"""Count-only worker contracts; campaign simulation is replaced by saved measurements."""
import ast
import builtins
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO/'src'), str(REPO/'zoo/fig12_edp'),
               str(REPO/'zoo/fig12_edp/counts'), str(REPO/'zoo/archx/zoo')]
spec = importlib.util.spec_from_file_location('stage1_worker', HERE/'stage1_worker.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def entry(memory=0, giant=False):
    return {'key': 'spinalflow/capture/layer', 'record_memory_proxy_gib': memory,
            'tier': 'historical_oom' if giant else 'regular'}


@pytest.mark.parametrize('proxy,giant,memory,minutes', [(0,False,16,25), (16,False,16,25),
    (16.01,False,64,45), (100,True,120,60)])
def test_tiers(proxy, giant, memory, minutes):
    assert w.resources(entry(proxy, giant), 0)['memory_gib'] == memory
    assert w.resources(entry(proxy, giant), 0)['timeout_seconds'] == minutes*60


@pytest.mark.parametrize('outcome', ['oom', 'timeout', 'killed_or_oom'])
def test_exactly_one_next_tier_retry(outcome):
    first = w.failure_status(outcome, entry(), 0)
    assert first['retry'] == {'attempt': 1, 'tier': 1, 'memory_gib': 64, 'timeout_seconds': 2700}
    assert w.failure_status(outcome, entry(), 1)['retry'] is None
    assert w.failure_status(outcome, entry(100, True), 0)['retry'] is None
    assert w.failure_status(outcome, entry(17), 0)['retry']['memory_gib'] == 120
    with pytest.raises(ValueError): w.resources(entry(), 2)
    with pytest.raises(ValueError): w.resources(entry(100, True), 1)
    assert w.failure_status('failed', entry(), 0)['retry'] is None


def test_full_559_scope_and_explicit_mini(tmp_path):
    from demo.all_bench.layer_scope import kept
    manifest = REPO/'zoo/wt500_fig3cfg/outputs/manifest.json'
    rows = w.load(manifest)['schedules']
    selected = [{'key': w.identity(c), 'record_memory_proxy_gib': 0} for c in rows
                if kept(c['layer']) and c['solver_status'] != 'INFEASIBLE']
    assert len(selected) == 559
    assert sum(kept(c['layer']) and c['solver_status'] == 'INFEASIBLE' for c in rows) == 6
    path = tmp_path/'selection.json'
    cfg = {'schedule_manifest': manifest, 'selection': path}
    w.save(path, {'cases': selected})
    assert len(w.selection(cfg)) == 559
    w.save(path, {'cases': selected[:-1]})
    with pytest.raises(ValueError, match='559'): w.selection(cfg)
    w.save(path, {'mini': True, 'cases': selected[:1]})
    assert len(w.selection(cfg)) == 1
    w.save(path, {'mini': True, 'cases': selected[:1]*2})
    with pytest.raises(ValueError, match='duplicate'): w.selection(cfg)


def test_no_pricing_entrypoint_or_table_in_worker():
    tree = ast.parse((HERE/'stage1_worker.py').read_text())
    calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
             for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, (ast.Name, ast.Attribute))}
    assert 'count' in calls
    assert not calls.intersection({'price', 'archx_aggregate_case', 'code_digest', 'current_inputs'})
    assert 'energy_table' not in (HERE/'stage1_worker.py').read_text()
    assert not any(isinstance(n, ast.ImportFrom) and n.module and
                   ('pricing' in n.module or n.module in ('demo.run', 'common')) for n in ast.walk(tree))


@pytest.fixture
def pipeline_fixture(tmp_path, monkeypatch, request):
    from snn_edp import model
    from nocsim import driver
    source = model.HERE/'fixtures/spinalflow'
    case = w.load(source/'case.json')
    cfg = {'repo': REPO, 'capture_root': tmp_path/'capture', 'schedule_cache': tmp_path/'schedules',
           'output_root': tmp_path/'durable', 'scratch_root': tmp_path/'scratch',
           'cachesim': tmp_path/'fake-cachesim', 'eventsim': tmp_path/'fake-eventsim',
           'cache_a': tmp_path/'a.json', 'cache_b': tmp_path/'b.json',
           'arch_yaml': {'spinalflow': tmp_path/'arch.yaml'}, 'sample': getattr(request, 'param', 0)}
    for name in ('cache_a', 'cache_b'): cfg[name].write_text('{}')
    before = {str(p): w.digest(p) for p in source.rglob('*') if p.is_file()}
    monkeypatch.setattr(w, 'inputs', lambda cfg, case: {'sample':cfg['sample'], 'case':case,
        'configs':[w.digest(cfg['cache_a']), w.digest(cfg['cache_b'])]})
    monkeypatch.setattr(w, 'input_files', lambda cfg, case: ({'schedule':tmp_path/'schedule.json'}, 'unused'))
    monkeypatch.setattr(w, 'count_sample', lambda cfg, case, records: w.load(source/'counts.json'))
    commands = []
    def command(argv, log, stdout=None):
        commands.append(argv)
        if stdout is not None:
            assert argv[argv.index('--sample-start')+1] == str(cfg['sample'])
            assert argv[argv.index('--sample-count')+1] == '1'
            stdout.write(b'WCTRACE1'+struct.pack('<iQ', -1, 7))
        else:
            arm = 'a' if str(cfg['cache_a']) in argv else 'b'
            import csv
            with (source/f'cache_{arm}.csv').open() as stream: row, = list(csv.DictReader(stream))
            row['sample_idx'] = cfg['sample']
            with Path(argv[argv.index('--out')+1]).open('w') as stream:
                writer=csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
    monkeypatch.setattr(w, 'command', command)
    def noc(schedule, arch, trace, output, **kwargs):
        output.mkdir(parents=True, exist_ok=True)
        saved=w.load(source/'noc/result.json'); saved['sample_idx']=cfg['sample']; w.save(output/'result.json', saved)
        (output/'tc.csv').write_text('saved measurement fixture\n')
    monkeypatch.setattr(driver, 'run_case', noc)
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE', '1')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    monkeypatch.setenv('ARCHX_DISABLE_PERFORMANCE_CACHE', '1')
    for name, value in w.THREAD_ENV.items(): monkeypatch.setenv(name, value)
    yield cfg, case, commands
    assert before == {str(p): w.digest(p) for p in source.rglob('*') if p.is_file()}


@pytest.mark.parametrize('pipeline_fixture', [0, 7], indirect=True)
def test_real_count_checkpoint_resume_immutable_and_stale_rejection(pipeline_fixture, monkeypatch):
    cfg, case, commands = pipeline_fixture
    from snn_edp import run
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if 'energy_table' in path.name or path.name == 'pricing.py':
            raise AssertionError('Stage 1 accessed pricing input')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.endswith('pricing') or name == 'gurobipy':
            raise AssertionError('Stage 1 imported pricing/solver')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    assert w.pipeline(cfg, case) == 'complete'
    base, scratch = w.paths(cfg, case)
    assert not (scratch/(scratch.name+'.wcts')).exists()
    assert len(commands) == 3
    manifest = w.load(base/'counts/manifest.json')
    assert set(manifest['graphs']) == {'spad', 'cacheA', 'cacheB'}
    assert 'energy_table' not in json.dumps(manifest['fingerprint'])
    before = {str(p): (w.digest(p), p.stat().st_mtime_ns) for p in base.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs): raise AssertionError('complete case recomputed')
    monkeypatch.setattr(w, 'command', forbidden)
    monkeypatch.setattr(run, 'count', forbidden)
    # Simulates a crash after durable complete commit but before trace cleanup.
    (scratch/(scratch.name+'.wcts')).write_bytes(b'leftover')
    assert w.pipeline(cfg, case) == 'resumed'
    assert not (scratch/(scratch.name+'.wcts')).exists()
    assert before == {str(p): (w.digest(p), p.stat().st_mtime_ns) for p in base.rglob('*') if p.is_file()}
    cfg['cache_b'].write_text('{"different":true}')
    with pytest.raises(ValueError, match='inputs changed'): w.pipeline(cfg, case)


def test_failure_preserves_trace_and_durable_stages(pipeline_fixture, monkeypatch):
    cfg, case, commands = pipeline_fixture
    from snn_edp import run
    def fail(*args, **kwargs): raise MemoryError('test resource exhaustion')
    monkeypatch.setattr(run, 'count', fail)
    with pytest.raises(MemoryError): w.pipeline(cfg, case)
    base, scratch = w.paths(cfg, case)
    assert (scratch/(scratch.name+'.wcts')).exists()
    assert not (base/'complete.json').exists()
    assert w.valid_step(base, 'noc')
    before = len(commands)
    with pytest.raises(MemoryError): w.pipeline(cfg, case)
    assert len(commands) == before
    (base/'case/cache_a.csv').write_text('corrupt')
    with pytest.raises(ValueError, match='artifact changed'): w.pipeline(cfg, case)


def test_inherited_four_gib_hard_cap_reported_without_spawn(tmp_path, monkeypatch):
    case = {'arch':'spinalflow', 'trace_relative_dir':'capture', 'layer':'layer'}
    cfg = {'output_root':tmp_path/'out', 'scratch_root':tmp_path/'scratch'}
    monkeypatch.setattr(w, 'inputs', lambda *args: {})
    monkeypatch.setattr(w.resource, 'getrlimit', lambda kind: (4*w.GIB, 4*w.GIB))
    def forbidden(*args, **kwargs): raise AssertionError('spawn under inadequate hard cap')
    monkeypatch.setattr(w.subprocess, 'Popen', forbidden)
    result = w.supervise(tmp_path/'config', cfg, case, entry(), 0, 0)
    assert result['status'] == 'resource_unavailable'
    assert result['actual_limits']['rlimit_as_hard_bytes'] == 4*w.GIB
    assert result['retry'] is None


def test_timeout_cancels_only_owned_session_and_records_retry(tmp_path, monkeypatch):
    cfg = {'output_root':tmp_path/'out', 'scratch_root':tmp_path/'scratch'}
    case = {'arch':'spinalflow', 'trace_relative_dir':'capture', 'layer':'layer'}
    monkeypatch.setattr(w, 'inputs', lambda *args: {})
    monkeypatch.setattr(w, 'actual_limits', lambda: {'rlimit_as_hard_bytes': None})
    killed = []
    class Process:
        pid = 987654321
        def wait(self, timeout=None):
            if timeout == 1470: raise subprocess.TimeoutExpired('test', timeout)
            return -15
    def popen(*args, **kwargs):
        assert kwargs['start_new_session'] is True
        return Process()
    monkeypatch.setattr(w.subprocess, 'Popen', popen)
    monkeypatch.setattr(w.os, 'killpg', lambda pid, sig: killed.append(pid))
    result = w.supervise(tmp_path/'config', cfg, case, entry(), 0, 0)
    assert result['status'] == 'timeout'
    assert result['shutdown_reserve_seconds'] == 30
    assert result['retry']['memory_gib'] == 64
    assert killed and set(killed) == {Process.pid}
    with pytest.raises(ValueError, match='already used'):
        w.supervise(tmp_path/'config', cfg, case, entry(), 0, 0)


def test_count_sample_uses_sample_zero_and_following_density(tmp_path, monkeypatch):
    import numpy as np
    case = {'arch':'spinalflow', 'trace_relative_dir':'capture', 'layer':'conv1'}
    directory = tmp_path/'capture'; directory.mkdir()
    w.save(directory/'meta.json', {'layers':['conv1','conv2'],
        'layer_params':{'conv1':{'cout':4,'kernel':1,'stride':1}}})
    source = np.zeros((2,2,1,2,2), dtype=np.uint8)
    source[:,0] = 1
    following = np.zeros_like(source)
    following[0,0] = 1
    np.save(directory/'conv1.npy', source); np.save(directory/'conv2.npy', following)
    monkeypatch.setattr(w, 'input_files', lambda cfg, case:
        ({'capture':directory/'conv1.npy','density_capture':directory/'conv2.npy'}, 'conv2'))
    result = w.count_sample({'capture_root':tmp_path}, case, 7)
    assert result['S_win'] == 8
    assert result['d_out'] == 0.5
    assert result['L'] == 32
    assert result['O'] == 16
    assert result['density_layer'] == 'conv2'


def test_native_subprocess_sigkill_is_retryable(tmp_path, monkeypatch):
    case = {'arch':'spinalflow', 'trace_relative_dir':'capture', 'layer':'layer'}
    cfg = {'output_root':tmp_path/'out', 'scratch_root':tmp_path/'scratch'}
    monkeypatch.setattr(sys, 'argv', ['stage1_worker', '--config', str(tmp_path/'config'),
                                    '--case-index', '0', '--execute'])
    monkeypatch.setattr(w, 'configure', lambda path: cfg)
    monkeypatch.setattr(w, 'selection', lambda cfg: [(case, entry())])
    monkeypatch.setattr(w.resource, 'setrlimit', lambda *args: None)
    def killed(*args): raise subprocess.CalledProcessError(-9, ['native-test'])
    monkeypatch.setattr(w, 'pipeline', killed)
    assert w.main() == 44
    assert w.failure_status('killed_or_oom', entry(), 0)['retry']['memory_gib'] == 64
