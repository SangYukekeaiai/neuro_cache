"""Authorized one-time operational recovery; no scientific-source edits."""
from pathlib import Path
import fcntl
import json
import shutil
import sys
import time

root=(Path.home()/'snn_edp_stokes_20261114/full500').resolve()
repo=root.parent/'neuro_cache_wcache'
sys.path.insert(0,str(repo/'zoo/fig12_edp/stokes'))
import full500 as f
import stage1_worker as w

with (root/'driver.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    d=f.LOAD(root/'driver_status.json');f.DRIVER=d
    assert d['phase']=='blocked'
    assert all(f.HASH(Path(p))==sha for p,sha in d['scientific_hashes'].items())
    state=d['samples']['24']; indices=[20,24,26,27]
    assert set(state['failures'])==set(map(str,indices))
    assert not state.get('operational_count_retry'), 'bounded retry already used'
    assert not any(s.get('submission_intent') for s in d['samples'].values())
    assert not state['pending'] and all(j.get('reconciled') for j in state['jobs'])
    cfg=w.configure(root/'work/sample_024/config.json')
    entries=w.selection(cfg)
    evidence=root/'recovery_count_timeout/sample_024_recovery'
    evidence.mkdir(parents=True,exist_ok=True)
    if not (evidence/'driver_before.json').exists():
        shutil.copy2(root/'driver_status.json',evidence/'driver_before.json')
    checks={}
    for index in indices:
        case,entry=entries[index];base,scratch=w.paths(cfg,case)
        saved=f.LOAD(base/'attempt_0.json')
        assert saved==state['failures'][str(index)]
        assert saved['status']=='timeout' and saved['attempt']==0 and saved['tier']==2
        assert saved['case']==entry['key'] and w.resources(entry,0)['memory_gib']==120
        assert not (base/'complete.json').exists() and not (base/'counts/manifest.json').exists()
        assert w.inputs(cfg,case)==f.LOAD(base/'inputs.json')
        steps=['generation','numpy_counts','cache_a','cache_b','noc']
        assert all(w.valid_step(base,name) for name in steps)
        assert sorted(p.name for p in (base/'counts').iterdir())==['archx_0.log','request.json']
        checks[str(index)]={'case':entry['key'],'base':str(base),'prior_attempt':saved,
            'step_receipt_sha256':{name:f.HASH(base/'steps'/f'{name}.json') for name in steps},
            'input_fingerprint_sha256':f.HASH(base/'inputs.json'),
            'partial_counts':{p.name:f.HASH(p) for p in (base/'counts').iterdir()}}
        print('preflight_valid',index,entry['key'],flush=True)
    f.SAVE(evidence/'preflight.json',checks)
    for sample in (22,25):
        final=root/'rows'/f'sample_{sample:03d}'
        priced=root/'priced'/f'sample_{sample:03d}'
        if not (final/'commit.json').exists():
            assert f.LOAD(priced/'price_exit.json')['exit_code']==0
            assert f.verify_product(priced,sample)==1677
            if sample==22:
                prior=root/'recovery_price_receipt/sample_022/job_1146811/priced/counts_before.json'
                assert f.HASH(prior)==f.HASH(priced/'counts_before.json')==f.HASH(priced/'counts_after.json')
            print('committing',sample,flush=True)
        f.commit_sample(root,sample,d['samples'][str(sample)])
        f.SAVE(root/'driver_status.json',d)
        print('committed_and_retired',sample,flush=True)
    # Keep a durable authorization record before reopening the four used attempts.
    record={'created_unix':time.time(),'sample':24,'indices':indices,'maximum_operational_retries':1,
            'authority':'T99 manager authorization for operationally analogous bounded retry',
            'reason':'Archx compile TimeoutExpired after generation/counts/cacheA/cacheB/noc completed; no scientific changes',
            'same_resource_tier':{'memory_gib':120,'time_minutes':60},'preflight':checks}
    f.SAVE(evidence/'authorization.json',record)
    for index in indices:
        base=Path(checks[str(index)]['base']);dest=evidence/str(index);dest.mkdir(exist_ok=True)
        for name in ['attempt_0.json','attempt_0.log','counts']:
            source=base/name;target=dest/name
            assert not target.exists(), 'recovery already staged; reconcile, do not repeat'
            source.rename(target)
        assert all(f.HASH(base/'steps'/f'{name}.json')==sha for name,sha in checks[str(index)]['step_receipt_sha256'].items())
        assert f.HASH(base/'inputs.json')==checks[str(index)]['input_fingerprint_sha256']
    state['operational_count_retry']=record
    state['prior_terminal_failures']=state.pop('failures')
    state['pending']=[{'index':index,'attempt':0,'tier':2} for index in indices]
    d.setdefault('operational_recoveries',[]).append({'sample':24,'record':str(evidence/'authorization.json'),'time':time.time()})
    f.SAVE(root/'driver_status.json',d)
    f.SAVE(evidence/'prepared.json',{'indices':indices,'sources_unchanged':True,'existing_steps_unchanged':True,
                                  'committed':[22,25],'finished_unix':time.time()})
    print('RECOVERY_PREPARED',json.dumps({'indices':indices,'committed':[22,25],'evidence':str(evidence)}),flush=True)
