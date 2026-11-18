"""Figure 1 resnet19 extension: LoAS-only schedules, manifests and cases.

User call 2026-11-17 (urgent): add a resnet19 panel to Figure 1 on the LoAS
architecture, campaign on AWS. The pinned residency contract, arch yamls,
sizes and samples stay exactly as in schedule_spec; only the capture
(B09/loas_resnet19_T4_n500) and the layer set differ. The replayable set is
the 13 stride-1 convolutions of zoo/fig12_edp/docs/workload_layer_scope.md;
build_workload_from_trace itself rejects the stride-2 and shortcut layers.

Outputs (never touching the vgg16 or spikinglm artifacts):
  outputs/self_checks/schedule_contract_resnet19/verification.json
  outputs/manifest_resnet19/loas_{128k,256k,512k,1m}/{manifest.json,schedules/}
  configs/cases_resnet19.json           (index 0..519)

Run from the repo root:
  PYTHONPATH=src:.:zoo/fig1_energy_profiling/src \
      conda run -p /work/hdd/bebv/yyu9/fig12_full500_deltaai/env \
      python -B zoo/fig1_energy_profiling/src/resnet19_ext.py
"""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path

from lays.scheduler.artifact import ScheduleArtifact
from lays.weight_trace_gen.trace import build_workload_from_trace
from zoo.wt500_fig3cfg.gen_inputs import check_bridge_compatibility
from check_schedule_contract import inspect
from schedule_spec import ROOT, SIZES

ARCH = 'loas'
CAPTURE_REL = 'B09/loas_resnet19_T4_n500'
SAMPLES = list(range(10))
OUT = ROOT / 'outputs/self_checks/schedule_contract_resnet19'
MANIFEST_ROOT = ROOT / 'outputs/manifest_resnet19'
# canonical replayable set, zoo/fig12_edp/docs/workload_layer_scope.md (B09)
EXPECTED = [
    'layer_02_core_layer1_0_conv2',
    'layer_04_core_layer1_1_conv1', 'layer_05_core_layer1_1_conv2',
    'layer_06_core_layer1_2_conv1', 'layer_07_core_layer1_2_conv2',
    'layer_09_core_layer2_0_conv2',
    'layer_11_core_layer2_1_conv1', 'layer_12_core_layer2_1_conv2',
    'layer_13_core_layer2_2_conv1', 'layer_14_core_layer2_2_conv2',
    'layer_16_core_layer3_0_conv2',
    'layer_18_core_layer3_1_conv1', 'layer_19_core_layer3_1_conv2',
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path,
                        default=Path('/work/nvme/bebv/yyu9/input_trace_delta') / CAPTURE_REL)
    args = parser.parse_args()
    meta = json.loads((args.trace / 'meta.json').read_text())
    layers, excluded = [], []
    for name in meta['layers']:
        try:
            build_workload_from_trace(meta, name)
        except ValueError:
            excluded.append(name)
            continue
        layers.append(name)
    assert layers == EXPECTED, (layers, excluded)

    # inspect() writes its workload yaml under the vgg16 contract-check dir
    (ROOT / 'outputs/self_checks/schedule_contract/workloads').mkdir(
        parents=True, exist_ok=True)
    rows = []
    for size in SIZES:
        for layer in layers:
            problem = build_workload_from_trace(meta, layer)['problem']
            row = inspect(ARCH, layer, problem, ROOT / 'arch' / f'{ARCH}_{size}.yaml')
            if row['capacity_violations']:
                raise ValueError((layer, size, row['capacity_violations']))
            rows.append({**row, 'size': size})
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {'status': 'PASS', 'arch': ARCH, 'capture_relative_dir': CAPTURE_REL,
                'scope': 'LoAS-only resnet19 extension; same pinned analytic contract',
                'kept_layers': layers, 'excluded_layers': excluded,
                'planned_cases': len(rows) * len(SAMPLES), 'candidate_count': len(rows),
                'capacity_conflict_count': 0, 'candidates': rows,
                'meta_sha256': sha(args.trace / 'meta.json')}
    write(OUT / 'verification.json', evidence)

    contract_path = ROOT / 'configs/schedule_contract.json'  # unchanged pinned contract
    arch_manifest = json.loads((ROOT / 'configs/arch_manifest.json').read_text())
    cases = []
    summaries = {}
    for size, capacity in SIZES.items():
        directory = MANIFEST_ROOT / f'{ARCH}_{size}'
        arch_path = ROOT / 'arch' / f'{ARCH}_{size}.yaml'
        manifest_rows = []
        for row in [r for r in rows if r['size'] == size]:
            artifact = ScheduleArtifact(
                arch=ARCH, trace_dir=args.trace.name, layer_name=row['layer'],
                workload={'problem': row['problem']},
                result={'has_solution': True, 'status': 'ANALYTIC_VALIDATED',
                        'strategy': row['strategy'],
                        'configs': {'arch': str(arch_path.relative_to(ROOT.parents[1]))},
                        'capacity_bytes': row['capacity_bytes'],
                        'tile_bytes': row['tile_bytes']},
                dram_num_steps=row['tiles_checked'], mode='fig1_pinned',
                arch_yaml_sha256=sha(arch_path), mapspace_yaml_sha256=sha(contract_path))
            path = directory / 'schedules' / (row['layer'] + '.json')
            write(path, asdict(artifact))
            gate = check_bridge_compatibility(path, ARCH)
            if not gate['passed']:
                raise ValueError(f'{path}: {gate}')
            manifest_rows.append({k: row[k] for k in (
                'layer', 'resident_cout', 'spatial_cout', 'tile_bytes', 'weight_loads',
                'weight_transfer_bytes', 'compulsory_weight_bytes',
                'traffic_multiple_of_compulsory')})
            manifest_rows[-1].update(schedule=str(path.relative_to(ROOT)),
                                     schedule_sha256=sha(path), native_bridge=gate)
        assert len(manifest_rows) == len(EXPECTED)
        manifest = {'arch': ARCH, 'size': size, 'weight_capacity_bytes': capacity,
                    'state_buffers': arch_manifest['state_buffers'],
                    'capture_relative_dir': CAPTURE_REL,
                    'meta_sha256': evidence['meta_sha256'], 'samples': SAMPLES,
                    'kept_layers': layers, 'excluded_layers': excluded,
                    'construction': 'direct analytic; no optimizer or post-solve permutation',
                    'schedule_contract_sha256': sha(contract_path),
                    'arch_path': str(arch_path.relative_to(ROOT)), 'arch_sha256': sha(arch_path),
                    'self_check_sha256': sha(OUT / 'verification.json'),
                    'cases': len(manifest_rows) * len(SAMPLES), 'layers': manifest_rows}
        manifest_path = directory / 'manifest.json'
        write(manifest_path, manifest)
        summaries[f'{ARCH}/{size}'] = {'path': str(manifest_path.relative_to(ROOT)),
                                       'sha256': sha(manifest_path),
                                       'layers': len(manifest_rows),
                                       'cases': len(manifest_rows) * len(SAMPLES)}
        for layer in layers:
            for sample in SAMPLES:
                cases.append({'index': len(cases), 'arch': ARCH, 'size': size,
                              'layer': layer, 'sample': sample,
                              'manifest': str(manifest_path.relative_to(ROOT))})
    write(MANIFEST_ROOT / 'index.json',
          {'manifests': summaries, 'total_schedules': len(rows),
           'total_cases': len(cases)})
    write(ROOT / 'configs/cases_resnet19.json', cases)
    print(f'{len(summaries)} manifests; {len(rows)} validated schedules; '
          f'{len(cases)} sample cases; zero capacity or bridge violations')


if __name__ == '__main__':
    main()
