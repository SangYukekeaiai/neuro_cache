import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full500 as f
import full500_batch as b


def test_batches_cover_cases_once_and_respect_tier_resources():
    assert b.groups(list(range(19)), 8) == [list(range(8)), list(range(8, 16)), [16, 17, 18]]
    assert b.MEMORY_GIB[0, 8] == 140
    assert b.MEMORY_GIB[1, 2] == 140
    assert b.MEMORY_GIB[2, 1] == 120
    assert [b.batch_width(0, delay) for delay in (0, 599, 600, 1200, 1800)] == [8, 8, 4, 2, 1]
    assert b.batch_width(1, 600) == b.batch_width(2, 0) == 1
    with pytest.raises(ValueError, match='duplicate'): b.groups([1, 1], 8)


def test_real_concurrent_children_keep_distinct_exit_codes(tmp_path):
    script = """import pathlib,sys,time
p=pathlib.Path(sys.argv[1]); (p/sys.argv[2]).touch()
deadline=time.monotonic()+5
while len(list(p.iterdir()))<3:
 if time.monotonic()>deadline: sys.exit(99)
 time.sleep(.01)
sys.exit(int(sys.argv[3]))
"""
    commands = {i: [sys.executable, '-B', '-c', script, str(tmp_path), str(i), str(code)]
                for i, code in enumerate((0, 75, 1))}
    assert b.run_commands(commands) == {0: 0, 1: 75, 2: 1}


def test_batch_accounting_expands_only_its_cases(monkeypatch):
    monkeypatch.setattr(f, 'run', lambda argv:
        '99_0|FAILED|1:0|00:01:00|\n99_1|COMPLETED|0:0|00:02:00|')
    result = f.accounting({'id': '99', 'indices': [4, 7, 9], 'batches': [[4, 7], [9]]})
    assert set(result) == {4, 7, 9}
    assert result[4]['batch_index'] == result[7]['batch_index'] == 0
    assert result[9]['state'] == 'COMPLETED'


def test_one_failed_case_does_not_retry_its_completed_batch_peer(tmp_path, monkeypatch):
    entries = [{'key': 'a', 'record_memory_proxy_gib': 1},
               {'key': 'b', 'record_memory_proxy_gib': 1}]
    cfg = tmp_path/'work/sample_001/config.json'
    out = tmp_path/'cases'
    f.SAVE(cfg, {'output_root': str(out)})
    f.SAVE(out/'a/sample_00001/complete.json', {'done': True})
    f.SAVE(out/'b/sample_00001/attempt_0.json', f.worker.failure_status('oom', entries[1], 0))
    job = {'id': '99', 'indices': [0, 1], 'batches': [[0, 1]], 'attempt': 0}
    state = {'phase': 'counting', 'jobs': [job], 'pending': []}
    monkeypatch.setattr(f, 'accounting', lambda job: {i: {'state': 'FAILED'} for i in (0, 1)})
    f.progress(tmp_path, 1, state, {}, entries, 'script')
    assert state['pending'] == [{'index': 1, 'attempt': 1, 'tier': 1}]
    f.progress(tmp_path, 1, state, {}, entries, 'script')
    assert len(state['pending']) == 1
    assert state['jobs'][0]['reconciled']


def test_hold_boundary_and_pipelined_sample_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(f, 'read_quota', lambda: {'capacity': 15})
    driver = {'samples': {'0': {'phase': 'done'}}, 'claimed_blocks': [0]}
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 499})
    f.admit_samples(tmp_path)
    assert list(driver['samples']) == ['0'] and driver['phase'] == 'held_after_sample000'
    f.SAVE(tmp_path/'release_after_sample000.json', {'approved': True})
    f.admit_samples(tmp_path)
    assert len(driver['samples']) == 16
    driver['samples']['1']['phase'] = 'pricing'
    f.admit_samples(tmp_path)
    assert len(driver['samples']) == 16
    driver['samples']['2']['phase'] = 'done'
    f.admit_samples(tmp_path)
    assert '16' in driver['samples']  # no wait for sample 1's pricing
    driver['samples'] = {'0': {'phase': 'done'}}
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 3})
    f.admit_samples(tmp_path)
    assert set(driver['samples']) == {'0', '1', '2', '3'}


def test_dispatch_reserves_job_slot_and_prices_without_sample_barrier(tmp_path, monkeypatch):
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 499})
    state = {'phase': 'counting', 'jobs': [],
             'pending': [{'index': i, 'attempt': 0, 'tier': 0} for i in range(30)]}
    driver = {'samples': {'1': {'phase': 'ready_to_price'}, '2': state}}
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    monkeypatch.setattr(f, 'queue_state', lambda: (246, 0))
    actions = []
    monkeypatch.setattr(f, 'price_submit', lambda *args: actions.append(('price', args[1])))
    monkeypatch.setattr(f, 'submit', lambda *args: actions.append(('compute', args[2], args[3], args[-1])))
    f.dispatch(tmp_path, 'worker', 'price')
    assert actions == [('price', 1), ('compute', 2, list(range(16)), 8)]
    actions.clear()
    monkeypatch.setattr(f, 'queue_state', lambda: (250, 0))
    f.dispatch(tmp_path, 'worker', 'price')
    assert not actions


def test_dispatch_shrinks_future_batches_and_rechecks_boundary(tmp_path, monkeypatch):
    state = {'phase': 'counting', 'jobs': [],
             'pending': [{'index': i, 'attempt': 0, 'tier': 0} for i in range(9)]}
    monkeypatch.setattr(f, 'DRIVER', {'samples': {'8': state}}, raising=False)
    monkeypatch.setattr(f, 'queue_state', lambda: (247, 601))
    actions = []
    monkeypatch.setattr(f, 'submit', lambda *args: actions.append((args[3], args[-1])))
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 8})
    f.dispatch(tmp_path, 'worker', 'price')
    assert actions == [(list(range(8)), 4)]
    actions.clear()
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 7})
    f.dispatch(tmp_path, 'worker', 'price')
    assert not actions


def test_queue_counts_expanded_elements_and_only_campaign_wait(monkeypatch):
    start = f.datetime.fromisoformat('2026-11-15T01:00:00').timestamp()
    monkeypatch.setattr(f.time, 'time', lambda: start+1201)
    def squeue(argv):
        assert '-r' in argv
        return ('12_0|RUNNING|2026-11-15T00:00:00|f500_s001_a0_t0_0\n'
                '12_1|PENDING|2026-11-15T01:00:00|f500_s001_a0_t0_0\n'
                '20|PENDING|2026-11-01T01:00:00|another_job')
    monkeypatch.setattr(f, 'run', squeue)
    assert f.queue_state() == (3, 1201)


def test_submit_manifest_and_intent_preserve_case_identity(tmp_path, monkeypatch):
    state = {'jobs': [], 'pending': [{'index': i, 'attempt': 0, 'tier': 0} for i in range(10)]}
    monkeypatch.setattr(f, 'DRIVER', {'samples': {'1': state}}, raising=False)
    commands = []
    def sbatch(argv):
        commands.append(argv)
        assert f.LOAD(tmp_path/'driver_status.json')['samples']['1']['submission_intent']
        return '123;cluster'
    monkeypatch.setattr(f, 'run', sbatch)
    cfg = tmp_path/'work/sample_001/config.json'
    f.submit(tmp_path, state, 1, list(range(9)), 0, 0, cfg, 'batch.sbatch', 8)
    assert '--cpus-per-task=8' in commands[0] and '--mem=140G' in commands[0]
    assert '--array=0-1' in commands[0]
    job = state['jobs'][0]
    assert job['batches'] == [list(range(8)), [8]]
    assert state['pending'] == [{'index': 9, 'attempt': 0, 'tier': 0}]
    assert 'submission_intent' not in state
    manifest = f.LOAD(Path(commands[0][-1]))
    assert manifest['batches'] == job['batches'] and manifest['attempt'] == 0


def test_numeric_sample_order_survives_sorted_json_reload(tmp_path, monkeypatch):
    samples = {str(i): {'phase': 'counting', 'jobs': [],
               'pending': [{'index': i, 'attempt': 0, 'tier': 0}]} for i in (1, 2, 10, 11)}
    driver = json.loads(json.dumps({'samples': samples}, sort_keys=True))
    assert list(driver['samples']) == ['1', '10', '11', '2']
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    monkeypatch.setattr(f, 'queue_state', lambda: (0, 0))
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 499})
    order = []
    monkeypatch.setattr(f, 'submit', lambda *args: order.append(args[2]))
    f.dispatch(tmp_path, 'worker', 'price')
    assert order == [1, 2, 10, 11]
    for state in driver['samples'].values(): state['phase'] = 'ready_to_price'
    order.clear()
    monkeypatch.setattr(f, 'price_submit', lambda *args: order.append(args[1]))
    f.dispatch(tmp_path, 'worker', 'price')
    assert order == [1, 2, 10, 11]
