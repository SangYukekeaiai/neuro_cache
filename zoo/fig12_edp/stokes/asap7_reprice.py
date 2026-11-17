"""Reprice the full500 durable rows with the measured ASAP7 1 GHz energy table.

Stage-B-equivalent arithmetic on the retained per-operation counts: each
results_ng45.csv row carries the complete breakdown {op: count} for its arm,
so dynamic energy is sum(count * unit) and standing leakage is the deduplicated
physical inventory of the arm's operations (model.py physical()/instances()
semantics, replicated here verbatim). Every row is first re-derived with the
sample's own pinned NG45 table and must reproduce the recorded E_dyn_nJ,
E_leak_nJ and area_mm2 to <1e-9 relative before the new table is applied;
whole-model aggregation is validated the same way against whole_model_ng45.csv.
T_s and cycles are price-independent and copied through.

Run: conda run -n base python asap7_reprice.py
"""
import ast
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROWS = Path('/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/fig12_edp/stokes/full500_rows_fetch_20261116/rows')
NEW_TABLE = HERE.parents[1] / 'archx/zoo/snn_edp/characterization/energy_table_asap7_1ghz.json'
OUT = HERE / 'results_asap7_20261116'
ARCHES = ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity')
REL_TOL = 1e-9
PRICING_STATUS = 'ASAP7_SYN_1GHZ'


def physical(key, row):
    ns, module, _ = key.split('.')
    return ns + '.' + (row.get('physical_module') or module)


def instances(key, row):
    ns, module, _ = key.split('.')
    scope = row.get('scope', 'node' if ns in ARCHES else 'system')
    n = row.get('physical_instances', 1)
    if ns == 'spinalflow' and module in ('adder32', 'cmp32', 'reg32') and scope == 'node':
        n = 4
    return n * (16 if scope == 'node' else 1)


def arm_energy(breakdown, table):
    dynamic = math.fsum(spec['count'] * table[key]['dynamic_energy_nJ']
                        for key, spec in breakdown.items())
    leak_mw = area = 0.0
    seen = set()
    for key in breakdown:
        row = table[key]
        name = physical(key, row)
        if name in seen:
            continue
        seen.add(name)
        leak_mw += row['leakage_power_mW'] * instances(key, row)
        area += row['area_mm2'] * instances(key, row)
    return dynamic, leak_mw, area


def close(a, b):
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-12)


def main():
    new_table = json.loads(NEW_TABLE.read_text())
    new_sha = hashlib.sha256(NEW_TABLE.read_bytes()).hexdigest()
    caveat = next(iter(r.get('assumption') for r in new_table.values()
                       if r.get('pricing_status') == PRICING_STATUS))
    samples = sorted(p for p in ROWS.iterdir() if p.name.startswith('sample_'))
    if not samples:
        sys.exit('no sample dirs under ' + str(ROWS))
    OUT.mkdir(exist_ok=True)
    report = {'samples': len(samples), 'rows': 0, 'whole_rows': 0,
              'max_rel_err': {'E_dyn': 0.0, 'E_leak': 0.0, 'area': 0.0,
                              'whole_energy': 0.0, 'whole_edp': 0.0},
              'new_table_sha256': new_sha, 'skipped_rows': 0}

    def track(slot, old, check):
        err = abs(check - old) / max(abs(old), 1e-30)
        report['max_rel_err'][slot] = max(report['max_rel_err'][slot], err)
        if not close(old, check):
            raise ValueError(f'{slot} validation failed: recorded {old} vs derived {check}')

    for sample_dir in samples:
        old_tables = {}
        rows_out = []
        groups = {}
        groups_old_energy = {}
        with (sample_dir / 'results_ng45.csv').open(newline='') as stream:
            for row in csv.DictReader(stream):
                sha = row['energy_table_sha256']
                if sha not in old_tables:
                    path = sample_dir / f'nangate45_table_{sha}.json'
                    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                        raise ValueError('table snapshot hash mismatch: ' + str(path))
                    old_tables[sha] = json.loads(path.read_text())
                old_table = old_tables[sha]
                breakdown = ast.literal_eval(row['breakdown'])
                unknown = [k for k in breakdown if k not in new_table]
                if unknown:
                    raise ValueError('ops missing from new table: ' + ', '.join(unknown))
                t_s = float(row['T_s'])
                dyn_old, leak_mw_old, area_old = arm_energy(breakdown, old_table)
                track('E_dyn', float(row['E_dyn_nJ']), dyn_old)
                track('E_leak', float(row['E_leak_nJ']), leak_mw_old * t_s * 1e6)
                track('area', float(row['area_mm2']), area_old)
                dyn_new, leak_mw_new, area_new = arm_energy(breakdown, new_table)
                e_leak_new = leak_mw_new * t_s * 1e6
                incomplete = sorted(
                    f'{k}:{f}' for k in breakdown for f in ('dynamic_energy_nJ', 'leakage_power_mW', 'area_mm2')
                    if new_table[k].get(f) is None)
                out = {'capture': row['capture'], 'arch': row['arch'], 'arm': row['arm'],
                       'layer': row['layer'], 'sample': row['sample'],
                       'total_cycles': row['total_cycles'], 'frequency_MHz': row['frequency_MHz'],
                       'T_s': t_s, 'E_dyn_nJ': dyn_new, 'E_leak_nJ': e_leak_new,
                       'EDP_nJ_s': (dyn_new + e_leak_new) * t_s, 'area_mm2': area_new,
                       'incomplete': bool(incomplete), 'incomplete_reasons': ';'.join(incomplete),
                       'pricing_status': PRICING_STATUS, 'energy_table_sha256': new_sha,
                       'trace_sha256': row['trace_sha256']}
                rows_out.append(out)
                group_key = (row['capture'], row['arch'], row['arm'])
                groups.setdefault(group_key, []).append(out)
                groups_old_energy.setdefault(group_key, []).append(
                    float(row['E_dyn_nJ']) + float(row['E_leak_nJ']))
                report['rows'] += 1

        whole_old = {}
        with (sample_dir / 'whole_model_ng45.csv').open(newline='') as stream:
            for row in csv.DictReader(stream):
                whole_old[(row['benchmark'], row['arch'], row['arm'])] = row
        whole_out = []
        for key, members in sorted(groups.items()):
            old = whole_old[key]
            sum_e = math.fsum(m['E_dyn_nJ'] + m['E_leak_nJ'] for m in members)
            sum_t = math.fsum(m['T_s'] for m in members)
            # price-independent checks against the old collector output; an
            # incomplete benchmark records its sums in the partial_* columns.
            old_e = old['sum_energy_nJ'] or old['partial_sum_energy_nJ']
            old_t = old['sum_latency_s'] or old['partial_sum_latency_s']
            if not close(float(old_t), sum_t):
                raise ValueError(f'latency aggregation mismatch for {key}')
            if int(old['completed_layers']) != len(members):
                raise ValueError(f'layer count mismatch for {key}')
            with_old = math.fsum(groups_old_energy[key])
            track('whole_energy', float(old_e), with_old)
            if old['model_EDP_nJ_s']:
                track('whole_edp', float(old['model_EDP_nJ_s']), with_old * float(old_t))
            whole_out.append({'benchmark': key[0], 'arch': key[1], 'arm': key[2],
                              'sample': members[0]['sample'],
                              'completed_layers': len(members),
                              'expected_layers': old['expected_layers'],
                              'coverage_complete': old['coverage_complete'],
                              'sum_energy_nJ': sum_e, 'sum_latency_s': sum_t,
                              'model_EDP_nJ_s': sum_e * sum_t,
                              'incomplete': any(m['incomplete'] for m in members),
                              'pricing_status': PRICING_STATUS,
                              'energy_table_sha256': new_sha})
            report['whole_rows'] += 1

        out_dir = OUT / sample_dir.name
        out_dir.mkdir(exist_ok=True)
        for name, data in (('results_asap7.csv', rows_out), ('whole_model_asap7.csv', whole_out)):
            with (out_dir / name).open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
        print(f'{sample_dir.name}: {len(rows_out)} rows, {len(whole_out)} whole-model rows')

    report['caveat'] = caveat
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['max_rel_err'], indent=2))
    print(f"total: {report['rows']} rows, {report['whole_rows']} whole-model rows, "
          f"{report['samples']} samples -> {OUT}")


if __name__ == '__main__':
    main()
