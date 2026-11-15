"""Partition validation and the portable, explicit global sample-0 approval."""
import hashlib
import json
from pathlib import Path

from config import digest, key

TERMINAL = {'complete', 'resumed', 'failed', 'timeout', 'skipped_oom', 'skipped_budget'}


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def native_inputs(shared):
    return {k: v for k, v in shared.items() if k in ('cachesim', 'eventsim') or k.startswith('generator_')}


def comparable_inputs(shared):
    return {k: v for k, v in shared.items() if k not in native_inputs(shared)}


def read_partition(path, manifest_path):
    plan = json.loads(path.read_text())
    manifest = json.loads(manifest_path.read_text())
    feasible = {key(c) for c in manifest['schedules'] if c['solver_status'] != 'INFEASIBLE'}
    infeasible = {key(c) for c in manifest['schedules'] if c['solver_status'] == 'INFEASIBLE'}
    if len(feasible) != 749 or len(infeasible) != 6 or plan['manifest_sha256'] != digest(manifest_path):
        raise ValueError('partition does not match the 749+6 schedule manifest')
    for label, expected in (('feasible_case_keys', feasible), ('infeasible_case_keys', infeasible)):
        if len(plan[label]) != len(set(plan[label])) or set(plan[label]) != expected:
            raise ValueError('partition omitted, duplicated or changed '+label)
    selected = plan['selected_case_keys']
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= feasible:
        raise ValueError('invalid selected case keys')
    if plan['subset'] != (set(selected) != feasible):
        raise ValueError('mini partition cannot masquerade as a full gate')
    assignments, seen = {}, set()
    for shard in plan['shards']:
        name, keys = shard['id'], shard['case_keys']
        if name in assignments or not keys or len(keys) != len(set(keys)) or seen.intersection(keys):
            raise ValueError('duplicate shard or overlapping case keys')
        assignments[name] = set(keys); seen.update(keys)
    if seen != set(selected):
        raise ValueError('shards omit or add selected case keys')
    return plan, assignments


def validate_checkpoint(root, sample, campaign=None, expected_keys=None):
    directory = root/('demo' if sample == 0 else f'samples/sample_{sample:05d}')
    path = directory/'checkpoint.json'
    if not path.exists():
        raise ValueError(f'sample barrier missing: {path}')
    checkpoint = json.loads(path.read_text())
    keys = set(expected_keys if expected_keys is not None else checkpoint['campaign']['cases'])
    if (checkpoint['sample'] != sample or checkpoint['attempts_finished'] != len(keys)
            or set(checkpoint['states']) != keys or not set(checkpoint['states'].values()) <= TERMINAL
            or (campaign is not None and checkpoint['campaign'] != campaign)):
        raise ValueError('sample checkpoint is stale, foreign or incomplete')
    required = {'results.csv', 'whole_model.csv', 'coverage.json'} | ({'draft.pdf'} if sample == 0 else set())
    if set(checkpoint.get('artifacts', {})) != required:
        raise ValueError('sample checkpoint lacks artifact fingerprints')
    for name, sha in checkpoint['artifacts'].items():
        if not (directory/name).exists() or digest(directory/name) != sha:
            raise ValueError('sample checkpoint artifact missing or changed')
    return checkpoint


def verify_unlock(cfg, campaign):
    if not cfg.get('shard_manifest'):
        return
    plan, assignments = read_partition(Path(cfg['shard_manifest']), Path(cfg['manifest']))
    path = Path(cfg.get('global_unlock') or '/nonexistent/global_unlock.json')
    if not path.exists():
        raise ValueError('global sample-0 unlock missing; merge, review the global figure and approve first')
    token = json.loads(path.read_text())
    payload = {k: v for k, v in token.items() if k != 'integrity_sha256'}
    if token.get('integrity_sha256') != object_digest(payload):
        raise ValueError('global unlock integrity mismatch')
    purpose = 'mini_sample0_approval' if plan['subset'] else 'full_sample0_approval'
    if (token.get('figure_reviewed') is not True or token.get('sample') != 0
            or token.get('purpose') != purpose or token.get('subset') != plan['subset']
            or token.get('partition_sha256') != digest(cfg['shard_manifest'])
            or token.get('selected_global_pairs') != len(plan['selected_case_keys'])
            or set(token.get('shards', {})) != set(assignments)
            or token.get('comparable_inputs') != comparable_inputs(campaign['shared'])):
        raise ValueError('foreign or subset-mismatched global unlock')
    if set(token.get('merged_artifacts', {})) != {'results.csv', 'whole_model.csv', 'coverage.json', 'draft.pdf', 'merge.json'}:
        raise ValueError('global unlock must pin all merged checkpoint artifacts')
    evidence = token['shards'][cfg['shard_id']]
    for name, keys in assignments.items():
        if token['shards'][name]['case_keys_sha256'] != object_digest(sorted(keys)):
            raise ValueError('global unlock assignment mismatch')
    checkpoint = Path(cfg['output'])/'demo/checkpoint.json'
    validate_checkpoint(Path(cfg['output']), 0, campaign, assignments[cfg['shard_id']])
    if (evidence['checkpoint_sha256'] != digest(checkpoint)
            or evidence['campaign_sha256'] != object_digest(campaign)
            or evidence['native_inputs'] != native_inputs(campaign['shared'])):
        raise ValueError('this box sample-0 checkpoint/native fingerprint differs from global approval')
