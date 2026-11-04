# Artifact-generation prompt: `cin_khkw_concat` versus `khkw_split`

This file is a self-contained prompt. Hand everything below the rule to an
agent on another machine or another account; it carries the design story, every
measured number, and the accuracy constraints the artifact must respect. The
reader needs **no repository access**: there is nothing to clone, build or run,
and no number to look up. Every figure the artifact may show is inline below.

Scope note for the dispatcher: this document is the deliverable. It is a prompt
to be executed elsewhere, not the artifact itself.

---

## Task

Build an **interactive web artifact** that explains two cache address-indexing
layouts for a weight cache, and presents a measured comparison between them.

All content is in this prompt. Do not look for a repository, do not run code,
and do not add numbers from anywhere else. Visual and layout design is yours;
the content and the accuracy constraints are not.

### 1. The system being indexed

A simulated two-level weight cache feeds a 16-core accelerator running
convolutional spiking-neural-network layers. One layer's weights form a 4-D
tensor indexed by `(kh, kw, cin, cout)`: kernel row, kernel column, input
channel, output channel.

- Weights are fetched in **blocks**: `cin_block x cout_block` weights of
  `weight_bytes` each form one **cache line**.
- Set and tag are **not bit fields**. A *layout* flattens the blocked
  coordinate into a dense integer **line id**, and the cache then applies
  `set = line_id % num_sets`, `tag = line_id / num_sets`.
- So a layout is a choice of **digit nesting**: which coordinate varies
  fastest in the line id, hence which coordinate supplies the low index bits.
- Each core owns a contiguous slice of `cout` for the duration of a tile, so a
  single core's index entropy comes from `cin` and the kernel position, not
  from `cout` varying inside its own slice.

### 2. Layout A — `khkw_split` (the existing layout)

Let `pos = kh * KW + kw` be the kernel position, `n_pos = KH * KW`. The layout
splits the position into two digits and nests four digits, outermost first:

```
[ pos_hi | cout_blk | cin_blk | pos_lo ]        pos_lo radix = min(8, KH*KW)
                                                pos_hi radix = ceil(n_pos / pos_lo radix)
line = pos_hi*(n_cout_blocks*n_cin_blocks*pos_lo_radix)
     + cout_blk*(n_cin_blocks*pos_lo_radix)
     + cin_blk*pos_lo_radix
     + pos_lo
```

Two consequences worth showing:

- **For a 3x3 kernel** (`n_pos = 9`) the split is **ragged**: `pos_lo` has radix
  8 and `pos_hi` radix 2, so the position pair occupies **16 slots for 9 real
  positions**. The id space is about `16/9 = 1.78x` larger than the number of
  lines that exist. (Measured below: 1.776x-1.778x in every configuration, since
  the implementation bounds the id space by the largest id actually reachable
  rather than by the raw radix product.)
- **For `KH = KW = 1`** (a GEMM-shaped layer) the split collapses:
  `min(8, 1) = 1`, both position digits vanish, and the line id degenerates to
  `cout_blk * n_cin_blocks + cin_blk`. Kernel position costs nothing there; this
  corrects a common assumption that the position digits waste index bits on
  1x1 layers.

### 3. Layout B — `cin_khkw_concat` (the proposed layout)

Concatenate the input-channel block and the kernel position into **one dense
digit**, CIN-major and position-minor:

```
d = cin_blk * (KH*KW) + pos            d in [0, D),  D = n_cin_blocks * KH*KW
```

Then nest **two** digits only, with no split anywhere:

```
[ cout_blk | d ]                       line = cout_blk * D + d
```

- Every kernel position lives in the same dense digit. A 3x3 kernel uses
  exactly 9 values, with no unused radix combination and no special case for
  the ninth position, so the id space is the **exact product**
  `n_cout_blocks * D`.
- **Why no explicit split.** A first draft split `d` as
  `[d_hi | cout | d_lo]` with `d_lo`'s radix equal to the L1 set count. That
  fails on limited-channel layers: a core's `cout` is pinned per tile, so if
  `D < num_sets` a pure-`d` index can only reach `D` of the sets. A 128-input
  GEMM layer with `cin_block = 16` has 8 CIN blocks, so `d in [0, 8)` would pin
  the index to 8 of 32 L1 sets and strand 75% of L1.
- **How the two-digit form fixes that instead.** The modulo placement does the
  work: `set = (cout_blk*D + d) % num_sets`. When `D < num_sets`, successive
  `cout` blocks shift the dense band `[0, D)` in steps whose greatest common
  divisor with `num_sets` never exceeds `D`, so the union over a core's own
  `cout` blocks covers every set. No configuration knob, no unreachable-index
  warning. Two regimes to show: `D >= num_sets`, where the index comes from `d`
  alone (the intended policy), and `D < num_sets`, where `cout` tops the index
  up through the modulo.
- **Residual limit, independent of any layout**: a core whose
  (cout-slice x cin x position) footprint has fewer distinct lines than there
  are sets cannot fill them under any mapping.

### 4. The structural identity — the layouts can only differ above 8 positions

Substitute `KH*KW <= 8` into Layout A: `pos_lo` radix becomes `KH*KW`, so
`pos_lo = pos` and `pos_hi = 0`, and

```
line = cout_blk*(n_cin_blocks*n_pos) + cin_blk*n_pos + pos
```

which is exactly `cout_blk*D + d` with `D = n_cin_blocks*n_pos`. **The two
layouts produce identical line ids, hence identical placement, whenever
`KH*KW <= 8.`** Only kernels with more than 8 positions - 3x3 being the first -
can behave differently at all. Every measured layer below is 3x3. This identity
is a good thing for the artifact to make visible: it bounds where any difference
can come from.

### 5. The measured comparison

**What was run.** 20 pre-existing weight-access trace streams - 4 layers x 5
samples - replayed through the simulator under **2 layouts x 3 line sizes** =
120 simulations. No trace was regenerated; both layouts replay the same streams,
so the access sequence is identical and only the line ids differ.

**Layers** (all 3x3 kernels, `(KH, KW, CIN, COUT)`), and the identical L1 access
count each produces under both layouts (mean of 5 samples):

| Tag | Network / layer | Shape | Tiles | L1 accesses (both layouts) |
|---|---|---|---|---|
| V8 | VGG16 `layer_08_features_27` | 3x3x512x512 | 128 | 2,481,126.4 |
| V9 | VGG16 `layer_09_features_30` | 3x3x512x512 | 128 | 4,954,009.6 |
| R9 | ResNet19 `layer_09_layer2_0_conv2` | 3x3x256x128 | 128 | 1,234,278.4 |
| R16 | ResNet19 `layer_16_layer3_0_conv2` | 3x3x512x256 | 64 | 1,999,129.6 |

**Fixed cache configuration** for every one of the 120 runs: 16 cores; L1
16,384 B, 8-way, private per core; L2 524,288 B, 16-way, **1 bank**,
non-inclusive; LRU at both levels; **no prefetching at either level**; L1 hit
latency 0, L2 hit latency 2, L2 miss latency 24; L1 MSHRs 16, L2 MSHRs 32;
`cout_block = 4`, `weight_bytes = 1`.

**The three line sizes** vary `cin_block` only, which changes the geometry:

| Line size | `cin_block` | L1 lines | L1 sets | L2 lines | L2 sets |
|---|---|---|---|---|---|
| 16 B | 4 | 1024 | 128 | 32768 | 2048 |
| 32 B | 8 | 512 | 64 | 16384 | 1024 |
| 64 B | 16 | 256 | 32 | 8192 | 512 |

**Where each configuration sits in the `D` regime**, with the id space of each
layout (`concat` = `n_cout_blocks * D` exactly; `split` = one past its largest
reachable id):

| Layer | Line | CIN blocks | COUT blocks | D | L1 sets | L2 sets | split id space | concat id space | ratio |
|---|---|---|---|---|---|---|---|---|---|
| V8 | 16 B | 128 | 128 | 1152 | 128 | 2048 | 262137 | 147456 | 1.778 |
| V8 | 32 B | 64 | 128 | 576 | 64 | 1024 | 131065 | 73728 | 1.778 |
| V8 | 64 B | 32 | 128 | 288 | 32 | 512 | 65529 | 36864 | 1.778 |
| V9 | 16 B | 128 | 128 | 1152 | 128 | 2048 | 262137 | 147456 | 1.778 |
| V9 | 32 B | 64 | 128 | 576 | 64 | 1024 | 131065 | 73728 | 1.778 |
| V9 | 64 B | 32 | 128 | 288 | 32 | 512 | 65529 | 36864 | 1.778 |
| R9 | 16 B | 64 | 32 | 576 | 128 | 2048 | 32761 | 18432 | 1.777 |
| R9 | 32 B | 32 | 32 | 288 | 64 | 1024 | 16377 | 9216 | 1.777 |
| R9 | 64 B | 16 | 32 | 144 | 32 | 512 | 8185 | 4608 | 1.776 |
| R16 | 16 B | 128 | 64 | 1152 | 128 | 2048 | 131065 | 73728 | 1.778 |
| R16 | 32 B | 64 | 64 | 576 | 64 | 1024 | 65529 | 36864 | 1.778 |
| R16 | 64 B | 32 | 64 | 288 | 32 | 512 | 32761 | 18432 | 1.777 |

Note for the artifact: **`D >= L1 sets` in all twelve configurations**, so the
measurement never exercises the `D < num_sets` top-up regime at L1. At L2,
`D < L2 sets` throughout, so the `cout` top-up is what supplies the upper L2
index there.

#### 5a. Headline table — mean of the 5 samples per cell

Hit rates are arithmetic means of the per-sample rates, in percent; deltas are
in percentage points (pp). Every delta is **concat minus split**. Cycles are
simulated cycles.

| Layer | Line | split cycles | concat cycles | d cycles | d % | split L1 % | concat L1 % | d L1 pp | split L2 % | concat L2 % | d L2 pp | split DRAM MB | concat DRAM MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V8 | 16 B | 607,947.2 | 572,251.2 | -35,696.0 | **-5.872%** | 88.3315 | 83.2607 | -5.0708 | 5.7153 | 64.3441 | +58.6288 | 4.361 | 2.358 |
| V8 | 32 B | 406,182.4 | 522,844.8 | +116,662.4 | **+28.722%** | 93.7725 | 84.1647 | -9.6078 | 0.9307 | 81.1927 | +80.2620 | 4.889 | 2.359 |
| V8 | 64 B | 282,854.4 | 328,931.2 | +46,076.8 | **+16.290%** | 96.8572 | 91.2333 | -5.6239 | 0.0000 | 83.0189 | +83.0189 | 4.981 | 2.359 |
| V9 | 16 B | 816,334.4 | 1,117,193.6 | +300,859.2 | **+36.855%** | 93.7230 | 82.7630 | -10.9600 | 0.1235 | 82.7294 | +82.6058 | 4.968 | 2.359 |
| V9 | 32 B | 563,873.6 | 655,102.4 | +91,228.8 | **+16.179%** | 96.8576 | 91.2343 | -5.6233 | 0.0000 | 83.0189 | +83.0189 | 4.981 | 2.359 |
| V9 | 64 B | 437,409.6 | 418,900.8 | -18,508.8 | **-4.231%** | 98.4288 | 95.6172 | -2.8116 | 0.0000 | 83.0189 | +83.0189 | 4.981 | 2.359 |
| R9 | 16 B | 107,652.4 | 107,652.4 | 0.0 | **0.000%** | 98.4894 | 98.4894 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.295 | 0.295 |
| R9 | 32 B | 92,394.4 | 92,394.4 | 0.0 | **0.000%** | 99.2447 | 99.2447 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.295 | 0.295 |
| R9 | 64 B | 84,762.4 | 84,762.4 | 0.0 | **0.000%** | 99.6223 | 99.6223 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.295 | 0.295 |
| R16 | 16 B | 374,619.2 | 492,643.2 | +118,024.0 | **+31.505%** | 92.3056 | 80.9625 | -11.3431 | 1.0326 | 80.5885 | +79.5559 | 2.435 | 1.179 |
| R16 | 32 B | 252,008.8 | 308,811.2 | +56,802.4 | **+22.540%** | 96.1079 | 89.1794 | -6.9285 | 0.0329 | 82.9562 | +82.9233 | 2.489 | 1.180 |
| R16 | 64 B | 188,837.6 | 190,733.6 | +1,896.0 | **+1.004%** | 98.0533 | 94.5698 | -3.4835 | 0.0000 | 83.0189 | +83.0189 | 2.490 | 1.180 |

#### 5b. Misses and DRAM traffic against the compulsory floor

"Distinct lines" is the layer's total line count at that blocking
(`n_cout_blocks * D`), which is the same under both layouts because both
flattens are bijections over the same block grid. It is the **floor** on DRAM
accesses: a run cannot fetch fewer than one per distinct line.

| Layer | Line | distinct lines (floor) | split L1 misses | concat L1 misses | concat / split | split DRAM accesses | / floor | concat DRAM accesses | / floor |
|---|---|---|---|---|---|---|---|---|---|
| V8 | 16 B | 147,456 | 289,049.6 | 415,616.0 | 1.44x | 272,537.6 | 1.848 | 147,353.6 | 0.999 |
| V8 | 32 B | 73,728 | 154,214.4 | 392,320.0 | 2.54x | 152,780.8 | 2.072 | 73,728.0 | 1.000 |
| V8 | 64 B | 36,864 | 77,824.0 | 217,088.0 | 2.79x | 77,824.0 | 2.111 | 36,864.0 | 1.000 |
| V9 | 16 B | 147,456 | 310,912.0 | 853,836.8 | 2.75x | 310,528.0 | 2.106 | 147,456.0 | 1.000 |
| V9 | 32 B | 73,728 | 155,648.0 | 434,176.0 | 2.79x | 155,648.0 | 2.111 | 73,728.0 | 1.000 |
| V9 | 64 B | 36,864 | 77,824.0 | 217,088.0 | 2.79x | 77,824.0 | 2.111 | 36,864.0 | 1.000 |
| R9 | 16 B | 18,432 | 18,432.0 | 18,432.0 | 1.00x | 18,432.0 | 1.000 | 18,432.0 | 1.000 |
| R9 | 32 B | 9,216 | 9,216.0 | 9,216.0 | 1.00x | 9,216.0 | 1.000 | 9,216.0 | 1.000 |
| R9 | 64 B | 4,608 | 4,608.0 | 4,608.0 | 1.00x | 4,608.0 | 1.000 | 4,608.0 | 1.000 |
| R16 | 16 B | 73,728 | 153,804.8 | 380,646.4 | 2.47x | 152,217.6 | 2.065 | 73,715.2 | 1.000 |
| R16 | 32 B | 36,864 | 77,798.4 | 216,294.4 | 2.78x | 77,772.8 | 2.110 | 36,864.0 | 1.000 |
| R16 | 64 B | 18,432 | 38,912.0 | 108,544.0 | 2.79x | 38,912.0 | 2.111 | 18,432.0 | 1.000 |

Two facts this table supports, both safe to state:

- **`cin_khkw_concat` reaches the compulsory DRAM floor in every measured
  configuration** (ratio 0.999-1.000; the 0.999 is sample-to-sample variation in
  how much of the layer a sample touches). Its DRAM bytes equal the layer's
  weight footprint exactly - `9 * CIN * COUT` bytes: 2,359,296 for V8 and V9,
  1,179,648 for R16, 294,912 for R9 - and are therefore the same at all three
  line sizes.
- **`khkw_split` fetches each line about twice**: 1.85x to 2.11x the floor on
  every non-tying configuration. It re-reads from DRAM what it has already
  evicted.
- Every L1 miss becomes exactly one L2 access in this data, so "L1 misses" and
  "L2 accesses" are the same column.

#### 5c. Where the cycles go

Stall cycles, mean of 5 samples. `stall_channel` is waiting on the DRAM
channel; `stall_l2_port` is waiting for the single L2 bank's port.

| Layer | Line | split stall_total | concat stall_total | split stall_channel | concat stall_channel | split stall_l2_port | concat stall_l2_port |
|---|---|---|---|---|---|---|---|
| V8 | 16 B | 7,248,076.8 | 6,676,940.8 | 7,132,190.4 | 3,888,944.0 | 55,262.4 | 2,672,609.6 |
| V8 | 32 B | 4,019,840.0 | 5,886,438.4 | 3,989,739.2 | 1,931,008.0 | 5,947.2 | 3,866,865.6 |
| V8 | 64 B | 2,046,592.0 | 2,783,820.8 | 2,033,984.0 | 962,304.0 | 0.0 | 1,761,636.8 |
| V9 | 16 B | 8,109,388.8 | 12,923,136.0 | 8,087,446.4 | 3,838,171.2 | 2,016.0 | 8,951,411.2 |
| V9 | 32 B | 4,070,016.0 | 5,529,676.8 | 4,057,408.0 | 1,920,768.0 | 0.0 | 3,512,652.8 |
| V9 | 64 B | 2,046,592.0 | 1,750,451.2 | 2,033,984.0 | 962,304.0 | 0.0 | 704,067.2 |
| R9 | 16 B | 490,208.0 | 490,208.0 | 483,696.0 | 483,696.0 | 0.0 | 0.0 |
| R9 | 32 B | 246,080.0 | 246,080.0 | 241,824.0 | 241,824.0 | 0.0 | 0.0 |
| R9 | 64 B | 123,968.0 | 123,968.0 | 120,864.0 | 120,864.0 | 0.0 | 0.0 |
| R16 | 16 B | 3,995,801.6 | 5,884,185.6 | 3,969,692.8 | 1,926,627.2 | 6,056.8 | 3,888,290.4 |
| R16 | 32 B | 2,034,035.2 | 2,942,873.6 | 2,027,484.8 | 960,700.8 | 136.8 | 1,935,856.8 |
| R16 | 64 B | 1,023,296.0 | 1,053,632.0 | 1,016,992.0 | 481,152.0 | 0.0 | 533,978.4 |

### 6. The mechanism to tell, and the mechanism NOT to tell

**Tell this.** The concatenated layout trades L1 hit rate for L2 hit rate and
DRAM traffic. Its L1 hit rate falls in every non-tying configuration (-2.8 to
-11.3 pp) and its L1 misses rise 1.4x-2.8x, but those extra misses are nearly
all caught by L2 - whose hit rate rises from near zero to 64-83% - so DRAM
traffic drops to the compulsory floor, roughly halving it. In cycle terms the
stall moves off the DRAM channel and onto the single L2 port: `stall_channel`
falls by about half or more in every non-tying cell while `stall_l2_port` rises
from essentially zero to between 0.5M and 9.0M cycles. The net sign is whichever
of those two is larger.

**Do not tell a predictive rule.** The sign of the cycle delta does not follow
any single column in these twelve cells. V8/16 B loses 5.07 pp of L1 hit rate
and **wins** 5.9%, while V8/64 B loses 5.62 pp and **loses** 16.3%; V9/64 B has
the same 2.79x miss multiple as V9/32 B and V8/64 B yet is the one cell of the
three that wins. State the per-cell outcomes and the mechanism; do not fit a
rule that says when concat wins, and do not present a geomean as the verdict.

**The R9 tie, which must be explained and not hidden.** R9 is identical between
the layouts in every column, at all three line sizes. The reason is visible in
5b: for R9 the DRAM accesses equal the distinct-line floor under *both* layouts,
and L2 hits are zero, so no line is ever fetched twice - every miss is a first
touch. The number of first touches is the number of distinct lines, which is the
same under any bijective flatten. With no re-fetch to rearrange, the two layouts
cannot differ, so cycles, hit rates and bytes match exactly. R9 is the layer
whose per-core footprint fits, not a layer with no reuse: its L1 hit rate is
98.5-99.6%.

### 7. The conclusions to present, with losses as prominent as wins

Of the 12 (layer, line size) cells, on mean simulated cycles:

- **`cin_khkw_concat` loses in 7**: V9/16 B +36.855%, R16/16 B +31.505%,
  V8/32 B +28.722%, R16/32 B +22.540%, V8/64 B +16.290%, V9/32 B +16.179%,
  R16/64 B +1.004%.
- **It wins in 2**: V8/16 B -5.872%, V9/64 B -4.231%.
- **It ties in 3**: all three R9 cells, exactly 0.000%.

The honest one-line summary: *on these layers and this cache configuration the
concatenated layout is mostly slower, while cutting DRAM traffic roughly in
half.* Any framing that leads with the DRAM win and buries the cycle losses is
wrong for this data.

### 8. What the artifact should be

An interactive explainer page, with roughly these parts. Pick the visual
language, the component set and the layout yourself; what follows is content
structure, not pixel design.

1. **The two flattens, shown visually.** A reader should be able to see the
   digit nesting of each layout and watch where a given `(kh, kw, cin, cout)`
   lands - the line id, and the set after the modulo. Making the digits
   interactive (change the shape, the blocking or the set count and watch the
   mapping move) is the single most useful thing this artifact can do. Showing
   `khkw_split`'s 16-slots-for-9-positions raggedness next to `concat`'s dense
   9 is worth a panel of its own.
2. **The structural identity.** Let the reader set `KH*KW <= 8` and see the two
   layouts collapse onto the same line ids, which explains why only 3x3-and-up
   kernels appear in the measurement.
3. **The comparison data**, from the tables in section 5: per-cell cycles, L1
   and L2 hit rates, and DRAM bytes, with a metric toggle or one chart per
   metric, and the per-cell deltas visible with their sign. 12 cells is small
   enough to show whole; do not aggregate them away.
4. **The mechanism**, section 6: the L1-for-L2 trade, the DRAM floor, the stall
   moving from the channel to the L2 port, and the R9 tie.
5. **Limitations**, section 9, as a real section and not a footnote.

### 9. Limitations the artifact must state

- **Four layers, five samples, three blockings, one cache configuration.** 120
  simulations in total, all on 3x3 convolution layers of two networks. Nothing
  here establishes behavior for other workloads, other layer shapes, other
  cache geometries, or other replacement and prefetch policies.
- **No prefetching anywhere**, and **one L2 bank**. The cycle result hinges on
  L2 port contention, which a multi-bank L2 would change; that was not measured.
- **`D >= L1 sets` in every measured cell**, so the `D < num_sets` modulo
  top-up - the argument that motivated the two-digit design - is exercised at
  L2 only and never at L1. The limited-channel case that the design reasoning
  is about is therefore *not* what these numbers test.
- **No GEMM-shaped (1x1) measurement exists.** By the identity in section 4
  the two layouts are provably identical there, so there is nothing to measure,
  but do not present that as an experimental result - it is algebra.
- **Hit rates are means of per-sample rates**, not pooled hit/access ratios.
- **Cycles are simulated cycles** from one simulator; there is no silicon, no
  area or power number, and no wall-clock claim.
- Do not extrapolate, do not rank the layouts in general, and do not introduce
  any number that is not in this prompt.

### 10. Reporting back

Hand back the artifact plus a short note listing: which numbers you presented
and where each came from in this prompt, anything in sections 6, 7 or 9 you
could not fit and why, and any place where you felt the data was ambiguous.
If something here looks internally inconsistent, say so rather than smoothing
it over in the artifact.
