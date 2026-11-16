import json
from pathlib import Path
import subprocess

import pytest
import watch


def test_rate_counts_complete_commits_only():
    now = 100000.
    inventory = {'stokes': {'entries': [dict(sample=0, rows=1677, committed_unix=now-100),
                                      dict(sample=1, rows=1674, committed_unix=now-100),
                                      dict(sample=2, rows=1677, committed_unix=now-30000)],
                             'quarantined_samples': [1, 5], 'observed_unix': now},
                 'delta': {'entries': [], 'quarantined_samples': [], 'observed_unix': now}}
    result = watch.progress(inventory, now)
    assert result['complete'] == 2
    assert result['complete_samples_per_hour'] == {'stokes': 1/6, 'delta': 0}
    assert result['conditional_hours_at_observed_rate'] == 588
    assert '100 requires another front' in result['eta_caveat']


def test_stale_front_prevents_freeze_without_any_campaign_action(tmp_path, monkeypatch):
    def inventory(front, blocks):
        if front['name'] == 'deltaai':
            raise ValueError('master unavailable')
        return {'entries': [], 'quarantined_samples': [], 'observed_unix': 1}
    monkeypatch.setattr(watch, 'inventory', inventory)
    monkeypatch.setattr(watch, 'freeze', lambda *a: pytest.fail('must not freeze stale inventory'))
    assert watch.cycle({'fronts': [{'name': 'delta'}, {'name': 'deltaai'}]}, tmp_path) is False
    status = json.loads((tmp_path / 'status.json').read_text())
    assert status['phase'] == 'waiting_for_front_inventory'
    assert status['errors']['deltaai'] == 'master unavailable'


def test_no_remote_retry_after_connection_failure(monkeypatch):
    front = dict(name='remote', host='host', socket='/socket', root='/root', python_command=['conda', 'run', '-n', 'test', 'python'])
    calls = []
    monkeypatch.setattr(watch, 'socket_identity', lambda f: [1, 2, 3])
    def command(argv):
        calls.append(argv)
        if '-O' not in argv:
            raise subprocess.CalledProcessError(255, argv)
        return ''
    monkeypatch.setattr(watch, 'command', command)
    blocked = {}
    with pytest.raises(subprocess.CalledProcessError):
        watch.inventory(front, blocked)
    assert len(calls) == 2
    with pytest.raises(ValueError, match='suspended'):
        watch.inventory(front, blocked)
    assert len(calls) == 2
    assert '-o' in calls[1] and 'ProxyCommand=false' in calls[1]


def test_inventory_watermark_excludes_racing_commits(tmp_path, monkeypatch):
    def inventory(front, blocks):
        return {'entries': [{'sample': 2, 'rows': 1677, 'committed_unix': 101., 'front': front['name']}],
                'quarantined_samples': [], 'observed_unix': 100.}
    monkeypatch.setattr(watch, 'inventory', inventory)
    monkeypatch.setattr(watch, 'mirror', lambda *a: pytest.fail('commit is newer than inventory watermark'))
    assert watch.cycle({'fronts': [{'name': 'delta'}]}, tmp_path) is False
    assert json.loads((tmp_path / 'verified_inventory.json').read_text())['samples'] == []


def test_reports_are_periodic_and_final_delivery_is_retried(tmp_path, monkeypatch):
    status = dict(phase='waiting_for_commits', complete=11,
                  quarantined_partials={'stokes': [1,5]}, complete_samples_per_hour={'stokes': 1.67},
                  errors={}, conditional_hours_at_observed_rate=53.4, eta_caveat='conditional')
    calls = []
    def run(argv, **kwargs):
        calls.append(kwargs['input'])
        return subprocess.CompletedProcess(argv, 0, 'sent', '')
    monkeypatch.setattr(watch.subprocess, 'run', run)
    cfg = dict(report_command=['send'], report_seconds=7200)
    assert watch.notify(cfg, tmp_path, status)
    assert watch.notify(cfg, tmp_path, status)
    assert len(calls) == 1
    assert calls[0].endswith('\n\nMeow...\n')
    status.update(phase='figures_ready', output='/output')
    assert watch.notify(cfg, tmp_path, status)
    assert len(calls) == 2 and 'no pause' in calls[-1]


def test_notification_failure_does_not_abort_and_can_retry(tmp_path, monkeypatch):
    status = dict(phase='figures_ready', complete=100, quarantined_partials={},
                  complete_samples_per_hour={}, errors={}, conditional_hours_at_observed_rate=0,
                  eta_caveat='', output='/output')
    cfg = dict(report_command=['send'], report_seconds=7200)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('send', 30)
    monkeypatch.setattr(watch.subprocess, 'run', timeout)
    assert watch.notify(cfg, tmp_path, status) is False
    assert json.loads((tmp_path / 'report_delivery.json').read_text())['delivered'] is False
    monkeypatch.setattr(watch.subprocess, 'run',
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, 'sent', ''))
    assert watch.notify(cfg, tmp_path, status) is True
