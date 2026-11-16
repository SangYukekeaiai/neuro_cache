from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full500 as f
from test_full500 import product
from test_full500_quota import quota


def setup_release(root, monkeypatch):
    priced = product(root, 9)
    final = root/'rows/sample_009'
    final.parent.mkdir(parents=True)
    shutil.move(priced, final)
    f.SAVE(final/'commit.json', {'sample': 9, 'rows': 1677,
        'artifacts': {p.name: f.HASH(p) for p in final.iterdir()}})
    f.SAVE(root/'boundary.json', {'max_sample': 12, 'ownership_max_sample': 489,
        'automatic_release': {'enabled': True, 'consumed_retirements': [0, 8]}})
    f.SAVE(root/'release_after_sample000.json', {'approved': True})
    driver = {'samples': {'0': {'phase': 'done'}, '8': {'phase': 'done'},
                         '9': {'phase': 'done'}, '12': {'phase': 'counting'},
                         '13': {'phase': 'counting'}}, 'claimed_blocks': [0, 1]}
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    monkeypatch.setattr(f, 'read_quota', lambda: f.quota_capacity(quota()))
    return driver


def test_verified_retirement_advances_once_and_survives_status_loss(tmp_path, monkeypatch):
    driver = setup_release(tmp_path, monkeypatch)
    before = (tmp_path/'rows/sample_009/results_ng45.csv').read_bytes()
    f.auto_release(tmp_path)
    control = f.LOAD(tmp_path/'boundary.json')
    assert control['max_sample'] == 13
    assert control['automatic_release']['consumed_retirements'] == [0, 8, 9]
    assert control['automatic_release']['releases'][0]['retired_sample'] == 9
    driver.pop('automatic_release')  # Restart before driver_status was saved.
    f.auto_release(tmp_path)
    assert f.LOAD(tmp_path/'boundary.json') == control
    assert (tmp_path/'rows/sample_009/results_ng45.csv').read_bytes() == before


@pytest.mark.parametrize('kind', ['bytes', 'inodes', 'tripwire', 'active', 'error'])
def test_quota_holds_credit_without_touching_existing_work(tmp_path, monkeypatch, kind):
    driver = setup_release(tmp_path, monkeypatch)
    q = f.quota_capacity(quota())
    if kind == 'bytes': q['available_bytes'] = f.SAMPLE_BYTES+f.RESERVE_BYTES-1
    if kind == 'inodes': q['available_inodes'] = f.SAMPLE_INODES+f.RESERVE_INODES-1
    if kind == 'tripwire': q['used_inodes'] = f.INODE_TRIPWIRE-f.SAMPLE_INODES-f.RESERVE_INODES+1
    if kind == 'active': q['capacity'] = 1
    def read():
        if kind == 'error': raise OSError('quota down')
        return q
    monkeypatch.setattr(f, 'read_quota', read)
    before = (tmp_path/'boundary.json').read_bytes()
    f.auto_release(tmp_path)
    assert (tmp_path/'boundary.json').read_bytes() == before
    assert driver['automatic_release']['status'] == 'quota_hold'
    assert driver['samples']['12']['phase'] == 'counting'


def test_cleanup_and_ownership_limit_are_hard_gates(tmp_path, monkeypatch):
    driver = setup_release(tmp_path, monkeypatch)
    scratch = tmp_path/'scratch/sample_009'
    scratch.mkdir(parents=True)
    f.auto_release(tmp_path)
    assert f.boundary(tmp_path) == 12
    assert driver['automatic_release']['status'] == 'awaiting_retirement_cleanup'
    scratch.rmdir()
    control = f.LOAD(tmp_path/'boundary.json')
    control['ownership_max_sample'] = 12
    f.SAVE(tmp_path/'boundary.json', control)
    f.auto_release(tmp_path)
    assert f.boundary(tmp_path) == 12
    assert driver['automatic_release']['status'] == 'ownership_hold'


def test_corrupt_retirement_cannot_release(tmp_path, monkeypatch):
    setup_release(tmp_path, monkeypatch)
    (tmp_path/'rows/sample_009/results_ng45.csv').write_text('corrupt')
    with pytest.raises(ValueError, match='artifact changed'):
        f.auto_release(tmp_path)
    assert f.boundary(tmp_path) == 12


def test_pending_credit_releases_when_quota_recovers(tmp_path, monkeypatch):
    driver = setup_release(tmp_path, monkeypatch)
    monkeypatch.setattr(f, 'read_quota', lambda: f.quota_capacity(quota(950)))
    f.auto_release(tmp_path)
    assert f.boundary(tmp_path) == 12
    monkeypatch.setattr(f, 'read_quota', lambda: f.quota_capacity(quota()))
    f.auto_release(tmp_path)
    assert f.boundary(tmp_path) == 13
    assert driver['automatic_release']['status'] == 'released'
