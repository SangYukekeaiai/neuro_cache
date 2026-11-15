"""Dummy prices remain identifiable and category rollups count operations."""
from snn_edp import model, pricing, run


def test_dummy_table_covers_pending_and_keeps_default_prices():
    original=model.load(model.HERE/'energy_table.json')
    dummy=model.load(model.HERE/'characterization/energy_table_dummy.json')
    assert set(dummy)==set(original)
    assert model.digest(model.HERE/'energy_table.json')=='8c3589272e2a68dc9b01847be61f2076fb5dbb84eee7a4dc582671da9ff79942'
    metrics=('dynamic_energy_nJ','leakage_power_mW','area_mm2')
    for key,row in original.items():
        if row.get('placeholder'):
            assert dummy[key]['assumption'] in ('DUMMY placeholder pending ASAP7 synthesis','DUMMY (magnitude from retired tnn characterization) pending ASAP7 synthesis')
            assert dummy[key]['placeholder']=='DUMMY placeholder pending ASAP7 synthesis'
            assert dummy[key]['dummy_basis']
            assert all(dummy[key][x]>0 for x in metrics)
        else:
            assert all(dummy[key][x]==row[x] for x in metrics)
    for operation in ('search','write'):
        spec=model.load(model.HERE/'hardware.json')['prosperity.tcam.'+operation]['implementation']
        assert spec['matching']=='(entry AND query) == entry'
        assert (spec['banks'],spec['entries_per_bank'],spec['entry_bits'])==(2,256,16)
    queue=model.load(model.HERE/'hardware.json')['cache.next_access_logic.step']['implementation']
    assert (queue['address_queue_entries'],queue['address_bits'],queue['data_buffer_bytes'])==(4,64,0)


def test_native_category_rollups_and_dummy_warning(tmp_path):
    case=model.HERE/'fixtures/spinalflow'
    checkpoint=run.count(case,tmp_path/'counts')
    saved=model.load(checkpoint/'event_count_categories.json')
    raw=model.load(case/'counts.json')
    additions=raw['S_win']*raw['COUT']
    lif=raw['HO']*raw['WO']*raw['COUT']*raw['T']
    fetches=additions/raw['cout_n']
    expected_core=3*additions+lif+3*fetches+lif*raw['d_out']
    for arm,data in saved['arms'].items():
        assert data['rollups']['core']==expected_core
        assert data['rollups']['total']==sum(v['count'] for v in data['operations'].values())
        assert data['category_event_invocations']=={'core':1,'memory':1}
        assert data['operations']['spinalflow.adder32.add']=={'count':additions,'category':'core'}
        assert data['operations']['shared.ddr4.read']['category']=='memory'
    manifest=model.validate_artifacts(checkpoint)
    assert 'event_count_categories.json' in manifest['artifacts']
    rows=pricing.price(checkpoint,model.HERE/'characterization/energy_table_dummy.json',tmp_path/'price')
    assert len(rows)==3
    for row in rows:
        assert row['incomplete']
        assert 'DUMMY placeholder pending ASAP7 synthesis' in row['caveats']
        assert not any(reason.endswith('=null') for reason in row['incomplete_reasons'])
        assert row['E_dyn_nJ']>0 and row['EDP_nJ_s']>0
