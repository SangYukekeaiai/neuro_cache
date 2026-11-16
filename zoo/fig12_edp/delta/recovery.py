"""Resume scheduler interruptions without consuming a resource-tier retry."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def context(chunk_seconds=0):
    job = os.environ.get('SLURM_JOB_ID')
    if os.environ.get('SLURM_ARRAY_JOB_ID'):
        job = os.environ['SLURM_ARRAY_JOB_ID']+'_'+os.environ['SLURM_ARRAY_TASK_ID']
    return {'job': job, 'restart': int(os.environ.get('SLURM_RESTART_COUNT', '0')),
            'chunk_seconds': chunk_seconds}


def scheduler_state(job):
    output = subprocess.check_output(['sacct', '-X', '-j', job, '-n', '-P',
                                      '-o', 'JobID,State'], text=True)
    states = [line.split('|')[1].split()[0].rstrip('+') for line in output.splitlines()
              if line.split('|')[0] == job]
    if len(states) != 1:
        raise ValueError('scheduler termination is not proven: '+job)
    return states[0]


def resume_interrupted(base, receipt, current, state_reader=scheduler_state):
    if receipt['status'] not in ('running', 'interrupted'):
        return False
    previous = json.loads((base/'dispatch.json').read_text())
    if not previous['job'] or not current['job']:
        raise ValueError('scheduler identity required for interrupted resume')
    if previous['job'] == current['job']:
        safe = current['restart'] > previous['restart']
    else:
        state = state_reader(previous['job'])
        safe = state in ('PREEMPTED', 'TIMEOUT', 'CANCELLED', 'NODE_FAIL')
        safe |= (state == 'COMPLETED' and receipt['status'] == 'interrupted'
                 and previous['chunk_seconds'] > 0)
    if not safe:
        raise ValueError('previous worker allocation is not safely retired')
    archive = base/'resume_history'/str(time.time_ns())
    archive.mkdir(parents=True)
    for path in [base/'dispatch.json', *base.glob('*.log')]:
        if path.exists():
            shutil.copyfile(path, archive/path.name)
    # The worker rejects a reused attempt receipt. Preserve it before reopening
    # the same tier; its fingerprint and all durable stage receipts remain live.
    path = base/f'attempt_{receipt["attempt"]}.json'
    path.replace(archive/path.name)
    return True
