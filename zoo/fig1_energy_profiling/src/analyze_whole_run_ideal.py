"""Coverage and contention bounds from frozen baseline counts, before ideal replay."""
import csv,json,hashlib,math
import yaml
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/self_checks/whole_run_ideal'
load=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,rows):
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
 OUT.mkdir(exist_ok=True)
 coverage=[];whole=[];runtime=[];details=[]
 for arch in ('ptb','loas','gustavsnn'):
  manifest=load(ROOT/f'outputs/manifest/{arch}_256k/manifest.json')
  for layer in manifest['layers']:
   unique=[];total=layer['compulsory_weight_bytes']
   for sample in range(10):
    case=ROOT/f'outputs/counts/{arch}/256k/sample_{sample:03d}'/layer['layer']
    unique.append(load(case/'ideal_counts.json')['needed_weight_words'])
   coverage.append({'arch':arch,'layer':layer['layer'],'samples':10,'total_weight_words':total,
     'unique_words_mean':sum(unique)/10,'unique_words_min':min(unique),'unique_words_max':max(unique),
     'coverage_mean':sum(unique)/(10*total),'coverage_min':min(unique)/total,'coverage_max':max(unique)/total})
  sub=[x for x in coverage if x['arch']==arch]
  total=sum(x['total_weight_words'] for x in sub);unique=sum(x['unique_words_mean'] for x in sub)
  whole.append({'arch':arch,'total_weight_words':total,'unique_words_mean':unique,'weighted_coverage':unique/total})
  for size in ('128k','256k','512k','1m'):
   sums=defaultdict(float)
   size_rows={x['layer']:x for x in load(ROOT/f'outputs/manifest/{arch}_{size}/manifest.json')['layers']}
   dram_latency=yaml.safe_load((ROOT/f'arch/{arch}_{size}.yaml').read_text())['arch']['bitwidths']['DRAM_LATENCY']
   for sample in range(10):
    for layer in manifest['layers']:
     case=ROOT/f'outputs/counts/{arch}/{size}/sample_{sample:03d}'/layer['layer']
     n=load(case/'noc/result.json');e=n['eventsim'];u=load(case/'ideal_counts.json')['needed_weight_bytes']
     assert n['frequency_hz']==500000000 and n['topology']['X']==n['topology']['Y']==1
     C,D,T=e['count_cycles'],e['dram_cycles'],e['total_cycles']
     assert max(C,D)<=T<=C+D
     packet=n['units']['gb_access_bytes'];assert packet==32
     width=size_rows[layer['layer']]['resident_cout'];assert u%width==0
     dlo=math.ceil(math.ceil(u/packet)*dram_latency)
     dhi=(u//width)*math.ceil(math.ceil(width/packet)*dram_latency)
     bounds={'baseline_cycles':T,'native_compute_cycles':C,'dram_occupancy_cycles':D,
                 'exposed_stall_cycles':T-C,'overlapped_cycles':C+D-T,
                 'ideal_dram_lower_cycles':dlo,'ideal_dram_upper_cycles':dhi,
                 'ideal_runtime_lower_cycles':C+dlo,'ideal_runtime_upper_cycles':C+dhi}
     details.append({'arch':arch,'size':size,'sample':sample,'layer':layer['layer'],**bounds})
     for k,v in bounds.items():sums[k]+=v/10
   out={'arch':arch,'size':size,**dict(sums)}
   out['native_compute_fraction']=out['native_compute_cycles']/out['baseline_cycles']
   out['ideal_runtime_ratio_lower']=out['ideal_runtime_lower_cycles']/out['baseline_cycles']
   out['ideal_runtime_ratio_upper']=out['ideal_runtime_upper_cycles']/out['baseline_cycles']
   row=load(ROOT/f'outputs/priced/baseline/{arch}/{size}/sample_000/{manifest["layers"][0]["layer"]}/result.json')
   power=sum(m['power_mW'] for m in row['inventory'].values() if m['segment']=='off_chip_other')
   for label,field in [('baseline','baseline_cycles'),('ideal_lower','ideal_runtime_lower_cycles'),('ideal_upper','ideal_runtime_upper_cycles')]:out[f'{label}_grey_mJ']=power*out[field]/500e6
   runtime.append(out)
 write('weight_coverage.csv',coverage);write('weight_coverage_aggregate.csv',whole);write('runtime_prediction.csv',runtime);write('runtime_bounds_by_case.csv',details)
 lines=['# Whole-run ideal: pre-execution analysis','','Coverage is the unique touched union divided by all kernel weights, averaged over samples 000–009. All weights are one byte. The union is independent of architecture and weight capacity.','','| Layer | All weights | Mean unique | Coverage | Sample coverage range |','|---|---:|---:|---:|---:|']
 for x in coverage[:12]:lines.append(f"| {x['layer']} | {x['total_weight_words']:,} | {x['unique_words_mean']:,.1f} | {x['coverage_mean']:.2%} | {x['coverage_min']:.2%}–{x['coverage_max']:.2%} |")
 lines+=['',f"Weighted aggregate: {whole[0]['weighted_coverage']:.4%}; {whole[0]['unique_words_mean']:,.1f} unique of {whole[0]['total_weight_words']:,} total words per sample. The CSV lists all 36 architecture/layer rows.",'','Runtime bounds preserve every native compute COUNT. On one node, compute occupancy C is serial; exposed stalls are total−C, and overlapped occupancy is C+D−total. Ideal deduplication is by word, not cache line. Each native first-use tick groups its new words into an SPD transfer: ceil(words/32) packets, then ceil(packets×0.25) occupancy cycles. The bound spans one aggregate transfer through separate native COUT-span transfers; COUT span is taken from each size/layer manifest. Blocking first-use replay finishes between C+D_lower and C+D_upper. The existing 64-byte DRAM energy-accounting burst rounds each transfer independently; it is not a cache line or the deduplication unit. These are predictions, not simulated ideal results.','','| Architecture | Weight SRAM | Baseline ms | Compute fraction | Ideal runtime / baseline bound | Baseline gray mJ | Ideal gray mJ bound |','|---|---|---:|---:|---:|---:|---:|']
 for x in runtime:lines.append(f"| {x['arch']} | {x['size']} | {x['baseline_cycles']/500e3:.5f} | {x['native_compute_fraction']:.2%} | {x['ideal_runtime_ratio_lower']:.4f}–{x['ideal_runtime_ratio_upper']:.4f} | {x['baseline_grey_mJ']:.6f} | {x['ideal_lower_grey_mJ']:.6f}–{x['ideal_upper_grey_mJ']:.6f} |")
 lines+=['','Gray is standing DDR4/IO leakage. Its energy follows duration; no non-weight DRAM dynamic stream is introduced. Every capacity is analyzed; the plotted ideal retains the 256 KiB geometry unless otherwise directed.']
 (OUT/'PRE_EXECUTION.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'coverage':whole,'runtime':[{'arch':x['arch'],'size':x['size'],'compute_fraction':x['native_compute_fraction'],'ideal_ratio_bound':[x['ideal_runtime_ratio_lower'],x['ideal_runtime_ratio_upper']]} for x in runtime]},indent=2))
if __name__=='__main__':main()
