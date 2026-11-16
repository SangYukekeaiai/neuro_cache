"""Extract immutable LoAS scratchpad counts, never NG45 prices, from durable rows."""
import ast
import csv
from decimal import Decimal
import json
from pathlib import Path


def extract(rows_root, layers, output, record_source):
    cases = []
    summaries = []
    samples = []
    for folder in sorted(Path(rows_root).glob('sample_*')):
        commit_path = folder / 'commit.json'
        record_source(commit_path)
        commit = json.loads(commit_path.read_text())
        source = folder / 'results_ng45.csv'
        digest = record_source(source)
        assert digest == commit['artifacts']['results_ng45.csv'], source
        sample = int(folder.name.removeprefix('sample_'))
        found = set()
        with source.open(newline='') as stream:
            csv.field_size_limit(16 * 1024 * 1024)
            for row in csv.DictReader(stream):
                if (row['arch'], row['arm'], row['capture']) != ('loas', 'spad', 'B09/loas_vgg16_T4_n500'):
                    continue
                layer = row['layer']
                assert layer in layers and layer not in found
                found.add(layer)
                provenance = ast.literal_eval(row['input_count_provenance'])
                noc = provenance['noc']
                assert int(row['sample']) == sample == noc['sample_idx']
                assert Decimal(row['total_cycles']) == noc['total_cycles']
                assert float(row['T_s']) == noc['total_cycles'] / 500_000_000
                terms = ast.literal_eval(row['breakdown'])
                terms = {k: {f: v[f] for f in ('count', 'count_expression', 'category')} for k,v in terms.items()}
                case = dict(arch='loas', arm='spad', layer=layer, sample=sample,
                            total_cycles=noc['total_cycles'], counts=provenance['counts'],
                            noc={k:v for k,v in noc.items() if k!='inputs'}, operations=terms,
                            source_csv_sha256=digest, original_input_hashes=provenance['source_hashes'],
                            original_noc_input_hashes={k:v['sha256'] for k,v in noc['inputs'].items()
                                                       if isinstance(v,dict) and 'sha256' in v})
                dest = output / 'nocsim_counts_real' / f'sample_{sample:03d}' / (layer+'.json')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(case, indent=2, sort_keys=True)+'\n')
                cases.append(case)
                summaries.append(dict(sample=sample,layer=layer,total_cycles=noc['total_cycles'],
                                      cycles_mod_T=noc['total_cycles'] % provenance['counts']['T'],
                                      A=provenance['counts']['A'], B=provenance['counts']['B'],
                                      S_or=provenance['counts']['S_or'],S_sum=provenance['counts']['S_sum']))
        assert found == set(layers), (sample, found ^ set(layers))
        samples.append(sample)
    assert len(samples) == 23 and len(cases) == 276, (len(samples),len(cases))
    with (output/'real_counts_index.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    return samples, cases
