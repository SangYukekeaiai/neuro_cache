"""Concurrent case commands inside one Slurm allocation; receipts remain per case."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import stage1_worker as worker

MAX_JOBS = 250
MAX_SAMPLES = 15
PENDING_STEP_SECONDS = 600
BATCH_WIDTHS = (8, 2, 1)
MEMORY_GIB = {(0, 8): 140, (0, 4): 70, (0, 2): 35, (0, 1): 16,
              (1, 2): 140, (1, 1): 64, (2, 1): 120}


def batch_width(tier, pending_seconds):
    return max(1, BATCH_WIDTHS[tier] >> min(3, int(pending_seconds // PENDING_STEP_SECONDS)))


def groups(indices, width):
    if width < 1 or len(indices) != len(set(indices)):
        raise ValueError('invalid or duplicate batch cases')
    return [indices[i:i+width] for i in range(0, len(indices), width)]


def run_commands(commands):
    """Start each case supervisor once; let it own its worker-group cleanup."""
    processes = {}
    stopped = False

    def interrupt(signum, frame):
        nonlocal stopped
        stopped = True

    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for index, command in commands.items():
            if stopped:
                break
            processes[index] = subprocess.Popen(command)
        while not stopped and any(p.poll() is None for p in processes.values()):
            time.sleep(0.2)
    finally:
        # Supervisors receive TERM and stop only their own native worker sessions.
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic()+15
        for process in processes.values():
            try:
                process.wait(timeout=max(0, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return {index: processes[index].returncode if index in processes else None for index in commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--batch-index', type=int, required=True)
    args = parser.parse_args()
    manifest = worker.load(args.manifest)
    indices = manifest['batches'][args.batch_index]
    cfg = worker.configure(manifest['config'])
    entries = worker.load(cfg['selection'])['cases']
    if len(indices) > manifest['width'] or len(indices) != len(set(indices)):
        raise ValueError('invalid batch membership')
    for index in indices:
        if worker.resources(entries[index], manifest['attempt'])['tier'] != manifest['tier']:
            raise ValueError('batch contains another memory tier')
    commands = {index: [sys.executable, '-B', str(Path(worker.__file__).resolve()),
        '--config', manifest['config'], '--case-index', str(index),
        '--attempt', str(manifest['attempt'])] for index in indices}
    codes = run_commands(commands)
    receipt = {'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'case_exit_codes': codes,
               'finished_unix': time.time()}
    worker.save(args.manifest.with_name(args.manifest.stem+f'_batch_{args.batch_index}_exit.json'), receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if all(code == 0 for code in codes.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
