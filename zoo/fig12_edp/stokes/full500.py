"""Stokes-resident ascending campaign; durable rows precede transient retirement."""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime

import stage1_worker as worker
import stage2
import full500_batch as batch

TABLE_SHA = '2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3'
TERMINAL = {'COMPLETED', 'FAILED', 'TIMEOUT', 'OUT_OF_MEMORY', 'CANCELLED', 'NODE_FAIL', 'BOOT_FAIL', 'PREEMPTED', 'DEADLINE'}
SAVE = worker.save
LOAD = worker.load
HASH = worker.digest
QUOTA_FILESYSTEM = '/lustre/fs1'
SAMPLE_BYTES = 70*1024**3
SAMPLE_INODES = 70000
RESERVE_BYTES = 30*1024**3
RESERVE_INODES = 20000
INODE_TRIPWIRE = 850000


def quota_capacity(text):
    lines = [line.split() for line in text.splitlines()]
    rows = [parts for parts in lines if parts and parts[0] == QUOTA_FILESYSTEM]
    if len(rows) != 1 or len(rows[0]) != 9:
        raise ValueError('unrecognized user quota output')
    row = rows[0]
    used, soft, hard, inodes, inode_soft, inode_hard = (
        int(row[i].rstrip('*')) for i in (1, 2, 3, 5, 6, 7))
    byte_limits = [n for n in (soft, hard) if n > 0]
    inode_limits = [n for n in (inode_soft, inode_hard) if n > 0]
    if not byte_limits or not inode_limits or min(used, soft, hard, inodes, inode_soft, inode_hard) < 0:
        raise ValueError('missing or invalid finite user quotas')
    available_bytes = max(0, (min(byte_limits)-used)*1024)
    available_inodes = max(0, min(inode_limits)-inodes)
    capacity = max(0, min(batch.MAX_SAMPLES,
        (available_bytes-RESERVE_BYTES)//SAMPLE_BYTES,
        (available_inodes-RESERVE_INODES)//SAMPLE_INODES))
    return {'capacity': capacity, 'used_bytes': used*1024, 'used_inodes': inodes,
        'available_bytes': available_bytes, 'available_inodes': available_inodes,
        'sample_bytes': SAMPLE_BYTES, 'sample_inodes': SAMPLE_INODES,
        'reserve_bytes': RESERVE_BYTES, 'reserve_inodes': RESERVE_INODES}


def read_quota():
    text = subprocess.check_output(['lfs', 'quota', '-u', str(os.getuid()), QUOTA_FILESYSTEM],
                                   text=True, timeout=15)
    return quota_capacity(text)


def ordered_samples():
    return sorted(DRIVER['samples'].items(), key=lambda item: int(item[0]))


def run(argv):
    return subprocess.check_output(list(map(str, argv)), text=True).strip()


def boundary(root):
    value = LOAD(root/'boundary.json')['max_sample']
    if type(value) is not int or not -1 <= value <= 499:
        raise ValueError('invalid ascending sample boundary')
    return value


def auto_release(root):
    control = LOAD(root/'boundary.json')
    policy = control.get('automatic_release')
    if not policy or policy.get('enabled') is not True:
        return
    limit = control.get('ownership_max_sample')
    if type(limit) is not int or not -1 <= limit <= 499:
        raise ValueError('automatic release requires a valid ownership limit')
    upper = boundary(root)
    if upper >= limit:
        DRIVER['automatic_release'] = {'status': 'ownership_hold', 'limit': limit}
        return
    release = root/'release_after_sample000.json'
    if not release.exists() or LOAD(release).get('approved') is not True:
        DRIVER['automatic_release'] = {'status': 'sample000_hold'}
        return
    consumed = policy['consumed_retirements']
    if not isinstance(consumed, list) or any(type(n) is not int for n in consumed):
        raise ValueError('invalid retirement credit ledger')
    candidates = [int(k) for k, s in ordered_samples()
                  if s['phase'] == 'done' and int(k) not in consumed]
    if not candidates:
        DRIVER['automatic_release'] = {'status': 'awaiting_retirement'}
        return
    try:
        quota = read_quota()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        DRIVER['automatic_release'] = {'status': 'quota_hold', 'error': str(error)}
        return
    active = sum(int(k) <= upper and s['phase'] != 'done' for k, s in ordered_samples())
    if (active >= quota['capacity']
            or quota['available_bytes'] < SAMPLE_BYTES+RESERVE_BYTES
            or quota['available_inodes'] < SAMPLE_INODES+RESERVE_INODES
            or quota['used_inodes']+SAMPLE_INODES+RESERVE_INODES > INODE_TRIPWIRE):
        DRIVER['automatic_release'] = {'status': 'quota_hold', 'quota': quota,
                                       'active_released_samples': active}
        return
    sample = candidates[0]
    tag = f'sample_{sample:03d}'
    final = root/'rows'/tag
    commit = LOAD(final/'commit.json')
    if commit['rows'] != 1677 or commit['sample'] != sample:
        raise ValueError('retirement credit has wrong sample/coverage')
    for name, sha in commit['artifacts'].items():
        path = final/name
        if path.resolve().parent != final.resolve() or HASH(path) != sha:
            raise ValueError('retirement credit artifact changed')
    verify_product(final, sample)
    if any((root/parent/tag).exists() for parent in ('work', 'scratch', 'priced')):
        DRIVER['automatic_release'] = {'status': 'awaiting_retirement_cleanup', 'sample': sample}
        return
    event = {'retired_sample': sample, 'commit_sha256': HASH(final/'commit.json'),
             'from': upper, 'to': upper+1, 'quota': quota, 'time': time.time()}
    # Credit consumption and ceiling advance share one atomic file replacement.
    if LOAD(root/'boundary.json') != control:
        DRIVER['automatic_release'] = {'status': 'control_changed'}
        return
    policy['consumed_retirements'].append(sample)
    policy.setdefault('releases', []).append(event)
    control.update(max_sample=upper+1, updated_unix=event['time'],
                   reason='automatic quota-checked release after verified retirement')
    SAVE(root/'boundary.json', control)
    DRIVER['automatic_release'] = {'status': 'released', **event}


def verify_product(directory, sample, expected=559):
    coverage = LOAD(directory/'coverage.json')
    immutable = LOAD(directory/'immutability.json')
    if not coverage['report_complete'] or coverage['completed_cases'] != expected or coverage['errors']:
        raise ValueError('incomplete sample cannot be retired')
    if coverage['energy_table_sha256'] != TABLE_SHA or not immutable['unchanged']:
        raise ValueError('table or counts changed')
    rows = list(csv.DictReader((directory/'results_ng45.csv').open()))
    keys = {(r['arch'], r['capture'], r['layer'], r['arm']) for r in rows}
    if len(rows) != expected*3 or len(keys) != len(rows):
        raise ValueError('sample row coverage mismatch')
    for row in rows:
        if int(row['sample']) != sample or row['energy_table_sha256'] != TABLE_SHA:
            raise ValueError('sample/table mismatch')
        e = float(row['E_dyn_nJ'])+float(row['E_leak_nJ'])
        import math
        if not math.isclose(float(row['EDP_nJ_s']), e*float(row['T_s']), rel_tol=1e-12):
            raise ValueError('invalid EDP')
    return len(rows)


def commit_sample(root, sample, state):
    tag = f'sample_{sample:03d}'
    stage = root/'work'/tag
    priced = root/'priced'/tag
    final = root/'rows'/tag
    commit = final/'commit.json'
    if not commit.exists():
        verify_product(priced, sample)
        final.mkdir(parents=True, exist_ok=True)
        for source in priced.iterdir():
            if source.is_file():
                shutil.copyfile(source, final/source.name)
        accounting = {'sample': sample, 'jobs': state['jobs'], 'cases': {}}
        cfg = LOAD(stage/'config.json')
        for case in LOAD(cfg['selection'])['cases']:
            base = Path(cfg['output_root'])/case['key']/f'sample_{sample:05d}'
            accounting['cases'][case['key']] = {
                'complete': LOAD(base/'complete.json'),
                'attempts': [LOAD(p) for p in sorted(base.glob('attempt_*.json'))],
                'checkpoint_receipt': LOAD(base/'steps/checkpoint.json')}
        SAVE(final/'accounting.json', accounting)
        verify_product(final, sample)
        files = {p.name: HASH(p) for p in final.iterdir() if p.is_file() and p.name != 'commit.json'}
        for name in files:
            with (final/name).open('rb') as stream: os.fsync(stream.fileno())
        worker.sync_dir(final)
        SAVE(commit, {'sample': sample, 'rows': 1677, 'table_sha256': TABLE_SHA,
                      'artifacts': files, 'committed_unix': time.time()})
    for name, sha in LOAD(commit)['artifacts'].items():
        if HASH(final/name) != sha: raise ValueError('durable product corrupted; retirement refused')
    # Only these sample-owned transient roots are retired, after committed hashes verify.
    for parent in ('work', 'scratch', 'priced'):
        target = root/parent/tag
        if target.exists():
            if target.is_symlink() or target.resolve().parent != (root/parent).resolve():
                raise ValueError('unsafe retirement path')
            shutil.rmtree(target)
            worker.sync_dir(target.parent)
    state.update(phase='done', done_unix=time.time(), rows_sha256=HASH(final/'results_ng45.csv'))


def accounting(job):
    text = run(['sacct', '-j', job['id'], '--array', '-n', '-P', '-o', 'JobID,State,ExitCode,Elapsed,MaxRSS'])
    records = {}
    for line in text.splitlines():
        fields = line.split('|')
        ident = fields[0]
        if '.' in ident or not ident.startswith(job['id']+'_'): continue
        suffix = ident.split('_', 1)[1]
        if suffix.isdigit(): records[int(suffix)] = {'state': fields[1].split()[0].rstrip('+'), 'raw': line}
    array_indices = range(len(job['batches'])) if 'batches' in job else job['indices']
    if not all(i in records and records[i]['state'] in TERMINAL for i in array_indices):
        return None
    if 'batches' in job:
        return {index: {**records[b], 'batch_index': b}
                for b, indices in enumerate(job['batches']) for index in indices}
    return records


def queue_state():
    text = run(['squeue', '-r', '-h', '-u', str(os.getuid()), '-o', '%i|%T|%V|%j'])
    rows = [line.split('|') for line in text.splitlines() if line.strip()]
    waits = []
    for _, state, submitted, name in rows:
        if state == 'PENDING' and name.startswith('f500_s'):
            waits.append(max(0, time.time()-datetime.fromisoformat(submitted).timestamp()))
    return len(rows), max(waits, default=0)


def submit(root, state, sample, indices, attempt, tier, cfg, script, width):
    serial = len(state['jobs'])
    name = f'f500_s{sample:03d}_a{attempt}_t{tier}_{serial}'
    memory = batch.MEMORY_GIB[tier, width]
    minutes = worker.TIERS[tier][1]
    batches = batch.groups(indices, width)
    manifest = cfg.parent/'batches'/f'{name}.json'
    SAVE(manifest, {'config': str(cfg), 'batches': batches, 'attempt': attempt,
                    'tier': tier, 'width': width, 'memory_gib': memory})
    # A saved unresolved intent requires operator reconciliation, never blind resubmission.
    state['submission_intent'] = {'name': name, 'indices': indices, 'time': time.time()}
    SAVE(root/'driver_status.json', DRIVER)
    jobid = run(['sbatch', '--parsable', '--partition=normal', '--account=dwu2', '--qos=normal',
        '--nodes=1', '--ntasks=1', f'--cpus-per-task={width}', '--propagate=NONE',
        f'--job-name={name}', f'--mem={memory}G', f'--time={minutes}',
        f'--array=0-{len(batches)-1}',
        '--output='+str(root/'logs'/f'{name}_%A_%a.log'), script, manifest]).split(';')[0]
    state['jobs'].append({'id': jobid, 'indices': indices, 'attempt': attempt, 'tier': tier,
                          'batches': batches, 'width': width, 'memory_gib': memory,
                          'manifest_sha256': HASH(manifest), 'submitted_unix': time.time()})
    state['pending'] = [item for item in state['pending']
                        if not (item['attempt'] == attempt and item['index'] in indices)]
    state.pop('submission_intent')
    SAVE(root/'driver_status.json', DRIVER)


def prepare(root, sample, base, entries):
    tag = f'sample_{sample:03d}'
    stage = root/'work'/tag
    cfg = {**base, 'sample': sample, 'capture_root': str(root.parent/'input_trace_full500'),
           'output_root': str(stage/'cases'), 'scratch_root': str(root/'scratch'/tag)}
    SAVE(stage/'config.json', cfg)
    return stage/'config.json'


def authorized_heavy_failure(failure):
    parts = failure.get('case', '').split('/')
    return (len(parts) == 4
        and parts[0] in ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity')
        and parts[1:] == ['C01', 'sma_azo_vgg_dvs128_gesture_T16_n500', 'layer_03_core_block4_0_0']
        and failure.get('memory_gib') == 120 and failure.get('tier') == 2
        and failure.get('retry') is None
        and (failure.get('status') == 'oom'
             or (failure.get('status') == 'timeout' and failure.get('timeout_seconds') == 3600)))


def progress(root, sample, state, base, entries, script):
    if state['phase'] == 'done': return
    if (root/'rows'/f'sample_{sample:03d}'/'commit.json').exists():
        commit_sample(root,sample,state); return
    cfgpath = root/'work'/f'sample_{sample:03d}'/'config.json'
    if state['phase'] == 'new':
        if sample > boundary(root): return
        cfgpath = prepare(root, sample, base, entries)
        state['pending'] = [{'index': i, 'attempt': 0, 'tier': worker.initial_tier(e)}
                            for i,e in enumerate(entries)]
        state['phase'] = 'counting'
    if state['phase'] == 'counting':
        retry = {}
        for job in list(state['jobs']):
            if job.get('reconciled'): continue
            records = accounting(job)
            if records is None: continue
            for index, rec in records.items():
                cfg = LOAD(cfgpath)
                basepath = Path(cfg['output_root'])/entries[index]['key']/f'sample_{sample:05d}'
                path = basepath/f"attempt_{job['attempt']}.json"
                if not (basepath/'complete.json').exists():
                    result = LOAD(path) if path.exists() else {}
                    if result.get('status') == 'running' or not result:
                        outcome = {'OUT_OF_MEMORY':'oom', 'TIMEOUT':'timeout'}.get(rec['state'], 'failed')
                        result = {**result, **worker.failure_status(outcome, entries[index], job['attempt']),
                                  'scheduler_accounting':rec, 'finished_unix':time.time()}
                        SAVE(path,result)
                    if result.get('retry'):
                        tier = result['retry']['tier']
                        retry.setdefault(tier, []).append(index)
                    else:
                        state.setdefault('failures', {})[str(index)] = result
            job.update(reconciled=True, accounting=records)
        for tier, indices in retry.items():
            state['pending'].extend({'index': i, 'attempt': 1, 'tier': tier} for i in indices)
        if not state['pending'] and all(j.get('reconciled') for j in state['jobs']):
            if state.get('failures'):
                for key, failure in state['failures'].items():
                    if authorized_heavy_failure(failure):
                        state.setdefault('quarantined_failures', {})[key] = dict(failure)
                        state.setdefault('quarantine_authority', {}).setdefault(key, {
                            'reason': 'manager-authorized C01 gesture layer03 terminal 120GiB failure; no extra retry',
                            'recorded_unix': time.time()})
                approved = state.get('quarantined_failures', {})
                if any(approved.get(key) != failure for key, failure in state['failures'].items()):
                    raise RuntimeError(f'sample {sample}: terminal failures; checkpoints retained')
                state['phase'] = 'quarantined'
                return
            state['phase'] = 'ready_to_price'
    if state['phase'] == 'pricing':
        receipt = root/'priced'/f'sample_{sample:03d}'/'price_exit.json'
        if receipt.exists():
            if LOAD(receipt)['exit_code'] != 0: raise RuntimeError('pricing failed; evidence retained')
            commit_sample(root, sample, state)
        elif state['price_job'] not in run(['squeue', '-h', '-u', str(os.getuid()), '-o', '%i']).splitlines():
            records = run(['sacct', '-n', '-P', '-j', state['price_job'],
                           '-o', 'JobID,State,ExitCode'])
            parents = [r.split('|') for r in records.splitlines()
                       if r.split('|')[0] == state['price_job']]
            if len(parents) == 1 and parents[0][1] in TERMINAL:
                retry_missing_price_receipt(root, sample, state, parents[0])


def retry_missing_price_receipt(root, sample, state, accounting):
    job, status, exit_code = accounting[:3]
    if not (status == 'TIMEOUT' or (status == 'COMPLETED' and exit_code == '0:0')):
        raise RuntimeError('pricing job ended without durable exit receipt: ' + '|'.join(accounting))
    retries = state.setdefault('price_receipt_retries', [])
    if retries and retries[-1]['job'] != job:
        raise RuntimeError('pricing retry ended without durable exit receipt; evidence retained')
    archive = root/'recovery_price_receipt'/f'sample_{sample:03d}'/f'job_{job}'/'priced'
    if not retries:
        retries.append({'job': job, 'accounting': accounting, 'archive': str(archive),
                        'recorded_unix': time.time(), 'reason': 'missing durable pricing exit receipt'})
        # Persist the retry credit before moving outputs or issuing another job.
        SAVE(root/'driver_status.json', DRIVER)
    output = root/'priced'/f'sample_{sample:03d}'
    if output.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            raise RuntimeError('pricing recovery archive already exists alongside output')
        output.rename(archive)
    state.update(phase='ready_to_price', price_time_minutes=120 if status == 'TIMEOUT' else 60)
    SAVE(root/'driver_status.json', DRIVER)


def price_submit(root, sample, state, script):
    name = f'f500_price_{sample:03d}'
    state['submission_intent'] = {'name': name, 'time': time.time()}
    SAVE(root/'driver_status.json', DRIVER)
    state['price_job'] = run(['sbatch','--parsable','--partition=normal','--account=dwu2','--qos=normal',
        '--nodes=1','--ntasks=1','--cpus-per-task=2','--mem=8G',
        '--time='+str(state.get('price_time_minutes',60)),'--propagate=NONE',
        '--job-name='+name,'--output='+str(root/'logs'/f'{name}_%j.log'), script, root, sample]).split(';')[0]
    state.pop('submission_intent'); state['phase']='pricing'
    SAVE(root/'driver_status.json', DRIVER)


def admit_samples(root):
    released = ((root/'release_after_sample000.json').exists()
                and LOAD(root/'release_after_sample000.json').get('approved') is True)
    if DRIVER['samples'].get('0', {}).get('phase') == 'done' and not released:
        DRIVER['phase'] = 'held_after_sample000'
        return
    upper = boundary(root) if released else min(0, boundary(root))
    active = sum(s['phase'] != 'done' for s in DRIVER['samples'].values())
    try:
        quota = read_quota()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        quota = {'capacity': 0, 'error': str(error)}
    DRIVER['quota_admission'] = {**quota, 'checked_unix': time.time(),
        'active_samples': active, 'admissions_held': active >= quota['capacity']}
    next_sample = max(map(int, DRIVER['samples']), default=-1)+1
    while active < quota['capacity'] and next_sample <= upper:
        block = next_sample//10
        if block not in DRIVER['claimed_blocks']: DRIVER['claimed_blocks'].append(block)
        DRIVER['samples'][str(next_sample)] = {'phase': 'new', 'jobs': []}
        active += 1; next_sample += 1
    DRIVER['quota_admission'].update(active_samples=active,
                                    admissions_held=active >= quota['capacity'])
    DRIVER['phase'] = 'running' if active else 'boundary_hold'
    if not active and next_sample <= upper and quota['capacity'] == 0:
        DRIVER['phase'] = 'quota_admission_hold'


def dispatch(root, script, pricescript):
    occupied, pending_seconds = queue_state()
    DRIVER['scheduler'] = {'owned_jobs': occupied, 'oldest_pending_seconds': pending_seconds,
        'batch_widths': [batch.batch_width(tier, pending_seconds) for tier in range(3)]}
    # Pricing has admission priority; one slot stays free for the next finished sample.
    for key, state in ordered_samples():
        if state['phase'] == 'ready_to_price' and occupied < batch.MAX_JOBS:
            price_submit(root, int(key), state, pricescript); occupied += 1
    slots = max(0, batch.MAX_JOBS-1-occupied)
    for key, state in ordered_samples():
        if state['phase'] != 'counting' or int(key) > boundary(root): continue
        cfg = root/'work'/f'sample_{int(key):03d}'/'config.json'
        # Start the long-memory cases early; each batch retains its own tier.
        for attempt in (1, 0):
            for tier in (2, 1, 0):
                if not slots: return
                width = batch.batch_width(tier, pending_seconds)
                indices = [p['index'] for p in state['pending']
                           if p['attempt'] == attempt and p['tier'] == tier][:slots*width]
                if indices:
                    submit(root, state, int(key), indices, attempt, tier, cfg, script, width)
                    slots -= len(batch.groups(indices, width))


def price_mode(root, sample):
    output = root/'priced'/f'sample_{sample:03d}'
    table = worker.REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json'
    if HASH(table) != TABLE_SHA: raise ValueError('NG45 table pin changed')
    try:
        stage2.run(root/'work'/f'sample_{sample:03d}', table, output,
                   confirmed_drained=True, workers=2, pricing_profile='nangate45')
    except BaseException:
        SAVE(output/'price_exit.json', {'exit_code': 1}); raise
    SAVE(output/'price_exit.json', {'exit_code': 0})


def main():
    global DRIVER
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--price',type=int)
    args=parser.parse_args(); root=args.root.resolve()
    if args.price is not None: return price_mode(root,args.price)
    root.mkdir(parents=True,exist_ok=True)
    lock=(root/'driver.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    (root/'logs').mkdir(exist_ok=True)
    base=LOAD(root/'base_config.json'); entries=LOAD(base['selection'])['cases']
    sys.path.insert(0,str(worker.REPO/'zoo/fig12_edp'))
    from energy_driver import check_cache_configs
    check_cache_configs(*(Path(base['repo'])/base['cache_'+arm] for arm in ('a','b')))
    scientific_files=[Path(__file__), Path(batch.__file__), Path(worker.__file__), Path(stage2.__file__),
        Path(base['repo'])/'zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json']
    scientific_hashes={str(p):HASH(p) for p in scientific_files}
    if HASH(scientific_files[-1]) != TABLE_SHA: raise ValueError('NG45 table pin changed')
    if len(entries)!=559: raise ValueError('559 kept cases required')
    statefile=root/'driver_status.json'
    DRIVER=LOAD(statefile) if statefile.exists() else {'samples':{},'claimed_blocks':[], 'started_unix':time.time()}
    if any(s.get('submission_intent') for s in DRIVER['samples'].values()):
        raise RuntimeError('unresolved sbatch intent; reconcile before restarting')
    if DRIVER.get('scientific_hashes', scientific_hashes) != scientific_hashes:
        raise ValueError('controller/worker/pricing sources changed; reconcile before resume')
    DRIVER['scientific_hashes']=scientific_hashes
    DRIVER.pop('error', None)
    DRIVER.update(pid=os.getpid(),host=os.uname().nodename,phase='waiting_for_inputs')
    script=root/'batch.sbatch'; pricescript=root/'price.sbatch'
    try:
        while True:
            DRIVER['updated_unix']=time.time()
            if not (root/'staging/ALL_READY').exists() or not (root/'fixture_gate.json').exists():
                SAVE(statefile,DRIVER); time.sleep(30); continue
            if not LOAD(root/'fixture_gate.json')['passed']: raise RuntimeError('fixture gate failed')
            for key,state in ordered_samples():
                progress(root,int(key),state,base,entries,script)
                SAVE(statefile,DRIVER)
            auto_release(root)
            admit_samples(root)
            dispatch(root, script, pricescript)
            DRIVER['free_bytes']=shutil.disk_usage(root).free
            if DRIVER['free_bytes']<30*1024**3: raise RuntimeError('less than 30 GiB free; submission held')
            SAVE(statefile,DRIVER)
            time.sleep(30)
    except BaseException as error:
        DRIVER.update(phase='blocked',error=repr(error),updated_unix=time.time())
        SAVE(statefile,DRIVER); raise


if __name__=='__main__': main()
