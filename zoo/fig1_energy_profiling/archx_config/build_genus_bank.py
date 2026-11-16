"""Convert copied Genus reports to local csv_cmos rows; never write the backend."""
from collections import OrderedDict
import csv
import hashlib
import json
import math
from pathlib import Path
import re

from archx.interface.csv_cmos.csv_cmos import query

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
BANK = HERE/'asap7_genus'
FREQUENCY_MHZ = 500
DESIGNS = {
    'adder': ('snn_adder16', {'width': 16}),
    'register': ('snn_register16', {'width': 16}),
    'fifo': ('snn_fifo32x8', {'width': 32, 'depth': 8}),
    **{name: ('snn_'+name, {}) for name in ('and_gate', 'and_gate_5', 'or_gate', 'xor_gate', 'not_gate', 'mux2')},
}
CAVEAT = ('ASAP7 Genus synthesis only, no post-route parasitics; project-default mixed library declarations '
          '(AO/INVBUF/OA/SEQ 0.77V/0C, SIMPLE 0.70V/25C); reports name PVT_0P77V_0C; '
          'unconstrained I/O, no end-to-end 500MHz timing claim; default activity without per-operation VCD.')
METRICS = {'dynamic_energy': 'dynamic_energy_nJ', 'leakage_power': 'leakage_power_mW', 'area': 'area_mm2'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+'\n')


def extract(design):
    power_path = BANK/'raw'/design/(design+'_power.rpt')
    area_path = BANK/'raw'/design/(design+'_area.rpt')
    power = power_path.read_text(); area = area_path.read_text()
    if 'Power Unit: W' not in power or 'Operating conditions:   PVT_0P77V_0C' not in area:
        raise ValueError('unrecognized report units/corner: '+design)
    subtotal, = re.findall(r'^\s*Subtotal\s+([^\n]+)', power, re.MULTILINE)
    leakage, internal, switching, total = map(float, subtotal.split()[:4])
    if not math.isclose(leakage+internal+switching, total, rel_tol=1e-4):
        raise ValueError('report total does not reconcile: '+design)
    match, = re.findall(r'^'+re.escape(design)+r'\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$', area, re.MULTILINE)
    cells, cell_area, net_area, _ = match
    return {'cells': int(cells), 'cell_area_um2': float(cell_area), 'estimated_net_area_um2': float(net_area),
            'dynamic_mW': (internal+switching)*1000, 'leakage_mW': leakage*1000,
            'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in (power_path, area_path)}}


def primitive(variant):
    if m := re.fullmatch(r'(adder|register)(\d+)', variant):
        family = m[1]; dimensions = {'width': int(m[2])}
    elif m := re.fullmatch(r'fifo(\d+)x(\d+)', variant):
        family = 'fifo'; dimensions = {'width': int(m[1]), 'depth': int(m[2])}
    else:
        family = variant; dimensions = {}
    path = BANK/'syn_csv'/f'{family}.csv'
    # csv_cmos joins the class with its CSV directory; an absolute class path
    # resolves this explicit local asset without editing the installed interface.
    request = OrderedDict({'class': str(path.with_suffix('')), 'technology': 7,
                           'frequency': FREQUENCY_MHZ, **dimensions})
    result = query(variant, 'csv_cmos', request)
    return {'source_csv': str(path.relative_to(ROOT)), 'source_csv_sha256': sha(path),
            'dimensions': dimensions, 'interpolation': 'linear through origin, independently in width and depth',
            **{field: result[name]['value'] for name, field in METRICS.items()}}


def main():
    directory = BANK/'syn_csv'; directory.mkdir(exist_ok=True)
    measured = {}
    for family, (design, dimensions) in DESIGNS.items():
        row = extract(design); measured[family] = {'design': design, **row, 'dimensions': dimensions}
        values = {'technology': 7, 'frequency': FREQUENCY_MHZ,
                  'dynamic_uw': row['dynamic_mW'], 'leakage_uw': row['leakage_mW'],
                  'area_mm2': row['cell_area_um2']*1e-6, **dimensions,
                  'num_instances': 1, 'interpolation': 'linear'}
        with (directory/f'{family}.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values)); writer.writeheader(); writer.writerow(values)
    audit_path = REPO/'zoo/archx/zoo/snn_edp/characterization/STRUCTURAL_AUDIT.json'
    all_vectors = json.loads(audit_path.read_text())['quantified_composition']['operations']
    vectors = {k:v for k,v in all_vectors.items() if k.split('.')[0] in ('ptb', 'loas', 'gustavsnn')}
    basics = {v: primitive(v) for v in sorted({p for r in vectors.values() for p in r['primitive_counts']})}
    prices = {}
    for key, vector in vectors.items():
        metrics = {m: math.fsum(n*basics[p][m] for p,n in vector['primitive_counts'].items()) for m in METRICS.values()}
        metrics['dynamic_energy_nJ'] *= vector['dynamic_event_cycles']
        prices[key] = {**metrics, 'assumption': CAVEAT+' Additive primitive composition; width/depth interpolation is an estimate, not whole-module characterization.',
                       'primitive_counts': vector['primitive_counts'], 'dynamic_event_cycles': vector['dynamic_event_cycles']}
    save(BANK/'logic_prices.json', {'operations': prices, 'primitives': basics, 'caveat': CAVEAT})
    import archx
    manifest = {'status': 'LOGIC_PRICE_BASIS_ONLY; not a complete geometry-specific energy table',
        'backend_file': str(Path(archx.__file__).resolve()), 'frequency_MHz': FREQUENCY_MHZ,
        'caveat': CAVEAT, 'measured_designs': measured, 'operations': len(prices),
        'structural_audit_sha256': sha(audit_path), 'builder_sha256': sha(Path(__file__)),
        'logic_prices_sha256': sha(BANK/'logic_prices.json'),
        'csv_sha256': {p.name: sha(p) for p in sorted(directory.glob('*.csv'))},
        'library_provenance_sha256': sha(BANK/'library_provenance.json'),
        'units': 'Genus W multiplied by1000 to mW. Legacy CSV *_uw headers carry mW as required by csv_cmos. nJ/event=mW/500. Cell um2 divided by1e6 to mm2; net-area estimate excluded.',
        'and_gate_5_semantics': 'Five parallel two-input AND gates (5-bit bitwise AND); not a five-input reduction. No Figure1 composition consumes it.',
        'shared_sources_modified': False}
    save(BANK/'bank_manifest.json', manifest)
    print(json.dumps({'designs': len(measured), 'logic_operations': len(prices),
                      'logic_prices_sha256': manifest['logic_prices_sha256'], 'archx_file': manifest['backend_file']}))


if __name__ == '__main__':
    main()
