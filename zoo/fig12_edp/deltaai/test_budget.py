import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('arm_budget', Path(__file__).with_name('budget.py'))
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def test_shared_cap_counts_double_charge_and_releases_unused_reservation():
    records = {}
    budget.reserve(records, 'normal', 4, 21600, cap=40)
    budget.reserve(records, 'interactive', 8, 7200, cap=40)
    assert sum(map(budget.charge, records.values())) == 40
    with pytest.raises(ValueError, match='cap reached'):
        budget.reserve(records, 'another', 4, 21600, cap=40)
    records['normal']['measured_hours'] = 4
    budget.reserve(records, 'next_interactive', 8, 7200, cap=40)
    assert sum(map(budget.charge, records.values())) == 36


def test_duplicate_entry_does_not_charge_twice():
    records = {}
    budget.reserve(records, 'job', 4, 21600)
    budget.reserve(records, 'job', 4, 21600)
    assert sum(map(budget.charge, records.values())) == 24


def test_unknown_accounting_keeps_full_reservation(monkeypatch):
    records = {}
    budget.reserve(records, 'job', 8, 7200)
    monkeypatch.setattr(budget.subprocess, 'check_output', lambda *a, **k:'job|RUNNING|20|\n')
    budget.refresh(records)
    assert budget.charge(records['job']) == 16
    monkeypatch.setattr(budget.subprocess, 'check_output', lambda *a, **k:'job|COMPLETED|1800|\n')
    budget.refresh(records)
    assert budget.charge(records['job']) == 4


@pytest.mark.parametrize('partition,gpus,expected', [
    ('ghx4','4',(4,21600)), ('ghx4-interactive','4',(8,7200)),
    ('ghx4-interactive','1',(2,7200))])
def test_actual_gpu_count_sets_rate(partition,gpus,expected):
    assert budget.reservation_parameters({'SLURM_JOB_PARTITION':partition,'SLURM_GPUS_ON_NODE':gpus}) == expected
