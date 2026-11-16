import importlib.util
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('delta_node', HERE/'run_node.py')
node = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node)


def test_memory_packing_reserves_full_retry_tier():
    entries = [dict(record_memory_proxy_gib=1), dict(record_memory_proxy_gib=20),
               dict(record_memory_proxy_gib=20)]
    pending = [(0, 0), (1, 0), (2, 1)]
    selected = []
    free = 240
    while choice := node.fitting_case(pending, entries, free):
        pending.remove(choice)
        free -= node.worker.resources(entries[choice[0]], choice[1])['memory_gib']
        selected.append(choice)
    assert selected == [(2, 1), (1, 0), (0, 0)]
    assert free == 40
    assert node.fitting_case([(2, 1)], entries, 119) is None
    assert node.fitting_case([(2, 1), (0, 0)], entries, 119) == (0, 0)


def test_quarter_share_records_120g_deferral_without_launch(tmp_path, monkeypatch):
    case={'arch':'spinalflow','trace_relative_dir':'C01/capture','layer':'layer03'}
    entry={'key':'spinalflow/C01/capture/layer03','record_memory_proxy_gib':20,'tier':'historical_oom'}
    monkeypatch.setattr(node.worker,'selection',lambda _: [(case,entry)])
    monkeypatch.setattr(node.worker,'paths',lambda *a:(tmp_path/'case',tmp_path/'scratch'))
    monkeypatch.setattr(node.subprocess,'Popen',lambda *a,**k:pytest.fail('oversize case launched'))
    state={'jobs':[]}
    node.execute_cases(tmp_path,tmp_path/'config.json',{'sample':489},[entry],state,100,72,defer_oversize=True)
    deferred,=state['deferred_to_batch']
    assert deferred['memory_gib']==120 and deferred['attempt']==0
    assert deferred['case']==entry['key'] and state['jobs'][0]['kind']=='deferred_to_batch'
    assert not list(tmp_path.rglob('attempt_*.json'))
    with pytest.raises(RuntimeError,match='no case fits'):
        node.execute_cases(tmp_path,tmp_path/'config.json',{'sample':489},[entry],{'jobs':[]},100,72)
