# Stage 2 results: weight-trace generation

First run 2026-08-23 over two layers. **Re-run 2026-08-23 over four**, after the
spike-density survey (`../HANDOFF-ANSWER.md`) added a representative layer per
workload beside the two dense ones. `run_stage2.py`, `conda run -n base`. No
Gurobi, no re-solving. 9m15s wall. Logs in `logs/`, machine-readable record in
`stage2_report.json`, raw streams in `stream/`.

The two carried-over layers were already on disk, so the generator skipped them
(`Skipping 5 already-generated sample(s)`, 0.3 s) and their `.json.gz` artifacts
are bit-for-bit the ones from the first run. Their statistics in
`stage2_report.json` came back identical field for field. Only the two new
layers were generated.

## The four layers

| tag | trace dir | layer | shape | density |
|---|---|---|---|---|
| **V8** | `vgg16_T4_n5` | `layer_08_features_27` | KH3 KW3 CIN512 COUT512 HO4 WO4 T4 | 0.207 |
| **R9** | `resnet19_T4_n5` | `layer_09_layer2_0_conv2` | KH3 KW3 CIN256 COUT128 HO8 WO8 T4 | 0.178 |
| **V9** | `vgg16_T4_n5` | `layer_09_features_30` | KH3 KW3 CIN512 COUT512 HO4 WO4 T4 | 0.578 |
| **R16** | `resnet19_T4_n5` | `layer_16_layer3_0_conv2` | KH3 KW3 CIN512 COUT256 HO4 WO4 T4 | 0.449 |

Density is the median over the five samples. V8 and R9 are the representative
pair; V9 and R16 are the stated low-sparsity stress case.

## Inputs

Staged into `inputs/` before anything ran; `inputs/MANIFEST.json` carries the
provenance and SHA-256 of each.

| Input | Source | Note |
|---|---|---|
| `schedules/loas/<trace_dir>/<layer>.json`, 4 files | Stage 1 `outputs/schedules/pe16/loas/<*_T4_all>/` | `trace_dir` field rewritten to `_n5` |
| `input_trace/<trace_dir>/{meta.json, <layer>.npy}`, 4 pairs | `input_trace/loas/` | uint8 `[T, B, Cin, Hin, Win]` |

The schedule is derived from layer shape alone, so it transfers to the 5-sample
subset unchanged. Only the directory name had to follow, because
`generate_weight_traces.py:128` resolves the schedule as
`<schedule-cache>/<arch>/<trace_dir>/<layer>.json`.

**Native bridge.** `src/archmodels/loas/loasgen` was rebuilt 2026-08-23 15:48
against `main.cpp` of 2026-08-20 (commit 34c9836, which inverted the emission
nesting and added stdout streaming), and is still current for this run. The
nesting change is benign either way: `native_bridge.py:54-55` still loops
tile-outer while the binary emits sample-outer, but `assemble_layer_traces`
(`tracegen.py:257-265`) keys every record off its own `tile_idx`/`sample_idx`
rather than loop position, and the record count is `num_tiles * num_samples` in
both orders.

## The five samples

Array indices 0 through 4 of the `_n5` subset, which are **CIFAR-10 images
2697, 3078, 5110, 6367, 8502**, drawn by
`numpy.random.default_rng(0).choice(10000, 5, replace=False)` then sorted, and
recorded in both `meta.json` files under `subset`. The same five images in both
workloads and in all four layers.

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

A "site" is one `(cin, hin, win)` position; it is silent when it never fires
across all four ticks, which is the exact test the generator runs. `density` is
spikes over `T*Cin*Hin*Win`.

### V8, vgg16 `layer_08_features_27` (elements 32768, sites 8192)

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 6793 | 0.2073 | 25 / 512 | 4965 / 8192 | 0.3939 |
| 1 | 3078 | 6764 | 0.2064 | 79 / 512 | 5246 / 8192 | 0.3596 |
| 2 | 5110 | 6306 | 0.1924 | 71 / 512 | 5302 / 8192 | 0.3528 |
| 3 | 6367 | 6123 | 0.1869 | 26 / 512 | 5075 / 8192 | 0.3805 |
| 4 | 8502 | 7376 | 0.2251 | 24 / 512 | 4953 / 8192 | 0.3954 |

### R9, resnet19 `layer_09_layer2_0_conv2` (elements 65536, sites 16384)

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 12773 | 0.1949 | 0 / 256 | 10787 / 16384 | 0.3416 |
| 1 | 3078 | 10738 | 0.1638 | 13 / 256 | 12034 / 16384 | 0.2655 |
| 2 | 5110 | 10527 | 0.1606 | 26 / 256 | 11964 / 16384 | 0.2698 |
| 3 | 6367 | 11637 | 0.1776 | 0 / 256 | 11191 / 16384 | 0.3170 |
| 4 | 8502 | 13652 | 0.2083 | 3 / 256 | 10865 / 16384 | 0.3369 |

### V9, vgg16 `layer_09_features_30` (elements 32768, sites 8192)

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 18950 | 0.5783 | 1 / 512 | 1941 / 8192 | 0.7631 |
| 1 | 3078 | 19266 | 0.5880 | 2 / 512 | 2074 / 8192 | 0.7468 |
| 2 | 5110 | 19339 | 0.5902 | 0 / 512 | 1959 / 8192 | 0.7609 |
| 3 | 6367 | 18623 | 0.5683 | 1 / 512 | 1914 / 8192 | 0.7664 |
| 4 | 8502 | 18944 | 0.5781 | 0 / 512 | 2141 / 8192 | 0.7386 |

### R16, resnet19 `layer_16_layer3_0_conv2` (elements 32768, sites 8192)

| sample | CIFAR | spikes | density | silent channels | silent sites | site fire rate |
|---|---|---|---|---|---|---|
| 0 | 2697 | 13809 | 0.4214 | 35 / 512 | 3373 / 8192 | 0.5883 |
| 1 | 3078 | 15134 | 0.4619 | 48 / 512 | 3283 / 8192 | 0.5992 |
| 2 | 5110 | 15398 | 0.4699 | 51 / 512 | 3228 / 8192 | 0.6060 |
| 3 | 6367 | 13579 | 0.4144 | 35 / 512 | 3268 / 8192 | 0.6011 |
| 4 | 8502 | 14714 | 0.4490 | 41 / 512 | 3329 / 8192 | 0.5936 |

### The representative layers vary far more between images

| layer | density median | min | max | range / median |
|---|---|---|---|---|
| V8 | 0.2064 | 0.1869 | 0.2251 | **0.185** |
| R9 | 0.1776 | 0.1606 | 0.2083 | **0.269** |
| V9 | 0.5783 | 0.5683 | 0.5902 | 0.038 |
| R16 | 0.4490 | 0.4144 | 0.4699 | 0.124 |

Emitted rows carry the same pattern: range over median is 0.105 for V8 and
0.247 for R9 against 0.035 for V9 and 0.028 for R16. A dense layer is dense on
every image; a sparse one is sparse by an image-dependent amount. Five samples
resolve V9 and R16 comfortably and resolve R9 poorly.

This is **not** yet the trigger for the "raise n if the range exceeds 5% of the
median" rule. That rule is about the per-sample *ratio* in a paired A-vs-B
comparison, which is far tighter than the raw workload volume because both arms
see the same image. It cannot be evaluated until Stage 4 produces a paired
ratio. It does say to expect a wider ratio spread on R9 than the earlier layers
suggested, and to plan for n above 5 there.

Whole-channel silence is rare in the dense layers (0 to 2 of 512 in V9) and
substantial in the sparse ones (up to 79 of 512 in V8). The work that gets
removed is still per-site, not per-channel, in every layer.

## Weight trace statistics

A `LayerWeightTrace` tile is one `(dram_i, noc_i)` pair with all 16 cores merged
inside it, so `len(tiles) == dram_num_steps * noc_num_steps`. The `NodeTileSpec`
list the reconstruction walked is 16x larger.

| | V8 | R9 | V9 | R16 |
|---|---|---|---|---|
| `dram_num_steps` x `noc_num_steps` | 16 x 8 | 2 x 64 | 16 x 8 | 32 x 2 |
| tiles per sample | 128 | 128 | 128 | 64 |
| NodeTileSpecs walked | 2048 | 2048 | 2048 | 1024 |
| cores per tile | 16 | 16 | 16 | 16 |
| per-core ceiling `KH*KW*CIN` | 4608 | 2304 | 4608 | 4608 |
| output pixels `HO*WO` | 16 | 64 | 16 | 16 |
| tile instances per pixel | 128 | 32 | 128 | 64 |

### V8, vgg16 `layer_08_features_27`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 2,597,632 | 1268.4 | 0.2753 | 162,352 | 8,138,203 |
| 1 | 2,372,352 | 1158.4 | 0.2514 | 148,272 | 7,453,132 |
| 2 | 2,339,200 | 1142.2 | 0.2479 | 146,200 | 7,369,469 |
| 3 | 2,496,256 | 1218.9 | 0.2645 | 156,016 | 7,846,900 |
| 4 | 2,600,192 | 1269.6 | 0.2755 | 162,512 | 8,164,585 |

### R9, resnet19 `layer_09_layer2_0_conv2`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 1,382,144 | 674.9 | 0.2929 | 86,384 | 4,347,522 |
| 1 | 1,070,560 | 522.7 | 0.2269 | 66,910 | 3,385,458 |
| 2 | 1,093,728 | 534.0 | 0.2318 | 68,358 | 3,451,684 |
| 3 | 1,263,264 | 616.8 | 0.2677 | 78,954 | 3,980,226 |
| 4 | 1,361,696 | 664.9 | 0.2886 | 85,106 | 4,278,753 |

### V9, vgg16 `layer_09_features_30`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 4,995,072 | 2439.0 | 0.5293 | 312,192 | 15,354,643 |
| 1 | 4,909,952 | 2397.4 | 0.5203 | 306,872 | 15,100,519 |
| 2 | 4,998,784 | 2440.8 | 0.5297 | 312,424 | 15,363,264 |
| 3 | 5,020,416 | 2451.4 | 0.5320 | 313,776 | 15,420,611 |
| 4 | 4,845,824 | 2366.1 | 0.5135 | 302,864 | 14,924,533 |

### R16, resnet19 `layer_16_layer3_0_conv2`

| sample | total rows | rows/core/tile | emitted/possible | mac_cycles | gz bytes |
|---|---|---|---|---|---|
| 0 | 1,969,728 | 1923.6 | 0.4174 | 123,108 | 6,141,834 |
| 1 | 2,004,480 | 1957.5 | 0.4248 | 125,280 | 6,243,442 |
| 2 | 2,025,152 | 1977.7 | 0.4292 | 126,572 | 6,302,109 |
| 3 | 2,016,192 | 1968.9 | 0.4273 | 126,012 | 6,282,407 |
| 4 | 1,980,096 | 1933.7 | 0.4196 | 123,756 | 6,174,218 |

The representative pair emits roughly half the rows of the stress pair: V8 is
0.48x V9 on the same schedule, and R9 is 0.68x R16 on a smaller one.

## Five checks that passed

**1. Row counts reproduce from the raw spikes, exactly, on all 20 samples.**
`verify_reconstruction.py` (committed this run) walks `(ho, wo, kh, kw, cin)` in
NumPy with the same padding rule, counts non-silent sites, and multiplies by the
tile instances per pixel, which it derives from the schedule alone as
`COUT / node_spatial_COUT`. It imports neither the generator nor the native
bridge. Every `total_rows` and every `mac_cycles` total matches as an integer:

```
all row and mac_cycles counts reproduce exactly
```

The first run described this check but never committed the code. It is now a
script, and it re-derives the two carried-over layers' original numbers as well
as the two new ones.

**2. `mac_cycles` is consistent with the row counts.** `mac_cycles` per tile is
the max over cores, and every core at one `(ho, wo)` emits the same rows because
COUT does not affect which positions fire, so the max equals each. Total
`mac_cycles` therefore equals `total_rows / 16` in every layer:
`2597632 / 16 = 162352`, `1382144 / 16 = 86384`, `4995072 / 16 = 312192`,
`1969728 / 16 = 123108`. Check 1 predicts both independently and both land.

**3. Padding accounts for the emission gap.** Valid taps per pixel average
`6.25 / 9 = 0.6944` on a 4x4 plane with a 3x3 pad-1 kernel, and
`7.5625 / 9 = 0.8403` on an 8x8 plane. Predicted emission is
`valid_tap_fraction * site_fire_rate`, on sample 0:

| layer | predicted | measured | residual |
|---|---|---|---|
| V8 | 0.6944 x 0.3939 = 0.2735 | 0.2753 | +0.0018 |
| R9 | 0.8403 x 0.3416 = 0.2871 | 0.2929 | +0.0058 |
| V9 | 0.6944 x 0.7631 = 0.5299 | 0.5293 | -0.0006 |
| R16 | 0.6944 x 0.5883 = 0.4085 | 0.4174 | +0.0089 |

The residual is border weighting, since silent sites are not spread uniformly
across the pixel grid. Approximate by construction, and close in all four,
including the 8x8 plane whose tap fraction is different.

**4. Every WCTS stream is self-consistent.** Trailer magic `-1`, the trailer's
`total_bursts` equal to a full walk of the frames, and bytes consumed equal to
file size, on all eight dumps: four full streams and four 4-tile excerpts.

**5. The stream and the JSON trace agree on row count.** Each full stream's
`total_bursts` equals that sample's `total_rows` from the `.json.gz`:
2,597,632 / 1,382,144 / 4,995,072 / 1,969,728. Two independent writers of the
same reconstruction, same integer.

## The COUT partition, which decides Stage 4

Verified for all four layers by `verify_reconstruction.py`, which collects every
`(cout_start, cout_end)` block each core emits and checks the cover:

```
V8, V9    16 cores, 128 distinct blocks, 32 COUT channels each, union 0..511
R9        16 cores,  32 distinct blocks,  8 COUT channels each, union 0..127
R16       16 cores,  64 distinct blocks, 16 COUT channels each, union 0..255
```

Every channel is covered exactly once in every layer: disjoint, complete. Core
`c` owns a contiguous run of `COUT / 16` channels and the DRAM COUT loop walks
it 4 at a time. That is `tiles.py:155-158`,
`core_idx * node_bound * noc_t * dram_t`, which is `1*4*1*8 = 32` for the vgg16
layers, `1*4*1*2 = 8` for R9, and `1*4*1*4 = 16` for R16.

**The 16 cores never request the same weight address.** For any given
`(kh, kw, cin)` they each want a different COUT slice. So within one tile a
shared L2 sees no cross-core weight reuse at all; all reuse has to come from
revisiting the same `(kh, kw, cin, cout)` across different `(ho, wo)` tiles.
That is the single most important fact carried into Stage 4, it holds in all
four layers, and it is a direct consequence of the NoCLevel spatial split being
COUTx16.

R9 sharpens it: with only 8 channels per core and 64 output pixels, its reuse
opportunity is the largest of the four, and its per-core working set the
smallest.

## Raw stream artifacts

| File | Bytes | Contents |
|---|---|---|
| `stream/layer_08_features_27_s00000.wcts` | 72,753,392 | full sample 0, 128 tiles |
| `stream/layer_08_features_27_s00000_first4tiles.wcts` | 2,281,616 | valid 4-tile stream |
| `stream/layer_09_layer2_0_conv2_s00000.wcts` | 38,719,734 | full sample 0, 128 tiles |
| `stream/layer_09_layer2_0_conv2_s00000_first4tiles.wcts` | 742,294 | valid 4-tile stream |
| `stream/layer_09_features_30_s00000.wcts` | 139,881,712 | full sample 0, 128 tiles |
| `stream/layer_09_features_30_s00000_first4tiles.wcts` | 4,424,848 | valid 4-tile stream |
| `stream/layer_16_layer3_0_conv2_s00000.wcts` | 55,162,358 | full sample 0, 64 tiles |
| `stream/layer_16_layer3_0_conv2_s00000_first4tiles.wcts` | 3,413,270 | valid 4-tile stream |

`stream/*_first4tiles.txt` are readable decodes produced by `wcts_excerpt.py`.
The R9 header reads:

```
n_tiles 4   n_cores 16   weight_bytes 1
burst_dim 3 (COUT)   burst_stride 1   burst_span 4
addr fields  ['kh', 'kw', 'cin', 'run_start', 'run_end']
spatial_factors  {COUT:16}  product=16
dims  {KH:3, KW:3, CIN:256, COUT:128, HO:8, WO:8, T:4}
```

`burst_dim = COUT` in all four headers, which is what the downstream grids
assume, so the U29 hazard in `PROGRESS.md` (a non-COUT burst dim decoding
silently wrong) is not triggered by any of them. `burst_span = 4` matches the
NodeLevel COUT spatial factor everywhere.

Tile 0's first burst is `kh=1 kw=1`, not `kh=0 kw=0`: tile 0 is the corner pixel
`(ho, wo) = (0, 0)` where `kh=0` maps to `hin=-1`, which is padding. Correct per
`LoASGen.h:72-79`, and true in all four layers.

## What Stage 3 consumes

`outputs/weight_traces/loas/noc2MiB_node32kb/<trace_dir>/<layer>/sample_*.json.gz`,
20 files across four layers. The `stream/` dumps are for inspection and are not
pipeline inputs.

## Cost

Generation, single worker: V8 243 s, R9 112 s for 5 samples each. V9 and R16
were skipped as already present (they cost 528 s and 187 s in the first run).
Stream dumps 15/12 s, 7/6 s, 29/21 s, 11/9 s. Reconstruction check 95 s for all
20 samples.
