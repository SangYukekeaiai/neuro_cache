"""Materialize a tiny receipt fixture without any capture or simulator access."""
import json
from pathlib import Path


def make_receipt(directory,common):
    spec=json.loads(Path(__file__).with_suffix('.json').read_text())
    case,inputs=spec['case'],spec['inputs']
    folder=common.demo.folder_for(case,directory);folder.mkdir(parents=True,exist_ok=True)
    (folder/'noc').mkdir(exist_ok=True)
    (folder/'arch.yaml').write_text('architecture: {}\n')
    (folder/'schedule.json').write_text('{}\n')
    (folder/'noc/tc.csv').write_text('op,size\n')
    fingerprint={**{k:inputs[k] for k in ('table','configs','code','cachesim')},
        'schedule':common.demo.digest(folder/'schedule.json'),
        **{k:spec[k] for k in ('capture_size','capture_mtime','sample')}}
    rows=[{'arch':case['arch'],'capture':case['trace_relative_dir'],'layer':case['layer'],
        'sample':0,'arm':arm,'energy_table_sha256':inputs['table'],'trace_sha256':spec['trace_sha256'],
        'T_s':1.0,'E_dyn_nJ':2.0,'E_leak_nJ':3.0,'EDP_nJ_s':5.0} for arm in common.ARMS]
    common.demo.save(folder/'case.json',case)
    common.demo.save(folder/'result.json',{'fingerprint':fingerprint,'rows':rows})
    common.demo.save(folder/'generation.json',{'sha256':spec['trace_sha256'],'schedule_sha256':fingerprint['schedule']})
    common.demo.save(folder/'noc/result.json',{'tc_sha256':common.demo.digest(folder/'noc/tc.csv'),
        'inputs':{'source_sha256':inputs['noc_source'],'eventsim':{'sha256':inputs['eventsim']},
            'arch_config':{'path':str(folder/'arch.yaml'),'sha256':common.demo.digest(folder/'arch.yaml')},
            'schedule':{'sha256':fingerprint['schedule']},'sample':{'sha256':spec['trace_sha256']}}})
    for arm in ('a','b'):(folder/f'cache_{arm}.csv').write_text('total_cycles\n1\n')
    common.write_receipt(folder,inputs,{'kind':'synthetic_test'})
    return case,folder,inputs,fingerprint
