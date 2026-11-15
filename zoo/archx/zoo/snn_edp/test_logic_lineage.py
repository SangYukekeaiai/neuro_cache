"""No active retired-library prices; exact own-RTL geometry coverage."""
import json
from snn_edp import model


def test_retired_logic_is_pending_and_dummy_history_is_explicit():
    hardware=model.load(model.HERE/'hardware.json')
    default=model.load(model.HERE/'energy_table.json')
    dummy=model.load(model.HERE/'characterization/energy_table_dummy.json')
    excluded=set(model.load(model.HERE/'characterization/pricing_policy.json')['excluded_operations'])
    retired=model.load(model.HERE/'provenance/retired_logic.json')['rows']
    assert len(retired)==14
    assert 'tnn' not in json.dumps(hardware).lower()
    for key,row in default.items():
        assert 'tnn' not in str(row.get('source_csv','')).lower()
        assert 'tnn' not in str(row.get('query',{}).get('class','')).lower()
        if row.get('query',{}).get('interface')=='csv_cmos' and key not in excluded:
            assert row['placeholder']=='pending-ASAP7-synthesis'
            assert row['query']['frequency']==500
            assert all(row[k] is None for k in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'))
        assert 'tnn' not in str(dummy[key].get('source_csv','')).lower()
        assert 'tnn' not in str(dummy[key].get('query',{}).get('class','')).lower()
    for key,old in retired.items():
        if key in excluded:
            assert all(default[key][f]==dummy[key][f]==0 for f in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'))
            continue
        assert dummy[key]['assumption']=='DUMMY (magnitude from retired tnn characterization) pending ASAP7 synthesis'
        assert dummy[key]['placeholder']
        for field in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'):
            assert default[key][field] is None
            assert dummy[key][field]==old[field]
    for table in (hardware,default,dummy):
        assert table['cache.distance_metadata.write']['implementation']==table['cache.distance_metadata.read']['implementation']


def test_worklist_covers_each_required_width_and_storage_geometry():
    work={r['component']:r for r in model.load(model.HERE/'characterization/auto_syn_pnr_worklist.json')}
    assert set(work['adder']['width_bits'])=={1,2,3,4,5,13,16,32}
    assert set(work['register']['characterization_width_bits'])=={1,2,3,5,16,32,64}
    assert set(work['adder']['characterization_width_bits'])=={1,2,3,4,5,13,16,32}
    files={(r['width_bits'],r['depth']) for r in work['register']['regfile_variants']}
    assert {(32,64),(64,320),(64,384),(64,16),(64,32),(16,256)}<=files
    fifo={(r['width_bits'],d) for r in work['fifo']['geometries'] for d in r.get('depths',[r.get('depth')])}
    assert fifo=={(16,8),(32,8),(64,2)}
    for row in work.values():
        assert row['frequency_MHz']==500 and row['clock_period_ns']==2
        assert row['target_library']['family']=='ASAP7_75t_R'
        assert row['target_library']['corner']=='TT'
