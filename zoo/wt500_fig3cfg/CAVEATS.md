# Walkthrough caveats: parking lot

Every caveat raised by the step-3 generator walkthroughs, with a verdict on
whether it affects **current campaign generation**. User decision (2026-11-10):
**no caveat fixes now** - none of the parked items affect generation, so they
are deferred to next week. This file is the record so nothing is lost.

One section per arch, appended by that arch's walkthrough row. All five are
complete.

Prosperity's section and P1 describe the mapspace at commit `b927291`, with the
kernel dimensions capped and resident.

Fields per caveat: the caveat (cited to its walkthrough section), the
generation verdict with its reason, the severity **if the precondition ever
changes**, and a fix sketch for next week.

---

## SETTLED - config decisions, recorded not pending

### P1. Prosperity's kernel residency: RESOLVED by restoring the caps

`mapspaces/prosperity.yaml` (commit `b927291`) caps `KH: 4` and `KW: 4`, so a
3x3 kernel is wholly resident in a tile and the bridge gate passes with zero
violations. Prosperity's 151 schedulable pairs resolve as **6 infeasible at the
partial-sum capacity and 145 generating**, of which 47 are 3x3 and 98 are 1x1
convolutions and GEMMs.

Under **config B**, where `KH` and `KW` are absent and so barred (absent ==
cap 1), every 3x3 layer gets `node_bound[KH] = node_bound[KW] = 1` - a split
kernel. The wire format carries kernel bounds and no kernel offset, so a one-tap
tile is indistinguishable from a whole-window tile, and `gen_inputs.py` refuses
all 47 such layers with `kernel_tile_bound`. Config B's accounting is 6
infeasible / 47 refused / 98 generating, the 47 being the 53 class-S2 layers of
`layer_dim_coverage.md` minus the 6 infeasible before the gate.

R2 below is what carries over to config A: the gate's refusal is the only thing
substituting for a kernel-offset field the format does not have, so any mapspace
that bars the kernel reintroduces the problem.

### P2. The infeasibility boundary under the finalized mapspace

`prosperity_infeasibility.md` states the boundary for the finalized mapspace:
with `WO` barred (`WO_resident = 1`) and `HO: 8`, the binding inequality is
`2 x HO_res x 1 x COUT_spatial x T <= 1024`, so `T <= 16` where
`HO_res = 8`, and the infeasible set is **6** pairs - A08/`vgg16_cifar10_loas`
L1-L6 at 2,048 B against the 1,024 B budget.

Three layers sit on the boundary rather than over it: A08 L7-L9 have `ho = 4`,
so `HO_res = 4` and the demand is exactly 1,024 B - feasible at zero slack. The
eight C01 convolutions clear at 640 B (`T = 10`) and 1,024 B (`T = 16`).

The mechanism is one binding constraint, `cap_NodeLevel_psum`, with `T` forced
fully resident and the other factors pinned by equalities, so the result is
structural rather than a search failure. Confirmed by real solve: the six are
`status = 3` with the IIS `cap_NodeLevel_psum, node_cap_bound_HO,
node_cap_full_T, pe_split_COUT`, and L7-L9 plus the C01 layers are
`status = 2`.

---

## PENDING - needs action

### P3. `layer_dim_coverage.md`'s solve-derived counts describe the pre-finalization solve

That document's step-1c coverage matrix and every count taken from
`schedule_tiles.csv` - the 738 exported rows, the per-arch tile totals, the
151-of-157 scheduled set, the 17 infeasible pairs, the 1,179,648-tile
prosperity ceiling - were measured against the solve that preceded the mapspace
finalization.

Prosperity's numbers there are already superseded: under the finalized mapspace
it has 6 infeasible pairs rather than 17, so 145 of its 151 pairs solve rather
than 134. Under config B, where the kernel was barred, only 98 of those
generated and 47 stopped at the bridge gate; under config A all 145 generate.
Gustavsnn's mapspace changes carry the same risk.

**Action:** a refresh row the moment prosperity and gustavsnn re-solve, covering
both the coverage matrix and the tile-count and shard-weighting figures that
depend on it. Prosperity has re-solved twice now - once at finalization and
again when the kernel caps were restored - so its rows need the refresh
regardless of gustavsnn's timing, and the refresh must include record counts for
its 47 newly generating 3x3 layers. Until then, treat `layer_dim_coverage.md`'s prosperity and
gustavsnn rows as describing the earlier solve, and its loas, ptb and
spinalflow rows as current - those three mapspaces are unchanged.

One conclusion in that document is already superseded and matters for shard
weighting, so it is recorded here rather than left to the refresh: it names
**prosperity on A07's GEMMs as the campaign cost ceiling at 1,179,648 tiles**.
Under the current mapspace that layer is 589,824 tiles and about 3.9 million
records, while SpinalFlow's C01 layers are 131,072 tiles and about 52.5 million
records, so tile count is not a usable cost proxy across architectures and
weights should come from records.

**GustavSNN is now the heaviest measured, and the comparison is still pending
on one side.** Its C01 layers compute to about **105 million** records per
sample (cifar10_dvs variant; 77.8 million on dvs128), which is exactly **2x**
SpinalFlow's on the same captures - both fetch once per spike, and GustavSNN's
output-channel slab is 2 where SpinalFlow's is 4, so it has twice the slabs. The
factor is by construction, not measurement. GustavSNN also has the largest tile
count in the campaign at 2,097,152.

**The remaining gap is prosperity's.** It was computed when
prosperity generated only its 98 one-by-one layers. Its 47 3x3 layers now
generate too, and **nobody has counted their records** - they are not estimated
here, because a 3x3 layer's record count depends on both the nine-bit prefix
reuse and the tiling, neither of which transfers from the 1x1 measurements. So:
the records-over-tiles *principle* holds, tile count remains unusable as a
cross-architecture cost proxy. The ranking among layers measured so far is
**GustavSNN first at about 105 million records, SpinalFlow second at about 52.5
million, Prosperity third at about 3.9 million** - and that third figure is a
**floor**, not the number, because prosperity's 47 newly generating 3x3 layers
are uncounted. The ranking should be re-derived once they are measured.

---

## loas

Source: `walkthroughs/loas.md` section 5, caveats 1-10. None of the ten affect
current campaign generation.

### L1. Stride is absent from the whole native path

*Caveat (section 5.1):* the tile record has no stride field and the generator
computes the input row as `output row + kernel row - pad`, an implicit stride
of 1. A stride-2 layer would silently read the wrong input pixels.

- **Affects current generation? No.** The trace loader excludes non-3x3 /
  non-stride-1 convolutions, so the six stride-2 layers in the corpus (classes
  S4 and S5 in `layer_dim_coverage.md`: B09/`loas_resnet19` L1, L8, L15 and
  L3, L10, L17) are never scheduled for any arch. Confirmed independently:
  `schedule_tiles.csv` carries 151 of 157 layers, and the missing 6 are exactly
  those.
- **Severity if the precondition changes: silent wrong trace.** No guard exists
  in the generator; the protection is entirely upstream loader policy. Relax
  that filter and every stride-2 layer produces plausible, wrong addresses with
  no error.
- **Fix sketch:** add a stride field to the tile record and use it in the input
  index (`input = output * stride + tap - pad`). Until that exists, make the
  bridge guard refuse any layer whose stride is not 1, so the dependency on
  loader policy is explicit rather than implicit.

### L2. The bridge gate lives in `gen_inputs.py`, not in the bridge

*Caveat (section 5.3, 5.4):* HO/WO tile offsets default to 0 when absent and
kernel offsets are not sent at all. The only thing checking that those defaults
are safe is the gate in `gen_inputs.py` (`missing_pixel_offset`,
`pixel_tile_bound`, `kernel_offset`, `kernel_tile_bound`).

- **Affects current generation? No.** The campaign path goes through
  `gen_inputs.py`, so the checks do run. **Latent for any other caller.**
- **Severity if the precondition changes: silent wrong trace.** A caller that
  invokes the bridge directly gets no check at all: a split output-pixel
  dimension with a missing offset silently reconstructs pixel 0, and a
  kernel-split tile silently reconstructs the full window. This is the same
  mechanism as P1 above, which is why P1 is loud today and would be silent
  off-path.
- **Fix sketch (as directed):** move the guard into the bridge's shared packing
  helper - refuse a missing HO/WO offset when the problem dimension is split
  above 1, and refuse a KH/KW bound smaller than the full kernel (there is no
  kernel-offset field, so a smaller bound is unrepresentable rather than
  merely unsupported). `gen_inputs.py` keeps its own checks as the friendly
  early error, so a sweep still fails before launching work rather than inside
  a subprocess.

### L3. Padding is inferred from the kernel size, not read from the layer

*Caveat (section 5.2):* the generator hardcodes same-padding as
`pad = (kernel - 1) / 2`. A 3x3 layer with padding 0 would be reconstructed
wrongly with no error raised.

- **Affects current generation? No.** All 157 captured layers are
  same-padding: `LAYER_SHAPES.md` records padding 1 for every 3x3 convolution
  and 0 for every 1x1 convolution and GEMM, and step 1b established that
  padding is fully determined by `(type, kernel)` across the whole corpus. The
  formula returns the recorded value in every case. A04's 1x1 convolutions get
  `pad = 0` correctly, though by the coincidence of `kernel = 1` rather than by
  checking anything.
- **Severity if the precondition changes: silent wrong trace**, and harder to
  notice than L1 because the addresses stay in range - only the input pixel
  mapping shifts.
- **Fix sketch (as directed):** enforce `kernel in {1, 3}` at the same bridge
  guard and emit an explicit `PAD` field into the problem dict so the value
  travels with the layer instead of being re-derived. Longer term, record the
  real padding in the capture metadata (`capture_traces.py` in the bench-trace
  repo) so the assumption becomes checkable rather than assumed; note
  `LAYER_SHAPES.md` already flags that padding/dilation/groups for A02-B09 were
  module-derived and never re-verified against the capture metadata, so this fix
  closes that gap too.

### L4. Ticks are an ordinal, not a time

*Caveat (section 5.5):* the tick is a dense counter over non-silent lines, so
the strictly-ascending rule of the stream format can never be violated by loas
by construction. The flip side is that ticks carry no timing information at
all - the timestep axis is already collapsed by the any-fire test.

- **Affects current generation? No - observation only.** The behavior is
  correct; the risk is a downstream consumer misreading a tick as a cycle or a
  timestep.
- **Severity: cosmetic for generation, misinterpretation risk downstream.**
- **Fix sketch:** none needed in code. Worth one sentence in the format
  documentation stating that a v2 tick is MAC order, not time.

### L5. `mac_cycles` is a degenerate maximum for loas

*Caveat (section 5.6):* the assembly step takes the maximum `mac_cycles` across
a tile group's cores. For loas every core in a group walks the identical
`(tap, channel)` lines and differs only in its output-channel run, so all cores
report the same value and the maximum is degenerate.

- **Affects current generation? No - observation only.** The field is safe,
  just uninformative for this arch; it is not a per-core quantity in the output.
- **Severity: cosmetic.**
- **Fix sketch:** none. Relevant only when comparing against an arch whose
  cores genuinely diverge (gustavsnn), where the maximum does real work.

### L6. The only output framing check is a bare `assert`

*Caveat (section 5.9):* the unpacking step ends with an assertion that the
consumed byte count equals the file size, and nothing else validates that the
binary's output matches the expected tile and sample counts. A bare `assert`
is removed under `python -O`.

- **Affects current generation? No.** The campaign does not run with `-O`.
- **Severity if the precondition changes: silent truncation.** Under `-O` a
  framing mismatch would pass unnoticed and produce a short trace.
- **Fix sketch:** replace with an explicit raise, and add a count check that
  the number of `(tile, sample)` records read equals
  `len(tiles) x len(samples)`.

### L7. The stream writer trusts its caller for the machine width

*Caveat (section 5.10):* the header writer validates that the spatial factors'
product equals the declared core count, but in the campaign path both come from
the same source, so the check cannot catch a schedule/machine mismatch - only
an inconsistently computed product. The bound check on core ids is the one that
would actually catch a wrong width.

- **Affects current generation? No - observation only.** Both values are
  derived from the solved schedule, so they agree by construction.
- **Severity: loud failure if ever violated** (the core-id bound check raises).
- **Fix sketch:** none required. If tightened, compare the declared width
  against the architecture's node and PE counts rather than against the
  schedule that produced it.

### L8. `HANDOFF.md`'s T21 dead-reference list is stale

*Caveat (section 5.7):* the T21 list records dead Python references at
`LoASGen.h:7-9` and `:11-13`; none of those strings exist in the current file,
which was rewritten by commit `fc24ea5`. T21's `ProsperityGen.h:154-156` entry
is also stale: that range is live pattern-bit emission code now, with no
`event_to_address`/`divmod` narration left.

- **Affects current generation? No - stale documentation, not code.**
- **Severity: cosmetic, but it wastes a dispatch.** Two of T21's entries are
  already dead, so the row as written would send an implementer looking for
  text that is not there.
- **Fix sketch:** regenerate the T21 list against the current tree before
  working it, rather than trusting its line numbers.

### L9. Record volume, not runtime, is the scaling risk

*Caveat (section 5.8):* B09/`loas_vgg16` L10 produced 528,896 records for
**one** sample in 2.6 s at 0.32 GB, giving a 14.8 MB stream. Cost scales as
`tiles x surviving lines`, so a layer with large input-channel count and many
pixels grows the record count fast while CPU time stays modest.

- **Affects current generation? No - a sizing input, not a defect.**
- **Severity: capacity planning.** The number to extrapolate from is the
  per-sample stream size, not the runtime.
- **Fix sketch:** none. Feeds the shard-weighting work, which must be weighted
  per (arch, layer) and driven by **record count** rather than tile count. On
  layers measured so far GustavSNN's C01 layers are heaviest at about 105
  million records per sample, SpinalFlow's second at about 52.5 million, and
  prosperity's heaviest third at about 3.9 million despite its larger tile
  count - but see P3: prosperity's 3.9 million is a floor and the ranking is
  pending re-measurement.

### L10. Blocking, not sparsity, decides the footprint

*Caveat (section 2.1):*
sparsity sets the **fetch** count but the blocking sets the **line** count, and
they come apart immediately. Measured on A08's classifier, sample 0, core 0:
235 of 512 lines touched at `cin_block = 1` (46%, sparsity fully visible), but
64 of 64 at `cin_block = 8` and 16 of 16 at `cin_block = 32` - 100% both times.
The trace has 3.3x fewer fetches than a dense layer while the footprint is
identical.

- **Affects current generation? No.** The trace stores logical coordinates, not
  addresses, precisely so the layout and blocking remain swept parameters; the
  same records answer differently under each blocking. Generation is unaffected.
- **Severity: a study-design question, not a defect.** If the headline metric
  is footprint rather than fetch count, the blocking choice decides whether
  loas sparsity is visible at all.
- **Fix sketch:** nothing to fix in the generator. Worth settling which metric
  the study reports before the remaining four walkthroughs, since the same
  sensitivity will recur for ptb, spinalflow and prosperity.

---

## ptb

Source: `walkthroughs/ptb.md` section 4, caveats B1-B6. **None affect
generation of any of the 8 benchmarks' layers.** All 151 PTB pairs are
feasible: PTB bars output pixels from residency, so its partial-sum footprint
is `2 x 1 x 1 x COUT_spatial x T` bytes, taking six values over the 151 pairs -
`{16, 32, 40, 80, 128, 256}` B against a 1,024 B budget. The minimum is
B09/`loas_vgg16`'s classifier (`COUT = 10` gives `COUT_spatial = 2` at
`T = 4`); the maximum is the A08 layers at `T = 32`. No layer is within a
factor of four of the limit.

The structural reason the list is short: **PTB's weight-address trace is
record-for-record identical to LoAS's** for the same layer, schedule and sample
(verified by direct comparison on A08's classifier - the same 1,175 records,
ticks and channel runs). The serialized frames are not byte-identical, since
the differing cycle count travels in the frame header. Its two-pass algorithm's second pass feeds
only the cycle count, so everything PTB-specific below concerns that number
rather than the trace.

### B1. Only 4 of the 8 array columns are ever used

*Caveat (ptb section 2.3):* column usage is `ceil(timesteps / 8)` capped at 8.
A08 at 32 timesteps spans 4 columns; the `T = 4` workloads span 1. No campaign
layer uses more than half the array's temporal width.

- **Affects generation? No.** Column count enters only the compute-cost
  formula; fetches, their order and their ticks come from the first pass alone.
- **Severity: efficiency and modeling fidelity, never correctness.** The cycle
  numbers truthfully describe an array at half temporal occupancy on these
  workloads.
- **Fix sketch:** nothing to fix. Full temporal occupancy needs a 64-timestep
  capture, not a code change.

### B2. Timestep counts that are not multiples of 8 give partial windows

*Caveat (ptb section 2.2, 2.3):* C01 runs at 10 and 16 timesteps, five
workloads at 4. At 10 the last column holds 2 of its 8 timesteps; at 4 it holds
4.

- **Affects generation? No, and the partial case is handled explicitly.** The
  last-column term is `timesteps - 8 x (columns - 1)`, the column's true
  occupancy, so a partial window is costed at its real size - no rounding up,
  no zero-padding of the timestep axis, no truncated work. Verified on the C01
  head at 10 timesteps: last column 2, cycle count 103, matching an independent
  recomputation. At 16 the division is exact.
- **Severity: none for correctness.**
- **Fix sketch:** none needed.

### B3. The cycle formula assumes the resident window never exceeds 64 timesteps

*Caveat (ptb section 2.3, derived):* the column count is capped at 8 but the
last-column term is not, so above 64 resident timesteps that term exceeds the
8-timestep column width (at 72 it computes 16), describing a column holding
twice the time it can hold.

- **Affects generation? No.** The mapspace caps resident timesteps at 64 -
  exactly `TW_SIZE x PE_COLS_MAX`, the array's own temporal reach - so a tile's
  window cannot exceed it, and the deepest capture is 32.
- **Severity if the precondition changes: silently wrong cycle counts**, not
  wrong traces. A deeper capture would still be split along time by the cap, so
  reaching the bad range requires raising the cap itself.
- **Fix sketch:** assert the window is at most `TW_SIZE x PE_COLS_MAX` so
  raising the cap fails loudly. The behavioural facts, for whoever resolves the
  mapspace's open question about this value: the window must be at most
  `TW_SIZE x PE_COLS_MAX = 64` for the last-column term to stay within a
  column, and a 32-tick window would strand four of the eight columns by
  construction while changing nothing for the current captures.

### B4. The second pass's group count depends on enumeration order

*Caveat (ptb section 1.3):* the merge walk is greedy and left-to-right over
adjacent pairs in the fixed kernel-row, kernel-column, input-channel order, so
which lines are neighbours - and therefore mergeable - is a property of the
enumeration rather than of the spike pattern. Greedy pairing is also not
optimal; an absorbed line is never reconsidered.

- **Affects generation? No.** The group count feeds only the cycle number.
- **Severity: modeling fidelity, not a defect.** The published architecture
  pairs physically adjacent rows, so order dependence is faithful to the
  hardware - but the count should not be read as the best achievable grouping
  for a given spike pattern.
- **Fix sketch:** none. Worth one sentence wherever the cycle model is
  documented so the number is not mistaken for an optimum.

### B5. An access-bound tile hides its group count

*Caveat (ptb section 2.4):* the cycle count is the maximum of the access and
compute costs, so an access-bound tile discards the group count, which cannot
then be recovered from the output. B09/`loas_vgg16` `features_34` is one: 1,033
fetches and 1,033 cycles.

- **Affects generation? No - an observability limit.**
- **Severity: cosmetic, with an analysis trap.** Measuring PTB's compression
  benefit from cycle counts alone silently sees nothing on access-bound tiles,
  and both regimes occur in this campaign: A08's classifier is compute-bound
  (261 cycles for 235 fetches), the 3x3 layer at 4 timesteps is access-bound.
- **Fix sketch:** emit the group count as its own field if the compression
  effect is to be reported; inference from cycles works only while a tile is
  compute-bound.

### B6. Shared caveats that apply unchanged

Properties of code PTB shares with LoAS, not rediscoveries - the verdicts carry
over because the code is the same. `ptb/native_bridge.py`'s task packing is
byte-for-byte identical to loas's (verified by diff), and `PTBGen.h` duplicates
the same padding formula with no stride term.

- **L1 stride absent from the native path** - does not affect generation; the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`** - does not affect
  generation; the campaign path runs the gate. Latent for other callers.
- **L3 padding inferred from kernel size** - does not affect generation; all
  157 captured layers are same-padding.
- **L6 bare assert as the only framing check** and **L7 the stream writer
  trusts its caller for machine width** - shared code, shared verdicts, neither
  affects generation.
- **L10 blocking rather than sparsity decides the footprint** - applies
  verbatim and with the same numbers, since the address trace is identical.

## spinalflow

Source: `walkthroughs/spinalflow.md` section 4, caveats S1-S5. **None affect
generation of any of the 8 benchmarks' layers.** All 151 SpinalFlow pairs are
feasible: output pixels are barred from residency, so the partial-sum footprint
is `2 x COUT_spatial x T` bytes, taking six values over the 151 pairs -
`{16, 32, 40, 80, 128, 256}` B against a 1,024 B budget. `COUT_spatial` is 4
only when the output-channel count is divisible by 4, so `T` alone does not set
the footprint: the minimum 16 B is B09/`loas_vgg16`'s classifier at `T = 4`,
and A08's own classifier is 128 B rather than 256.

Unlike PTB, SpinalFlow's address stream **genuinely differs** from LoAS's.
LoAS and PTB fetch a weight line once if it ever fires; SpinalFlow fetches it
once per timestep at which it fires, so its trace length is the total spike
count rather than the count of distinct spiking lines. On A08's classifier,
sample 0: 5,504 fetches against 235, a factor of 23.4. Everything below follows
from that.

### S1. Tile count is the product of output pixels and output-channel slabs

*Caveat (spinalflow sections 1.2, 2.3):* output pixels are barred from
residency and channel slabs are PE-width, so tile count grows as
`pixels x slabs`. Both C01 `block2_0_0` layers reach 131,072 tiles - 4,096
pixels x 32 slabs, confirmed from the solved tile list. The timestep count is
not a factor, since all timesteps are resident inside each tile.

- **Affects generation? No - a cost, not a defect.** Tiles are correctly formed
  and the output is right. For one sample of the worst layer: 755 million trace
  position reads (arithmetic, `131,072 x 5,760`), about 52.5 million records and
  1.47 GB of stream (computed from the true per-pixel window counts over all
  4,096 pixels, mean 400.2 records per tile), and roughly 4 minutes
  (extrapolated from timed 64- and 256-tile subsets, which cover the native scan
  and unpack only). A 256-tile subset mean of 384 is border-biased and is not a
  safe estimator: a corner pixel is 49 records against an interior pixel's 380.
- **Severity: capacity and scheduling.** At 500 samples this layer dominates
  any flat per-case budget, which is what broke the earlier pilot's
  2,000-case / 90-minute shard assumption.
- **Fix sketch:** none in the generator. Shard weighting must be per
  (arch, layer) and driven by **record count** rather than tile count, with
  dedicated shards and their own time and memory limits for the heavy C01
  layers. On records they are **second** among layers measured so far - 52.5
  million, behind GustavSNN's C01 layers at about 105 million, which fetch once
  per spike as these do but across twice as many output-channel slabs. Ahead of
  Prosperity's heaviest at about 3.9 million, which has 4.5x the tiles at 6.6
  records each - but see P3: that 3.9 million is a floor, since prosperity's 47
  3x3 layers are uncounted, so the ranking is pending re-measurement.

### S2. 97% of the heavy layer's trace scanning is repeated work

*Caveat (spinalflow section 2.3):* the 32 output-channel slabs of one pixel each
re-scan the identical spike window and find the identical events, differing
only in the channel range stamped onto each record.

- **Affects generation? No - the output is correct**, just produced more slowly
  than necessary.
- **Severity: efficiency only**, about 32x the necessary position reads on the
  heavy layers and proportionally less where the slab count is smaller.
- **Fix sketch:** scan a pixel's window once and emit the per-slab record
  variants from that pass; output would be byte-identical. It would not reduce
  the record count or the memory, which are inherent to the dataflow.

### S3. Memory is driven by record count, which is inherent

*Caveat (spinalflow section 2.3):* records are materialized as Python objects
before streaming, so a 50-million-record layer holds gigabytes of live objects
however fast the native scan is. This is the mechanism behind the earlier
pilot's roughly 15 GB on one sample.

- **Affects generation? Not correctness, but it is the binding practical limit
  on the heavy layers** - the one caveat in this file that can actually stop a
  run.
- **Severity: loud failure** (an out-of-memory kill), not silent corruption.
  A job killed by the kernel out-of-memory killer can take its whole process
  scope with it unless started in its own scope.
- **Fix sketch:** stream per tile instead of accumulating the whole layer. The
  record assembly already groups by tile, so each completed tile frame could be
  handed to the writer and released, changing peak memory from layer-sized to
  tile-sized without changing the output.

### S4. Ticks carry ordering but not timing, despite the time-major walk

*Caveat (spinalflow section 1.4):* ticks are a dense event counter. The walk is
time-major so tick order follows timestep order, but a tick is not a timestep
and the timestep is not recorded.

- **Affects generation? No - observation only.**
- **Severity: misinterpretation risk.** A consumer cannot recover which
  timestep an event belongs to: the record carries kernel position, channel and
  channel run, not time, and the boundaries between timesteps are invisible in
  the tick sequence.
- **Fix sketch:** none for the campaign. Timestep attribution would have to be
  an added record field; it cannot be derived after the fact.

### S5. Shared caveats that apply unchanged

Properties of code SpinalFlow shares with LoAS. Task packing is byte-for-byte
identical to loas's (verified by diff), and `SpinalFlowGen.h` duplicates the
same padding formula with no stride term.

- **L1 stride absent from the native path** - does not affect generation; the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`** - does not affect
  generation; the campaign path runs the gate. Worth noting that SpinalFlow's
  tiles **do** split the pixel dimensions, so the explicit-offset path is
  exercised on every multi-pixel layer and the gate's `missing_pixel_offset`
  check is doing real work here rather than guarding a case that never arises.
- **L3 padding inferred from kernel size** - does not affect generation; all
  157 captured layers are same-padding.
- **L6 bare assert as the only framing check** and **L7 the stream writer
  trusts its caller for machine width** - shared code, shared verdicts, neither
  affects generation.
- **L10 blocking rather than sparsity decides the footprint** - applies, but
  this is the arch where it bites least: because the same line recurs many
  times per tile, its reuse is temporal rather than purely spatial, so capacity
  and blocking sweeps have real room to move its numbers, unlike LoAS where
  each line appears once per tile.

## prosperity

Source: `walkthroughs/prosperity.md` section 4, caveats R1-R5. P1 and P2 at the
top of this file belong to this arch; both are settled, and the walkthrough
demonstrates rather than decides them.

Under **config A** - the mapspace on disk, kernel capped and resident - 145 of
prosperity's 151 schedulable layers generate and the 6 that do not are
partial-sum infeasibilities. Config labels are defined in
`prosperity_infeasibility.md` section 0 and used the same way here, in
`walkthroughs/prosperity.md` and in the swap plan: **A** current, **B**
kernel barred, **K** four-wide pixel block.

Two findings from the walkthrough that are not in P1 or P2:

- **The compression is inert on the 98 one-by-one layers.** A 1x1 layer gives
  one bit per row, and a one-bit row has no pattern to compress, so after the
  first firing row in a tile every later one finds an exact prefix and fetches
  nothing. The fetch rule degenerates to one fetch per firing input channel -
  numerically LoAS's rule. Measured on A08's classifier: 1,175 records, the same
  count as LoAS, with every `(input channel, output slab)` pair appearing
  exactly once and the channels being exactly the 235 that fire. The 47 3x3
  layers are unaffected.
- **A large tile count does not mean a high cost.** Prosperity's heaviest
  generating layer, A07's `intermediate_dense`, has 589,824 tiles but only about
  3.9 million records - 6.6 per tile. SpinalFlow's C01 layers have 131,072 tiles
  and about 52.5 million records, a mean of 400.2 per tile, and GustavSNN's C01
  layers have 2,097,152 tiles - the campaign's largest - and about 105 million
  records. So the three archs rank in a different order by tiles than by
  records, which is why tile count is not a usable cross-architecture cost proxy
  and shard weights should come from records. The record ranking is **pending
  re-measurement**: see P3, since prosperity's 47 3x3 layers now generate and
  their records are uncounted, making its 3.9 million a floor.

### R1. The compression is inert on the 98 one-by-one layers

*Caveat (prosperity section 1.3):* a 1x1 layer gives one bit per row and a
one-bit row has nothing to compress, so the fetch rule collapses to LoAS's. The
47 3x3 layers are unaffected and show about **2.07x** reuse (18,768 raw spike
bits to 9,084 fetches over 128 tiles of one layer). Under the current mapspace
this caveat covers the 98 1x1 and GEMM layers only.

- **Affects generation? No - the traces are correct.** Every fetch that should
  happen does, none is duplicated. What is lost is the architecture's
  distinguishing behaviour.
- **Severity: a study-validity question, not a correctness one.** On those 98
  layers Prosperity's fetch counts equal LoAS's by construction, so a result
  reading "Prosperity performs like LoAS" would be describing kernel width
  rather than architecture.
- **Fix sketch:** none. This is a property of 1x1 kernels rather than of any
  configuration - a one-tap row has nothing to compress under any mapspace - so
  reporting should separate the 47 from the 98 rather than averaging them.

### R2. A split kernel is unrepresentable on the wire, and only the gate catches it

*Caveat (prosperity section 2.2):* the task format carries kernel bounds and no
kernel offset, so a one-tap tile is indistinguishable from a whole-window tile.
A solver produces such schedules whenever a mapspace bars the kernel.

- **Affects generation? No under the current mapspace**, where the kernel is
  resident and the gate passes with zero violations on all 145 generating
  layers. The caveat is about what protects that invariant.
- **Severity: loud failure on the campaign path, silent corruption off it.**
  Demonstrated with the kernel barred on B09/`loas_vgg16`
  `layer_10_core_features_34`: 73,728 tiles checked, 245,760 violations
  (`kernel_tile_bound` 147,456 and `kernel_offset` 98,304), against LoAS on the
  same layer, Prosperity on a 1x1 layer, and Prosperity on the same layer with
  the caps restored, all three passing.
- **Fix sketch:** add a kernel-offset field to the wire format if split kernels
  are ever wanted; the gate's refusal currently stands in for it.

### R3. The per-channel expansion multiplies the task payload 16-fold

*Caveat (prosperity sections 1.2, 2.3):* the bridge expands each tile into one
native tile per resident input channel, because a compression prefix is only
valid within a single input channel. At 16 resident channels that is a 16x
multiplication of the packed task: A07's heaviest layer becomes 9,437,184
native tiles, about 453 MB of task payload per sample against about 28 MB
unexpanded.

- **Affects generation? No** - the measured runs completed and the records are
  correct.
- **Severity: capacity.** A per-sample temporary file that scales with the
  heaviest layer, 16x larger than any other architecture's for the same tile
  list.
- **Fix sketch:** send the resident channel range once per tile and loop over
  channels inside the native call, keeping the per-channel prefix histories
  separate there. The expansion exists for prefix correctness, which can be
  maintained within one invocation as well as across sixteen.

### R4. Record order follows processing order, not position order

*Caveat (prosperity section 1.4):* rows are emitted in firing-tap-count order
with a stable tie-break, so records are not ordered by output position or
timestep. In the degenerate one-tap case this reduces to channel-and-position
order, but as a side effect rather than a guarantee.

- **Affects generation? No - observation only.**
- **Severity: misinterpretation risk.** A consumer assuming position-major or
  time-major order would be wrong. The ordering also depends on the kernel
  width, since the popcount sort key does: it differs between the 47 3x3 layers
  and the 98 one-by-one ones.
- **Fix sketch:** none; worth one sentence wherever record order is documented.

### R5. Shared caveats that apply here

Prosperity's task packing **differs** from the other three (12 ints per tile
rather than 11, sending the output-row and output-column bounds and dropping
the channel count), so L2 lands differently.

- **L1 stride absent from the native path** - does not affect generation; the
  loader excludes the 6 stride-2 layers for every arch.
- **L2 the bridge gate lives in `gen_inputs.py`** - and for Prosperity this is
  the caveat that matters most, since the gate is the **only** thing between a
  split-kernel schedule and a silently wrong trace. Does not affect generation
  on the campaign path, which runs the gate. The HO/WO defaulting half does not
  apply here, because Prosperity sends those bounds explicitly; the kernel half
  applies with full force.
- **L3 padding inferred from kernel size** - does not affect generation; all
  157 captured layers are same-padding. Under config A the formula reads the
  resident kernel extent, so a 3x3 tile gets padding 1 and a 1x1 tile gets 0,
  both correct. Under config B a one-tap tile would yield padding 0 for a 3x3
  layer, which is wrong - and is part of why those tiles must not reach the
  generator.
- **L6 bare assert as the only framing check** and **L7 the stream writer
  trusts its caller for machine width** - shared code, shared verdicts, neither
  affects generation.
- **L10 blocking rather than sparsity decides the footprint** - applies as for
  LoAS on the 98 one-by-one layers, where one fetch per firing channel per tile
  leaves no intra-tile reuse to exploit. On the 47 3x3 layers prefix reuse does
  operate (about 2.07x), so the two groups should not be read together.

## gustavsnn

Source: `walkthroughs/gustavsnn.md` section 4, caveats G1-G6. **G1 is a YES -
the only one in this file.** All 151 pairs are feasible: with the output column
capped at 1 and timesteps barred, the partial-sum footprint is
`2 x HO_resident x COUT_spatial` bytes and takes three values over the 151
pairs, `{2, 4, 8}` B against a 1,024 B budget.

### G1. The shipped binary is older than its sources, and generation fails outright

*Caveat (gustavsnn, stated at the top):* `gustavsnn/gustavgen` dates from 11-07
while `gustavsnn/main.cpp` and `GustavGen.h` were modified at 20:29 on 11-10,
and the task wire format changed with them. The stale parser misreads the task;
the mismatch surfaces as `IndexError: list index out of range` in
`weight_trace.py:assemble_layer_traces` when the returned sample index falls
outside the requested set. GustavSNN is the only arch in this state - the other
four have binaries newer than their sources.

- **Affects generation? YES, for every gustavsnn layer, today.** A binary
  rebuilt from current sources works; the shipped one cannot run at all.
- **Severity: loud failure, which is the good case.** The exception precedes any
  output, so nothing silently wrong is written. A layout change that still
  parsed - a reordered field of the same count - would have been silent.
- **Fix sketch:** rebuild before the campaign runs
  (`make -C src/lays/weight_trace_gen/gustavsnn`), and have the generation
  entry point refuse a binary older than its sources. `make build` covers only
  LoAS, so all four other archs are built by hand and can drift this way.

### G2. A wrong positive wave width is undetectable

*Caveat (gustavsnn sections 1.2, 3):* validation rejects a missing,
non-integer or non-positive width on both sides, but cannot reject a wrong
positive one - the native side never learns what the schedule's spatial product
was.

- **Affects generation? No, on the campaign path**, where the only caller
  derives width and tiles from the same artifact.
- **Severity: silently wrong cycle counts and ticks.** The width enters only the
  wave start, so **addresses and their order stay correct** while ticks and
  cycles are wrong - the hardest shape of error to notice, since the trace looks
  well-formed.
- **Fix sketch:** send the node-level spatial factors rather than their product
  and multiply natively, or assert the product against `ho_n x cout_n`, which
  bounds any legitimate width.

### G3. Equal ticks lose lane identity

*Caveat (gustavsnn sections 1.6, 2.2):* concurrency is expressed only by tick
equality, so a group's bursts are known to be simultaneous but not which lane
issued each.

- **Affects generation? No - observation only.**
- **Severity: an analysis limit.** Per-lane behaviour cannot be recovered and
  must not be inferred from within-group ordering.
- **Fix sketch:** none; a lane id would have to be a record field.

### G4. The largest tile counts in the campaign, and subsets do not estimate them

*Caveat (gustavsnn section 2.4):* barring timesteps and capping the output
column at 1 gives 2,097,152 tiles on C01's first layer, 3.6x prosperity's
heaviest and 4x what `schedule_tiles.csv` records for it. The per-tile record
rate also varies 18x across the solved tile order, so a subset mean is unusable.

- **Affects generation? No - a cost, not a defect.** But it sizes the campaign:
  about 105 million records and 2.9 GB per sample on the heaviest layer.
- **Severity: capacity and scheduling.** This arch runs last, so a budget that
  fits the first four can still fail here.
- **Fix sketch:** none in the generator. Shard weights must come from per-layer
  record counts computed exactly - one neighbourhood sum over the capture -
  never from timing a slice.

### G5. Running last is not an ordering guarantee

*Caveat (gustavsnn):* `sweep_config.yaml` lists gustavsnn last. No output
depends on that - each stream carries its own identity block and is written
independently.

- **Affects generation? No.**
- **Severity: none.** Worth stating only because "runs last" could be mistaken
  for a dependency; the real consequence is that its failures surface late,
  which G1 makes concrete.
- **Fix sketch:** none needed.

### G6. Shared caveats that apply here

Task packing differs (12 ints plus a `wave_width` header field), so L2's
output-row/column half does not apply - those bounds are sent explicitly.

- **L1 stride absent** - does not affect generation; the loader excludes the 6
  stride-2 layers for every arch.
- **L2 the gate lives in `gen_inputs.py`** - does not affect generation; the
  campaign path runs it. Its gustavsnn branch also requires all input channels
  resident and one timestep per tile, matching this mapspace.
- **L3 padding inferred from kernel size** - does not affect generation; all
  157 captured layers are same-padding.
- **L5 `mac_cycles` is a maximum across a frame's cores** - **not** degenerate
  here, as for prosperity and unlike LoAS: cores hold different output-row
  blocks and channel slabs.
- **L6 bare assert as the only framing check** - and G1 is what a real framing
  break looks like: the assert is not what caught it.
- **L7 the stream writer trusts its caller for the machine width** - sharper
  here, since machine width and wave width are different per-schedule numbers
  that are easy to confuse (G2).
- **L10 blocking rather than sparsity decides the footprint** - applies, and
  this arch has the most intra-layer reuse of the five, since a line's repeats
  spread across timestep tiles.
