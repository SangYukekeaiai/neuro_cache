"""Validate all boxes, merge one sample, then explicitly approve its global figure."""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from collect import write_summary
from config import HERE, digest, environment, input_files, key, load, save, scientific_inputs
from pipeline import validate_result
from shards import (comparable_inputs, native_inputs, object_digest, read_partition,
                    validate_checkpoint)


def gather(cfg, partition, roots, sample, allow_native_rebuilds=False):
    plan, assignments = read_partition(partition, Path(cfg['manifest']))
    expected = scientific_inputs({k: v for k, v in cfg.items() if k not in ('shard_manifest', 'shard_id')})
    expected['shard_manifest'] = digest(partition)
    manifest = json.loads(Path(cfg['manifest']).read_text())
    cases = {key(c): c for c in manifest['schedules'] if c['solver_status'] != 'INFEASIBLE'}
    found, states, rows, input_hashes = {}, {}, [], {}
    for root in roots:
        campaign = json.loads((root/'campaign.json').read_text())
        shard = campaign.get('shard') or {}
        name = shard.get('id')
        if name not in assignments or name in found:
            raise ValueError('duplicate or foreign shard output')
        if (shard.get('partition_sha256') != digest(partition)
                or shard.get('global_subset') != plan['subset']
                or shard.get('selected_global_pairs') != len(plan['selected_case_keys'])
                or set(campaign['cases']) != assignments[name]):
            raise ValueError('shard assignment/partition differs')
        if comparable_inputs(campaign['shared']) != comparable_inputs(expected):
            raise ValueError('foreign source/table/config fingerprints')
        if native_inputs(campaign['shared']) != native_inputs(expected) and not allow_native_rebuilds:
            raise ValueError('native binaries differ; explicit --allow-native-rebuilds acknowledgement required')
        checkpoint = validate_checkpoint(root, sample, campaign, assignments[name])
        local_rows = []
        for identity in sorted(assignments[name]):
            current_inputs = {}
            for label, path in input_files(cfg, cases[identity]).items():
                if str(path) not in input_hashes:
                    input_hashes[str(path)] = digest(path)
                current_inputs[label] = input_hashes[str(path)]
            if current_inputs != campaign['cases'][identity]:
                raise ValueError('foreign capture/metadata/schedule fingerprints')
            location = root/'cases'/identity/f'sample_{sample:05d}'
            state = checkpoint['states'][identity]
            fingerprint = {'shared': campaign['shared'], 'case': identity, 'sample': sample, 'inputs': current_inputs}
            if state in ('complete', 'resumed'):
                local_rows.extend(validate_result(location/'result.json', fingerprint)['rows'])
            else:
                failure = json.loads((location/'failure.json').read_text())
                if (failure['status'], failure['sample'], failure['case']) != (state, sample, identity):
                    raise ValueError('failure coverage differs from checkpoint')
            states[identity] = state
        directory = root/('demo' if sample == 0 else f'samples/sample_{sample:05d}')
        with (directory/'results.csv').open() as stream:
            actual = list(csv.DictReader(stream))
        fields = sorted({k for row in local_rows for k in row})
        serialized = [{k: '' if r.get(k) is None else str(r[k]) for k in fields} for r in local_rows]
        sort_key = lambda r: (r['arch'], r['capture'], r['layer'], r['arm'])
        if sorted(actual, key=sort_key) != sorted(serialized, key=sort_key):
            raise ValueError('checkpoint CSV differs from durable case rows')
        rows.extend(local_rows)
        found[name] = {'checkpoint_sha256': digest(directory/'checkpoint.json'),
            'campaign_sha256': object_digest(campaign), 'case_keys_sha256': object_digest(sorted(assignments[name])),
            'native_inputs': native_inputs(campaign['shared']),
            'complete_cases': sum(v in ('complete', 'resumed') for v in checkpoint['states'].values()),
            'selected_pairs': len(assignments[name])}
    if set(found) != set(assignments):
        raise ValueError('missing shard outputs')
    if len({(r['arch'], r['capture'], r['layer'], r['sample'], r['arm']) for r in rows}) != len(rows):
        raise ValueError('duplicate global result rows')
    selection = {'cases': [cases[k] for k in plan['selected_case_keys']], 'subset': plan['subset'],
                 'captures': manifest['capture_order'],
                 'infeasible': [c for c in manifest['schedules'] if c['solver_status'] == 'INFEASIBLE']}
    evidence = {'schema': 'fig12_merge_v1', 'sample': sample, 'partition_sha256': digest(partition),
                'subset': plan['subset'], 'selected_global_pairs': len(plan['selected_case_keys']),
                'comparable_inputs': comparable_inputs(expected), 'shards': found,
                'native_rebuilds_allowed': allow_native_rebuilds, 'result_rows': len(rows),
                'complete_cases': sum(v in ('complete', 'resumed') for v in states.values())}
    return manifest, selection, rows, states, evidence


def render(cfg, out):
    process = subprocess.Popen(cfg['plot_command']+[str(HERE/'plot.py'), '--checkpoint', str(out)],
        start_new_session=True, env={**environment(cfg), 'MPLCONFIGDIR': str(out/'mplconfig')})
    def stop(signum, frame):
        raise InterruptedError('merge renderer interrupted')
    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        if process.wait(timeout=cfg['timeout_seconds']):
            raise RuntimeError('global figure render failed')
    finally:
        from run import terminate
        terminate(process)
        for s, handler in old.items():
            signal.signal(s, handler)


def merge(cfg, partition, roots, out, sample=0, allow_native_rebuilds=False):
    manifest, selection, rows, states, evidence = gather(cfg, partition, roots, sample, allow_native_rebuilds)
    write_summary(out, manifest['schedules'], selection, sample, rows, states)
    if sample == 0:
        render(cfg, out)
    names = ['results.csv', 'whole_model.csv', 'coverage.json']+(['draft.pdf'] if sample == 0 else [])
    save(out/'merge.json', {**evidence, 'artifacts': {n: digest(out/n) for n in names}})
    return evidence


def approve(cfg, partition, roots, out, unlock, allow_native_rebuilds=False):
    _, _, _, _, evidence = gather(cfg, partition, roots, 0, allow_native_rebuilds)
    saved = json.loads((out/'merge.json').read_text())
    if {k: v for k, v in saved.items() if k != 'artifacts'} != evidence:
        raise ValueError('reviewed global merge is stale; merge and inspect again')
    if set(saved['artifacts']) != {'results.csv', 'whole_model.csv', 'coverage.json', 'draft.pdf'}:
        raise ValueError('global figure checkpoint incomplete')
    for name, sha in saved['artifacts'].items():
        if digest(out/name) != sha:
            raise ValueError('reviewed merged artifact changed')
    payload = {**evidence, 'purpose': 'mini_sample0_approval' if evidence['subset'] else 'full_sample0_approval',
               'figure_reviewed': True, 'approved_unix': time.time(),
               'merged_artifacts': {**saved['artifacts'], 'merge.json': digest(out/'merge.json')}}
    save(unlock, {**payload, 'integrity_sha256': object_digest(payload)})
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--partition', type=Path, required=True)
    parser.add_argument('--shard-output', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sample', type=int, default=0)
    parser.add_argument('--allow-native-rebuilds', action='store_true')
    parser.add_argument('--approve-figure', action='store_true', help='explicit human review of the existing merged figure')
    parser.add_argument('--unlock', type=Path)
    args = parser.parse_args(); cfg = load(args.config)
    if args.sample < 0 or args.sample >= 500 or (args.approve_figure and args.sample != 0):
        parser.error('approval is for sample 0; sample must be in [0,500)')
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out/'merge.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.approve_figure:
            result = approve(cfg, args.partition, args.shard_output, args.out,
                             args.unlock or args.out/'global_unlock.json', args.allow_native_rebuilds)
        else:
            result = merge(cfg, args.partition, args.shard_output, args.out, args.sample, args.allow_native_rebuilds)
        print(json.dumps({k: result[k] for k in ('sample', 'subset', 'selected_global_pairs', 'result_rows', 'complete_cases')}))


if __name__ == '__main__':
    main()
