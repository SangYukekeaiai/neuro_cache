"""Price counted Figure 1 graphs without accessing simulator inputs."""
import argparse
import math
import sys
from model import *
from archx.event import load_event_graph, save_event_graph
from archx.metric import aggregate_event_metric, aggregate_event_count
from loguru import logger


def price(directory, table_path, output, ideal=False):
    manifest=load(directory/'manifest.json')
    for name,sha in manifest['artifacts'].items():
        if digest(directory/name)!=sha: raise ValueError('count checkpoint changed')
    before=digest(directory/'manifest.json')
    data=load(directory/'counts.json'); specs=data['specifications']
    table=load(table_path); rows=table['variants'][data['variant']]['operations']
    graph=load_event_graph(str(directory/'counted.graph.json'))
    overrides={}
    if ideal:
        if data['identity']['size']!='256k': raise ValueError('ideal is defined at the 256KiB baseline only')
        n=data['ideal_needed_weight_bytes']; arch=data['identity']['arch']
        weight=arch+'.l1_weight_spad.write'
        overrides={'shared.ddr4.read':n/64,'shared.ddr4_io.byte':n,
                   weight:n*8/specs[weight]['query']['width']}
        for key,value in overrides.items():
            if value>data['counts'][key]: raise ValueError('ideal count exceeds baseline')
            graph.set_edge_count(specs[key]['segment'],event(key),float(value))
    modules={}
    graph.init_metrics({k:v['unit'] for k,v in METRICS.items()})
    for key,spec in specs.items():
        row=rows[key]
        for dimension in ('width','depth','bank'):
            if dimension in spec['query'] and row.get('query',{}).get(dimension,spec['query'][dimension]) != spec['query'][dimension]:
                raise ValueError('geometry differs: '+key)
        name=leaf(key)
        module=modules.setdefault(name, {'key':key,'instances':spec['instances'],
            'segment':spec['inventory_segment'],'dynamic':{},'power':row['leakage_power_mW'],'area':row['area_mm2']})
        if (module['instances'],module['power'],module['area']) != (spec['instances'],row['leakage_power_mW'],row['area_mm2']):
            raise ValueError('inconsistent physical inventory: '+key)
        module['dynamic'][key.split('.')[-1]]={'value':row['dynamic_energy_nJ'],'unit':'nJ'}
    for name,m in modules.items():
        graph.set_module_data(name, {'dynamic_energy':m['dynamic'],
            'leakage_power':{'value':m['power'],'unit':'mW'},'area':{'value':m['area'],'unit':'mm^2'}},m['instances'],[m['segment']])
    def metric(kind, node):
        return aggregate_event_metric(graph,METRICS,kind,event=node)['value']
    duration=data['cycles']/(FREQUENCY_MHZ*1e6)
    breakdown={}
    for key,spec in specs.items():
        n=aggregate_event_count(graph,workload='spad',event=event(key))
        e=aggregate_event_metric(graph,METRICS,'dynamic_energy',workload='spad',event=event(key))['value']
        if n!=overrides.get(key,data['counts'][key]): raise ValueError('priced graph count changed')
        if not math.isclose(e,n*rows[key]['dynamic_energy_nJ'],rel_tol=1e-12,abs_tol=1e-18): raise ValueError('term arithmetic differs')
        breakdown[key]={'count':n,'count_expression':spec['expression'],'E_dyn_nJ':e,'segment':spec['segment']}
    segments={s:{'E_dyn_nJ':metric('dynamic_energy',s) if graph.has_node(s) else 0., 'E_leak_nJ':0.} for s in SEGMENTS}
    inventory={}
    for name,m in modules.items():
        power=metric('leakage_power',name); area=metric('area',name)
        if not math.isclose(power,m['power']*m['instances'],rel_tol=1e-12,abs_tol=1e-18): raise ValueError('physical leakage differs')
        segments[m['segment']]['E_leak_nJ']+=power*duration*1e6
        inventory[name]={'instances':m['instances'],'power_mW':power,'area_mm2':area,'segment':m['segment']}
    dynamic=metric('dynamic_energy','spad'); leakage=metric('leakage_power','spad')*duration*1e6
    if not math.isclose(dynamic,sum(v['E_dyn_nJ'] for v in breakdown.values()),rel_tol=1e-12,abs_tol=1e-18): raise ValueError('dynamic sum mismatch')
    if not math.isclose(leakage,sum(v['E_leak_nJ'] for v in segments.values()),rel_tol=1e-12,abs_tol=1e-18): raise ValueError('leakage sum mismatch')
    result={**data['identity'],'bar':'ideal' if ideal or data['identity'].get('execution')=='whole_run_ideal' else data['identity']['size'], 'E_dyn_nJ':dynamic,'E_leak_nJ':leakage,
            'E_total_nJ':dynamic+leakage,'T_s':duration,'total_cycles':data['cycles'],
            'EDP_nJ_s':(dynamic+leakage)*duration,'area_mm2':metric('area','spad'),
            'segments':segments,'inventory':inventory,'breakdown':breakdown,'energy_only_overrides':overrides,
            'energy_table_sha256':digest(table_path),'count_manifest_sha256':before,
            'caveats':sorted({rows[k]['assumption'] for k in specs}),
            'pricing_status':'ASAP7_GENUS_SYNTHESIS_ESTIMATE'}
    save(output/'result.json',result)
    save_event_graph(graph,str(output/'priced.graph.json'))
    save(output/'manifest.json',{'table_sha256':digest(table_path),'count_manifest_sha256':before,
        'pricing_code_sha256':digest(Path(__file__)),'archx_file':archx.__file__,
        'artifacts':{n:digest(output/n) for n in ('result.json','priced.graph.json')}})
    if before!=digest(directory/'manifest.json') or any(digest(directory/n)!=h for n,h in manifest['artifacts'].items()):
        raise ValueError('Stage A changed during pricing')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--counts',type=Path);p.add_argument('--out',type=Path)
    p.add_argument('--table',type=Path,required=True);p.add_argument('--ideal',action='store_true')
    args=p.parse_args();logger.remove();logger.add(sys.stderr,level='ERROR')
    print('archx.__file__='+archx.__file__,flush=True)
    if args.counts:
        if not args.out:p.error('--out is required with --counts')
        price(args.counts,args.table,args.out,args.ideal);return
    directories=[p.parent for p in sorted((ROOT/'outputs/archx_counts').glob('*/*/sample_*/*/manifest.json'))]
    if len(directories)!=1440: raise ValueError('expected 1440 count checkpoints')
    for i,directory in enumerate(directories):
        relative=directory.relative_to(ROOT/'outputs/archx_counts')
        price(directory,args.table,ROOT/'outputs/priced/baseline'/relative)
        if relative.parts[1]=='256k':price(directory,args.table,ROOT/'outputs/priced/ideal'/relative,True)
        if (i+1)%120==0:print(f'priced {i+1}/{len(directories)}',flush=True)


if __name__=='__main__':main()
