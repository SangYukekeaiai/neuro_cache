# Generator walkthrough: GUSTAVSNN

Step 3 of `docs/plans/2026-11-10-wt500-restart-plan.md`, arch 5 of 5.

Four parts, logic first:

1. **How a GustavSNN weight trace is generated** - the model, no code.
2. **Worked examples** - real measured numbers, hand-checkable.
3. **Where this lives in the code** - the implementation path.
4. **Caveats** - each with a verdict on whether it affects generation of any of
   the 8 benchmarks' layers.

Then a limits section, because three of the headline numbers here are computed
rather than produced.

**A blocker first, because it silently produced empty traces:** the
`gustavgen` binary shipped in the tree predated its own sources - binary 11-07
against `gustavsnn/main.cpp` and `GustavGen.h` at 20:29 on 11-10 - and the task
wire format changed in between. The current task carries a wave-width integer in
its header that the older parser does not expect, so every later read shifts by
one integer and the first tile's output-row **count** receives its output-row
**offset**, which is 0. Zero output rows gives zero row-lists, which gives
**zero records**: an empty trace, written without complaint.

Whether that surfaces depends on the sample chunk size. At a chunk of one or two
the shifted sample index falls outside the requested set and the assembly step
raises `IndexError: list index out of range`, which is how this was found. **The
campaign chunks in tens** - `cli.py:70` sets `SAMPLE_CHUNK_SIZE = 10`, used at
`:216` and `:255`, and `slurm/harness.py:443` passes `--sample-count` with no
chunk-size override - and at ten the garbage index lands inside the requested
range, so nothing raises and the empty traces are kept. **The configuration that
raises is the benign one; the campaign's own configuration is the silent one.**

A note on detecting this, because the obvious test does not work: comparing
binary and source timestamps flags **all five** archs, not one. Every
generator's header carries the same 20:29 on 11-10 modification. What set
gustavsnn apart is that its `main.cpp` was modified then too - the other four
`main.cpp` files date from 11-04 and predate their binaries - so only
gustavsnn's parser went out of step with its packer. A timestamp check is
therefore the wrong pre-flight test; running the generator, or hashing the
sources it was built from, is the right one.

Everything measured below used a binary rebuilt from the current sources. See
caveat G1.

Solver provenance, as in the sibling documents: these solves come from the
scheduler's cache-and-solve entry point, which sweeps traffic modes, where the
campaign path is BASE mode. Tile counts, wave widths and record counts are
mode-invariant, so the figures are campaign-relevant without being
byte-for-byte the campaign's schedules.

## 1. How a GustavSNN weight trace is generated (the logic)

### 1.1 What a wave is

GustavSNN's node works on several **output rows at once**. Each resident output
row has its own list of weight lines to fetch - the `(kernel row, kernel
column, input channel)` positions that fire for that row - and the node steps
those lists **in parallel**, one line from each row per cycle.

A **wave** is a group of output rows advancing together. The rows in a wave
start at the same cycle, and each row's `j`-th line is fetched at
`wave_start + j`. A wave therefore lasts as long as its **longest** row's list,
and rows with shorter lists simply finish early and contribute nothing for the
remaining cycles.

The **wave width** is how many rows advance together, and it is not a constant.
Section 1.2 derives it; 1.2a then shows it is **behaviorally inert** on every
layer in this campaign, which is worth knowing before weighting anything on
it.

### 1.2 Why the wave width is a per-schedule quantity, never a flat 4

The width is the product of the node-level **spatial** factors the scheduler
chose - how many ways the node fans a dimension across its PEs. The mapspace
asks for output channels two ways and output rows two ways, so `2 x 2 = 4`
fills the four PEs of a node. But the realized fan for each dimension is the
largest divisor of that layer's own dimension that fits the cap, so a layer
whose dimension is smaller than the cap gets a narrower fan.

Over the 151 schedulable pairs the width is:

| width | pairs | why |
|---:|---:|---|
| 4 | 145 | both output channels and output rows divide by 2 |
| 2 | 5 | one of the two does not - a single output row, or an odd channel count |
| 1 | 1 | neither does |

All five width-2 layers have a **single output row**, so their row fan is 1 and
the 2 comes from the channel fan alone: A08's classifier, B09/`loas_vgg16`'s
classifier, C01/`sma_azo_vgg_cifar10_dvs`'s final head (all three at 10 output
channels) and both C01 penultimate layers (at 1,024). The single width-1 layer
is C01/`sma_azo_vgg_dvs128_gesture`'s final head, whose 11 output channels admit
no even fan either, so both fans collapse to 1. So **a check that assumed a
flat width of 4 would wrongly reject 6 of 151 layers**, and one of those six is
the cross-architecture example this document uses.

A second quantity is easy to confuse with the width and is not it: the number
of **cores** in the machine, which is the product of *all* the schedule's
spatial factors, not just the node-level ones. For A08's classifier the wave
width is 2 while the machine has 16 cores. Both are per-schedule, and they are
different numbers.

### 1.2a Why the width changes nothing on any campaign layer

A wave groups **output rows**, and output rows are the only thing it groups: the
generator builds exactly one row-list per resident output row, so a tile has
`HO_resident` of them and no more. Output channels are not lanes in this sense -
a channel slab rides inside each row's records rather than forming its own list.

This mapspace fans output rows two ways, so `HO_resident` is **at most 2**. With
a width of 4 and at most 2 row-lists, **every tile is a single wave** on every
one of the 151 layers: the width is larger than the thing it bounds.

So no layer's ticks or cycles depend on the width as long as it is at least 2 -
widths 2, 3 and 4 all give the same single wave. Only a width of **1** behaves
differently, splitting the two rows into consecutive waves and removing the
concurrency of section 2.2. The width is a real per-schedule quantity, it is
computed correctly, and it is inert across this campaign. That bears directly
on caveat G2: a wrong positive width above 1 cannot change any output here.

### 1.3 What a tile means

The mapspace holds the whole kernel and all input channels resident, fans
output channels and output rows two ways each, caps the output column extent at
one, and **bars the timestep dimension** from residency. So a tile is:

> *one timestep, a block of up to 2 output rows at one output column, one slab
> of up to 2 output channels, with the whole kernel window and all input
> channels available locally.*

Barring timesteps is what distinguishes this arch's tiling from every other
one here: LoAS, PTB and SpinalFlow keep the whole timestep range inside a tile,
and Prosperity does too. GustavSNN cuts along time instead, so a layer with 16
timesteps has 16 times the tiles it would otherwise have. Combined with one
output column per tile, this gives it the largest tile counts in the campaign.

### 1.4 The fetch rule, against the other four

For each resident output row, a `(kernel row, kernel column, input channel)`
line is fetched when that input fires at **this tile's single timestep**,
through that tap, anywhere in the tile's resident output-column range. One
fetch per firing line per row.

Side by side:

- **LoAS**: one fetch per line that fires at *any* timestep. Time collapsed.
- **PTB**: same fetches as LoAS; a second pass computes cycles only.
- **SpinalFlow**: one fetch per firing *event*, so a line firing at five
  timesteps is fetched five times - but all within one tile.
- **Prosperity**: on a resident kernel, one fetch per tap not already covered
  by a prefix; on a one-tap kernel, one per firing channel.
- **GustavSNN**: one fetch per firing line *at this tile's timestep*. Summed
  over the layer's tiles this is the same total as SpinalFlow's event count,
  because both fetch once per spike - but GustavSNN spreads those fetches
  across one tile per timestep where SpinalFlow emits them all inside one tile.

So GustavSNN and SpinalFlow agree on *how many* fetches a layer needs and
disagree on *where they sit*. That matters for a cache study: SpinalFlow
presents a line's repeats close together within one tile, GustavSNN presents
them in different tiles separated by every other row and channel of the
intervening timestep.

### 1.5 What one record means, and tick semantics

A record says:

> *at tick `j`, this core fetched the weights for kernel position
> `(kernel row, kernel column)`, input channel `cin`, covering output channels
> `[cout_start, cout_end)`.*

The **tick is the cycle within the tile**, and it is where this architecture
differs from every other one here: because the rows of a wave advance together,
**two rows' `j`-th lines carry the same tick**. A tick is therefore not unique
within a core - it identifies a cycle at which that core issued *several*
fetches concurrently.

The tile's cycle count is the sum of its waves' lengths, each wave's length
being its longest row's line count. A row that finishes early leaves its slots
unused, so the cycle count is set by the worst row in each wave rather than by
the average - the standard cost of lockstep lanes.

### 1.6 Why the stream format needs a relaxed tick rule

The other four architectures issue one fetch per cycle per core, so their ticks
are **strictly ascending** within a core, and the stream format's version 2
enforces exactly that. GustavSNN cannot satisfy it: concurrent lanes genuinely
produce several bursts at one tick.

Version 3 of the format relaxes the rule to **non-decreasing** within a core,
so equal ticks are legal and mean "these bursts issued on the same cycle". That
is the whole difference between the two versions, and GustavSNN is the only
arch that needs it.

Both sides of the pipe are involved. The **writer** picks the version from the
architecture name and enforces the matching rule as it writes, refusing a stream
that violates it (`src/lays/cachesim/stream.py:219` for the selection,
`:134-140` for the check). The **reader** is the C++ decoder in
`src/lays/cachesim/native/include/cachesim/trace/stream_format.h`, which accepts
either version and applies the corresponding rule, so a v2 stream with equal
ticks is rejected and a v3 stream with them is not. The consequence worth noting: concurrency is expressed only
by tick equality, so a reader cannot tell *which lane* issued which burst of a
concurrent group - only that they were simultaneous.

## 2. Worked examples

### 2.1 A08 classifier, sample 0 - completing the cross-arch series

512 input channels, 10 output channels, 32 timesteps, a 1x1 kernel. Because
timesteps are barred, the 32 timesteps become 32 separate tile positions, and
with 5 output-channel slabs that is **160 tiles**, grouped into **10 frames**
across **16 cores**. Wave width is **2**, not 4: the layer has a single output
row, so the output-row fan cannot be 2.

| | records | frames | cycles (frame 0) | stream vs LoAS |
|---|---:|---:|---:|---|
| LoAS | 1,175 | 1 | 235 | - |
| PTB | 1,175 | 1 | 261 | record-identical |
| SpinalFlow | 27,520 | 1 | 5,504 | differs |
| Prosperity | 1,175 | 10 | 10 | coordinates equal, order differs |
| **GustavSNN** | **27,520** | **10** | **176** | differs |

GustavSNN emits **27,520** records - the same count as SpinalFlow, and for the
reason section 1.4 gives: both fetch once per spike, and the layer's firing
array holds 5,504 ones, so `5,504 x 5 slabs = 27,520`. The streams are not the
same, though: a record-for-record comparison against SpinalFlow returns false,
because GustavSNN distributes those fetches across 32 timestep tiles while
SpinalFlow emits them inside one.

**No concurrency on this layer.** With a single output row there is one row per
wave, so no two rows advance together and every `(core, tick)` entry holds
exactly one address - measured, 0 of 27,520 entries hold more than one. The v3
format is *permitted* here but not *exercised*: this stream would satisfy v2's
strictly-ascending rule too.

### 2.2 A 3x3 layer - concurrency, and the v3 rule actually earning its keep

B09/`loas_vgg16` `layer_10_core_features_34`: 3x3 kernel, 512 input and output
channels, 2x2 output, 4 timesteps. Here the output has 2 rows, so the output-row
fan is 2 and the wave width is the full **4**. Each tile carries **2 output
rows**, which is what makes concurrency possible.

Measured on 64 tiles of sample 0: **every single `(core, tick)` entry holds
exactly 2 addresses** - 37,536 of 37,536 - and the maximum is 2. That is the two
resident output rows advancing in lockstep, each contributing its `j`-th line at
the same tick.

A concrete entry, predictable by hand. At frame `(dram 0, noc 0)`, core 0,
tick 0:

```
[(1, 1, 12, 0, 2), (0, 1, 12, 0, 2)]
```

Two fetches, same cycle: input channel 12 through kernel position `(1, 1)` for
one output row and through `(0, 1)` for the other. The kernel rows differ by
exactly 1 because the two output rows are adjacent - output row `ho` reads input
row `ho + kh - 1`, so the same input row is tap 1 for the lower output row and
tap 0 for the upper one. Same input, same channel, two output rows, one cycle.

**This is the stream that v2 would reject.** Both bursts carry tick 0 in one
core, which violates strictly-ascending and satisfies non-decreasing. So the
format's two versions are not a stylistic choice: on this layer the v2 writer
would raise rather than emit.

### 2.3 The width-1 layer, pinning the non-flat-4 fact in output

C01/`sma_azo_vgg_dvs128_gesture`'s final head: 1,024 input channels, **11**
output channels, 1x1 kernel, 16 timesteps. Eleven is odd, so the output-channel
fan cannot be 2; there is one output row, so the row fan cannot be 2 either.
The solved wave width is **1**.

Measured: 176 tiles, 11 frames, 11,594 records, no concurrent bursts - with
width 1 each wave holds one row by definition. A generation-time check
asserting a width of 4 would reject this layer outright, and a check asserting
"width > 1" would reject it too.

### 2.4 The heavy case, and it changes the campaign's cost ranking

C01/`sma_azo_vgg_dvs128_gesture` `layer_01_core_block2_0_0`: 3x3, 64 input and
128 output channels, 64x64 output, 16 timesteps.

**Tiles: 2,097,152.** The composition is `32 output-row blocks x 64 output
columns x 16 timesteps x 64 output-channel slabs`, confirmed against the solved
tile list. This is the largest tile count in the campaign by a factor of 3.6
over Prosperity's heaviest, and it is four times the 524,288 that
`schedule_tiles.csv` records, because that export predates tightening the
output-column cap from 4 to 1. That cap change is exactly where the factor of
four comes from: at a cap of 4 a 64-wide output row splits into 16 column
blocks, at a cap of 1 into 64.

**Records: 77,762,112**, computed rather than extrapolated. A tile's records are
the firing lines of its output rows at its one timestep, so the layer's total is
`(output-channel slabs) x (sum over every output position and timestep of the
firing lines in its receptive field)`. Summing the true per-position window
counts over the whole 64x64 grid gives 1,215,033 lines, and `64 x 1,215,033 =
77,762,112`. At 28 bytes a burst that is about **2.18 GB** for one sample.

Extrapolating instead would have been badly wrong, and this is worth recording:
a 128-tile slice gives 2.1 records per tile and a 512-tile slice gives 22.6,
against a true mean of 37.1. The solved tile order visits output positions in a
way that front-loads sparse border regions, so early slices understate by up to
18x.

**The ranking this changes.** `CAVEATS.md` records SpinalFlow's C01 layers as
the heaviest measured, at 52.5 million records. GustavSNN on the same capture
family is higher, and the mechanism is exact rather than statistical:

| arch | output-channel slab | slabs | records on C01/dvs128 L1 | on C01/cifar10_dvs L1 |
|---|---:|---:|---:|---:|
| SpinalFlow | 4 | 32 | 38,881,056 | 52,458,688 |
| **GustavSNN** | **2** | **64** | **77,762,112** | **104,917,376** |

Both architectures fetch once per spike, so both totals are
`slabs x lines`, with the same `lines`. GustavSNN's output-channel slab is 2
where SpinalFlow's is 4, so it has twice the slabs and emits **exactly twice
the records** on any layer where both fetch per spike. The factor is 2.00 by
construction, not by measurement.

So on current evidence **GustavSNN's C01 layers are the campaign's record
ceiling**, at about 105 million records and 2.9 GB for one sample of the
cifar10_dvs variant. That is the number any shard budget has to survive, and it
is 27 times Prosperity's heaviest and twice SpinalFlow's.

## 3. Where this lives in the code

The path is the same six hops as LoAS; see `walkthroughs/loas.md` section 3.
Differences only.

**Shared:** schedule loading, dispatch, the regroup step and the stream writer.
`src/lays/cachesim/stream.py:219` selects the format version by architecture
name, and GustavSNN is the one name that yields **v3**; the version-dependent
tick comparison is at `stream.py:134-140`.

**The dispatch is not quite shared.** `weight_trace.py:reconstruct_samples`
takes a `wave_width` argument and raises `ValueError` for any arch other than
gustavsnn that passes one; the complementary raise, when gustavsnn passes none,
is in `gustavsnn/native_bridge.py:133-136`. The width comes
from `weight_trace.py:node_level_spatial_product`, which reads the solved
strategy's NodeLevel `spatial_split` factors and multiplies them.

**Task packing differs:** `gustavsnn/native_bridge.py:_pack_task` writes
**12 ints per tile** rather than LoAS's 11 - adding the timestep offset and the
output-row and output-column **bounds** alongside their offsets - plus one
extra int for `wave_width` in the task header, after the tile and sample
counts. Prosperity also packs 12 and also sends those bounds, so 12 is not
unique to this arch; the `wave_width` header field is.

`_validate_wave_width` (`:32-35`) rejects a non-integer, a bool, or a value
`<= 0`, on both the Python side and again in `main.cpp`, which exits on a
non-positive value.

**GustavSNN-specific, in `gustavsnn/GustavGen.h`:**

- `reconstruct_tile` (`:76-118`) builds one `Submatrix` per resident output
  row, each holding that row's firing `(kh, kw, cin)` lines. A line is active
  when the input fires at the tile's single timestep through that tap, for any
  output column in the resident range - the activation mask is reduced along
  the output-column axis, not along the kernel.
- `addresses_and_ticks` (`:125-164`) groups submatrices into waves of
  `wave_width`, sets every submatrix in a wave to the same `wave_start`, adds
  the wave's **longest** line count to the cycle total, then emits line `j` of
  submatrix `i` at `wave_start_of[i] + j`. That last expression is the source
  of the equal ticks.
- Cycles are the sum of wave lengths, so unlike LoAS the cycle count is **not**
  the record count: a wave pays for its longest row.

## 4. Caveats

Each carries the standing question: **does it affect weight-trace generation of
any of the 8 benchmarks' layers under the current campaign?**

Partial-sum footprint first: with the output column capped at 1 and timesteps
barred, the node footprint is
`2 x HO_resident x COUT_spatial` bytes, and both factors are per-layer. Over
the 151 pairs it takes three values - **{2, 4, 8} B** against a 1,024 B budget,
with 8 B on the 145 width-4 layers. Vmem is `{4, 8, 16} B`. Nothing is remotely
near the limit, and all 151 pairs are feasible.

### G1. The shipped binary is older than its sources, and generation fails outright

*Caveat (stated at the top):* `gustavsnn/gustavgen` dates from 11-07;
`gustavsnn/main.cpp` and `GustavGen.h` were modified at 20:29 on 11-10 and the
task layout changed with them. The stale parser misreads the task, and the
mismatch surfaces as `IndexError: list index out of range` in
`weight_trace.py:assemble_layer_traces` when the returned sample index falls
outside the requested set.

- **Affects generation? YES, for every gustavsnn layer, today.** This is the
  only unambiguous yes across the five walkthroughs. A rebuilt binary from the
  current sources works; the shipped one cannot run at all.
- **Severity: loud failure, which is the good case.** The exception is raised
  before any trace is written, so there is no silently wrong output. Had the
  layout changed in a way that still parsed - a reordered field of the same
  count - it would have been silent instead.
- **Fix sketch:** rebuild before the campaign runs
  (`make -C src/lays/weight_trace_gen/gustavsnn`), and make the generation
  entry point refuse to run a binary older than its sources rather than relying
  on whoever launches it. The docs already note that `make build` covers only
  LoAS, so the other four are built by hand and can drift this way; gustavsnn
  is simply the one that has.

### G2. A wrong positive wave width is undetectable

*Caveat (sections 1.2, 3):* validation rejects a missing, non-integer or
non-positive width, on both sides. It cannot reject a **wrong positive** one,
because nothing on the native side knows what the schedule's spatial product
was - the width arrives as a bare integer.

- **Affects generation? No, on the campaign path**, where the only caller
  derives the width from the same artifact it derives the tiles from, so they
  cannot disagree.
- **Severity: silently wrong cycle counts and tick numbering.** A width larger
  than the true one merges waves that should be sequential, lowering the cycle
  count and creating equal ticks that the hardware would not produce; a smaller
  one splits waves and inflates cycles. **Addresses and their order are
  unaffected** - the width enters only `wave_start_of`, so the records are
  right and only the ticks and cycles are wrong. That makes it the worst shape
  of error to detect downstream, since the trace looks well-formed.
- **Fix sketch:** send the node-level spatial factors rather than their
  product, and have the generator multiply them itself; or carry the product in
  the task and assert it against the tile bounds, since
  `ho_n x cout_n` is an upper bound on a legitimate width.

### G3. Equal ticks lose lane identity

*Caveat (sections 1.6, 2.2):* concurrency is expressed only by tick equality, so
a concurrent group's bursts are known to be simultaneous but not which lane
issued each. On the 3x3 layer every entry is a pair, and the pair's order
reflects submatrix order in the emitting loop rather than anything the format
records.

- **Affects generation? No - observation only.** The records and their ticks
  are correct.
- **Severity: an analysis limit.** A consumer wanting per-lane behaviour cannot
  recover it, and must not infer it from within-group ordering.
- **Fix sketch:** none for the campaign. A lane id would have to be a record
  field; it cannot be derived.

### G4. Tile count, and a subset is not a safe estimator

*Caveat (section 2.4):* barring timesteps and capping the output column at 1
gives this arch the campaign's largest tile counts - 2,097,152 on C01's first
layer, 3.6x Prosperity's heaviest. Separately, the per-tile record rate varies
by 18x across the solved tile order, so a subset mean is not usable.

- **Affects generation? No - a cost, not a defect.** But it is the cost that
  sizes the campaign: about 105 million records and 2.9 GB per sample on the
  heaviest layer.
- **Severity: capacity and scheduling.** This arch runs last in the campaign,
  so a budget that fits the first four can still fail here.
- **Fix sketch:** none in the generator. Shard weights must come from record
  counts computed per layer, not from tile counts and not from subset
  extrapolation. The exact-count method in section 2.4 is cheap - one
  neighbourhood sum over the capture - and should be preferred to timing a
  slice.

### G4a. The campaign config disagreed with the mapspace: RESOLVED

*Caveat (resolved):* `mapspaces/gustavsnn.yaml`'s comment formerly said the
output column was "capped at 4" while the value was `WO: 1`, and
`sweep_config.yaml` recorded `WO: 4` with a hardcoded
`gustavsnn_wave_width: 4`. All three now agree with the mapspace: the comment
reads `WO` capped at 1, `sweep_config.yaml:48` records `WO: 1`, and `:67` names
the derivation `schedule_nodelevel_spatial_product` rather than a value.

- **Affects generation? No, and it never did** - the mapspace value is what the
  scheduler reads, and nothing consumed the comment or the sweep-config entry.
  The risk was to readers: this document's tile-count figures depend on
  `WO: 1`, so a reader checking the sweep config would have concluded they were
  wrong by a factor of four.
- **Severity: was a correctness trap for readers, not for runs.**
- **What remains:** the durable half of G2 - take the wave width from the
  schedule's NodeLevel spatial product, never from a constant, since it is 4 on
  145 layers, 2 on five and 1 on one.

### G5. Running last is not an ordering guarantee

*Caveat:* `sweep_config.yaml` lists gustavsnn last and comments that it "runs
LAST". Nothing in the output format or the record content depends on that: each
layer's stream carries its own identity block naming arch, workload, layer and
sample, and each is written independently.

- **Affects generation? No.** The ordering is a scheduling convenience, and no
  output assumes it.
- **Severity: none.** Worth stating because "runs last" could be mistaken for
  a dependency; the only real consequence is that gustavsnn's failures surface
  late, which G1 makes concrete.
- **Fix sketch:** none needed.

### G6. Shared caveats that apply here

Properties of code shared with LoAS. Task packing differs as described in
section 3, so L2's output-row/column half does not apply - GustavSNN sends
those bounds explicitly.

- **L1 stride absent from the native path.** `GustavGen.h` duplicates
  `hin = ho + kh - pad_h` with no stride term. Does not affect generation: the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`, not the bridge.** Does not
  affect generation; the campaign path runs the gate. The gate's gustavsnn
  branch additionally requires all input channels resident and exactly one
  timestep per tile, which matches this mapspace.
- **L3 padding inferred from kernel size.** Same formula, duplicated again.
  Does not affect generation: all 157 captured layers are same-padding.
- **L5 `mac_cycles` is a maximum across a frame's cores**, and it is **not**
  degenerate here: cores hold different output-row blocks and channel slabs and
  so diverge, as they do for Prosperity and unlike LoAS.
- **L6 bare assert as the only framing check.** Shared, and G1 is what happens
  when the framing actually breaks - the assert is not what caught it.
- **L7 the stream writer trusts its caller for the machine width.** Shared, and
  sharper here: the machine width and the wave width are different per-schedule
  numbers that are easy to confuse, as G2 describes.
- **L10 blocking rather than sparsity decides the footprint.** Applies. This
  arch has the most intra-layer reuse of any of the five, since a line's
  repeats are spread across timestep tiles, so capacity sweeps have the most
  room to move its numbers.

## 5. Limits of this write-up

1. **The 77.8 million and 104.9 million record figures were not produced.**
   Both are computed from per-position window counts summed over the capture,
   times the slab count. No full-layer run was performed, and the largest run
   here was 512 tiles of 2,097,152.
2. **The 2.00x ratio against SpinalFlow is derived, not measured.** It follows
   from both architectures fetching once per spike and from the slab widths 2
   and 4. The per-spike equivalence is checked on A08's classifier, where both
   emit 27,520 records, but not on the C01 layers themselves.
3. **No wall-clock or memory figure is given for the heavy layer.** The subset
   timings are unusable for extrapolation here, by the same 18x variance that
   makes the record rate unusable, so no time or peak-memory estimate is
   offered at all.
4. **4 of 151 layers were generated.** A08's classifier, B09/`loas_vgg16`'s
   `features_34` (64 tiles), C01/dvs128's final head, and 512 tiles of C01's
   first layer. The wave-width distribution over all 151 is computed from the
   mapspace caps and each layer's dimensions, and it reproduces the 145/5/1
   split recorded for the earlier schedules, but 147 of those widths were not
   solved here.
5. **The concurrency measurement covers one layer.** Every `(core, tick)` entry
   holding exactly 2 addresses is from 64 tiles of one 3x3 layer. Whether a
   wave ever carries 3 or 4 concurrent bursts is untested - it would need a
   layer whose output-row fan exceeds 2, which this mapspace does not produce.
6. **Every measured number is sample 0 of one sample.** Record counts scale
   with sparsity, which varies per sample.

## 6. Reproducing

Solve via the scheduler's cache-and-solve entry point with the campaign
`arch.yaml` and `mapspaces/gustavsnn.yaml`; take the wave width from
`node_level_spatial_product` on the solved strategy and the machine core count
from the product of all the schedule's spatial factors. **Rebuild `gustavgen`
from the current sources first** (G1), or the run fails in assembly. Generation
goes through the arch dispatch with `wave_width=` supplied. Concurrency is
detected by looking for a single core holding more than one address at one tick,
not by looking for a repeated tick value - the wire format buckets addresses by
tick, so a repeated value never appears. The heavy layer's record total is a
3x3 neighbourhood sum of per-input-pixel event counts over the capture, times
the output-channel slab count. Drivers and the rebuilt binary are in this
session's scratchpad; nothing was written into the repo.
