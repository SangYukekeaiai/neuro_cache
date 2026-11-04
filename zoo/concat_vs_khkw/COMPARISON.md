# loas: cin_khkw_concat versus khkw_split

## Scope and reproducibility

20 existing `.baseline/wcache/streams/{V8,V9,R9,R16}_s0000{0..4}.wcts` streams × two layouts × three line sizes = 120 simulations. These baseline streams predate T53. No traces were regenerated and `.baseline` was not modified; original stream hashes are recorded in [provenance.json](provenance.json) and checked again after replay.

The stored streams contain WCTS v1 coordinates, not line IDs. The v1 refusal message in [stream_format.h](../../src/lays/cachesim/native/include/cachesim/trace/stream_format.h), identifies `[kh, kw, cin, run_start, run_end]`: for COUT bursts, `run_start` is exactly the v2 COUT anchor. The explicitly enabled pipe adapter requires valid magic, version 1, COUT, and stride 1, then changes only the four-byte version field at offsets [8,12) to 2. Every other byte passes unchanged; no converted file is saved. The simulator [decodes coordinates](../../src/lays/cachesim/native/src/trace/stream_trace.cpp) and [expands them through the mapper](../../src/lays/cachesim/native/src/core/engine_core.cpp) during replay, computing layout-dependent line IDs anew; reuse across layouts and blockings is therefore sound.

Rerun from the repository root (stdlib Python and g++/make required):

```sh
python3 zoo/concat_vs_khkw/run.py --allow-v1-cout --jobs 4
```

The script builds `MODE=release` apps, derives six saved `config_*.json` files from [base.json](../../examples/cache/base.json), then runs `cachesim_run` once per stream/config. Only `layout` and `cin_block` vary: CIN 4/8/16 × COUT 4 × weight_bytes 1 gives 16/32/64B lines. L1 is 16384B, 8-way; L2 is 524288B, 16-way; every other base.json setting is held fixed. Omitted settings use the same native defaults for every run, visible in [results.csv](results.csv). The CSV retains every native column name and value; `_tag` and `_stream` identify the input. Native `sim_wall_seconds` is host wall time and may change on rerun; comparisons below use simulated cycles.

## Mean of five samples per layer and line size

Rates are arithmetic means of the simulator's reported per-sample `l1_hit_rate`/`l2_hit_rate`, expressed as percentages; they are not pooled hit/access ratios. Every delta is concat minus split. Rate deltas are percentage points (pp). Cycle ratio = mean concat `total_cycles` / mean split `total_cycles`; a ratio below 1 favors concat.

| Layer | Line B | split L1 % | concat L1 % | Δ L1 pp | split L2 % | concat L2 % | Δ L2 pp | split cycles | concat cycles | Δ cycles | cycles ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V8 | 16 | 88.3315 | 83.2607 | -5.0708 | 5.7153 | 64.3441 | +58.6288 | 607947.2 | 572251.2 | -35696.0 | 0.941284 |
| V8 | 32 | 93.7725 | 84.1647 | -9.6078 | 0.9307 | 81.1927 | +80.2620 | 406182.4 | 522844.8 | +116662.4 | 1.287217 |
| V8 | 64 | 96.8572 | 91.2333 | -5.6239 | 0.0000 | 83.0189 | +83.0189 | 282854.4 | 328931.2 | +46076.8 | 1.162899 |
| V9 | 16 | 93.7230 | 82.7630 | -10.9600 | 0.1235 | 82.7294 | +82.6058 | 816334.4 | 1117193.6 | +300859.2 | 1.368549 |
| V9 | 32 | 96.8576 | 91.2343 | -5.6233 | 0.0000 | 83.0189 | +83.0189 | 563873.6 | 655102.4 | +91228.8 | 1.161789 |
| V9 | 64 | 98.4288 | 95.6172 | -2.8116 | 0.0000 | 83.0189 | +83.0189 | 437409.6 | 418900.8 | -18508.8 | 0.957685 |
| R9 | 16 | 98.4894 | 98.4894 | +0.0000 | 0.0000 | 0.0000 | +0.0000 | 107652.4 | 107652.4 | +0.0 | 1.000000 |
| R9 | 32 | 99.2447 | 99.2447 | +0.0000 | 0.0000 | 0.0000 | +0.0000 | 92394.4 | 92394.4 | +0.0 | 1.000000 |
| R9 | 64 | 99.6223 | 99.6223 | +0.0000 | 0.0000 | 0.0000 | +0.0000 | 84762.4 | 84762.4 | +0.0 | 1.000000 |
| R16 | 16 | 92.3056 | 80.9625 | -11.3431 | 1.0326 | 80.5885 | +79.5559 | 374619.2 | 492643.2 | +118024.0 | 1.315051 |
| R16 | 32 | 96.1079 | 89.1794 | -6.9285 | 0.0329 | 82.9562 | +82.9233 | 252008.8 | 308811.2 | +56802.4 | 1.225398 |
| R16 | 64 | 98.0533 | 94.5698 | -3.4835 | 0.0000 | 83.0189 | +83.0189 | 188837.6 | 190733.6 | +1896.0 | 1.010040 |

## Mean hit and miss counts

Cells are split → concat (Δ), averaged over the same five samples. Miss counts are derived as native `accesses - hits`; the native CSV does not have separate miss columns.

| Layer | Line B | L1 hits | Derived L1 misses | L2 hits | Derived L2 misses |
|---|---:|---:|---:|---:|---:|
| V8 | 16 | 2192076.8 → 2065510.4 (-126566.4) | 289049.6 → 415616.0 (+126566.4) | 16512.0 → 268262.4 (+251750.4) | 272537.6 → 147353.6 (-125184.0) |
| V8 | 32 | 2326912.0 → 2088806.4 (-238105.6) | 154214.4 → 392320.0 (+238105.6) | 1433.6 → 318592.0 (+317158.4) | 152780.8 → 73728.0 (-79052.8) |
| V8 | 64 | 2403302.4 → 2264038.4 (-139264.0) | 77824.0 → 217088.0 (+139264.0) | 0.0 → 180224.0 (+180224.0) | 77824.0 → 36864.0 (-40960.0) |
| V9 | 16 | 4643097.6 → 4100172.8 (-542924.8) | 310912.0 → 853836.8 (+542924.8) | 384.0 → 706380.8 (+705996.8) | 310528.0 → 147456.0 (-163072.0) |
| V9 | 32 | 4798361.6 → 4519833.6 (-278528.0) | 155648.0 → 434176.0 (+278528.0) | 0.0 → 360448.0 (+360448.0) | 155648.0 → 73728.0 (-81920.0) |
| V9 | 64 | 4876185.6 → 4736921.6 (-139264.0) | 77824.0 → 217088.0 (+139264.0) | 0.0 → 180224.0 (+180224.0) | 77824.0 → 36864.0 (-40960.0) |
| R9 | 16 | 1215846.4 → 1215846.4 (+0.0) | 18432.0 → 18432.0 (+0.0) | 0.0 → 0.0 (+0.0) | 18432.0 → 18432.0 (+0.0) |
| R9 | 32 | 1225062.4 → 1225062.4 (+0.0) | 9216.0 → 9216.0 (+0.0) | 0.0 → 0.0 (+0.0) | 9216.0 → 9216.0 (+0.0) |
| R9 | 64 | 1229670.4 → 1229670.4 (+0.0) | 4608.0 → 4608.0 (+0.0) | 0.0 → 0.0 (+0.0) | 4608.0 → 4608.0 (+0.0) |
| R16 | 16 | 1845324.8 → 1618483.2 (-226841.6) | 153804.8 → 380646.4 (+226841.6) | 1587.2 → 306931.2 (+305344.0) | 152217.6 → 73715.2 (-78502.4) |
| R16 | 32 | 1921331.2 → 1782835.2 (-138496.0) | 77798.4 → 216294.4 (+138496.0) | 25.6 → 179430.4 (+179404.8) | 77772.8 → 36864.0 (-40908.8) |
| R16 | 64 | 1960217.6 → 1890585.6 (-69632.0) | 38912.0 → 108544.0 (+69632.0) | 0.0 → 90112.0 (+90112.0) | 38912.0 → 18432.0 (-20480.0) |

## Conclusions

- Concat wins on mean simulated cycles (2/12): V8/16B (-35696.0 cycles, -5.872%); V9/64B (-18508.8 cycles, -4.231%).
- Concat loses on mean simulated cycles (7/12): V8/32B (+116662.4 cycles, +28.722%); V8/64B (+46076.8 cycles, +16.290%); V9/16B (+300859.2 cycles, +36.855%); V9/32B (+91228.8 cycles, +16.179%); R16/16B (+118024.0 cycles, +31.505%); R16/32B (+56802.4 cycles, +22.540%); R16/64B (+1896.0 cycles, +1.004%).
- Concat ties on mean simulated cycles (3/12): R9/16B (+0.0 cycles, +0.000%); R9/32B (+0.0 cycles, +0.000%); R9/64B (+0.0 cycles, +0.000%).

R9 (stream-header shape 3×3, CIN 256, COUT 128) has exactly one L1 miss per distinct weight line: `l1_accesses - l1_hits` is 18,432 / 9,216 / 4,608 at 16/32/64B in every sample under both layouts, leaving no conflict/refetch misses for either mapping to remove despite their different line IDs. In contrast, every V8/V9/R16 run exceeds its layer's distinct-line count, and these refetch miss counts change between the two layouts, unlike R9's compulsory-only misses.

These observations cover only these four loas layers, their five stored samples, the three blockings, and the fixed base cache settings. They do not establish results for other workloads or settings.
