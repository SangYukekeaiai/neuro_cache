"""Validate the five full-pipeline dummy cases and publish their exact paths."""
import csv
import json
import math
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from demo.all_bench import common
from energy_driver import MODEL_ROOT
from snn_edp import model


def main():
    output=HERE.parent/'all_bench'
    table=MODEL_ROOT/'characterization/energy_table_dummy.json'
    inputs=common.current_inputs(); inputs['table']=common.demo.digest(table)
    index=[]; rows=[]
    record_keys={'spinalflow':'R','ptb':'B','loas':'B','gustavsnn':'R_g','prosperity':'R_p'}
    for arch in common.demo.ARCHES:
        case=json.loads((HERE/(arch+'.json')).read_text())
        folder=common.demo.folder_for(case,output).resolve()
        result=json.loads((folder/'result.json').read_text())
        actual=common.validate_case(case,folder,inputs,receipt=False)
        counts=json.loads((folder/'counts.json').read_text())
        generation=json.loads((folder/'generation.json').read_text())
        assert counts[record_keys[arch]]==generation['records']
        with (folder/'record_count.csv').open() as f: record,=list(csv.DictReader(f))
        assert int(record['R_p'])==generation['records']
        base=folder.parent/'archx_artifacts'/folder.name
        counts_dir,=list((base/'counts').iterdir())
        priced_dir,=list((base/'energy').iterdir())
        cm=model.validate_artifacts(counts_dir);pm=model.validate_artifacts(priced_dir)
        assert pm['fingerprint']['energy_table_sha256']==inputs['table']
        assert cm['fingerprint']==model.count_fingerprint(folder)
        assert pm['fingerprint']['count_manifest_sha256']==model.digest(counts_dir/'manifest.json')
        categories_path=counts_dir/'event_count_categories.json'
        categories=json.loads(categories_path.read_text())['arms']
        assert set(categories)==set(common.ARMS)
        for row in actual:
            assert row['incomplete'] and row['EDP_nJ_s']>0
            assert 'DUMMY placeholder pending ASAP7 synthesis' in row['caveats']
            assert not any(x.endswith('=null') for x in row['incomplete_reasons'])
            data=categories[row['arm']]
            assert set(data['operations'])==set(row['breakdown'])
            for key,value in data['operations'].items():
                assert value=={name:row['breakdown'][key][name] for name in ('count','category')}
            for category in ('core','memory'):
                expected=sum(v['count'] for v in data['operations'].values() if v['category']==category)
                assert math.isclose(data['rollups'][category],expected,rel_tol=1e-12)
            assert data['rollups']['total']==data['rollups']['core']+data['rollups']['memory']
        assert not (folder/'sample_00000.wcts').exists()
        assert not (folder/'failure.json').exists()
        common.write_receipt(folder,inputs,{'task':'layer8 dummy dry run','energy_table':str(table),'counts_dir':str(counts_dir),'priced_result':str(priced_dir/'result.json')})
        common.validate_case(case,folder,inputs)
        index.append({'arch':arch,'case_folder':str(folder),'pipeline_counts':str(folder/'counts.json'),'counts_dir':str(counts_dir),'event_count_categories':str(categories_path),'priced_result':str(priced_dir/'result.json'),'pipeline_result':str(folder/'result.json'),'receipt':str(folder/'receipt.json')})
        rows.extend(actual)
    assert len(rows)==15 and len({(r['arch'],r['arm']) for r in rows})==15
    common.demo.collect(output)
    common.write_csv(HERE/'results.csv',rows)
    common.demo.save(HERE/'output_paths.json',{'dummy_table':str(table),'dummy_table_sha256':inputs['table'],'cases':index})
    columns=('arch','arm','total_cycles','T_s','E_dyn_nJ','E_leak_nJ','EDP_nJ_s','incomplete')
    common.write_csv(HERE/'comparison.csv',[{k:r[k] for k in columns} for r in rows],columns)
    text='# Layer-8 dummy execution outputs\n\nDUMMY placeholder pending ASAP7 synthesis. Sample0; layer_08_core_features_27, B09/loas_vgg16_T4_n500.\n\n'
    text+='Dummy table: `'+str(table)+'`\n\nSHA256: `'+inputs['table']+'`\n'
    for item in index:
        text+='\n## '+item['arch']+'\n\n'
        for name,path in item.items():
            if name!='arch':text+='- '+name+': `'+path+'`\n'
    text+='\nFigures: `'+str(HERE.parents[1]/'figures/layer8_dummy_edp.pdf')+'` and `'+str(HERE.parents[1]/'figures/layer8_dummy_edp.png')+'`.\n'
    (HERE/'OUTPUT_PATHS.md').write_text(text)
    summary={'cases':5,'rows':15,'arms':list(common.ARMS),'all_metrics_finite_positive':True,'all_rows_flagged_dummy_incomplete':True,'null_price_reasons':0,'analytic_record_matches':5,'category_breakdown_matches':15,'table_sha256':inputs['table']}
    common.demo.save(HERE/'validation.json',summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
