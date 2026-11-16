import csv
import importlib.util
import json
from pathlib import Path
import sys
import pytest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import full500 as f


def product(root,sample=7):
    out=root/'priced'/f'sample_{sample:03d}'
    f.SAVE(out/'coverage.json',{'report_complete':True,'completed_cases':559,'errors':{},'energy_table_sha256':f.TABLE_SHA})
    f.SAVE(out/'immutability.json',{'unchanged':True})
    rows=[dict(arch='spinalflow',capture='b',layer=str(i),arm=arm,sample=sample,energy_table_sha256=f.TABLE_SHA,
               E_dyn_nJ=2,E_leak_nJ=1,T_s=4,EDP_nJ_s=12) for i in range(559) for arm in ('spad','cacheA','cacheB')]
    with (out/'results_ng45.csv').open('w') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return out


def test_product_rejects_wrong_sample_missing_rows_and_bad_edp(tmp_path):
    out=product(tmp_path)
    assert f.verify_product(out,7)==1677
    with pytest.raises(ValueError,match='sample/table'): f.verify_product(out,6)
    p=out/'results_ng45.csv'; original=p.read_text()
    p.write_text(original.replace(',12\n',',13\n',1))
    with pytest.raises(ValueError,match='EDP'): f.verify_product(out,7)
    p.write_text('\n'.join(original.splitlines()[:-1])+'\n')
    with pytest.raises(ValueError,match='coverage'): f.verify_product(out,7)


def test_corrupted_commit_never_retires(tmp_path):
    stage=tmp_path/'work/sample_007';stage.mkdir(parents=True)
    (stage/'precious').write_text('counts')
    final=tmp_path/'rows/sample_007'
    f.SAVE(final/'commit.json',{'artifacts':{'results.csv':'wrong'}})
    (final/'results.csv').write_text('changed')
    with pytest.raises(ValueError,match='corrupted'):f.commit_sample(tmp_path,7,{'jobs':[]})
    assert (stage/'precious').exists()


def test_verified_commit_retires_only_its_sample_and_is_restartable(tmp_path):
    final=tmp_path/'rows/sample_007';final.mkdir(parents=True)
    (final/'results_ng45.csv').write_text('durable rows')
    f.SAVE(final/'commit.json',{'artifacts':{'results_ng45.csv':f.HASH(final/'results_ng45.csv')}})
    for parent in ('work','scratch','priced'):
        for sample in (7,8):
            p=tmp_path/parent/f'sample_{sample:03d}';p.mkdir(parents=True);(p/'x').write_text('data')
    state={'jobs':[]};f.commit_sample(tmp_path,7,state)
    assert state['phase']=='done'
    for parent in ('work','scratch','priced'):
        assert not (tmp_path/parent/'sample_007').exists()
        assert (tmp_path/parent/'sample_008/x').exists()
    f.commit_sample(tmp_path,7,state)


def test_boundary_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):f.boundary(tmp_path)
    for value in (-2,500,'499',True):
        f.SAVE(tmp_path/'boundary.json',{'max_sample':value})
        with pytest.raises(ValueError):f.boundary(tmp_path)
    f.SAVE(tmp_path/'boundary.json',{'max_sample':9}); assert f.boundary(tmp_path)==9


def test_only_exact_approved_failure_is_quarantined(tmp_path):
    failure = {'case': 'gustavsnn/example/layer03', 'attempt': 1, 'status': 'oom', 'memory_gib': 120}
    state = {'phase': 'counting', 'jobs': [], 'pending': [], 'failures': {'2': failure}}
    evidence = tmp_path/'work/sample_005/cases/failed/attempt_1.json'
    f.SAVE(evidence, failure)
    before = evidence.read_bytes()
    with pytest.raises(RuntimeError, match='terminal failures'):
        f.progress(tmp_path, 5, state, {}, [], None)
    state['quarantined_failures'] = {'2': {**failure, 'memory_gib': 64}}
    with pytest.raises(RuntimeError, match='terminal failures'):
        f.progress(tmp_path, 5, state, {}, [], None)
    state['quarantined_failures'] = {'2': dict(failure)}
    f.progress(tmp_path, 5, state, {}, [], None)
    assert state['phase'] == 'quarantined'
    f.progress(tmp_path, 5, state, {}, [], None)
    assert evidence.read_bytes() == before
    assert not (tmp_path/'rows/sample_005').exists()
    assert not (tmp_path/'priced/sample_005').exists()


@pytest.mark.parametrize('arch', ['spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity'])
@pytest.mark.parametrize('status', ['oom', 'timeout'])
def test_heavy_signature_quarantines_without_retry(tmp_path, arch, status):
    failure = {'case': f'{arch}/C01/sma_azo_vgg_dvs128_gesture_T16_n500/layer_03_core_block4_0_0',
               'status': status, 'tier': 2, 'memory_gib': 120, 'timeout_seconds': 3600, 'retry': None}
    state = {'phase': 'counting', 'pending': [], 'jobs': [], 'failures': {'9': failure}}
    f.progress(tmp_path, 1, state, {}, [], None)
    assert state['phase'] == 'quarantined'
    assert state['quarantined_failures'] == {'9': failure}
    assert state['pending'] == []
    assert not (tmp_path/'priced').exists()


@pytest.mark.parametrize('change', [
    {'case': 'spinalflow/A08/vgg/layer03'}, {'memory_gib': 64}, {'tier': 1},
    {'status': 'failed'}, {'status': 'killed_or_oom'}, {'timeout_seconds': 2700},
    {'retry': {'attempt': 1}},
])
def test_other_failure_signatures_still_stop(tmp_path, change):
    failure = {'case': 'spinalflow/C01/sma_azo_vgg_dvs128_gesture_T16_n500/layer_03_core_block4_0_0',
               'status': 'timeout', 'tier': 2, 'memory_gib': 120, 'timeout_seconds': 3600, 'retry': None,
               **change}
    state = {'phase': 'counting', 'pending': [], 'jobs': [], 'failures': {'9': failure}}
    with pytest.raises(RuntimeError, match='terminal failures'):
        f.progress(tmp_path, 1, state, {}, [], None)


def test_real_array_accounting_uses_array_identity_not_raw_job_number(monkeypatch):
    def sacct(argv):
        assert argv[-1] == 'JobID,State,ExitCode,Elapsed,MaxRSS'
        return '1139095_0|COMPLETED|0:0|00:01:00|\n1139095_0.batch|COMPLETED|0:0|00:01:00|5K\n1139095_1|OUT_OF_MEMORY|0:125|00:00:20|'
    monkeypatch.setattr(f,'run',sacct)
    rows=f.accounting({'id':'1139095','indices':[0,1]})
    assert set(rows)=={0,1}
    assert rows[1]['state']=='OUT_OF_MEMORY'
    assert f.accounting({'id':'1139095','indices':[0,1,2]}) is None
