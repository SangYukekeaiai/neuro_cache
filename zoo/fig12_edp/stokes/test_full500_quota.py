from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full500 as f


def quota(used_gib=348, used_inodes=387674):
    return (f'Disk quotas for usr test\n Filesystem kbytes quota limit grace files quota limit grace\n'
            f' /lustre/fs1 {used_gib*1024**2} 1048576000 1059061760 - '
            f'{used_inodes} 1000000 1010000 -\n')


def test_real_quota_units_and_both_reservations():
    record = f.quota_capacity(quota())
    assert record['capacity'] == 8
    assert record['available_bytes'] == 652*1024**3
    assert record['available_inodes'] == 612326
    assert f.quota_capacity(quota(950))['capacity'] == 0
    assert f.quota_capacity(quota(348, 990000))['capacity'] == 0
    assert f.quota_capacity(quota(1100).replace('1153433600 ', '1153433600* '))['capacity'] == 0
    # Removing 163 GiB alone cannot raise depth while the inode quota binds.
    assert f.quota_capacity(quota(348-163))['capacity'] == 8


@pytest.mark.parametrize('text', ['', 'lfs: unavailable', quota()+quota(),
    '/lustre/fs1 1 0 0 - 1 0 0 -', '/lustre/fs1 -1 20 30 - 1 20 30 -'])
def test_unreadable_or_unbounded_quota_fails_closed(text):
    with pytest.raises(ValueError): f.quota_capacity(text)


def test_admission_reserves_for_all_active_samples_and_keeps_grandfathered(tmp_path, monkeypatch):
    f.SAVE(tmp_path/'release_after_sample000.json', {'approved': True})
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 499})
    driver = {'samples': {'0': {'phase': 'done'}}, 'claimed_blocks': [0]}
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    monkeypatch.setattr(f, 'read_quota', lambda: f.quota_capacity(quota()))
    f.admit_samples(tmp_path)
    assert set(driver['samples']) == set(map(str, range(9)))
    assert driver['quota_admission']['active_samples'] == 8
    for i in range(9, 16): driver['samples'][str(i)] = {'phase': 'counting', 'jobs': [{'id': str(i)}]}
    before = {k: v.copy() for k, v in driver['samples'].items()}
    f.admit_samples(tmp_path)
    assert driver['samples'] == before
    assert driver['quota_admission']['active_samples'] == 15
    assert driver['quota_admission']['admissions_held']


def test_quota_error_does_not_stop_existing_dispatch_or_pricing(tmp_path, monkeypatch):
    f.SAVE(tmp_path/'release_after_sample000.json', {'approved': True})
    f.SAVE(tmp_path/'boundary.json', {'max_sample': 499})
    driver = {'samples': {'0': {'phase': 'done'}, '1': {'phase': 'ready_to_price'},
              '2': {'phase': 'counting', 'jobs': [],
                    'pending': [{'index': 4, 'attempt': 0, 'tier': 0}]}}, 'claimed_blocks': [0]}
    monkeypatch.setattr(f, 'DRIVER', driver, raising=False)
    def unavailable(): raise OSError('quota unavailable')
    monkeypatch.setattr(f, 'read_quota', unavailable)
    f.admit_samples(tmp_path)
    assert set(driver['samples']) == {'0', '1', '2'}
    assert driver['quota_admission']['capacity'] == 0
    actions = []
    monkeypatch.setattr(f, 'queue_state', lambda: (0, 0))
    monkeypatch.setattr(f, 'price_submit', lambda *args: actions.append(('price', args[1])))
    monkeypatch.setattr(f, 'submit', lambda *args: actions.append(('compute', args[2])))
    f.dispatch(tmp_path, 'worker', 'price')
    assert actions == [('price', 1), ('compute', 2)]
