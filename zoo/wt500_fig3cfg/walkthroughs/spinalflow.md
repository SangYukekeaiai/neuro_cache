# Generator walkthrough: SPINALFLOW

Step 3 of `docs/plans/2026-11-10-wt500-restart-plan.md`, arch 3 of 5.

Four parts, logic first:

1. **How a SpinalFlow weight trace is generated** - the model, no code.
2. **Worked examples at the logic level** - real measured numbers, hand-checkable.
3. **Where this lives in the code** - the implementation path.
4. **Caveats** - each with a verdict on whether it affects generation of any of
   the 8 benchmarks' layers.

Everything measured here was run on this host against the finalized
`zoo/wt500_fig3cfg/arch.yaml` and `zoo/wt500_fig3cfg/mapspaces/spinalflow.yaml`
and the real n=500 captures under `examples/input_trace/delta/`.

**The headline: unlike PTB, SpinalFlow's address stream genuinely differs from
LoAS's - by a factor of 23 on the same layer.** LoAS and PTB fetch a weight
line once if it ever fires. SpinalFlow fetches it **once per timestep at which
it fires**. On A08's classifier, sample 0, that is 235 fetches against
**5,504**. This single difference is also the mechanism behind the campaign's
worst-case layer, which this document quantifies in section 2.3.

## 1. How a SpinalFlow weight trace is generated (the logic)

### 1.1 The dataflow: spikes in time order

SpinalFlow's organising idea is that spikes arrive **sorted by time**. The
machine consumes a stream of firing events ordered by timestep, and each event
is handled as it arrives: the weights for the input channel that fired are
fetched, and applied to the output channels the current slab covers.

That ordering is the whole architecture. LoAS and PTB collapse the time axis
before touching weights - they ask "did this line ever fire" and fetch once.
SpinalFlow never collapses it. Time is the outer loop, and a weight line is
re-fetched at every timestep its input fires.

The consequence that matters for a weight-cache study: the same weight address
recurs many times within a tile, spread across the timestep sequence. Whether
that recurrence is a cache hit or a miss is exactly the question the campaign
exists to answer, and SpinalFlow is the architecture that generates the
recurrence in the first place.

### 1.2 What a tile means for SpinalFlow

The mapspace holds all input channels and all timesteps resident, caps the
receptive field at 4x4 (so any 3x3 kernel is fully resident), fans output
channels across the PEs - the mapspace caps a node's slab at 4 while the
machine-wide fan is the schedule's own spatial product, 5 cores on A08's
classifier and 16 on the heavy C01 layer - and bars output pixels from
residency. One
tile is therefore:

> *one output pixel, one contiguous slab of output channels, with the whole
> kernel window, all input channels and all timesteps available locally.*

Because output pixels are barred, the layer is cut one pixel at a time, and
because an output-channel slab is only as wide as the PE fan-out, a layer with
many output channels is cut again into many slabs. **Tile count is therefore
(number of output pixels) x (number of output-channel slabs)**, and both
factors grow with the layer. That product is what makes SpinalFlow the arch
with the campaign's tile-count problem (section 2.3).

### 1.3 The sparsity rule, and how it differs from LoAS and PTB

All three architectures are driven by the same input recording, and all three
skip work for inputs that never fire. They differ in what one unit of work is.

- **LoAS**: one fetch per `(kernel tap, input channel)` line that fires **at
  least once** anywhere in the timestep window. Fires once or fires thirty
  times - one fetch either way. The time axis is collapsed by an any-fire test.
- **PTB**: the same any-fire test for fetching, plus a second pass that pairs
  lines whose firing times do not collide, used only to compute cycles. Its
  address stream is identical to LoAS's.
- **SpinalFlow**: one fetch per **firing event**. A line that fires at five
  timesteps is fetched five times, at five different ticks. Nothing collapses
  the time axis.

So SpinalFlow's trace length is the **total spike count** in the tile's window,
where LoAS's is the **count of distinct lines that ever spiked**. The ratio
between them is the average number of timesteps a firing line is active for,
which is a property of the input data rather than of the hardware - and it is
large: on A08's classifier it is 23.4.

A line that never fires still costs nothing, so SpinalFlow is sparsity-driven
too. It simply exploits a weaker form of sparsity: it skips silent
`(timestep, tap, channel)` positions rather than silent lines.

### 1.4 What one record means, and tick semantics

One record says:

> *at tick `j`, this core fetched the weights for kernel position
> `(kernel row, kernel column)`, input channel `cin`, covering output channels
> `[cout_start, cout_end)`.*

Identical in shape to the other two architectures' records, and the channel run
is one burst of `(run width) x weight_bytes` bytes as before. What differs is
**how many records exist and in what order**.

The **tick is the event's position in the time-ordered sequence**: tick 0 is
the first spike of the earliest timestep, and ticks advance through that
timestep's firing channels, then the next timestep's, and so on. Ticks are
dense, one per event, an ordinal rather than a cycle count.

Two things follow that do not hold for LoAS or PTB:

- **The same address appears at many ticks.** A channel firing at timesteps 0,
  3 and 7 contributes three records with the same coordinates and three
  different ticks. In LoAS's trace that is one record.
- **Record order is time-major, not channel-major.** Early ticks sweep all
  channels firing at the first timestep, so the channel index rises, resets,
  and rises again once per timestep. LoAS's channel index rises monotonically
  across the whole tile.

The cycle count is the event count: one fetch per event, no overlap, the same
simple model LoAS uses and unlike PTB's two-term maximum.

### 1.5 How per-core streams become one file

Unchanged from the other two architectures. Cores sharing a pixel-and-step are
interleaved tick-major, absent cores omitted; one frame per `(dram_i, noc_i)`
tile group - A08's classifier is one frame of 5 cores, while the heavy C01
layer's 131,072 tiles become 8,192 frames of 16 cores; a header
describing machine and layer, then frames, then an end marker and total count.
SpinalFlow writes the **strictly ascending** tick variant, which its dense
per-event numbering satisfies by construction.

## 2. Worked examples at the logic level

### 2.1 A08 classifier, sample 0 - the same tiles, a 23x longer trace

The layer: 512 input channels, 10 output channels, 32 timesteps, 1x1 kernel.
The solve is identical to LoAS's and PTB's - output channels 10 split as **2
per core across 5 cores**, one pixel, **5 tiles**, whole kernel and all 512
channels and all 32 timesteps resident.

So the tiling is the same. The trace is not.

| quantity | LoAS | PTB | SpinalFlow |
|---|---:|---:|---:|
| fetches per core | 235 | 235 | **5,504** |
| records in the layer | 1,175 | 1,175 | **27,520** |
| cycles reported | 235 | 261 | **5,504** |
| address stream identical to LoAS? | - | **yes** | **no** |

The 5,504 is the **total number of ones** in the 32-by-512 firing recording for
sample 0, confirmed by summing the raw array directly. The 235 is the number of
channels with at least one one. The ratio 5,504 / 235 = 23.4 is the average
number of timesteps a firing channel stays active.

Core 0's first records, predictable by hand - take the channels firing at
timestep 0 in increasing order, then timestep 1's, and number from zero:

| tick | timestep | input channel | why | output channels |
|---:|---:|---:|---|---|
| 0 | 0 | 0 | fires at t=0 | 0-1 |
| 1 | 0 | 1 | fires at t=0 | 0-1 |
| - | 0 | **2** | **fired at some t, but not t=0 - no record here** | - |
| 2 | 0 | 5 | fires at t=0 | 0-1 |
| 3 | 0 | 7 | fires at t=0 | 0-1 |
| 4 | 0 | 10 | fires at t=0 | 0-1 |
| 5 | 0 | 12 | fires at t=0 | 0-1 |
| ... | | | 138 events at t=0 in total | |
| 138 | 1 | first channel firing at t=1 | | 0-1 |

The channels firing at timestep 0 are `0, 1, 5, 7, 10, 12, ...`, 138 of them,
and those are exactly the first six ticks' channels. **Compare with the LoAS
table for the same layer and sample**, whose first ticks read channels
`0, 1, 2, 4, 5, 7`: channel 2 appears at LoAS tick 2 but not in SpinalFlow's
first timestep, because channel 2 fires later in the window rather than at
timestep 0. The two architectures see the same spikes and order them
differently.

Per-timestep event counts for the first eight timesteps are
`138, 173, 170, 168, 160, 180, 172, 181`, and the whole 32-timestep sequence
sums to 5,504. The last tick, 5,503, reads channel 508 - the same channel LoAS
ends on, since it is the highest-numbered firing channel either way.

The stream for this one layer and sample is 27,520 bursts in 770,842 bytes,
against LoAS's 1,175 bursts in 33,176. Both figures count a header carrying a
single spatial-factor entry, which is what the drivers here passed; the
production path passes the full seven-key spatial-factor dict, giving a header
48 bytes larger and a stream of 770,890 bytes for the same records. See
`walkthroughs/loas.md` section 4 for the same distinction on that arch.

### 2.2 What this means for a weight cache

The point of the difference is reuse distance. LoAS presents each weight line
once per tile, so within a tile there is no reuse to exploit at all - every
fetch is a first touch. SpinalFlow presents the same line up to 32 times,
spread across the time sequence, with roughly 170 other events between
consecutive appearances on this layer. Whether those recurrences hit depends
entirely on whether 170-odd events' worth of distinct lines fit in the cache -
which is precisely the quantity the campaign sweeps.

So SpinalFlow is the architecture whose numbers the blocking and capacity
sweeps can actually move, and LoAS is closer to a floor. That is worth knowing
before interpreting cross-architecture results, and it follows from the
dataflow rather than from any tuning.

### 2.3 The 131,072-tile C01 layer - where the cost comes from

C01/`sma_azo_vgg_cifar10_dvs`'s first captured layer: 3x3 kernel, 64 input and
128 output channels, **64x64 output**, 10 timesteps. This is the layer the
earlier pilot recorded as running at least 23 minutes on one sample at about
15 GB. The mechanism, measured:

**Where 131,072 tiles comes from.** The solve gives 4,096 distinct output
pixels (the full 64x64 grid, since pixels are barred from residency) and **32**
distinct output-channel slabs (128 output channels at 4 per slab).
`4,096 x 32 = 131,072`, confirmed directly from the solved tile list. This also
settles the open question from the step-1b work: the factor beyond the 4,096
spatial positions is the output-channel slab count, and the timestep count is
**not** a factor, because all 10 timesteps are resident inside each tile.

**Work per tile.** Each tile scans every `(timestep, kernel row, kernel column,
input channel)` position in its window: `10 x 3 x 3 x 64 = 5,760` positions,
emitting a record for each one that fired. For an interior pixel the receptive
field contains **380** spike events at this layer's 7.1% firing rate, so a tile
emits of order 380 records from 5,760 position reads.

**Totals for one sample**, measured on tile subsets and extrapolated:

| quantity | value |
|---|---:|
| trace positions read | `131,072 x 5,760` = **755 million** |
| records emitted | about **52.5 million** |
| WCTS stream size | about **1.47 GB** |
| measured rate | 64 tiles in 0.12 s, 256 tiles in 0.41 s |
| extrapolated generation time | about **4 minutes** |

The record figure needs care, because the obvious shortcut is biased. The
256-tile subset averages **384** records per tile, and an interior pixel hand
counts to **380** - but those agree only because both are low: the subset's
tiles are border pixels, where part of the receptive field is padding, and the
hand count is a single interior pixel. Summing the true window count over all
4,096 pixels gives a mean of **400.2** records per tile, which is where the
52.5 million and 1.47 GB above come from. A corner pixel is 49 records against
an interior pixel's 380, so border bias on this layer is large and a subset
mean is not a safe estimator for it.

**Why the memory is about 15 GB.** The records are materialized as Python objects before
being streamed - one tuple per record inside a per-tick, per-core structure.
At 50 million records that is gigabytes of live objects regardless of how fast
the native scan is. The memory is driven by record **count**, which is set by
the dataflow, not by anything about the implementation's speed.

**Where the real waste is.** The 32 output-channel slabs of a given pixel each
re-scan the **identical** spike data and find the **identical** events; they
differ only in the output-channel range stamped onto each record. So about
**97% of the 755 million position reads are repeated work** - the same pixel's
window scanned 32 times. A scan-once-emit-32-variants restructuring would cut
the position reads by that factor while producing byte-identical output. It
would not reduce the record count or the memory, which are inherent.

**The dvs128_gesture twin** has the same 131,072 tiles and 16 timesteps instead
of 10, so it scans `16 x 3 x 3 x 64 = 9,216` positions per tile - 1.6x the work
and proportionally more events.

## 3. Where this lives in the code

The path is the same six hops as LoAS; see `walkthroughs/loas.md` section 3
for the full account. Only the differences are described here.

Identical to LoAS and PTB:

- **Schedule to tiles**, **dispatch**, **regroup** and **stream** are shared
  code. SpinalFlow is not gustavsnn, so the stream writer selects **v2** with
  its strictly-ascending tick rule.
- **Task packing**: `spinalflow/native_bridge.py`'s `_pack_task` is
  byte-for-byte identical to `loas/native_bridge.py`'s - verified by diff. Same
  11 ints per tile, same `tile_offset.get(DIM_HO, 0)` defaulting, same absent
  kernel-offset field, same slicing of the trace to requested samples before
  packing.

SpinalFlow-specific, all in `spinalflow/SpinalFlowGen.h`:

- `reconstruct_sample`'s loop nest is `t` **outermost**, then `kh`, `kw`, with
  `cin` innermost - the comment states this is so ticks line up with event
  position. LoAS and PTB have no `t` loop around their address walk at all;
  theirs is a single `[KH, KW, CIN]` pass with the timestep range consumed
  inside the any-fire test.
- A record is pushed for **every** position where the trace byte is non-zero,
  with `row.tick = result.mac_cycles` incremented per record. There is no
  silence-removal pass and no bit-vector: the condition is the spike itself.
- `result.mac_cycles` is the event count, so cycles equal fetches as in LoAS.
- Padding is `pad_h = (kh_n - 1) / 2` with `hin = ho + kh - pad_h`, skipped by
  `continue` at the row and column level - the same formula as the other two,
  duplicated again, with no stride term.
- `TileSpec` carries `cout_off`/`cout_n` and `cin_off`/`cin_n`, which is why a
  tile is a channel slab of a pixel rather than the whole pixel.

## 4. Caveats

Each carries the standing question: **does it affect weight-trace generation of
any of the 8 benchmarks' layers under the current campaign?** All 151
SpinalFlow pairs are feasible - output pixels are barred from residency, so the
partial-sum footprint is `2 x COUT_spatial x T` bytes. Note both factors matter:
`COUT_spatial` is 4 only when the layer's output-channel count is divisible by
4, so `T` alone does not set the footprint. Over the 151 pairs it takes six
values, `{16, 32, 40, 80, 128, 256}` B against a 1,024 B budget. The minimum,
16 B, is B09/`loas_vgg16`'s classifier (`COUT = 10` gives `COUT_spatial = 2` at
`T = 4`); the maximum, 256 B, is the A08 convolutions at `T = 32`. This
document's own worked example, A08's classifier, is **128 B** rather than 256,
because its `COUT = 10` gives a slab of 2.

### S1. Tile count is the product of pixels and output-channel slabs

*Caveat (section 1.2, 2.3):* because output pixels are barred from residency
and channel slabs are PE-width, tile count grows as
`pixels x channel slabs`. The C01 layers reach 131,072 tiles, and both C01
workloads hit it.

- **Affects generation? No - it is a cost, not a defect.** Every tile is
  correctly formed and the output is right. For one sample of the worst layer:
  **755 million** trace position reads (arithmetic, `131,072 x 5,760`), about
  **52.5 million** records and **1.47 GB** of stream (computed from the true
  per-pixel window counts), and roughly **4 minutes** (extrapolated from timed
  64- and 256-tile subsets). Only the subset timings and their per-tile record
  counts were measured directly; see section 5 for what that extrapolation does
  and does not cover.
- **Severity: capacity and scheduling.** At 500 samples per layer this one
  layer dominates any flat per-case budget, which is what broke the earlier
  pilot's 2,000-case / 90-minute shard assumption.
- **Fix sketch:** none in the generator. Shard weighting must be per
  (arch, layer) and should be driven by **record count**, not tile count. On
  records these C01 layers are the campaign's ceiling: 52.5 million against
  about 3.9 million for Prosperity's heaviest surviving layer, which has 4.5x
  as many tiles (589,824) at only 6.6 records each. They need dedicated shards
  with their own time and memory limits. (`layer_dim_coverage.md` names
  Prosperity as the ceiling on a tile-count ranking taken from the
  pre-finalization solve; that ranking inverts once records are counted.)

### S2. 97% of the heavy layer's trace scanning is repeated work

*Caveat (section 2.3):* the 32 output-channel slabs of one pixel each re-scan
the identical spike window and discover the identical events, differing only in
the channel range written into each record.

- **Affects generation? No - the output is correct**, just produced more slowly
  than necessary.
- **Severity: efficiency only.** It costs about 32x the necessary position
  reads on the heavy layers and proportionally less where the slab count is
  smaller.
- **Fix sketch:** scan a pixel's window once and emit the per-slab record
  variants from that one pass. Output would be byte-identical. It would not
  reduce the record count or the memory, which are set by the dataflow.

### S3. Memory is driven by record count, which is inherent

*Caveat (section 2.3):* records are materialized as Python objects before
streaming, so a 50-million-record layer holds gigabytes of live objects
regardless of native scan speed. This is the mechanism behind the earlier
pilot's roughly 15 GB.

- **Affects generation? Not correctness, but it is the binding practical
  limit** on the heavy layers, and it is the one caveat here that can actually
  stop a run.
- **Severity: loud failure** - an out-of-memory kill, not silent corruption.
  Note the pane-level risk recorded in the team's process rules: a job killed
  by the kernel out-of-memory killer can take its whole process scope with it
  unless started in its own scope.
- **Fix sketch:** stream per tile rather than accumulating the whole layer -
  the record assembly already groups by tile, so the regroup step could hand
  each completed tile frame to the writer and release it. That changes peak
  memory from layer-sized to tile-sized without changing the output.

### S4. Ticks carry ordering but not timing, despite the time-major walk

*Caveat (section 1.4):* ticks are a dense event counter. Because the walk is
time-major the tick order does follow timestep order, which is more
informative than LoAS's ordering - but a tick is still not a timestep, and the
timestep itself is not recorded in the output.

- **Affects generation? No - observation only.**
- **Severity: misinterpretation risk.** A consumer wanting to know which
  timestep an event belongs to cannot recover it from the stream: the record
  carries kernel position, channel and channel run, not time. The boundaries
  between timesteps are invisible in the tick sequence.
- **Fix sketch:** none required for the campaign. If timestep attribution is
  ever needed, it would have to be added as a record field; it cannot be
  derived after the fact.

### S5. Shared caveats that apply here unchanged

Properties of code SpinalFlow shares with LoAS, not rediscoveries. See
`walkthroughs/loas.md` section 5 and the `loas` section of `CAVEATS.md`.

- **L1 stride absent from the native path.** `SpinalFlowGen.h` duplicates
  `hin = ho + kh - pad_h` with no stride term. Does not affect generation: the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`, not the bridge.** Task packing
  is identical to LoAS's, including HO/WO offset defaulting and the missing
  kernel-offset field. Does not affect generation: the campaign path runs the
  gate. Latent for other callers. Note SpinalFlow's tiles **do** split the
  pixel dimensions, so the explicit-offset path is exercised on every multi-
  pixel layer, and the gate's `missing_pixel_offset` check is doing real work
  here rather than guarding a case that never arises.
- **L3 padding inferred from kernel size.** Same formula, duplicated again.
  Does not affect generation: all 157 captured layers are same-padding.
- **L6 bare assert as the only framing check** and **L7 the stream writer
  trusts its caller for machine width.** Shared code, shared verdicts; neither
  affects generation.
- **L10 blocking rather than sparsity decides the footprint.** Applies, but
  SpinalFlow is the arch where it bites least: because the same line recurs
  many times per tile, its reuse is temporal rather than purely spatial, so
  capacity and blocking sweeps have real room to move its numbers - unlike
  LoAS, where each line appears once per tile.

## 5. Limits of this write-up

Stated so they are not mistaken for measurements.

1. **The 4-minute figure does not reconcile with the earlier pilot's 23-plus
   minutes, and this document does not explain the gap.** The subsets timed
   here cover the native scan and the unpack only. They do not cover the
   regroup step, the stream write, or the memory pressure that dominated the
   pilot - and a 50-million-record layer spends most of its wall clock in
   exactly those stages. Treat 4 minutes as a floor on the native scan, not an
   estimate of end-to-end cost, and treat the 6x gap as unexplained.
2. **The 15 GB is quoted from the earlier pilot, not re-measured here.** The
   largest run in this document peaked at 0.18 GB on a 256-tile subset. The
   claim that 52.5 million records implies gigabytes of live objects is an
   argument from record count, with no per-record object size measured, so the
   mechanism is plausible rather than demonstrated.
3. **Neither the 52.5 million records nor the 1.47 GB stream was produced.**
   Both are computed: the record count from the true per-pixel window counts
   summed over all 4,096 pixels times 32 slabs, the byte count from that at 28
   bytes per burst. No full-layer run was performed.
4. **The scan-once restructuring in S2 is argued from the code, not
   demonstrated.** "Byte-identical output" is a claim about what the loops
   would produce, and the untested part is tick numbering across slabs: today
   each slab's walk numbers its own ticks, and a single-scan variant would have
   to reproduce that numbering exactly rather than merely emit the same
   coordinates.
5. **Measured numbers are sample 0 of one sample.** The 5,504 events, 235
   survivors, 23.4x ratio and the per-pixel counts are all from a single sample
   of a 500-sample capture. Sparsity varies per sample. The structural result -
   one record per firing event, so the trace length is the spike count - does
   not depend on the sample; every count does.

## 6. Reproducing

Solve via the scheduler's cache-and-solve entry point with the campaign
`arch.yaml` and `mapspaces/spinalflow.yaml`; tiles via the shared schedule
loader; generation via the arch dispatch on a memory-mapped capture. The
LoAS-versus-SpinalFlow comparison is a direct set comparison of the two
generators' records for the same layer, schedule and sample. The 5,504 event
count was confirmed by summing the raw firing array for the sample, and the
per-timestep counts by summing each timestep's row. The heavy layer's figures
come from the solved tile list (4,096 pixels x 32 slabs), an arithmetic
position-read count, timed runs on 64- and 256-tile subsets extrapolated to the
full 131,072, and a full per-pixel window count over the 64x64 grid for the
record total. All measurements are sample 0. Drivers are throwaway scripts under this session's scratchpad;
nothing was written into the repo.
