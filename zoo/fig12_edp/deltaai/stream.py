"""One resident interactive lane; held batch tasks own the later pricing step."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import budget

ROOT = budget.ROOT
HERE = Path(__file__).resolve().parent


def run(args):
    return subprocess.check_output(args, text=True).strip()


def save(state):
    state['updated_unix'] = time.time()
    path = ROOT/'interactive_status.json'
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(state, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def queue():
    text = run(['squeue', '-r', '-h', '-u', os.environ['USER'], '-o', '%i|%T|%R'])
    return {p[0]:[p[1], p[2].strip('()')] for line in text.splitlines()
            if len(p:=line.split('|')) == 3}


def finished(job):
    text = run(['sacct', '-X', '-n', '-P', '-j', job, '-o', 'JobID,State,Start,ElapsedRaw'])
    for line in text.splitlines():
        fields = line.split('|')
        if fields[0] == job:
            return {'state':fields[1].split()[0].rstrip('+'), 'start':fields[2],
                    'elapsed_seconds':int(fields[3])}
    return None


def candidates(catalog, jobs, state):
    result = []
    handed = set(state.get('handed_to_batch', []))
    for wave in catalog['arrays']:
        for index, sample in enumerate(wave['samples']):
            job = wave['job']+'_'+str(index)
            if sample not in handed and jobs.get(job, [None])[0] == 'PENDING':
                result.append((sample, job))
    return sorted(result, reverse=True)


def reconcile_contenders(state, jobs):
    selected = state.get('selected', {}).get('sample')
    contenders = ([state['active']] if state.get('active') else [])+state.get('standby', [])
    remaining = []
    winner = None
    for item in contenders:
        path = ROOT/'interactive_outcomes'/(item['job']+'.json')
        outcome = json.loads(path.read_text()) if path.exists() else {}
        skipped = outcome.get('status') in ('lost_race', 'already_handed_to_batch')
        final = finished(item['job']) if item['job'] not in jobs else None
        if skipped and final and final['state'] in budget.FINAL:
            state.setdefault('history', []).append({**item, **final, 'disposition':outcome['status']})
            continue
        remaining.append(item)
        if item['sample'] == selected and outcome.get('status') == 'owns_lane' and (
                jobs.get(item['job'], [None])[0] == 'RUNNING' or (final and final['state'] in budget.FINAL)):
            if winner is None or jobs.get(item['job'], [None])[0] == 'RUNNING':
                winner = item
    if winner:
        state['active'] = winner
        state['standby'] = [item for item in remaining if item['job'] != winner['job']]
    elif state.get('active') not in remaining:
        state.pop('active', None)
        state['standby'] = remaining
    else:
        state['standby'] = [item for item in remaining if item != state.get('active')]


def hand_back(state, active):
    with (ROOT/'interactive_lane.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        if active['sample'] not in state.setdefault('handed_to_batch', []):
            state['handed_to_batch'].append(active['sample'])
        state.pop('selected', None)
        save(state)
        if queue().get(active['batch_task']) == ['PENDING', 'JobHeldUser']:
            run(['scontrol', 'release', active['batch_task']])
        return True


def step(state):
    jobs = queue()
    reconcile_contenders(state, jobs)
    active = state.get('active')
    if active:
        job = active['job']
        if job in jobs:
            active['scheduler'] = jobs[job]
            if jobs[job][0] == 'PENDING':
                forecast = run(['squeue', '-h', '-j', job, '-o', '%S'])
                if forecast != active.get('tentative_start'):
                    active['tentative_start'] = forecast
                    event = {'job':job, 'tentative_start':forecast, 'observed_unix':time.time()}
                    state.setdefault('start_forecasts', []).append(event)
                    print(json.dumps(event), flush=True)
                note = ROOT/f'resize_{job}.json'
                if note.exists() and time.time() >= json.loads(note.read_text())['reassess_after_unix']:
                    state['reassessment'] = {'job':job, 'reason':'still pending two hours after resize'}
            if jobs[job][0] == 'RUNNING' and not active.get('start'):
                evidence = finished(job)
                if evidence and evidence['start'] not in ('Unknown', 'N/A', 'None', ''):
                    active.update(evidence)
            return
        outcome = finished(job)
        if outcome is None or outcome['state'] not in budget.FINAL:
            return
        active.update(outcome)
        sample_state = ROOT/f'sample_{active["sample"]:03d}_status.json'
        status = json.loads(sample_state.read_text()) if sample_state.exists() else {}
        phase = status.get('phase')
        if phase in ('counts_ready', 'counts_partial', 'done', 'quarantined'):
            if not hand_back(state, active):
                return
        elif phase not in ('paused', 'interrupted') and not (
                outcome['state'] == 'TIMEOUT' and phase in ('counting', 'pricing')):
            raise RuntimeError(f'interactive job {job} requires diagnosis: {outcome}, phase={phase}')
        state.setdefault('history', []).append(active)
        state.pop('active')
    run([os.sys.executable, '-B', str(HERE/'budget.py'), '--check'])
    usage = json.loads((ROOT/'budget.json').read_text())
    if usage['charged_or_reserved_hours']+4 > usage['cap_gh200_hours']:
        state.update(phase='budget_hold', budget=usage['charged_or_reserved_hours'])
        return
    if not (ROOT/'environment_ready.json').exists():
        state['phase'] = 'environment_wait'
        return
    if not state.get('selected'):
        catalog = json.loads((ROOT/'array_catalog.json').read_text())
        for sample, task in candidates(catalog, jobs, state):
            try:
                run(['scontrol', 'hold', task])
            except subprocess.CalledProcessError:
                continue
            observed = queue().get(task)
            if observed != ['PENDING', 'JobHeldUser']:
                raise RuntimeError('batch task hold did not settle: '+task)
            state['selected'] = {'sample':sample, 'batch_task':task}
            save(state)
            break
    if state.get('selected'):
        selected = state['selected']
        job = run(['sbatch', '--parsable', str(HERE/'quarter.sbatch'), str(selected['sample'])]).split(';')[0]
        state['active'] = {**selected, 'job':job, 'submitted_unix':time.time()}
        state['phase'] = 'running'
        print(json.dumps({'submitted':state['active']}), flush=True)
    else:
        state['phase'] = 'awaiting_pending_case'


def main():
    with (ROOT/'interactive_controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        path = ROOT/'interactive_status.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        if state.get('error'):
            state.setdefault('previous_errors', []).append(
                {'error':state.pop('error'), 'updated_unix':state.get('updated_unix')})
        state['controller_pid'] = os.getpid()
        while True:
            try:
                step(state)
                save(state)
            except Exception as error:
                state.update(phase='blocked', error=repr(error))
                save(state)
                raise
            time.sleep(60)


if __name__ == '__main__':
    main()
