#!/usr/bin/env python3
"""Static khkw_split reachability; stdlib only, independent of compute.py.

Run normally to regenerate the three sibling reports. --verify compares every
real weight shape/core/sweep point with a literal block-coordinate flatten;
--check checks committed/generated report bytes without writing anything.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


TRACE_ROOT = Path('/home/ya867177/neuro_cache_bench_trace/out_real')
CORES = 16
WAYS = (1, 2, 4, 8, 16, 32, 64)
LEVELS = (('L1', 16384), ('L2', 524288))
LINE_BYTES = (16, 32, 64)
COUT_BLOCK = 4
WEIGHT_BYTES = 1


@dataclass(frozen=True, order=True)
class Shape:
    kh: int
    kw: int
    cin: int
    cout: int


@dataclass(frozen=True)
class Layer:
    name: str
    shape: Shape
    gemm: bool


@dataclass(frozen=True)
class Row:
    ways: int
    sets: int
    full: int
    feasible: int
    capacity_bound: int
    failures: tuple[str, ...]


def ceil_div(n, d):
    return (n + d - 1) // d


def load_layers(root=TRACE_ROOT):
    """Follow LAYER_SHAPES.md conventions; never visit out/ or out_second/."""
    paths = sorted(root.glob('*/*/meta.json'))
    if len(paths) != 6:
        raise ValueError(f'Expected all six real captures under {root}; got {len(paths)}')
    layers = []
    for path in paths:
        meta = json.loads(path.read_text(encoding='utf-8'))
        gemm = meta.get('gemm', {})
        if not set(gemm).issubset(meta['layers']):
            raise ValueError(f'{path}: GEMM names missing from layers')
        for name, dims in sorted(meta['layers'].items()):
            params = meta['layer_params'][name]
            cin, cout = dims[2], params['cout']
            is_gemm = name in gemm
            if is_gemm:
                # K is the recorded input channel extent; N is output features.
                fields = gemm[name]
                if (fields['K'], fields['N'], fields['M'], dims[4]) != (
                    cin, cout, dims[3], 1
                ):
                    raise ValueError(f'{path}: inconsistent GEMM M/K/N for {name}')
                kh = kw = 1
            else:
                kh = kw = params['kernel']
            if any(type(n) is not int or n <= 0 for n in (kh, kw, cin, cout)):
                raise ValueError(f'{path}: invalid weight shape for {name}')
            qualified = f'{path.parent.relative_to(root).as_posix()}/{name}'
            layers.append(Layer(qualified, Shape(kh, kw, cin, cout), is_gemm))
    return tuple(layers)


def owned_blocks(n_cout, core):
    width = ceil_div(n_cout, CORES)
    return min(core * width, n_cout), min((core + 1) * width, n_cout)


@lru_cache(maxsize=None)
def line_intervals(shape, cin_block, core):
    """Disjoint half-open intervals of valid lines owned by one core.

    Mirrors constructor strides and line_of in native source:
    src/lays/cachesim/native/src/layout/khkw_split.cpp, with kPosLoRadix=8
    from native/include/cachesim/layout/khkw_split.h. Flatten order is
    [pos_hi][cout_block][cin_block][pos_lo]. Full low-position slabs are
    contiguous; a ragged last slab has one short interval per CIN/COUT block.
    Padding in channel blocks shares a valid line; missing kernel positions
    do not create valid lines. In particular num_lines() is not a line count.
    """
    ni = ceil_div(shape.cin, cin_block)
    no = ceil_div(shape.cout, COUT_BLOCK)
    start, stop = owned_blocks(no, core)
    if start == stop:
        return ()
    positions = shape.kh * shape.kw
    low = min(8, positions)
    intervals = []
    for hi, pos in enumerate(range(0, positions, low)):
        width = min(low, positions - pos)
        base = hi * no * ni * low
        if width == low:
            intervals.append((base + start * ni * low, base + stop * ni * low))
        else:
            intervals.extend((base + b * low, base + b * low + width)
                             for b in range(start * ni, stop * ni))
    return tuple(intervals)


def residue_count(intervals, sets):
    """Union interval images modulo sets, splitting wrapped intervals."""
    spans = []
    for start, stop in intervals:
        length = stop - start
        if length >= sets:
            return sets
        begin = start % sets
        end = begin + length
        spans.append((begin, min(end, sets)))
        if end > sets:
            spans.append((0, end - sets))
    count = end = 0
    for begin, stop in sorted(spans):
        count += max(0, stop - max(begin, end))
        end = max(end, stop)
    return count


@lru_cache(maxsize=None)
def per_core(shape, line_bytes, sets):
    cin_block = line_bytes // (COUT_BLOCK * WEIGHT_BYTES)
    result = []
    for core in range(CORES):
        intervals = line_intervals(shape, cin_block, core)
        valid = sum(stop - start for start, stop in intervals)
        result.append((valid, residue_count(intervals, sets)))
    return tuple(result)


def sweep(layers, line_bytes, capacity_bytes):
    capacity = capacity_bytes // line_bytes
    rows = []
    for ways in WAYS:
        if ways > capacity:
            continue
        sets = capacity // ways
        full = capacity_bound = 0
        failures = []
        for layer in layers:
            cores = per_core(layer.shape, line_bytes, sets)
            minimum_lines = min(valid for valid, _ in cores)
            minimum_reach = min(reach for _, reach in cores)
            if minimum_lines < sets:
                capacity_bound += 1
            elif minimum_reach == sets:
                full += 1
            else:
                failures.append(layer.name)
        feasible = len(layers) - capacity_bound
        assert full + len(failures) == feasible
        rows.append(Row(ways, sets, full, feasible, capacity_bound, tuple(failures)))
    return tuple(rows)


def stable_threshold(rows):
    for i, row in enumerate(rows):
        # Explicit nonempty denominators prevent a vacuous all-covered claim.
        if all(r.feasible > 0 and r.full == r.feasible for r in rows[i:]):
            return row.ways
    return None


def render(layers, line_bytes):
    captures = Counter(layer.name.rsplit('/', 1)[0] for layer in layers)
    gemms = sum(layer.gemm for layer in layers)
    text = [
        f'# khkw_split associativity sweep: {line_bytes}B lines', '',
        'Generated by `python3 -B zoo/set_utilization/ways_sweep.py`.', '',
        f'Input: `{TRACE_ROOT}/*/*/meta.json` only; `out/` and `out_second/` excluded. '
        f'{len(layers)} layers across {len(captures)} captures: {gemms} GEMMs and '
        f'{len(layers) - gemms} convolutions; {len({x.shape for x in layers})} '
        'unique weight shapes (KH, KW, CIN, COUT).', '',
    ]
    text.extend(f'- `{name}`: {count} layers' for name, count in sorted(captures.items()))
    text.extend([
        '', f'Blocking: CIN={line_bytes // 4}, COUT=4, weight_bytes=1. '
        'All 16 cores are included, even empty cores (zero lines and zero reach). '
        'Core c owns COUT blocks [c*q, min((c+1)*q, n_cout_blocks)), clipped at '
        'n_cout_blocks, where q=ceil(n_cout_blocks/16).', '',
        'Shapes follow `neuro_cache_bench_trace/LAYER_SHAPES.md`: GEMM iff the '
        'layer name is in `meta["gemm"]`; KH=KW=1, CIN=layers[name][2]=K, '
        'COUT=layer_params[name]["cout"]=N (M/K/N checked). Other layers use '
        'KH=KW=layer_params.kernel, with the same CIN/COUT fields.', '',
        'The flatten mirrors `src/lays/cachesim/native/src/layout/khkw_split.cpp`: '
        '`low=min(8,KH*KW)`; '
        '`line=(((pos//low)*n_cout_blocks+cout_block)*n_cin_blocks+cin_block)*low'
        '+pos%low`, `pos=kh*KW+kw`, `set=line%sets`. Only valid kernel positions '
        'and channel blocks are counted; holes in the address span are excluded.', '',
        'Each layer is evaluated by its minimum per-core set reach. Capacity-bound '
        'means its minimum owned valid-line count is less than sets; such layers '
        'are excluded from both the feasible denominator and indexing failures. '
        'Full coverage requires every core to reach every set. Failure names are '
        'fully qualified as benchmark id/capture/layer; more than five failures '
        'are shown as a count.', '',
    ])
    for level, capacity in LEVELS:
        rows = sweep(layers, line_bytes, capacity)
        text.extend([
            f'## {level}: {capacity}B ({capacity // line_bytes} lines)', '',
            '| ways | sets | full coverage / feasible layers | capacity-bound layers | indexing failures |',
            '| ---: | ---: | ---: | ---: | --- |',
        ])
        for row in rows:
            failures = ('none' if not row.failures else
                        ', '.join(f'`{name}`' for name in row.failures)
                        if len(row.failures) <= 5 else f'{len(row.failures)} failures')
            text.append(f'| {row.ways} | {row.sets} | {row.full} / {row.feasible} | '
                        f'{row.capacity_bound} | {failures} |')
        threshold = stable_threshold(rows)
        text.extend(['', (
            f'Smallest stable sampled ways: **{threshold}**. At this and every '
            'subsequent sampled ways, every feasible layer has full coverage '
            '(with a nonzero feasible denominator at every point).'
            if threshold is not None else
            'No sampled ways begins a suffix in which every feasible layer has '
            'full coverage and every feasible denominator is nonzero.'
        ), ''])
    text.extend([
        '## Limits', '',
        'This is static potential set coverage, not occupancy, hit rate, or a '
        'trace-driven cache simulation. It assumes a core can access all valid '
        'weights in its COUT slice; spike sparsity, access order, replacement, '
        'prefetch, traffic, and contention are not modeled. L2 is evaluated per '
        'core, not as a union across cores. Coverage does not establish that '
        'lines fit simultaneously or that ways are balanced. Capacity-bound '
        'here is a reachability feasibility test, not a cache-fit claim. '
        'Only the six captured workloads and sampled ways 1, 2, 4, 8, 16, 32, '
        '64 (when within line capacity) are covered; the stable threshold makes '
        'no claim about untested ways or other shapes.', '',
        'Verification: `python3 -B zoo/set_utilization/ways_sweep.py --verify --check` '
        'checks all unique real weight shapes against brute-force flattening '
        'at every level/line-size/ways point, all 16 cores, and report bytes.', '',
    ])
    return '\n'.join(text).encode('utf-8')


def verify(layers):
    """Independent literal flatten at each valid block coordinate, no intervals."""
    shapes = sorted({layer.shape for layer in layers})
    comparisons = 0
    # Extra cases exercise ragged channels, empty cores, and several POS_HI slabs.
    extra_shapes = (Shape(1, 1, 3, 5), Shape(3, 3, 17, 65), Shape(3, 5, 9, 68),
                    Shape(4, 4, 7, 64), Shape(5, 5, 5, 128))
    for shape in [*shapes, *extra_shapes]:
        for line_bytes in LINE_BYTES:
            cb = line_bytes // 4
            ni, no = ceil_div(shape.cin, cb), ceil_div(shape.cout, 4)
            low = min(8, shape.kh * shape.kw)
            reference = []
            for core in range(16):
                width = (no + 15) // 16
                lines = set()
                for co in range(core * width, min((core + 1) * width, no)):
                    for ci in range(ni):
                        for kh in range(shape.kh):
                            for kw in range(shape.kw):
                                pos = kh * shape.kw + kw
                                # Literal mirror of native khkw_split.cpp::line_of.
                                lines.add((pos // low) * no * ni * low
                                          + co * ni * low + ci * low + pos % low)
                reference.append(lines)
            for _, capacity in LEVELS:
                for ways in WAYS:
                    if ways > capacity // line_bytes:
                        continue
                    sets = capacity // line_bytes // ways
                    expected = tuple((len(lines), len({x % sets for x in lines}))
                                     for lines in reference)
                    actual = per_core(shape, line_bytes, sets)
                    assert actual == expected, (shape, line_bytes, sets, actual, expected)
                    comparisons += CORES
    assert stable_threshold((Row(1, 1, 0, 0, 1, ()),)) is None
    assert stable_threshold((Row(1, 2, 0, 0, 1, ()), Row(2, 1, 1, 1, 0, ()))) == 2
    print(f'Verified {len(shapes)} real weight shapes + {len(extra_shapes)} edge shapes; '
          f'{comparisons} per-core comparisons across all sweep points.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='also check brute-force flatten')
    parser.add_argument('--check', action='store_true', help='compare reports without writing')
    args = parser.parse_args()
    layers = load_layers()
    if args.verify:
        verify(layers)
    for line_bytes in LINE_BYTES:
        content = render(layers, line_bytes)
        path = Path(__file__).resolve().with_name(f'WAYS_COVERAGE_{line_bytes}B.md')
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(f'Stale or missing report: {path}')
            print(f'Checked {path.name}: {len(content)} deterministic bytes')
        else:
            path.write_bytes(content)
            print(f'Wrote {path.name}: {len(content)} bytes')


if __name__ == '__main__':
    main()
