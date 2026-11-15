"""Apply a table to saved count graphs; all hardware sums are native archx queries."""
import math
from archx.event import load_event_graph, save_event_graph
from archx.metric import aggregate_event_metric, aggregate_event_count
from .model import *


DEFAULT_FREQUENCY_MHZ = 500


def price(count_dir, table_path, output, frequency_MHz=DEFAULT_FREQUENCY_MHZ):
    count_dir=Path(count_dir); output=Path(output)
    if not math.isfinite(frequency_MHz) or frequency_MHz<=0: raise ValueError('frequency must be finite and positive')
    manifest=validate_artifacts(count_dir)
    if manifest['fingerprint']['archx']!=backend_fingerprint(): raise ValueError('archx backend differs from count checkpoint')
    table_bytes=Path(table_path).read_bytes(); table=json.loads(table_bytes)
    table_sha=hashlib.sha256(table_bytes).hexdigest()
    metadata=load(count_dir/'counts.json'); arch=metadata['arch']
    all_specs={key:spec for arm_specs in metadata['operations'].values() for key,spec in arm_specs.items()}
    rename_path=HERE/'provenance/operation_renames.json'
    renames=load(rename_path)['operation_keys']
    bindings={key:renames.get(key,key) for key in all_specs}
    aliases={key:target for key,target in bindings.items() if key!=target}
    if len(set(bindings.values()))!=len(bindings): raise ValueError('operation aliases collide in count checkpoint')
    for key,target in bindings.items():
        if target not in table: raise ValueError('unknown price operation: '+key+' -> '+target)
    fingerprint={'count_manifest_sha256':digest(count_dir/'manifest.json'),
                 'energy_table_sha256':table_sha,'frequency_MHz':frequency_MHz,
                 'pricing_code':{name:digest(HERE/name) for name in ('pricing.py','model.py')},
                 'archx':backend_fingerprint(),'operation_aliases':aliases,
                 'operation_renames_sha256':digest(rename_path)}
    if (output/'manifest.json').exists():
        previous=validate_artifacts(output)
        if previous['fingerprint']!=fingerprint: raise ValueError('pricing output belongs to different inputs')
        return load(output/'result.json')['rows']
    if output.exists() and any(output.iterdir()): raise ValueError('pricing output is uncommitted; use a fresh directory')
    result=[]
    for arm in ARMS:
        graph=load_event_graph(str(count_dir/manifest['graphs'][arm]))
        specs=metadata['operations'][arm]
        modules={}; incomplete=[]
        for key,spec in all_specs.items():
            current_key=bindings[key]; row=table[current_key]
            for field in ('physical_instances','physical_module','scope','applies_to','count_expression','technology_nm'):
                if row.get(field)!=spec.get(field): raise ValueError('hardware/count definition changed: '+key+'.'+field)
            for dimension in ('width','depth','bank','associativity','size','inputs','state_register'):
                if row.get('query',{}).get(dimension)!=spec.get('query',{}).get(dimension): raise ValueError('hardware changed: '+key+'.'+dimension)
            metrics={}
            for metric,field in (('dynamic_energy','dynamic_energy_nJ'),('leakage_power','leakage_power_mW'),('area','area_mm2')):
                value=row.get(field)
                if value is None:
                    if key in specs: incomplete.append(current_key+':'+field+'=null')
                    value=0
                if not math.isfinite(value) or value<0: raise ValueError('invalid metric: '+key)
                metrics[metric]=value
            if key in specs and row.get('placeholder'): incomplete.append(current_key+':incomplete/placeholder')
            name=leaf(key,spec); module=modules.setdefault(name,{'key':key,'spec':spec,'dynamic_energy':{},'power':metrics['leakage_power'],'area':metrics['area']})
            if (module['power'],module['area'])!=(metrics['leakage_power'],metrics['area']): raise ValueError('inconsistent physical metrics: '+key)
            module['dynamic_energy'][key.split('.')[-1]]={'value':metrics['dynamic_energy'],'unit':'nJ'}
        graph.init_metrics({k:v['unit'] for k,v in METRICS.items()})
        for name,module in modules.items():
            graph.set_module_data(name,{'dynamic_energy':module['dynamic_energy'],
                'leakage_power':{'value':module['power'],'unit':'mW'},'area':{'value':module['area'],'unit':'mm^2'}},
                instances(module['key'],module['spec']),[module['key'].split('.')[0]])
        def metric(name,event_name):
            return aggregate_event_metric(graph,METRICS,name,event=event_name)['value']
        breakdown={bindings[key]:{'count_expression':spec['expression'],
            'count':aggregate_event_count(graph,workload=arm,event=event(arm,key)),
            'E_dyn_nJ':aggregate_event_metric(graph,METRICS,'dynamic_energy',workload=arm,event=event(arm,key))['value'],
            'category':spec['category']} for key,spec in specs.items()}
        dynamic=metric('dynamic_energy',arm); power=metric('leakage_power',arm); area=metric('area',arm)
        cycles=metadata['cycles'][arm]; seconds=cycles/(frequency_MHz*1e6); leakage=power*seconds*1e6
        result.append({'arch':arch,'arm':arm,'E_dyn_nJ':dynamic,'E_leak_nJ':leakage,'T_s':seconds,
            'EDP_nJ_s':(dynamic+leakage)*seconds,'area_mm2':area,'incomplete':bool(incomplete),
            'incomplete_reasons':sorted(set(incomplete)),'energy_table_sha256':__import__('hashlib').sha256(table_bytes).hexdigest(),
            'total_cycles':cycles,'frequency_MHz':frequency_MHz,'E_core_dyn_nJ':metric('dynamic_energy','core_'+arm),
            'E_chain_reference_nJ':metric('dynamic_energy','chain_reference'),
            'input_count_provenance':({**metadata['provenance'],'operation_aliases':aliases} if aliases else metadata['provenance']),'breakdown':breakdown,
            'caveats':sorted({table[bindings[key]]['assumption'] for key in specs if 'assumption' in table[bindings[key]]})})
        output.mkdir(parents=True,exist_ok=True)
        save_event_graph(graph,str(output/(arm+'.graph.json')))
    save(output/'result.json',{'count_manifest_sha256':digest(count_dir/'manifest.json'),'rows':result})
    (output/'energy_table.json').write_bytes(table_bytes)
    if fingerprint['count_manifest_sha256']!=digest(count_dir/'manifest.json'):
        raise ValueError('count manifest changed during pricing')
    validate_artifacts(count_dir)
    save(output/'manifest.json',{'fingerprint':fingerprint,'artifacts':{
        name:digest(output/name) for name in ['result.json','energy_table.json',*[arm+'.graph.json' for arm in ARMS]]}})
    return result
