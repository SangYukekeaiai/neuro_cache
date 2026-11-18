"""Figure 1 spikinglm extension: LoAS-only schedules, manifests and cases.

User call 2026-11-17 (urgent): replace the PTB panel with spikinglm on the
LoAS architecture. The pinned residency contract, arch yamls, sizes and
samples stay exactly as in schedule_spec; only the capture
(A07/spikinglm_t4_T4_n500) and the layer set differ. Layers follow the
canonical fig12 scope rule (zoo/fig12_edp/docs/workload_layer_scope.md):
the 48 kept attention GEMMs; MLP dense layers are skipped.

Outputs (never touching the vgg16 artifacts):
  outputs/self_checks/schedule_contract_spikinglm/verification.json
  outputs/manifest_spikinglm/loas_{128k,256k,512k,1m}/{manifest.json,schedules/}
  configs/cases_spikinglm.json          (index 0..1919)

Run from the repo root:
  PYTHONPATH=src:. conda run -n fig12-archx python -B \
      zoo/fig1_energy_profiling/src/spikinglm_ext.py
"""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path

from lays.scheduler.artifact import ScheduleArtifact
from lays.weight_trace_gen.trace import build_workload_from_trace
from zoo.wt500_fig3cfg.gen_inputs import check_bridge_compatibility
from zoo.fig12_edp.demo.all_bench.layer_scope import kept
from check_schedule_contract import inspect
from schedule_spec import ROOT, SIZES, PES

ARCH = 'loas'
CAPTURE_REL = 'A07/spikinglm_t4_T4_n500'
SAMPLES = list(range(10))
OUT = ROOT / 'outputs/self_checks/schedule_contract_spikinglm'
MANIFEST_ROOT = ROOT / 'outputs/manifest_spikinglm'


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
    layers = [name for name in meta['layers'] if kept(name)]
    assert len(layers) == 48, (len(layers), layers[:3])

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
                'scope': 'LoAS-only spikinglm extension; same pinned analytic contract',
                'kept_layers': layers,
                'excluded_layers': [n for n in meta['layers'] if not kept(n)],
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
        assert len(manifest_rows) == 48
        manifest = {'arch': ARCH, 'size': size, 'weight_capacity_bytes': capacity,
                    'state_buffers': arch_manifest['state_buffers'],
                    'capture_relative_dir': CAPTURE_REL,
                    'meta_sha256': evidence['meta_sha256'], 'samples': SAMPLES,
                    'kept_layers': layers, 'excluded_layers': evidence['excluded_layers'],
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
    write(ROOT / 'configs/cases_spikinglm.json', cases)
    print(f'{len(summaries)} manifests; {len(rows)} validated schedules; '
          f'{len(cases)} sample cases; zero capacity or bridge violations')


if __name__ == '__main__':
    main()
