"""Compile/execute count descriptions, then apply prices to their checkpoints."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from .model import *
from . import BACKEND_ROOT

THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','RAYON_NUM_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_MAX_THREADS','POLARS_MAX_THREADS','TBB_NUM_THREADS','GOTO_NUM_THREADS')


def count(case,output):
    case=Path(case).resolve(); output=Path(output).resolve()
    if output.is_relative_to(case): raise ValueError('checkpoints must be outside receipted case')
    if (output/'manifest.json').exists(): raise ValueError('count output already committed')
    fingerprint=count_fingerprint(case)
    measurements.cache_clear()
    data=measurements(str(case)); arch=data['identity']['arch']
    sources=fingerprint['inputs']
    save(output/'request.json',{'case_dir':str(case)})
    env={**os.environ,**dict.fromkeys(THREADS,'1'),'ARCHX_DISABLE_PERFORMANCE_CACHE':'1',
         'ARCHX_INTERFACE_CACHE_DIR':str(output/'interface_cache'),
         'PYTHONPATH':os.pathsep.join(map(str,(HERE/'runtime',BACKEND_ROOT/'src',ROOT))),'PYTHONDONTWRITEBYTECODE':'1'}
    commands=[['-compile',str(HERE/'designs/snn/description.py'),'-r',str(output)],
              ['-r',str(output),'-extract',str(output/'configurations.csv')],
              ['-x',str(output/'runs.txt'),'-r',str(output)]]
    os.environ.update(dict.fromkeys(THREADS,'1'))
    os.environ['ARCHX_DISABLE_PERFORMANCE_CACHE']='1'
    for i,args in enumerate(commands):
        with (output/f'archx_{i}.log').open('w') as log:
            subprocess.run([sys.executable,'-m','archx.main',*args],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    from archx.event import load_event_graph
    from archx.metric import aggregate_event_count
    runs=list(csv.DictReader((output/'configurations.csv').open()))
    if len(runs)!=3: raise ValueError('expected three arm graphs')
    graphs={row['workload_name']:str(Path(row['checkpoint_path']).relative_to(output)) for row in runs}
    ops={arm:operations(arch,arm) for arm in ARMS}
    counts={}
    categories={}
    for arm in ARMS:
        graph=load_event_graph(str(output/graphs[arm]))
        counts[arm]={key:aggregate_event_count(graph,workload=arm,event=event(arm,key)) for key in ops[arm]}
        by_operation={key:{'count':counts[arm][key],'category':spec['category']} for key,spec in ops[arm].items()}
        rollups={category:sum(aggregate_event_count(graph,workload=category+'_'+arm,event=event(arm,key))
                    for key,spec in ops[arm].items() if spec['category']==category) for category in ('core','memory')}
        rollups['total']=rollups['core']+rollups['memory']
        if rollups['total'] != sum(counts[arm].values()): raise ValueError('category count rollup differs from operations')
        categories[arm]={'operations':by_operation,'rollups':rollups,
            'category_event_invocations':{category:aggregate_event_count(graph,workload=arm,event=category+'_'+arm)
                                          for category in ('core','memory')}}
    metadata={'arch':arch,'identity':data['identity'],'operations':ops,'counts':counts,
        'cycles':{arm:float((data['noc'] if arm=='spad' else data['caches'][arm])['total_cycles']) for arm in ARMS},
        'provenance':{'counts':data['counts'],'noc':data['noc'],'cachesim':data['caches'],'source_hashes':sources}}
    save(output/'counts.json',metadata)
    save(output/'event_count_categories.json',{'arch':arch,'arms':categories,'rollup_semantics':'sum native aggregate_event_count queries rooted at each category event; heterogeneous operation totals, not cycles or bytes'})
    if fingerprint!=count_fingerprint(case): raise ValueError('count inputs/model changed during counting')
    artifacts={name:digest(output/name) for name in [*graphs.values(),'counts.json','event_count_categories.json']}
    save(output/'manifest.json',{'fingerprint':fingerprint,'graphs':graphs,'artifacts':artifacts})
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('count','price'))
    parser.add_argument('--case',type=Path)
    parser.add_argument('--counts',type=Path)
    parser.add_argument('--table',type=Path,default=HERE/'energy_table.json')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.stage=='count':
        if not args.case: parser.error('count requires --case')
        count(args.case,args.out)
    else:
        if not args.counts: parser.error('price requires --counts')
        from .pricing import price
        price(args.counts,args.table,args.out)
    print(json.dumps({'stage':args.stage,'output':str(args.out)}))


if __name__=='__main__': main()
