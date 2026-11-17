"""Assemble the measured ASAP7 1 GHz logic price basis without changing counted hardware.

Fills the 48 structural logic rows of the default energy table from the
Genus synthesis-only reports in /work/hdd/bebv/yyu9/asap7_syn_1ghz_20261116
(all 24 measured basics present at their exact widths: no neighbor or width
scaling). The 48 rows include shared.router.hop, which is an audit vector
and is therefore repriced from the ASAP7 basics (its baseline value was the
scaled archx router CSV). Memory (cacti_fn 7 nm), DDR4/IO (pinned cacti7)
and the shared.link.hop wire row are copied from the baseline table
untouched; the nine prefetch-control exclusions stay zero by decision.
"""
import argparse
import copy
import hashlib
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = HERE.parent
DEFAULT_DROP = Path('/work/hdd/bebv/yyu9/asap7_syn_1ghz_20261116')
CAVEAT = ('ASAP7 Genus synthesis-only at 1 GHz (CLK_PERIOD_NS=1.0), mixed shipped '
          'libraries (AO/INVBUF/OA/SEQ 0.77V/0C, SIMPLE 0.70V/25C), Joules power at '
          'the default 50% switching activity without VCD, no place-and-route '
          'parasitics; prices applied to the 7nm/500MHz performance model')
METRICS = ('dynamic_energy_nJ', 'leakage_power_mW', 'area_mm2')
FREQUENCY_MHZ = 1000.0


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def genus_metrics(drop, module):
    """Total cell area (mm^2), leakage and internal+switching power (mW) of one top."""
    rpt = drop / module / 'scripts/cadence/syn_rpt'
    area_path = rpt / 'final_area.rpt'
    area_um2 = None
    for line in area_path.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == module and len(fields) >= 4:
            area_um2 = float(fields[-1])
            break
    if area_um2 is None:
        raise ValueError(f'no module area row in {area_path}')
    power_path = rpt / f'{module}_power.rpt'
    leak_w = dynamic_w = None
    for line in power_path.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == 'Subtotal' and len(fields) >= 5:
            leak_w = float(fields[1])
            dynamic_w = float(fields[2]) + float(fields[3])  # internal + switching
            break
    if leak_w is None:
        raise ValueError(f'no Subtotal power row in {power_path}')
    log = drop / module / 'scripts/cadence/log/genus.log'
    if 'CLK_PERIOD_NS found in environment: 1.0' not in log.read_text():
        raise ValueError(f'clock evidence missing in {log}')
    return {
        'source_report_area': str(area_path), 'source_report_area_sha256': digest(area_path),
        'source_report_power': str(power_path), 'source_report_power_sha256': digest(power_path),
        'source_technology_nm': 7, 'source_frequency_MHz': FREQUENCY_MHZ,
        'synthesis': 'Genus 21.18 synthesis-only (no P&R)',
        'activity': 'default 50% switching, no VCD',
        'area_mm2': area_um2 * 1e-6,
        'leakage_power_mW': leak_w * 1e3,
        'dynamic_power_mW': dynamic_w * 1e3,
        'dynamic_energy_nJ': dynamic_w * 1e3 / FREQUENCY_MHZ,  # mW / MHz = nJ per cycle
    }


def build(drop):
    baseline_path = MODEL / 'energy_table.json'
    table = load(baseline_path)
    baseline = copy.deepcopy(table)
    audit_path = HERE / 'STRUCTURAL_AUDIT.json'
    vectors = load(audit_path)['quantified_composition']['operations']
    assert len(vectors) == 48
    variants = sorted({v for r in vectors.values() for v in r['primitive_counts']})
    basics = {}
    for variant in variants:
        source = genus_metrics(drop, 'snn_' + variant)
        basics[variant] = {**source, 'variant': variant, 'scale': 1,
                           'measured_directly': True,
                           'scaled_metrics': {f: source[f] for f in METRICS}}
    substitutions = {}
    stale = ('placeholder', 'rtl_source', 'target_width_bits', 'num_units', 'synthesis', 'process')
    for key, vector in vectors.items():
        row = table[key]
        previous_status = row.get('pricing_status') or row.get('source')
        cycles = vector['dynamic_event_cycles']
        metrics = {field: math.fsum(n * basics[v]['scaled_metrics'][field]
                                    for v, n in vector['primitive_counts'].items())
                   for field in METRICS}
        metrics['dynamic_energy_nJ'] *= cycles
        for field, value in metrics.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(key + ' invalid ' + field)
        basis = {'method': 'ASAP7 1 GHz measured primitive composition',
                 'primitive_counts': vector['primitive_counts'],
                 'dynamic_event_cycles': cycles, 'structural_terms': vector['terms'],
                 'boundary': vector.get('boundary'),
                 'previous_pricing_status': previous_status,
                 'formula': 'dynamic = cycles * sum(count * source_dynamic_mW/source_frequency_MHz); '
                            'leakage/area = sum(count * source_metric)'}
        for field in stale:
            row.pop(field, None)
        row.update(metrics, source='asap7_syn_1ghz_20261116', placeholder=False,
                   pricing_status='ASAP7_SYN_1GHZ',
                   assumption=CAVEAT + '. Structural vector composed from directly measured '
                              'ASAP7 basics at their exact widths; no width or technology scaling. '
                              'Charge all declared leaf activity; no whole-module timing, '
                              'clock-gating, routing or switching correlation is characterized.',
                   characterization_technology_nm=7, price_basis=basis)
        substitutions[key] = basis
    # Everything outside the 48 logic vectors is copied from the baseline unchanged.
    untouched = {key: row for key, row in table.items() if key not in vectors}
    for key, row in untouched.items():
        if row != baseline[key]:
            raise ValueError('non-logic row drifted: ' + key)
    invariant = ('technology_nm', 'physical_instances', 'physical_module', 'scope',
                 'applies_to', 'count_expression', 'query')
    for key in table:
        assert all(table[key].get(f) == baseline[key].get(f) for f in invariant), key
    pending = [k for k, r in table.items() if r.get('placeholder')]
    assert not pending, pending
    out = HERE / 'energy_table_asap7_1ghz.json'
    save(out, table)
    sub = HERE / 'asap7_1ghz_substitutions.json'
    save(sub, {'caveat': CAVEAT, 'operation_count': len(table),
               'hardware_contract': 'shared.router.hop is one of the 48 audit vectors and is repriced '
                                    'from the ASAP7 basics; memory, DDR4 and the shared.link.hop wire '
                                    'row are baseline values, untouched. '
                                    'technology_nm and query describe the unchanged 7nm hardware '
                                    'checkpoint; the price basis is measured ASAP7 synthesis at 1 GHz.',
               'sources': basics, 'operations': substitutions})
    manifest = {'caveat': CAVEAT, 'table_sha256': digest(out),
                'baseline_sha256': digest(baseline_path),
                'substitution_manifest': sub.name, 'substitution_manifest_sha256': digest(sub),
                'structural_audit_sha256': digest(audit_path),
                'builder_sha256': digest(Path(__file__)),
                'drop': str(drop), 'drop_readme_sha256': digest(drop / 'README.md'),
                'operations': len(table), 'logic': len(vectors),
                'untouched_rows': len(untouched),
                'performance_frequency_MHz': 500, 'source_frequency_MHz': [FREQUENCY_MHZ],
                'logic_technology_nm': 7, 'default_table_modified': False,
                'assumptions': [
                    'Power is Genus Joules at default 50% switching activity without VCD; '
                    'per-event energy = (internal+switching) power / 1000 MHz, per dynamic-event cycle.',
                    'Synthesis-only: no place-and-route wire parasitics (Innovus OOM on the vlsi host).',
                    'All 24 basics measured at their exact widths; additive structural composition '
                    'remains an estimate, not whole-module characterization.',
                    'Per-event energies use the 1 GHz source clock; the pipeline time base remains 500 MHz.']}
    save(HERE / 'energy_table_asap7_1ghz.manifest.json', manifest)
    print(json.dumps({k: manifest[k] for k in ('table_sha256', 'operations', 'logic', 'untouched_rows')}, indent=2))
    print('basics harvested:', len(basics))
    for v in ('adder32', 'register64', 'fifo32x8', 'and_gate', 'mux2'):
        b = basics[v]
        print(f"  {v:10s} area {b['area_mm2']*1e6:9.3f} um2  leak {b['leakage_power_mW']*1e3:9.4f} uW  "
              f"dyn {b['dynamic_energy_nJ']*1e6:9.4f} fJ/cycle")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drop', type=Path, default=DEFAULT_DROP)
    build(parser.parse_args().drop)
