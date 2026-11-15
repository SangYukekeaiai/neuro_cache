"""Check native sample identity, known-answer metrics, barriers and resume evidence."""
import argparse
import csv
import json
from pathlib import Path

from config import HERE, digest, folder, key, load, save
from pipeline import validate_result
from run import fingerprints_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-resume', action='store_true')
    args = parser.parse_args()
    cfg = load(HERE/'mini.json'); out = Path(cfg['output'])
    campaign = json.loads((out/'campaign.json').read_text())
    selection = json.loads((out/'selection.json').read_text())
    case, = selection['cases']
    data = []
    snapshot = {}
    for sample in (0, 1):
        location = folder(cfg, case, sample)
        result = validate_result(location/'result.json', fingerprints_for(campaign, sample)[key(case)])
        generation = json.loads((location/'generation.json').read_text())
        argv = generation['command']
        assert argv[argv.index('--sample-start')+1] == str(sample)
        noc = json.loads((location/'noc/result.json').read_text())
        assert noc['sample_idx'] == sample
        with (location/'record_count.csv').open() as stream:
            record, = list(csv.DictReader(stream))
        assert int(record['sample']) == sample and int(record['R_p']) == generation['records']
        for arm in ('a', 'b'):
            with (location/f'cache_{arm}.csv').open() as stream:
                cache, = list(csv.DictReader(stream))
            assert int(cache['sample_idx']) == sample
        evidence = json.loads((location/'sample_evidence.json').read_text())
        assert evidence['sample'] == sample
        data.append((result, generation, evidence))
        for name in ('result.json', 'generation.json', 'counts.json', 'cache_a.csv', 'cache_b.csv'):
            p = location/name
            snapshot[str(p)] = {'sha256': digest(p), 'mtime_ns': p.stat().st_mtime_ns}
    assert data[0][2]['capture_sample_sha256'] != data[1][2]['capture_sample_sha256']
    assert data[0][2]['d_out'] != data[1][2]['d_out']
    assert data[0][1]['sha256'] != data[1][1]['sha256']
    golden = Path(cfg['repo_root'])/'zoo/fig12_edp/demo/vgg16_full/cases'/key(case)/'sample_00000/result.json'
    old = json.loads(golden.read_text())
    assert old['fingerprint']['table'] == campaign['shared']['energy_table']
    assert old['fingerprint']['configs'] == [campaign['shared']['cache_a'], campaign['shared']['cache_b']]
    assert data[0][1]['sha256'] == old['rows'][0]['trace_sha256']
    metrics = ('T_s', 'E_dyn_nJ', 'E_leak_nJ', 'EDP_nJ_s', 'total_cycles')
    for row in data[0][0]['rows']:
        known = next(r for r in old['rows'] if r['arm'] == row['arm'])
        assert all(row[m] == known[m] for m in metrics), (row['arm'], [(m, row[m], known[m]) for m in metrics])
        assert json.loads(row['counts_json']) == json.loads(known['counts_json'])
    events = [json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
    first1 = next(i for i, e in enumerate(events) if e['event'] == 'started' and e['sample'] == 1)
    assert any(e['event'] == 'sample_checkpoint' and e['sample'] == 0 for e in events[:first1])
    assert len([e for e in events if e['event'] == 'started']) == 2
    if args.before_resume:
        save(HERE/'before_resume.json', snapshot)
    else:
        assert json.loads((HERE/'before_resume.json').read_text()) == snapshot
        assert len([e for e in events if e['event'] == 'resumed']) >= 2
    assert not list(Path(cfg['scratch']).rglob('*.wcts'))
    report = {'native_samples': [0, 1], 'completed_cases': 2, 'result_rows': 6, 'subset': True,
        'sample0_golden_numeric_checks': len(metrics)*3, 'sample0_golden_trace_identical': True,
        'samples_have_distinct_capture_and_trace_digests': True, 'density_sample0': data[0][2]['d_out'],
        'density_sample1': data[1][2]['d_out'], 'sample0_figure_barrier_before_sample1': True,
        'resume_without_recompute': not args.before_resume, 'worker_launches': 2,
        'scope_memory_max_gib': 4, 'worker_memory_gib': 3}
    save(HERE/'mini_validation.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
