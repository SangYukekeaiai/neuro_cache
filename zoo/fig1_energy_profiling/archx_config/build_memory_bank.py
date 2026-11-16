"""Run byte-identical FN-CACTI code in a Figure 1-local runtime directory."""
from collections import OrderedDict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
SOURCE = REPO/'zoo/archx/src/archx/interface/cacti_fn'
RUNTIME = HERE/'fn_cacti_runtime'
OUTPUT = HERE/'memory'
CAVEAT = ('FN-CACTI physical memory model, 7nm FinFET at0.7V; the bundled '
          'finfet_7nm_0p7.xml is a first-order extrapolation of the0.45V device. '
          'This is not an SRAM synthesis result. One read and one write port, one bank.')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+'\n')


def main():
    OUTPUT.mkdir(exist_ok=True)
    binary = 'cacti-'+platform.system()+'-'+platform.machine()
    paths = [SOURCE/'cacti_fn.py', SOURCE/'sram.cfg', SOURCE/'include/cacti_fn'/binary]
    paths += [p for p in (SOURCE/'include/cacti_fn/xmls').rglob('*') if p.is_file()]
    originals = {str(p.relative_to(SOURCE)): sha(p) for p in paths}
    for path in paths:
        target = RUNTIME/path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or sha(target) != sha(path):
            shutil.copy2(path, target)
        assert sha(target) == sha(path)
    spec = importlib.util.spec_from_file_location('fig1_local_cacti_fn', RUNTIME/'cacti_fn.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    manifest_path = ROOT/'configs/arch_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    queries = {}
    for name, entry in manifest['variants'].items():
        import yaml
        arch = yaml.safe_load((ROOT/entry['path']).read_text())['arch']
        node = arch['storage'][0]
        width = node['pe']['num_pes']*arch['bitwidths']['BW_WEIGHT']
        capacity = node['local_buffer']['entries']['weight']
        queries[f'weight_{capacity}_w{width}'] = {'width': width, 'depth': capacity*8//width}
    fixed = manifest['state_buffers']['fixed_capacity_bytes']
    queries.update(psum_fixed={'width': 16, 'depth': fixed['psum']//2},
                   vmem_fixed={'width': 32, 'depth': fixed['vmem']//4},
                   ptb_spike_buffer={'width': 32, 'depth': 256})
    results = {}
    for name, dimensions in queries.items():
        directory = OUTPUT/name; directory.mkdir(exist_ok=True)
        request = OrderedDict({'class': 'sram', 'technology': 7, 'frequency': 500, 'bank': 1, **dimensions})
        data = module.query(name, 'cacti_fn', request, output_dir=str(directory.resolve()))
        report, = list(directory.glob('*.rpt'))
        config, = list(directory.glob('*.cfg'))
        _, _, _, _, fmax = module.parse_report_sram(report)
        results[name] = {'query': dict(request), 'metrics': data, 'fmax_MHz': fmax,
                         'meets_500MHz': fmax >= 500, 'assumption': CAVEAT,
                         'source_report': str(report.relative_to(ROOT)), 'source_report_sha256': sha(report),
                         'source_config': str(config.relative_to(ROOT)), 'source_config_sha256': sha(config)}
        print(name, 'fmax_MHz', fmax, flush=True)
    if any(sha(SOURCE/p) != h for p,h in originals.items()):
        raise ValueError('shared memory-model source changed')
    save(OUTPUT/'memory_prices.json', {'queries': results, 'assumption': CAVEAT})
    save(OUTPUT/'manifest.json', {'source': str(SOURCE), 'source_sha256': originals,
        'runtime_copy': str(RUNTIME.relative_to(ROOT)), 'runtime_code_byte_identical': True,
        'side_effects': 'FN-CACTI pcacti_report.txt is confined to this runtime copy; no shared source or package file written',
        'arch_manifest_sha256': sha(manifest_path), 'builder_sha256': sha(Path(__file__)),
        'memory_prices_sha256': sha(OUTPUT/'memory_prices.json'),
        'below_500MHz': [n for n,r in results.items() if not r['meets_500MHz']],
        'source_unchanged': True, 'queries': len(results)})


if __name__ == '__main__':
    main()
