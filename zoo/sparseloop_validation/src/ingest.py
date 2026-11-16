"""S0 only: snapshot external inputs; subsequent stages use this directory alone."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from measure_density import measure
from extract_real_counts import extract

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--traces',type=Path,required=True)
    args=parser.parse_args(); out=ROOT/'inputs';out.mkdir(exist_ok=True)
    assert not (out/'snapshot_manifest.json').exists(), 'S0 already sealed'
    sources={}; copies={}
    def record(source):
        source=source.resolve(); digest=sha(source)
        sources[str(source)]={'sha256':digest,'bytes':source.stat().st_size}
        return digest
    def copy(source, dest):
        digest=record(source);target=out/dest;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);assert sha(target)==digest
        copies[str(target.relative_to(out))]={'source':str(source.resolve()),'sha256':digest}
    repo=args.repo.resolve()
    copy(repo/'zoo/wt500_fig3cfg/outputs/manifest.json','schedule_manifest.json')
    copy(repo/'zoo/wt500_fig3cfg/arch.yaml','campaign_arch.yaml')
    copy(repo/'zoo/wt500_fig3cfg/mapspaces/loas.yaml','campaign_mapspace.yaml')
    copy(repo/'zoo/archx/zoo/snn_edp/hardware.json','hardware.json')
    for name in ('energy_table_asap7_syn.json','table_manifest.json'):
        copy(repo/'zoo/fig1_energy_profiling/archx_config'/name,name)
    copy(args.traces/'meta.json','trace_meta.json')
    manifest=json.loads((out/'schedule_manifest.json').read_text())
    schedules=[x for x in manifest['schedules'] if x['arch']=='loas' and x['trace_relative_dir']=='B09/loas_vgg16_T4_n500' and not x['layer'].endswith('classifier')]
    assert len(schedules)==12
    layers={}
    for entry in schedules:
        dest='schedules/'+entry['layer']+'.json'
        copy(repo/'zoo/wt500_fig3cfg/outputs'/entry['schedule_path'],dest)
        assert sha(out/dest)==entry['schedule_sha256']
        assert entry['arch_yaml_sha256']==sha(out/'campaign_arch.yaml')
        layers[entry['layer']]={'problem':entry['workload']['problem'],'schedule':dest}
    (out/'layer_set.json').write_text(json.dumps(layers,indent=2,sort_keys=True)+'\n')
    samples,cases=extract(repo/'zoo/fig12_edp/stokes/full500_rows_fetch_20261116/rows',layers,out,record)
    density=measure(args.traces,layers,samples,out,record)
    # Freeze the executable sources now so Tier B needs no imports from another task.
    roots=[repo/'src/lays',repo/'zoo/fig12_edp/nocsim',repo/'zoo/fig12_edp/counts']
    for base in roots:
        for source in sorted(base.rglob('*')):
            if not source.is_file() or '__pycache__' in source.parts:continue
            if source.suffix not in ('.py','.h','.hpp','.c','.cc','.cpp','.yaml','.json') and source.name not in ('Makefile',):continue
            if source.name.startswith('test_') or 'validation' in source.name:continue
            copy(source,Path('runtime')/source.relative_to(repo))
    files={str(p.relative_to(out)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()}
    report={'schema':'t100_snapshot_v1','arch':'loas','samples':samples,'layers':12,'real_cases':len(cases),'density_rows':len(density),
            'captured_utc':datetime.now(timezone.utc).isoformat(),'external_sources':sources,'copies':copies,'files':files,
            'raw_spikes':'Lossless selected real samples retained for actual-data masks; no post-S0 trace reads required.',
            'count_extraction':'spad only; NG45 energy discarded; original operation counts and cycles preserved',
            'sealed':True}
    (out/'snapshot_manifest.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'sources':len(sources),'files':len(files),'cases':len(cases),'density_rows':len(density),'samples':samples}),flush=True)

if __name__=='__main__':main()
