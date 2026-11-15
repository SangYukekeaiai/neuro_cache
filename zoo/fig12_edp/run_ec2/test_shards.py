"""Partition, global approval, source-pinning and owned scratch regression tests."""
import copy
import json
from pathlib import Path
import shutil

import pytest

import config
from config import HERE, digest, key, load, save
from merge_results import approve, gather
from pipeline import cleanup_scratch, scratch_for
from run import preflight
from shards import object_digest, read_partition, verify_unlock

MINI = HERE/'t86_mini'


def fixture_data():
    cfg = load(MINI/'base.json')
    partition = MINI/'plan/partition.json'
    roots = [MINI/'outputs'/f'box_{i}' for i in (1, 2)]
    return cfg, partition, roots


def test_real_partition_is_disjoint_exhaustive():
    cfg, partition, _ = fixture_data()
    plan, assignments = read_partition(partition, Path(cfg['manifest']))
    assert len(plan['feasible_case_keys']) == 749 and len(plan['infeasible_case_keys']) == 6
    assert len(set.union(*assignments.values())) == 2 and plan['subset']
    full, boxes = read_partition(HERE/'three_box_plan/partition.json', Path(cfg['manifest']))
    assert not full['subset'] and len(boxes) == 3
    assert sum(map(len, boxes.values())) == len(set.union(*boxes.values())) == 749


@pytest.mark.parametrize('mutation', ['duplicate_shard', 'overlap', 'omission', 'fake_full', 'missing_feasible', 'missing_infeasible'])
def test_invalid_partitions_rejected(tmp_path, mutation):
    cfg, partition, _ = fixture_data(); plan = json.loads(partition.read_text())
    if mutation == 'duplicate_shard':
        plan['shards'][1]['id'] = plan['shards'][0]['id']
    elif mutation == 'overlap':
        plan['shards'][1]['case_keys'] = plan['shards'][0]['case_keys'][:]
    elif mutation == 'omission':
        plan['shards'].pop()
    elif mutation == 'fake_full':
        plan['subset'] = False
    elif mutation == 'missing_feasible':
        plan['feasible_case_keys'].pop()
    else:
        plan['infeasible_case_keys'].pop()
    path = tmp_path/'partition.json'; save(path, plan)
    with pytest.raises(ValueError):
        read_partition(path, Path(cfg['manifest']))


def test_missing_duplicate_and_modified_shard_artifact(tmp_path):
    cfg, partition, roots = fixture_data()
    with pytest.raises(ValueError, match='missing shard'):
        gather(cfg, partition, roots[:1], 0)
    with pytest.raises(ValueError, match='duplicate'):
        gather(cfg, partition, [roots[0], roots[0]], 0)
    clone = tmp_path/'box_1'; shutil.copytree(roots[0], clone)
    with (clone/'demo/results.csv').open('a') as stream:
        stream.write('\n')
    with pytest.raises(ValueError, match='artifact'):
        gather(cfg, partition, [clone, roots[1]], 0)


@pytest.mark.parametrize('field', ['energy_table', 'cache_a', 'runner/collect.py'])
def test_foreign_scientific_inputs_rejected(tmp_path, field):
    cfg, partition, roots = fixture_data()
    clone = tmp_path/'box_1'; shutil.copytree(roots[0], clone)
    campaign = json.loads((clone/'campaign.json').read_text()); campaign['shared'][field] = 'foreign'
    save(clone/'campaign.json', campaign)
    with pytest.raises(ValueError, match='foreign source/table/config'):
        gather(cfg, partition, [clone, roots[1]], 0)


def test_mutated_collect_source_refuses_real_preflight_resume(tmp_path, monkeypatch):
    # Hash a private copy under canonical source names; never edit the running implementation.
    sources = tmp_path/'sources'; sources.mkdir()
    for name in ('pipeline.py', 'config.py', 'collect.py', 'run.py', 'plot.py', 'shards.py', 'shard_cases.py', 'merge_results.py'):
        shutil.copy2(HERE/name, sources/name)
    monkeypatch.setattr(config, 'HERE', sources)
    cfg = load(MINI/'plan/box_1.json'); cfg['output'] = str(tmp_path/'output')
    Path(cfg['output']).mkdir()
    preflight(cfg)
    path = sources/'collect.py'; before = path.read_text()
    changed = before.replace("'model_EDP_nJ_s': energy*latency", "'model_EDP_nJ_s': energy+latency")
    assert changed != before; path.write_text(changed)
    with pytest.raises(ValueError, match='fingerprint changed'):
        preflight(cfg)


@pytest.mark.parametrize('field,value', [('sample', 1), ('figure_reviewed', False)])
def test_approval_metadata_cannot_drift_even_with_recomputed_digest(tmp_path, field, value):
    cfg = load(MINI/'plan/box_1.json')
    campaign = json.loads((Path(cfg['output'])/'campaign.json').read_text())
    token = json.loads((MINI/'plan/global_unlock.json').read_text())
    token[field] = value
    token['integrity_sha256'] = object_digest({k: v for k, v in token.items() if k != 'integrity_sha256'})
    cfg['global_unlock'] = str(tmp_path/'unlock.json'); save(Path(cfg['global_unlock']), token)
    with pytest.raises(ValueError, match='global unlock'):
        verify_unlock(cfg, campaign)


def test_unlock_required_and_this_box_checkpoint_pinned(tmp_path):
    cfg = load(MINI/'plan/box_1.json')
    campaign = json.loads((Path(cfg['output'])/'campaign.json').read_text())
    cfg['global_unlock'] = str(tmp_path/'absent.json')
    with pytest.raises(ValueError, match='unlock missing'):
        verify_unlock(cfg, campaign)
    clone = tmp_path/'output'; shutil.copytree(Path(cfg['output']), clone)
    cfg['output'] = str(clone); cfg['global_unlock'] = str(MINI/'plan/global_unlock.json')
    # Harmless whitespace still changes the exact checkpoint the reviewer approved.
    with (clone/'demo/checkpoint.json').open('a') as stream:
        stream.write('\n')
    with pytest.raises(ValueError, match='this box'):
        verify_unlock(cfg, campaign)


def test_approval_refuses_changed_merged_figure(tmp_path):
    cfg, partition, roots = fixture_data()
    out = tmp_path/'merged'; shutil.copytree(MINI/'merged', out)
    with (out/'draft.pdf').open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='merged artifact changed'):
        approve(cfg, partition, roots, out, tmp_path/'unlock.json')


def test_success_and_resume_cleanup_guard(tmp_path):
    cfg = load(MINI/'plan/box_1.json')
    selection = json.loads((Path(cfg['output'])/'selection.json').read_text()); case = selection['cases'][0]
    source = Path(cfg['output'])/'cases'/key(case)/'sample_00000'
    target = tmp_path/'output/cases'/key(case)/'sample_00000'; shutil.copytree(source, target)
    cfg.update(output=str(tmp_path/'output'), scratch=str(tmp_path/'scratch'))
    expected = json.loads((target/'result.json').read_text())['fingerprint']
    scratch = scratch_for(cfg, case, 0); scratch.mkdir(parents=True)
    save(scratch/'owner.json', expected); (scratch/'tmp_native.yaml').write_text('owned')
    (scratch/'nested').mkdir(); (scratch/'nested/task.bin').write_bytes(b'owned')
    cleanup_scratch(cfg, case, 0, expected)
    assert not scratch.exists()
    scratch.mkdir(); save(scratch/'owner.json', {'foreign': True})
    with pytest.raises(ValueError, match='foreign scratch'):
        cleanup_scratch(cfg, case, 0, expected)
    assert scratch.exists()
    save(scratch/'owner.json', expected)
    (target/'result.json').rename(target/'result.saved.json')
    with pytest.raises(FileNotFoundError):
        cleanup_scratch(cfg, case, 0, expected)
    assert scratch.exists(), 'failure/partial scratch must remain'
