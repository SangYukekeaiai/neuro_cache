"""Keep attention GEMMs, omit FC/FFN, and retain nominal infeasible coverage."""
import csv
import json
import pytest

import common
import layer_scope
import report


def test_rule_matches_every_documented_layer_and_campaign_pair():
    capture = disposition = None
    declared = {}
    for line in layer_scope.SCOPE_PATH.read_text().splitlines():
        if line.startswith('## '):
            capture = line[3:]
        elif line.startswith('Kept ('):
            disposition = True
        elif line.startswith('Skipped'):
            disposition = False
        elif capture and line.startswith('- layer_'):
            declared[capture, line[2:]] = disposition
    assert len(declared) == 151 and sum(declared.values()) == 113
    for (_, layer), expected in declared.items():
        assert bool(layer_scope.kept(layer)) == expected
    manifest=json.loads(common.demo.MANIFEST.read_text())
    selection={'feasible':[c for c in manifest['schedules'] if c['solver_status']!='INFEASIBLE'],
               'infeasible':[c for c in manifest['schedules'] if c['solver_status']=='INFEASIBLE']}
    selection['captures']=manifest['capture_order']
    campaign = {(c['trace_relative_dir'], c['layer'])
                for kind in ('feasible', 'infeasible') for c in selection[kind]}
    assert campaign == declared.keys()
    selected = layer_scope.scoped_selection(selection)
    assert len(selected['feasible']) == 559
    assert len(selected['infeasible']) == 6
    assert layer_scope.scope_summary(selection)['excluded_feasible_pairs'] == 190
    # The attention output matches SKIP too; KEEP must take precedence.
    _, skip, _ = layer_scope.scope_rule()
    layer = 'layer_04_core_bert_encoder_layer_0_attention_output_dense'
    assert skip.search(layer) and layer_scope.kept(layer)


def test_excluded_rows_and_oom_do_not_affect_scope_totals():
    kept = {'arch': 'spinalflow', 'trace_relative_dir': 'example', 'layer': 'layer_01_conv'}
    excluded = {**kept, 'layer': 'layer_02_core_classifier'}
    selection = {'captures': ['example'], 'feasible': [kept, excluded], 'infeasible': []}
    def row(case, energy, latency):
        return {'arch': case['arch'], 'capture': 'example', 'layer': case['layer'], 'arm': 'spad',
                'E_dyn_nJ': energy, 'E_leak_nJ': 0, 'T_s': latency, 'EDP_nJ_s': energy*latency,
                'incomplete': True, 'energy_table_sha256': 'hash'}
    states = {common.identity(excluded): 'skipped_oom'}
    totals = report.whole_model(selection, [row(kept, 2, 3), row(excluded, 1000, 999)], states)
    first = totals[0]
    assert first['coverage'] == '1/1' and first['coverage_complete']
    assert first['sum_energy_nJ'] == 2 and first['sum_latency_s'] == 3
    assert first['model_EDP_nJ_s'] == first['sum_layer_EDP_nJ_s'] == 6
    assert first['oom_layers'] == 0
    selection['infeasible'] = [{**kept, 'layer': 'layer_03_conv'}]
    first = report.whole_model(selection, [row(kept, 2, 3)], states)[0]
    assert first['coverage'] == '1/2' and first['infeasible_layers'] == 1
    assert first['model_EDP_nJ_s'] is None


def test_collection_keeps_excluded_artifacts_and_driver_states(tmp_path, monkeypatch):
    cases = [{'arch': 'spinalflow', 'trace_relative_dir': 'example', 'layer': name}
             for name in ('layer_01_conv', 'layer_02_core_classifier')]
    selection = {'captures': ['example'], 'feasible': cases, 'infeasible': []}
    monkeypatch.setattr(report, 'HERE', tmp_path)
    originals = {}
    for case in cases:
        folder = common.demo.folder_for(case, tmp_path)
        folder.mkdir(parents=True)
        path = folder/'result.json'
        path.write_text('preserve this original result')
        originals[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    def verified(case, folder, inputs):
        return [{'arch': case['arch'], 'capture': 'example', 'layer': case['layer'], 'arm': arm,
                 'E_dyn_nJ': 2, 'E_leak_nJ': 0, 'T_s': 3, 'EDP_nJ_s': 6,
                 'incomplete': True, 'energy_table_sha256': 'hash'} for arm in common.ARMS]
    monkeypatch.setattr(report, 'validate_case', verified)
    states = report.collect(selection, {})
    assert set(states.values()) == {'complete'} and len(states) == 2
    rows = list(csv.DictReader((tmp_path/'results.csv').open()))
    assert len(rows) == 3 and {r['layer'] for r in rows} == {'layer_01_conv'}
    coverage = json.loads((tmp_path/'coverage.json').read_text())
    assert list(coverage['case_states']) == [common.identity(cases[0])]
    assert list(coverage['excluded_case_states']) == [common.identity(cases[1])]
    assert coverage['scope']['sha256'] == common.demo.digest(layer_scope.SCOPE_PATH)
    for path, original in originals.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original


def test_plot_rejects_unfiltered_coverage(tmp_path, monkeypatch):
    import plot
    (tmp_path/'coverage.json').write_text('{}')
    monkeypatch.setattr('sys.argv', ['plot.py', '--input', str(tmp_path/'whole_model.csv')])
    with pytest.raises(ValueError, match='current workload scope'):
        plot.main()
