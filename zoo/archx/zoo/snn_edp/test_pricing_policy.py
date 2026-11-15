"""Intentional exclusions preserve activity and change only their own prices."""
import copy
import math
from pathlib import Path
from snn_edp import model, pricing, run

EXCLUDED = {
    'cache.next_access_logic.step', 'cache.distance_logic.step',
    'cache.next_access_state.rmw', 'cache.distance_metadata.read',
    'cache.next_line_l1.add', 'cache.next_line_l2.add',
    'cache.distance_metadata.write', 'cache.l1_tags.read', 'cache.l2_tags.read',
}
MARKER = 'excluded by decision (prefetch control)'
METRICS = ('dynamic_energy_nJ', 'leakage_power_mW', 'area_mm2')


def test_exact_exclusion_set_and_unmodified_array_fills():
    policy=model.load(model.HERE/'characterization/pricing_policy.json')
    assert set(policy['excluded_operations'])==EXCLUDED
    assert policy['marker']==MARKER
    hardware=model.load(model.HERE/'hardware.json')
    for name in ('energy_table.json','characterization/energy_table_dummy.json'):
        table=model.load(model.HERE/name)
        assert {k for k,r in table.items() if r.get('pricing_status')==MARKER}==EXCLUDED
        for key in EXCLUDED:
            row=table[key]
            assert all(row[x]==0 for x in METRICS)
            assert row['placeholder'] is False and not row.get('dummy')
            assert row['assumption']==MARKER and row['source']=='excluded_by_decision'
            assert row['count_expression']==hardware[key]['count_expression']
            technical=model.load(model.HERE/'provenance/prefetch_control_exclusion.json')['rows']['default'][key].get('assumption')
            if technical:assert row['geometry_assumption']==technical
        assert table['cache.l1.write']['count_expression']=='l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve'
        assert table['cache.l2.write']['count_expression']=='dram_accesses'
        assert table['cache.l1.write']['dynamic_energy_nJ']>0
        assert table['cache.l2.write']['dynamic_energy_nJ']>0
    work=model.load(model.HERE/'characterization/auto_syn_pnr_worklist.json')
    assert 'prefetcher' not in {r['component'] for r in work}
    assert sum(r['included_in_round'] for r in work)==18


def test_reprice_exclusions_without_case_inputs_or_counting(tmp_path,monkeypatch):
    counts=model.HERE/'runs/spinalflow/fixture_counts'
    hashes={str(p.relative_to(counts)):model.digest(p) for p in counts.rglob('*') if p.is_file()}
    current=model.load(model.HERE/'characterization/energy_table_dummy.json')
    old=copy.deepcopy(current)
    evidence=model.load(model.HERE/'provenance/prefetch_control_exclusion.json')
    for k in EXCLUDED:old[k]=evidence['rows']['dummy'][k]
    old_path=tmp_path/'old.json';model.save(old_path,old)
    original=Path.open
    def guarded(path,*args,**kwargs):
        if path.resolve().is_relative_to(model.HERE/'fixtures'):
            raise AssertionError('pricing read simulator inputs')
        return original(path,*args,**kwargs)
    def forbidden(*a,**k):raise AssertionError('pricing called counting/simulator')
    monkeypatch.setattr(Path,'open',guarded)
    monkeypatch.setattr(run,'count',forbidden)
    monkeypatch.setattr(model,'measurements',forbidden)
    monkeypatch.setattr(run.subprocess,'run',forbidden)
    before=pricing.price(counts,old_path,tmp_path/'old_price')
    after=pricing.price(counts,model.HERE/'characterization/energy_table_dummy.json',tmp_path/'new_price')
    changed=set()
    for oldrow,newrow in zip(before,after):
        energy=power=area=0;seen=set()
        assert oldrow['T_s']==newrow['T_s']
        for key,term in oldrow['breakdown'].items():
            newterm=newrow['breakdown'][key]
            assert term['count']==newterm['count']
            assert term['count_expression']==newterm['count_expression']
            if key not in EXCLUDED:
                assert term==newterm
                continue
            assert newterm['E_dyn_nJ']==0
            assert not any(r.startswith(key+':') for r in newrow['incomplete_reasons'])
            if term['E_dyn_nJ']>0:changed.add(key)
            energy+=term['E_dyn_nJ']
            owner=key.rsplit('.',1)[0]
            if owner not in seen:
                n=evidence['system_instances'][key]
                power+=old[key]['leakage_power_mW']*n
                area+=old[key]['area_mm2']*n
                seen.add(owner)
        assert math.isclose(newrow['E_dyn_nJ'],oldrow['E_dyn_nJ']-energy,rel_tol=1e-12,abs_tol=1e-9)
        assert math.isclose(newrow['E_leak_nJ'],oldrow['E_leak_nJ']-power*oldrow['T_s']*1e6,rel_tol=1e-12,abs_tol=1e-9)
        assert math.isclose(newrow['area_mm2'],oldrow['area_mm2']-area,rel_tol=1e-12,abs_tol=1e-9)
        if oldrow['arm']!='spad':assert MARKER in newrow['caveats']
    assert changed==EXCLUDED
    assert hashes=={str(p.relative_to(counts)):model.digest(p) for p in counts.rglob('*') if p.is_file()}


def test_query_clocks_match_pipeline_clock():
    for name in ('hardware.json','energy_table.json','characterization/energy_table_dummy.json'):
        for key,row in model.load(model.HERE/name).items():
            if 'frequency' in row.get('query',{}):assert row['query']['frequency']==pricing.DEFAULT_FREQUENCY_MHZ, key
            if name!='hardware.json':assert row['frequency_MHz']==pricing.DEFAULT_FREQUENCY_MHZ, key
    evidence=model.load(model.HERE/'provenance/cacti_frequency.json')
    assert evidence['unique_queries']==12 and evidence['native_runs']==24
    for row in evidence['results']:
        assert row['outputs']['100']==row['outputs']['500']
        assert row['config_sha256']['100']==row['config_sha256']['500']
