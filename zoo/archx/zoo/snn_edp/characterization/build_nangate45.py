"""Assemble an explicitly approximate 45nm price basis without changing counted hardware."""
import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
MODEL = HERE.parent
VENDOR = MODEL.parents[1]
INTERFACE = VENDOR/'src/archx/interface/csv_cmos_asplos_2026_ae'
CAVEAT = 'NanGate45-characterized prices applied to a 7nm/500MHz performance model; interim until ASAP7 synthesis'
METRICS = ('dynamic_energy_nJ', 'leakage_power_mW', 'area_mm2')


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def asset(csv_name, design):
    path = INTERFACE/'include/csv'/(csv_name+'.csv')
    with path.open() as stream:
        rows = [r for r in csv.DictReader(stream) if r['technology']=='45']
    if len(rows)!=1:
        raise ValueError('expected exactly one 45nm source row: '+str(path))
    row = rows[0]
    report = INTERFACE/'syn_pnr_rpt/NanGate45'/design/(design+'_DETAILS.rpt')
    with report.open() as stream:
        report_rows = [{k.strip():v.strip() for k,v in r.items()} for r in csv.DictReader(stream)]
    post, = [r for r in report_rows if r['Physical Design Stage']=='postRouteOpt']
    # CSV headers are misleading; the raw report and archx interface both specify mW.
    for field, raw, scale in [('dynamic_uw','Dynamic Power (mW)',1),
                              ('leakage_uw','Leakage Power (mW)',1),
                              ('area_mm2','Report Area (um^2)',1e-6)]:
        if not math.isclose(float(row[field]),float(post[raw])*scale,rel_tol=1e-12):
            raise ValueError('CSV/report mismatch: '+str(path)+' '+field)
    f=float(row['frequency'])
    if f<=0: raise ValueError('invalid source frequency')
    return {'source_csv':str(path.relative_to(VENDOR)), 'source_csv_sha256':digest(path),
            'source_report':str(report.relative_to(VENDOR)), 'source_report_sha256':digest(report),
            'source_row':row, 'source_technology_nm':45, 'source_frequency_MHz':f,
            'power_units':'mW, verified against postRouteOpt report despite *_uw CSV header',
            'dynamic_energy_nJ':float(row['dynamic_uw'])/f,
            'leakage_power_mW':float(row['leakage_uw']), 'area_mm2':float(row['area_mm2'])}


def primitive(variant):
    if match:=re.fullmatch(r'adder(\d+)',variant):
        w=int(match[1]); source=asset('adder','adder');scale=w/32
        reason=f'{w}-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference.'
    elif match:=re.fullmatch(r'register(\d+)',variant):
        w=int(match[1]);source=asset('register','REGISTER');scale=w
        reason=f'{w} independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount.'
    elif match:=re.fullmatch(r'fifo(\d+)x(\d+)',variant):
        w,d=map(int,match.groups());source=asset('fifo','FIFO');scale=w*d/(16*8)
        reason=f'FIFO {w}x{d} uses characterized FIFO16x8 scaled by stored bits ({w}*{d})/(16*8); pointer/control scaling is an explicit approximation.'
    else:
        name,design,scale,reason={
            'and_gate':('and_bitwise','AND_BITWISE',1,'One characterized one-bit AND.'),
            'and_gate_5':('and_bitwise','AND_BITWISE',4,'Five-input AND is a tree of four characterized two-input AND gates.'),
            'or_gate':('or_bitwise','OR_BITWISE',1,'One characterized one-bit OR.'),
            'xor_gate':('xor_bitwise','XOR_BITWISE',1,'One characterized one-bit XOR.'),
            'not_gate':('xor_bitwise','XOR_BITWISE',1,'No inverter CSV: a one-bit XOR with one input tied high is the logical neighbor; charge the complete characterized XOR, without constant-folding discount.'),
            'mux2':('multiplexer','MULTIPLEXER',1/16,'One-bit 2:1 mux uses 1/16 of the characterized 16-bit 2:1 MULTIPLEXER; shared-select/control overhead scales with width.')
        }[variant]
        source=asset(name,design)
    return {**source,'variant':variant,'scale':scale,'neighbor_reason':reason,
            'scaled_metrics':{field:source[field]*scale for field in METRICS}}


def build(memory_path):
    baseline_path=MODEL/'energy_table.json'
    table=load(baseline_path); baseline=copy.deepcopy(table)
    audit_path=HERE/'STRUCTURAL_AUDIT.json'
    vectors=load(audit_path)['quantified_composition']['operations']
    excluded={k for k,r in table.items() if r.get('pricing_status')=='excluded by decision (prefetch control)'}
    assert len(excluded)==9 and len(vectors)==48
    basics={v:primitive(v) for v in sorted({v for r in vectors.values() for v in r['primitive_counts']})}
    memory=load(memory_path)['operations']
    ddr={'shared.ddr4.read','shared.ddr4_io.byte'}
    assert set(vectors).isdisjoint(memory)
    assert set(table)==set(vectors)|set(memory)|excluded|ddr
    substitutions={}
    stale=('source_csv','source_file','source','device','voltage_V','voltage_model','process','synthesis',
           'reference_technology_nm','area_scale','dynamic_scale','leakage_scale','scaling_citation',
           'unvalidated_dynamic_energy_nJ','capacitance_F_per_um')
    for key,row in table.items():
        if key in excluded:
            assert all(row[m]==0 for m in METRICS)
            substitutions[key]={'method':'excluded by decision (prefetch control)','baseline_row_preserved':True}
            continue
        if key in ddr:
            substitutions[key]={'method':'pinned cacti7 DDR4 exception','baseline_row_preserved':True,
                'reason':'Off-chip commodity DDR4/PHY remains the pinned cacti7 model; no on-chip node transfer.'}
            continue
        for field in stale:row.pop(field,None)
        if key in vectors:
            vector=vectors[key];cycles=vector['dynamic_event_cycles']
            metrics={field:math.fsum(n*basics[v]['scaled_metrics'][field]
                        for v,n in vector['primitive_counts'].items()) for field in METRICS}
            metrics['dynamic_energy_nJ']*=cycles
            basis={'method':'NanGate45 primitive composition','primitive_counts':vector['primitive_counts'],
                   'dynamic_event_cycles':cycles,'structural_terms':vector['terms'],
                   'boundary':vector.get('boundary'),
                   'sources':{v:basics[v] for v in vector['primitive_counts']},
                   'formula':'dynamic = cycles * sum(count * scale * source_dynamic_mW/source_frequency_MHz); leakage/area = sum(count * scale * source_metric)'}
            assumption=(CAVEAT+'. Existing structural vector composed from 45nm primitive neighbors; '
                        'no process scaling. Charge all declared leaf activity, including flop arrays; no whole-module timing, clock-gating, routing or switching correlation is characterized. '
                        +'; '.join(f'{v}: {n} x ({basics[v]["neighbor_reason"]})' for v,n in vector['primitive_counts'].items()))
        else:
            item=memory[key];metrics={field:item[field] for field in METRICS}
            basis=item['provenance'];assumption=CAVEAT+'. '+item['assumption']
        for field,value in metrics.items():
            if not math.isfinite(value) or value<0:raise ValueError(key+' invalid '+field)
        row.update(metrics,source='nangate45_interim',placeholder=False,pricing_status='NG45_INTERIM',
                   assumption=assumption,characterization_technology_nm=45,price_basis=basis)
        substitutions[key]=basis
    # Top-level technology/query remain the counted hardware contract, not the price basis.
    invariant=('technology_nm','physical_instances','physical_module','scope','applies_to','count_expression','query')
    for key in table:
        assert all(table[key].get(f)==baseline[key].get(f) for f in invariant),key
        assert all(table[key][f] is not None for f in METRICS),key
        assert '.'.join((key.split('.')[0],table[key]['module'],table[key]['operation']))==key
    out=HERE/'energy_table_nangate45.json';save(out,table)
    sub=HERE/'nangate45_substitutions.json';save(sub,{'caveat':CAVEAT,'operation_count':98,
        'hardware_contract':'technology_nm and query describe the unchanged 7nm hardware checkpoint; characterization_technology_nm and price_basis describe the independent 45nm price source. DDR4 remains pinned at its existing technology.',
        'sources':basics,'operations':substitutions})
    manifest={'caveat':CAVEAT,'table_sha256':digest(out),'baseline_sha256':digest(baseline_path),
              'substitution_manifest':sub.name,'substitution_manifest_sha256':digest(sub),
              'structural_audit_sha256':digest(audit_path),'memory_manifest':str(memory_path.relative_to(HERE)),
              'memory_manifest_sha256':digest(memory_path),'builder_sha256':digest(Path(__file__)),
              'operations':98,'logic':48,'memory_and_wire':len(memory),'excluded':9,'ddr4_unchanged':2,
              'performance_frequency_MHz':500,'source_frequency_MHz':sorted({r['source_frequency_MHz'] for r in basics.values()}),
              'logic_technology_nm':45,'default_table_modified':False,'tnn_sources':[],
              'assumptions':['CSV *_uw columns contain mW in these assets, verified against raw postRouteOpt mW fields.',
                  'Per-event energies use each row source frequency, not the 500MHz performance clock.',
                  'Width/storage-bit scaling and additive composition are estimates, not whole-module characterization.',
                  'One-bit COMPARATOR is not used as a numeric comparison: arithmetic/glue vectors preserve the specified compare circuit.',
                  'No fabricated frequency/technology transfer. Default and dummy tables remain selectable and unchanged.']}
    save(HERE/'energy_table_nangate45.manifest.json',manifest)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory',type=Path,default=HERE/'nangate45_memory/memory_prices.json')
    build(parser.parse_args().memory)
