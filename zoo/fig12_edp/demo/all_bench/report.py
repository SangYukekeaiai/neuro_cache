"""Collect validated cases and expose coverage before computing whole-model totals."""
import json
from common import ARMS, HERE, demo, identity, validate_case, write_csv
from layer_scope import kept, scoped_selection, scope_summary


def collect(selection, inputs):
    rows, states = [], {}
    for case in selection['feasible']:
        folder = demo.folder_for(case, HERE)
        key = identity(case)
        if (folder/'result.json').exists():
            try:
                verified = validate_case(case, folder, inputs)
                if kept(case['layer']):
                    rows.extend(verified)
                states[key] = 'complete'
                continue
            except (ValueError, KeyError, OSError) as error:
                failure = folder/'failure.json'
                states[key] = (json.loads(failure.read_text())['status'] if failure.exists()
                               else 'stale: '+str(error))
                continue
        if (folder/'failure.json').exists():
            states[key] = json.loads((folder/'failure.json').read_text())['status']
        else:
            states[key] = 'pending'
    # Preserve the parent's sorted union-of-row-fields CSV schema.
    if rows:
        write_csv(HERE/'results.csv', rows)
    else:
        fields = ['arch', 'capture', 'layer', 'sample', 'arm', 'T_s', 'E_dyn_nJ',
                  'E_leak_nJ', 'EDP_nJ_s', 'incomplete', 'energy_table_sha256']
        write_csv(HERE/'results.csv', [], fields)
    totals = whole_model(selection, rows, states)
    write_csv(HERE/'whole_model.csv', totals)
    selected = scoped_selection(selection)
    keys = {identity(c) for c in selected['feasible']}
    demo.save(HERE/'coverage.json', {'case_states': {k: v for k, v in states.items() if k in keys},
                                   'excluded_case_states': {k: v for k, v in states.items() if k not in keys},
                                   'scope': scope_summary(selection), 'infeasible': selected['infeasible'],
                                   'result_rows': len(rows), 'whole_model_groups': len(totals)})
    return states


def whole_model(selection, rows, states):
    selection = scoped_selection(selection)
    rows = [r for r in rows if kept(r['layer'])]
    by = {(r['arch'], r['capture'], r['layer'], r['arm']): r for r in rows}
    if len(by) != len(rows):
        raise ValueError('duplicate result row')
    totals = []
    for capture in selection['captures']:
        for arch in demo.ARCHES:
            cases = [c for c in selection['feasible'] if c['arch'] == arch and c['trace_relative_dir'] == capture]
            infeasible = [c for c in selection['infeasible'] if c['arch'] == arch and c['trace_relative_dir'] == capture]
            for arm in ARMS:
                group = [by[(arch, capture, c['layer'], arm)] for c in cases
                         if (arch, capture, c['layer'], arm) in by]
                expected = len(cases)+len(infeasible)
                complete = len(group) == expected
                incomplete = any(str(r['incomplete']).lower() in ('true', '1') for r in group)
                energy = sum(float(r['E_dyn_nJ'])+float(r['E_leak_nJ']) for r in group)
                latency = sum(float(r['T_s']) for r in group)
                layer_edp = sum(float(r['EDP_nJ_s']) for r in group)
                totals.append({'benchmark': capture, 'arch': arch, 'arm': arm, 'sample': 0,
                    'n': 1 if group else 0, 'expected_layers': expected, 'feasible_layers': len(cases),
                    'completed_layers': len(group), 'infeasible_layers': len(infeasible),
                    'oom_layers': sum(states.get(identity(c)) == 'skipped_oom' for c in cases),
                    'failed_layers': sum(states.get(identity(c)) == 'failed' for c in cases),
                    'coverage': f'{len(group)}/{expected}', 'coverage_complete': complete,
                    'energy_incomplete': incomplete, 'comparable_complete': complete and not incomplete,
                    'status': ('complete_lower_bound' if incomplete else 'complete') if complete else 'missing_layers',
                    'sum_energy_nJ': energy if complete else None,
                    'sum_latency_s': latency if complete else None,
                    'model_EDP_nJ_s': energy*latency if complete else None,
                    'sum_layer_EDP_nJ_s': layer_edp if complete else None,
                    'partial_sum_energy_nJ': energy if group else None,
                    'partial_sum_latency_s': latency if group else None,
                    'partial_sum_layer_EDP_nJ_s': layer_edp if group else None,
                    'energy_table_sha256': group[0]['energy_table_sha256'] if group else None})
    return totals
