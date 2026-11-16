"""Check the pinned traversal against real tile and local-buffer contracts."""
import hashlib
import json
from pathlib import Path

import yaml

from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.steps import StepInfo
from lays.nocsim.schedule.tiles import iter_node_tiles
from lays.parsers.arch import SNNArch
from lays.parsers.bitwidths import SNNBitwidths
from lays.parsers.layer import SNNProb
from lays.weight_trace_gen.trace import build_workload_from_trace
from zoo.fig12_edp.demo.all_bench.layer_scope import kept, SCOPE_PATH
from zoo.wt500_fig3cfg.gen_inputs import _bridge_tile_violations
from schedule_spec import PES, SIZES, ROOT, TRACE, resident, strategy as pinned_strategy

REPO = ROOT.parents[1]
OUT = ROOT / 'outputs/self_checks/schedule_contract'


def inspect(arch_name, name, problem, arch_path, cout=None):
    arch = SNNArch(arch_path)
    bw = SNNBitwidths(arch_path)
    capacities = arch.node_local_buffer_entries
    weight_per_channel = problem['KH'] * problem['KW'] * problem['CIN'] * bw.bw_weight // 8
    tile = resident(problem, arch_name, capacities['weight'], bw.bw_weight)
    if cout is not None:
        tile['COUT'] = cout
    cout = tile['COUT']
    strategy = pinned_strategy(problem, tile, arch_name)
    path = OUT / 'workloads' / f'{name}.yaml'
    path.write_text(yaml.safe_dump({'problem': problem}))
    prob = SNNProb(path)
    schedule = schedule_from_strategy(strategy, prob)
    steps = StepInfo(schedule, prob)
    footprint = {v: schedule.data_size[v] * getattr(bw, 'bw_' + v) // 8
                 for v in ('weight', 'psum', 'vmem')}
    violations = []
    tile_count = 0
    for i, tile in enumerate(iter_node_tiles(schedule, prob)):
        violations.extend(_bridge_tile_violations(arch_name, tile, problem, i))
        tile_count += 1
    loads = sum(steps.weight_changes(i, 0) for i in range(schedule.dram_num_steps))
    total_weights = weight_per_channel * problem['COUT']
    expected_loads = (problem['COUT'] // cout if arch_name == 'gustavsnn' or cout == problem['COUT']
                      else problem['HO'] * problem['WO'] * problem['COUT'] // cout)
    assert loads == expected_loads
    assert not violations, violations[:1]
    return {'arch': arch_name, 'layer': name, 'problem': problem, 'strategy': strategy,
            'resident_cout': cout, 'spatial_cout': PES[arch_name],
            'tile_bytes': footprint, 'capacity_bytes': capacities,
            'capacity_violations': {v: {'required': n, 'capacity': capacities[v]}
                                    for v, n in footprint.items() if n > capacities[v]},
            'native_bridge_violations': len(violations), 'tiles_checked': tile_count,
            'weight_loads': loads, 'weight_transfer_bytes': loads * footprint['weight'],
            'compulsory_weight_bytes': total_weights,
            'traffic_multiple_of_compulsory': loads * footprint['weight'] / total_weights}


def main():
    (OUT / 'workloads').mkdir(parents=True, exist_ok=True)
    meta = json.loads((TRACE / 'meta.json').read_text())
    layers = [name for name in meta['layers'] if kept(name)]
    assert len(layers) == 12
    rows = []
    for arch in PES:
        for size in SIZES:
            for layer in layers:
                row = inspect(arch, layer, build_workload_from_trace(meta, layer)['problem'],
                              ROOT / 'arch' / f'{arch}_{size}.yaml')
                rows.append({**row, 'size': size})
    example_problem = {'shape': 'snn-layer', 'KH': 3, 'KW': 3, 'CIN': 256,
                       'COUT': 256, 'HO': 28, 'WO': 28, 'T': 4}
    example = inspect('loas', 'boss_conv3_1_example', example_problem, ROOT / 'arch/loas_256k.yaml')
    assert example['resident_cout'] == 64 and example['tile_bytes']['weight'] == 144 * 1024
    assert not example['capacity_violations']
    layer = 'layer_04_core_features_14'
    bounded = inspect('loas', layer, build_workload_from_trace(meta, layer)['problem'],
                      ROOT / 'arch/loas_512k.yaml', cout=128)
    assert not bounded['capacity_violations'] and bounded['traffic_multiple_of_compulsory'] == 64
    first = layers[0]
    gustav_minimum = inspect('gustavsnn', first, build_workload_from_trace(meta, first)['problem'],
                            ROOT / 'arch/gustavsnn_128k.yaml', cout=PES['gustavsnn'])
    sources = [TRACE / 'meta.json', SCOPE_PATH, Path(__file__),
               REPO / 'src/lays/nocsim/schedule/decode.py',
               REPO / 'src/lays/nocsim/schedule/steps.py',
               REPO / 'src/lays/scheduler/objectives/utilization.py',
               REPO / 'src/lays/scheduler/constants.py',
               REPO / 'zoo/wt500_fig3cfg/gen_inputs.py']
    report = {'status': 'PASS' if not any(r['capacity_violations'] for r in rows) else 'POP_OUT_LOCAL_BUFFER_CONFLICT',
              'scope': 'Analytic candidates and shared decoder/bridge checks; no production schedules or native runs',
              'kept_layers': layers, 'excluded_layers': [n for n in meta['layers'] if not kept(n)],
              'planned_cases': len(rows) * 10, 'candidate_count': len(rows),
              'capacity_conflict_count': sum(bool(r['capacity_violations']) for r in rows),
              'boss_worked_example': example, 'gustav_minimum_fanout_tile': gustav_minimum,
              'loas_deliberately_smaller_cout_control': bounded, 'candidates': rows,
              'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'planned_cases', 'candidate_count', 'capacity_conflict_count')}))
    print('Boss example:', example['tile_bytes'], 'traffic multiple:', example['traffic_multiple_of_compulsory'])
    print('Gustav minimum tile:', gustav_minimum['tile_bytes'])
    print('LoAS bounded:', bounded['tile_bytes'], 'traffic multiple:', bounded['traffic_multiple_of_compulsory'])


if __name__ == '__main__':
    main()
