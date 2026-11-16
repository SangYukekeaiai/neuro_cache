"""Verify complete Figure 1 groups and aggregate whole-model sample energies."""
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SEGMENTS=('compute','on_chip_sram','off_chip_weights','off_chip_other')
BARS=('128k','256k','512k','1m','ideal')
ARCHES=('ptb','loas','gustavsnn')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())
def save(path,data):path.write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n')


def write_csv(path, rows):
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def collect():
    table_path=ROOT/'archx_config/energy_table_asap7_syn.json';table=load(table_path);table_sha=digest(table_path)
    paths=sorted((ROOT/'outputs/priced').glob('*/*/*/sample_*/*/result.json'))
    if len(paths)!=1800:raise ValueError(f'expected 1800 baseline+ideal layer rows, got {len(paths)}')
    groups=defaultdict(list); case_rows=[]; identities=set(); terms=0
    for path in paths:
        row=load(path); identity=(row['arch'],row['bar'],row['sample'],row['layer'])
        if identity in identities:raise ValueError('duplicate case')
        identities.add(identity)
        if row['energy_table_sha256']!=table_sha:raise ValueError('mixed table hashes')
        prices=table['variants'][row['arch']+'/'+row['size']]['operations']
        for key,term in row['breakdown'].items():
            if not math.isclose(term['E_dyn_nJ'],term['count']*prices[key]['dynamic_energy_nJ'],rel_tol=1e-12,abs_tol=1e-18):raise ValueError('term arithmetic')
            if '.psum_sram.' in key or '.vmem_sram.' in key:
                if term['count']!=0 or term['E_dyn_nJ']!=0:raise ValueError('unapproved state boundary')
            terms+=1
        segment_energies={s:row['segments'][s]['E_dyn_nJ']+row['segments'][s]['E_leak_nJ'] for s in SEGMENTS}
        if not math.isclose(sum(segment_energies.values()),row['E_total_nJ'],rel_tol=1e-12):raise ValueError('segment total')
        if any(not math.isfinite(x) or x<0 for x in segment_energies.values()):raise ValueError('nonfinite/negative energy')
        if row['T_s']!=row['total_cycles']/500e6:raise ValueError('time base')
        flat={k:row[k] for k in ('arch','bar','size','sample','layer','E_dyn_nJ','E_leak_nJ','E_total_nJ','T_s','total_cycles')}
        flat.update({s+'_nJ':segment_energies[s] for s in SEGMENTS});flat['table_sha256']=table_sha
        case_rows.append(flat);groups[identity[:3]].append(flat)
    whole=[]
    for arch in ARCHES:
        expected={r['layer'] for r in load(ROOT/f'outputs/manifest/{arch}_256k/manifest.json')['layers']}
        for bar in BARS:
            for sample in range(10):
                rows=groups[(arch,bar,sample)]
                if {r['layer'] for r in rows}!=expected or len(rows)!=12:raise ValueError('incomplete whole model')
                whole.append({'arch':arch,'bar':bar,'sample':sample,'layers':12,
                              **{k:sum(r[k] for r in rows) for k in ('E_dyn_nJ','E_leak_nJ','E_total_nJ','T_s',*[s+'_nJ' for s in SEGMENTS])},
                              'table_sha256':table_sha})
    numbers=[]; critical=2.2621571628540993  # t(9) 97.5th percentile; fixed ten-sample experiment
    for arch in ARCHES:
        baseline=np.array([r['E_total_nJ'] for r in whole if r['arch']==arch and r['bar']=='256k'])
        norm=float(baseline.mean())
        for bar in BARS:
            rows=[r for r in whole if r['arch']==arch and r['bar']==bar]
            for segment in (*SEGMENTS,'total'):
                values=np.array([r['E_total_nJ' if segment=='total' else segment+'_nJ'] for r in rows])
                mean=float(values.mean());ci=float(critical*values.std(ddof=1)/math.sqrt(10))
                numbers.append({'arch':arch,'bar':bar,'segment':segment,'n':10,'layers':12,
                    'mean_energy_nJ':mean,'ci95_halfwidth_nJ':ci,'normalizer_256k_mean_nJ':norm,
                    'normalized_mean':mean/norm,'normalized_ci95_halfwidth':ci/norm,'table_sha256':table_sha})
    before=load(ROOT/'outputs/self_checks/stage_a_before_pricing.json')
    if any(digest(ROOT/n)!=sha for n,sha in before.items()):raise ValueError('Stage A was changed')
    native=load(ROOT/'outputs/count_validation.json')['inventory']
    if any(digest(ROOT/n)!=sha for n,sha in native.items()):raise ValueError('native count input was changed')
    write_csv(ROOT/'outputs/layer_energy.csv',case_rows)
    write_csv(ROOT/'outputs/whole_model_samples.csv',whole)
    write_csv(ROOT/'outputs/fig1_numbers.csv',numbers)
    report={'layer_rows':len(case_rows),'whole_model_samples':len(whole),'bars':15,'terms_rechecked':terms,
            'layers_per_model':12,'samples_per_bar':10,'stage_a_files_unchanged':len(before),
            'native_files_unchanged':len(native),'table_sha256':table_sha,
            'confidence_interval':'Student-t 95%, df=9, over ten whole-model sample energies; fixed normalization by each architecture mean baseline@256KiB, not a CI for a ratio estimator',
            'all_groups_complete':True,'state_sram_dynamic_zero':True,
            'csv_sha256':{n:digest(ROOT/'outputs'/n) for n in ('layer_energy.csv','whole_model_samples.csv','fig1_numbers.csv')}}
    save(ROOT/'outputs/energy_validation.json',report)
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':collect()
