import json
from pathlib import Path

import numpy as np
import pytest

import collect
from collect import bootstrap_weights, digest, freeze, read_sample, select_entries, summarize, verify_commit


def entry(sample, rows=1677, front='stokes'):
    return dict(sample=sample, rows=rows, front=front, committed_unix=sample + 100.,
                commit_sha256='a' * 64, mirror='/unused')


def test_quarantined_partials_do_not_count_and_duplicates_fail():
    entries = [entry(1, 1674), entry(5, 1674)] + [entry(i) for i in range(10, 112)]
    assert [e['sample'] for e in select_entries(entries)] == list(range(10, 110))
    with pytest.raises(ValueError, match='duplicate'):
        select_entries([entry(10), entry(10, front='delta')])


def test_freeze_is_immutable_and_waits_for_100(tmp_path):
    path = tmp_path / 'snapshot.json'
    entries = [entry(i) for i in range(100)]
    with pytest.raises(ValueError, match='not yet'):
        freeze(path, entries[:-1])
    assert not path.exists()
    first = freeze(path, entries)
    assert freeze(path, list(reversed(entries))) == first
    changed = [dict(e) for e in entries]
    changed[0]['front'] = 'delta'
    with pytest.raises(ValueError, match='cannot change'):
        freeze(path, changed)


def test_sample_bootstrap_matches_explicit_resampling_and_preserves_nulls():
    weights = bootstrap_weights(3, repetitions=200, seed=17)
    values = np.array([[1., np.nan], [3., np.nan], [20., np.nan]])
    result = summarize([('complete',), ('infeasible',)], {'T': values}, weights, ('group',))
    explicit = np.array([sum(v * w for v, w in zip(values[:, 0], row)) for row in weights])
    assert result[0]['T_mean'] == 8
    assert result[0]['T_ci95_low'] == pytest.approx(np.quantile(explicit, .025))
    assert result[0]['T_ci95_high'] == pytest.approx(np.quantile(explicit, .975))
    assert result[1]['T_mean'] is result[1]['T_ci95_low'] is result[1]['T_ci95_high'] is None
    with pytest.raises(ValueError, match='missing samples'):
        summarize([('partial',)], {'T': [[1], [np.nan], [3]]}, weights, ('group',))


def test_whole_model_edp_is_mean_of_products_not_product_of_means():
    weights = bootstrap_weights(2, repetitions=200)
    energy, latency = np.array([1., 9.]), np.array([9., 1.])
    result = summarize([('model',)], {'EDP': (energy * latency)[:, None]}, weights, ('group',))
    assert result[0]['EDP_mean'] == 9
    assert result[0]['EDP_mean'] != energy.mean() * latency.mean()
    assert result[0]['EDP_ci95_low'] == result[0]['EDP_ci95_high'] == 9


def test_commit_digest_and_partial_rejection(tmp_path):
    path = tmp_path / 'commit.json'
    path.write_text(json.dumps(dict(sample=5, rows=1674)))
    e = entry(5, rows=1674)
    e['commit_sha256'] = digest(path)
    with pytest.raises(ValueError, match='full 559'):
        verify_commit(tmp_path, e)
    path.write_text('{}')
    with pytest.raises(ValueError, match='commit changed'):
        verify_commit(tmp_path, e)


def test_expected_zero_is_exact():
    with pytest.raises(ValueError, match='arithmetic'):
        collect.same(1e-30, 0., 'zero')
    collect.same(0., 0., 'zero')


def test_collection_aggregates_sample_products_and_preserves_raw_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, 'TARGET', 2)
    monkeypatch.setattr(collect, 'verify_commit', lambda *a: None)
    keys = [('model', 'arch', 'spad'), ('infeasible', 'arch', 'spad')]
    def read(folder, sample):
        energy, latency = ((1., 9.) if sample == 0 else (9., 1.))
        case = dict(T_s=latency, E_dyn_nJ=energy, E_leak_nJ=0., energy_nJ=energy,
                    EDP_nJ_s=energy * latency, total_cycles=latency * 500e6)
        models = {keys[0]: dict(completed_layers=1, expected_layers=1, infeasible_layers=0,
                               coverage_complete=True, sum_latency_s=latency,
                               sum_energy_nJ=energy, model_EDP_nJ_s=energy * latency,
                               sum_layer_EDP_nJ_s=energy * latency),
                  keys[1]: dict(completed_layers=1, expected_layers=2, infeasible_layers=1,
                               coverage_complete=False, **{m: None for m in collect.MODEL_METRICS})}
        return [dict(sample=str(sample), EDP_nJ_s=str(energy * latency))], {('arch', 'model', 'layer', 'spad'): case}, models, 'scope'
    monkeypatch.setattr(collect, 'read_sample', read)
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(dict(samples=[entry(0), entry(1)], energy_table_sha256=collect.TABLE_SHA)))
    output = tmp_path / 'products'
    collect.collect(snapshot, output)
    rows = collect.read_csv(output / 'whole_model_partial100.csv')
    complete = next(r for r in rows if r['benchmark'] == 'model')
    assert float(complete['model_EDP_nJ_s_mean']) == 9
    assert float(complete['sum_energy_nJ_mean']) * float(complete['sum_latency_s_mean']) == 25
    incomplete = next(r for r in rows if r['benchmark'] == 'infeasible')
    assert all(incomplete[m + '_mean'] == '' for m in collect.MODEL_METRICS)
    assert [r['sample'] for r in collect.read_csv(output / 'results_partial100.csv')] == ['0', '1']
