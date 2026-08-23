# Stage 2 results: weight-trace generation

Run 2026-08-23 by `run_stage2.py`, `conda run -n base`. No Gurobi, no
re-solving. Logs in `logs/`, machine-readable record in `stage2_report.json`,
raw streams in `stream/`.

## Inputs

Staged into `inputs/` before anything ran; `inputs/MANIFEST.json` carries the
provenance and SHA-256 of each.

| Input | Source | Note |
|---|---|---|
| `schedules/loas/vgg16_T4_n5/layer_09_features_30.json` | Stage 1 `outputs/schedules/pe16/loas/vgg16_T4_all/` | `trace_dir` field rewritten to `_n5` |
| `schedules/loas/resnet19_T4_n5/layer_16_layer3_0_conv2.json` | same | same |
| `input_trace/vgg16_T4_n5/{meta.json, layer_09_features_30.npy}` | `input_trace/loas/` | `(4, 5, 512, 4, 4)` uint8, 163840 B |
| `input_trace/resnet19_T4_n5/{meta.json, layer_16_layer3_0_conv2.npy}` | same | same shape |

The schedule is derived from layer shape alone, so it transfers to the 5-sample
subset unchanged. Only the directory name had to follow, because
`generate_weight_traces.py:128` resolves the schedule as
`<schedule-cache>/<arch>/<trace_dir>/<layer>.json`.

**Native bridge rebuilt before running.** `src/archmodels/loas/loasgen` was
built 2026-08-02 but `main.cpp` was last changed 2026-08-20 (commit 34c9836,
which inverted the emission nesting and added stdout streaming). Rebuilt with
`make`. The nesting change is benign either way:
`native_bridge.py:54-55` still loops tile-outer while the current binary emits
sample-outer, but `assemble_layer_traces` (`tracegen.py:257-265`) keys every
record off its own `tile_idx`/`sample_idx` rather than loop position, and the
record count is `num_tiles * num_samples` in both orders.

## The five samples

Array indices 0 through 4 of the `_n5` subset, which are **CIFAR-10 images
2697, 3078, 5110, 6367, 8502**, drawn by
`numpy.random.default_rng(0).choice(10000, 5, replace=False)` then sorted, and
recorded in both `meta.json` files under `subset`. The same five images in both
workloads.

Output files are named `sample_00000.json.gz` through `sample_00004.json.gz` by
**array** index, not by CIFAR index.

## What contributes to the trace

`src/archmodels/loas/LoASGen.h:66-119`. One tile is one fixed `(ho, wo)` output
pixel's full reduction row, walked `[KH, KW, CIN]` with CIN innermost. For each
`(kh, kw, cin)`:

```
hin = ho + kh - (kh_n-1)/2      win = wo + kw - (kw_n-1)/2       "same" padding
non_silent = any spike at trace[t][sample][cin][hin][win] for t in the tile's T range
```

- **non_silent** emits exactly one `AddressRow (kh, kw, cin, cout_start, cout_end)`
  and increments `mac_cycles`; `tick i == line i`, strictly sequential.
- **silent** across all T contributes nothing: no address, no tick, no cycle.
- **out-of-range hin/win** is padding, never a spike, contributes nothing.

So `mac_cycles == len(addresses)` per core, and input sparsity is the entire
mechanism. `cout_start`/`cout_end` come from the tile spec, not the spikes, so
COUT never affects *which* rows exist, only how wide each is.

## Input trace statistics

`density` is spikes over `T*Cin*Hin*Win = 4*512*4*4 = 32768` elements. A
"site" is one `(cin, hin, win)` position; it is silent when it never fires
across all four ticks, which is the exact test the generator runs.

### vgg16 `layer_09_features_30`

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 18950 | 0.5783 | 1 / 512 | 1941 / 8192 | 0.7631 |
| 1 | 3078 | 19266 | 0.5880 | 2 / 512 | 2074 / 8192 | 0.7468 |
| 2 | 5110 | 19339 | 0.5902 | 0 / 512 | 1959 / 8192 | 0.7609 |
| 3 | 6367 | 18623 | 0.5683 | 1 / 512 | 1914 / 8192 | 0.7664 |
| 4 | 8502 | 18944 | 0.5781 | 0 / 512 | 2141 / 8192 | 0.7386 |

### resnet19 `layer_16_layer3_0_conv2`

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 13809 | 0.4214 | 35 / 512 | 3373 / 8192 | 0.5883 |
| 1 | 3078 | 15134 | 0.4619 | 48 / 512 | 3283 / 8192 | 0.5992 |
| 2 | 5110 | 15398 | 0.4699 | 51 / 512 | 3228 / 8192 | 0.6060 |
| 3 | 6367 | 13579 | 0.4144 | 35 / 512 | 3268 / 8192 | 0.6011 |
| 4 | 8502 | 14714 | 0.4490 | 41 / 512 | 3329 / 8192 | 0.5936 |

These are dense layers by SNN standards. Whole-channel silence is rare in
vgg16 (0 to 2 of 512) and modest in resnet19 (35 to 51 of 512), so the sparsity
that removes work is per-site, not per-channel.

## Weight trace statistics

A `LayerWeightTrace` tile is one `(dram_i, noc_i)` pair with all 16 cores
merged inside it, so `len(tiles) == dram_num_steps * noc_num_steps`. The
`NodeTileSpec` list the reconstruction walked is 16x larger.

| | vgg16 | resnet19 |
|---|---|---|
| `dram_num_steps` x `noc_num_steps` | 16 x 8 | 32 x 2 |
| tiles per sample | 128 | 64 |
| NodeTileSpecs walked | 2048 | 1024 |
| cores per tile | 16 to 16 | 16 to 16 |
| ticks per tile | 1516 to 3575 | 1176 to 2854 |
| per-core ceiling `KH*KW*CIN` | 4608 | 4608 |

### vgg16 `layer_09_features_30`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 4,995,072 | 2439.0 | 0.5293 | 312,192 | 15,354,643 |
| 1 | 4,909,952 | 2397.4 | 0.5203 | 306,872 | 15,100,519 |
| 2 | 4,998,784 | 2440.8 | 0.5297 | 312,424 | 15,363,264 |
| 3 | 5,020,416 | 2451.4 | 0.5320 | 313,776 | 15,420,611 |
| 4 | 4,845,824 | 2366.1 | 0.5135 | 302,864 | 14,924,533 |

### resnet19 `layer_16_layer3_0_conv2`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 1,969,728 | 1923.6 | 0.4174 | 123,108 | 6,141,834 |
| 1 | 2,004,480 | 1957.5 | 0.4248 | 125,280 | 6,243,442 |
| 2 | 2,025,152 | 1977.7 | 0.4292 | 126,572 | 6,302,109 |
| 3 | 2,016,192 | 1968.9 | 0.4273 | 126,012 | 6,282,407 |
| 4 | 1,980,096 | 1933.7 | 0.4196 | 123,756 | 6,174,218 |

## Four checks that passed

**1. Row counts reproduce from the raw spikes.** An independent NumPy
recomputation, walking `(ho, wo, kh, kw)` with the same padding rule and
counting non-silent `(cin, hin, win)` sites, then multiplying by the number of
NodeTileSpecs per output pixel, matches the generator **exactly on all ten
samples**. This is the strongest evidence in this stage that the reconstruction
is doing what `LoASGen.h` says.

**2. `mac_cycles` is consistent with the row counts.** Total `mac_cycles`
divided by tile count equals `rows_per_core_mean` to the digit, for every
sample: `312192 / 128 = 2439.0` and `123108 / 64 = 1923.6`. `mac_cycles` per
tile is the max over cores, and every core at one `(ho, wo)` emits the same
rows because COUT does not affect which positions fire, so max equals each.

**3. Padding accounts for the gap.** For `HO = WO = 4` with a 3x3 kernel and
pad 1, valid taps per output row are `[2, 3, 3, 2]`, so the mean valid tap
fraction is `6.25 / 9 = 0.6944`. Predicted emission is
`0.6944 * site_fire_rate`: vgg16 sample 0 gives `0.6944 * 0.7631 = 0.5299`
against a measured 0.5293, and resnet19 sample 0 gives 0.4085 against 0.4174.
The residual is border weighting, since silent sites are not spread uniformly
across the pixel grid. Approximate by construction, and close.

**4. Every WCTS stream is self-consistent.** Trailer magic `-1`, the trailer's
`total_bursts` equals a full walk of the frames, and bytes consumed equals file
size, on both dumps.

## The COUT partition, which decides Stage 4

From the stream header and confirmed by enumerating all tile offsets:

```
vgg16     16 cores, 32 COUT channels each, disjoint, union = 0..511  complete
resnet19  16 cores, 16 COUT channels each, disjoint, union = 0..255  complete
```

Core `c` owns COUT `[c*32, c*32+32)` and the DRAM COUT loop walks it 4 at a
time across the 8 DRAM steps. That comes straight out of `tiles.py:155-158`:
`core_idx * node_bound * noc_t * dram_t = 1 * 4 * 1 * 8 = 32`.

**The 16 cores never request the same weight address.** For any given
`(kh, kw, cin)` they each want a different COUT slice. So within one tile a
shared L2 sees no cross-core weight reuse at all; all reuse has to come from
revisiting the same `(kh, kw, cin, cout)` across different `(ho, wo)` tiles.
That is the single most important fact carried into Stage 4, and it is a direct
consequence of the NoCLevel spatial split being COUTx16.

## Raw stream artifacts

| File | Bytes | Contents |
|---|---|---|
| `stream/layer_09_features_30_s00000.wcts` | 139,881,712 | full sample 0, 128 tiles |
| `stream/layer_09_features_30_s00000_first4tiles.wcts` | 4,424,848 | valid 4-tile stream |
| `stream/layer_16_layer3_0_conv2_s00000.wcts` | 55,162,358 | full sample 0, 64 tiles |
| `stream/layer_16_layer3_0_conv2_s00000_first4tiles.wcts` | 3,413,270 | valid 4-tile stream |

`stream/*_first4tiles.txt` are readable decodes produced by
`wcts_excerpt.py`. The vgg16 header reads:

```
n_tiles 4   n_cores 16   weight_bytes 1
burst_dim 3 (COUT)   burst_stride 1   burst_span 4
addr fields  ['kh', 'kw', 'cin', 'run_start', 'run_end']
spatial_factors  {COUT:16}  product=16
dims  {KH:3, KW:3, CIN:512, COUT:512, HO:4, WO:4, T:4}
```

`burst_dim = COUT` is what the downstream grids assume, so the U29 hazard in
`PROGRESS.md` (a non-COUT burst dim decoding silently wrong) is not triggered.
`burst_span = 4` matches the NodeLevel COUT spatial factor.

Tile 0's first burst is `kh=1 kw=1`, not `kh=0 kw=0`: tile 0 is the corner
pixel `(ho, wo) = (0, 0)` where `kh=0` maps to `hin=-1`, which is padding.
Correct per `LoASGen.h:72-79`.

## What Stage 3 consumes

`outputs/weight_traces/loas/noc2MiB_node32kb/<trace_dir>/<layer>/sample_*.json.gz`,
ten files. The `stream/` dumps are for inspection and are not pipeline inputs.

## Cost

vgg16 528 s for 5 samples, resnet19 187 s. Stream dumps 33 s and 11 s each.
Single worker throughout.
