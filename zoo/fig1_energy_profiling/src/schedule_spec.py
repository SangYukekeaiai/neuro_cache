"""Pinned Figure 1 residency and traversal, independent of prices or a solver."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE = Path('/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_vgg16_T4_n500')
PES = {'loas': 16, 'ptb': 8, 'gustavsnn': 8}
SIZES = {'128k': 131072, '256k': 262144, '512k': 524288, '1m': 1048576}
STATE_MARGIN = 1.25


def resident(problem, arch, capacity, weight_bits):
    per_channel = problem['KH'] * problem['KW'] * problem['CIN'] * weight_bits // 8
    candidates = [c for c in range(PES[arch], problem['COUT'] + 1, PES[arch])
                  if problem['COUT'] % c == 0 and per_channel * c <= capacity]
    if not candidates:
        raise ValueError(f'{arch}: no full-kernel/full-CIN tile fits {capacity} bytes')
    tile = {k: v for k, v in problem.items() if k != 'shape'}
    tile['COUT'] = max(candidates)
    if arch == 'gustavsnn':
        tile['HO'] = tile['WO'] = tile['T'] = 1
    else:
        tile['HO'] = tile['WO'] = 1
    return tile


def strategy(problem, tile, arch):
    order = ['COUT', 'HO', 'WO', 'T'] if arch == 'gustavsnn' else ['HO', 'WO', 'COUT']
    factors = {d: problem[d] // tile[d] for d in order}
    return {
        'NodeLevel': {'spatial_split': {'factors': [{'dim': 'COUT', 'size': PES[arch]}]},
                      'resident_dimensions': tile},
        'NoCLevel': {'temporal_permutation': {'loops': []}, 'spatial_splitting': {'loops': []}},
        'DRAM': {'temporal_permutation': {'loops': [
            {'dim': d, 'size': factors[d]} for d in order if factors[d] > 1]}}}
