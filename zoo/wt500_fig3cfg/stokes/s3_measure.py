#!/usr/bin/env python3
"""Build the WT500 S3 schedule/record digest and weighted shard list."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pathlib
import subprocess
import sys
from collections import defaultdict

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUTPUTS = REPO / 'zoo/wt500_fig3cfg/outputs'
MANIFEST_PATH = OUTPUTS / 'manifest.json'
TRACE_ROOT = pathlib.Path('/work/nvme/bebv/yyu9/input_trace_delta')
STOKES_DIR = HERE
HELPER_SOURCE = HERE / 'prosperity_count.cpp'
HELPER = pathlib.Path('/tmp/wt500_s3_prosperity_count')
DIMS = ('KH', 'KW', 'CIN', 'COUT', 'HO', 'WO', 'T')
ARCH_ORDER = {'loas': 0, 'ptb': 1, 'prosperity': 2, 'spinalflow': 3, 'gustavsnn': 4}
SAMPLE_COUNT = 500
MACHINE_CORES = 16 * 4
SHARD_TARGET_RECORDS = 50_000_000_000
HEAVY_THRESHOLD_RECORDS_PER_SAMPLE = 50_000_000
NATIVE_OUT_BYTES_PER_RECORD = 89
NATIVE_TMPFS_GIB = 94


def product(values):
    result = 1
    for value in values:
        result *= int(value)
    return result


def totals(loops):
    result = defaultdict(lambda: 1)
    for entry in loops or []:
        result[entry['dim']] *= int(entry['size'])
    return dict(result)


def schedule_info(record):
    problem = record['workload']['problem']
    strategy = record['artifact']['result']['strategy']
    noc = strategy['NoCLevel']
    spatial = defaultdict(lambda: 1)
    for entry in noc.get('spatial_splitting', {}).get('loops', []):
        spatial[entry['dim']] *= int(entry['size'])
    noc_totals = totals(noc.get('temporal_permutation', {}).get('loops', []))
    dram_totals = totals(strategy['DRAM']['temporal_permutation'].get('loops', []))
    node_bound = {}
    for dim in DIMS:
        divisor = dram_totals.get(dim, 1) * noc_totals.get(dim, 1) * spatial.get(dim, 1)
        value = int(problem[dim]) // divisor
        if value < 1:
            value = 1
        if int(problem[dim]) % divisor:
            raise RuntimeError(f'{record["arch"]}/{record["layer"]}: nonintegral {dim} tile divisor {divisor}')
        node_bound[dim] = value
    noc_steps = product(noc_totals.values())
    dram_steps = int(record['artifact']['dram_num_steps'])
    node_cores = product(spatial.values())
    tile_count = dram_steps * noc_steps * node_cores
    wave_width = None
    if record['arch'] == 'gustavsnn':
        wave_width = product(
            int(entry['size'])
            for entry in strategy['NodeLevel']['spatial_split']['factors']
        )
    cout = int(problem['COUT'])
    if cout % node_bound['COUT']:
        raise RuntimeError(f'{record["arch"]}/{record["layer"]}: COUT does not divide tile bound')
    return {
        'problem': problem,
        'node_bound': node_bound,
        'dram_steps': dram_steps,
        'noc_steps': noc_steps,
        'frame_count': dram_steps * noc_steps,
        'tile_count': tile_count,
        'machine_cores': MACHINE_CORES,
        'cout_slabs': cout // node_bound['COUT'],
        'wave_width': wave_width,
    }


def neighbourhood_counts(path: pathlib.Path, kernel: int):
    """Return exact LoAS-line and event sums for every sample in one capture."""
    trace = np.load(path, mmap_mode='r')
    t, batch, channels, height, width = map(int, trace.shape)
    active = np.asarray(trace).any(axis=0)
    line_counts = np.zeros(batch, dtype=np.int64)
    event_counts = np.zeros(batch, dtype=np.int64)
    padding = (kernel - 1) // 2
    for kh in range(kernel):
        ih0 = max(0, kh - padding)
        ih1 = min(height, height + kh - padding)
        oh0 = ih0 - kh + padding
        oh1 = oh0 + (ih1 - ih0)
        for kw in range(kernel):
            iw0 = max(0, kw - padding)
            iw1 = min(width, width + kw - padding)
            ow0 = iw0 - kw + padding
            ow1 = ow0 + (iw1 - iw0)
            # One independent (tap, channel, output-position) line per
            # non-silent tap.  The destination coordinates are only used to
            # make the padding convention explicit; the sum is over sources.
            line_counts += active[:, :, ih0:ih1, iw0:iw1].sum((1, 2, 3), dtype=np.int64)
            event_counts += np.asarray(trace[:, :, :, ih0:ih1, iw0:iw1]).sum(
                (0, 2, 3, 4), dtype=np.int64
            )
    return line_counts, event_counts, tuple(map(int, trace.shape))


def prosperity_counts(path: pathlib.Path, info):
    """Run the native Prosperity row/prefix walk in count-only form."""
    problem = info['problem']
    nb = info['node_bound']
    trace = np.load(path, mmap_mode='r')
    if int(problem['KH']) == 1 and int(problem['KW']) == 1:
        # The one-bit prefix walk collapses to one fetch per input channel
        # that fires anywhere in the realized (HO, WO, T) tile.  Keep the
        # exact tile partition, but use NumPy's streaming reduction rather
        # than reimplementing the native row sort for every 1x1 row.
        totals = np.zeros(int(trace.shape[1]), dtype=np.int64)
        for t0 in range(0, int(trace.shape[0]), int(nb['T'])):
            active = np.asarray(trace[t0:t0 + int(nb['T'])]).any(axis=0)
            for h0 in range(0, int(trace.shape[3]), int(nb['HO'])):
                for w0 in range(0, int(trace.shape[4]), int(nb['WO'])):
                    for c0 in range(0, int(trace.shape[2]), int(nb['CIN'])):
                        block = active[:, c0:c0 + int(nb['CIN']), h0:h0 + int(nb['HO']), w0:w0 + int(nb['WO'])]
                        totals += block.any(axis=(2, 3)).sum(axis=1, dtype=np.int64)
        return totals * int(info['cout_slabs']), tuple(map(int, trace.shape))
    command = [
        str(HELPER), str(path), str(problem['KH']), str(problem['KW']),
        str(nb['HO']), str(nb['WO']), str(nb['CIN']), str(nb['T']),
        str(nb['COUT']),
    ]
    text = subprocess.check_output(command, text=True)
    values = np.fromstring(text, sep='\n', dtype=np.int64)
    if values.size != int(trace.shape[1]):
        raise RuntimeError(f'{path}: helper returned {values.size}, expected {trace.shape[1]} samples')
    return values * int(info['cout_slabs']), tuple(map(int, trace.shape))


def pair_sort_key(row):
    return (
        int(row['estimated_records_per_sample']),
        ARCH_ORDER[row['arch']],
        row['trace_dir'],
        row['layer'],
    )


def shard_rows(rows):
    # This is a planning weight for all 500 samples. C01's two event-stream
    # architectures are always dedicated; the same is true of any layer in
    # the Prosperity-sized heavy band. The remaining rows are packed in rank
    # order against a 50e9-record target for the 2--4 hour Stokes shard budget.
    target = SHARD_TARGET_RECORDS
    shards = []
    current = []
    current_weight = 0

    def flush():
        nonlocal current, current_weight
        if not current:
            return
        shards.append((current, current_weight))
        current = []
        current_weight = 0

    for row in rows:
        weight = int(row['records_sum_500'])
        explicit_heavy = (
            (row['arch'] in {'spinalflow', 'gustavsnn'} and row['trace_dir'].startswith('sma_azo_vgg_'))
            or int(row['estimated_records_per_sample']) >= HEAVY_THRESHOLD_RECORDS_PER_SAMPLE
        )
        if explicit_heavy:
            flush()
            shards.append(([row], weight))
            continue
        if current and current_weight + weight > target:
            flush()
        current.append(row)
        current_weight += weight
    flush()

    out = []
    for index, (members, weight) in enumerate(shards, 1):
        out.append({
            'shard_id': f'shard_{index:04d}',
            'pairs': [
                {
                    'rank': int(row['rank']),
                    'arch': row['arch'],
                    'benchmark': row['trace_dir'],
                    'layer': row['layer'],
                    'estimated_records_per_sample': int(row['estimated_records_per_sample']),
                    'estimated_records': int(row['records_sum_500']),
                }
                for row in members
            ],
            'estimated_records': int(weight),
            'heavy': any(
                (row['arch'] in {'spinalflow', 'gustavsnn'} and row['trace_dir'].startswith('sma_azo_vgg_'))
                or int(row['estimated_records_per_sample']) >= HEAVY_THRESHOLD_RECORDS_PER_SAMPLE
                for row in members
            ),
        })
    return target, out


def _millions(value):
    return f"{int(value) / 1_000_000:.1f}M"


def _run_order_sentence(rows):
    a07 = [
        row for row in rows
        if row['arch'] == 'gustavsnn'
        and row['trace_dir'].startswith('spikinglm_')
        and row['layer'].endswith('intermediate_dense')
        and int(row['problem']['KH']) == 1
        and int(row['problem']['KW']) == 1
    ]
    a08 = next(
        row for row in rows
        if row['arch'] == 'gustavsnn'
        and row['trace_dir'] == 'vgg16_cifar10_loas_T32_n500'
        and row['layer'] == 'layer_09_core_features_30'
    )
    c01 = [
        row for row in rows
        if row['arch'] in {'spinalflow', 'gustavsnn'}
        and row['trace_dir'].startswith('sma_azo_vgg_')
    ]
    if not a07 or not c01:
        raise RuntimeError('run-order anchors are missing from the measured rows')
    c01_benchmarks = (
        'sma_azo_vgg_cifar10_dvs_T10_n500',
        'sma_azo_vgg_dvs128_gesture_T16_n500',
    )
    c01_means = []
    for benchmark in c01_benchmarks:
        row = next(row for row in c01 if row['arch'] == 'gustavsnn'
                   and row['layer'].endswith('block2_0_0')
                   and row['trace_dir'] == benchmark)
        c01_means.append(_millions(row['estimated_records_per_sample']))
    c01_min = min(int(row['rank']) for row in c01)
    c01_max = max(int(row['rank']) for row in c01)
    above_c01 = [row for row in rows if int(row['rank']) > c01_max]
    if len(above_c01) != 1 or above_c01[0] != a08:
        raise RuntimeError('run-order departure is not the expected single A08 row')
    return (
        f"The measured rank is the source of truth: A07 spikinglm GustavSNN GEMMs "
        f"span {_millions(min(row['estimated_records_per_sample'] for row in a07))}--"
        f"{_millions(max(row['estimated_records_per_sample'] for row in a07))} records/sample "
        f"(mean); their high end only thinly exceeds the C01 block2 means "
        f"({c01_means[0]}/{c01_means[1]}). The A08 vgg16 `layer_09_core_features_30` "
        f"3x3 convolution reaches {_millions(a08['estimated_records_per_sample'])} "
        f"({int(a08['estimated_records_per_sample']):,}) and is rank {a08['rank']}. "
        f"This is exactly one row of departure from C01-last: C01 rows span ranks "
        f"{c01_min}--{c01_max}, and only that A08 convolution sits above the last C01 row; "
        "forcing every C01 row to the absolute end would break the required "
        "non-decreasing record order."
    )


def _limits_lines(rows, manifest, shards):
    weights = [int(shard['estimated_records']) for shard in shards]
    scratch_bytes_per_record = 2 * NATIVE_OUT_BYTES_PER_RECORD
    spread = next(
        row for row in rows
        if row['arch'] == 'gustavsnn'
        and row['trace_dir'] == 'sma_azo_vgg_dvs128_gesture_T16_n500'
        and row['layer'] == 'layer_01_core_block2_0_0'
    )
    return [
        'The digest columns are derived estimates: capture masks provide the exact per-sample',
        'line/event counts, and solved schedule tile/slab bounds provide the multiplicity.',
        'They are not subset timings or extrapolations. No universal records-to-wall-clock',
        f'rate was measured by this digest: the {SHARD_TARGET_RECORDS:,}-record shard target',
        'and hardcoded `--time=90:00` remain planning conversions, not guarantees. A',
        f'Stokes native observation supplies an I/O basis: `out.bin` is about {NATIVE_OUT_BYTES_PER_RECORD}',
        'bytes per record (8.7 GB for an observed ~98M-record/sample layer), so roughly',
        f'2 x {NATIVE_OUT_BYTES_PER_RECORD} = {scratch_bytes_per_record} bytes/record of native',
        'scratch traffic bounds wall-clock in',
        'the observed configuration, rather than Lustre or CPU. In job 1132795, five',
        'tasks x four workers per node interleaved 32 natives on local `/tmp`, reaching',
        '~160 MB/s aggregate (~5 MB/s each), with all workers in D-state and zero',
        'completed chunks after 30 minutes. The rerun uses `--mem=150G` and',
        f'`TMPDIR=/dev/shm` ({NATIVE_TMPFS_GIB} GiB tmpfs). The 2--3 heaviest singletons',
        'at >=230M records/sample imply ~21 GB `out.bin` per worker x four workers;',
        'they may hit ENOSPC on the 94 GiB tmpfs and should be rerun with CPUS=2.',
        'The completed demo re-measurement is still required to calibrate a shard',
        f'records-to-time conversion. The {len(shards)}',
        f'shard weights range from {min(weights):,} to {max(weights):,} records',
        f'(about {max(weights) / min(weights):,.0f}x, with {min(len(shard["pairs"]) for shard in shards)}--'
        f'{max(len(shard["pairs"]) for shard in shards)} pairs per shard); whether the heaviest',
        'shard fits the wall-clock window is unknown until the Stokes demo re-measurement.',
        'Full-shard output volume and scratch/TMPDIR headroom remain unvalidated. The',
        f'{len(manifest["infeasible_pairs"])} Prosperity INFEASIBLE pairs remain schedule-only',
        'records with no generated trace output. Heavy C01 rows have extreme per-sample',
        'spread: GustavSNN DVS128',
        f'block2_0_0 ranges from {spread["records_min"]:,} to {spread["records_max"]:,}',
        f'around a {spread["estimated_records_per_sample"]:,} mean; shard weights remain exact',
        '500-sample sums, but any per-sample timeout assumption remains unvalidated.',
        '',
        'Two rows were cross-checked against real generated traces: Prosperity A07',
        '`layer_05_core_bert_encoder_layer_0_intermediate_dense`, sample 0, emitted',
        '3,909,120 bursts exactly; Prosperity B09 `loas_resnet19`',
        '`layer_14_core_layer2_2_conv2`, sample 0, emitted 2,606,528 bursts, inside its',
        '2,208,640--3,015,040 measured range around the 2,578,088 mean.',
    ]


def write_digest(rows, manifest, shards):
    digest_path = STOKES_DIR / 's3_digest.md'
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    excluded = manifest['excluded_pairs']
    rows_by_arch = defaultdict(list)
    for row in rows:
        rows_by_arch[row['arch']].append(row)
    max_row = max(rows, key=lambda row: int(row['estimated_records_per_sample']))
    anchors = []
    for arch in ('gustavsnn', 'spinalflow'):
        for benchmark in ('sma_azo_vgg_cifar10_dvs_T10_n500', 'sma_azo_vgg_dvs128_gesture_T16_n500'):
            matches = [
                row for row in rows
                if row['arch'] == arch and row['trace_dir'] == benchmark
                and row['layer'].endswith('block2_0_0')
            ]
            if matches:
                anchors.append(matches[0])
    prosperity_anchor = [
        row for row in rows
        if row['arch'] == 'prosperity'
        and row['trace_dir'] == 'spikinglm_t4_T4_n500'
        and row['layer'] == 'layer_05_core_bert_encoder_layer_0_intermediate_dense'
    ]
    if prosperity_anchor:
        anchors.append(prosperity_anchor[0])
    manifest_rel = pathlib.PurePosixPath(
        os.path.relpath(MANIFEST_PATH, STOKES_DIR)
    ).as_posix()
    trace_root_display = str(TRACE_ROOT).rstrip('/') + '/'
    lines = [
        '# WT500 S3 schedule and record digest',
        '',
        f'Generated 2026-11-11 from `{manifest_rel}` and the eight captures under',
        f'`{trace_root_display}`; all 500 samples of every capture',
        'were scanned. `estimated_records_per_sample` is the rounded arithmetic mean',
        'of the exact 500 per-sample counts; `records_sum_500` is the exact total used',
        'for shard weighting.',
        '',
        'Reproducer: [`s3_measure.py`](s3_measure.py) beside this digest; it compiles',
        '[`prosperity_count.cpp`](prosperity_count.cpp) on demand and emits both',
        '`shards/shards.json` and `shards/shards.csv`.',
        '',
        '## Coverage and method',
        '',
        f'- {len(rows)} generating rows: ' + ', '.join(f'{arch} {len(rows_by_arch[arch])}' for arch in ARCH_ORDER) + '.',
        f'- The {len(manifest["infeasible_pairs"])} Prosperity INFEASIBLE pairs remain recorded in the S2 manifest; {len(excluded)} stride-2 pairs are absent from this digest (the six layers x five architectures).',
        '- Tile count is `dram_num_steps x noc_num_steps x product(NoCLevel spatial factors)`; frame count is `dram_num_steps x noc_num_steps`; machine core count is the fixed 16 nodes x 4 PEs = 64.',
        '- LoAS/PTB counts are the exact 3x3-neighbourhood line sum (or 1x1 line sum) over each capture, multiplied by COUT slab count. PTB has the same records as LoAS.',
        '- SpinalFlow counts every firing event in each receptive field, multiplied by its COUT slab count. GustavSNN uses the same event sum with its realized slab count; its wave width is the schedule NodeLevel spatial product.',
        '- Prosperity was measured with the same exact neighbourhood masks, then the native stable popcount-sort/subset-prefix walk was applied per realized tile and CIN. This covers all 145 surviving rows, including all 47 3x3 rows; no subset timing or extrapolation is used.',
        '- Rows are ranked by estimated records per sample. The weighted shard file uses exact 500-sample totals and keeps the C01 SpinalFlow/GustavSNN rows dedicated.',
        f'- {_run_order_sentence(rows)}',
        '',
        '## Limits and production cross-checks',
        '',
        *_limits_lines(rows, manifest, shards),
        '',
        '## Anchor checks',
        '',
        '| arch | benchmark | layer | sample 0 records | mean/sample |',
        '|---|---|---|---:|---:|',
    ]
    for row in anchors:
        lines.append(f"| {row['arch']} | {row['trace_dir']} | {row['layer']} | {row['records_sample_0']:,} | {row['estimated_records_per_sample']:,} |")
    lines.extend([
        f"| {max_row['arch']} | {max_row['trace_dir']} | {max_row['layer']} | {max_row['records_sample_0']:,} | {max_row['estimated_records_per_sample']:,} |",
        '',
        '## Ranked generating pairs',
        '',
        '| rank | arch | benchmark | layer | shape | tiles | wave width | feasible | frames | machine cores | records/sample (mean) | sample min | sample max | records (500 samples) |',
        '|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|',
    ])
    for row in rows:
        shape = f"{row['problem']['KH']}x{row['problem']['KW']} s{row['stride']} p{row['padding']}"
        wave = '-' if row['wave_width'] is None else str(row['wave_width'])
        lines.append(
            f"| {row['rank']} | {row['arch']} | {row['trace_dir']} | {row['layer']} | {shape} | "
            f"{row['tile_count']:,} | {wave} | SOLVED | {row['frame_count']:,} | {row['machine_cores']} | "
            f"{row['estimated_records_per_sample']:,} | {row['records_min']:,} | {row['records_max']:,} | {row['records_sum_500']:,} |"
        )
    lines.extend([
        '',
        '## Shards',
        '',
        'See [`shards/shards.csv`](shards/shards.csv). Its `estimated_records` values are exact totals over 500 samples; `heavy=true` marks dedicated C01 event-stream layers and the >=50M-record/sample band. Non-heavy shards target 50,000,000,000 records, the planning weight for the 2--4 hour Stokes window.',
    ])
    digest_path.write_text('\n'.join(lines) + '\n')
    return digest_path


def main():
    global MANIFEST_PATH, OUTPUTS, TRACE_ROOT, STOKES_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-manifest', type=pathlib.Path, default=MANIFEST_PATH)
    parser.add_argument('--trace-root', type=pathlib.Path, default=TRACE_ROOT)
    parser.add_argument('--output-dir', type=pathlib.Path, default=STOKES_DIR,
                        help='directory for s3_digest.md and shards/')
    args = parser.parse_args()
    MANIFEST_PATH = args.campaign_manifest.resolve()
    OUTPUTS = MANIFEST_PATH.parent
    TRACE_ROOT = args.trace_root.resolve()
    STOKES_DIR = args.output_dir.resolve()

    if not HELPER.exists() or HELPER.stat().st_mtime < HELPER_SOURCE.stat().st_mtime:
        subprocess.run([
            'g++', '-O3', '-fopenmp', '-std=c++17',
            '-o', str(HELPER), str(HELPER_SOURCE),
        ], check=True)

    manifest = json.loads(MANIFEST_PATH.read_text())
    if len(manifest['schedules']) != 755:
        raise RuntimeError('expected 755 S2 schedule rows')
    records = []
    for raw in manifest['schedules']:
        if raw.get('solver_status') == 'INFEASIBLE':
            continue
        if raw.get('solver_status') not in {'SOLVED', 'CACHED'}:
            raise RuntimeError(f"unexpected solver status {raw.get('solver_status')}")
        artifact_path = OUTPUTS / raw['schedule_path']
        artifact = json.loads(artifact_path.read_text())
        record = dict(raw)
        record['artifact'] = artifact
        record['info'] = schedule_info(record)
        record['npy'] = TRACE_ROOT / raw['trace_relative_dir'] / f"{raw['layer']}.npy"
        if not record['npy'].is_file():
            raise RuntimeError(f"missing capture {record['npy']}")
        records.append(record)
    if len(records) != 749:
        raise RuntimeError(f'expected 749 generating rows, got {len(records)}')
    if len({(r['arch'], r['trace_dir'], r['layer']) for r in records}) != 749:
        raise RuntimeError('duplicate generating pair')

    global_cache = {}
    prosperity_cache = {}
    non_pros = sorted({r['npy'] for r in records if r['arch'] != 'prosperity'}, key=str)
    total_inputs = len(set(r['npy'] for r in records))
    for index, path in enumerate(non_pros, 1):
        kernel = 3 if any(r['npy'] == path and int(r['info']['problem']['KH']) == 3 for r in records) else 1
        print(f'global {index}/{len(non_pros)} {path}', flush=True)
        line, events, shape = neighbourhood_counts(path, kernel)
        global_cache[path] = (line, events, shape)
    prosperity_records = [r for r in records if r['arch'] == 'prosperity']
    for index, record in enumerate(prosperity_records, 1):
        path = record['npy']
        if path not in prosperity_cache:
            print(f'prosperity {index}/{len(prosperity_records)} {path}', flush=True)
            prosperity_cache[path] = prosperity_counts(path, record['info'])

    for record in records:
        info = record['info']
        problem = info['problem']
        if record['arch'] == 'prosperity':
            values, shape = prosperity_cache[record['npy']]
        else:
            line, events, shape = global_cache[record['npy']]
            values = line if record['arch'] in {'loas', 'ptb'} else events
            values = values * int(info['cout_slabs'])
        if values.size != SAMPLE_COUNT:
            raise RuntimeError(f"{record['arch']}/{record['layer']}: expected 500 counts, got {values.size}")
        record.update(info)
        record.update({
            'problem': problem,
            'shape': list(shape),
            'stride': 1,
            'padding': (int(problem['KH']) - 1) // 2,
            'records_sample_0': int(values[0]),
            'records_min': int(values.min()),
            'records_max': int(values.max()),
            'records_sum_500': int(values.sum(dtype=np.int64)),
            'estimated_records_per_sample': int(round(float(values.mean()))),
            'record_rule': 'prosperity_native_prefix' if record['arch'] == 'prosperity' else (
                'line_per_slab' if record['arch'] in {'loas', 'ptb'} else 'event_per_slab'
            ),
        })
    records.sort(key=pair_sort_key)
    for rank, record in enumerate(records, 1):
        record['rank'] = rank

    target, shards = shard_rows(records)
    shard_dir = STOKES_DIR / 'shards'
    shard_path = shard_dir / 'shards.json'
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_payload = {
        'schema': 1,
        'source': 'zoo/wt500_fig3cfg/outputs/manifest.json',
        'samples_per_pair': SAMPLE_COUNT,
        'weight_units': 'records over all 500 samples',
        'target_records_per_shard': target,
        'heavy_threshold_records_per_sample': HEAVY_THRESHOLD_RECORDS_PER_SAMPLE,
        'shard_count': len(shards),
        'pair_count': sum(len(shard['pairs']) for shard in shards),
        'shards': shards,
    }
    shard_path.write_text(json.dumps(shard_payload, indent=2) + '\n')
    csv_path = shard_dir / 'shards.csv'
    with csv_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=('shard_id', 'pairs', 'estimated_records', 'heavy'))
        writer.writeheader()
        for shard in shards:
            pairs = ';'.join(
                f"{pair['arch']}|{pair['benchmark']}|{pair['layer']}"
                for pair in shard['pairs']
            )
            writer.writerow({
                'shard_id': shard['shard_id'],
                'pairs': pairs,
                'estimated_records': shard['estimated_records'],
                'heavy': str(bool(shard['heavy'])).lower(),
            })
    digest_path = write_digest(records, manifest, shards)
    print(f'rows={len(records)} inputs={total_inputs} shards={len(shards)}', flush=True)
    print(f'digest={digest_path}', flush=True)
    print(f'shards={shard_path}', flush=True)
    print(f'shards_csv={csv_path}', flush=True)
    for row in records:
        if row['arch'] in {'spinalflow', 'gustavsnn'} and row['trace_dir'].startswith('sma_azo_vgg_') and row['layer'].endswith('block2_0_0'):
            print('anchor', row['arch'], row['trace_dir'], row['records_sample_0'], row['estimated_records_per_sample'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
