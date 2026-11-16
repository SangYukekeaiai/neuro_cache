"""Unique convolution weights needed by a sample, independent of prices."""
import numpy as np


def needed_lines(sample, kernel):
    """Return KH×KW×CIN demand for the shared stride-one/same-padding contract."""
    if sample.ndim != 4 or kernel not in (1, 3):
        raise ValueError('expected [T,CIN,H,W] sample and kernel 1 or 3')
    _, channels, height, width = sample.shape
    result = np.zeros((kernel, kernel, channels), dtype=bool)
    pad = (kernel - 1) // 2
    for kh in range(kernel):
        for kw in range(kernel):
            h0, h1 = max(0, kh-pad), min(height, height+kh-pad)
            w0, w1 = max(0, kw-pad), min(width, width+kw-pad)
            result[kh, kw] = np.any(sample[:, :, h0:h1, w0:w1], axis=(0, 2, 3))
    return result


def native_demand(trace):
    """Count physical words and deduplicate the native bridge's address spans."""
    dims = trace.workload_dims
    used = np.zeros(tuple(dims[d] for d in ('KH', 'KW', 'CIN', 'COUT')), dtype=bool)
    records = words = 0
    for tile in trace.tiles:
        for tick in tile.ticks:
            for core in tick.cores:
                if core.core_id != 0:
                    raise ValueError('Figure 1 permits exactly one node')
                for kh, kw, cin, start, end in core.weight_addresses:
                    if not (0 <= kh < dims['KH'] and 0 <= kw < dims['KW'] and
                            0 <= cin < dims['CIN'] and 0 <= start < end <= dims['COUT']):
                        raise ValueError('native weight address outside problem extent')
                    used[kh, kw, cin, start:end] = True
                    records += 1
                    words += end-start
    return used, records, words
