import importlib.util
import json
import pytest
from pathlib import Path

spec=importlib.util.spec_from_file_location('fig12_demo_run',Path(__file__).with_name('run.py'))
run=importlib.util.module_from_spec(spec); spec.loader.exec_module(run)


def test_selection_is_complete_and_smoke_has_one_case_per_arch():
    cases=run.select_cases()
    assert len(cases)==749
    assert len({(r['arch'],r['trace_relative_dir'],r['layer']) for r in cases})==749
    smoke=run.select_cases(True)
    assert {r['arch'] for r in smoke}==set(run.ARCHES)
    for row in smoke:
        p=row['workload']['problem']
        assert p['T']*p['CIN']*p['HO']*p['WO']*p['COUT']>0


def test_atomic_results_collect_only_completed_cases(tmp_path):
    good=tmp_path/'cases/loas/B09/capture/layer/sample_00000/result.json'
    rows=[{'arch':'loas','arm':arm,'total_cycles':i+1} for i,arm in enumerate(('spad','cacheA','cacheB'))]
    run.save(good,{'rows':rows})
    run.save(good.with_name('failure.json'),{'status':'interrupted'})
    assert run.collect(tmp_path)==3
    import csv
    actual=list(csv.DictReader((tmp_path/'results.csv').open()))
    assert [r['arm'] for r in actual]==['spad','cacheA','cacheB']
    assert not good.with_suffix('.json.part').exists()


def test_stale_native_binary_is_rejected(tmp_path):
    import os
    import pytest
    native=tmp_path/'native'; source=native/'src/input.cpp'
    source.parent.mkdir(parents=True); source.write_text('source')
    binary=tmp_path/'cachesim'; binary.write_bytes(b'bin')
    os.utime(source,ns=(100,100)); os.utime(binary,ns=(200,200))
    run.check_cachesim_fresh(binary,native)
    os.utime(source,ns=(300,300))
    with pytest.raises(RuntimeError,match='stale cachesim binary'):
        run.check_cachesim_fresh(binary,native)


def test_excluded_case_fails_before_any_simulation(tmp_path,monkeypatch):
    import importlib.util
    import pytest
    from zoo.fig12_edp.demo.all_bench.layer_scope import kept
    path=Path(__file__).with_name('run.py')
    spec=importlib.util.spec_from_file_location('scoped_demo',path)
    demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
    def forbidden(*args,**kwargs): raise AssertionError('excluded case reached native simulation')
    monkeypatch.setattr(demo,'check_cachesim_fresh',forbidden)
    with pytest.raises(ValueError,match='kept workload scope'):
        demo.run_case({'layer':'layer_13_core_classifier','arch':'spinalflow'},tmp_path,0)
    assert kept('layer_10_attention_output_dense')
    assert not kept('layer_11_output_dense')


@pytest.mark.parametrize('preexisting_generation', [False,True], ids=['fresh','pending_without_command'])
def test_trace_provenance_survives_durable_commit_and_trace_deletion(tmp_path,monkeypatch,preexisting_generation):
    import struct
    import sys
    import types
    noc_driver=types.ModuleType("nocsim.driver")
    noc_driver.run_case=lambda *a:{"total_cycles":10}
    case={'arch':'spinalflow','trace_relative_dir':'B09/example','layer':'layer_01_conv','schedule_path':'schedule.json'}
    trace_root=tmp_path/'captures';source=trace_root/'B09/example/layer_01_conv.npy'
    source.parent.mkdir(parents=True);source.write_bytes(b'saved capture')
    manifest=tmp_path/'manifest.json';manifest.write_text('{}');manifest.with_name('schedule.json').write_text('{}')
    monkeypatch.setattr(run,'TRACE_ROOT',trace_root);monkeypatch.setattr(run,'MANIFEST',manifest)
    monkeypatch.setattr(run,'check_cachesim_fresh',lambda *a:None)
    monkeypatch.setattr(run,'code_digest',lambda:'test-source')
    monkeypatch.setattr(run,'count_case',lambda *a:{'A':1})
    generation_commands=[]
    def command(args,log,stdout=None,**kwargs):
        if stdout is not None:
            generation_commands.append(args)
            stdout.write(b'fixture-stream'+struct.pack('<iQ',-1,17))
        else:
            Path(args[args.index('--out')+1]).write_text('total_cycles\n10\n')
    monkeypatch.setattr(run,'command',command)
    monkeypatch.setattr(noc_driver,'run_case',lambda *a:{'total_cycles':10})
    # run_case imports nocsim.driver using the script's import path.
    monkeypatch.setitem(sys.modules,'nocsim.driver',noc_driver)
    monkeypatch.setattr(run,'archx_aggregate_case',lambda arch,folder,table:[
        {'arm':arm,'energy_table_sha256':run.digest(table),'input_count_provenance':{}}
        for arm in ('spad','cacheA','cacheB')])
    folder=run.folder_for(case,tmp_path/'output');trace=folder/'sample_00000.wcts'
    if preexisting_generation:
        folder.mkdir(parents=True)
        trace.write_bytes(b'old-stream'+struct.pack('<iQ',-1,23))
        run.save(folder/'generation.json',{'sha256':run.digest(trace),'records':23,
            'sample':0,'schedule_sha256':run.digest(manifest.with_name('schedule.json'))})
        assert not (folder/'result.json').exists()
    original_save=run.save
    def save(path,value):
        if path.name=='result.json':assert trace.exists(), 'trace removed before durable commit'
        original_save(path,value)
    monkeypatch.setattr(run,'save',save)
    run.run_case(case,tmp_path/'output',0)
    assert len(generation_commands)==1
    assert not trace.exists()
    generation=json.loads((folder/'generation.json').read_text())
    assert generation['trace_path']==str(trace.resolve())
    assert generation['capture_path']==str(source.resolve())
    assert generation['records']==17 and len(generation['sha256'])==64
    command=generation['generator_command']
    assert command==generation_commands[0]
    assert command[command.index('--layer')+1]=='layer_01_conv'
    assert command[command.index('--sample-start')+1]=='0'
    result=json.loads((folder/'result.json').read_text())
    assert all(row['input_count_provenance']['trace']==generation for row in result['rows'])
