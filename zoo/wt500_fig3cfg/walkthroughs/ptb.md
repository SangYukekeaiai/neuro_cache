# Generator walkthrough: PTB

Step 3 of `docs/plans/2026-11-10-wt500-restart-plan.md`, arch 2 of 5.

Four parts, logic first:

1. **How a PTB weight trace is generated** - the model, no code.
2. **Worked examples at the logic level** - real measured numbers, hand-checkable.
3. **Where this lives in the code** - the implementation path.
4. **Caveats** - each with a verdict on whether it affects generation of any of
   the 8 benchmarks' layers.

Everything measured here was run on this host against the finalized
`zoo/wt500_fig3cfg/arch.yaml` and `zoo/wt500_fig3cfg/mapspaces/ptb.yaml` and
the real n=500 captures under `examples/input_trace/delta/`.

**The headline, stated up front because it shapes everything below: PTB's
weight-address trace is record-for-record identical to LoAS's for the same
layer.** Verified by direct comparison on A08's classifier: the same 1,175
records, the same ticks, the same channel runs. The serialized frames are
**not** byte-identical, because the cycle count travels in the frame header and
does differ (261 against 235) - it is the record stream that matches. PTB
differs from LoAS only in that cycle count, and everything genuinely new in
this document is about it.

## 1. How a PTB weight trace is generated (the logic)

### 1.1 What PTB's hardware is, and the window that defines it

PTB processes a layer on a systolic array with two bounds that matter: at most
**16 rows**, which carry output channels, and at most **8 columns**, each of
which handles a **window of 8 consecutive timesteps**. Eight columns of eight
timesteps is **64 timesteps**, and that product is the largest span of time the
array can hold at once.

This is why the mapspace caps resident timesteps at 64. The cap is not a
tuning choice: it is exactly the hardware's temporal reach, so a tile can never
be handed more time than the array can represent.

The rest of the mapspace is close to LoAS's but not the same, and the
difference matters for section 2.3. PTB caps the kernel dimensions at 4 and the
timestep count at 64, where LoAS declares both unbounded: PTB has a **finite**
temporal window and LoAS has none at all. For every layer in this campaign the
two are indistinguishable in effect - a 3x3 kernel is wholly resident under a
cap of 4, and every capture has at most 32 timesteps, well under 64 - but PTB's
window is a real bound its cycle model reads, and LoAS has no equivalent. Both
hold all input channels resident, fan output channels across the PEs (a node's
slab is capped at 4; the machine-wide fan is the schedule's spatial product),
and bar output pixels from residency.

### 1.2 What a tile means for PTB

The same thing it means for LoAS, because the residency rules are the same:

> *one output pixel, one contiguous run of output channels, with the entire
> kernel, the entire input channel range and the tile's timestep window
> available locally.*

Output pixels cannot be resident, so one tile is one pixel; output channels are
fanned spatially, so each core holds its own slab and all cores work the same
pixel at once. The number of tiles is `(off-chip steps) x (shared-buffer steps)
x (cores)`.

Since every captured benchmark has at most 32 timesteps, and 32 is under the
64-timestep cap, **the whole timestep range is always resident in one tile**
for this campaign. No layer is ever split along time.

### 1.3 The sparsity rule, and how it differs from LoAS's

PTB applies **two** passes where LoAS applies one.

**Pass 1 - silence removal.** Identical in effect to LoAS: for each
`(kernel row, kernel column, input channel)` line of the reduction, ask whether
the corresponding input fired at **any** timestep in the window. If it never
fired, the line is silent, its weights are never needed, and it produces no
fetch and no record. If it fired at least once, its weights are fetched.

This is the only pass that touches the trace. **Which weights get fetched, and
in what order, is decided entirely by Pass 1** - and Pass 1 is the same
any-fire test LoAS uses. That is the mechanical reason the two architectures
produce the same address trace.

One thing Pass 1 keeps that LoAS discards: the **per-timestep firing pattern**
of each surviving line, not just the yes/no. LoAS never needs it; PTB does,
for Pass 2.

**Pass 2 - adjacent non-overlap merge.** This is PTB's actual idea. Walk the
surviving lines in order and look at each neighbouring pair. If two adjacent
lines **never fire at the same timestep** - their firing patterns are disjoint
in time - they can share one pass through the array, because at every timestep
at most one of them has work. Such a pair merges into one group. If they ever
collide at any timestep, the line stands alone. The walk is greedy and
left-to-right: a line already absorbed into a group is not reconsidered.

The group count is what the cycle model consumes. **Pass 2 changes no
addresses, no ticks and no record count** - it is a statement about how much
time the array needs to chew through work it was going to fetch anyway.

So the difference from LoAS, precisely: LoAS asks "did this line ever fire"
and is done. PTB asks that, then additionally asks "can these two lines
timeshare", and uses the answer to compute cycles rather than fetches.

### 1.4 What one record means, and tick semantics

One record says:

> *at tick `j`, this core fetched the weights for kernel position
> `(kernel row, kernel column)`, input channel `cin`, covering output channels
> `[cout_start, cout_end)`.*

As with LoAS, the channel run is one burst and its size is
`(run width) x weight_bytes`, one byte per weight at this campaign's 8-bit
weights.

The **tick is the index of the fetch among Pass-1 survivors**: the first
surviving line is tick 0, the next tick 1, and so on. Dense, no gaps, an
ordinal rather than a time. Pass 2's grouping does not renumber anything.

### 1.5 Where PTB and LoAS genuinely diverge: the cycle count

For LoAS the cycle count of a tile *is* the number of fetches - one fetch, one
cycle, no overlap. For PTB it is the **larger of two competing costs**:

- the **access cost**, which is the number of Pass-1 survivors, i.e. exactly
  the number of fetches and ticks; and
- the **compute cost**, a systolic fill-and-drain time built from the Pass-2
  group count, how many array rows the output-channel slab occupies, how many
  8-timestep columns the window spans, and how many timesteps land in the last,
  possibly partial, column.

Whichever is larger is the tile's cycle count. A tile can therefore report
**more cycles than it has fetches** - the array is still draining after the
last weight has arrived. This never happens for LoAS, and it is the one number
a cross-architecture comparison must read differently.

The compute cost has two forms and takes the larger: one that pays for the full
timestep span, and one that pays only for the columns actually in use plus the
last column's occupancy. Which one dominates depends on the window, and both
behaviours appear in this campaign (section 2.3).

### 1.6 How per-core streams become one file

Unchanged from LoAS. Each core's ordered fetches for its own channel slab are
interleaved tick-major - all cores at tick 0, then all at tick 1 - with absent
cores omitted rather than padded. That block is one tile frame; the file is a
header describing machine and layer, one frame per `(dram_i, noc_i)` tile group,
an end marker and a
total count. PTB uses the **strictly ascending** tick variant of the format,
which its dense Pass-1 numbering satisfies by construction.

The cycle count travels in the frame alongside the records, which is where the
PTB-versus-LoAS difference actually lands in the output.

## 2. Worked examples at the logic level

### 2.1 A08 classifier, sample 0 - the same trace as LoAS, a different cost

The layer: A08's classifier, 512 input channels, 10 output channels, 32
timesteps, a 1x1 kernel. The solve gives exactly what LoAS gave - output
channels 10 split as **2 per core across 5 cores**, one pixel, **5 tiles** -
and the resident bounds are the whole kernel, all 512 input channels and all 32
timesteps.

Pass 1 on sample 0: the input fires at some point on channels
`0, 1, 2, 4, 5, 7, 10, 12, ...`, **235 of 512**. Channels `3, 6, 8, 9, 11` and
272 others never fire. So each core fetches 235 times and the layer produces
`235 x 5 = 1175` records.

Core 0's first records, predictable by hand - walk the channels in order, skip
what never fired, number what is left from zero:

| tick | input channel | why | output channels | bytes |
|---:|---:|---|---|---:|
| 0 | 0 | fired | 0-1 | 2 |
| 1 | 1 | fired | 0-1 | 2 |
| 2 | 2 | fired | 0-1 | 2 |
| - | **3** | **silent - no record at all** | - | - |
| 3 | 4 | fired | 0-1 | 2 |
| 4 | 5 | fired | 0-1 | 2 |
| - | **6** | **silent** | - | - |
| 5 | 7 | fired | 0-1 | 2 |
| - | **8, 9** | **silent** | - | - |
| 6 | 10 | fired | 0-1 | 2 |
| - | **11** | **silent** | - | - |
| 7 | 12 | fired | 0-1 | 2 |

Last record: tick 234, channel 508. This table is identical to the LoAS one,
and direct comparison of the two generators' full output confirms it: **the
1,175 records match exactly, record for record.**

**Pass 2, and the cost that differs.** Of the 235 survivors, the greedy walk
finds only **8 mergeable adjacent pairs** out of 234 candidates, leaving
**227 groups**. Merges are rare for a quantitative reason: the 5,504 firing
events are spread over just 235 surviving channels, so a **survivor** is active
on `5,504 / 235 = 23.4` of the 32 timesteps on average. Two lines each
occupying roughly three quarters of the window almost always collide somewhere,
so disjointness is the exception. (Averaged over all 512 channels the figure is
10.75, but that population includes the 277 silent channels, which are never
merge candidates.)

The resulting costs, with the array parameters this layer gives:

- access cost = **235** (the fetch count)
- array rows occupied = 2 (the core's 2-channel slab, well under the 16 available)
- columns spanned = 4 of 8 (32 timesteps at 8 per column)
- last column occupancy = 8 timesteps (exact, not partial)
- compute cost = **261**

So the tile reports **261 cycles for 235 fetches** - compute-bound, draining
for 26 cycles after the last weight lands. LoAS reports 235 for the same
trace. Independently recomputed from the raw recording: Pass 1 gives 235, Pass
2 gives 227 groups, and the published formula on those yields 261, matching the
generator exactly.

### 2.2 C01 classifier head at 10 timesteps - a partial window, and zero merges

C01/`sma_azo_vgg_cifar10_dvs`'s final head: 1,024 input channels, 10 output
channels, 10 timesteps, 1x1 kernel. Solve: 5 tiles again, 2 output channels per
core.

Pass 1: only **91 of 1,024** channels fire - far sparser than A08's classifier.
The first surviving channels are `7, 23, 32, ...`, so core 0's trace opens
tick 0 on channel 7, tick 1 on channel 23, tick 2 on channel 32. The whole
layer is `91 x 5 = 455` records.

Pass 2 finds **zero** mergeable pairs among the 90 candidates, so the group
count equals the survivor count at 91. With only 10 timesteps there is little
room for two lines to be disjoint in time and still both fire.

The window here is **partial**: 10 timesteps span 2 columns, and the second
column holds only **2** timesteps rather than a full 8. That is handled by the
formula's last-column term directly - no special case, no padding of the
window, no truncation of work. Cost: access 91, compute **103**, so again
compute-bound.

### 2.3 The window across every campaign timestep count

The array's column usage and last-column occupancy are fully determined by the
resident timestep count:

| timesteps | columns used | of 8 | last column holds | partial? | which cost form dominates |
|---:|---:|---:|---:|---|---|
| 4 | 1 | 1/8 | 4 | yes | the active-drain form |
| 10 | 2 | 2/8 | 2 | yes | the full-span form |
| 16 | 2 | 2/8 | 8 | no | the full-span form |
| 32 | 4 | 4/8 | 8 | no | the full-span form |
| 64 | 8 | 8/8 | 8 | no | the full-span form |

Every captured benchmark sits in the first four rows: A02, A04, A07 and both
B09 workloads at 4, C01 at 10 and 16, A08 at 32. **No campaign layer uses more
than 4 of the 8 columns**, and the two C01 timestep counts plus the T=4
workloads run partial windows. The 64-timestep row is the saturation point and
the reason for the cap - it is the only row where all 8 columns are busy and
the last column is exactly full.

Worth noting from the table: at 4 timesteps the *other* cost form wins, the one
that pays per active column rather than for the whole span. That is the only
campaign case where it does, and it makes the T=4 workloads the ones where the
two cost forms are closest together.

### 2.4 A three-by-three layer at 4 timesteps - access-bound instead

B09/`loas_vgg16`'s `features_34`: 3x3 kernel, 512 input and output channels,
2x2 output, 4 timesteps. Solve: 512 tiles collapsing into 32 frames of 16 cores
each, 4 output channels per core.

The kernel and padding behave exactly as in the LoAS walkthrough: at the corner
pixel 5 of the 9 kernel taps fall on padding and can never fire, and the 4 real
taps contribute `264 + 239 + 282 + 248 = 1033` surviving lines. The first
records open at kernel row 1, column 1 - the first non-padding tap - with
channels 0, 1, 2 then a jump to 5.

Here the cost flips: access cost is 1,033 while the compute cost cannot exceed
roughly `groups + 8`, so the tile is **access-bound** and reports **1,033
cycles for 1,033 fetches** - the same number LoAS reports. A consequence worth
keeping in mind when reading cycle counts: when a tile is access-bound the
group count is **invisible in the output**, because the maximum discards it.
Pass 2's work cannot be recovered from the cycle count on such a tile.

Measured cost for one sample: 528,896 records across 32 frames in 2.2 s.

## 3. Where this lives in the code

The path is the same six hops as LoAS, with the same shared pieces, so only
the differences are described here. See `walkthroughs/loas.md` section 3 for
the full hop-by-hop account of schedule loading, dispatch, task packing, the
regroup step and the stream writer.

Identical to LoAS:

- **Schedule to tiles** and **dispatch** are shared code, not per-arch.
- **Task packing**: `ptb/native_bridge.py`'s `_pack_task` is byte-for-byte
  identical to `loas/native_bridge.py`'s - verified by diff of
  `src/lays/weight_trace_gen/{loas,ptb}/native_bridge.py:26` onward. Same 11 ints per
  tile (`dram_i, ho, wo, kh_n, kw_n, cin_off, cin_n, t_off, t_n, cout_off,
  cout_n`), same `tile_offset.get(DIM_HO, 0)` defaulting, same absence of a
  kernel-offset field, same trace slicing to the requested samples before
  packing.
- **Regroup**: `assemble_layer_traces` is shared; `mac_cycles` is the maximum
  across a group's cores.
- **Stream**: `src/lays/cachesim/stream.py:219` selects the v3 format only for
  gustavsnn, so PTB writes **v2**, whose strictly-ascending tick rule is
  enforced at `stream.py:134-140`.

PTB-specific, all in `ptb/PTBGen.h`:

- `reconstruct_sample` runs the two passes described above. Pass 1 builds a
  `Pass1Line` per survivor carrying `bits`, a length-`t_n` vector, rather than
  LoAS's bare yes/no.
- Pass 2 is the greedy `while` loop at the middle of the function: `merge` is
  true when no index of the two neighbours' `bits` is set in both, and `ln`
  counts groups.
- `row.tick = (int32_t)i` indexes **Pass-1** lines, and the comment states
  this explicitly ("Address traversal uses Pass-1 lines directly (NOT Pass-2
  groups)").
- `compute_cycle_count(ln, cout_n, total_t)` (`ptb/PTBGen.h:73-79`) implements
  the systolic formula with `TW_SIZE = 8`, `PE_ROWS_MAX = 16`,
  `PE_COLS_MAX = 8` (`:37-39`), returning the maximum of a full-span term and
  an active-drain term.
- `result.mac_cycles = std::max(access_cycle_count, compute_cycles)`
  (`PTBGen.h:162`), where the access count is the Pass-1 survivor count. The header calls out that this
  differs from LoAS, SpinalFlow and Prosperity, which all use the survivor
  count directly.
- Padding is `pad_h = (kh_n - 1) / 2`, `hin = ho + kh - pad_h`
  (`PTBGen.h:86-98`) - the same formula as LoAS, duplicated in this header,
  with no stride term.

## 4. Caveats

Each carries the dispatched question: **does it affect weight-trace generation
of any of the 8 benchmarks' layers under the current campaign?** All 151 PTB
pairs are feasible - PTB bars output pixels from residency, so its partial-sum
footprint is `2 x 1 x 1 x COUT_spatial x T` bytes. Over the 151 pairs it takes
six values, `{16, 32, 40, 80, 128, 256}` B, against a 1,024 B budget. The
minimum, 16 B, is B09/`loas_vgg16`'s classifier, whose `COUT = 10` gives
`COUT_spatial = 2` at `T = 4`; the maximum, 256 B, is the A08 layers at
`T = 32`. No layer is within a factor of four of the limit.

### B1. Only 4 of the 8 array columns are ever used

*Caveat (section 2.3):* column usage is `ceil(timesteps / 8)` capped at 8. The
deepest campaign workload is A08 at 32 timesteps, which spans 4 columns; the
T=4 workloads span 1. No campaign layer uses more than half the array's
temporal width.

- **Affects generation? No.** Column count enters only the compute-cost
  formula; it has no influence on which weights are fetched, their order, or
  their ticks. Addresses are set by Pass 1 alone.
- **Severity if it mattered: efficiency and modeling fidelity, never
  correctness.** The traces are right; the cycle numbers describe an array
  running at half temporal occupancy, which is a true statement about the
  modeled hardware on these workloads rather than an error.
- **Fix sketch:** nothing to fix. If the study wants PTB evaluated at full
  temporal occupancy it needs a capture with 64 timesteps, not a code change.

### B2. Timestep counts that are not multiples of 8 give partial windows

*Caveat (section 2.2, 2.3):* C01 runs at 10 and 16 timesteps and five workloads
run at 4. At 10 the last column holds 2 timesteps of its 8; at 4 it holds 4.

- **Affects generation? No, and the partial case is handled explicitly.** The
  formula's last-column term is `timesteps - 8 x (columns - 1)`, which is the
  true occupancy of the final column, so a partial window is costed at its
  real size. There is no rounding up to a full window, no zero-padding of the
  timestep axis, and no truncation of work. Verified on the C01 head at 10
  timesteps: last column 2, cost 103, matching an independent recomputation.
- **Severity: none for correctness.** At 16 timesteps the division is exact, so
  that workload runs full windows in both its columns.
- **Fix sketch:** none needed.

### B3. The formula assumes the resident timestep count never exceeds 64

*Caveat (derived in section 2.3):* column count is capped at 8 but the
last-column term is not. Above 64 resident timesteps the term exceeds the
8-timestep window width - at 72 it computes 16 - which would describe a column
holding twice the time it can hold.

- **Affects generation? No.** The mapspace caps resident timesteps at 64, so a
  tile's window can never exceed 64, and the deepest capture is 32 anyway. The
  cap is exactly `8 x 8`, the array's own reach, which is what keeps the
  formula in its valid range.
- **Severity if the precondition changes: silently wrong cycle counts**, not
  wrong traces. A capture deeper than 64 timesteps would still be split along
  time by the cap, so reaching the bad range needs the cap itself to be raised.
- **Fix sketch:** add an assertion that the window is at most
  `TW_SIZE x PE_COLS_MAX`, so raising the cap fails loudly instead of producing
  a quiet overrun. The behavioural facts, for whoever resolves the mapspace's
  open question about this value: the window must be at most
  `TW_SIZE x PE_COLS_MAX = 64` for the last-column term to stay within a
  column, and a 32-tick window would strand four of the eight columns by
  construction while changing nothing for the current captures, all of which
  are at 32 timesteps or fewer.

### B4. The Pass-2 group count depends on enumeration order

*Caveat (section 1.3):* Pass 2 is a greedy left-to-right walk over adjacent
pairs in the fixed kernel-row, kernel-column, input-channel order. Whether two
lines are neighbours - and therefore whether they can merge - is a property of
that enumeration, not of the spike pattern. A different iteration order over
the same data would give a different group count and so a different cycle
count. Greedy pairing is also not optimal: it never reconsiders a line it has
already absorbed.

- **Affects generation? No.** The group count feeds only the cycle number.
  Addresses, order and ticks come from Pass 1.
- **Severity: a modeling-fidelity question, not a defect.** The published
  architecture pairs physically adjacent rows, so order dependence is faithful
  to the hardware rather than an artifact - but the resulting count should not
  be read as "the best achievable grouping for this spike pattern".
- **Fix sketch:** none. Worth one sentence wherever the cycle model is
  documented, so the number is not mistaken for an optimum.

### B5. An access-bound tile hides its group count

*Caveat (section 2.4):* the cycle count is the maximum of the access and
compute costs, so on an access-bound tile the group count is discarded and
cannot be recovered from the output. B09/`loas_vgg16` `features_34` is such a
tile: 1,033 fetches and 1,033 cycles, with the Pass-2 result invisible.

- **Affects generation? No - an observability limit, not a defect.**
- **Severity: cosmetic, with an analysis trap.** Any attempt to measure PTB's
  compression benefit from cycle counts alone will silently see nothing on
  access-bound tiles, and both regimes occur in this campaign: A08's classifier
  is compute-bound (261 vs 235), the 3x3 layer at 4 timesteps is access-bound.
- **Fix sketch:** if the compression effect is to be reported, emit the group
  count as its own field rather than inferring it from cycles. Inference works
  only while a tile is compute-bound.

### B6. Shared caveats that apply here unchanged

These are properties of code PTB shares with LoAS, not rediscoveries. See
`walkthroughs/loas.md` section 5 and the `loas` section of `CAVEATS.md`; the
verdicts carry over because the code is the same.

- **Stride is absent from the native path** (loas L1). `PTBGen.h` duplicates
  `hin = ho + kh - pad_h` with no stride term. Does not affect generation: the
  loader excludes the 6 stride-2 layers for every arch.
- **The bridge gate lives in `gen_inputs.py`, not the bridge** (loas L2).
  `_pack_task` is identical to LoAS's, including the HO/WO offset defaulting
  and the missing kernel-offset field. Does not affect generation: the campaign
  path runs the gate. Latent for other callers.
- **Padding is inferred from kernel size** (loas L3). Same formula, duplicated
  in `PTBGen.h`. Does not affect generation: all 157 captured layers are
  same-padding.
- **The only output framing check is a bare assert** (loas L6) and **the stream
  writer trusts its caller for the machine width** (loas L7). Shared code,
  shared verdicts: neither affects generation.
- **Blocking, not sparsity, decides the footprint** (loas L10). PTB's address
  trace is identical to LoAS's, so this applies verbatim and with the same
  numbers - at 8 input channels per line, core 0 of A08's classifier touches
  every line in its slab despite fetching only 235 of 512 times.

## 5. Limits of this write-up

Three things this document does not establish, stated so they are not mistaken
for measurements.

1. **The 64-timestep window value is settled by argument, not by evidence of
   intent.** Section 2.3 and caveat B3 show that 64 is the only value
   consistent with the generator's own array constants, and that a smaller
   value would strand columns. That is an argument from the hardware model; it
   is not evidence of what the value was meant to be, and nothing here recovers
   the original intent.
2. **148 of the 151 pairs are analytic, not solved.** Three layers were solved
   locally with the real solver and generated from real captures: A08's
   classifier, C01/cifar10_dvs's classifier head, and B09/`loas_vgg16`'s
   `features_34`. The feasibility claim for the other 148, and the footprint
   value set in section 4, come from applying the capacity inequality to the
   captured layer dimensions rather than from solving each one.
3. **Every measured number is sample 0 of one sample.** The 235 survivors, the
   8 merges, the 227 groups, the 261 cycles, the 1,033 and 528,896 figures are
   all from a single sample of a 500-sample capture. Sparsity varies per sample,
   so the counts are representative rather than typical, and no spread is
   reported. The identity of the record stream with LoAS's is structural rather
   than statistical, so that result does not depend on the sample - but the
   cycle numbers do.

## 6. Reproducing

Solve via the scheduler's cache-and-solve entry point with the campaign
`arch.yaml` and `mapspaces/ptb.yaml`; tiles via the shared schedule loader;
generation via the arch dispatch on a memory-mapped capture; stream via the
WCTS writer with core count and spatial factors taken from the solved
schedule, all on sample 0 of each capture. The LoAS-versus-PTB address
comparison is a direct set comparison of the two generators' records for the
same layer, schedule and sample. Pass 1 and
Pass 2 were independently recomputed in Python from the raw recording - survivor
count, group count, and the published formula - and matched the generator's
reported cycle count on both the A08 and C01 heads. Drivers are throwaway
scripts under this session's scratchpad; nothing was written into the repo.
