"""Guard price-bank rebuilds and the capacity-only SRAM sweep."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fig1_build_table', ROOT/'archx_config/build_table.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_committed_table_matches_banks():
    rebuilt, _, _ = builder.build()
    assert rebuilt == json.loads((ROOT/'archx_config/energy_table_asap7_syn.json').read_text())
    assert len(rebuilt['variants']) == 12


def test_state_and_logic_prices_fixed_across_sweep():
    table = json.loads((ROOT/'archx_config/energy_table_asap7_syn.json').read_text())
    fixed = json.loads((ROOT/'configs/arch_manifest.json').read_text())['state_buffers']['fixed_capacity_bytes']
    for arch in ('loas', 'ptb', 'gustavsnn'):
        base = table['variants'][arch+'/256k']['operations']
        for size, capacity in (('128k', 131072), ('256k', 262144), ('512k', 524288), ('1m', 1048576)):
            rows = table['variants'][arch+'/'+size]['operations']
            assert set(rows) == set(base)
            for key, row in rows.items():
                if '.l1_weight_spad.' in key:
                    query = row['query']
                    assert query['width']*query['depth']//8 == capacity
                    assert query['width'] == (16 if arch == 'loas' else 8)*8
                else:
                    assert row == base[key]
            for state, capacity in fixed.items():
                read = rows[f'{arch}.{state}_sram.read']
                write = rows[f'{arch}.{state}_sram.write']
                assert read['query']['width']*read['query']['depth']//8 == capacity
                assert read['leakage_power_mW'] == write['leakage_power_mW']
                assert read['area_mm2'] == write['area_mm2']
