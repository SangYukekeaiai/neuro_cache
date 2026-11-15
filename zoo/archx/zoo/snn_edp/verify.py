"""Sanity-check native model quantities against saved T84 CSV data only."""
import argparse
import ast
import csv
import math
import time
from .model import *
from .run import count
from .pricing import price


def close(actual,expected,label):
    actual,expected=float(actual),float(expected)
    error=abs(actual-expected)/abs(expected) if expected else (0 if actual==0 else math.inf)
    if not math.isfinite(actual) or error>=1e-9: raise AssertionError(f'{label}: {actual} != {expected}; rel={error}')
    return error


def retired_reference(reference, arch, table):
    """Subtract only explicitly retired costs from independent historical data."""
    import copy
    ref=copy.deepcopy(reference)
    retirement=load(HERE/'provenance/retired_logic.json')
    assert ref['energy_table_sha256']==retirement['baseline_table_sha256']
    assert digest(table)==retirement['current_table_sha256']
    terms=ast.literal_eval(ref['breakdown'])
    reasons=set(ast.literal_eval(ref['incomplete_reasons']))
    dynamic=core=power=area=0.0; seen=set()
    for key,old in retirement['rows'].items():
        if key not in terms: continue
        term=terms[key]
        removed=float(term['count'])*old['dynamic_energy_nJ']
        close(term['E_dyn_nJ'],removed,'historical energy identity:'+key)
        dynamic+=removed
        if key.startswith(arch+'.'): core+=removed
        term['E_dyn_nJ']=0.0
        physical=old['physical_module']
        if physical not in seen:
            power+=old['leakage_power_mW']*old['system_instances']
            area+=old['area_mm2']*old['system_instances'];seen.add(physical)
        reasons.add(key+':incomplete/placeholder')
        reasons.update(key+':'+field+'=null' for field in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'))
    exclusion=load(HERE/'provenance/prefetch_control_exclusion.json')
    excluded=set(exclusion['excluded_operations'])
    for key,old in exclusion['rows']['default'].items():
        if key not in terms: continue
        terms[key]['E_dyn_nJ']=0.0
        owner=key.rsplit('.',1)[0]
        if owner not in seen:
            n=exclusion['system_instances'][key]
            power+=(old['leakage_power_mW'] or 0)*n
            area+=(old['area_mm2'] or 0)*n
            seen.add(owner)
    reasons={reason for reason in reasons if reason.split(':',1)[0] not in excluded}
    ref['E_dyn_nJ']=sum(float(v['E_dyn_nJ']) for v in terms.values())
    ref['E_core_dyn_nJ']=sum(float(v['E_dyn_nJ']) for key,v in terms.items() if key.startswith(arch+'.') and '.l1_weight_spad.' not in key)
    ref['E_leak_nJ']=float(ref['E_leak_nJ'])-power*float(ref['T_s'])*1e6
    ref['area_mm2']=float(ref['area_mm2'])-area
    ref['EDP_nJ_s']=(ref['E_dyn_nJ']+ref['E_leak_nJ'])*float(ref['T_s'])
    aliases=load(HERE/'provenance/operation_renames.json')['operation_keys']
    terms={aliases.get(key,key):value for key,value in terms.items()}
    reasons={next((new+reason[len(old):] for old,new in aliases.items() if reason.startswith(old+':')),reason) for reason in reasons}
    ref['breakdown']=repr(terms);ref['incomplete_reasons']=repr(sorted(reasons))
    ref['energy_table_sha256']=digest(table)
    return ref


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch',choices=ARCHES,action='append')
    args=parser.parse_args()
    import archx
    print("archx.__file__="+archx.__file__,flush=True)
    from loguru import logger
    logger.remove(); archx.set_log_level('ERROR')
    source=HERE/'reference_t84_results.csv'
    fixture_manifest=load(HERE/'fixtures/manifest.json')
    assert digest(source)==fixture_manifest['reference_sha256'], 'pinned reference changed'
    references=list(csv.DictReader(source.open()))
    table=HERE/'energy_table.json'
    checked=[]; started=time.monotonic()
    for arch in args.arch or ARCHES:
        chosen=[r for r in references if r['arch']==arch and r['capture']=='B09/loas_vgg16_T4_n500' and r['layer']=='layer_01_core_features_3']
        assert len(chosen)==3
        case=HERE/'fixtures'/arch
        for name,expected in fixture_manifest['cases'][arch]['files'].items():
            assert digest(case/name)==expected, 'fixture changed: '+arch+'/'+name
        directory=HERE/'runs'/arch
        if not (directory/'fixture_counts/manifest.json').exists(): count(case,directory/'fixture_counts')
        result=price(directory/'fixture_counts',table,directory/'fixture_priced')
        worst=0; term_worst=0; terms=0
        for row in result:
            ref=retired_reference(next(r for r in chosen if r['arm']==row['arm']),arch,table)
            for field in ('E_dyn_nJ','E_leak_nJ','T_s','EDP_nJ_s','area_mm2','total_cycles','E_core_dyn_nJ','E_chain_reference_nJ'):
                worst=max(worst,close(row[field],ref[field],arch+'/'+row['arm']+'/'+field))
            expected=ast.literal_eval(ref['breakdown'])
            assert set(expected)==set(row['breakdown'])
            for key,term in row['breakdown'].items():
                for field in ('count','E_dyn_nJ'):
                    term_worst=max(term_worst,close(term[field],expected[key][field],key+'/'+field))
                assert term['count_expression']==expected[key]['count_expression']
                terms+=1
            assert row['energy_table_sha256']==ref['energy_table_sha256']
            assert row['incomplete']==(ref['incomplete']=='True')
            assert row['incomplete_reasons']==ast.literal_eval(ref['incomplete_reasons'])
        checked.append({'arch':arch,'rows':len(result),'terms':terms,'max_total_relative_error':worst,'max_term_relative_error':term_worst})
        print(json.dumps(checked[-1]),flush=True)
    report={'cases':checked,'rows':sum(c['rows'] for c in checked),'terms':sum(c['terms'] for c in checked),
            'validation_basis':'historical independent CSV minus retired logic prices and nine explicit prefetch-control exclusions; deduplicated physical inventory', 'retirement_record':str(HERE/'provenance/retired_logic.json'),'reference_csv':str(source),'reference_sha256':digest(source),'energy_table_sha256':digest(table),
            'archx_backend':'AGraph compile/extract/execute; aggregate_event_count + aggregate_event_metric',
            'archx_file':archx.__file__, 'performance_cache_disabled':True,'wall_seconds':time.monotonic()-started}
    save(HERE/('first_arch.json' if args.arch else 'validation.json'),report)


if __name__=='__main__': main()
