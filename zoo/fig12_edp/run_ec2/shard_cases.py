"""Create disjoint per-box case lists and configs; no simulations or remote actions."""
import argparse
import json
from pathlib import Path

from config import digest, key, load, save, select
from shards import read_partition


def create(cfg, destination, boxes, mini_keys=()):
    if cfg.get('shard_manifest') or cfg['case_keys'] or cfg['case_limit']:
        raise ValueError('use an unfiltered single-host base config; mini selection is explicit')
    selection = select(cfg)
    cases = selection['cases']
    if mini_keys:
        if len(mini_keys) != len(set(mini_keys)):
            raise ValueError('duplicate mini keys')
        cases = [c for c in cases if key(c) in mini_keys]
        if {key(c) for c in cases} != set(mini_keys):
            raise ValueError('unknown mini case key')
    if not 1 <= boxes <= len(cases):
        raise ValueError('boxes must be positive and cannot produce empty shards')
    bins = [{'id': f'box_{i+1}', 'case_keys': [], 'estimated_records': 0} for i in range(boxes)]
    for case in sorted(cases, key=lambda c: (-c['estimated_records'], key(c))):
        target = min(bins, key=lambda b: (b['estimated_records'], len(b['case_keys']), b['id']))
        target['case_keys'].append(key(case)); target['estimated_records'] += case['estimated_records']
    plan = {'schema': 'fig12_partition_v1', 'manifest_sha256': digest(cfg['manifest']),
            'feasible_case_keys': sorted(key(c) for c in selection['cases']),
            'infeasible_case_keys': sorted(key(c) for c in selection['infeasible']),
            'selected_case_keys': sorted(key(c) for c in cases), 'subset': len(cases) != 749, 'shards': bins}
    path = destination/'partition.json'
    if path.exists():
        raise ValueError('partition already exists; use a new destination to avoid changing a live assignment')
    save(path, plan); read_partition(path, Path(cfg['manifest']))
    def portable(p):
        p = Path(p).resolve(); root = Path(cfg['repo_root'])
        return str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
    for shard in bins:
        output_cfg = {**cfg, 'shard_manifest': portable(path), 'shard_id': shard['id'],
            'global_unlock': portable(destination/'global_unlock.json'),
            'output': str(Path(cfg['output'])/shard['id']), 'scratch': str(Path(cfg['scratch'])/shard['id']),
            'sample_start': 0, 'sample_stop': 1}
        # Repo assets move with the checkout; machine storage paths remain explicit.
        for field in ('repo_root', 'manifest', 'arch_yaml', 'cachesim', 'eventsim', 'energy_table',
                      'cache_a', 'cache_b', 'record_estimates'):
            output_cfg[field] = portable(output_cfg[field])
        save(destination/(shard['id']+'.json'), output_cfg)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--boxes', type=int, default=3)
    parser.add_argument('--mini-case-key', action='append', default=[])
    args = parser.parse_args()
    plan = create(load(args.config), args.out.resolve(), args.boxes, args.mini_case_key)
    print(json.dumps({'shards': {s['id']: len(s['case_keys']) for s in plan['shards']},
                      'selected_pairs': len(plan['selected_case_keys']), 'infeasible': 6, 'subset': plan['subset']}))


if __name__ == '__main__':
    main()
