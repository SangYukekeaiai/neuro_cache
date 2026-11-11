# Generator walkthrough: PROSPERITY

Step 3 of `docs/plans/2026-11-10-wt500-restart-plan.md`, arch 4 of 5.

Four parts, logic first:

1. **How a Prosperity weight trace is generated** - the model, no code.
2. **Worked examples** - the cross-arch comparison, and a demonstration of the
   kernel rejection on a real 3x3 layer.
3. **Where this lives in the code** - the implementation path.
4. **Caveats** - each with a verdict on whether it affects generation of any of
   the 8 benchmarks' layers.

Everything measured here was run on this host against the finalized
`zoo/wt500_fig3cfg/arch.yaml` and `zoo/wt500_fig3cfg/mapspaces/prosperity.yaml`
and the real n=500 captures. The solves here come from the scheduler's
cache-and-solve entry point, which sweeps every traffic mode and keeps the
best-scoring one. The **campaign** path now does the same: `gen_inputs.py`
invokes `python -m lays.scheduler enumerate --time-limit 30`, which solves
every traffic mode and selects by the same CoSA reference score (w_u 0.1,
w_tr 1.0, w_dl 10.0). The figures below therefore describe the campaign's
actual selection rule, not merely a projection of it onto the quantities that
happen to be mode-invariant. Tile counts and gate results remain
mode-invariant in any case. These are still not byte-for-byte the campaign's
schedules: a re-solve can return a different optimum at the same score.

**The headline: Prosperity's compression is active on its 3x3 layers and
degenerate on its 1x1 ones, and the split is 47 against 98.**

The mapspace caps the kernel dimensions at 4, so a 3x3 kernel is wholly
resident and a row carries nine bits - enough for prefix reuse to do real work,
measured at about 2x. A 1x1 layer has one bit per row, and a one-bit row has no
pattern to compress: after the first firing row in a tile every later one finds
an exact prefix and fetches nothing, so the fetch rule collapses to one fetch
per firing input channel, numerically LoAS's rule. Measured on A08's
classifier: 1,175 records, the same count as LoAS, against SpinalFlow's 27,520.

Of the 151 schedulable pairs, **145 generate** - 47 at nine bits per row with
compression active, 98 at one bit per row where it is inert - and 6 are
infeasible at the partial-sum capacity.

## 1. How a Prosperity weight trace is generated (the logic)

### 1.1 The published idea: product sparsity

Prosperity's premise is that spiking inputs repeat themselves. Consider the set
of kernel taps that fire for one input channel at one output position and
timestep - call that a **row**, a small set of taps drawn from the kernel
window. Across the many rows of a layer the same tap-sets recur, and more
usefully, one row's tap-set is often a **superset** of another's.

When it is, the weights for the shared part have already been fetched. Only the
**difference** needs fetching. That is the compression: a row whose tap-set
contains an earlier row's needs only the extra taps, not the whole set.

Making that pay off requires seeing the small sets before the large ones, so
rows are processed in order of **increasing number of firing taps**, ties
broken by original position. For each row, the machine looks back over rows
already processed, finds those whose tap-set is a subset of the current row's,
and takes the **most recently processed** such row as its prefix. The fetched
pattern is then the current row's taps **minus** the prefix's taps. If no
processed row is a subset, the full tap-set is fetched.

So the fetch count is not the number of firing taps - it is the number of
firing taps **that are not already covered by a prefix**. That is the quantity
Prosperity is built to reduce, and it is strictly smaller than the raw count
whenever supersets occur.

### 1.2 What a tile means under the finalized mapspace

The mapspace holds up to 16 input channels and all timesteps resident, keeps a
block of 8 output rows, fans output channels across the PEs (a node's slab is
capped at 4; the machine-wide fan is the schedule's spatial product), and bars
the kernel dimensions and the output column dimension from residency. A tile is
therefore:

> *a block of up to 8 output rows at one output column, one slab of up to 4
> output channels, one group of up to 16 input channels, with the whole kernel
> window and all timesteps resident.*

Every bound there is a cap, not a fixed size: the realized extent is the
largest divisor of the layer's own dimension that fits. A08's classifier has a
single output row and 10 output channels, so its tiles carry one row and a slab
of **2** channels, not 8 and 4.

Two features of this shape matter.

**Input channels are resident as a group but processed one at a time.** A
prefix is only meaningful between rows of the *same* input channel: a tap-set
from a different channel names entirely different weights, so reusing it would
be wrong. The 16 resident channels are therefore walked as 16 independent
sequences, each with its own prefix history, and their results concatenated.
Correctness here comes from that separation, not from the compression.

**The kernel is resident, so a row's tap-set is as wide as the kernel.** A 3x3
layer gives nine bits per row and a 1x1 layer gives one. That single number
decides whether the compression does anything at all, which is section 1.3.

### 1.3 Where the compression works, and where it collapses

**With nine bits per row it works.** Rows carry real tap-sets, supersets occur,
and a row whose taps contain an earlier row's fetches only the difference.
Measured on a 3x3 layer, 128 tiles of sample 0: 18,768 raw spike bits reduce to
9,084 fetches, about **2.07x**, in the same range as the 2.52x and 1.49x this
generator already records on two other layers.

**With one bit per row it collapses.** Rows sort by firing-tap count, so all
non-firing rows come first, then all firing rows. The first firing row finds a
non-firing row as its prefix - the empty set is a subset of everything - so it
fetches its one tap. Every **later** firing row finds the previous firing row as
its prefix, whose single tap is a subset of its own single tap, so the
difference is **empty** and it fetches nothing.

The fetch rule there collapses to: **one fetch per input channel that fires
anywhere in the tile, and nothing more.** Not one per spike, not one per
timestep - one per channel, exactly as if the time axis had been collapsed by an
any-fire test. Which is LoAS's rule, reached by a completely different route.

A warning about reading the ratio: the collapsed case shows a **higher**
apparent compression than the working one - 3.76x against 2.07x on the same
layer's data - because one fetch standing in for many spikes looks like
aggressive reuse. The ratio alone does not tell the two apart; the bit width
does.

Put beside the others:

- **LoAS**: one fetch per `(tap, channel)` line that ever fires. Time collapsed
  by an any-fire test.
- **PTB**: the same fetches; a second pass pairs non-colliding lines to compute
  cycles only.
- **SpinalFlow**: one fetch per firing **event** - once per timestep a channel
  fires. Time never collapsed.
- **Prosperity, as configured**: one fetch per firing channel, because the
  one-bit rows make every prefix exact after the first.

So three of the four architectures fetch the same *number* of lines, and
SpinalFlow is the outlier at roughly 23x more. The compression machinery is
real and would matter with a multi-tap kernel; with a single tap it has no
work to do.

### 1.4 What one record means, and tick semantics

One record says:

> *at tick `j`, this core fetched the weights for kernel position
> `(kernel row, kernel column)`, input channel `cin`, covering output channels
> `[cout_start, cout_end)`.*

Same shape as the other three architectures, same burst along the output-channel
axis, same bytes per record.

The **tick is the position of the fetch in processing order**, and processing
order is the firing-tap-count sort, not the natural output-position-and-timestep
order. One cycle is charged per fetched tap, so the cycle count equals the
record count exactly - no competing compute term, unlike PTB.

A consequence of the sort worth stating plainly: **record order does not follow
the output positions or the timesteps.** With one-bit rows the sort puts every
non-firing row first and then the firing rows in original order, so what
survives is ordered by channel and position - but that is a side effect of the
degenerate case, not a general property.

Each resident channel's sequence is numbered from zero and the sequences are
then concatenated, with later channels' ticks shifted past earlier ones, so the
tile's ticks remain dense and ascending overall.

### 1.5 How per-core streams become one file

Unchanged from the other three. Cores sharing a tile position are interleaved
tick-major, absent cores omitted; one frame per `(dram_i, noc_i)` tile group; a
header, the frames, an
end marker and a total count. Prosperity writes the **strictly ascending** tick
variant, satisfied by the concatenated per-channel numbering.

## 1.6 The two configurations in this document

Measurements are tagged with the configuration they were taken under, the way
`prosperity_infeasibility.md` tags its two.

**Config A - current** (`mapspaces/prosperity.yaml`, commit `b927291`): `KH: 4`,
`KW: 4`, `CIN: 16`, `COUT: {spatial: 4}`, `HO: 8`, `T: full`, `WO` absent. A
3x3 kernel is wholly resident. **6 infeasible, 0 kernel-refused, 145
generating.**

**Config B - barred kernel**: the same with `KH` and `KW` also absent, so every
kernel tap becomes its own tile. **6 infeasible, 47 kernel-refused, 98
generating.** Section 2.2's rejection demonstration is config B and is kept
because the mechanism it shows - a solver happily splitting a kernel the wire
format cannot represent - is a real property of the gate and the bridge, not a
historical note.

## 2. Worked examples

### 2.1 A08 classifier, sample 0 - the cross-arch series completed

The layer: 512 input channels, 10 output channels, 32 timesteps, 1x1 kernel.
The solve differs from the other three architectures because the mapspace does:
output channels split 2 per core, input channels in groups of 16, giving
**160 tiles** (32 input-channel groups x 5 output-channel slabs) across 16
cores, which group into **10 frames**. Frames are
`dram_num_steps x noc_num_steps`, and that split is **not** reproducible across
solves of this layer - runs have produced 10x1, 1x10 and 5x2 - so only the
product, 10 frames and 160 tiles, is a stable fact about the layer. Several
schedules score equally here.

| | fetches per output slab | records | frames | cycles (sum over frames) | ordered stream vs LoAS |
|---|---:|---:|---:|---:|---|
| LoAS | 235 | 1,175 | 1 | 235 | - |
| PTB | 235 | 1,175 | 1 | 261 | **identical** |
| SpinalFlow | 5,504 | 27,520 | 1 | 5,504 | differs |
| **Prosperity** | **235** | **1,175** | **10** | **100** | differs in order only |

The cycle column is the sum of each frame's cycle count, and a frame's count is
the **maximum across its cores**. Prosperity's 100 is ten frames at 10 each.
That is lower than its own record count, and it is the one arch here where the
max-over-cores aggregation is not degenerate: its cores genuinely diverge,
because each walks a different input-channel group, where LoAS's cores all walk
identical lines and differ only in their output-channel run. Shared caveat L5
is what explains the 100.

Prosperity's record count equals LoAS's exactly, and the reason is checkable:
of the 1,175 records, the distinct `(input channel, output slab)` pairs number
**1,175** - every pair appears exactly **once** - and the 235 channels appearing
are precisely the 235 channels that fire somewhere in the 32 timesteps. So the
trace is "each firing channel, once per output slab", confirming section 1.3's
derivation on real data.

But the **ordered stream differs from LoAS's, while the coordinates do not**.
Measured both ways: against LoAS, set equality is **true** and multiset
equality is **true** - the same 1,175 coordinates with the same multiplicities.
Against SpinalFlow, set equality is **true** as well, since its 27,520 records
collapse onto the same 1,175 coordinates, but multiset equality is false. So
what distinguishes Prosperity from LoAS is only the **order and the tick
numbering**, not which weights are fetched: Prosperity's tiling cuts input
channels into groups of 16 and its ticks follow processing order within each
group. The first frame opens at channels 0, 1, 2, 4 - skipping silent channel
3 - and the second frame opens at channel 20, where LoAS continues the same
monotone sequence in one frame.

The whole layer is 1,175 bursts in 34,638 bytes, against LoAS's 33,176 for the
same 1,175 records. Both counts assume a header carrying a single
spatial-factor entry, which is what the drivers here passed; the production path
passes the full seven-key dict for a 48-byte-larger header. The 1,462-byte
difference is mostly **per-core frame entries** - 160 of them against LoAS's 5 -
rather than the 10 frame headers.

### 2.2 Config B: what happens when the kernel is not resident

**This section is config B, not the campaign's configuration.** Under config A
the layer below generates normally with the whole kernel resident, 8,192 tiles
and zero gate violations. It is kept because it demonstrates a property of the
gate and the wire format that holds whenever a schedule splits a kernel: the
solver will produce such a schedule happily, and only the gate stops it.

Layer: B09/`loas_vgg16` `layer_10_core_features_34`, a 3x3 convolution, 512
input and output channels, 2x2 output, 4 timesteps.

**Step 1 - the solve succeeds.** **73,728 tiles**. The solver is perfectly
happy: nothing in the constraint model says a tile must hold a whole kernel.

(Solver provenance is as stated at the top of this document: a mode sweep
rather than the campaign's BASE mode, with tile counts and gate results
mode-invariant.)

**Step 2 - but the kernel is split.** The problem declares a 3x3 kernel, while
the solved tile holds `KH = 1, KW = 1`. Each tile covers one of the nine taps.

**Step 3 - the gate refuses it.** Running the campaign's bridge-compatibility
check on the solved schedule:

```
prosperity  passed=False  tiles_checked=73728  violation_count=245760
            violation_codes={'kernel_tile_bound': 147456, 'kernel_offset': 98304}
```

The individual records, verbatim from the first tiles:

```
{"tile": 0, "code": "kernel_tile_bound",
 "message": "KH tile bound is not the full kernel",
 "dimension": "KH", "bound": 1, "expected": 3}
{"tile": 0, "code": "kernel_tile_bound",
 "message": "KW tile bound is not the full kernel",
 "dimension": "KW", "bound": 1, "expected": 3}
```

Both counts are explicable. `kernel_tile_bound` fires twice per tile, once for
each kernel dimension: `73,728 x 2 = 147,456`. `kernel_offset` fires for every
non-zero kernel offset, and offsets run 0, 1, 2 in each dimension, so two
thirds of tiles are non-zero in each: `73,728 x 2/3 x 2 = 98,304`.

**Controls.** The same check on the **same layer** for LoAS reports
`passed=True` with 512 tiles and zero violations, because LoAS's mapspace keeps
the kernel resident. On Prosperity's **1x1** A08 classifier it reports
`passed=True` with 160 tiles and zero violations. And under **config A** the
same 3x3 layer reports `passed=True` with 8,192 tiles and zero violations. So
the gate discriminates on exactly the property at issue - whether a tile holds
the whole kernel - and not on the architecture.

**The accounting under both configurations**, applying the psum boundary and
the kernel rule to the 151 schedulable prosperity rows of the staged manifest
digest:

| outcome | config A (current) | config B |
|---|---:|---:|
| infeasible at solve (psum capacity) | 6 | 6 |
| refused by `kernel_tile_bound` | **0** | 47 |
| **generated** | **145** | 98 |
| total | 151 | 151 |

The psum column is identical because the kernel dimensions do not appear in the
partial-sum term. Of config A's 145 generating layers, 47 are 3x3 with nine
bits per row and 98 are 1x1 with one. The digest itself records an earlier
solve - 134 feasible, 17 infeasible, 6 loader-excluded - which is the staleness
tracked as P3 in `CAVEATS.md`; both columns above are that same layer list
re-evaluated.

### 2.3 The largest tile count in the campaign: A07's BERT GEMMs

A07's GEMMs are 1x1, so they survive the kernel rule and are Prosperity's
heaviest generating layers. Measured on
`layer_05_core_bert_encoder_layer_0_intermediate_dense` (768 input channels,
3,072 output channels, 128 output rows, 4 timesteps):

| quantity | value |
|---|---:|
| tiles | **589,824** |
| composition | 48 input-channel groups x 768 output-channel slabs x 16 output-row blocks |
| native one-channel tiles after expansion | **9,437,184** per sample |
| records | about **3.9 million** |
| extrapolated generation time | a few minutes |

This layer has **589,824** tiles under the current mapspace, the largest tile
count measured in the campaign, and 24 of A07's layers share it. The staged
export `schedule_tiles.csv` records 1,179,648 for it, from a solve with 4
resident output rows rather than 8. Largest tile count is not the same as
largest cost, as the rest of this section shows.

**But tile count is a poor cost proxy across architectures, and this is the
sharper point.** Records per tile:

| heavy case | tiles | records | records per tile |
|---|---:|---:|---:|
| SpinalFlow, C01 `block2_0_0` | 131,072 | about 52,500,000 | 400.2 |
| Prosperity, A07 `intermediate_dense` | 589,824 | about 3,900,000 | 6.6 |

Prosperity has 4.5x the tiles and about **one thirteenth** the records. Since
record count drives both output volume and the memory that killed the earlier
pilot, **SpinalFlow's C01 layers are the real cost ceiling of the campaign, not
Prosperity's A07 GEMMs** - the opposite of what a tile-count ranking says. Any
shard weighting should be records-based, or tile-count-based per architecture
rather than across them.

## 3. Where this lives in the code

The path is the same six hops as LoAS; see `walkthroughs/loas.md` section 3.
Prosperity shares the least of the four.

**What is shared:** schedule loading, dispatch, the regroup step and the stream
writer, all common code. Prosperity is not gustavsnn, so the stream writer
selects **v2** with its strictly-ascending tick rule.

**What is not:** `prosperity/native_bridge.py`'s `_pack_task` **differs** from
the other three, which are byte-for-byte identical to each other. Verified by
diff: Prosperity packs **12** ints per tile rather than 11, sending
`node_bound[DIM_HO]` and `node_bound[DIM_WO]` alongside their offsets, and
dropping the input-channel count because each native tile carries exactly one
channel.

Prosperity-specific pieces:

- `_expand_cin_tiles` makes one native tile per resident input channel, setting
  that tile's channel bound to 1 and its offset to the absolute channel index.
  Its docstring states the correctness reason: "a prefix from another CIN would
  name different weights".
- `_combine_cin_results` concatenates the per-channel walks back into one tile
  result, shifting each walk's ticks past the previous walk's cycle count so
  the tile's ticks stay dense and ascending.
- `ProsperityGen.h`'s `reconstruct_sample` builds the tile's rows row-major
  (output row outer, output column middle, timestep inner), packs each row's
  taps into a 64-bit mask, sorts rows by popcount with a stable tie-break,
  then walks them selecting the most recently processed subset as prefix and
  emitting one address per set bit of the XOR pattern.
- `row.kh = bit_idx / tile.kw_n` and `row.kw = bit_idx % tile.kw_n` recover the
  kernel coordinates from the bit index.
- Cycles equal the total pattern popcount, so access and compute counts
  coincide and there is no dominance case - the header says so explicitly.
- Padding is `pad_h = (kh_n - 1) / 2` with `hin = ho + kh - pad_h`, the same
  formula as the other three, duplicated again, with no stride term.

## 4. Caveats

Each carries the standing question: **does it affect weight-trace generation of
any of the 8 benchmarks' layers under the current campaign?** Under config A the
answer is no for all five: 145 of 151 schedulable layers generate, and the 6
that do not are partial-sum infeasibilities, a scheduler result rather than a
generator caveat.

Partial-sum footprint, for completeness: with `WO` barred it is
`2 x HO_resident x COUT_spatial x T` bytes. `COUT_spatial` is 4 only when the
output-channel count is divisible by 4, so `T` alone does not set it - A08's
classifier has 10 channels, giving a slab of 2. The 6 infeasible layers are
exactly those exceeding 1,024 B.

### R1. The compression is inert on the 98 one-by-one layers

*Caveat (section 1.3):* a 1x1 layer gives one bit per row, and a one-bit row has
nothing to compress. After the first firing row in a tile every later one finds
an exact prefix and fetches nothing, so the fetch rule degenerates to one fetch
per firing input channel - LoAS's count. Measured on A08's classifier: 1,175
records, every `(channel, output slab)` pair exactly once. Under config A this
applies to the **98** 1x1 and GEMM layers; the 47 3x3 layers show about 2.07x
reuse.

- **Affects generation? No - the traces are correct.** Every fetch that should
  happen does, and no fetch is duplicated. What is lost is the architecture's
  distinguishing behaviour.
- **Severity: a study-validity question, not a correctness one.** On the 98
  one-by-one layers Prosperity's fetch counts equal LoAS's by construction, so a
  result reading "Prosperity performs like LoAS" would be describing kernel
  width rather than architecture. The 47 3x3 layers are where its behaviour
  actually differs, and they are a third of its generating set.
- **Fix sketch:** none. This is a property of 1x1 kernels rather than of the
  configuration - a one-tap row has nothing to compress under any mapspace - so
  reporting should separate the two groups rather than averaging them.

### R2. A split kernel is unrepresentable on the wire, and only the gate catches it

*Caveat (section 2.2, config B):* the task format carries kernel **bounds** and
no kernel offset, so a one-tap tile is indistinguishable from a whole-window
tile. A solver produces such schedules whenever the mapspace allows it, as
config B shows with 73,728 single-tap tiles.

- **Affects generation? No under config A**, where the kernel is resident and
  the gate passes with zero violations. The caveat is about what protects that
  invariant, not about a current failure.
- **Severity: loud failure on the campaign path, silent corruption off it.** A
  mapspace change that split the kernel again would be caught by the gate - but
  only for callers that run it (shared caveat L2).
- **Fix sketch:** if split kernels are ever wanted, a kernel-offset field must
  be added to the wire format first; the gate's refusal currently stands in for
  that missing field.

### R3. The per-channel expansion multiplies the task payload 16-fold

*Caveat (sections 1.2, 2.3):* the bridge expands each tile into one native tile
per resident input channel. At 16 resident channels that is a 16x multiplication
of the packed task. For A07's heaviest layer it means 9,437,184 native tiles,
about **453 MB** of task payload written to a temporary file per sample, where
the unexpanded tiles would be about 28 MB.

- **Affects generation? No** - it completed in the measured runs and the
  records are correct.
- **Severity: capacity.** It is a per-sample temporary file and a corresponding
  parse on the native side, so it scales with the heaviest layer rather than
  the whole campaign - but it is 16x larger than any other architecture's task
  payload for the same tile list.
- **Fix sketch:** send the resident channel range once per tile and let the
  native side loop over channels internally, keeping the per-channel prefix
  histories separate. The expansion exists for correctness of the prefix
  history, which is a property that can be maintained inside one invocation
  just as well as across sixteen.

### R4. Record order follows processing order, not position order

*Caveat (section 1.4):* rows are emitted in firing-tap-count order with a
stable tie-break, so records are not ordered by output position or timestep. In
the degenerate one-tap case this reduces to channel-and-position order, but
that is a side effect rather than a guarantee.

- **Affects generation? No - observation only.**
- **Severity: misinterpretation risk.** A consumer assuming a natural
  position-major or time-major order would be wrong, and the ordering would
  change if the kernel were ever made resident.
- **Fix sketch:** none. Worth one sentence wherever the record order is
  documented.

### R5. Shared caveats that apply here

Properties of code shared with LoAS. Prosperity's task packing differs from
LoAS's, PTB's and SpinalFlow's, which are byte-for-byte identical to each
other: 12 ints per tile rather than 11, sending the output-row and
output-column bounds and dropping the channel count. It is not alone in that -
GustavSNN also packs 12 ints and also sends those bounds - so the accurate
statement is "differs from the identical three". The HO/WO part of L2 lands
differently as a result.

- **L5 `mac_cycles` is a maximum across a frame's cores**, and for Prosperity it
  is **not** degenerate, unlike LoAS. Its cores walk different input-channel
  groups and genuinely diverge, which is why A08's classifier reports 100 cycles
  for 1,175 records. Any cross-arch cycle comparison must account for this.

- **L1 stride absent from the native path.** `ProsperityGen.h` duplicates
  `hin = ho + kh - pad_h` with no stride term. Does not affect generation: the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`, not the bridge** - and for
  Prosperity this is the caveat that matters most, since the gate is the **only**
  thing standing between a split-kernel schedule and a silently wrong trace.
  Does not affect generation on the campaign path, which runs the gate. Note
  Prosperity's packing does send the output-row and output-column **bounds**,
  not just offsets, so the HO/WO defaulting half of L2 does not apply to it;
  the kernel half applies with full force.
- **L3 padding inferred from kernel size.** Same formula, duplicated again.
  Does not affect generation: all 157 captured layers are same-padding. Note
  that with the kernel barred, `pad = (1 - 1) / 2 = 0` for every tile, which is
  correct for the 1x1 layers it generates and would be wrong for the 3x3 layers
  - which the gate refuses anyway.
- **L6 bare assert as the only framing check** and **L7 the stream writer
  trusts its caller for machine width.** Shared code, shared verdicts; neither
  affects generation.
- **L10 blocking rather than sparsity decides the footprint.** Applies as it
  does to LoAS, and for the same reason: with one fetch per firing channel per
  tile there is no intra-tile temporal reuse to exploit.

## 5. Limits of this write-up

Stated so they are not mistaken for measurements.

1. **2 of the 145 generating layers were ever generated.** A08's classifier and
   a slice of A07's `intermediate_dense` were run end to end on one sample. The
   other 143 are unexercised, and the feasibility and accounting figures for
   them come from applying the capacity inequality and the kernel rule to the
   captured layer dimensions.
2. **The A07 figures are extrapolations, and the section says "measured on".**
   9,437,184 is `589,824 x 16` by arithmetic. The roughly 3.9 million records
   comes from timed 32- and 128-tile slices of the first off-chip step, which is
   not a uniform sample of the layer. The tile count and the composition
   `48 x 768 x 16` are from a real solve.
3. **The record-count ratio against SpinalFlow rests on two extrapolations,
   neither of them this document's.** The roughly 52.5 million on the SpinalFlow
   side is computed in `walkthroughs/spinalflow.md` from per-pixel window counts,
   not produced; the 3.9 million on this side is item 2. "One thirteenth the
   records" is therefore a ratio of two estimates.
4. **"The largest tile count measured in the campaign" excludes unmeasured
   ground.** GustavSNN's numbers in `layer_dim_coverage.md` are flagged as
   pre-finalization by P3 in `CAVEATS.md`, and the 47 3x3 layers that config A
   newly generates have never had their records counted at all.
5. **R1 generalizes from one layer.** The claim that Prosperity's fetch counts
   equal LoAS's on 1x1 layers is derived from the degeneracy argument and
   confirmed on A08's classifier only. The argument is structural, so it should
   hold for every 1x1 layer, but 97 of the 98 are unchecked.
6. **Every measured number is sample 0 of one sample.** Sparsity varies per
   sample; the 235 firing channels, 1,175 records and 100 cycles are
   representative rather than typical, and no spread is reported.

## 6. Reproducing

Solve via the scheduler's cache-and-solve entry point with the campaign
`arch.yaml` and `mapspaces/prosperity.yaml`; tiles via the shared schedule
loader; generation via the arch dispatch on a memory-mapped capture. The
rejection demonstration calls the campaign's own bridge-compatibility check on
the solved 3x3 schedule, with LoAS on the same layer and Prosperity on a 1x1
layer as controls. The "every `(channel, slab)` pair exactly once" property was
checked by counting record coordinates and comparing the channel set against
the firing channels computed from the raw recording. The accounting was
re-evaluated over the staged manifest digest's own 151 schedulable prosperity
rows. A07 figures come from the solved tile list, the expansion factor, and
timed runs on 32- and 128-tile subsets extrapolated to the full count. Drivers
are throwaway scripts under this session's scratchpad; nothing was written into
the repo.
