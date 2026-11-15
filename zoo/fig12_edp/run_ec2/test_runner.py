"""Pure scheduling/fingerprint tests plus verification of the real two-sample mini."""
import json
from pathlib import Path

import pytest

from config import HERE, digest, folder, key, load, scientific_inputs
from run import can_start, next_tier, reserve_tier, require_previous, run_sample


def budget():
    return {'memory_tiers_gib': [8, 32, 96, 224], 'memory_budget_gib': 240,
            'driver_reserve_gib': 4, 'workers': 4, 'serial_at_gib': 96}


def test_memory_reservations_and_serial_giants():
    cfg = budget()
    assert reserve_tier(63, cfg) == 96
    assert reserve_tier(200, cfg) == 224
    assert reserve_tier(300, cfg) is None
    assert can_start(8, [8, 8, 8], cfg)
    assert not can_start(8, [8, 8, 8, 8], cfg)
    assert can_start(224, [], cfg)
    assert not can_start(224, [8], cfg)
    assert not can_start(8, [224], cfg)
    assert not can_start(224, [], {**cfg, 'memory_budget_gib': 200})
    assert not can_start(32, [32], {**cfg, 'memory_budget_gib': 60})


def test_oom_escalation_is_finite():
    cfg = budget(); tier = 8; attempts = []
    while tier is not None:
        attempts.append(tier); tier = next_tier(tier, cfg)
    assert attempts == [8, 32, 96, 224]


def test_sample_barrier_fails_closed(tmp_path):
    cfg = {'output': str(tmp_path)}; selection = {'cases': [1, 2]}; campaign = {'identity': 7}
    require_previous(cfg, selection, campaign, 0)
    with pytest.raises(ValueError, match='barrier'):
        require_previous(cfg, selection, campaign, 1)
    (tmp_path/'demo').mkdir()
    p = tmp_path/'demo/checkpoint.json'
    p.write_text(json.dumps({'campaign': campaign, 'attempts_finished': 1}))
    with pytest.raises(ValueError, match='incomplete'):
        require_previous(cfg, selection, campaign, 1)
    artifacts = {}
    for name in ('results.csv', 'whole_model.csv', 'coverage.json', 'draft.pdf'):
        file = p.parent/name; file.write_text('test checkpoint')
        artifacts[name] = digest(file)
    p.write_text(json.dumps({'campaign': campaign, 'attempts_finished': 2, 'artifacts': artifacts}))
    require_previous(cfg, selection, campaign, 1)
    with pytest.raises(ValueError, match='stale'):
        require_previous(cfg, selection, {'identity': 8}, 1)
    (p.parent/'draft.pdf').write_text('changed')
    with pytest.raises(ValueError, match='artifact'):
        require_previous(cfg, selection, campaign, 1)


def test_config_pin_rejects_change(tmp_path):
    cfg = load(HERE/'mini.json')
    altered = json.loads(Path(cfg['cache_a']).read_text()); altered['l2_prefetch_distance'] = 4
    path = tmp_path/'changed_a.json'; path.write_text(json.dumps(altered))
    cfg['cache_a'] = str(path)
    with pytest.raises(ValueError, match='pinned SHA256'):
        scientific_inputs(cfg)


def test_paths_and_sample_ranges_are_explicit(tmp_path):
    cfg = json.loads((HERE/'mini.json').read_text())
    cfg['sample_start'] = 1; cfg['sample_stop'] = 1
    p = tmp_path/'bad.json'; p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match='samples'):
        load(p)
    cfg['sample_stop'] = 2; cfg['output'] = cfg['capture_root']; p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match='protected'):
        load(p)


def test_over_budget_is_reported_without_a_worker(tmp_path, monkeypatch):
    cfg = load(HERE/'mini.json')
    cfg.update(output=str(tmp_path/'output'), scratch=str(tmp_path/'scratch'), memory_tiers_gib=[1])
    Path(cfg['output']).mkdir(); Path(cfg['scratch']).mkdir()
    selection = json.loads((HERE/'mini_output/selection.json').read_text())
    case, = selection['cases']
    campaign = {'shared': {}, 'cases': {key(case): {}}, 'subset': True}
    def no_worker(*args, **kwargs):
        raise AssertionError('over-budget case must never launch')
    monkeypatch.setattr('run.subprocess.Popen', no_worker)
    run_sample(cfg, selection, campaign, 1)
    failure = json.loads((folder(cfg, case, 1)/'failure.json').read_text())
    assert failure['status'] == 'skipped_budget'
    checkpoint = json.loads((Path(cfg['output'])/'samples/sample_00001/checkpoint.json').read_text())
    assert checkpoint['attempts_finished'] == 1 and checkpoint['complete_cases'] == 0
    assert not checkpoint['full_sample_complete']


def test_modified_durable_artifact_is_rejected(tmp_path):
    import shutil
    from pipeline import validate_result
    cfg = load(HERE/'mini.json')
    selection = json.loads((HERE/'mini_output/selection.json').read_text())
    source = folder(cfg, selection['cases'][0], 1)
    target = tmp_path/'case'; shutil.copytree(source, target)
    result = json.loads((target/'result.json').read_text())
    with (target/'counts.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='artifact changed'):
        validate_result(target/'result.json', result['fingerprint'])
