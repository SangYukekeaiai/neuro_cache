"""One Delta node: fixture gate, bounded cases, NG45 pricing, durable retirement."""
import argparse
import ast
import csv
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import recovery
sys.path.insert(0, str(HERE.parent/'stokes'))
import stage1_worker as worker
import full500 as campaign
import stage2


def fitting_case(pending, entries, free_gib):
    eligible = [(i, attempt) for i, attempt in pending
                if worker.resources(entries[i], attempt)['memory_gib'] <= free_gib]
    return max(eligible, key=lambda p: worker.resources(entries[p[0]], p[1])['memory_gib'], default=None)


def fixture_gate(root, cfg):
    from snn_edp.model import HERE as model, ARCHES, load, digest
    from snn_edp.run import count
    from snn_edp.pricing import price
    from snn_edp.verify import close, retired_reference
    import archx
    print('archx.__file__='+archx.__file__, flush=True)
    assert Path(archx.__file__).resolve().is_relative_to(cfg['repo']/'zoo/archx/src')
    reference = model/'reference_t84_results.csv'
    manifest = load(model/'fixtures/manifest.json')
    assert digest(reference) == manifest['reference_sha256']
    refs = list(csv.DictReader(reference.open()))
    rows = terms = 0
    worst = term_worst = 0.0
    for arch in ARCHES:
        case = model/'fixtures'/arch
        for name, expected in manifest['cases'][arch]['files'].items():
            assert digest(case/name) == expected
        counts = root/'gate'/arch/'counts'
        if not (counts/'manifest.json').exists():
            count(case, counts)
        for row in price(counts, model/'energy_table.json', root/'gate'/arch/'priced'):
            ref = retired_reference(next(r for r in refs if r['arch'] == arch and r['arm'] == row['arm']),
                                    arch, model/'energy_table.json')
            for field in ('E_dyn_nJ', 'E_leak_nJ', 'T_s', 'EDP_nJ_s', 'area_mm2', 'total_cycles',
                          'E_core_dyn_nJ', 'E_chain_reference_nJ'):
                worst = max(worst, close(row[field], ref[field], arch+'/'+field))
            expected = ast.literal_eval(ref['breakdown'])
            assert set(row['breakdown']) == set(expected)
            for key, term in row['breakdown'].items():
                for field in ('count', 'E_dyn_nJ'):
                    term_worst = max(term_worst, close(term[field], expected[key][field], key+'/'+field))
                assert term['count_expression'] == expected[key]['count_expression']
                terms += 1
            rows += 1
    assert rows == 15 and terms == 386
    result = {'passed': True, 'rows': rows, 'terms': terms, 'max_total_relative_error': worst,
              'max_term_relative_error': term_worst, 'archx_file': archx.__file__,
              'reference_sha256': digest(reference), 'table_sha256': digest(model/'energy_table.json'),
              'host': os.uname().nodename, 'job': os.environ.get('SLURM_JOB_ID'),
              'native_hashes': {k: worker.digest(cfg[k]) for k in ('cachesim', 'eventsim')},
              'finished_unix': time.time()}
    worker.save(root/'fixture_gate.json', result)
    print('FIXTURE_GATE '+str(result), flush=True)


class ChunkPaused(Exception):
    pass


def execute_cases(root, config, cfg, entries, state, memory_gib, cores, chunk_seconds=0, defer_oversize=False):
    deadline = time.monotonic()+chunk_seconds if chunk_seconds else None
    owner = recovery.context(chunk_seconds)
    cases = worker.selection(cfg)
    pending = []
    for index, (case, entry) in enumerate(cases):
        base, _ = worker.paths(cfg, case)
        if (base/'complete.json').exists():
            if not worker.completed(base, worker.inputs(cfg, case)):
                raise ValueError('invalid completion receipt')
            continue
        attempts = sorted(base.glob('attempt_*.json'))
        if not attempts:
            pending.append((index, 0))
        else:
            previous = worker.load(attempts[-1])
            if recovery.resume_interrupted(base, previous, owner):
                pending.append((index, previous['attempt']))
            elif previous['status'] == 'resource_unavailable':
                pending.append((index, previous['attempt']))
            elif previous.get('retry'):
                pending.append((index, previous['retry']['attempt']))
            elif campaign.authorized_heavy_failure(previous):
                state.setdefault('quarantined_failures', {})[str(index)] = previous
            else:
                raise RuntimeError(f'case {index}: exhausted/interrupted attempt requires diagnosis')
    active = {}
    stopping = False

    def interrupt(signum, frame):
        nonlocal stopping
        stopping = True

    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        while pending or active:
            if deadline and time.monotonic() >= deadline:
                raise ChunkPaused('interactive chunk ended; durable steps retained')
            if stopping:
                raise InterruptedError('node job interrupted; case evidence retained')
            used = sum(item['memory_gib'] for item in active.values())
            while len(active) < cores:
                choice = fitting_case(pending, entries, memory_gib-used)
                if choice is None:
                    break
                index, attempt = choice
                pending.remove(choice)
                limits = worker.resources(entries[index], attempt)
                base, _ = worker.paths(cfg, cases[index][0])
                worker.save(base/'dispatch.json', owner)
                log = (root/'logs'/f'sample_{cfg["sample"]:03d}_case_{index}_attempt_{attempt}.log').open('a')
                command = [sys.executable, '-B', str(Path(worker.__file__)), '--config', str(config),
                           '--case-index', str(index), '--attempt', str(attempt)]
                process = subprocess.Popen(command, stdout=log, stderr=log)
                active[index] = {'process': process, 'attempt': attempt, 'log': log, **limits}
                used += limits['memory_gib']
            if pending and not active:
                if defer_oversize:
                    state['deferred_to_batch'] = [
                        {'case_index':i, 'case':worker.identity(cases[i][0]), 'attempt':a,
                         **worker.resources(entries[i], a)} for i, a in pending]
                    assert all(item['memory_gib'] > memory_gib for item in state['deferred_to_batch'])
                    state['jobs'].append({'kind':'deferred_to_batch', 'cases':state['deferred_to_batch']})
                    pending.clear()
                    break
                raise RuntimeError('no case fits the node memory budget')
            for index, item in list(active.items()):
                code = item['process'].poll()
                if code is None:
                    continue
                item['log'].close()
                del active[index]
                base, _ = worker.paths(cfg, cases[index][0])
                receipt = worker.load(base/f'attempt_{item["attempt"]}.json')
                if code == 0 and (base/'complete.json').exists():
                    pass
                elif receipt.get('retry'):
                    pending.append((index, receipt['retry']['attempt']))
                elif campaign.authorized_heavy_failure(receipt):
                    state.setdefault('quarantined_failures', {})[str(index)] = receipt
                else:
                    raise RuntimeError(f'case {index}: {receipt}; evidence retained')
            state.update(phase='counting', active_cases=sorted(active), pending_cases=len(pending),
                         updated_unix=time.time())
            worker.save(root/f'sample_{cfg["sample"]:03d}_status.json', state)
            time.sleep(1)
    finally:
        for item in active.values():
            if item['process'].poll() is None:
                item['process'].terminate()
        for item in active.values():
            item['process'].wait()
            item['log'].close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--sample', type=int, required=True)
    parser.add_argument('--memory-gib', type=int, default=240)
    parser.add_argument('--cores', type=int, default=64)
    parser.add_argument('--chunk-seconds', type=int, default=0)
    parser.add_argument('--count-only', action='store_true')
    parser.add_argument('--defer-oversize', action='store_true')
    args = parser.parse_args()
    if args.defer_oversize and not args.count_only:
        parser.error('--defer-oversize requires --count-only')
    root = args.root.resolve()
    claims = worker.load(root/'claims.json')
    if args.sample not in claims['samples']:
        raise ValueError('sample is outside manager-confirmed Delta claims')
    import fcntl
    lock = (root/f'sample_{args.sample:03d}.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    state_path = root/f'sample_{args.sample:03d}_status.json'
    previous_state = worker.load(state_path) if state_path.exists() else {}
    if (root/'rows'/f'sample_{args.sample:03d}'/'commit.json').exists():
        campaign.commit_sample(root, args.sample, previous_state)
        worker.save(state_path, previous_state)
        return
    config = root/'work'/f'sample_{args.sample:03d}'/'config.json'
    raw = worker.load(root/'base_config.json')
    raw.update(sample=args.sample, output_root=str(config.parent/'cases'),
               scratch_root=str(root/'scratch'/f'sample_{args.sample:03d}'))
    worker.save(config, raw)
    cfg = worker.configure(config)
    from energy_driver import check_cache_configs
    check_cache_configs(cfg['cache_a'], cfg['cache_b'])
    entries = worker.load(cfg['selection'])['cases']
    worker.selection(cfg)
    with (root/'gate.lock').open('a') as gate_lock:
        fcntl.flock(gate_lock, fcntl.LOCK_EX)
        fixture_gate(root, cfg)
    state = {'sample': args.sample, 'started_unix': time.time(), 'phase': 'counting',
             'jobs': previous_state.get('jobs', [])+[{'id': os.environ.get('SLURM_JOB_ID'), 'host': os.uname().nodename,
                       'memory_gib': args.memory_gib, 'cores': args.cores}],
             'runner_sha256': worker.digest(Path(__file__))}
    try:
        execute_cases(root, config, cfg, entries, state, args.memory_gib, args.cores,
                      args.chunk_seconds, args.defer_oversize)
        if state.get('quarantined_failures'):
            state.update(phase='quarantined', active_cases=[])
            worker.save(root/f'sample_{args.sample:03d}_status.json', state)
            return
        if args.count_only:
            state.update(phase='counts_partial' if state.get('deferred_to_batch') else 'counts_ready', active_cases=[])
            worker.save(state_path, state)
            return
        table = cfg['repo']/'zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json'
        assert worker.digest(table) == campaign.TABLE_SHA
        state.update(phase='pricing', active_cases=[])
        worker.save(root/f'sample_{args.sample:03d}_status.json', state)
        stage2.run(config.parent, table, root/'priced'/f'sample_{args.sample:03d}',
                   confirmed_drained=True, workers=2, pricing_profile='nangate45')
        campaign.commit_sample(root, args.sample, state)
        worker.save(root/f'sample_{args.sample:03d}_status.json', state)
        print('SAMPLE_COMMITTED '+str(state), flush=True)
    except ChunkPaused as exc:
        state.update(phase='paused', active_cases=[], reason=str(exc), updated_unix=time.time())
        worker.save(state_path, state)
    except InterruptedError as exc:
        state.update(phase='interrupted', active_cases=[], reason=str(exc), updated_unix=time.time())
        worker.save(state_path, state)
        raise
    except BaseException as exc:
        state.update(phase='blocked', error=repr(exc), updated_unix=time.time())
        worker.save(root/f'sample_{args.sample:03d}_status.json', state)
        raise


if __name__ == '__main__':
    main()
