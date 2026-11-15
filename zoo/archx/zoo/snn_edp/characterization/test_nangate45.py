"""Source-unit and independent-table checks for the interim 45nm price basis."""
import json
import math
import shutil
from pathlib import Path
import build_nangate45 as build


def test_rebuild_matches_committed_table(tmp_path, monkeypatch):
    expected = (build.HERE/'energy_table_nangate45.json').read_bytes()
    memory = tmp_path/'nangate45_memory/memory_prices.json'
    memory.parent.mkdir()
    shutil.copyfile(build.HERE/'nangate45_memory/memory_prices.json', memory)
    shutil.copyfile(build.HERE/'STRUCTURAL_AUDIT.json', tmp_path/'STRUCTURAL_AUDIT.json')
    monkeypatch.setattr(build, 'HERE', tmp_path)
    build.build(memory)
    assert (tmp_path/'energy_table_nangate45.json').read_bytes() == expected


def test_report_units_and_characterization_frequency():
    # Hand arithmetic from adder_DETAILS.rpt at the CSV's 400MHz, not 500MHz.
    adder=build.primitive('adder32')
    assert adder['source_frequency_MHz']==400
    assert adder['scaled_metrics']['dynamic_energy_nJ']==0.05513046/400
    assert adder['scaled_metrics']['leakage_power_mW']==0.00240549
    assert adder['scaled_metrics']['area_mm2']==0.000134596
    assert build.primitive('adder16')['scaled_metrics']['dynamic_energy_nJ']==0.05513046/400/2
    assert build.primitive('register64')['scaled_metrics']['dynamic_energy_nJ']==0.00231837/400*64
    assert build.primitive('not_gate')['source_csv'].endswith('/xor_bitwise.csv')


def test_complete_separate_table_and_inventory():
    table=build.load(build.HERE/'energy_table_nangate45.json')
    baseline=build.load(build.MODEL/'energy_table.json')
    manifest=build.load(build.HERE/'energy_table_nangate45.manifest.json')
    assert manifest['table_sha256']==build.digest(build.HERE/'energy_table_nangate45.json')
    assert set(table)==set(baseline) and len(table)==98
    excluded={k for k,r in baseline.items() if r.get('pricing_status')=='excluded by decision (prefetch control)'}
    assert len(excluded)==9
    invariant=('technology_nm','query','physical_module','physical_instances','scope','applies_to','count_expression')
    owners={}
    for key,row in table.items():
        assert all(row.get(f)==baseline[key].get(f) for f in invariant)
        assert all(isinstance(row[f],(float,int)) and math.isfinite(row[f]) and row[f]>=0 for f in build.METRICS)
        assert not row.get('placeholder')
        if key in excluded or key in ('shared.ddr4.read','shared.ddr4_io.byte'):
            assert row==baseline[key]
        else:
            assert row['characterization_technology_nm']==45
            assert build.CAVEAT in row['assumption']
            assert 'tnn' not in json.dumps(row['price_basis']).lower()
        namespace,module,op=key.split('.')
        owner=namespace+'.'+row.get('physical_module',module)
        pair=(row['leakage_power_mW'],row['area_mm2'])
        if owner in owners: assert pair==owners[owner]
        owners[owner]=pair
