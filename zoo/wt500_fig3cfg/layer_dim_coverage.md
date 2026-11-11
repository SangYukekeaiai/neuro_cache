# WT500 layer-dimension coverage (step 1b)

Source of truth: `/u/yyu9/neuro_cache_bench_trace/LAYER_SHAPES.md` (157 captured
layers, 8 benchmark workloads), collapsed here into the **unique shape classes**
the five weight-trace generators must handle. Step 1b only: the per-generator
coverage matrix is step 1c (stub at the bottom).

Collapse key: `(type, kh x kw, stride, padding, dilation, groups)`. Everything
that varies *inside* a class (`inc`, `oc`, `ho x wo`, `T`) is listed as a range,
because those are data-size knobs, not structural cases: a generator either
handles the structural class or it does not. `dilation = 1` and `groups = 1` for
all 157 layers, so neither discriminates any class; they are kept in the key to
make that explicit. GEMMs follow the LAYER_SHAPES convention: a `1x1`, stride-1,
unpadded conv with `ho = M`, `wo = 1`, `inc = K`, `oc = N`.

Layer numbers are the `#` capture-order index from LAYER_SHAPES (network order),
compacted as ranges.

## Unique shape classes

| class | type | kh x kw | stride | pad | dil | grp | layers | inc | oc | ho x wo | T | benchmark layers |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| S1 | spiking-GEMM | 1x1 | 1 | 0 | 1 | 1 | 86 | 384-3072 (384, 512, 768, 1024, 1536, 2048, 3072) | 10-3072 (10, 11, 384, 768, 1024, 3072) | 1x1, 64x1, 128x1 | 4, 10, 16, 32 | A02/spikformer_4_384 L5-12 (8); A07/spikinglm_t4 L1-72 (72); A08/vgg16_cifar10_loas L13 (1); B09/loas_vgg16 L13 (1); C01/sma_azo_vgg_cifar10_dvs L5-6 (2); C01/sma_azo_vgg_dvs128_gesture L5-6 (2) |
| S2 | spiking-Conv | 3x3 | 1 | 1 | 1 | 1 | 53 | 48-512 (48, 64, 96, 128, 192, 256, 384, 512) | 64-512 (64, 96, 128, 192, 256, 384, 512) | 2x2, 4x4, 8x8, 16x16, 32x32, 64x64 | 4, 10, 16, 32 | A02 L1-4 (4); A04/sdt_2_512 L1-4 (4); A08 L1-12 (12); B09/loas_resnet19 L2, L4-7, L9, L11-14, L16, L18-19 (13); B09/loas_vgg16 L1-12 (12); C01/cifar10_dvs L1-4 (4); C01/dvs128_gesture L1-4 (4) |
| S3 | spiking-Conv | 1x1 | 1 | 0 | 1 | 1 | 12 | 512, 2048 | 512, 2048 | 8x8 | 4 | A04/sdt_2_512 L5-16 (12) |
| S4 | spiking-Conv | 3x3 | 2 | 1 | 1 | 1 | 3 | 64, 128, 256 | 128, 256, 512 | 4x4, 8x8, 16x16 | 4 | B09/loas_resnet19 L1, L8, L15 (3) |
| S5 | spiking-Conv | 1x1 | 2 | 0 | 1 | 1 | 3 | 64, 128, 256 | 128, 256, 512 | 4x4, 8x8, 16x16 | 4 | B09/loas_resnet19 L3, L10, L17 (3) |

Five structural classes in total. Notes on why each exists and nothing else does:

- **S1** is the only GEMM class. It spans the widest `inc`/`oc` range of the
  campaign (`K` up to 3072 from A07's BERT `output_dense` layers) and three
  distinct `ho` values: `M = 1` for the per-sample classifier/FC heads,
  `M = 64` for A02's 8x8 token grid, `M = 128` for A07's token count.
- **S2** is the bulk conv case: 3x3, stride 1, "same" padding. 53 of 157 layers,
  contributed by seven of the eight workloads: five of the six registry ids (all
  but A07, whose 72 layers are all S1). It is the only class covering
  `ho x wo = 64x64` (the C01 DVS inputs) and `2x2` (the VGG tails).
- **S3** is A04's 1x1 attention/MLP convolutions. Structurally identical to S1 in
  `(kh, kw, stride, pad, dil, grp)` but typed `spiking-Conv`, not `spiking-GEMM`:
  `wo = 8`, not 1, so the loader and generators see a genuine 2-D output map.
  Kept as its own class for exactly that reason.
- **S4/S5** are the only stride-2 layers in the whole campaign: ResNet19's three
  downsampling `conv1`s (S4) and the three matching 1x1 projection shortcuts
  (S5). Both are B09/`loas_resnet19` only. `build_workload_from_trace` skips
  non-3x3/stride-1 convs via `exclusion_reason`, so S3, S4 and S5 are the classes
  where loader policy and generator capability must be checked separately in 1c.
- `padding` is fully determined by `(type, kh)` across all 157 layers: 3x3 convs
  use pad 1, every 1x1 conv and every GEMM uses pad 0. No 3x3-unpadded and no
  1x1-padded layer exists.

### Caveat carried from the source

LAYER_SHAPES records that conv `padding`, `dilation` and `groups` for A02-B09 are
**module-derived and not re-verified** against the delta capture metadata (which
does not store those fields); C01's values were read statically from the pinned
VGG8 constructors. The S1-S5 split therefore inherits that provenance: the
`stride` values come from `layer_params`, but `pad/dil/grp` do not come from the
traces themselves.

## Extremes

| quantity | min | max |
|---|---|---|
| `inc` | 48 - A02 L1 (`patch_embed_proj_conv1`) | 3072 - A07 L6, 12, 18, ... 72 (12x BERT `output_dense`) |
| `oc` | 10 - A08 L13, B09/loas_vgg16 L13, C01/cifar10_dvs L6 (CIFAR-10 / DVS heads; 11 for DVS128-Gesture) | 3072 - A07 L5, 11, 17, ... 71 (12x BERT `intermediate_dense`) |
| `ho x wo` tiles | 1 - A08 L13, B09/loas_vgg16 L13, C01 L5-6 (all `1x1` FC heads) | 4096 (64x64) - C01/cifar10_dvs L1 and C01/dvs128_gesture L1 |
| `T` | 4 - A02, A04, A07, B09/loas_resnet19, B09/loas_vgg16 | 32 - A08/vgg16_cifar10_loas |

Full observed sets: `ho x wo` tile counts `{1, 4, 16, 64, 128, 256, 1024, 4096}`;
`T` `{4, 10, 16, 32}`. `T = 32` is A08 alone, `T = 10` is C01/`sma_azo_vgg_cifar10_dvs`
alone, `T = 16` is C01/`sma_azo_vgg_dvs128_gesture` alone; every other workload is
`T = 4`.

Spatial-x-temporal work per layer (`ho*wo*T`) peaks on the same three layers.
Note this is **not** a proxy for generator cost: the measured section below shows
`tile_count` is per-sample and `T`-independent for four of the five generators.

| layer | class | ho x wo | T | `ho*wo*T` |
|---|---|---|---:|---:|
| C01/`sma_azo_vgg_dvs128_gesture` L1 `core_block2_0_0` | S2 | 64x64 | 16 | 65,536 |
| C01/`sma_azo_vgg_cifar10_dvs` L1 `core_block2_0_0` | S2 | 64x64 | 10 | 40,960 |
| A08/`vgg16_cifar10_loas` L1 `core_features_3` | S2 | 32x32 | 32 | 32,768 |

### The 131,072-tile SpinalFlow C01 heavy case (measured)

Resolved against the solve-stage export now staged at
`/work/nvme/bebv/yyu9/wt500_fig3cfg_step1c/` (`schedule_tiles.csv`, 738 rows,
`sha256sum -c` clean). `tile_count` there is defined as
`dram_num_steps * noc_num_steps * prod(spatial_factors)`
(`src/lays/nocsim/schedule/tiles.py:iter_node_tiles`), **per ONE sample**.

The pilot blocker (`HANDOFF.md:75`) is `layer_01_core_block2_0_0`, the C01
64x64 layer, at **131,072 tiles/sample** for SpinalFlow. Measured values for
that layer:

| arch | C01/cifar10_dvs (T=10) | C01/dvs128_gesture (T=16) |
|---|---:|---:|
| spinalflow, loas, ptb | 131,072 | 131,072 |
| gustavsnn | 327,680 | 524,288 |
| prosperity | INFEASIBLE | INFEASIBLE |

Two corrections to what shape data alone suggested:

1. **`T` is not a factor in `tile_count`.** Both C01 workloads give the same
   131,072 for SpinalFlow despite `T = 10` vs `T = 16`, so it is **not**
   `2 x (ho*wo*T)` and `T` does not enter the tile count at all. The reason is
   that the timestep range lives *inside* one tile: Python-side
   `NodeTileSpec.node_bound[DIM_T]` / `tile_offset[DIM_T]`
   (`src/lays/weight_trace_gen/__init__.py:40`), packed per tile by
   `spinalflow/native_bridge.py:37` and consumed on the native side as
   `struct TileSpec`'s `t_off, t_n`
   (`src/lays/weight_trace_gen/spinalflow/SpinalFlowGen.h:31`, looped at `:64`).
   Only gustavsnn's count varies with `T`, because its schedules tile the `T`
   dimension (C01 L1: 327,680 at `T=10` vs 524,288 at `T=16`).

   How 131,072 factorizes into `dram_num_steps x noc_num_steps x
   prod(spatial_factors)` is **undetermined from the staged export**:
   `schedule_tiles.csv` carries only `tile_count` and `wave_width`, and
   `manifest.json` carries schedule paths and hashes, not loop factors. The
   schedule JSONs are not on this host. Step 1c, which reads them, can settle
   it; `ho*wo = 4096` is a lower bound on the spatial part from the layer shape
   alone.
2. **131,072 is not the campaign maximum.** Per-arch maxima over the 738
   scheduled (arch, layer) pairs:

| arch | pairs | min tiles | max tiles | sum tiles/sample |
|---|---:|---:|---:|---:|
| prosperity | 134 | 160 | **1,179,648** | 43,914,048 |
| gustavsnn | 151 | 20 | 524,288 | 13,318,550 |
| spinalflow | 151 | 5 | 131,072 | 3,743,258 |
| loas | 151 | 5 | 131,072 | 3,743,258 |
| ptb | 151 | 5 | 131,072 | 3,743,258 |

Prosperity has no schedule for either C01 L1: all 17 of its INFEASIBLE pairs are
high-`T` class-S2 convs (C01/cifar10_dvs L1-4 at `T=10`, C01/dvs128_gesture L1-4
at `T=16`, A08 L1-9 at `T=32`). Mapping those to a cause is step 1c's job.

The real worst cases are **prosperity on A07's BERT GEMMs** (class S1):
1,179,648 tiles on each of 24 layers (`intermediate_dense` / `output_dense`),
9.0x the SpinalFlow case that already ran >= 23 min at ~15 GB RSS on one
sample, plus 294,912 tiles on 48 more A07 layers. gustavsnn's own C01 L1 is
4.0x the SpinalFlow figure. Any budget sized on 131,072 is therefore short by
roughly an order of magnitude for prosperity/A07.

Work is extremely top-heavy: 68,462,372 tiles/sample in total, of which the
top 10 (arch, layer) pairs are 17.2% and the top 50 are 54.7%. Shard weighting
by `tile_count` per (arch, layer) is not an optimization but a requirement, and
it must be per (arch, layer) and not per shape class: the heavy C01 layer sits
in S2 with 52 cheap layers, and the heavy A07 GEMMs sit in S1 with 85 others
including the trivial 5-tile classifier heads.

### Scheduled-layer count: 151, not 157

`schedule_tiles.csv` carries 151 layers per arch (prosperity 134 = 151 - 17
INFEASIBLE; 151 x 5 = 755 total pairs, matching the manifest's "755 valid",
minus the 17 infeasible leaves the 738 rows exported). The 6 of 157 captured
layers with no schedule are exactly classes **S4 and S5**: B09/`loas_resnet19`
L1, L8, L15 (3x3 stride-2) and L3, L10, L17 (1x1 stride-2), consistent with
`build_workload_from_trace` skipping non-3x3/stride-1 convs via
`exclusion_reason`. S1, S2 and S3 are scheduled in full (86 + 53 + 12 = 151).

Also confirmed from the same export: gustavsnn `wave_width` is 4 on 145 of 151
schedules, 2 on five and 1 on one, so the per-schedule spatial product, never a
flat 4, is the correct invariant (`HANDOFF.md` CRITICAL fact).

## Sanity rule: every layer lands in exactly one class

The collapse key is a function of each layer's recorded
`(type, kh, kw, stride, padding, dilation, groups)`, so each of the 157 layers
maps to exactly one class, and no class is empty. Per-class counts:

| class | layers |
|---|---:|
| S1 spiking-GEMM 1x1 s1 p0 | 86 |
| S2 spiking-Conv 3x3 s1 p1 | 53 |
| S3 spiking-Conv 1x1 s1 p0 | 12 |
| S4 spiking-Conv 3x3 s2 p1 | 3 |
| S5 spiking-Conv 1x1 s2 p0 | 3 |
| **total** | **157** |

86 + 53 + 12 + 3 + 3 = **157**, matching the 157 captured layers in LAYER_SHAPES
(A02 12, A04 16, A07 72, A08 13, B09/loas_resnet19 19, B09/loas_vgg16 13,
C01/cifar10_dvs 6, C01/dvs128_gesture 6). Per-benchmark cross-check of the same
partition:

| workload | S1 | S2 | S3 | S4 | S5 | total |
|---|---:|---:|---:|---:|---:|---:|
| A02/`spikformer_4_384` | 8 | 4 | 0 | 0 | 0 | 12 |
| A04/`sdt_2_512` | 0 | 4 | 12 | 0 | 0 | 16 |
| A07/`spikinglm_t4` | 72 | 0 | 0 | 0 | 0 | 72 |
| A08/`vgg16_cifar10_loas` | 1 | 12 | 0 | 0 | 0 | 13 |
| B09/`loas_resnet19` | 0 | 13 | 0 | 3 | 3 | 19 |
| B09/`loas_vgg16` | 1 | 12 | 0 | 0 | 0 | 13 |
| C01/`sma_azo_vgg_cifar10_dvs` | 2 | 4 | 0 | 0 | 0 | 6 |
| C01/`sma_azo_vgg_dvs128_gesture` | 2 | 4 | 0 | 0 | 0 | 6 |
| **total** | **86** | **53** | **12** | **3** | **3** | **157** |

The S1/S2+S3+S4+S5 column sums also reproduce the GEMM-vs-Conv split in
LAYER_SHAPES' cross-benchmark summary (GEMM = S1; Conv = S2+S3+S4+S5), so the
two independent partitions of the 157 layers agree.

LAYER_SHAPES separately reports **49** distinct `(kh, kw, oc, inc, ho, wo, t)`
classes; this document's 5 classes are the coarser structural collapse of those
49 (dimensions folded into ranges), not a competing count.

## Generator coverage (step 1c)

Evidence and scope:

- The staged export at `/work/nvme/bebv/yyu9/wt500_fig3cfg_step1c/` is
  checksum-clean: `SHA256SUMS` reports `OK` for `manifest.json`,
  `manifest_digest.csv`, and `schedule_tiles.csv`. The manifest has 755 valid
  (arch, layer) pairs and 30 loader exclusions; its 17 `prosperity`
  `INFEASIBLE` pairs are included in the valid-pair set but have no schedule.
  `schedule_tiles.csv` therefore has 738 schedule rows.
- `src/lays/weight_trace_gen/trace.py:100-117` is the shared loader gate:
  only 1x1 or 3x3 kernels with stride 1 and positive output dimensions are
  replayable. Thus S4/S5 are loader-policy exclusions, not a claim that the
  native kernels cannot loop over those dimensions.
- LoAS, PTB, and SpinalFlow pass arbitrary tile `KH/KW`, `CIN`, `T`, and
  `COUT` bounds through their packers (`loas/native_bridge.py:26-42`,
  `ptb/native_bridge.py:26-42`, `spinalflow/native_bridge.py:26-42`) and loop
  over the corresponding dimensions in `*Gen.h` (LoAS `LoASGen.h:28-35,54-76`;
  PTB `PTBGen.h:37-47,83-112`; SpinalFlow `SpinalFlowGen.h:26-33,52-74`).
  PTB's `TW_SIZE = 8` is an internal cycle-grouping limit, not a class
  exclusion; the T=32 S2 workload is scheduled.
- Prosperity's native path accepts `KH/KW`, `HO/WO`, and `T`, while its bridge
  expands resident CIN ranges into one-CIN calls (`ProsperityGen.h:46-54,83-109`;
  `prosperity/native_bridge.py:49-68`). GustavSNN accepts `KH/KW`, `HO/WO`,
  and `CIN` and requires a positive schedule-derived `wave_width`
  (`GustavGen.h:31-39,76-110`; `gustavsnn/native_bridge.py:133-138`).

### Coverage matrix

`covered` means every layer in the class has a feasible schedule for that
generator. `excluded` gives the measured reason and count. Counts are layers
per generator; the Prosperity S2 cell is mixed because 17 of its 53 class
layers are solver-infeasible.

| generator | S1 GEMM 1x1 s1p0 | S2 Conv 3x3 s1p1 | S3 Conv 1x1 s1p0 | S4 Conv 3x3 s2p1 | S5 Conv 1x1 s2p0 |
|---|---|---|---|---|---|
| loas | **covered** (86/86) | **covered** (53/53) | **covered** (12/12) | **excluded** — loader stride != 1 (3) | **excluded** — loader stride != 1 (3) |
| ptb | **covered** (86/86) | **covered** (53/53) | **covered** (12/12) | **excluded** — loader stride != 1 (3) | **excluded** — loader stride != 1 (3) |
| spinalflow | **covered** (86/86) | **covered** (53/53) | **covered** (12/12) | **excluded** — loader stride != 1 (3) | **excluded** — loader stride != 1 (3) |
| prosperity | **covered** (86/86) | **excluded** — 17 high-T `INFEASIBLE` pairs; 36/53 covered | **covered** (12/12) | **excluded** — loader stride != 1 (3) | **excluded** — loader stride != 1 (3) |
| gustavsnn | **covered** (86/86) | **covered** (53/53) | **covered** (12/12) | **excluded** — loader stride != 1 (3) | **excluded** — loader stride != 1 (3) |

The 30 `excluded_pairs` are exactly the six B09/`loas_resnet19` S4/S5
layers (three of each) crossed with the five generators. The 17 Prosperity
infeasibilities are exactly the high-T S2 convolutions: C01 L1-4 at T=10,
C01 L1-4 at T=16, and A08 L1-9 at T=32. The manifest establishes the
statuses; the reason for the Prosperity solver failure is not established and
must not be labeled as psum pressure without further evidence.

No coverage cell is unknown: the manifest and loader classify all 785
generator/layer pairs. What remains unknown is the Prosperity infeasibility
mechanism and the DRAM x NoC x spatial loop-factorization behind `tile_count`.
The schedule JSONs are not on this host; `manifest.json` has their paths and
hashes, while `schedule_tiles.csv` carries only `tile_count` and `wave_width`.
A second DeltaAI export would need the referenced schedule JSONs, the solver
inputs/diagnostics for all 17 Prosperity `INFEASIBLE` pairs, and the explicit
loop factors used to derive each tile count. Do not infer those factors here.

### Cost-ceiling correction

The campaign ceiling is not the 131,072-tile SpinalFlow C01 case. Prosperity
reaches **1,179,648 tiles/sample** on each of 24 A07 BERT GEMM layers (9.0x
the 131,072 case, which took at least 23 minutes and about 15 GB RSS for one
sample), plus 294,912 tiles on 48 more A07 layers. GustavSNN reaches 524,288
tiles/sample on C01 L1 (4.0x). Prosperity contributes 43,914,048
tiles/sample, 64% of the 68,462,372 campaign total. Prosperity has no schedule
for either C01 L1 because both are infeasible, so its true ceiling is A07,
not C01; a budget based on 131,072 is roughly an order of magnitude short.

The GustavSNN `wave_width` is the per-schedule NodeLevel spatial product, not
a flat 4: the export has width 4 on 145 schedules, 2 on five, and 1 on one.
