"""Separate-process inputs and zero-dynamic state inventory contracts."""
import csv
import importlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'archx_config'))
model=importlib.import_module('model')
count_stage=importlib.import_module('count')
price_stage=importlib.import_module('price')
TABLE=ROOT/'archx_config/energy_table_asap7_syn.json'
FIRST=Path('gustavsnn/128k/sample_000/layer_01_core_features_3')


def fail(*args,**kwargs):
    raise AssertionError('pricing must not execute a count or performance path')


def test_count_without_table(tmp_path):
    template_dir=ROOT/'outputs/archx_templates/gustavsnn/128k'
    row,=list(csv.DictReader((template_dir/'configurations.csv').open()))
    hidden=TABLE.with_suffix('.json.absent_for_count_test')
    assert not hidden.exists()
    TABLE.rename(hidden)
    try:
        assert not TABLE.exists()
        count_stage.count(ROOT/'outputs/counts'/FIRST,tmp_path/'counts',Path(row['checkpoint_path']))
        metadata=model.load(tmp_path/'counts/counts.json')
        assert metadata['counts']['gustavsnn.psum_sram.read']==0
        assert metadata['counts']['gustavsnn.vmem_sram.write']==0
    finally:
        hidden.rename(TABLE)


def test_price_without_case_inputs_and_reprice(tmp_path,monkeypatch):
    checkpoint=tmp_path/'checkpoint'
    shutil.copytree(ROOT/'outputs/archx_counts'/FIRST,checkpoint)
    original={p.name:model.digest(p) for p in checkpoint.iterdir()}
    original_open=Path.open
    def guarded(path,*args,**kwargs):
        if path.resolve().is_relative_to(ROOT/'outputs/counts'):
            raise AssertionError('Stage B opened simulator inputs')
        return original_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',guarded)
    monkeypatch.setattr(model,'measurements',fail)
    monkeypatch.setattr(count_stage,'count',fail)
    import archx.performance
    monkeypatch.setattr(archx.performance,'simulate_performance_all_events',fail)
    result=price_stage.price(checkpoint,TABLE,tmp_path/'price')
    for state in ('psum','vmem'):
        for op in ('read','write'):
            term=result['breakdown'][f'gustavsnn.{state}_sram.{op}']
            assert term['count']==0 and term['E_dyn_nJ']==0
        assert result['inventory'][f'm__gustavsnn__{state}_sram']['power_mW']>0
    assert result['inventory']['m__gustavsnn__adder16']['instances']==8
    assert result['inventory']['m__gustavsnn__leading_spike_detector']['instances']==1
    assert not any('merger' in k for k in result['breakdown'])
    table=model.load(TABLE); row=table['variants']['gustavsnn/128k']['operations']['gustavsnn.adder16.add']
    old=row['dynamic_energy_nJ']; row['dynamic_energy_nJ']*=2
    model.save(tmp_path/'table.json',table)
    repriced=price_stage.price(checkpoint,tmp_path/'table.json',tmp_path/'reprice')
    expected=result['breakdown']['gustavsnn.adder16.add']['count']*old
    assert abs((repriced['E_dyn_nJ']-result['E_dyn_nJ'])-expected)<1e-9
    assert repriced['T_s']==result['T_s'] and repriced['E_leak_nJ']==result['E_leak_nJ']
    assert original=={p.name:model.digest(p) for p in checkpoint.iterdir()}


def test_ideal_changes_only_weight_read_and_fill(tmp_path):
    directory=ROOT/'outputs/archx_counts/gustavsnn/256k/sample_000/layer_01_core_features_3'
    before={p.name:model.digest(p) for p in directory.iterdir()}
    baseline=price_stage.price(directory,TABLE,tmp_path/'baseline')
    ideal=price_stage.price(directory,TABLE,tmp_path/'ideal',True)
    allowed={'shared.ddr4.read','shared.ddr4_io.byte','gustavsnn.l1_weight_spad.write'}
    assert set(ideal['energy_only_overrides'])==allowed
    for key,row in baseline['breakdown'].items():
        if key not in allowed:assert ideal['breakdown'][key]==row
    assert ideal['E_total_nJ']<baseline['E_total_nJ']
    for key in ('T_s','total_cycles','E_leak_nJ','area_mm2','inventory'):
        assert ideal[key]==baseline[key]
    assert before=={p.name:model.digest(p) for p in directory.iterdir()}
