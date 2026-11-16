"""Use existing dynamic counts and per-case runtime brackets for whole-run ideals."""
import csv,json,math
from collections import defaultdict
import numpy as np
from collect_energy import ROOT,SEGMENTS,BARS,ARCHES,load,save,digest,write_csv,collect

ANALYSIS=ROOT/'outputs/self_checks/whole_run_ideal'
CRITICAL=2.2621571628540993

def statistics(values):
    x=np.asarray(values,dtype=float)
    assert len(x)==10
    return float(x.mean()),float(CRITICAL*x.std(ddof=1)/math.sqrt(10))


def interval_statistics(mid,low,high):
    m,c=statistics(mid);lo,lc=statistics(low);hi,hc=statistics(high)
    assert lo<=m+1e-8 and m<=hi+1e-8
    return m,c,lo,hi,min(lo-lc,m-c),max(hi+hc,m+c)


def main():
    base=collect()
    original_numbers=list(csv.DictReader((ROOT/'outputs/fig1_numbers.csv').open()))
    original_whole=list(csv.DictReader((ROOT/'outputs/whole_model_samples.csv').open()))
    bounds=list(csv.DictReader((ANALYSIS/'runtime_bounds_by_case.csv').open()))
    bound_map={(r['arch'],r['size'],int(r['sample']),r['layer']):r for r in bounds}
    predictions=list(csv.DictReader((ANALYSIS/'runtime_prediction.csv').open()))
    for row in predictions:
        sub=[r for r in bounds if (r['arch'],r['size'])==(row['arch'],row['size'])]
        assert len(sub)==120
        for field in ('ideal_runtime_lower_cycles','ideal_runtime_upper_cycles'):
            assert math.isclose(sum(float(r[field]) for r in sub)/10,float(row[field]),rel_tol=1e-12)
    table=load(ROOT/'archx_config/energy_table_asap7_syn.json')
    layers=[];rounding=[];groups=defaultdict(list)
    for path in sorted((ROOT/'outputs/priced').glob('*/*/*/sample_*/*/result.json')):
        row=load(path);arch,size,sample,layer=(row[k] for k in ('arch','size','sample','layer'))
        lo=hi=float(row['total_cycles'])
        if row['bar']=='ideal':
            b=bound_map[arch,size,sample,layer];lo=float(b['ideal_runtime_lower_cycles']);hi=float(b['ideal_runtime_upper_cycles'])
            assert float(b['baseline_cycles'])==row['total_cycles']
            ideal=load(ROOT/f'outputs/counts/{arch}/{size}/sample_{sample:03d}/{layer}/ideal_counts.json')
            words=ideal['needed_weight_words'];packets=math.ceil(words/32);payload=packets*32;bursts=math.ceil(payload/64)
            # Immediate-render instruction retains saved union dynamic counts;
            # SPD packetization applies to that saved aggregate, not cache lines.
            spec=table['variants'][arch+'/'+size]['operations'][arch+'.l1_weight_spad.write']
            expected={'shared.ddr4.read':bursts,'shared.ddr4_io.byte':bursts*64,
                      arch+'.l1_weight_spad.write':payload*8/spec['query']['width']}
            for key,n in expected.items():assert row['breakdown'][key]['count']==n,(key,n)
            rounding.append({'arch':arch,'sample':sample,'layer':layer,'unique_words':words,'spd_packets_32B':packets,
                'payload_bytes':payload,'dram_energy_bursts_64B':bursts,'transfer_grouping':'saved per-layer compulsory union; first-use timing bracketed',
                'dynamic_energy_delta_nJ':0.0})
        mid=(lo+hi)/2
        flat={k:row[k] for k in ('arch','bar','size','sample','layer','E_dyn_nJ')}
        flat.update(total_cycles=mid,cycles_lower=lo,cycles_upper=hi,T_s=mid/500e6,T_s_lower=lo/500e6,T_s_upper=hi/500e6,
                    table_sha256=row['energy_table_sha256'],runtime_kind='analytic_bound_midpoint' if row['bar']=='ideal' else 'simulated')
        leak=0.;total_lower=total_upper=0.
        for seg in SEGMENTS:
            dynamic=row['segments'][seg]['E_dyn_nJ']
            power=sum(m['power_mW'] for m in row['inventory'].values() if m['segment']==seg)
            lower=dynamic+power*lo/500e6*1e6;upper=dynamic+power*hi/500e6*1e6
            value=(lower+upper)/2
            if row['bar']!='ideal':
                # Preserve baseline summation/order and exact numeric values.
                value=row['segments'][seg]['E_dyn_nJ']+row['segments'][seg]['E_leak_nJ'];lower=upper=value
            flat[seg+'_nJ']=value;flat[seg+'_lower_nJ']=lower;flat[seg+'_upper_nJ']=upper
            total_lower+=lower;total_upper+=upper;leak+=value-dynamic
        flat.update(E_leak_nJ=leak,E_total_nJ=(total_lower+total_upper)/2,E_total_lower_nJ=total_lower,E_total_upper_nJ=total_upper)
        if row['bar']!='ideal':
            for k in ('E_leak_nJ','E_total_nJ','T_s','total_cycles'):flat[k]=row[k]
            flat['E_total_lower_nJ']=flat['E_total_upper_nJ']=row['E_total_nJ']
        layers.append(flat);groups[arch,row['bar'],sample].append(flat)
    whole=[]
    fields=('E_dyn_nJ','E_leak_nJ','E_total_nJ','E_total_lower_nJ','E_total_upper_nJ','T_s','T_s_lower','T_s_upper',
            *[s+suffix for s in SEGMENTS for suffix in ('_nJ','_lower_nJ','_upper_nJ')])
    for arch in ARCHES:
        for bar in BARS:
            for sample in range(10):
                rows=groups[arch,bar,sample];assert len(rows)==len({r['layer'] for r in rows})==12
                whole.append({'arch':arch,'bar':bar,'sample':sample,'layers':12,**{k:sum(r[k] for r in rows) for k in fields},
                              'table_sha256':base['table_sha256'],'runtime_kind':rows[0]['runtime_kind']})
    prior={(r['arch'],r['bar'],int(r['sample'])):r for r in original_whole}
    for r in whole:
        if r['bar']!='ideal':
            for k in ('E_dyn_nJ','E_leak_nJ','E_total_nJ','T_s',*[s+'_nJ' for s in SEGMENTS]):assert r[k]==float(prior[r['arch'],r['bar'],r['sample']][k]),k
    numbers=[]
    for arch in ARCHES:
        norm=statistics([r['E_total_nJ'] for r in whole if r['arch']==arch and r['bar']=='256k'])[0]
        for bar in BARS:
            rows=[r for r in whole if (r['arch'],r['bar'])==(arch,bar)]
            for segment in (*SEGMENTS,'total'):
                stem='E_total' if segment=='total' else segment
                m,c,lo,hi,lower,upper=interval_statistics([r[stem+'_nJ'] for r in rows],[r[stem+'_lower_nJ'] for r in rows],[r[stem+'_upper_nJ'] for r in rows])
                numbers.append({'arch':arch,'bar':bar,'segment':segment,'n':10,'layers':12,'mean_energy_nJ':m,
                    'ci95_halfwidth_nJ':c,'normalizer_256k_mean_nJ':norm,'normalized_mean':m/norm,'normalized_ci95_halfwidth':c/norm,
                    'table_sha256':base['table_sha256'],'runtime_bound_mean_lower_nJ':lo,'runtime_bound_mean_upper_nJ':hi,
                    'interval_lower_nJ':lower,'interval_upper_nJ':upper,'normalized_error_lower':(m-lower)/norm,'normalized_error_upper':(upper-m)/norm})
    old={(r['arch'],r['bar'],r['segment']):r for r in original_numbers}
    for row in numbers:
        if row['bar']!='ideal':
            ref=old[row['arch'],row['bar'],row['segment']]
            for k in ('mean_energy_nJ','ci95_halfwidth_nJ','normalized_mean','normalized_ci95_halfwidth'):assert row[k]==float(ref[k]),k
    write_csv(ROOT/'outputs/layer_energy.csv',layers);write_csv(ROOT/'outputs/whole_model_samples.csv',whole);write_csv(ROOT/'outputs/fig1_numbers.csv',numbers)
    write_csv(ANALYSIS/'ideal_transfer_rounding.csv',rounding)
    base.update(ideal_semantics='whole-run runtime bracket; midpoint energy; exact first-use timing unresolved',
        ideal_dynamic_source='existing unique-union counts, SPD 32B packet rounding and existing 64B DRAM energy-burst rounding; no cache-line deduplication',
        ideal_dynamic_transfer_grouping='saved per-layer compulsory union, per boss immediate-render direction; exact first-use transfer grouping is separate pending work',
        ideal_cases_bracketed=360,baseline_bar_segment_rows_unchanged=60,baseline_whole_model_rows_unchanged=120,
        runtime_prediction_sha256=digest(ANALYSIS/'runtime_prediction.csv'),runtime_bounds_sha256=digest(ANALYSIS/'runtime_bounds_by_case.csv'),
        confidence_interval='Baselines: Student-t 95% CI df9. Ideal: midpoint bar; whisker envelope of lower/upper runtime-bound means plus their respective 95% sample CIs (not a confidence interval for exact runtime).',
        csv_sha256={n:digest(ROOT/'outputs'/n) for n in ('layer_energy.csv','whole_model_samples.csv','fig1_numbers.csv')})
    save(ROOT/'outputs/energy_validation.json',base)
    print(json.dumps(base,indent=2))
if __name__=='__main__':main()
