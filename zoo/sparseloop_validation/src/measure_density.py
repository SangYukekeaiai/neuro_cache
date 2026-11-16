"""Read-only capture measurement and lossless snapshots of the selected samples."""
import csv
from pathlib import Path
import numpy as np


def measure(trace_root, layers, samples, output, record_source):
    rows = []
    (output / 'traces').mkdir(exist_ok=True)
    for layer in layers:
        source = Path(trace_root) / (layer + '.npy')
        source_sha = record_source(source)
        array = np.load(source, mmap_mode='r', allow_pickle=False)
        assert array.ndim == 5 and array.dtype == np.uint8, (layer, array.shape, array.dtype)
        selected = np.asarray(array[:, samples, :, :, :])
        assert np.all((selected == 0) | (selected == 1)), layer
        dest = output / 'traces' / (layer + '.npz')
        np.savez_compressed(dest, spikes=selected, sample_indices=np.array(samples))
        for index, sample in enumerate(samples):
            value = selected[:, index]
            nnz = int(np.count_nonzero(value))
            row = dict(layer=layer, sample=sample, timesteps=value.shape[0],
                       channels=value.shape[1], height=value.shape[2], width=value.shape[3],
                       nonzero=nnz, elements=value.size, density=nnz/value.size,
                       temporal_union_nonzero=int(np.count_nonzero(np.any(value, axis=0))),
                       source_sha256=source_sha)
            for t in range(value.shape[0]):
                row[f'nonzero_t{t}'] = int(np.count_nonzero(value[t]))
            rows.append(row)
        print('density', layer, len(samples), flush=True)
    with (output / 'measured_density.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return rows
