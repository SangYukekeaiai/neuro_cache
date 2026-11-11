# Walkthrough caveats: parking lot

Every caveat raised by the step-3 generator walkthroughs, with a verdict on
whether it affects **current campaign generation**. User decision (2026-11-10):
**no caveat fixes now** - none of the parked items affect generation, so they
are deferred to next week. This file is the record so nothing is lost.

One section per arch, appended by that arch's walkthrough row. loas is
complete; ptb, spinalflow, prosperity and gustavsnn follow.

Fields per caveat: the caveat (cited to its walkthrough section), the
generation verdict with its reason, the severity **if the precondition ever
changes**, and a fix sketch for next week.

---

## PENDING, not parked - decide BEFORE generation

These two are not deferred. They are open questions about the finalized configs
that need an answer before the campaign runs.

### P1. Prosperity `KH: 1` / `KW: 1` vs its 47 three-by-three layers

The finalized `mapspaces/prosperity.yaml` caps `KH: 1` and `KW: 1`. The
node-capacity rule pins a dimension's resident product to the largest
sub-product of its own prime factors that does not exceed the cap, so a 3x3
layer gets `node_bound[KH] = node_bound[KW] = 1`, **not 3**: the kernel is
split, and only one tap of nine lands in each tile.

The bridges have **no kernel-offset field** - the packing helper sends
`node_bound[KH]`/`node_bound[KW]` and nothing else - so a tile holding one tap
is indistinguishable from a tile holding the whole window. The mapspace's own
comment still claims the opposite ("KH/KW are explicit so every native tile
receives the full kernel window"), which is now stale against its own values.

Scale, measured over the 157 captured layers: **47** class-S2 (3x3, stride-1)
layers would be scheduled for prosperity under the finalized mapspace, and
every one of them is affected.

**Important qualifier on the risk.** On the campaign path this fails **loudly,
not silently**: the bridge gate checks `node_bound[KH] != problem["KH"]` and
raises `kernel_tile_bound` for exactly this case, so all 47 would be rejected
rather than mis-reconstructed. The silent-corruption path exists only for a
caller that reaches the bridge without going through that gate (see L2 below).
So the realistic outcome is "prosperity generates nothing for 47 layers",
not "prosperity generates 47 wrong traces" - still a blocker, but a visible one.

**To decide in the prosperity walkthrough demo, before generation:** whether
`KH: 1 / KW: 1` was intended (and the 47 layers are deliberately out of scope),
or whether it should be `KH: 4 / KW: 4` as in the pre-finalization copy, which
gives `node_bound = 3` and the full window.

### P2. `prosperity_infeasibility.md`'s T <= 8 boundary is stale

`prosperity_infeasibility.md` derived the infeasibility boundary under the
prosperity mapspace as it stood then, `HO: 4, WO: 4`. The finalized mapspace is
`HO: 8, WO: 1`, which changes the binding arithmetic:

| | then (`HO 4 / WO 4`) | finalized (`HO 8 / WO 1`) |
|---|---|---|
| psum bytes | `2 x 4 x 4 x 4 x T = 128 T` | `2 x HO_res x 1 x 4 x T` |
| boundary | `T <= 8` | `T <= 16` when `HO_res = 8` |
| infeasible pairs | **17** | **6** |

Under the finalized values only A08/`vgg16_cifar10_loas` **L1-L6** remain
infeasible (2,048 B against the 1,024 B psum budget). The eight C01 layers at
`T = 10` and `T = 16` become **feasible**, and so do A08 **L7-L9**, whose
`ho = 4` gives `HO_res = 4` and exactly 1,024 B - the zero-slack boundary case
again. So "A08 T=32 is still out" is right, but it is 6 of the 9, not all 9.

The mechanism in that document is unchanged and still correct: one binding
constraint, the NodeLevel psum capacity, with `T` forced fully resident and the
other factors pinned by equalities. Only the numeric boundary and the affected
set move.

**Action:** `prosperity_infeasibility.md` needs a correction pass once P1 is
decided, since `KH`/`KW` do not enter the psum term and the two questions are
independent - but there is no point rewriting the numbers twice. Not parked:
its boundary and affected set are wrong on disk right now.

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

Pending its walkthrough row.

## spinalflow

Pending its walkthrough row.

## prosperity

Pending its walkthrough row. P1 and P2 above belong to this arch and are
tracked at the top because they must be decided before generation.

## gustavsnn

Pending its walkthrough row.
