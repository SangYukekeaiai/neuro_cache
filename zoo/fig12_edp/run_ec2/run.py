"""No-Slurm, sample-first campaign queue with bounded reservations and owned workers."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from config import (GIB, HERE, digest, environment, folder, key, load, save,
                    scientific_inputs, select)
from pipeline import cleanup_scratch, run_case, validate_result
from collect import collect_sample
from shards import validate_checkpoint, verify_unlock

STOP = False


def reserve_tier(estimate, cfg):
    return next((t for t in cfg['memory_tiers_gib'] if t >= estimate), None)


def next_tier(previous, cfg):
    return next((t for t in cfg['memory_tiers_gib'] if t > previous), None)


def can_start(limit, active_limits, cfg):
    if limit is None or sum(active_limits)+limit+cfg['driver_reserve_gib'] > cfg['memory_budget_gib']:
        return False
    if len(active_limits) >= cfg['workers']:
        return False
    if active_limits and (limit >= cfg['serial_at_gib'] or max(active_limits) >= cfg['serial_at_gib']):
        return False
    return True


def event(cfg, name, **fields):
    with (Path(cfg['output'])/'events.jsonl').open('a') as stream:
        stream.write(json.dumps({'time': time.time(), 'event': name, **fields})+'\n')
        stream.flush(); os.fsync(stream.fileno())


def terminate(process):
    # The process was started in a new session by this driver; never discover other PIDs.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL); process.wait()
    # A dead leader can leave native grandchildren in its owned process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def fail(cfg, case, sample, status, **details):
    save(folder(cfg, case, sample)/'failure.json', {'status': status, 'sample': sample,
                                                'case': key(case), **details})
    event(cfg, status, case=key(case), sample=sample, **{k: v for k, v in details.items() if k != 'log_tail'})


def available_memory_gib():
    mem = dict(x.split(':', 1) for x in Path('/proc/meminfo').read_text().splitlines())
    available = int(mem['MemAvailable'].split()[0])*1024
    cgroup_file = Path('/proc/self/cgroup').read_text()
    if '0::' in cgroup_file:
        location = Path('/sys/fs/cgroup')/cgroup_file.split('0::')[1].splitlines()[0].lstrip('/')
        for p in (location, *location.parents):
            if (p/'memory.max').exists():
                maximum = (p/'memory.max').read_text().strip()
                if maximum != 'max':
                    available = min(available, max(0, int(maximum)-int((p/'memory.current').read_text())))
    return available/GIB


def preflight(cfg):
    selection = select(cfg)
    shared = scientific_inputs(cfg)
    # Hash each unique capture/density file only once at startup (about 33 GB for a full campaign).
    from config import input_files, digest
    hashes = {}
    cases = {}
    for case in selection['cases']:
        names = input_files(cfg, case)
        for path in names.values():
            if str(path) not in hashes:
                hashes[str(path)] = digest(path)
        cases[key(case)] = {name: hashes[str(path)] for name, path in names.items()}
    campaign = {'shared': shared, 'cases': cases, 'subset': selection['subset'],
                'shard': selection.get('shard'),
                'snapshot_provenance': {a: cfg['snapshot_'+a] for a in ('a', 'b')}}
    previous = Path(cfg['output'])/'campaign.json'
    if previous.exists():
        old = json.loads(previous.read_text())
        if any(old.get(k) != campaign.get(k) for k in ('shared', 'cases', 'subset', 'shard')):
            raise ValueError('campaign fingerprint changed; refusing stale resume; use a new output root')
        campaign = old
    else:
        save(previous, campaign)
    save(Path(cfg['output'])/'selection.json', selection)
    save(Path(cfg['output'])/'effective_config.json', cfg)
    return selection, campaign


def fingerprints_for(campaign, sample):
    return {k: {'shared': campaign['shared'], 'case': k, 'sample': sample, 'inputs': v}
            for k, v in campaign['cases'].items()}


def run_sample(cfg, selection, campaign, sample):
    fingerprints = fingerprints_for(campaign, sample)
    queue, states, active = [], {}, {}
    for case in selection['cases']:
        location = folder(cfg, case, sample); location.mkdir(parents=True, exist_ok=True)
        if (location/'result.json').exists():
            validate_result(location/'result.json', fingerprints[key(case)])
            cleanup_scratch(cfg, case, sample, fingerprints[key(case)])
            states[key(case)] = 'resumed'
            event(cfg, 'resumed', case=key(case), sample=sample)
        elif (location/'failure.json').exists() and json.loads((location/'failure.json').read_text())['status'] not in ('interrupted', 'retry_oom'):
            states[key(case)] = json.loads((location/'failure.json').read_text())['status']
        else:
            tier = reserve_tier(case['estimated_memory_gib'], cfg)
            if (location/'failure.json').exists():
                previous = json.loads((location/'failure.json').read_text())
                tier = previous.get('next_memory_gib', tier)
            queue.append((case, tier))
    checkpoint_path = Path(cfg['output'])/('demo' if sample == 0 else f'samples/sample_{sample:05d}')/'checkpoint.json'
    if not queue and checkpoint_path.exists():
        previous = validate_checkpoint(Path(cfg['output']), sample, campaign, states)
        normalize = lambda mapping: {k: 'complete' if v == 'resumed' else v for k, v in mapping.items()}
        if normalize(previous['states']) != normalize(states):
            raise ValueError('case states differ from committed sample checkpoint')
        event(cfg, 'resumed_checkpoint', sample=sample)
        return
    started = time.time(); last_status = 0
    try:
        while (queue or active) and not STOP:
            # Small tasks run first. Oversized work is explicitly terminal, never complete.
            for case, limit in list(queue):
                if limit is None or limit+cfg['driver_reserve_gib'] > cfg['memory_budget_gib']:
                    fail(cfg, case, sample, 'skipped_budget', estimated_memory_gib=case['estimated_memory_gib'],
                         requested_memory_gib=limit, budget_gib=cfg['memory_budget_gib'])
                    states[key(case)] = 'skipped_budget'; queue.remove((case, limit)); continue
                if not can_start(limit, [v['limit'] for v in active.values()], cfg):
                    continue
                if shutil.disk_usage(cfg['scratch']).free/GIB < cfg['scratch_min_free_gib']:
                    raise RuntimeError('NVMe scratch free space below configured reserve')
                location = folder(cfg, case, sample)
                task = {'case': case, 'sample': sample, 'memory_gib': limit, 'fingerprint': fingerprints[key(case)]}
                save(location/'task.json', task)
                log = (location/'worker.log').open('w')
                process = subprocess.Popen([sys.executable, '-B', str(HERE/'run.py'), '--worker', str(location/'task.json'),
                                            '--config', str(Path(cfg['output'])/'effective_config.json')],
                                           stdout=log, stderr=log, start_new_session=True, env=environment(cfg), cwd=cfg['repo_root'])
                active[key(case)] = {'case': case, 'limit': limit, 'process': process, 'log': log, 'started': time.time()}
                queue.remove((case, limit)); event(cfg, 'started', case=key(case), sample=sample, memory_gib=limit, pid=process.pid)
            for name, entry in list(active.items()):
                proc = entry['process']; timed_out = time.time()-entry['started'] > cfg['timeout_seconds']
                if proc.poll() is None and not timed_out:
                    continue
                terminate(proc); entry['log'].close(); del active[name]
                case, limit = entry['case'], entry['limit']
                location = folder(cfg, case, sample)
                if proc.returncode == 0 and not timed_out:
                    validate_result(location/'result.json', fingerprints[name]); states[name] = 'complete'
                    event(cfg, 'complete', case=name, sample=sample)
                    continue
                log = '\n'.join(p.read_text(errors='replace')[-3000:] for p in location.glob('*.log'))[-12000:]
                oom = proc.returncode in (-9, 137) or any(x in log for x in ('MemoryError', 'bad_alloc', 'bad allocation',
                    'cannot allocate memory', 'ArrayMemoryError', 'SIGKILL', 'exit status -9'))
                following = next_tier(limit, cfg) if oom and not timed_out else None
                state = 'timeout' if timed_out else 'retry_oom' if following is not None else 'skipped_oom' if oom else 'failed'
                fail(cfg, case, sample, state, memory_gib=limit, next_memory_gib=following,
                     returncode=proc.returncode, log_tail=log)
                if state == 'retry_oom':
                    queue.append((case, following))
                else:
                    states[name] = state
            if time.time()-last_status >= 5:
                save(Path(cfg['output'])/'status.json', {'phase': 'running', 'sample': sample, 'subset': selection['subset'],
                    'selected_pairs': len(selection['cases']), 'finished_attempts': len(states), 'queued': len(queue),
                    'active': {k: {'pid': v['process'].pid, 'memory_gib': v['limit']} for k, v in active.items()},
                    'reserved_gib': sum(v['limit'] for v in active.values()), 'budget_gib': cfg['memory_budget_gib'],
                    'driver_pid': os.getpid(), 'driver_pgid': os.getpgid(0), 'elapsed_seconds': time.time()-started})
                last_status = time.time()
            if active:
                time.sleep(.2)
    finally:
        for entry in active.values():
            terminate(entry['process']); entry['log'].close()
            fail(cfg, entry['case'], sample, 'interrupted', memory_gib=entry['limit'], next_memory_gib=entry['limit'])
    if STOP:
        raise InterruptedError('owned workers cancelled; resume the same configuration')
    output = collect_sample(cfg, selection, sample, fingerprints)
    if sample == 0:
        # A failed renderer holds the barrier: no sample 1 may start until its checkpoint exists.
        plot = subprocess.Popen(cfg['plot_command']+[str(HERE/'plot.py'), '--checkpoint', str(output)],
                 start_new_session=True, env={**environment(cfg), 'MPLCONFIGDIR': str(Path(cfg['output'])/'mplconfig')})
        deadline = time.monotonic()+cfg['timeout_seconds']
        while plot.poll() is None and not STOP and time.monotonic() < deadline:
            time.sleep(.2)
        if plot.poll() is None:
            terminate(plot)
            raise RuntimeError('draft renderer cancelled or timed out; sample barrier held')
        if plot.returncode:
            terminate(plot)
            raise RuntimeError('draft renderer failed; sample barrier held')
    names = ['results.csv', 'whole_model.csv', 'coverage.json']+(['draft.pdf'] if sample == 0 else [])
    checkpoint = {'sample': sample, 'selected_pairs': len(selection['cases']), 'subset': selection['subset'],
                  'attempts_finished': len(states), 'complete_cases': sum(s in ('complete', 'resumed') for s in states.values()),
                  'full_sample_complete': not selection['subset'] and all(s in ('complete', 'resumed') for s in states.values()),
                  'states': states, 'campaign': campaign, 'artifacts': {name: digest(output/name) for name in names}}
    save(output/'checkpoint.json', checkpoint)
    event(cfg, 'sample_checkpoint', sample=sample, selected_pairs=len(states), subset=selection['subset'])


def require_previous(cfg, selection, campaign, sample):
    if sample == 0:
        return
    for previous_sample in sorted({0, sample-1}):
        validate_checkpoint(Path(cfg['output']), previous_sample, campaign, [key(c) for c in selection['cases']])
    verify_unlock(cfg, campaign)


def main():
    global STOP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(); cfg = load(args.config)
    os.environ.update(environment(cfg))
    if args.worker:
        run_case(cfg, json.loads(args.worker.read_text())); return
    Path(cfg['output']).mkdir(parents=True, exist_ok=True); Path(cfg['scratch']).mkdir(parents=True, exist_ok=True)
    with (Path(cfg['output'])/'driver.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selection, campaign = preflight(cfg)
        print(json.dumps({'selected_pairs': len(selection['cases']), 'subset': selection['subset'],
                          'effective_available_memory_gib': available_memory_gib()}), flush=True)
        if args.preflight:
            return
        # Actual allocations remain below reservations; include the separate driver allowance.
        if available_memory_gib()+.25 < cfg['memory_budget_gib']:
            raise RuntimeError('configured budget exceeds currently available host/cgroup memory')
        def stop(signum, frame):
            global STOP
            STOP = True
        signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
        for sample in range(cfg['sample_start'], cfg['sample_stop']):
            require_previous(cfg, selection, campaign, sample)
            run_sample(cfg, selection, campaign, sample)
        save(Path(cfg['output'])/'status.json', {'phase': 'finished', 'subset': selection['subset'],
             'sample_start': cfg['sample_start'], 'sample_stop': cfg['sample_stop'],
             'meaning': 'all selected attempts/checkpoints finished; inspect coverage for failures'})
        print(json.dumps({'phase': 'finished', 'samples': [cfg['sample_start'], cfg['sample_stop']],
                          'selected_pairs': len(selection['cases']), 'subset': selection['subset']}), flush=True)


if __name__ == '__main__':
    main()
