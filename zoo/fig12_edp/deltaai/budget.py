"""Reserve bounded GH200-hours across normal and double-charge interactive jobs."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/work/hdd/bebv/yyu9/fig12_full500_deltaai')
CAP = 240.0
FINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'PREEMPTED'}


def charge(record):
    return record.get('measured_hours', record['reserved_hours'])


def refresh(records):
    if not records:
        return
    output = subprocess.check_output(['sacct', '-X', '-n', '-P', '-j', ','.join(records),
                                      '-o', 'JobID,State,ElapsedRaw'], text=True)
    for line in output.splitlines():
        fields = line.split('|')
        if len(fields) < 3 or fields[0] not in records:
            continue
        rec = records[fields[0]]
        state = fields[1].split()[0].rstrip('+')
        if state in FINAL:
            rec.update(state=state, elapsed_seconds=int(fields[2]),
                       measured_hours=int(fields[2])*rec['rate']/3600)


def reserve(records, job, rate, wall_seconds, cap=CAP):
    if job in records:
        return
    wanted = rate*wall_seconds/3600
    if sum(map(charge, records.values()))+wanted > cap:
        raise ValueError('GH200 budget cap reached; new execution refused')
    records[job] = {'rate': rate, 'wall_seconds': wall_seconds,
                    'reserved_hours': wanted, 'admitted_unix': time.time()}


def reservation_parameters(environ):
    interactive = environ.get('SLURM_JOB_PARTITION') == 'ghx4-interactive'
    gpus = int(environ['SLURM_GPUS_ON_NODE'])
    if gpus not in (1, 4):
        raise ValueError('unexpected GPU allocation for budget accounting')
    return gpus*(2 if interactive else 1), 7200 if interactive else 21600


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'budget.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = ROOT/'budget.json'
        data = json.loads(path.read_text()) if path.exists() else {'cap_gh200_hours':CAP,'jobs':{}}
        refresh(data['jobs'])
        if not args.check:
            job = os.environ['SLURM_JOB_ID']
            if os.environ.get('SLURM_ARRAY_JOB_ID'):
                job = os.environ['SLURM_ARRAY_JOB_ID']+'_'+os.environ['SLURM_ARRAY_TASK_ID']
            rate, wall_seconds = reservation_parameters(os.environ)
            reserve(data['jobs'], job, rate, wall_seconds, data['cap_gh200_hours'])
        data['charged_or_reserved_hours'] = sum(map(charge, data['jobs'].values()))
        data['updated_unix'] = time.time()
        temporary = path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(data, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
        print(json.dumps(data), flush=True)


if __name__ == '__main__':
    main()
