"""Check the decoded-timestep recount against retained native and priced artifacts."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/self_checks/temporal_order'
OLD = ROOT/'outputs/temporal_before'
SEGMENTS = ('compute', 'on_chip_sram', 'off_chip_weights', 'off_chip_other')


def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def raw_gate():
    previous = load(OLD/'count_validation.json')
    inventory = dict(previous['inventory'])
    unchanged = 0
    for name, digest in inventory.items():
        if '/gustavsnn/' not in name:
            assert sha(ROOT/name) == digest, name
            unchanged += 1
    sums = defaultdict(int)
    changes = []
    paths = sorted((ROOT/'outputs/counts/gustavsnn').glob('*/sample_*/*/receipt.json'))
    assert len(paths) == 480, len(paths)
    for receipt in paths:
        case = receipt.parent
        size, sample, layer = case.relative_to(ROOT/'outputs/counts/gustavsnn').parts
        old = OLD/'counts/gustavsnn'/size/sample/layer
        meta = load(receipt)
        assert meta['status'] == 'complete' and meta['price_free']
        assert meta['zero_gb'] and meta['native_demand_oracle_equal']
        for name, digest in meta['artifacts'].items():
            assert sha(case/name) == digest, str(case/name)
            inventory[str((case/name).relative_to(ROOT))] = digest
        inventory[str(receipt.relative_to(ROOT))] = sha(receipt)
        manifest = load(ROOT/f'outputs/manifest/gustavsnn_{size}/manifest.json')
        row, = [r for r in manifest['layers'] if r['layer'] == layer]
        assert meta['inputs']['schedule_sha256'] == row['schedule_sha256']
        assert meta['inputs']['manifest_sha256'] == sha(ROOT/f'outputs/manifest/gustavsnn_{size}/manifest.json')
        noc, before = load(case/'noc/result.json'), load(old/'noc/result.json')
        compulsory = row['compulsory_weight_bytes']
        for field in ('dram_payload_bytes','dram_bytes','l1_delivery_bytes'):
            assert noc[field] == before[field] == compulsory, (case, field)
        for field in ('gb_reads','gb_writes','weight_packet_hops','psum_boundary_bytes','vmem_boundary_bytes'):
            assert noc[field] == 0, (case, field)
        ideal = load(case/'ideal_counts.json')
        unique = ideal['needed_weight_words']
        assert ideal['oracle_equal'] and unique == ideal['needed_weight_bytes']
        assert unique == load(old/'ideal_counts.json')['needed_weight_words']
        for arch in ('loas','ptb'):
            assert unique == load(ROOT/f'outputs/counts/{arch}/{size}/{sample}/{layer}/ideal_counts.json')['needed_weight_words']
        sums[size] += unique
        changes.append({'size':size,'sample':sample,'layer':layer,
                        'cycles_before':before['total_cycles'],'cycles_after':noc['total_cycles'],
                        'unique_weight_words':unique,'compulsory_weight_bytes':compulsory,
                        'native_stream_words_before':load(old/'ideal_counts.json')['native_weight_words'],
                        'native_stream_words_after':ideal['native_weight_words']})
    assert len(sums)==4 and set(sums.values()) == {118852096}, dict(sums)
    with (OUT/'native_deltas.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(changes[0]));writer.writeheader();writer.writerows(changes)
    report={'gustav_cases':480,'other_arch_native_files_unchanged':unchanged,
            'unique_words_per_capacity':dict(sums),'all_baseline_weight_traffic_compulsory':True,
            'all_zero_gb_and_state_boundary':True,'all_native_oracle_equal':True,
            'realized_orders':{'gustavsnn':'COUT -> HO -> WO -> T, each visit one pixel/timestep; weights retained across HO/WO/T',
                               'loas':'HO -> WO -> COUT; T fully resident in the temporal-parallel tile',
                               'ptb':'HO -> WO -> COUT; T fully resident in the T-bit-vector batch'}}
    save(OUT/'native_verification.json',report)
    previous.update(inventory=inventory)
    save(ROOT/'outputs/count_validation.json',previous)
    print(json.dumps(report,indent=2))


def priced_gate():
    before_inventory=load(OLD/'stage_a_before_pricing.json')
    unchanged=0
    for name,digest in before_inventory.items():
        if '/gustavsnn/' not in name:
            assert sha(ROOT/name)==digest,name
            unchanged+=1
    per_case=[];groups=defaultdict(lambda:defaultdict(float))
    paths=sorted((ROOT/'outputs/priced/baseline/gustavsnn').glob('*/sample_*/*/result.json'))
    paths+=sorted((ROOT/'outputs/priced/ideal/gustavsnn').glob('*/sample_*/*/result.json'))
    assert len(paths)==600
    for path in paths:
        row=load(path);old=load(OLD/path.relative_to(ROOT/'outputs'))
        assert row['energy_table_sha256']==old['energy_table_sha256']
        assert row['inventory']==old['inventory']
        for key,term in row['breakdown'].items():
            assert term==old['breakdown'][key], (path,key)
        for segment in SEGMENTS:
            a,b=old['segments'][segment],row['segments'][segment]
            assert a['E_dyn_nJ']==b['E_dyn_nJ'],(path,segment)
            rec={'bar':row['bar'],'sample':row['sample'],'layer':row['layer'],'segment':segment,
                 'before_nJ':sum(a.values()),'after_nJ':sum(b.values()),
                 'dynamic_delta_nJ':b['E_dyn_nJ']-a['E_dyn_nJ'],
                 'leakage_delta_nJ':b['E_leak_nJ']-a['E_leak_nJ']}
            rec['delta_nJ']=rec['after_nJ']-rec['before_nJ'];per_case.append(rec)
            for field in ('before_nJ','after_nJ','dynamic_delta_nJ','leakage_delta_nJ','delta_nJ'):
                groups[(row['bar'],segment)][field]+=rec[field]/10
    summaries=[{'bar':bar,'segment':seg,**values} for (bar,seg),values in sorted(groups.items())]
    for filename,rows in (('segment_deltas_by_case.csv',per_case),('segment_deltas.csv',summaries)):
        with (OUT/filename).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    old_rows=list(csv.DictReader((OLD/'whole_model_samples.csv').open()))
    new_rows=list(csv.DictReader((ROOT/'outputs/whole_model_samples.csv').open()))
    old_map={(r['arch'],r['bar'],r['sample']):r for r in old_rows}
    for row in new_rows:
        if row['arch']!='gustavsnn':assert row==old_map[(row['arch'],row['bar'],row['sample'])]
    report={'gustav_priced_cases':600,'all_dynamic_terms_unchanged':True,
            'all_inventory_and_table_prices_unchanged':True,'energy_delta_source':'leakage duration only',
            'other_arch_count_files_unchanged':unchanged,'ptb_loas_whole_model_rows_unchanged':100,
            'mean_whole_model_segment_deltas_nJ':summaries}
    save(OUT/'priced_verification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('raw','priced'))
    args=parser.parse_args()
    raw_gate() if args.stage=='raw' else priced_gate()
