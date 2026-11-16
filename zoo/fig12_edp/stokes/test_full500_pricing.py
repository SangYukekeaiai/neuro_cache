import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import full500 as f


def setup(tmp_path, monkeypatch, records):
    state = {'phase': 'pricing', 'price_job': '123', 'jobs': []}
    monkeypatch.setattr(f, 'DRIVER', {'samples': {'22': state}}, raising=False)
    def run(argv):
        return '' if argv[0] == 'squeue' else records
    monkeypatch.setattr(f, 'run', run)
    output = tmp_path/'priced/sample_022'
    f.SAVE(output/'coverage.json', {'report_complete': False})
    counts = tmp_path/'work/sample_022/cases/case/counts.json'
    f.SAVE(counts, {'count': 7})
    return state, output, counts


@pytest.mark.parametrize('status,limit', [('COMPLETED',60), ('TIMEOUT',120)])
def test_missing_receipt_retries_once_preserves_evidence_and_counts(tmp_path, monkeypatch, status, limit):
    state, output, counts = setup(tmp_path, monkeypatch, f'123|{status}|0:0|\n123.extern|COMPLETED|0:0|')
    before = counts.read_bytes()
    f.progress(tmp_path, 22, state, {}, [], None)
    assert state['phase'] == 'ready_to_price' and state['price_time_minutes'] == limit
    assert len(state['price_receipt_retries']) == 1
    archive = Path(state['price_receipt_retries'][0]['archive'])
    assert f.LOAD(archive/'coverage.json') == {'report_complete':False}
    assert not output.exists() and counts.read_bytes() == before
    # Restart in the durable-credit / directory-rename gap must not consume a second retry.
    state['phase'] = 'pricing'
    f.progress(tmp_path, 22, state, {}, [], None)
    assert state['phase'] == 'ready_to_price' and len(state['price_receipt_retries']) == 1
    state.update(phase='pricing', price_job='124')
    monkeypatch.setattr(f, 'run', lambda argv: '' if argv[0]=='squeue' else f'124|{status}|0:0|')
    with pytest.raises(RuntimeError, match='retry ended'):
        f.progress(tmp_path, 22, state, {}, [], None)
    assert counts.read_bytes() == before


@pytest.mark.parametrize('records', ['123|RUNNING|0:0|\n123.extern|COMPLETED|0:0|',
                                   '123.extern|COMPLETED|0:0|', ''])
def test_child_completion_or_accounting_lag_does_not_requeue(tmp_path, monkeypatch, records):
    state, output, _ = setup(tmp_path, monkeypatch, records)
    f.progress(tmp_path,22,state,{},[],None)
    assert state['phase']=='pricing' and output.exists()
    assert not state.get('price_receipt_retries')


@pytest.mark.parametrize('record', ['FAILED|1:0', 'OUT_OF_MEMORY|0:125', 'CANCELLED|0:15', 'COMPLETED|1:0'])
def test_other_parent_failures_stop(tmp_path, monkeypatch, record):
    state, output, _ = setup(tmp_path, monkeypatch, '123|'+record+'|')
    with pytest.raises(RuntimeError, match='without durable'):
        f.progress(tmp_path,22,state,{},[],None)
    assert output.exists() and not state.get('price_receipt_retries')


def test_failure_receipt_never_uses_operational_retry(tmp_path, monkeypatch):
    state, output, _ = setup(tmp_path, monkeypatch, '123|COMPLETED|0:0|')
    f.SAVE(output/'price_exit.json', {'exit_code':1})
    with pytest.raises(RuntimeError, match='pricing failed'):
        f.progress(tmp_path,22,state,{},[],None)
    assert not state.get('price_receipt_retries')


def test_retry_submission_uses_extended_walltime(tmp_path, monkeypatch):
    state = {'phase':'ready_to_price', 'price_time_minutes':120}
    monkeypatch.setattr(f,'DRIVER',{'samples':{'22':state}},raising=False)
    commands=[]
    monkeypatch.setattr(f,'run',lambda argv: commands.append(argv) or '124')
    f.price_submit(tmp_path,22,state,'price.sbatch')
    assert '--time=120' in commands[0] and state['price_job']=='124'
    assert state['phase']=='pricing' and 'submission_intent' not in state


def test_expired_job_id_uses_user_queue_not_invalid_direct_lookup(tmp_path, monkeypatch):
    state, _, _ = setup(tmp_path, monkeypatch, '')
    def run(argv):
        if argv[0]=='squeue':
            assert '-j' not in argv and '-u' in argv
            return '1234'  # Another job is not this job.
        return '123|COMPLETED|0:0|'
    monkeypatch.setattr(f,'run',run)
    f.progress(tmp_path,22,state,{},[],None)
    assert state['phase']=='ready_to_price'
