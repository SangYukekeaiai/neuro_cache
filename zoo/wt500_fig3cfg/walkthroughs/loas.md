# Generator walkthrough: LOAS

Step 3 of `docs/plans/2026-11-10-wt500-restart-plan.md`, arch 1 of 5.

This document is in four parts, logic first:

1. **How a LoAS weight trace is generated** - the model, no code.
2. **Worked examples at the logic level** - real measured numbers, hand-checkable.
3. **Where this lives in the code** - the implementation path.
4. **Caveats** - what may be wrong or fragile.

Everything measured here was run on this host against the finalized
`zoo/wt500_fig3cfg/arch.yaml` and `zoo/wt500_fig3cfg/mapspaces/loas.yaml`
(unchanged by the user's finalization) and the real n=500 captures under
`examples/input_trace/delta/`. Every number is measured, not illustrative.

## 1. How a LoAS weight trace is generated (the logic)

### 1.1 What the weights of a layer are

A layer's weights are one 4-D tensor indexed by
`(kh, kw, cin, cout)`: for each position in the convolution kernel, for each
input channel, the multiplier that feeds each output channel. A fully
connected layer is the degenerate case with a 1x1 kernel, so the same four
coordinates describe both. The captured layer dimensions give the extent of
each axis; nothing about spikes or timesteps appears in the weight tensor,
because a weight is reused at every timestep.

One **weight line** is the smallest unit the memory system moves. A line holds
a small rectangular block of that tensor - a range of input channels by a range
of output channels, at one kernel position - so a line is named by
`(kh, kw, cin_block, cout_block)`, and the blocking decides how many weights
travel together.

The important consequence, and the reason the trace looks the way it does:
**the trace does not contain addresses.** It contains those four logical
coordinates. The address of a weight is derived later, when the cache
simulator replays the trace under a chosen blocking and layout. That is
deliberate - it makes the layout a swept parameter rather than a property baked
into the trace corpus, so one trace replayed under several blockings is several
different demand profiles. Four layouts exist to be compared this way
(block-packed, split-CIN, KH/KW-split, CIN-KH/KW-concatenated).

So "what address does this record read" is a question with one answer per
layout, and the trace is deliberately one step upstream of it. Section 2 shows
the arithmetic for the block-packed layout and what changes under a different
blocking.

### 1.2 What the schedule carves, and what a tile MEANS

The scheduler is handed the layer's dimensions, the hardware (16 nodes, 4 PEs
each, with per-node and shared buffer capacities), and a mapspace saying which
dimensions a node may hold resident at once. For LoAS the mapspace says: hold
the **whole kernel**, **all input channels** and **all timesteps** resident,
fan **output channels** across PEs, and hold **no output pixels** resident.

That last point is what defines a LoAS tile. Because output pixels cannot be
resident, the layer is cut so that **one tile is one output pixel** - and
within that pixel, one slab of output channels. Concretely a tile means:

> *one output pixel `(ho, wo)`, one contiguous run of output channels
> `[cout_off, cout_off + cout_n)`, with the entire kernel, the entire input
> channel range and the entire timestep range available locally.*

The work is then spread two ways. Output channels are **fanned spatially**:
each core gets its own slab of `cout`, and all cores work the same pixel at the
same time. Everything that does not fit resident - the remaining output
channels and all the output pixels - becomes **sequential steps** over the
shared buffer and off-chip memory. The number of tiles is therefore
`(off-chip steps) x (shared-buffer steps) x (cores)`, and every tile is a
`(pixel, channel-slab, core)` triple.

Two useful consequences:

- All cores in one step hold the **same** pixel and the **same** input-channel
  range, so they fetch the same kernel positions and the same input channels in
  the same order. They differ only in which output channels they fetch.
- The input spike data for a pixel is read once per tile, and the timestep range
  is entirely inside the tile, so nothing about a tile's work depends on any
  other tile.

### 1.3 The sparsity rule - LoAS's whole point

This is the part that makes a LoAS trace different from a dense one.

For a given output pixel, consider one `(kh, kw, cin)` position - call it a
**line of the reduction**. The input spike recording tells us, for that
position, whether the corresponding input neuron fired at **any** timestep in
the tile's range. Two cases:

- **It fired at least once.** The weights for that line are needed, so they
  are fetched. The line is *non-silent*.
- **It never fired, at any timestep.** Then every product it would contribute
  is zero, so its weights are never needed and are **never fetched at all**.
  The line is *silent* and costs nothing: no fetch, no cycle, no record in the
  trace.

So the spike pattern of the input, not the layer's shape, decides the length of
the trace. A layer with 512 input channels whose input fires on 235 of them
produces 235 fetches, not 512. That ratio is the layer's realized sparsity, and
it varies per sample - which is why the campaign runs 500 samples rather than
one.

Note what the rule is **not**: it is not per-timestep. A line that fires once at
timestep 7 and never again is fetched exactly as often as one that fires at
every timestep - once. The timestep axis is collapsed by an "any fire" test, so
`T` affects *which* lines are non-silent (a longer window makes silence less
likely) but never *how many times* a non-silent line is fetched.

The order the lines are visited is fixed: kernel row outermost, then kernel
column, then input channel innermost. Silent lines are skipped in place, so the
surviving sequence is that same order with gaps removed.

### 1.4 What one trace record means, and why ticks are just MAC order

One record says:

> *at tick `j`, this core fetched the weights for kernel position `(kh, kw)`,
> input channel `cin`, covering output channels `[cout_start, cout_end)`.*

The channel run is one record rather than many because the whole slab is
fetched together - a **burst** along the output-channel axis. Its size in bytes
is `(cout_end - cout_start) x weight_bytes`, which for this campaign's 8-bit
weights is one byte per weight.

The **tick** is the position of this fetch in the core's own MAC order: the
first surviving line is tick 0, the next is tick 1, and so on. It is an
**ordinal, not a time**. Three things follow:

- Ticks are dense: `0, 1, 2, ...` with no gaps, because silent lines were
  dropped before numbering, not numbered and skipped.
- A tick is not a timestep and not a cycle count. The timestep axis was already
  collapsed by the any-fire test, so no `t` survives into the record.
- The highest tick plus one is the count of non-silent lines, which is also the
  tile's MAC cycle count: one weight fetch per surviving line, no overlap.

So a reader who knows the input's firing pattern can write the whole trace by
hand: walk the kernel and channels in order, skip what never fired, number what
is left from zero.

### 1.5 How per-core streams become one file

Each core produces its own ordered list of fetches for its own channel slab.
The cores that shared a pixel-and-step are then interleaved into one
**tick-major** sequence: all cores' fetches at tick 0, then all at tick 1, and
so on, with cores in id order. A core that has no fetch at some tick is simply
absent from that tick rather than padded with an empty entry.

That interleaved per-pixel block is one **tile frame** in the output file. The
file as a whole is: a header describing the machine and the layer (core count,
how output channels were fanned, the layer's seven dimensions, the burst axis
and the maximum burst width, plus an identity string naming arch/workload/
layer/sample), then one frame per tile, then an end marker and a total count.

The cache simulator replays it in that order, resolving each record's logical
coordinates into lines under whichever blocking and layout the run is testing.
The format requires each core's ticks to be **strictly ascending** within a
frame, which LoAS satisfies trivially because its ticks are a dense counter.
(The relaxed "equal ticks allowed" variant of the format exists for an
architecture whose internal lanes genuinely fetch concurrently; LoAS is not
one.)

## 2. Worked examples at the logic level

### 2.1 A08 classifier, sample 0 - predictable by hand

The layer: A08's classifier, a fully connected layer with 512 input channels
and 10 output channels, recorded over 32 timesteps. As a kernel it is 1x1, so
there is exactly one kernel position `(0, 0)` and a "line of the reduction" is
just an input channel.

The schedule: output channels 10 split as **2 per core across 5 cores**
(`2 x 5 = 10`, exactly), one output pixel (the layer has only one), everything
else resident. That is **5 tiles**, one per core, all at the same pixel and the
same off-chip step.

So core `c` owns output channels `[2c, 2c+2)`:

| core | owns output channels |
|---:|---|
| 0 | 0, 1 |
| 1 | 2, 3 |
| 2 | 4, 5 |
| 3 | 6, 7 |
| 4 | 8, 9 |

The sparsity: for sample 0, the input fires - at some point in the 32
timesteps - on channels `0, 1, 2, 4, 5, 7, 10, 12, 13, 15, ...`, and on
**235 of the 512** channels in total (a firing rate of 0.3359 across the whole
timestep-by-channel recording). Channels `3, 6, 8, 9, 11, 14, ...` never fire.

Therefore **each core's trace is exactly 235 fetches**, and the whole layer's
is `235 x 5 = 1175` records. The 277 silent channels appear nowhere.

Core 0's first eight records, with the address arithmetic. Under the
block-packed layout a line is `(kh, kw, cin / cin_block, cout / cout_block)`
flattened in that order, so with a 1x1 kernel the line id reduces to
`(cin / cin_block) x n_cout_blocks + (cout / cout_block)`, and the line holds
`cin_block x cout_block x weight_bytes` bytes. Shown at `cin_block = 1`,
`cout_block = 2` so that one line is exactly the one weight pair a core-0
record covers, and the arithmetic is visible: `n_cout_blocks = 5`, both of core
0's channels fall in cout block 0, so the line id is `cin x 5`:

| tick | input channel | why | output channels | bytes | line id at `cin_block=1, cout_block=2` |
|---:|---:|---|---|---:|---:|
| 0 | 0 | fired | 0-1 | 2 | 0 |
| 1 | 1 | fired | 0-1 | 2 | 5 |
| 2 | 2 | fired | 0-1 | 2 | 10 |
| - | **3** | **silent - no record at all** | - | - | - |
| 3 | 4 | fired | 0-1 | 2 | 20 |
| 4 | 5 | fired | 0-1 | 2 | 25 |
| - | **6** | **silent** | - | - | - |
| 5 | 7 | fired | 0-1 | 2 | 35 |
| - | **8, 9** | **silent** | - | - | - |
| 6 | 10 | fired | 0-1 | 2 | 50 |
| - | **11** | **silent** | - | - | - |
| 7 | 12 | fired | 0-1 | 2 | 60 |

Each row is one record **and** one line here, because `cout_block = 2` exactly
spans core 0's two-channel slab. At `cout_block = 1` the same record would
straddle two lines (`cin x 10` and `cin x 10 + 1`) while still being a single
2-byte burst - a reminder that a record and a line are different units, and
only coincide when the blocking happens to match the slab.

Reading it: tick 2 reads channel 2; channel 3 never fired so it produces
nothing; **tick 3 reads channel 4**, not channel 3. The tick counter advances
only for surviving lines, which is why by tick 7 the channel index has already
reached 12. The last record of the core is tick 234 reading channel 508 - the
235th non-silent channel - and `508 != 234` is the whole point of the
distinction. Core 1 emits the identical 235 ticks and channels, with output
channels `2-3` instead of `0-1`.

**What the blocking does to this, measured.** The number of *fetches* is set by
sparsity, but the number of distinct *lines* is set by sparsity **and** the
blocking, and the two come apart fast:

Counts below are **distinct lines core 0 actually touches**, taken over both of
its output channels, against the lines its slab spans:

| `cin_block` | `cout_block` | bytes per line | lines core 0 touches | lines in its slab | from 235 fetches |
|---:|---:|---:|---:|---:|---|
| 1 | 2 | 2 | 235 | 512 | 46% - sparsity fully visible |
| 8 | 4 | 32 | 64 | 64 | **100%** - sparsity invisible |
| 32 | 4 | 128 | 16 | 16 | **100%** - sparsity invisible |

(At `cin_block = 1, cout_block = 1` the same measurement is 470 of 1,024 - twice
each count, since every record straddles two lines - so the 46% is unchanged.)

With 8 channels packed per line, the 235 surviving channels are spread evenly
enough that every line is touched anyway: the trace still has 3.3x fewer
*fetches* than a dense layer, but the *footprint* is identical. This is the
distinction the whole study is about, and it is why keeping coordinates rather
than addresses in the trace matters - the same 1175 records answer differently
under each blocking.

### 2.2 The same logic with a 3x3 kernel - what padding means

The 1x1 case hides the kernel, so take a 3x3 convolution layer whose output is
only 2x2 pixels (512 input and 512 output channels, 4 timesteps). Now a "line
of the reduction" is a `(kernel row, kernel column, input channel)` triple, and
there are 9 kernel positions per pixel.

Consider the corner output pixel `(0, 0)`. With "same" padding each kernel tap
reaches one pixel up/left of centre, so the tap at kernel row 0 reaches input
row `-1` and the tap at kernel column 0 reaches input column `-1`. Those do not
exist: they are padding, structurally zero, and **a padding tap can never
fire**, so no line under it can ever be non-silent. Of the 9 taps:

| kernel tap | reaches input | status | non-silent input channels |
|---|---|---|---:|
| row 0, any column | row -1 | padding | 0 |
| any row, column 0 | column -1 | padding | 0 |
| row 1, column 1 | (0, 0) | real | 264 |
| row 1, column 2 | (0, 1) | real | 239 |
| row 2, column 1 | (1, 0) | real | 282 |
| row 2, column 2 | (1, 1) | real | 248 |

So **5 of the 9 taps contribute nothing at all** at a corner pixel, and the
pixel's whole trace is the 4 real taps' surviving channels:
`264 + 239 + 282 + 248 = 1033` fetches, which is exactly the MAC cycle count
the generator reports for that tile.

Two effects stack here and are worth keeping apart: *padding* removes whole
taps geometrically and would do so even for a dense dataflow, while *sparsity*
removes individual channels within each surviving tap. On this pixel the first
effect cuts 9 taps to 4, and the second cuts each tap's 512 channels to about
half.

The first records of that tile read: tick 0 at (row 1, column 1, channel 0),
tick 1 channel 1, tick 2 channel 2, then **tick 3 at channel 5** - channels 3
and 4 are silent at that pixel. Iteration starts at row 1, column 1 rather than
row 0, column 0 because the entire first kernel row is padding.

## 3. Where this lives in the code

### Hop 0 - `weight_trace.py:load_schedule` (schedule -> tiles)

Reads the persisted `ScheduleArtifact`, rebuilds `prob` from the cached
workload, decodes the solved strategy with `schedule_from_strategy`, then
materializes the tile list with `iter_node_tiles(schedule, prob)`. Nothing is
re-solved and no tile list is serialized: `iter_node_tiles` is a pure function
of `(schedule, prob)`, so the same artifact always yields the identical tile
list. Each tile is a `NodeTileSpec` carrying `dram_i`, `noc_i`, `core_id`,
`node_bound` (per-dimension resident extent) and `tile_offset` (per-dimension
start, **present only for dimensions that are actually split**).

### Hop 1 - `weight_trace.py:reconstruct_samples` (dispatch)

Pure dispatch: looks `arch_name` up in `ARCH_NATIVE_BRIDGES`, imports that
module and calls its `reconstruct_samples_native`. It refuses a `wave_width`
for any arch but gustavsnn. It does **not** load the trace - the caller owns
that, so a multi-sample worker loads the `.npy` once rather than once per call.

### Hop 2 - `loas/native_bridge.py` (pack -> subprocess -> unpack)

1. `trace[:, sample_indices]` is sliced and made contiguous **before** packing,
   so the child process only ever sees the requested samples. This is the
   explicit fix for the OOM found in the gustavsnn bridge on 2026-07-26 - with
   a 500-sample capture, passing the whole array would be the difference
   between ~6 MB and 2.8 GB on the A08 capture.
2. `_pack_task` writes a flat little-endian task: a 5-int trace shape, then
   `(n_tiles, n_samples)`, then **11 ints per tile** -
   `dram_i, ho, wo, kh_n, kw_n, cin_off, cin_n, t_off, t_n, cout_off, cout_n` -
   then the sample indices. Note `ho`/`wo` come from
   `tile.tile_offset.get(DIM_HO, 0)`, i.e. **they default to 0 when the
   dimension is not split**; `kh_n`/`kw_n` come from `node_bound` with no
   offset field at all. Both facts are what the bridge gate in `gen_inputs.py`
   exists to police (Part 3).
3. Trace and task are written to a `TemporaryDirectory`, the `loasgen` binary
   is run with `check=True`, and `out.bin` is read back. The temp dir is
   removed on exit, so nothing persists between calls.
4. `_unpack_output` parses the tick-grouped wire format: per `(tile, sample)` a
   `(tile_idx, sample_idx, mac_cycles, num_ticks)` header, then per tick a
   `(tick_value, num_addresses)` pair followed by that many
   `(kh, kw, cin, cout_start, cout_end)` 5-int records. The per-address tick
   field is **not** on the wire - the tick is the group key. It ends with
   `assert off == n`, so a framing mismatch fails loudly rather than silently
   truncating.

### Hop 3 - `loas/LoASGen.h:reconstruct_sample` (the actual model)

Per tile and sample, a triple loop `[KH, KW, CIN]` with `kh` outermost and
`cin` innermost. For each `(kh, kw, cin)` position - a "line" - it scans the
tile's `T` range and asks one yes/no question: did this position fire at **any**
timestep? That is the "non-silent" test. Silent lines contribute nothing at
all; they are not emitted and consume no tick.

Each non-silent line emits one `AddressRow`
`(kh, kw, cin, cout_start=cout_off, cout_end=cout_off+cout_n)` with
`tick = result.mac_cycles`, and then increments `mac_cycles`. So **ticks are a
dense sequential counter over non-silent lines only** - tick `i` is the `i`-th
non-silent line in `[KH, KW, CIN]` order, not the `cin` index and not a
timestep. One weight fetch per non-silent row, no intra-tile parallelism.
`mac_cycles` therefore equals the non-silent line count.

Padding is derived from the kernel extent, not from the layer: `pad_h =
(kh_n-1)/2`, `pad_w = (kw_n-1)/2`, `hin = ho + kh - pad_h`,
`win = wo + kw - pad_w`. Out-of-range `(hin, win)` is treated as padding
(never fires, never indexed), so it is skipped without emitting anything.

### Hop 4 - `weight_trace.py:assemble_layer_traces` (regroup)

Keys every record by its own `(tile_idx, local_sample_idx)`, so it is
independent of the binary's emission order. Groups by `(dram_i, noc_i)`, merges
the cores of each group via `merge_cores_by_tick` into tick-major order
(canonical on-disk order is `dram_i -> noc_i -> tick -> core`, core
fastest-varying), takes `mac_cycles = max` over the group's cores, and packages
one `LayerWeightTrace` per sample. **N `NodeTileSpec`s collapse into fewer
`TileWeightTrace`s**: one per `(dram_i, noc_i)` pair, each holding several
cores. A core with no fetch at a tick is omitted, never padded.

### Hop 5 - `cachesim/stream.py:stream_weight_trace` (WCTS v2)

loas is not gustavsnn, so `format_version = WCTS_VERSION = 2`.
`_wcts_tile_frames` performs the tick-major -> core-major inversion (flagged in
its own docstring as "the one conversion where a mistake is invisible"),
measures `burst_span` as the maximum `cout_end - cout_start` over the layer,
and rejects any empty COUT run. Then a 56-byte fixed header plus field codes,
spatial factors, dims and an identity block; one frame per tile; a `-1` end
magic and total burst count. `burst_dim` must be 3 (COUT) - anything else is
refused rather than mislabelled. **v2 enforces strictly ascending local ticks
within each core**, checked in `write_tile_frame`.

`n_cores` and `spatial_factors` come from the schedule, not the arch:
`src/lays/weight_trace_gen/cli.py:356-359` takes `dict(schedule.spatial_factors)` and multiplies them to
get `n_cores`. The dim ids already match the WCTS wire codes, so they pass
through untranslated.

## 4. Measured demo run (the same two examples, with implementation detail)

### Example A: A08 `layer_13_core_classifier` (5 tiles, hand-checkable)

Capture `examples/input_trace/delta/A08/vgg16_cifar10_loas_T32_n500`, trace
shape `[T=32, N=500, Cin=512, Hin=1, Win=1]`, sample 0.

**Solve** (`solve_and_cache_schedule`, real gurobi 13.0.2 on this host):
winning mode `gb_oooo`, `dram_num_steps = 1`,
workload `KH=1 KW=1 CIN=512 COUT=10 HO=1 WO=1 T=32`.

Solved NodeLevel temporal tile: `KH 1, KW 1, CIN 512, T 32`; NodeLevel spatial
split `COUT x 2`; NoCLevel spatial splitting `COUT x 5`. So
`COUT_node = _largest_divisor_leq(10, 4) = 2` and the remaining factor 5 goes
to NoCLevel: `2 x 5 = 10 = COUT`, exactly.

`schedule.spatial_factors = {COUT: 5}` -> `n_cores = 5`.
`dram_num_steps x noc_num_steps x prod(spatial) = 1 x 1 x 5 = 5` tiles, which
matches `schedule_tiles.csv`'s recorded `5` for this pair.

**Tiles** (all five, complete):

| tile | dram_i | noc_i | core_id | node_bound | tile_offset |
|---:|---:|---:|---:|---|---|
| 0 | 0 | 0 | 0 | KH 1, KW 1, CIN 512, COUT 2, HO 1, WO 1, T 32 | COUT 0 |
| 1 | 0 | 0 | 1 | same | COUT 2 |
| 2 | 0 | 0 | 2 | same | COUT 4 |
| 3 | 0 | 0 | 3 | same | COUT 6 |
| 4 | 0 | 0 | 4 | same | COUT 8 |

`tile_offset` carries **only** `COUT`. `HO`/`WO` are absent because both
problem dims are 1 and nothing split them - the case the bridge's `get(..., 0)`
default is safe for.

**Packed task** (11 ints per tile, as the binary receives them):

```
header: T=32 B=1 Cin=512 Hin=1 Win=1 | n_tiles=5 n_samples=1
tile0 = dram_i=0 ho=0 wo=0 kh_n=1 kw_n=1 cin_off=0 cin_n=512 t_off=0 t_n=32 cout_off=0 cout_n=2
tile1 = dram_i=0 ho=0 wo=0 kh_n=1 kw_n=1 cin_off=0 cin_n=512 t_off=0 t_n=32 cout_off=2 cout_n=2
tile2 = ... cout_off=4 cout_n=2
tile3 = ... cout_off=6 cout_n=2
tile4 = ... cout_off=8 cout_n=2
```

`B=1`: the trace was sliced to the one requested sample before packing, so the
child sees a 1-sample array, not 500.

**Generated records.** The 5 `NodeTileSpec`s collapse to **1**
`TileWeightTrace` at `(dram_i=0, noc_i=0)` with 5 cores:

```
mac_cycles=235   n_ticks=235   cores=[0,1,2,3,4]
tick=0   core0 (0,0,  0, 0, 2)  core1 (0,0,  0, 2, 4)  ... core4 (0,0,  0, 8,10)
tick=1   core0 (0,0,  1, 0, 2)  core1 (0,0,  1, 2, 4)  ... core4 (0,0,  1, 8,10)
tick=2   core0 (0,0,  2, 0, 2)  ...
tick=234 core0 (0,0,508, 0, 2)  core1 (0,0,508, 2, 4)  ... core4 (0,0,508, 8,10)
total address records = 1175
```

**The arithmetic connecting them**, each independently re-derived from the raw
`.npy` rather than taken from the generator:

- `KH=KW=1` so there is exactly one `(kh, kw)` position, `(0, 0)`; the line
  count is therefore just the non-silent `CIN` count.
- Non-silent CIN for sample 0, computed directly as
  `trace[:, 0, :, 0, 0].any(axis=0).sum()` = **235** of 512 (firing rate 0.3359
  over the `[T, Cin]` slice). That is exactly `mac_cycles = 235`.
- Ticks run `0..234`, dense, one per non-silent line: 235 ticks.
- The first non-silent channels are `cin = 0, 1, 2, 4, 5, 7, 10, 12, ...` -
  note `3`, `6`, `8` and `9` are silent and simply absent. Tick 3's record
  therefore carries `cin=4`, not 3, and tick 4 carries `cin=5`.
  Checked for **all 235 ticks**: `tick -> cin` equals the `tick`-th non-silent
  channel, no exceptions. This is the tick-is-a-counter rule made concrete.
- The last tick, 234, carries `cin = 508`: the 235th non-silent channel, and
  `508 != 234`, which is the clearest demonstration that ticks are not CIN
  indices.
- Each core `c` emits the same 235 lines but with its own COUT run
  `[2c, 2c+2)`, from its tile's `cout_off`. Records total
  `235 x 5 = 1175`.

**WCTS v2 stream**, decoded field by field from the bytes:

```
magic WCTRACE1  version=2  header_bytes=200  n_tiles=1  n_cores=5
weight_bytes=1  burst_dim=3  burst_stride=1  burst_span=2
n_addr_fields=5  n_spatial=1  n_dims=7  identity_bytes=60
addr field codes (0,1,2,3,4)        = KH KW CIN COUT RUN_END
spatial_factors  [(3, 5)]           = COUT x 5, product 5 == n_cores
dims  [(0,1),(1,1),(2,512),(3,10),(4,1),(5,1),(6,32)]
                                    = KH1 KW1 CIN512 COUT10 HO1 WO1 T32
identity b'loas\0vgg16_cifar10_loas_T32_n500\0layer_13_core_classifier\00\0'
tile frame 0: tile_index=0 n_cores=5 mac_cycles=235 payload_bytes=32940
  core 0: 235 bursts | first (0, 0,0,  0, 0, 2) | last (234, 0,0,508, 0, 2)
  core 1: 235 bursts | first (0, 0,0,  0, 2, 4) | last (234, 0,0,508, 2, 4)
  core 2: 235 bursts | first (0, 0,0,  0, 4, 6) | last (234, 0,0,508, 4, 6)
  core 3: 235 bursts | first (0, 0,0,  0, 6, 8) | last (234, 0,0,508, 6, 8)
  core 4: 235 bursts | first (0, 0,0,  0, 8,10) | last (234, 0,0,508, 8,10)
trailer: end_magic=-1 total_bursts=1175; 33176 of 33176 bytes consumed
```

Size check: `payload_bytes = 5 cores x (8 + 28 x 235) = 5 x 6588 = 32940`, and
the whole stream is `200 (header) + 24 (frame header) + 32940 + 12 (trailer) =
33176` bytes, which is exactly the byte count produced. `burst_span = 2` is the
max `cout_end - cout_start`, matching `COUT_node = 2`.

### Example B: B09/`loas_vgg16` `layer_10_core_features_34` (exercises 3x3 + padding + HO/WO offsets)

Example A is a GEMM, so `KH=KW=1` leaves the kernel and padding logic
untested. This second layer covers them: `KH=3 KW=3 CIN=512 COUT=512 HO=2 WO=2
T=4`, trace shape `[4, 500, 512, 2, 2]`.

Solved: mode `gb_oooo`, `dram_num_steps = 16`, `noc_num_steps = 2`,
`schedule.spatial_factors = {COUT: 16}` -> `n_cores = 16`,
`16 x 2 x 16 = 512` tiles - again exactly the `512` in `schedule_tiles.csv`.
`node_bound` is `KH 3, KW 3, CIN 512, T 4` with `COUT 4`, and there are 128
distinct COUT offsets (`128 x 4 = 512 = COUT`). `tile_offset` now carries
**four distinct `(HO, WO)` pairs** - `(0,0), (0,1), (1,0), (1,1)` - one per
output pixel, which is the split case where those offsets are mandatory.

Note `n_cores = 16` while the mapspace says `COUT: {spatial: 4}`: the NodeLevel
part is the 4 in `node_bound[COUT]`, and NoCLevel splitting supplies another
factor of 4 across nodes, giving the 16-core machine width. The two multiply;
they are not in conflict.

**Padding, re-derived by hand for the `(ho=0, wo=0)` tile.**
`pad_h = pad_w = (3-1)/2 = 1`, so `hin = 0 + kh - 1` and `win = 0 + kw - 1`:

| kh | kw | hin | win | status | non-silent CIN |
|---:|---:|---:|---:|---|---:|
| 0 | 0 | -1 | -1 | padding | 0 |
| 0 | 1 | -1 | 0 | padding | 0 |
| 0 | 2 | -1 | 1 | padding | 0 |
| 1 | 0 | 0 | -1 | padding | 0 |
| 1 | 1 | 0 | 0 | valid | 264 |
| 1 | 2 | 0 | 1 | valid | 239 |
| 2 | 0 | 1 | -1 | padding | 0 |
| 2 | 1 | 1 | 0 | valid | 282 |
| 2 | 2 | 1 | 1 | valid | 248 |

`264 + 239 + 282 + 248 = 1033`, and the generator reports
`mac_cycles = 1033` for that tile. Five of the nine kernel positions are pure
padding on a corner pixel of a 2x2 output and contribute nothing - exactly as
the header documents.

The emitted first records for that tile are
`tick=0 (1,1,0,0,4)`, `tick=1 (1,1,1,0,4)`, `tick=2 (1,1,2,0,4)`,
`tick=3 (1,1,5,0,4)`: iteration starts at `kh=1, kw=1` because `kh=0` is
entirely padding, ticks restart at 0 for the tile, and `cin` jumps `2 -> 5`
where channels 3 and 4 are silent.

**Scale and cost, measured:** 512 tiles -> 32 `TileWeightTrace`s (16 `dram_i` x
2 `noc_i`), 16 cores each; 528,896 address records for **one** sample;
generation 2.6 s wall, peak Python RSS 0.32 GB; the full WCTS v2 stream is
14,814,156 bytes and the strictly-ascending tick rule held across all 512
frames.

Example A's 200-byte header does **not** carry over - the identity block is a
different length and the spatial-factor count differs - so the byte math here
is: `192 (header) + 32 x 24 (frame headers) + 512 x 8 (core headers) +
28 x 528,896 (bursts) + 12 (trailer) = 14,814,156`, matching the measured size.
The 192 is for the `spatial_factors={COUT: 16}` single-entry mapping my driver
passed. The production path differs: `src/lays/weight_trace_gen/cli.py` passes
`dict(schedule.spatial_factors)`, which carries **all seven** dim keys
(`{KH:1, KW:1, CIN:1, COUT:16, HO:1, WO:1, T:1}`), making the header 240 bytes
and the stream 14,814,204. Both are valid - `write_stream_header` only requires
that the factors' product equal `n_cores`, and 16 == 16 either way - but a
stream's exact byte size depends on how many spatial entries the caller
supplies, which is worth knowing before anyone size-checks campaign output
against a recomputed figure.

## 5. Caveats (flagged, not fixed)

1. **Stride is absent from the whole native path.** `TileSpec` has no stride
   field and `LoASGen.h` computes `hin = ho + kh - pad_h` with an implicit
   stride of 1. Any stride-2 layer would silently read the wrong input pixels.
   This is consistent with `build_workload_from_trace` excluding non-3x3 /
   non-stride-1 convs (the 6 unscheduled layers, classes S4+S5 in
   `layer_dim_coverage.md`), so nothing in the campaign hits it - but the
   generator itself has no guard, so the protection is entirely upstream
   policy. If that loader filter is ever relaxed, this breaks silently.
2. **Padding is inferred from the kernel size, not from the layer.**
   `pad_h = (kh_n-1)/2` hardcodes "same" padding. It happens to be correct for
   every captured layer (3x3 -> pad 1, 1x1 -> pad 0, which is what
   LAYER_SHAPES records), but a 3x3 layer with padding 0 would be
   reconstructed wrongly with no error raised. The 1x1 `spiking-Conv` layers of
   A04 (class S3, padding 0) get `pad = 0` from this formula and so are fine by
   coincidence of `kh=1`, not by checking.
3. **`HO`/`WO` offsets default to 0 when absent.** `_pack_task` uses
   `tile.tile_offset.get(DIM_HO, 0)`. That is safe only when the problem
   dimension is 1. The gate `_bridge_tile_violations` in `gen_inputs.py` is the
   sole thing enforcing this, via `missing_pixel_offset` (offset absent while
   `problem[name] != 1`) and `pixel_tile_bound` (`node_bound != 1`). Example A
   is the safe `HO=WO=1` case and Example B is the explicit-offset case, so
   both sides are exercised - but note the gate lives in `gen_inputs.py`, not in
   the bridge, so **any caller that reaches the bridge without going through
   `gen_inputs` loses the check entirely.**
4. **Kernel offsets are silently ignored.** `_pack_task` sends `node_bound[KH]`
   and `node_bound[KW]` but no kernel offset, so a tile that split the kernel
   would be reconstructed as if it held the whole window. Again caught only by
   the gate (`kernel_offset`, `kernel_tile_bound`), not by the bridge.
5. **Ticks are dense and sequential, which is stronger than v2 requires.**
   `tick = mac_cycles++` per non-silent line, so within a core ticks are
   `0, 1, 2, ...` with no gaps and no repeats. v2's strictly-ascending rule can
   therefore never be violated by loas by construction. The flip side: the
   ticks carry **no timing information** - they are an ordinal, not a cycle
   count, and `T` has already been collapsed away by the any-fire test. Any
   downstream consumer treating a loas tick as a time coordinate is
   misreading it.
6. **`mac_cycles` is a max across cores, and cores are near-identical here.**
   `assemble_layer_traces` takes `max(r["mac_cycles"])` over a group's cores.
   For loas every core in a group walks the same `(kh, kw, cin)` lines and
   differs only in its COUT run, so all cores in a group report the same
   `mac_cycles` and the `max` is degenerate. That makes the field safe but also
   uninformative for this arch; it is not a per-core quantity in the output.
7. **`HANDOFF.md`'s T21 dead-reference list is stale for `LoASGen.h`.** That
   list records `LoASGen.h:7-9` (`non_silent.reshape` / `num_batch`) and
   `:11-13` (`.lines/.bitmask/.ptr/.bits`) as surviving references to deleted
   Python. Grepping the current file finds **none** of those strings: `:5-13`
   is now the `[KH, KW, CIN]` iteration-order and "no row-level masks"
   paragraphs. The header was rewritten by commit `fc24ea5` ("wt500 campaign:
   WCTS v3, wave-width-aware trace gen, sweep scaffolding"), after that
   HANDOFF entry was written. The only vestige is the parenthetical
   "bitmask == 1" at `:5`, which is descriptive rather than a code reference.
   The caveat is therefore on the handoff notes, not on this generator: anyone
   redispatching T21 should re-grep before trusting its line numbers. This is
   not isolated to loas - T21's `ProsperityGen.h:154-156` entry is equally
   stale: that range is live pattern-bit emission code now
   (`row.kh = bit_idx / tile.kw_n` etc.), with no
   `event_to_address`/`divmod` narration left. Two of T21's entries are
   therefore dead; the list needs regenerating against the current tree before
   it is worked, not line-by-line trust.
8. **Record volume, not time, is the scaling risk.** Example B produced 528,896
   records for one sample of a 512-tile layer in 2.6 s at 0.32 GB. Cost scales
   as `tiles x non-silent lines x 1 record`, and `non-silent lines <=
   KH*KW*CIN`, so a layer with large `CIN` and many pixels grows the record
   count fast while CPU time stays modest. The 14.8 MB stream for a single
   sample of one mid-sized layer is the number to extrapolate from when sizing
   campaign output, not the runtime.
9. **The `assert off == n` in `_unpack_output` is the only framing check**, and
   it is a bare `assert` - it vanishes under `python -O`. Nothing else
   validates that the binary's output matches the expected tile/sample count.
10. **`stream_weight_trace` trusts its caller for `n_cores`.** The header
    writer validates `prod(spatial_factors) == n_cores`, but both come from the
    same `schedule.spatial_factors` in `src/lays/weight_trace_gen/cli.py`, so the check cannot catch a
    schedule/machine mismatch - only a caller that computed the product
    inconsistently. The `core_id < n_cores` bound check in `_wcts_tile_frames`
    is the one that would actually catch a wrong machine width.

## 6. Reproducing

Throwaway drivers live in this session's scratchpad (not committed):
solve via `lays.scheduler.artifact.solve_and_cache_schedule` with the campaign
`arch.yaml` + `mapspaces/loas.yaml`; tiles via
`lays.weight_trace_gen.weight_trace.load_schedule`; generation via
`reconstruct_samples('loas', ...)` on a `load_layer_trace(..., mmap=True)`
array; stream via `lays.cachesim.stream.stream_weight_trace` with
`n_cores`/`spatial_factors` taken from `schedule.spatial_factors` as
`src/lays/weight_trace_gen/cli.py:356-359` does. Schedule JSON cache and the `.wcts` output were written
under the scratchpad, nothing into the repo.
