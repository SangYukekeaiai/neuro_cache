"""Price-only updates, graph integrity and historical-receipt isolation."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from snn_edp import model, pricing, run


@pytest.fixture
def counts():
    path=model.HERE/'runs/spinalflow/fixture_counts'
    model.validate_artifacts(path)
    return path


def test_reprice_pending_without_recount_or_case_reads(counts,tmp_path,monkeypatch):
    before={str(p):model.digest(p) for p in counts.rglob('*') if p.is_file()}
    table=model.load(model.HERE/'energy_table.json')
    source=str(model.HERE/'fixtures/spinalflow')
    original_open=Path.open
    def guarded_open(path,*args,**kwargs):
        if path.resolve().is_relative_to(Path(source).resolve()):
            raise AssertionError('repricing opened original simulator inputs')
        return original_open(path,*args,**kwargs)
    def forbidden(*args,**kwargs): raise AssertionError('repricing invoked counting or a subprocess')
    monkeypatch.setattr(Path,'open',guarded_open)
    monkeypatch.setattr(model,'measurements',forbidden)
    monkeypatch.setattr(run,'count',forbidden)
    monkeypatch.setattr(subprocess,'run',forbidden)
    baseline=pricing.price(counts,model.HERE/'energy_table.json',tmp_path/'baseline')
    row=table['spinalflow.cmp32.compare']
    row.update(dynamic_energy_nJ=0.25,leakage_power_mW=0.1,area_mm2=0.01,placeholder=False)
    table_file=tmp_path/'synthesized.json'; model.save(table_file,table)
    changed=pricing.price(counts,table_file,tmp_path/'repriced')
    for old,new in zip(baseline,changed):
        count=old['breakdown']['spinalflow.cmp32.compare']['count']
        assert new['E_dyn_nJ']-old['E_dyn_nJ']==pytest.approx(count*0.25)
        assert new['E_leak_nJ']-old['E_leak_nJ']==pytest.approx(64*0.1*old['T_s']*1e6)
        assert new['area_mm2']-old['area_mm2']==pytest.approx(64*0.01)
        assert new['total_cycles']==old['total_cycles']
        assert new['energy_table_sha256']!=old['energy_table_sha256']
        assert not any(r.startswith('spinalflow.cmp32.compare:') for r in new['incomplete_reasons'])
    assert before=={str(p):model.digest(p) for p in counts.rglob('*') if p.is_file()}


def test_null_without_marker_is_flagged(counts,tmp_path):
    table=model.load(model.HERE/'energy_table.json')
    table['spinalflow.adder32.add']['dynamic_energy_nJ']=None
    table['spinalflow.adder32.add']['placeholder']=False
    path=tmp_path/'null.json';model.save(path,table)
    for row in pricing.price(counts,path,tmp_path/'priced'):
        assert 'spinalflow.adder32.add:dynamic_energy_nJ=null' in row['incomplete_reasons']
        assert row['breakdown']['spinalflow.adder32.add']['E_dyn_nJ']==0
        assert row['incomplete']


@pytest.mark.parametrize('field,value',[('query',{'width':123}),('physical_instances',123),('count_expression','A*100')])
def test_price_update_rejects_hardware_or_count_changes(counts,tmp_path,field,value):
    table=model.load(model.HERE/'energy_table.json')
    table['spinalflow.adder32.add'][field]=value
    path=tmp_path/'bad.json';model.save(path,table)
    with pytest.raises(ValueError,match='hardware'):
        pricing.price(counts,path,tmp_path/'priced')


def test_tampered_checkpoint_rejected(counts,tmp_path):
    target=tmp_path/'counts';shutil.copytree(counts,target)
    manifest=model.load(target/'manifest.json')
    graph=target/manifest['graphs']['spad']
    with graph.open('a') as stream: stream.write(' ')
    with pytest.raises(ValueError,match='checkpoint artifact changed'):
        pricing.price(target,model.HERE/'energy_table.json',tmp_path/'priced')


def test_count_checkpoint_has_no_price_identity(counts):
    manifest=model.load(counts/'manifest.json')
    assert 'energy_table' not in json.dumps(manifest['fingerprint'])
    metadata=model.load(counts/'counts.json')
    assert 'dynamic_energy_nJ' not in json.dumps(metadata['operations'])
    for name in manifest['graphs'].values():
        graph=model.load(counts/name)
        for node in graph['nodes']:
            for metric in node.get('metrics',{}).values():
                assert metric['value']==0


@pytest.mark.parametrize('expression', ['unknown', '__import__("os")', 'A**2', '-A'])
def test_count_expressions_fail_closed(expression):
    with pytest.raises((ValueError,KeyError)):
        model.evaluate(expression,{'A':2})



def test_pipeline_api_counts_once_and_keeps_receipt_tree_unchanged(counts,tmp_path,monkeypatch):
    from snn_edp import archx_aggregate_case
    source=model.HERE/'fixtures/spinalflow'
    case=tmp_path/'layer'/'sample_00000';case.mkdir(parents=True)
    for name in model.load(counts/'manifest.json')['fingerprint']['inputs']:
        target=case/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
    original={str(p.relative_to(case)):model.digest(p) for p in case.rglob('*') if p.is_file()}
    table=model.HERE/'energy_table.json'
    actual=archx_aggregate_case('spinalflow',case,table)
    expected=model.load(model.HERE/'runs/spinalflow/fixture_priced/result.json')['rows']
    for row,reference in zip(actual,expected):
        for field in ('E_dyn_nJ','E_leak_nJ','T_s','EDP_nJ_s','area_mm2'):
            assert row[field]==reference[field]
        assert row['breakdown']==reference['breakdown']
    def forbidden(*args,**kwargs):raise AssertionError('cached API reran counts')
    monkeypatch.setattr(run,'count',forbidden)
    artifacts=case.parent/'archx_artifacts'
    before={str(p):(model.digest(p),p.stat().st_mtime_ns) for p in artifacts.rglob('*') if p.is_file()}
    assert archx_aggregate_case('spinalflow',case,table)==actual
    assert before=={str(p):(model.digest(p),p.stat().st_mtime_ns) for p in artifacts.rglob('*') if p.is_file()}
    assert original=={str(p.relative_to(case)):model.digest(p) for p in case.rglob('*') if p.is_file()}


