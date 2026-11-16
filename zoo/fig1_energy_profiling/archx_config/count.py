"""Compile per-design archx templates and save price-free per-case graphs."""
import argparse
import csv
import os
import subprocess
import sys
from model import *
from archx.event import load_event_graph, save_event_graph
from archx.metric import aggregate_event_count
from archx.performance import simulate_performance_all_events
from loguru import logger

SOURCES = ('model.py','description.py','performance.py','zero_metrics.py','hardware.json','count.py')


def compile_template(case, destination):
    save(destination/'request.json', {'case_dir':str(case.resolve())})
    env = {**os.environ, 'ARCHX_DISABLE_PERFORMANCE_CACHE':'1', 'PYTHONDONTWRITEBYTECODE':'1',
           'ARCHX_INTERFACE_CACHE_DIR':str(destination/'interface_cache'),
           'PYTHONPATH':os.pathsep.join(map(str,(ROOT/'archx_config/runtime',ROOT/'archx_config',BACKEND/'src',BACKEND/'zoo')))}
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','RAYON_NUM_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_MAX_THREADS','POLARS_MAX_THREADS','TBB_NUM_THREADS','GOTO_NUM_THREADS'):
        env[name]='1'
    commands = [('-compile',str(ROOT/'archx_config/description.py'),'-r',str(destination)),
                ('-r',str(destination),'-extract',str(destination/'configurations.csv')),
                ('-x',str(destination/'runs.txt'),'-r',str(destination))]
    for index,args in enumerate(commands):
        with (destination/f'archx_{index}.log').open('w') as log:
            log.write('archx.__file__='+archx.__file__+'\n'); log.flush()
            subprocess.run([sys.executable,'-B','-m','archx.main',*args],cwd=ROOT,env=env,
                           stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
    row, = list(csv.DictReader((destination/'configurations.csv').open()))
    return Path(row['checkpoint_path'])


def count(case, output, template):
    before = {name:digest(case/name) for name in ('case.json','counts.json','noc/result.json','ideal_counts.json','receipt.json')}
    fingerprint = {'inputs':before, 'model':{name:digest(ROOT/'archx_config'/name) for name in SOURCES},
                   'archx_file':archx.__file__}
    if (output/'manifest.json').exists():
        previous=load(output/'manifest.json')
        if previous['fingerprint'] != fingerprint: raise ValueError('count checkpoint changed')
        if any(digest(output/n)!=h for n,h in previous['artifacts'].items()): raise ValueError('count artifact changed')
        return
    graph = load_event_graph(str(template))
    graph = simulate_performance_all_events(graph, {}, {'configuration':{'case_dir':str(case)}})
    identity,noc,expected = measurements(str(case))
    variant=identity['arch']+'/'+identity['size']; specs=specifications(variant)
    counted = {k:aggregate_event_count(graph,workload='spad',event=event(k)) for k in specs}
    if counted != expected: raise ValueError('native count graph differs from formulas')
    ideal = load(case/'ideal_counts.json')
    # Every required line spans all COUT channels; all kept COUT sizes are 64-byte multiples.
    raw = load(case/'counts.json')
    if raw['COUT']%64 or ideal['needed_weight_bytes']%64: raise ValueError('ideal DRAM burst alignment requires explicit address enumeration')
    metadata = {'identity':identity,'variant':variant,'specifications':specs,'counts':counted,
                'cycles':noc['total_cycles'],'frequency_MHz':FREQUENCY_MHZ,
                'ideal_needed_weight_bytes':ideal['needed_weight_bytes'],
                'ideal_contract':'native address union independently matched to input support; each full COUT line is a multiple of one 64-byte DRAM burst',
                'provenance':before}
    output.mkdir(parents=True,exist_ok=True)
    save_event_graph(graph,str(output/'counted.graph.json'))
    save(output/'counts.json',metadata)
    if before != {name:digest(case/name) for name in before}: raise ValueError('raw inputs changed during count')
    save(output/'manifest.json',{'fingerprint':fingerprint,'artifacts':{n:digest(output/n) for n in ('counted.graph.json','counts.json')}})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',type=Path); p.add_argument('--out',type=Path)
    args=p.parse_args()
    if os.environ.get('ARCHX_DISABLE_PERFORMANCE_CACHE')!='1': raise ValueError('ARCHX_DISABLE_PERFORMANCE_CACHE=1 is mandatory')
    logger.remove(); logger.add(sys.stderr,level='ERROR')
    print('archx.__file__='+archx.__file__,flush=True)
    cases=[args.case.resolve()] if args.case else [p.parent for p in sorted((ROOT/'outputs/counts').glob('*/*/sample_*/*/receipt.json'))]
    templates={}
    for i,case in enumerate(cases):
        identity=load(case/'case.json'); variant=identity['arch']+'/'+identity['size']
        if variant not in templates:
            templates[variant]=compile_template(case,ROOT/'outputs/archx_templates'/variant)
        output=args.out or ROOT/'outputs/archx_counts'/case.relative_to(ROOT/'outputs/counts')
        count(case,output,templates[variant])
        if (i+1)%120==0: print(f'counted {i+1}/{len(cases)}',flush=True)
    save(ROOT/'outputs/archx_count_summary.json', {'cases':len(cases),'templates':len(templates),'price_free':True,'archx_file':archx.__file__})


if __name__=='__main__':main()
