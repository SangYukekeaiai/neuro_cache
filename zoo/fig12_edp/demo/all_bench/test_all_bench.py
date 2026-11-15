"""Small contract tests; no experiment campaign is launched."""
import json
import shutil
from pathlib import Path

import pytest

import common
import report
import run


def selection():
    cases = [{'arch': 'spinalflow', 'trace_relative_dir': 'example', 'layer': name} for name in ('a', 'b')]
    return {'captures': ['example'], 'feasible': cases, 'infeasible': []}


def rows():
    return [{'arch': 'spinalflow', 'capture': 'example', 'layer': layer, 'arm': arm,
             'E_dyn_nJ': e, 'E_leak_nJ': 0, 'T_s': t, 'EDP_nJ_s': e*t,
             'incomplete': True, 'energy_table_sha256': 'hash'}
            for layer, e, t in [('a', 2, 3), ('b', 5, 7)] for arm in common.ARMS]


def test_whole_model_edp_is_product_of_sums():
    result = report.whole_model(selection(), rows(), {})[0]
    assert result['sum_energy_nJ'] == 7
    assert result['sum_latency_s'] == 10
    assert result['model_EDP_nJ_s'] == 70
    assert result['sum_layer_EDP_nJ_s'] == 41
    assert result['coverage_complete']
    assert result['energy_incomplete'] and not result['comparable_complete']


def test_partial_oom_and_infeasible_totals_are_null():
    data = selection()
    states = {'spinalflow/example/b': 'skipped_oom'}
    result = report.whole_model(data, rows()[:3], states)[0]
    assert result['coverage'] == '1/2' and result['oom_layers'] == 1
    assert result['sum_energy_nJ'] is None and result['model_EDP_nJ_s'] is None
    assert result['partial_sum_energy_nJ'] == 2
    data['infeasible'] = [data['feasible'].pop()]
    result = report.whole_model(data, rows()[:3], {})[0]
    assert result['infeasible_layers'] == 1 and not result['coverage_complete']
    assert result['sum_layer_EDP_nJ_s'] is None


def test_duplicate_rows_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        report.whole_model(selection(), rows()+rows()[:1], {})


def fixture_case(tmp_path, monkeypatch):
    from receipt_fixture import make_receipt
    case,folder,inputs,original=make_receipt(tmp_path,common)
    monkeypatch.setattr(common,'expected_fingerprint',lambda case,values: {
        **original,**{k:values[k] for k in ('table','configs','code','cachesim')}})
    monkeypatch.setattr(run,'expected_fingerprint',common.expected_fingerprint)
    return case,folder,inputs


def test_artifact_tampering_and_source_snapshot_rejected(tmp_path,monkeypatch):
    case,target,inputs=fixture_case(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='receipt'):
        common.validate_case(case,target,{**inputs,'source_tree':'changed'})
    with (target/'cache_a.csv').open('a') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='digest'):
        common.validate_case(case,target,inputs)


def test_resume_after_join_before_receipt_does_not_recompute(tmp_path,monkeypatch):
    case,target,inputs=fixture_case(tmp_path,monkeypatch)
    (target/'receipt.json').unlink()
    common.demo.save(target/'stage_inputs.json',{'inputs':inputs,'case':common.expected_fingerprint(case,inputs)})
    monkeypatch.setattr(run,'HERE',tmp_path)
    def no_compute(*args,**kwargs):raise AssertionError('completed case launched a worker')
    monkeypatch.setattr(run.subprocess,'Popen',no_compute)
    assert run.execute(case,8,inputs)==('complete',0)
    assert len(common.validate_case(case,target,inputs))==3


def test_execution_gate(monkeypatch):
    monkeypatch.setattr('sys.argv', ['run.py', '--case-json', '/tmp/not-a-campaign-case.json'])
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2


def test_memory_reads_ancestor_limits():
    state = common.memory_state()
    assert state['effective_available_gib'] <= state['host_available_gib']
    assert any(c['pids_max'] == '1000' for c in state['cgroups'])


def test_oom_report_and_collection(tmp_path, monkeypatch):
    case,folder,inputs=fixture_case(tmp_path,monkeypatch)
    (folder/'result.json').unlink();(folder/'receipt.json').unlink()
    monkeypatch.setattr(run, 'HERE', tmp_path)
    monkeypatch.setattr(report, 'HERE', tmp_path)
    class KilledWorker:
        def poll(self):
            return -9
        def wait(self):
            return -9
    monkeypatch.setattr(run.subprocess, 'Popen', lambda *a, **kw: KilledWorker())
    state, seconds = run.execute(case, 8, inputs)
    assert state == 'skipped_oom' and seconds >= 0
    folder = common.demo.folder_for(case, tmp_path)
    assert json.loads((folder/'failure.json').read_text())['memory_limit_gib'] == 8
    data = {'feasible': [case], 'infeasible': [], 'captures': [case['trace_relative_dir']]}
    states = report.collect(data, inputs)
    assert states[common.identity(case)] == 'skipped_oom'
    # An interrupted join must not override its explicit OOM with a stale-result label.
    common.demo.save(folder/'result.json', {'fingerprint': {}})
    states = report.collect(data, inputs)
    assert states[common.identity(case)] == 'skipped_oom'


def test_receipt_fingerprint_and_artifact_isolation(tmp_path,monkeypatch):
    
    import common
    from receipt_fixture import make_receipt
    case,folder,inputs,original=make_receipt(tmp_path,common)
    def fingerprint(case,values):
        return {**original,**{k:values[k] for k in ('table','configs','code','cachesim')}}
    monkeypatch.setattr(common,'expected_fingerprint',fingerprint)
    assert len(common.validate_case(case,folder,inputs))==3
    before=common.durable_hashes(folder)
    sibling=folder.parent/'archx_artifacts'/folder.name/'counts';sibling.mkdir(parents=True)
    (sibling/'checkpoint.json').write_text('{}')
    assert common.durable_hashes(folder)==before
    with pytest.raises(ValueError,match='receipt fingerprint'):
        common.validate_case(case,folder,{**inputs,'table':'unknown'})
    with (folder/'cache_a.csv').open('a') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='digest mismatch'):
        common.validate_case(case,folder,inputs)



@pytest.mark.parametrize('arm', ['a', 'b'])
def test_local_campaign_rejects_config_hash_drift(tmp_path, monkeypatch, arm):
    for candidate in ('a', 'b'):
        name = f'production_cache_{candidate}.json'
        shutil.copyfile(common.demo.CACHE_CONFIGS/name, tmp_path/name)
    path = tmp_path/f'production_cache_{arm}.json'
    path.write_bytes(path.read_bytes()+b'\n')
    monkeypatch.setattr(common.demo, 'CACHE_CONFIGS', tmp_path)
    monkeypatch.setattr(common.demo, 'check_cachesim_fresh', lambda *args: None)
    with pytest.raises(ValueError, match=f'cache {arm.upper()} differs from pinned SHA256'):
        common.current_inputs()
