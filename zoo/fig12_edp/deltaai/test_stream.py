import importlib.util
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location('arm_stream', Path(__file__).with_name('stream.py'))
stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream)


def test_scheduler_pending_reason_parentheses(monkeypatch):
    monkeypatch.setattr(stream, 'run', lambda _: '3608019_0|PENDING|(JobHeldUser)\n3608019_1|RUNNING|gh001')
    assert stream.queue() == {'3608019_0':['PENDING','JobHeldUser'],
                              '3608019_1':['RUNNING','gh001']}


def test_candidates_exclude_running_and_handed_samples():
    catalog = {'arrays':[{'job':'100','samples':[489,488,487,486]}]}
    jobs = {'100_0':['RUNNING','node'], '100_1':['PENDING','Priority'],
            '100_2':['PENDING','Priority'], '100_3':['PENDING','Priority']}
    assert stream.candidates(catalog, jobs, {'handed_to_batch':[488]}) == [(487,'100_2'),(486,'100_3')]


def test_unknown_failure_stops_without_releasing_or_resubmitting(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, 'ROOT', tmp_path)
    monkeypatch.setattr(stream, 'queue', lambda:{})
    monkeypatch.setattr(stream, 'finished', lambda _: {'state':'FAILED','start':'now','elapsed_seconds':10})
    monkeypatch.setattr(stream, 'run', lambda _:pytest.fail('unexpected scheduler mutation'))
    state={'active':{'job':'101','sample':489,'batch_task':'100_0'}}
    with pytest.raises(RuntimeError, match='requires diagnosis'):
        stream.step(state)


@pytest.mark.parametrize('phase', ['counts_ready', 'counts_partial', 'quarantined'])
def test_counts_ready_releases_batch_only_for_pricing(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(stream, 'ROOT', tmp_path)
    monkeypatch.setattr(stream, 'queue', lambda:{'100_0':['PENDING','JobHeldUser']})
    monkeypatch.setattr(stream, 'finished', lambda _: {'state':'COMPLETED','start':'now','elapsed_seconds':20})
    (tmp_path/'sample_489_status.json').write_text(json.dumps({'phase':phase}))
    (tmp_path/'budget.json').write_text(json.dumps({'charged_or_reserved_hours':240,'cap_gh200_hours':240}))
    calls=[]
    monkeypatch.setattr(stream, 'run', lambda args:calls.append(args) or '')
    state={'active':{'job':'101','sample':489,'batch_task':'100_0'},
           'selected':{'sample':489,'batch_task':'100_0'}}
    stream.step(state)
    assert calls[0] == ['scontrol','release','100_0']
    assert not any(c[0]=='sbatch' for c in calls)
    assert state['handed_to_batch']==[489] and state['phase']=='budget_hold'


def test_paused_chunk_resubmits_same_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, 'ROOT', tmp_path)
    monkeypatch.setattr(stream, 'queue', lambda:{'100_0':['PENDING','JobHeldUser']})
    monkeypatch.setattr(stream, 'finished', lambda _: {'state':'COMPLETED','start':'now','elapsed_seconds':6300})
    (tmp_path/'sample_489_status.json').write_text(json.dumps({'phase':'paused'}))
    (tmp_path/'environment_ready.json').write_text('{}')
    (tmp_path/'budget.json').write_text(json.dumps({'charged_or_reserved_hours':14,'cap_gh200_hours':240}))
    calls=[]
    monkeypatch.setattr(stream, 'run', lambda args:calls.append(args) or ('102' if args[0]=='sbatch' else ''))
    state={'active':{'job':'101','sample':489,'batch_task':'100_0'},
           'selected':{'sample':489,'batch_task':'100_0'}}
    stream.step(state)
    assert state['active']['job']=='102' and state['active']['sample']==489
    assert calls[-1][-1]=='489'
    assert not any(c[0] in ('scontrol','scancel') for c in calls)


def test_hold_precedes_submission_and_running_chunk_does_not_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, 'ROOT', tmp_path)
    jobs={'100_0':['PENDING','Priority']}
    monkeypatch.setattr(stream, 'queue', lambda:dict(jobs))
    (tmp_path/'environment_ready.json').write_text('{}')
    (tmp_path/'budget.json').write_text(json.dumps({'charged_or_reserved_hours':0,'cap_gh200_hours':240}))
    (tmp_path/'array_catalog.json').write_text(json.dumps({'arrays':[{'job':'100','samples':[489]}]}))
    calls=[]
    def run(args):
        calls.append(args)
        if args[:2]==['scontrol','hold']:
            jobs['100_0']=['PENDING','JobHeldUser']
        return '101' if args[0]=='sbatch' else ''
    monkeypatch.setattr(stream, 'run', run)
    state={}
    stream.step(state)
    hold=next(i for i,c in enumerate(calls) if c[0]=='scontrol')
    submit=next(i for i,c in enumerate(calls) if c[0]=='sbatch')
    assert hold < submit
    jobs['101']=['RUNNING','node']
    monkeypatch.setattr(stream, 'finished', lambda _: {'state':'RUNNING','start':'now','elapsed_seconds':5})
    stream.step(state)
    assert sum(c[0]=='sbatch' for c in calls)==1
    assert state['active']['start']=='now'


def test_quarter_winner_keeps_full_job_pending_without_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, 'ROOT', tmp_path)
    folder=tmp_path/'interactive_outcomes';folder.mkdir()
    (folder/'quarter.json').write_text(json.dumps({'status':'owns_lane'}))
    full={'job':'full','sample':489,'batch_task':'100_0'}
    quarter={'job':'quarter','sample':489,'batch_task':'100_0'}
    state={'selected':{'sample':489},'active':full,'standby':[quarter]}
    stream.reconcile_contenders(state, {'full':['PENDING','Priority'],'quarter':['RUNNING','node']})
    assert state['active']==quarter and state['standby']==[full]
    (folder/'full.json').write_text(json.dumps({'status':'lost_race'}))
    monkeypatch.setattr(stream,'finished',lambda _: {'state':'COMPLETED','elapsed_seconds':2})
    stream.reconcile_contenders(state, {'quarter':['RUNNING','node']})
    assert state['active']==quarter and state['standby']==[]
    assert state['history'][0]['disposition']=='lost_race'


def test_handoff_waits_for_the_other_running_interactive_job(tmp_path, monkeypatch):
    monkeypatch.setattr(stream,'ROOT',tmp_path)
    monkeypatch.setattr(stream,'run',lambda _:pytest.fail('must not release while interactive owner exists'))
    with (tmp_path/'interactive_lane.lock').open('a') as lock:
        stream.fcntl.flock(lock, stream.fcntl.LOCK_EX|stream.fcntl.LOCK_NB)
        state={}
        assert not stream.hand_back(state, {'sample':489,'batch_task':'100_0'})
        assert not state.get('handed_to_batch')


def test_handback_resume_does_not_release_running_array_task(tmp_path, monkeypatch):
    monkeypatch.setattr(stream,'ROOT',tmp_path)
    monkeypatch.setattr(stream,'queue',lambda:{'100_0':['RUNNING','node']})
    monkeypatch.setattr(stream,'run',lambda _:pytest.fail('running task must not be released again'))
    state={'handed_to_batch':[489]}
    assert stream.hand_back(state, {'sample':489,'batch_task':'100_0'})
    assert state['handed_to_batch']==[489]


def test_pending_forecast_and_reassessment_are_observation_only(tmp_path, monkeypatch):
    monkeypatch.setattr(stream,'ROOT',tmp_path)
    monkeypatch.setattr(stream,'queue',lambda:{'101':['PENDING','Priority']})
    calls=[]
    monkeypatch.setattr(stream,'run',lambda args:calls.append(args) or '2026-11-15T23:15:00')
    (tmp_path/'resize_101.json').write_text(json.dumps({'reassess_after_unix':0}))
    state={'active':{'job':'101','sample':489,'batch_task':'100_0'}}
    stream.step(state);stream.step(state)
    assert len(state['start_forecasts'])==1
    assert state['reassessment']['job']=='101'
    assert all(c[0]=='squeue' for c in calls)
