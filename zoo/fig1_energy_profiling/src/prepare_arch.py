"""Prepare the approved single-node bases and capacity-only SRAM variants."""
from pathlib import Path
import copy
import hashlib
import json
import math

import yaml
from lays.weight_trace_gen.trace import build_workload_from_trace
from zoo.fig12_edp.demo.all_bench.layer_scope import kept
from schedule_spec import PES, SIZES, ROOT, TRACE, STATE_MARGIN, resident

SOURCE = ROOT.parent / 'wt500_fig3cfg/arch.yaml'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def differences(old, new, prefix=''):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for key in sorted(old.keys() | new.keys()):
            path = f'{prefix}/{key}'
            if key not in new:
                result.append({'path': path, 'before': old[key], 'after': None, 'action': 'remove'})
            elif key not in old:
                result.append({'path': path, 'before': None, 'after': new[key], 'action': 'add'})
            else:
                result.extend(differences(old[key], new[key], path))
        return result
    if isinstance(old, list) and isinstance(new, list):
        assert len(old) == len(new)
        return [v for i, (a, b) in enumerate(zip(old, new)) for v in differences(a, b, f'{prefix}/{i}')]
    return [] if old == new else [{'path': prefix, 'before': old, 'after': new}]


def main():
    original = yaml.safe_load(SOURCE.read_text())
    meta = json.loads((TRACE / 'meta.json').read_text())
    widths = original['arch']['bitwidths']
    state_max = {'psum': 0, 'vmem': 0}
    maxima_at = {}
    for arch in PES:
        for size, capacity in SIZES.items():
            for layer in meta['layers']:
                if not kept(layer):
                    continue
                p = build_workload_from_trace(meta, layer)['problem']
                tile = resident(p, arch, capacity, widths['BW_WEIGHT'])
                outputs = tile['HO'] * tile['WO'] * tile['COUT']
                required = {'psum': outputs * tile['T'] * widths['BW_PSUM'] // 8,
                            'vmem': outputs * widths['BW_VMEM'] // 8}
                for var, count in required.items():
                    if count > state_max[var]:
                        state_max[var] = count
                        maxima_at[var] = {'arch': arch, 'size': size, 'layer': layer, 'tile': tile}
    fixed_state = {v: 1 << math.ceil(math.log2(n * STATE_MARGIN)) for v, n in state_max.items()}
    manifest = {'source': str(SOURCE), 'source_sha256': sha(SOURCE), 'bases': {}, 'variants': {},
                'authority': 'T101: one node, PEs 16/8/8; fixed state buffers sized to pinned-nest maximum plus margin; only weight capacity varies across bars',
                'state_buffers': {'maximum_required_bytes': state_max, 'maximum_at': maxima_at,
                                  'margin_factor_before_power_of_two_rounding': STATE_MARGIN,
                                  'fixed_capacity_bytes': fixed_state,
                                  'meta_sha256': sha(TRACE / 'meta.json'),
                                  'same_for_all_architectures_and_sizes': True},
                'plan_wording_amendment': 'Capacity-only applies relative to each approved single-node base, not the 16-node/4-PE campaign YAML.',
                'physical_hierarchy': 'DRAM <-> node-local buffers <-> PEs; no global buffer',
                'noclevel_schema_slot': 'Required by the shared parser, but entries omitted: has_noc_buffer=False. single_node=True disables NoC-level assignments and GB transactions.',
                'schedule_generation': 'Direct analytic construction authorized; local-buffer feasibility must pass before production manifests'}
    (ROOT / 'arch').mkdir(exist_ok=True)
    (ROOT / 'configs').mkdir(exist_ok=True)
    for arch, pes in PES.items():
        base = copy.deepcopy(original)
        base['arch']['single_node'] = True
        node = base['arch']['storage'][0]
        node['instances'] = 1
        node['pe']['num_pes'] = pes
        node['local_buffer']['entries'].update(fixed_state)
        del base['arch']['storage'][1]['entries']
        delta = differences(original, base)
        assert {d['path'] for d in delta} == {'/arch/single_node', '/arch/storage/0/instances', '/arch/storage/0/pe/num_pes', '/arch/storage/1/entries', '/arch/storage/0/local_buffer/entries/psum', '/arch/storage/0/local_buffer/entries/vmem'}
        path = ROOT / 'arch' / f'{arch}_base.yaml'
        path.write_text(yaml.safe_dump(base, sort_keys=False))
        manifest['bases'][arch] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'diff': delta}
        for size, capacity in SIZES.items():
            variant = copy.deepcopy(base)
            variant['arch']['storage'][0]['local_buffer']['entries']['weight'] = capacity
            delta = differences(base, variant)
            assert len(delta) == 1 and delta[0]['path'] == '/arch/storage/0/local_buffer/entries/weight'
            path = ROOT / 'arch' / f'{arch}_{size}.yaml'
            path.write_text(yaml.safe_dump(variant, sort_keys=False))
            manifest['variants'][f'{arch}/{size}'] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'diff': delta}
    assert sha(SOURCE) == manifest['source_sha256']
    (ROOT / 'configs/arch_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print('3 single-node bases; 12 weight-capacity variants; fixed state bytes:', fixed_state,
          '; maxima:', state_max, '; source unchanged')


if __name__ == '__main__':
    main()
