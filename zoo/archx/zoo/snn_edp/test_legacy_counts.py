"""Stage B prices archived operation names without changing or replaying counts."""
import copy
from pathlib import Path

import pytest
from archx.event import load_event_graph
from archx.metric import aggregate_event_count
from snn_edp import model, pricing, run

PATHS = model.HERE.parents[2]/'fig12_edp/demo/layer8_dummy/output_paths.json'


def archived(arch):
    entry=next(e for e in model.load(PATHS)['cases'] if e['arch']==arch)
    return entry,Path(entry['counts_dir'])


def checkpoint_hashes(directory):
    return {str(p.relative_to(directory)):model.digest(p) for p in directory.rglob('*') if p.is_file()}


def forbid_counting_and_case_reads(monkeypatch):
    case_roots=[Path(e['case_folder']).resolve() for e in model.load(PATHS)['cases']]
    original=Path.open
    def guarded(path,*args,**kwargs):
        if any(path.resolve().is_relative_to(root) for root in case_roots):
            raise AssertionError('Stage B read a simulator case')
        return original(path,*args,**kwargs)
    def forbidden(*args,**kwargs):
        raise AssertionError('Stage B replayed counting or a simulator')
    monkeypatch.setattr(Path,'open',guarded)
    monkeypatch.setattr(run,'count',forbidden)
    monkeypatch.setattr(model,'measurements',forbidden)
    monkeypatch.setattr(model,'case_counts',forbidden)
    monkeypatch.setattr(run.subprocess,'run',forbidden)


@pytest.mark.parametrize('arch',['ptb','loas','gustavsnn'])
def test_archived_layer8_uses_current_prices_on_saved_old_operations(tmp_path,monkeypatch,arch):
    _,counts=archived(arch)
    before=checkpoint_hashes(counts)
    manifest=model.validate_artifacts(counts)
    metadata=model.load(counts/'counts.json')
    renames=model.load(model.HERE/'provenance/operation_renames.json')['operation_keys']
    old,new=next((old,new) for old,new in renames.items() if old.startswith(arch+'.'))
    table_path=model.HERE/'characterization/energy_table_dummy.json'
    table=model.load(table_path); table_sha=model.digest(table_path)
    assert old not in table and new in table
    assert all(old in metadata['operations'][arm] for arm in model.ARMS)
    forbid_counting_and_case_reads(monkeypatch)
    output=tmp_path/'price'
    rows=pricing.price(counts,table_path,output)
    price_manifest=model.validate_artifacts(output)
    assert price_manifest['fingerprint']['operation_aliases']=={old:new}
    assert price_manifest['fingerprint']['operation_renames_sha256']==model.digest(model.HERE/'provenance/operation_renames.json')
    assert price_manifest['fingerprint']['energy_table_sha256']==table_sha
    assert (output/'energy_table.json').read_bytes()==table_path.read_bytes()
    for row in rows:
        arm=row['arm']; graph=load_event_graph(str(counts/manifest['graphs'][arm]))
        expected={renames.get(key,key):key for key in metadata['operations'][arm]}
        assert row['breakdown'].keys()==expected.keys()
        assert row['energy_table_sha256']==table_sha
        assert row['input_count_provenance']=={**metadata['provenance'],'operation_aliases':{old:new}}
        assert row['T_s']==metadata['cycles'][arm]/(500*1e6)
        for current,saved in expected.items():
            term=row['breakdown'][current]
            count=aggregate_event_count(graph,workload=arm,event=model.event(arm,saved))
            assert term['count']==count
            assert term['count_expression']==metadata['operations'][arm][saved]['expression']
            assert term['E_dyn_nJ']==pytest.approx(count*(table[current]['dynamic_energy_nJ'] or 0),rel=1e-12,abs=0)
        # The priced copy keeps the old graph event and old operation selector.
        priced=model.load(output/(arm+'.graph.json'))
        edge,=[e for e in priced['edges'] if e['source']==model.event(arm,old)]
        assert edge['operation']=={'dynamic_energy':old.split('.')[-1]}
    assert pricing.price(counts,table_path,output)==rows
    assert checkpoint_hashes(counts)==before
    assert model.digest(table_path)==table_sha


def test_aliases_normalize_pending_reasons_without_touching_counts(tmp_path,monkeypatch):
    _,counts=archived('ptb'); before=checkpoint_hashes(counts)
    table=model.HERE/'energy_table.json'
    forbid_counting_and_case_reads(monkeypatch)
    rows=pricing.price(counts,table,tmp_path/'price')
    spec=model.load(table)['ptb.spike_mask_overlap.check']
    for row in rows:
        assert not any(reason.startswith('ptb.merge.compare:') for reason in row['incomplete_reasons'])
        for field in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'):
            if spec[field] is None:
                assert 'ptb.spike_mask_overlap.check:'+field+'=null' in row['incomplete_reasons']
        if spec['dynamic_energy_nJ'] is None:
            assert row['breakdown']['ptb.spike_mask_overlap.check']['E_dyn_nJ']==0
    assert checkpoint_hashes(counts)==before


@pytest.mark.parametrize('kind',['unknown','collision'])
def test_unknown_or_colliding_bindings_fail_before_output(tmp_path,monkeypatch,kind):
    _,counts=archived('ptb'); before=checkpoint_hashes(counts)
    original=pricing.load
    def altered(path):
        value=original(path)
        if Path(path)==counts/'counts.json':
            value=copy.deepcopy(value)
            for specs in value['operations'].values():
                target='ptb.unknown.compare' if kind=='unknown' else 'ptb.spike_mask_overlap.check'
                specs[target]=specs['ptb.merge.compare']
        return value
    monkeypatch.setattr(pricing,'load',altered)
    forbid_counting_and_case_reads(monkeypatch)
    with pytest.raises(ValueError,match='unknown price operation' if kind=='unknown' else 'aliases collide'):
        pricing.price(counts,model.HERE/'energy_table.json',tmp_path/'price')
    assert not (tmp_path/'price').exists()
    assert checkpoint_hashes(counts)==before
