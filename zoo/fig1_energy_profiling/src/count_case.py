"""One isolated Figure 1 native replay, NoC count and ideal-demand checkpoint."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import numpy as np

from lays.nocsim.step_cycles import save_step_cycles
from lays.weight_trace_gen.weight_trace import load_schedule, reconstruct_samples, node_level_spatial_product
from zoo.fig12_edp.nocsim.driver import run_case as run_noc
from contracts import require_no_gb
from ideal_counts import needed_lines, native_demand
from schedule_spec import ROOT

REPO = ROOT.parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.part')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run(manifest_path, layer, sample, trace_root, output_root):
    manifest = json.loads(manifest_path.read_text())
    row, = [r for r in manifest['layers'] if r['layer'] == layer]
    if sample not in manifest['samples']:
        raise ValueError('sample outside approved range')
    arch = manifest['arch']; size = manifest['size']
    directory = trace_root / manifest['capture_relative_dir']
    if digest(directory/'meta.json') != manifest['meta_sha256']:
        raise ValueError('capture metadata differs from schedule')
    schedule_path = ROOT / row['schedule']; arch_path = ROOT / manifest['arch_path']
    if digest(schedule_path) != row['schedule_sha256'] or digest(arch_path) != manifest['arch_sha256']:
        raise ValueError('schedule or architecture changed')
    out = (output_root / arch / size / f'sample_{sample:03d}' / layer).resolve()
    if not out.is_relative_to(ROOT):
        raise ValueError('Figure 1 output must stay inside its own tree')
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((directory/'meta.json').read_text())
    capture = np.load(directory/(layer+'.npy'), mmap_mode='r')
    if list(capture.shape) != meta['layers'][layer]:
        raise ValueError('capture shape differs from metadata')
    selected = np.ascontiguousarray(capture[:, sample:sample+1])
    layers = list(meta['layers']); density_layer = layers[min(layers.index(layer)+1, len(layers)-1)]
    following = np.load(directory/(density_layer+'.npy'), mmap_mode='r')
    density_sample = np.ascontiguousarray(following[:, sample])
    module = importlib.import_module(f'lays.weight_trace_gen.{arch}.native_bridge')
    eventsim = REPO/'src/lays/nocsim/eventsim/eventsim'
    inputs = {'manifest_sha256': digest(manifest_path), 'schedule_sha256': digest(schedule_path),
              'arch_sha256': digest(arch_path), 'capture_sample_sha256': hashlib.sha256(selected.tobytes()).hexdigest(),
              'density_sample_sha256': hashlib.sha256(density_sample.tobytes()).hexdigest(),
              'generator_sha256': digest(module._BINARY), 'eventsim_sha256': digest(eventsim),
              'worker_sha256': digest(Path(__file__)), 'ideal_counter_sha256': digest(ROOT/'src/ideal_counts.py'),
              'sample': sample}
    receipt = out/'receipt.json'
    if receipt.exists():
        old = json.loads(receipt.read_text())
        if old['inputs'] != inputs or any(digest(out/n) != h for n,h in old['artifacts'].items()):
            raise ValueError('committed Figure 1 case changed')
        return {'status': 'resumed', 'path': str(out)}
    if any(out.iterdir()):
        out.rename(out.with_name(out.name + '.incomplete_' + str(time.time_ns())))
        out.mkdir()
    start = time.monotonic()
    scratch = out/'scratch'; scratch.mkdir(exist_ok=True)
    tempfile.tempdir = str(scratch)
    artifact, _, tiles = load_schedule(schedule_path)
    dims = artifact.workload['problem']
    options = {'wave_width': node_level_spatial_product(artifact.result['strategy'])} if arch == 'gustavsnn' else {}
    native, = reconstruct_samples(arch, selected, tiles, [0], artifact.trace_dir, layer,
                                  dims, artifact.dram_num_steps, **options)
    native.sample_idx = sample
    used, records, words = native_demand(native)
    oracle = needed_lines(selected[:, 0], dims['KH'])
    if not np.array_equal(used, np.broadcast_to(oracle[..., None], used.shape)):
        raise ValueError('native demand differs from the independent unique-weight oracle')
    ideal = {'needed_weight_words': int(used.sum()), 'needed_weight_bytes': int(used.sum()),
             'weight_bytes_per_word': 1, 'native_records': records, 'native_weight_words': words,
             'oracle_equal': True, 'definition': 'union of native kh,kw,cin,cout addresses, independently checked from input spike support'}
    step_path = out/'step_cycles.json.gz'; save_step_cycles(native, step_path)
    del native, used
    # The campaign's GustavSNN counter fixes COUT=2; the shared convolution
    # primitive accepts the explicitly approved Figure 1 PE fanout instead.
    sys.path.insert(0, str(REPO/'zoo/fig12_edp/counts'))
    import spinalflow_counts
    import ptb_counts
    density = float(np.count_nonzero(density_sample)/density_sample.size)
    kwargs = dict(cout=dims['COUT'], kernel=dims['KH'], cout_n=row['spatial_cout'])
    if arch == 'gustavsnn':
        counts = spinalflow_counts.count_sample(selected, 0, **kwargs)
        counts.update(L=counts['O'], O=counts['O']*density, d_out=density,
                      R_g=counts['R'], W_o=counts['O']*density)
    else:
        counts = ptb_counts.count_sample(selected, 0, d_out=density, **kwargs)
        counts['W_o'] = counts['O']/counts['T']
    counts.update(COUT=dims['COUT'], kernel=dims['KH'], resident_cout=row['resident_cout'],
                  native_records=records, native_weight_words=words,
                  density_layer=density_layer, O_source='next_layer_input_density',
                  cout_n_semantics='physical COUT PE fanout, distinct from weight residency')
    save(out/'counts.json', counts); save(out/'ideal_counts.json', ideal)
    save(out/'case.json', {'arch': arch, 'size': size, 'sample': sample, 'layer': layer,
                         'trace_relative_dir': manifest['capture_relative_dir']})
    noc = run_noc(schedule_path, arch, output_dir=out/'noc', steps_path=step_path,
                  arch_path=arch_path, eventsim_binary=eventsim)
    require_no_gb(noc)
    if noc['dram_payload_bytes'] != row['weight_transfer_bytes']:
        raise ValueError('NoC weight traffic differs from the pinned schedule self-check')
    save(out/'generation.json', {'generator_api': 'lays.weight_trace_gen.weight_trace.reconstruct_samples',
         'generator_binary': str(module._BINARY), 'generator_sha256': inputs['generator_sha256'],
         'capture': str(directory/(layer+'.npy')), 'sample': sample, 'schedule': str(schedule_path),
         'step_cycles': str(step_path), 'step_cycles_sha256': digest(step_path),
         'records': records, 'native_weight_words': words, 'wall_seconds': time.monotonic()-start,
         'trace_retention': 'native address records transient; durable step cycles and native-demand summary retained'})
    names = ['case.json', 'counts.json', 'ideal_counts.json', 'step_cycles.json.gz',
             'generation.json', 'noc/result.json', 'noc/tc.csv']
    save(receipt, {'inputs': inputs, 'artifacts': {n:digest(out/n) for n in names},
                   'status': 'complete', 'zero_gb': True, 'native_demand_oracle_equal': True,
                   'price_free': True, 'wall_seconds': time.monotonic()-start})
    shutil.rmtree(scratch)
    return {'status': 'complete', 'path': str(out), 'cycles': noc['total_cycles']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--layer', required=True)
    parser.add_argument('--sample', type=int, required=True)
    parser.add_argument('--trace-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT/'outputs/counts')
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.layer, args.sample, args.trace_root, args.out)))
