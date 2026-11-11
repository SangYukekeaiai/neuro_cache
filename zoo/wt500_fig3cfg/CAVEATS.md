# Walkthrough caveats: parking lot

Every caveat raised by the step-3 generator walkthroughs, with a verdict on
whether it affects **current campaign generation**. User decision (2026-11-10):
**no caveat fixes now** - none of the parked items affect generation, so they
are deferred to next week. This file is the record so nothing is lost.

One section per arch, appended by that arch's walkthrough row. loas and ptb are
complete; spinalflow, prosperity and gustavsnn follow.

Fields per caveat: the caveat (cited to its walkthrough section), the
generation verdict with its reason, the severity **if the precondition ever
changes**, and a fix sketch for next week.

---

## SETTLED - config decisions, recorded not pending

### P1. Prosperity's barred kernel and its 47 three-by-three layers

`mapspaces/prosperity.yaml` (commit `9b87861`) omits `KH`, `KW` and `WO` from
`node_dim_capacity`, which the node-capacity rule treats as barred from
NodeLevel residency (absent == cap 1). A 3x3 layer therefore receives
`node_bound[KH] = node_bound[KW] = 1`, not 3: the kernel is split and each tile
holds one tap of nine. The bridges carry no kernel-offset field, so a one-tap
tile is indistinguishable from a whole-window tile on the wire.

The bridge gate refuses exactly this case: `gen_inputs.py` raises
`kernel_tile_bound` when a tile's `KH`/`KW` bound differs from the problem's,
so those layers fail **loudly on the campaign path rather than being
mis-reconstructed**. The silent-corruption path exists only for a caller that
reaches the bridge without that gate - see L2 below.

**Decision: user-accepted.** Under this mapspace prosperity is a 1x1/GEMM-only
architecture, and the mapspace comment records it. Prosperity's 151 schedulable
pairs resolve as:

| outcome | pairs |
|---|---:|
| infeasible at solve (psum capacity) | 6 |
| refused by `kernel_tile_bound` | 47 |
| **generated** (1x1 convolutions and GEMMs) | **98** |

The 47 is the 53 class-S2 layers of `layer_dim_coverage.md` minus the 6 that
never reach the gate. The prosperity walkthrough demonstrates this outcome; it
does not decide it.

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
than 134, and of those only 98 generate (the other 47 stop at the bridge gate).
Gustavsnn's mapspace changes carry the same risk.

**Action:** a refresh row the moment prosperity and gustavsnn re-solve, covering
both the coverage matrix and the tile-count and shard-weighting figures that
depend on it. Until then, treat `layer_dim_coverage.md`'s prosperity and
gustavsnn rows as describing the earlier solve, and its loas, ptb and
spinalflow rows as current - those three mapspaces are unchanged.

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
  per (arch, layer) by tile count - see `layer_dim_coverage.md`, where the
  campaign's real ceiling is prosperity on A07's GEMMs at 1,179,648
  tiles/sample, roughly 9x the SpinalFlow case the old budget was sized on.

### L10. Blocking, not sparsity, decides the footprint

*Caveat (section 2.1, raised by the logic rework rather than the code read):*
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
is `2 x 1 x 1 x COUT_spatial x T` bytes - 32 B at `T = 4` up to 256 B at
`T = 32`, against a 1,024 B budget, with no layer near the limit.

The structural reason the list is short: **PTB's weight-address trace is
identical to LoAS's** for the same layer, schedule and sample (verified by
direct record-for-record comparison on A08's classifier - the same 1,175
records, ticks and channel runs). Its two-pass algorithm's second pass feeds
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
  raising the cap fails loudly. This also settles the mapspace's own review
  flag: 64 is correct because it is the array's temporal reach; 32 would strand
  4 of 8 columns by construction while changing nothing for the current
  captures.

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

Pending its walkthrough row.

## prosperity

Pending its walkthrough row. P1 and P2 at the top belong to this arch; both are
settled, and the walkthrough demonstrates rather than decides them.

## gustavsnn

Pending its walkthrough row.
