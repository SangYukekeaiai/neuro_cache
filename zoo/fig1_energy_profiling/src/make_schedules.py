"""Save the validated analytic nests in the native schedule artifact format."""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path

from lays.scheduler.artifact import ScheduleArtifact
from zoo.wt500_fig3cfg.gen_inputs import check_bridge_compatibility
from check_schedule_contract import main as check_contract
from schedule_spec import ROOT, TRACE, PES, SIZES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=tuple(PES))
    args = parser.parse_args()
    check_contract()
    evidence_path = ROOT / 'outputs/self_checks/schedule_contract/verification.json'
    evidence = json.loads(evidence_path.read_text())
    if evidence['status'] != 'PASS':
        raise ValueError('Pinned nest fails local-buffer feasibility; no manifests may be published')
    contract = {'construction': 'direct analytic; no optimizer or post-solve permutation',
                'outer_order': {'loas': ['HO', 'WO', 'COUT'], 'ptb': ['HO', 'WO', 'COUT'],
                                'gustavsnn': ['COUT', 'HO', 'WO', 'T']},
                'resident_cout': 'largest divisor of full COUT, divisible by spatial COUT, whose full-kernel/full-CIN weights fit',
                'spatial_cout': PES,
                'resident_pixels': {'loas': '1x1', 'ptb': '1x1', 'gustavsnn': '1x1; T advances before the next pixel'},
                'resident_T': {'loas': 'full', 'ptb': 'full', 'gustavsnn': 1},
                'noclevel': 'inert; no temporal loops or inter-node spatial factors',
                'spatial_vs_residency': 'The approved contract allows resident COUT above PE fanout. It does not use the stock optimizer constraint barring NodeLevel temporal COUT.',
                'spec_source_sha256': sha(ROOT / 'src/schedule_spec.py')}
    contract_path = ROOT / ('configs/schedule_contract_'+args.arch+'.json' if args.arch else 'configs/schedule_contract.json')
    write(contract_path, contract)
    arch_manifest = json.loads((ROOT / 'configs/arch_manifest.json').read_text())
    index_path = ROOT / 'outputs/manifest/index.json'
    summaries = json.loads(index_path.read_text())['manifests'] if args.arch else {}
    for arch in PES:
        if args.arch and arch != args.arch: continue
        for size, capacity in SIZES.items():
            directory = ROOT / 'outputs/manifest' / f'{arch}_{size}'
            rows = []
            for row in evidence['candidates']:
                if row['arch'] != arch or row['size'] != size:
                    continue
                arch_path = ROOT / 'arch' / f'{arch}_{size}.yaml'
                artifact = ScheduleArtifact(
                    arch=arch, trace_dir=TRACE.name, layer_name=row['layer'],
                    workload={'problem': row['problem']},
                    result={'has_solution': True, 'status': 'ANALYTIC_VALIDATED',
                            'strategy': row['strategy'],
                            'configs': {'arch': str(arch_path.relative_to(ROOT.parents[1]))},
                            'capacity_bytes': row['capacity_bytes'], 'tile_bytes': row['tile_bytes']},
                    dram_num_steps=row['tiles_checked'], mode='fig1_pinned',
                    arch_yaml_sha256=sha(arch_path), mapspace_yaml_sha256=sha(contract_path))
                path = directory / 'schedules' / (row['layer'] + '.json')
                write(path, asdict(artifact))
                gate = check_bridge_compatibility(path, arch)
                if not gate['passed']:
                    raise ValueError(f'{path}: {gate}')
                rows.append({k: row[k] for k in ('layer', 'resident_cout', 'spatial_cout', 'tile_bytes',
                                                'weight_loads', 'weight_transfer_bytes',
                                                'compulsory_weight_bytes', 'traffic_multiple_of_compulsory')})
                rows[-1].update(schedule=str(path.relative_to(ROOT)), schedule_sha256=sha(path), native_bridge=gate)
            assert len(rows) == len(evidence['kept_layers']) == 12
            manifest = {'arch': arch, 'size': size, 'weight_capacity_bytes': capacity,
                        'state_buffers': arch_manifest['state_buffers'],
                        'capture_relative_dir': 'B09/' + TRACE.name,
                        'meta_sha256': sha(TRACE / 'meta.json'), 'samples': list(range(10)),
                        'kept_layers': evidence['kept_layers'], 'excluded_layers': evidence['excluded_layers'],
                        'construction': contract['construction'], 'schedule_contract_sha256': sha(contract_path),
                        'arch_path': str(arch_path.relative_to(ROOT)), 'arch_sha256': sha(arch_path),
                        'self_check_sha256': sha(evidence_path), 'cases': 120, 'layers': rows}
            manifest_path = directory / 'manifest.json'
            write(manifest_path, manifest)
            summaries[f'{arch}/{size}'] = {'path': str(manifest_path.relative_to(ROOT)),
                                           'sha256': sha(manifest_path), 'layers': len(rows), 'cases': 120}
    write(ROOT / 'outputs/manifest/index.json', {'manifests': summaries, 'total_schedules': 144,
          'total_cases': 1440, 'examples': {arch: next(r for r in evidence['candidates']
          if r['arch'] == arch and r['size'] == '256k' and r['layer'] == 'layer_04_core_features_14') for arch in PES}})
    print('12 manifests; 144 validated schedules; 1440 sample cases; zero capacity or bridge violations')


if __name__ == '__main__':
    main()
