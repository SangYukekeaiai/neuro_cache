"""Price-only collection tests using archived native graphs; no simulation."""
import ast
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO/'zoo/archx/zoo'))
spec = importlib.util.spec_from_file_location('stokes_stage2', HERE/'stage2.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def archive(tmp_path):
    source = REPO/'zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts'
    metadata = s.load(source/'counts.json')
    case = metadata['identity']
    root = tmp_path/'stage1'; root.mkdir()
    output = root/'output'
    base = output/s.key(case)/'sample_00000'
    shutil.copytree(source, base/'counts')
    manifest = s.load(base/'counts/manifest.json')
    s.save(base/'steps/checkpoint.json', {'counts/'+name: s.digest(base/'counts'/name)
        for name in ('manifest.json', *manifest['artifacts'])})
    s.save(base/'complete.json', {'status':'complete', 'sample':0, 'arms':list(s.ARMS), 'inputs':{'case':case}})
    failed = {**case, 'arch':'loas'}
    s.save(output/s.key(failed)/'sample_00000/attempt_1.json', {'status':'oom', 'retry':None})
    infeasible = [{**case, 'arch':'prosperity', 'layer':f'layer_{i:02d}_conv', 'solver_status':'INFEASIBLE'}
                  for i in range(6)]
    schedule = tmp_path/'schedule_manifest.json'
    selection = tmp_path/'selection.json'
    s.save(schedule, {'schedules':[case,failed,*infeasible], 'capture_order':[case['trace_relative_dir']]})
    s.save(selection, {'mini':True, 'cases':[{'key':s.key(c)} for c in (case,failed)]})
    s.save(root/'config.json', {'repo':str(REPO), 'schedule_manifest':str(schedule),
        'selection':str(selection), 'output_root':str(output)})
    return root, output, case, failed


def test_real_price_process_counts_unchanged_and_terminal_oom_visible(archive, tmp_path, monkeypatch):
    root, stage1_output, case, failed = archive
    before = s.count_snapshot(stage1_output)
    source = REPO/'zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts'
    source_before = {str(p):s.digest(p) for p in source.rglob('*') if p.is_file()}
    from snn_edp import run, model
    def forbidden(*args, **kwargs): raise AssertionError('Stage 2 invoked a counting callback')
    monkeypatch.setattr(run, 'count', forbidden)
    monkeypatch.setattr(model, 'count_fingerprint', forbidden)
    monkeypatch.setattr(model, 'measurements', forbidden)
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path.is_relative_to(stage1_output) and 'case' in path.relative_to(stage1_output).parts:
            raise AssertionError('Stage 2 read simulator inputs')
        if path.name.endswith('.npy') or path.suffix == '.wcts':
            raise AssertionError('Stage 2 read a capture or trace')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    original_popen = s.subprocess.Popen
    calls = []
    def popen(argv, **kwargs):
        calls.append(argv)
        assert argv[:4] == [sys.executable, '-m', 'snn_edp.run', 'price']
        assert '--case' not in argv
        assert kwargs['start_new_session']
        assert all(kwargs['env'][name] == '1' for name in s.THREAD_ENV)
        return original_popen(argv, **kwargs)
    monkeypatch.setattr(s.subprocess, 'Popen', popen)
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    output = tmp_path/'stage2'
    coverage = s.run(root, table, output, confirmed_drained=True)
    assert len(calls) == 1
    assert coverage['completed_cases'] == 1
    assert coverage['finished_unix'] >= coverage['started_unix']
    assert coverage['wall_seconds'] > 0
    assert s.load(output/'coverage.json')['wall_seconds'] == coverage['wall_seconds']
    assert coverage['case_states'][s.key(failed)] == 'skipped_oom'
    assert coverage['report_complete'] is False
    assert len(coverage['infeasible']) == 6
    assert before == s.count_snapshot(stage1_output)
    assert source_before == {str(p):s.digest(p) for p in source.rglob('*') if p.is_file()}
    assert s.load(output/'immutability.json')['unchanged'] is True
    rows = read_csv(output/'results.csv')
    assert len(rows) == 3
    for row in rows:
        assert row['incomplete'] == 'True' and row['dummy_prices'] == 'True'
        assert row['dummy_table_sha256'] == s.digest(table)
        assert row['sample'] == '0' and row['n'] == '1'
        assert row['capture'] == case['trace_relative_dir']
        assert 'DUMMY PRICES' in row['caveats'] and row['count_A']
    models = read_csv(output/'whole_model.csv')
    complete = [r for r in models if r['arch'] == 'spinalflow']
    assert all(r['status'] == 'complete_dummy_prices' for r in complete)
    assert all(r['comparable_complete'] == 'False' for r in complete)
    for row in models:
        assert 'lower_bound' not in row['status']
        if row['arch'] != 'spinalflow':
            assert all(row[name] == '' for name in
                ('sum_energy_nJ','sum_latency_s','model_EDP_nJ_s','sum_layer_EDP_nJ_s'))
    # Repricing the same immutable graphs uses the existing per-case price receipt.
    per_case = output/'cases'/s.key(case)/'sample_00000'/s.digest(table)
    saved = {str(p):(s.digest(p),p.stat().st_mtime_ns) for p in per_case.rglob('*') if p.is_file()}
    s.run(root, table, output, confirmed_drained=True, workers=1)
    assert saved == {str(p):(s.digest(p),p.stat().st_mtime_ns) for p in per_case.rglob('*') if p.is_file()}


def test_totals_product_of_sums_and_missing_nulls():
    a = {'arch':'spinalflow', 'trace_relative_dir':'capture', 'layer':'layer_01_conv'}
    b = {**a, 'layer':'layer_02_conv'}
    selection = {'feasible':[a,b], 'infeasible':[], 'captures':['capture']}
    rows = []
    for case, energy, latency in ((a,2,3),(b,5,7)):
        rows.extend({'arch':case['arch'],'capture':'capture','layer':case['layer'], 'arm':arm,
            'E_dyn_nJ':energy,'E_leak_nJ':0,'T_s':latency,'EDP_nJ_s':energy*latency,
            'incomplete':True,'energy_table_sha256':'sha'} for arm in s.ARMS)
    models = s.totals(selection, rows, {s.key(a):'complete',s.key(b):'complete'}, 'sha')
    for row in [r for r in models if r['arch']=='spinalflow']:
        assert row['model_EDP_nJ_s'] == 70
        assert row['sum_layer_EDP_nJ_s'] == 41
        assert row['n'] == 1
    models = s.totals(selection, rows[:3], {s.key(a):'complete',s.key(b):'failed'}, 'sha')
    for row in [r for r in models if r['arch']=='spinalflow']:
        assert row['coverage'] == '1/2' and row['failed_layers'] == 1
        assert row['model_EDP_nJ_s'] is None and row['sum_latency_s'] is None
        assert row['partial_sum_energy_nJ'] == 2


def test_drain_confirmation_and_worker_bound(archive, tmp_path):
    root, output, case, _ = archive
    with pytest.raises(ValueError, match='confirm'):
        s.run(root, tmp_path/'missing', tmp_path/'out')
    with pytest.raises(ValueError, match='workers'):
        s.run(root, tmp_path/'missing', tmp_path/'out', confirmed_drained=True, workers=3)
    s.save(output/s.key(case)/'sample_00000/attempt_0.json', {'status':'running'})
    with pytest.raises(ValueError, match='running'):
        s.run(root, tmp_path/'missing', tmp_path/'out', confirmed_drained=True)


def test_corrupt_checkpoint_excluded_without_price(archive, tmp_path, monkeypatch):
    root, output, case, _ = archive
    (output/s.key(case)/'sample_00000/counts/counts.json').write_text('{}')
    def forbidden(*args, **kwargs): raise AssertionError('corrupt checkpoint was priced')
    monkeypatch.setattr(s, 'price_case', forbidden)
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    result = s.run(root, table, tmp_path/'stage2', confirmed_drained=True)
    assert result['result_rows'] == 0 and result['report_complete'] is False
    assert result['case_states'][s.key(case)] == 'failed'
    assert 'checksum' in result['errors'][s.key(case)]


def test_all_saved_artifacts_snapshotted_and_mutation_blocks_collection(archive, tmp_path, monkeypatch):
    root, output, case, _ = archive
    extra = output/'unselected/capture/layer/sample_00000/counts/partial.txt'
    extra.parent.mkdir(parents=True); extra.write_text('before')
    def mutate(*args):
        extra.write_text('changed')
        raise RuntimeError('failed pricing test')
    monkeypatch.setattr(s, 'price_case', mutate)
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    dest = tmp_path/'stage2'
    with pytest.raises(ValueError, match='changed during pricing'):
        s.run(root, table, dest, confirmed_drained=True)
    assert not s.load(dest/'immutability.json')['unchanged']
    assert str(extra.relative_to(output)) in s.load(dest/'counts_before.json')
    assert not (dest/'results.csv').exists()
    assert s.load(dest/'coverage.json')['status'] == 'input_drift'
    assert s.load(dest/'coverage.json')['report_complete'] is False


def test_coordinator_contains_no_simulation_or_count_calls():
    tree = ast.parse((HERE/'stage2.py').read_text())
    calls = {n.func.id if isinstance(n.func,ast.Name) else n.func.attr for n in ast.walk(tree)
             if isinstance(n,ast.Call) and isinstance(n.func,(ast.Name,ast.Attribute))}
    assert not calls.intersection({'count','count_case','count_sample','measurements','run_noc',
                                   'count_fingerprint','archx_aggregate_case'})


def test_progress_every_25_cases_is_flushed(archive, tmp_path, monkeypatch):
    root, _, original, _ = archive
    cases = [{**original, 'layer':f'layer_{i:02d}_conv'} for i in range(26)]
    cfg = s.load(root/'config.json')
    s.save(Path(cfg['schedule_manifest']), {'schedules':cases,
           'capture_order':[original['trace_relative_dir']]})
    s.save(Path(cfg['selection']), {'mini':True, 'cases':[{'key':s.key(c)} for c in cases]})
    monkeypatch.setattr(s, 'stage1_state', lambda base: 'complete')
    monkeypatch.setattr(s, 'count_checkpoint', lambda base, case, sample=0: (base/'counts', {}))
    def priced(case, counts, metadata, table, sha, output, stop, pricing_profile='dummy'):
        return [{'arch':case['arch'], 'capture':case['trace_relative_dir'], 'layer':case['layer'],
                 'arm':arm, 'E_dyn_nJ':2, 'E_leak_nJ':0, 'T_s':3, 'EDP_nJ_s':6,
                 'incomplete':True, 'energy_table_sha256':sha} for arm in s.ARMS]
    monkeypatch.setattr(s, 'price_case', priced)
    messages = []
    monkeypatch.setattr('builtins.print', lambda message, **kwargs:
                        messages.append((json.loads(message), kwargs.get('flush'))))
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    result = s.run(root, table, tmp_path/'stage2', confirmed_drained=True)
    assert [message['finished_cases'] for message, _ in messages] == [25,26]
    assert all(flushed is True for _, flushed in messages)
    assert all(message['total_price_cases'] == 26 for message, _ in messages)
    assert result['wall_seconds'] >= messages[-1][0]['wall_seconds'] >= 0


def test_default_profile_matches_explicit_dummy(archive, tmp_path):
    root, _, _, _ = archive
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    implicit, explicit = tmp_path/'default', tmp_path/'explicit_dummy'
    baseline = s.run(root, table, implicit, confirmed_drained=True)
    requested = s.run(root, table, explicit, confirmed_drained=True, pricing_profile='dummy')
    for name in ('results.csv', 'whole_model.csv'):
        assert (implicit/name).read_bytes() == (explicit/name).read_bytes()
    for result in (baseline, requested):
        assert result['dummy_prices'] is True
        assert result['pricing_profile'] == 'dummy'
        assert result['pricing_status'] == 'DUMMY'
        assert result['pricing_caveat'] == s.DUMMY_CAVEAT
        assert result['energy_table_sha256'] == result['dummy_table_sha256'] == s.digest(table)
    assert not (implicit/'results_ng45.csv').exists()


@pytest.fixture
def ng45_table():
    # Synthetic provenance/values exercise the coordinator contract, not characterization.
    model = REPO/'zoo/archx/zoo/snn_edp'
    table = s.load(model/'characterization/energy_table_dummy.json')
    baseline = s.load(model/'energy_table.json')
    excluded = set(s.load(model/'characterization/pricing_policy.json')['excluded_operations'])
    for name, row in table.items():
        if name in excluded or name in ('shared.ddr4.read', 'shared.ddr4_io.byte'):
            table[name] = baseline[name]
            continue
        row.update(pricing_status='NG45_INTERIM', characterization_technology_nm=45,
                   placeholder=False, dummy=False, assumption=s.NG45_CAVEAT,
                   price_basis={'source':'synthetic test fixture', 'operation':name})
    return table


def test_ng45_uses_supplied_prices_and_labels_without_mutating_checkpoints(archive, tmp_path, ng45_table):
    root, stage1_output, case, _ = archive
    original_table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    original_sha = s.digest(original_table)
    before = s.count_snapshot(stage1_output)
    baseline_dir = tmp_path/'dummy'
    s.run(root, original_table, baseline_dir, confirmed_drained=True)
    baseline = {r['arm']:r for r in read_csv(baseline_dir/'results.csv')}
    # The fixture supplies valid mock provenance; the delta independently tests price binding.
    table = ng45_table
    term = 'spinalflow.adder32.add'
    table[term]['dynamic_energy_nJ'] += 0.75
    supplied = tmp_path/'supplied_prices.json'
    s.save(supplied, table)
    output = tmp_path/'ng45'
    result = s.run(root, supplied, output, confirmed_drained=True, pricing_profile='nangate45')
    sha = s.digest(supplied)
    expected_caveat = 'NanGate45-characterized prices applied to a 7nm/500MHz performance model; interim until ASAP7 synthesis'
    assert result['energy_table_sha256'] == sha != original_sha
    assert result['pricing_caveat'] == expected_caveat
    assert result['pricing_profile'] == 'nangate45'
    assert result['pricing_status'] == 'NG45_INTERIM'
    assert result['dummy_prices'] is False
    assert result['incomplete'] and result['approximation']
    assert 'mixed_technology' in result['approximation_reason']
    assert 'neighbor' in result['approximation_reason']
    assert 'dummy_table_sha256' not in result
    assert result['count_artifacts_unchanged']
    assert before == s.count_snapshot(stage1_output)
    assert s.digest(original_table) == original_sha
    assert (output/('nangate45_table_'+sha+'.json')).read_bytes() == supplied.read_bytes()
    assert not (output/'results.csv').exists() and not (output/'whole_model.csv').exists()
    rows = read_csv(output/'results_ng45.csv')
    assert len(rows) == 3
    for row in rows:
        old = baseline[row['arm']]
        assert row['pricing_profile'] == 'nangate45' and row['pricing_status'] == 'NG45_INTERIM'
        assert row['energy_table_sha256'] == sha and 'dummy_table_sha256' not in row
        assert row['dummy_prices'] == 'False' and row['incomplete'] == row['approximation'] == 'True'
        assert row['pricing_caveat'] == expected_caveat
        assert expected_caveat in ast.literal_eval(row['caveats'])
        assert 'NG45_INTERIM_MIXED_TECHNOLOGY_NEIGHBOR_APPROXIMATION' in ast.literal_eval(row['incomplete_reasons'])
        count = ast.literal_eval(old['breakdown'])[term]['count']
        assert float(row['E_dyn_nJ']) == pytest.approx(float(old['E_dyn_nJ'])+count*0.75)
        assert row['T_s'] == old['T_s'] and row['total_cycles'] == old['total_cycles']
        assert row['counts_json'] == old['counts_json']
    models = read_csv(output/'whole_model_ng45.csv')
    for model in models:
        assert model['pricing_profile'] == 'nangate45'
        assert model['pricing_status'] == 'NG45_INTERIM'
        assert model['dummy_prices'] == 'False' and model['energy_incomplete'] == 'True'
        assert model['incomplete'] == model['approximation'] == 'True'
        assert model['pricing_caveat'] == expected_caveat
        assert model['energy_table_sha256'] == sha and 'dummy_table_sha256' not in model
        if model['arch'] == 'spinalflow':
            assert model['status'] == 'complete_ng45_interim'
        else:
            assert model['status'] == 'missing_layers'
            assert model['model_EDP_nJ_s'] == model['sum_energy_nJ'] == model['sum_latency_s'] == ''
    native = output/'cases'/s.key(case)/'sample_00000'/sha
    assert (native/'energy_table.json').read_bytes() == supplied.read_bytes()
    native_before = {str(p):(s.digest(p),p.stat().st_mtime_ns) for p in native.rglob('*') if p.is_file()}
    s.run(root, supplied, output, confirmed_drained=True, pricing_profile='nangate45')
    assert native_before == {str(p):(s.digest(p),p.stat().st_mtime_ns) for p in native.rglob('*') if p.is_file()}


@pytest.mark.parametrize('nested', [False, True])
def test_ng45_refuses_t97_root_or_child_without_writes(archive, tmp_path, nested):
    root, _, _, _ = archive
    old = tmp_path/'t97'
    s.save(old/'coverage.json', {'dummy_prices':True, 'dummy_table_sha256':'old'})
    (old/'results.csv').write_text('preserve exact T97 bytes\n')
    before = {str(p):s.digest(p) for p in old.rglob('*') if p.is_file()}
    target = old/'child' if nested else old
    with pytest.raises(ValueError, match='separate output root'):
        s.run(root, tmp_path/'unused-table', target, confirmed_drained=True, pricing_profile='nangate45')
    assert before == {str(p):s.digest(p) for p in old.rglob('*') if p.is_file()}
    if nested: assert not target.exists()


def test_unknown_profile_rejected_before_output(archive, tmp_path):
    root, _, _, _ = archive
    output = tmp_path/'invalid'
    with pytest.raises(ValueError, match='unknown pricing profile'):
        s.run(root, tmp_path/'unused-table', output, confirmed_drained=True, pricing_profile='ng45')
    assert not output.exists()


@pytest.mark.parametrize('table_name', ['energy_table.json', 'characterization/energy_table_dummy.json'])
def test_ng45_rejects_default_and_dummy_before_any_pricing(archive, tmp_path, monkeypatch, table_name):
    root, _, _, _ = archive
    table = REPO/'zoo/archx/zoo/snn_edp'/table_name
    output = tmp_path/'rejected'
    def forbidden(*args, **kwargs): raise AssertionError('invalid NG45 table reached pricing')
    monkeypatch.setattr(s, 'price_case', forbidden)
    with pytest.raises(ValueError, match='NG45'):
        s.run(root, table, output, confirmed_drained=True, pricing_profile='nangate45')
    assert not output.exists()


@pytest.mark.parametrize('operation,field,value', [
    ('spinalflow.adder32.add','dynamic_energy_nJ',None),
    ('spinalflow.adder32.add','leakage_power_mW',float('nan')),
    ('spinalflow.adder32.add','area_mm2',-1),
    ('spinalflow.adder32.add','placeholder',True),
    ('spinalflow.adder32.add','dummy',True),
    ('spinalflow.adder32.add','pricing_status','DUMMY'),
    ('spinalflow.adder32.add','characterization_technology_nm',7),
    ('spinalflow.adder32.add','price_basis',{}),
    ('spinalflow.adder32.add','assumption','missing the required caveat'),
    ('cache.l2_tags.read','dynamic_energy_nJ',1),
    ('cache.l2_tags.read','pricing_status','NG45_INTERIM'),
    ('shared.ddr4.read','dynamic_energy_nJ',0),
])
def test_ng45_contract_rejects_mutated_row(ng45_table, operation, field, value):
    s.check_ng45_table(ng45_table)
    ng45_table[operation][field] = value
    with pytest.raises(ValueError, match='NG45'):
        s.check_ng45_table(ng45_table)


def test_ng45_contract_rejects_missing_operation(ng45_table):
    del ng45_table['spinalflow.adder32.add']
    with pytest.raises(ValueError, match='98-operation'):
        s.check_ng45_table(ng45_table)


@pytest.fixture
def saved_price_response(archive, tmp_path, monkeypatch):
    _, stage1_output, case, _ = archive
    counts = stage1_output/s.key(case)/'sample_00000/counts'
    metadata = s.load(counts/'counts.json')
    table = REPO/'zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json'
    sha = s.digest(table)
    output = tmp_path/'saved_price_response'
    directory = output/'cases'/s.key(case)/'sample_00000'/sha
    rows = [{'arch':case['arch'], 'arm':arm, 'energy_table_sha256':sha,
             'E_dyn_nJ':2.0, 'E_leak_nJ':3.0, 'T_s':7.0, 'EDP_nJ_s':35.0,
             'incomplete_reasons':['existing_fixture_reason'], 'caveats':[]}
            for arm in s.ARMS]
    s.save(directory/'result.json', {'rows':rows})
    s.save(directory/'manifest.json', {
        'fingerprint':{'energy_table_sha256':sha, 'count_manifest_sha256':s.digest(counts/'manifest.json')},
        'artifacts':{'result.json':s.digest(directory/'result.json')}})
    class FinishedProcess:
        def wait(self, timeout=None): return 0
    def already_priced(argv, **kwargs):
        assert argv[:4] == [sys.executable, '-m', 'snn_edp.run', 'price']
        assert argv[argv.index('--counts')+1] == str(counts)
        assert argv[argv.index('--out')+1] == str(directory)
        return FinishedProcess()
    monkeypatch.setattr(s.subprocess, 'Popen', already_priced)
    return directory, (case, counts, metadata, table, sha, output, s.threading.Event())


def test_dummy_reason_is_added_to_all_three_returned_json_rows(saved_price_response):
    directory, arguments = saved_price_response
    assert all('DUMMY_PRICES' not in row['incomplete_reasons']
               for row in s.load(directory/'result.json')['rows'])
    returned = json.loads(json.dumps(s.price_case(*arguments)))
    assert len(returned) == 3 and {row['arm'] for row in returned} == set(s.ARMS)
    for row in returned:
        assert row['incomplete'] is True
        assert 'DUMMY_PRICES' in row['incomplete_reasons'], row['arm']
        assert 'existing_fixture_reason' in row['incomplete_reasons']


@pytest.mark.parametrize('arm', s.ARMS)
def test_bad_layer_edp_with_valid_artifact_hash_is_rejected(saved_price_response, arm):
    directory, arguments = saved_price_response
    result = s.load(directory/'result.json')
    next(row for row in result['rows'] if row['arm'] == arm)['EDP_nJ_s'] = 36.0
    s.save(directory/'result.json', result)
    manifest = s.load(directory/'manifest.json')
    manifest['artifacts']['result.json'] = s.digest(directory/'result.json')
    s.save(directory/'manifest.json', manifest)
    # Integrity and identity are valid; only 36 != (2+3)*7 must reject this row.
    assert s.validate_artifacts(directory) == manifest
    assert manifest['fingerprint']['count_manifest_sha256'] == s.digest(arguments[1]/'manifest.json')
    assert manifest['fingerprint']['energy_table_sha256'] == arguments[4]
    with pytest.raises(ValueError, match='^layer EDP differs from energy times latency$'):
        s.price_case(*arguments)
