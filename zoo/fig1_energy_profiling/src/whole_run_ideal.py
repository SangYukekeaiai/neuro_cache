"""Native-tick on-demand unique-weight supplier, replayed by unchanged nocsim."""
import argparse,csv,hashlib,importlib,json,math,shutil,tempfile
from pathlib import Path
import numpy as np
from lays.nocsim.sim import run_eventsim
from lays.nocsim.step_cycles import load_step_cycles
from lays.parsers.bitwidths import SNNBitwidths
from lays.weight_trace_gen.weight_trace import load_schedule,reconstruct_samples,node_level_spatial_product
from zoo.fig12_edp.nocsim.energycounts import parse_tc_csv
from count_case import digest,save,REPO
from contracts import require_no_gb
from schedule_spec import ROOT


def first_uses(native):
    dims=native.workload_dims; seen=np.zeros(math.prod(dims[d] for d in ('KH','KW','CIN','COUT')),dtype=bool);events=[];work=[]
    for tile in native.tiles:
        uses=[];previous=-1
        for tick in tile.ticks:
            assert previous<tick.tick<tile.mac_cycles
            previous=tick.tick;fresh=[];new_words=0
            for core in tick.cores:
                assert core.core_id==0
                for kh,kw,ci,start,end in core.weight_addresses:
                    base=((kh*dims['KW']+kw)*dims['CIN']+ci)*dims['COUT']
                    assert 0<=start<end<=dims['COUT']
                    first=base+start;last=base+end
                    local=~seen[first:last]
                    edges=np.flatnonzero(np.diff(np.r_[False,local,False].astype(np.int8)))
                    fresh.extend([[first+int(a),first+int(b)] for a,b in zip(edges[::2],edges[1::2])])
                    new_words+=int(local.sum());seen[first:last]=True
            if new_words:
                uses.append({'tick':tick.tick,'word_spans':fresh,'words':new_words})
        events.append({'dram_i':tile.dram_i,'noc_i':tile.noc_i,'mac_cycles':tile.mac_cycles,
                       'lif_cycles':tile.lif_cycles or 0,'first_uses':uses})
        work.append((tile.dram_i,tile.noc_i,tile.mac_cycles,tile.lif_cycles or 0))
    return events,int(seen.sum()),work


def write_stream(events,path,dram_port):
    """A blocking first use delays only following native work; no future-demand prefetch."""
    last=None;index=0;compute=0;packets=[]
    with path.open('w',newline='') as f:
        writer=csv.writer(f)
        def emit(label,actor,op,size,dest=''):
            nonlocal last,index
            f.write('# '+label+'\n')
            writer.writerow([index,actor,op,size,actor,dest,'' if last is None else last])
            last=index;index+=1
        for e in events:
            stem=f"{e['dram_i']}_{e['noc_i']}";cursor=0;part=0
            for use in e['first_uses']:
                delta=use['tick']-cursor
                if delta:
                    emit(f'mac_{stem}__count_0_part_{part}',0,2,delta);compute+=delta;part+=1
                n=(use['words']+31)//32;packets.append(n)
                emit(f'weight_{stem}__first_use_{use["tick"]}',dram_port,0,n,0)
                cursor=use['tick']
            tail=e['mac_cycles']-cursor
            emit(f'mac_{stem}__count_0_part_{part}',0,2,tail);compute+=tail
            emit(f'lif_{stem}__count_0',0,2,e['lif_cycles']);compute+=e['lif_cycles']
    return compute,packets


def run(case,trace_root,out,manifest_root=None):
    identity=json.loads((case/'case.json').read_text());arch=identity['arch'];size=identity['size'];sample=identity['sample'];layer=identity['layer']
    assert size=='256k'
    manifest_path=(manifest_root or ROOT/'outputs/manifest')/f'{arch}_{size}/manifest.json';manifest=json.loads(manifest_path.read_text())
    row,=[x for x in manifest['layers'] if x['layer']==layer]
    schedule=ROOT/row['schedule'];config=ROOT/manifest['arch_path']
    assert digest(schedule)==row['schedule_sha256'] and digest(config)==manifest['arch_sha256']
    receipt=json.loads((case/'receipt.json').read_text())
    for n,h in receipt['artifacts'].items():assert digest(case/n)==h,n
    binary=REPO/'src/lays/nocsim/eventsim/eventsim'
    inputs={'baseline_receipt_sha256':digest(case/'receipt.json'),'worker_sha256':digest(Path(__file__)),
            'eventsim_sha256':digest(binary),'manifest_sha256':digest(manifest_path)}
    out.mkdir(parents=True,exist_ok=True)
    if (out/'receipt.json').exists():
        prior=json.loads((out/'receipt.json').read_text());assert prior['inputs']==inputs
        for n,h in prior['artifacts'].items():assert digest(out/n)==h,n
        return prior
    scratch=out/'scratch';scratch.mkdir(exist_ok=True);tempfile.tempdir=str(scratch)
    capture=np.load(trace_root/manifest['capture_relative_dir']/(layer+'.npy'),mmap_mode='r')
    selected=np.ascontiguousarray(capture[:,sample:sample+1])
    assert hashlib.sha256(selected.tobytes()).hexdigest()==receipt['inputs']['capture_sample_sha256']
    module=importlib.import_module(f'lays.weight_trace_gen.{arch}.native_bridge')
    assert digest(module._BINARY)==receipt['inputs']['generator_sha256']
    artifact,_,tiles=load_schedule(schedule)
    options={'wave_width':node_level_spatial_product(artifact.result['strategy'])} if arch=='gustavsnn' else {}
    native,=reconstruct_samples(arch,selected,tiles,[0],artifact.trace_dir,layer,artifact.workload['problem'],artifact.dram_num_steps,**options)
    events,words,work=first_uses(native);del native
    steps=load_step_cycles(case/'step_cycles.json.gz')
    assert work==[(d,n,c.mac_cycles,c.lif_cycles or 0) for (d,n),c in sorted(steps.by_step.items())]
    ideal=json.loads((case/'ideal_counts.json').read_text());assert words==ideal['needed_weight_bytes']
    prior_noc=json.loads((case/'noc/result.json').read_text());topology=prior_noc['topology']
    assert topology['X']==topology['Y']==1
    (out/'noc').mkdir(exist_ok=True)
    tc=out/'noc/tc.csv';C,packets=write_stream(events,tc,topology['dram_port'])
    widths=SNNBitwidths(config);D=sum(math.ceil(p*widths.dram_latency) for p in packets)
    counts=parse_tc_csv(tc,**topology);require_no_gb(counts)
    latency=run_eventsim(tc,topology['X'],topology['Y'],topology['dram_port'],widths.dram_latency,binary=binary)
    assert latency['count_cycles']==C==prior_noc['eventsim']['count_cycles']
    assert latency['dram_cycles']==D and latency['total_cycles']==C+D
    assert counts['dram_payload_bytes']==counts['l1_delivery_bytes']==sum(packets)*32
    assert counts['dram_bytes']==sum((p*32+63)//64*64 for p in packets)
    assert counts['dram_payload_bytes']>=words
    noc={**prior_noc,**counts,'eventsim':latency,'total_cycles':latency['total_cycles'],
         'time_seconds':latency['total_cycles']/prior_noc['frequency_hz'],'tc_sha256':digest(tc),
         'inputs':inputs,'execution':'whole_run_ideal','supplier':'blocking first-use at native tick; unique words, native 32B packets; no future-demand prefetch; per-transaction native DRAM rounding'}
    save(out/'noc/result.json',noc)
    save(out/'first_uses.json',{'packet_bytes':32,'dram_energy_burst_bytes':64,'events':events,'unique_words':words,'packet_padding_bytes':counts['dram_payload_bytes']-words,'energy_burst_padding_bytes':counts['dram_bytes']-counts['dram_payload_bytes'],'native_cycles':C,'dram_cycles':D})
    save(out/'case.json',{**identity,'execution':'whole_run_ideal'})
    for name in ('counts.json','ideal_counts.json'):shutil.copy2(case/name,out/name)
    names=('case.json','counts.json','ideal_counts.json','noc/result.json','noc/tc.csv','first_uses.json')
    result={'status':'complete','inputs':inputs,'artifacts':{n:digest(out/n) for n in names},
            'native_compute_unchanged':True,'unique_words':words,'total_cycles':latency['total_cycles'],
            'baseline_cycles':prior_noc['total_cycles'],'price_free':True,'zero_gb':True}
    save(out/'receipt.json',result);shutil.rmtree(scratch)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',type=int,required=True);p.add_argument('--trace-root',type=Path,required=True)
    p.add_argument('--cases',type=Path,default=ROOT/'configs/cases.json')
    p.add_argument('--counts-root',type=Path,default=ROOT/'outputs/counts')
    p.add_argument('--out-root',type=Path,default=ROOT/'outputs/whole_run_ideal/counts')
    p.add_argument('--manifest-root',type=Path,default=ROOT/'outputs/manifest')
    a=p.parse_args()
    cases=[x for x in json.loads(a.cases.read_text()) if x['size']=='256k']
    if a.cases.name=='cases.json':assert len(cases)==360
    c=cases[a.index];rel=Path(c['arch'])/c['size']/f'sample_{c["sample"]:03d}'/c['layer']
    result=run(a.counts_root/rel,a.trace_root,a.out_root/rel,a.manifest_root)
    print(json.dumps({k:v for k,v in result.items() if k!='artifacts'}),flush=True)
if __name__=='__main__':main()
