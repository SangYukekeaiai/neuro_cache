"""Re-derive unique touched weights from active coordinates, independent of the native stream."""
from pathlib import Path
import csv
import hashlib
import json
import tarfile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
INPUT=Path('/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_vgg16_T4_n500')
OUTPUT=ROOT/'outputs/self_checks/ideal_dedup_audit'
ARCHES=('ptb','loas','gustavsnn')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())


def unique_lines_from_coordinates(sample, kernel):
    # Each active input coordinate contributes to every valid output window,
    # once per kernel offset/channel, regardless of time or revisit count.
    active=np.any(sample!=0,axis=0)
    ci,ih,iw=np.nonzero(active)
    height,width=sample.shape[-2:];pad=kernel//2
    required=np.zeros((kernel,kernel,sample.shape[1]),dtype=bool)
    for kh in range(kernel):
        for kw in range(kernel):
            oh=ih-kh+pad;ow=iw-kw+pad
            valid=(oh>=0)&(oh<height)&(ow>=0)&(ow<width)
            required[kh,kw,ci[valid]]=True
    return int(required.sum())


def main():
    OUTPUT.mkdir(exist_ok=True)
    archive=OUTPUT/'before.tar.gz'
    if not archive.exists():
        paths=[p for p in (ROOT/'outputs/priced/ideal').rglob('*') if p.is_file()]
        paths += [ROOT/'outputs'/n for n in ('fig1_numbers.csv','whole_model_samples.csv','fig1_energy_profiling.pdf','fig1_energy_profiling.png','figure_provenance.json','caption.txt')]
        with tarfile.open(archive,'w:gz') as tar:
            for path in paths:tar.add(path,arcname=str(path.relative_to(ROOT)))
        (OUTPUT/'before_sha256.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in paths},indent=2,sort_keys=True)+'\n')
    manifest=load(ROOT/'outputs/manifest/gustavsnn_256k/manifest.json')
    records=[];sums={arch:{'unique_words':0,'stream_words':0,'baseline_dram_bytes':0,'ideal_weight_energy_nJ':0} for arch in ARCHES}
    for layer_row in manifest['layers']:
        layer=layer_row['layer'];capture=np.load(INPUT/(layer+'.npy'),mmap_mode='r')
        for sample in range(10):
            ref=ROOT/f'outputs/counts/gustavsnn/256k/sample_{sample:03d}'/layer
            raw=load(ref/'counts.json');selected=capture[:,sample]
            unique=unique_lines_from_coordinates(selected,raw['kernel'])*raw['COUT']
            cross=[]
            for arch in ARCHES:
                case=ROOT/f'outputs/counts/{arch}/256k/sample_{sample:03d}'/layer
                summary=load(case/'ideal_counts.json');noc=load(case/'noc/result.json')
                priced=load(ROOT/f'outputs/priced/ideal/{arch}/256k/sample_{sample:03d}'/layer/'result.json')
                assert unique==summary['needed_weight_words']==summary['needed_weight_bytes']
                terms=priced['breakdown'];assert terms['shared.ddr4.read']['count']*64==unique
                assert terms['shared.ddr4_io.byte']['count']==unique
                width=16*8 if arch=='loas' else 8*8
                assert terms[f'{arch}.l1_weight_spad.write']['count']*width/8==unique
                assert unique<=summary['native_weight_words']
                energy=sum(terms[k]['E_dyn_nJ'] for k in ('shared.ddr4.read','shared.ddr4_io.byte'))
                cross.append(energy)
                records.append({'arch':arch,'layer':layer,'sample':sample,'unique_needed_words':unique,
                    'native_stream_words':summary['native_weight_words'],'baseline_dram_bytes':noc['dram_bytes'],
                    'ideal_dram_bytes':unique,'ideal_offchip_weight_energy_nJ':energy,
                    'unique_count_cross_arch_equal':True})
                sums[arch]['unique_words']+=unique;sums[arch]['stream_words']+=summary['native_weight_words']
                sums[arch]['baseline_dram_bytes']+=noc['dram_bytes'];sums[arch]['ideal_weight_energy_nJ']+=energy
            assert cross[0]==cross[1]==cross[2]
    with (OUTPUT/'per_case.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    assert all(v['unique_words']==118852096 for v in sums.values())
    numbers=list(csv.DictReader((ROOT/'outputs/fig1_numbers.csv').open()))
    report={'cases_checked':len(records),'independent_method':'active input coordinate projection to valid output windows; boolean union of kernel-offset/channel lines, multiplied by all COUT channels',
        'native_dedup':'boolean KH x KW x CIN x COUT union shared across all ticks and tiles',
        'repeat_counting_found':False,'all_architectures_same_absolute_unique_weight_energy':True,
        'comparison_scope':'unique-weight dynamic energy only; timestep-dependent leakage is reported separately in temporal_order/priced_verification.json',
        'archive_sha256':sha(archive),
        'sum_over_12_layers_10_samples':sums,
        'normalization':{arch:{'baseline_256k_mean_nJ':float(next(r['normalizer_256k_mean_nJ'] for r in numbers if r['arch']==arch)),
            'ideal_weight_segment_normalized':float(next(r['normalized_mean'] for r in numbers if r['arch']==arch and r['bar']=='ideal' and r['segment']=='off_chip_weights'))} for arch in ARCHES},
        'conclusion':'The ideal uses unique touched words, not spike-stream retouches. Different normalized heights come from architecture-specific baseline denominators; absolute ideal off-chip weight energy is identical across all three architectures.'}
    (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
