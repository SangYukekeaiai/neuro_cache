"""Prepare or run all 749 feasible sample-0 cases; kept-layer execution uses the archx backend."""
import argparse
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

from common import (HERE, GIB, SMALL_GIB, HEAVY_GIB, THREAD_ENV, demo,
                    current_inputs, durable_hashes, identity, memory_state,
                    expected_fingerprint, validate_case, write_receipt)
from report import collect
from layer_scope import kept

STOP = False


def prepare():
    inputs = current_inputs()
    manifest = json.loads(demo.MANIFEST.read_text())
    cases = demo.select_cases()
    infeasible = [c for c in manifest['schedules'] if c['solver_status'] == 'INFEASIBLE']
    captures = manifest['capture_order']
    if len(cases) != 749 or len(infeasible) != 6 or len(captures) != 8:
        raise ValueError('expected 749 feasible + 6 infeasible schedules across 8 benchmarks')
    if len({identity(c) for c in cases+infeasible}) != 755:
        raise ValueError('duplicate schedule identity')
    cases=[c for c in cases if kept(c['layer'])]
    infeasible=[c for c in infeasible if kept(c['layer'])]
    selection = {'feasible': cases, 'infeasible': infeasible, 'captures': captures,
                 'sample': 0, 'arms': ['spad', 'cacheA', 'cacheB']}
    demo.save(HERE/'selection.json', selection)
    demo.save(HERE/'inputs.json', inputs)
    states = collect(selection, inputs)
    demo.save(HERE/'status.json', status(states, {}, time.time(), [], 'prepared'))
    print(json.dumps({'feasible': len(cases), 'infeasible': len(infeasible),
                      'memory': memory_state()}), flush=True)
    return selection, inputs, states


def status(states, active, start, durations, phase):
    counts = {s: sum(v == s for v in states.values()) for s in set(states.values())}
    remaining = sum(v not in ('complete', 'skipped_oom', 'failed') for v in states.values())
    eta = None
    if durations:
        eta = remaining*(time.time()-start)/len(durations)
    return {'updated_unix': time.time(), 'phase': phase, 'elapsed_seconds': time.time()-start,
            'driver_pid': os.getpid(), 'driver_pgid': os.getpgid(0),
            'counts': counts, 'total_feasible': len(states), 'infeasible': 6,
            'active_cases': list(active), 'eta_seconds': eta,
            'eta_note': 'observed throughput including failed attempts; heavy-tail extrapolation is uncertain; null before new measurements',
            'small_memory_gib': SMALL_GIB, 'per_process_max_gib': HEAVY_GIB,
            'memory': memory_state()}


def worker(case_path, limit):
    resource.setrlimit(resource.RLIMIT_AS, (int(limit*GIB), int(limit*GIB)))
    case = json.loads(case_path.read_text())
    inputs = json.loads((HERE/'inputs.json').read_text())
    if inputs != current_inputs():
        raise ValueError('campaign inputs changed before worker')
    # Keep all subprocesses in the worker's owned session for group cancellation.
    def command(args, log, *, stdout=None, timeout=3600):
        with log.open('w') as stream:
            process = subprocess.Popen(args, stdout=stdout or stream, stderr=stream,
                                       env={**os.environ, **THREAD_ENV})
            try:
                code = process.wait(timeout=timeout)
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                raise
        if code:
            raise subprocess.CalledProcessError(code, args)
    demo.command = command
    demo.run_case(case, HERE, limit)
    folder = demo.folder_for(case, HERE)
    if current_inputs() != inputs:
        raise ValueError('campaign inputs changed during case')
    validate_case(case, folder, inputs, receipt=False)
    write_receipt(folder, inputs, {'kind': 'computed', 'sample': 0})


def execute(case, limit, inputs):
    folder = demo.folder_for(case, HERE)
    folder.mkdir(parents=True, exist_ok=True)
    task = folder/'case.json'
    demo.save(task, case)
    # A matching stage snapshot permits restart of an interrupted trace generation.
    stage = folder/'stage_inputs.json'
    stage_inputs = {'inputs': inputs, 'case': expected_fingerprint(case, inputs)}
    if (folder/'result.json').exists() and stage.exists() and json.loads(stage.read_text()) == stage_inputs:
        try:
            validate_case(case, folder, inputs, receipt=False)
        except (ValueError, KeyError, OSError):
            pass
        else:
            for name in ('sample_00000.wcts', 'sample_00000.part', 'failure.json'):
                (folder/name).unlink(missing_ok=True)
            write_receipt(folder, inputs, {'kind': 'recovered_committed_case', 'sample': 0})
            return 'complete', 0
    if (stage.exists() and json.loads(stage.read_text()) != stage_inputs) or (folder/'result.json').exists():
        for name in ('sample_00000.wcts', 'sample_00000.part'):
            (folder/name).unlink(missing_ok=True)
        archived = folder.with_name('stale_'+str(time.time_ns()))
        folder.rename(archived); folder.mkdir()
        demo.save(task, case)
    demo.save(stage, stage_inputs)
    started = time.time()
    with (folder/'worker.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-B', str(HERE/'run.py'), '--case-json', str(task),
                                    '--limit-gib', str(limit)], stdout=log, stderr=log,
                                   env={**os.environ, **THREAD_ENV}, start_new_session=True)
        deadline = time.monotonic()+7200
        while process.poll() is None and not STOP and time.monotonic() < deadline:
            time.sleep(.5)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
        code = process.wait()
    if code == 0:
        try:
            validate_case(case, folder, inputs)
            return 'complete', time.time()-started
        except (ValueError, KeyError, OSError) as error:
            detail = str(error)
    else:
        detail = f'worker exit {code}'
    logs = '\n'.join(p.read_text(errors='replace')[-4000:] for p in folder.glob('*.log'))
    oom = code in (-9, 137) or any(s in logs for s in (
        'MemoryError', 'bad_alloc', 'cannot allocate memory', 'ArrayMemoryError', 'SIGKILL', 'bad allocation', 'exit status -9'))
    state = 'interrupted' if STOP else 'skipped_oom' if oom else 'failed'
    demo.save(folder/'failure.json', {'status': state, 'error': detail, 'log_tail': logs[-12000:],
                                    'memory_limit_gib': limit, 'case': identity(case)})
    # Failed attempts cannot leave a successful-looking result in collection.
    (folder/'receipt.json').unlink(missing_ok=True)
    for name in ('sample_00000.wcts', 'sample_00000.part'):
        (folder/name).unlink(missing_ok=True)
    return state, time.time()-started


def run(selection, inputs, states, workers, retry_failed):
    global STOP
    start, durations, active = time.time(), [], {}
    def stop(signum, frame):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    pending = [c for c in selection['feasible'] if kept(c['layer']) and states[identity(c)] != 'complete'
               and (retry_failed or states[identity(c)] not in ('skipped_oom', 'failed'))]
    small = [c for c in pending if c['estimated_memory_gib'] <= SMALL_GIB]
    heavy = [c for c in pending if c['estimated_memory_gib'] > SMALL_GIB]
    for batch, concurrency, limit, phase in ((small, workers, SMALL_GIB, 'small'), (heavy, 1, HEAVY_GIB, 'heavy')):
        queue = iter(batch)
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {}
            last_status = 0
            while not STOP:
                while len(futures) < concurrency:
                    try:
                        case = next(queue)
                    except StopIteration:
                        break
                    futures[pool.submit(execute, case, limit, inputs)] = case
                    active[identity(case)] = case
                if not futures:
                    break
                done, _ = concurrent.futures.wait(futures, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    case = futures.pop(future); key = identity(case)
                    state, seconds = future.result(); states[key] = state
                    durations.append(seconds); active.pop(key)
                    if state == 'skipped_oom' and phase == 'small':
                        heavy.append(case); states[key] = 'pending_heavy_retry'
                    print(json.dumps({'case': key, 'status': state, 'seconds': seconds}), flush=True)
                if done or time.time()-last_status >= 15:
                    demo.save(HERE/'status.json', status(states, active, start, durations, phase))
                    last_status = time.time()
        if STOP:
            break
    states = collect(selection, inputs)
    demo.save(HERE/'status.json', status(states, {}, start, durations, 'interrupted' if STOP else 'finished'))
    print(json.dumps({'phase': 'interrupted' if STOP else 'finished',
                      'complete_cases': sum(s == 'complete' for s in states.values())}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--case-json', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--limit-gib', type=float, default=HEAVY_GIB, help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.environ.update(THREAD_ENV)
    if not 0 < args.limit_gib <= HEAVY_GIB:
        parser.error('per-process limit must be in (0, 54] GiB')
    if args.case_json:
        if args.case_json.resolve().is_relative_to(HERE/'cases'):
            worker(args.case_json, args.limit_gib); return
        parser.error('case file must be under all_bench/cases')
    with (HERE/'driver.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.prepare or not (HERE/'selection.json').exists():
            selection, inputs, states = prepare()
        else:
            selection = json.loads((HERE/'selection.json').read_text())
            inputs = current_inputs()
            saved_inputs = json.loads((HERE/'inputs.json').read_text())
            if inputs != saved_inputs:
                raise ValueError('campaign inputs changed; use a fresh output directory')
            states = collect(selection, inputs)
        if args.run:
            mem = memory_state()
            if mem['effective_available_gib'] < args.workers*SMALL_GIB+4:
                raise RuntimeError('insufficient aggregate headroom; use one worker or wait')
            if any(c['pids_max'] != 'max' and int(c['pids_max'])-c['pids_current'] < 40 for c in mem['cgroups']):
                raise RuntimeError('fewer than 40 free cgroup PIDs; wait before launch')
            run(selection, inputs, states, args.workers, args.retry_failed)
        elif args.collect_only:
            print(json.dumps({'complete_cases': sum(s == 'complete' for s in states.values())}))


if __name__ == '__main__':
    main()
