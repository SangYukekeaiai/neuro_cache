import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recovery


def prepare(tmp_path, status='interrupted', chunk=6600):
    receipt = {'status': status, 'attempt': 1, 'retry': None}
    (tmp_path/'attempt_1.json').write_text(json.dumps(receipt))
    (tmp_path/'attempt_0.json').write_text('tier-zero-evidence')
    (tmp_path/'dispatch.json').write_text(json.dumps({'job': '123_0', 'restart': 0, 'chunk_seconds': chunk}))
    (tmp_path/'inputs.json').write_text('fingerprint')
    (tmp_path/'cache_a.log').write_text('original output')
    return receipt


@pytest.mark.parametrize('status,slurm', [('running','PREEMPTED'), ('running','TIMEOUT'),
                                       ('interrupted','COMPLETED')])
def test_interruption_reopens_same_tier_with_evidence(tmp_path, status, slurm):
    receipt = prepare(tmp_path, status)
    assert recovery.resume_interrupted(tmp_path, receipt, {'job':'124_0','restart':0}, lambda _:slurm)
    archive, = (tmp_path/'resume_history').iterdir()
    assert json.loads((archive/'attempt_1.json').read_text()) == receipt
    assert (archive/'cache_a.log').read_text() == 'original output'
    assert (tmp_path/'inputs.json').read_text() == 'fingerprint'
    assert (tmp_path/'attempt_0.json').read_text() == 'tier-zero-evidence'
    assert not (tmp_path/'attempt_1.json').exists()


@pytest.mark.parametrize('slurm', ['RUNNING','PENDING','FAILED','OUT_OF_MEMORY'])
def test_live_or_unrelated_failure_cannot_be_reopened(tmp_path, slurm):
    receipt = prepare(tmp_path)
    with pytest.raises(ValueError, match='not safely retired'):
        recovery.resume_interrupted(tmp_path, receipt, {'job':'124_0','restart':0}, lambda _:slurm)
    assert (tmp_path/'attempt_1.json').exists()


def test_same_job_requires_slurm_restart_increment(tmp_path):
    receipt = prepare(tmp_path, 'running', 0)
    with pytest.raises(ValueError):
        recovery.resume_interrupted(tmp_path, receipt, {'job':'123_0','restart':0})
    assert recovery.resume_interrupted(tmp_path, receipt, {'job':'123_0','restart':1})


def test_resource_failure_is_not_preemption(tmp_path):
    receipt = prepare(tmp_path, 'oom')
    assert not recovery.resume_interrupted(tmp_path, receipt, {'job':'124_0','restart':0})
    assert (tmp_path/'attempt_1.json').exists()
