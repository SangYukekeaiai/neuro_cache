# Plan: swap the CIN and KH/KW roles in the Prosperity weight-trace generator

Status: **draft, awaiting review. No code changed.**

**Configuration note, which the whole plan depends on.**
`mapspaces/prosperity.yaml` as it stands on disk caps `KH: 4` and `KW: 4`, so a
3x3 kernel is wholly resident, the bridge gate passes with zero violations, and
prosperity generates 145 of its 151 schedulable layers. This document tags its
measurements:

- **config A** - the current file: kernel capped and resident.
- **config B** - kernel dimensions absent, so barred: each tap becomes its own
  tile.

Both dispatched outcomes - the 47 kernel refusals, and the degenerate
compression on 3x3 layers - are properties of **config B** and do not occur
under config A. Section 5.1 records that this was settled by a mapspace change
rather than by the swap. What remains genuinely open is section 5.2, and it is
not the question the dispatch assumed.

Goal as dispatched: inside the Prosperity weight-trace-gen path, make **CIN** the
in-tile pattern dimension that the ProSparsity prefix machinery compresses over,
and make **KH/KW** the external per-tile dimension carried as explicit kernel
offsets. Intended outcomes: the 47 `kernel_tile_bound` rejections disappear, and
the compression stops being degenerate.

**Read section 5 first if you are deciding whether to do this.** Both intended
outcomes are already achievable by restoring two capped dimensions in the
mapspace, with no code change at all, and that alternative is measured in
section 5.1. The rest of this document plans the swap as specified, so the
comparison is between two costed options rather than between a plan and a
guess.

Everything in sections 1-4 was read or measured on this host against the
current tree and the finalized configs.

---

## 1. Current semantics (the contract the redesign is checked against)

### 1.1 What a row and a bit are today

From `src/lays/weight_trace_gen/prosperity/ProsperityGen.h:84-116`:

- A **row** is one `(ho, wo, t)` position inside the tile. The row count is
  `m = ho_n * wo_n * t_n`, indexed row-major with `ho` outer, `wo` middle and
  `t` inner: `row = (ho_local * wo_n + wo_local) * t_n + t_local`.
- A **bit** within a row is one **kernel position**. The bit width is
  `k = kh_n * kw_n` and the bit index is `kh * kw_n + kw`, `kh` outer.
- A bit is set when the input spikes at that kernel tap for this row's output
  position and timestep: `shape.index(t, sample_idx, tile.cin, hin, win)` is
  non-zero, with `hin = ho + kh - pad_h`, `win = wo + kw - pad_w` and
  `pad_h = (kh_n - 1) / 2`. Out-of-range taps are padding and are skipped, so
  their bits stay 0.
- Rows are packed into a `uint64_t`, so `k <= 64` is assumed.
- **One input channel per invocation.** `TileSpec` carries a scalar
  `int32_t cin` (`:51`), not a range.

`docs/weight_trace_gen_archs.md:89-100` documents exactly this: "Each
`(ho, wo, t)` in the tile becomes a **row**: a bitmask of which kernel positions
see a spike, with `bit = kh*3 + kw`." The worked example at `:117-146` is a
`HO=2, WO=2, T=1` tile whose four rows carry kernel-position bitmasks, reducing
12 spike bits to 8 fetches.

### 1.2 The prefix walk

`ProsperityGen.h:118-167`:

1. Stable-sort rows by ascending popcount, ties keeping original row index.
2. Walk in that order. For each row, scan **backward** over already-processed
   rows and take the first whose bits are a subset: `(processed & ~bits) == 0`.
   Because the processed list is itself in ascending `(popcount, index)` order,
   the first backward hit is the most recently processed subset.
3. `pattern = bits XOR prefix_bits`, or `bits` unchanged if no subset exists.
4. Emit one address per set bit of `pattern`, `kh = bit_idx / kw_n`,
   `kw = bit_idx % kw_n`, with `cin` the tile's single channel and the
   output-channel run from the tile.
5. One tick and one cycle per emitted bit; `mac_cycles` equals the record count
   exactly, with no competing compute term.

### 1.3 What the bridge does around it

`src/lays/weight_trace_gen/prosperity/native_bridge.py`:

- `_expand_cin_tiles` (`:49-69`) turns each scheduled tile into **one native
  tile per resident input channel**, setting that tile's channel bound to 1 and
  its offset to the absolute channel index. Its docstring gives the reason: "a
  prefix from another CIN would name different weights", so prefix history must
  not cross channels.
- `_combine_cin_results` (`:72-90`) concatenates the per-channel walks back into
  one tile result, shifting each walk's ticks past the running `mac_cycles` so
  the tile's ticks stay dense and ascending.
- `_pack_task` (`:26-46`) writes **12 ints per tile**, in this order:

  | # | field | source |
  |---:|---|---|
  | 1 | `dram_i` | `tile.dram_i` |
  | 2 | `ho_off` | `tile_offset.get(DIM_HO, 0)` |
  | 3 | `ho_n` | `node_bound[DIM_HO]` |
  | 4 | `wo_off` | `tile_offset.get(DIM_WO, 0)` |
  | 5 | `wo_n` | `node_bound[DIM_WO]` |
  | 6 | `kh_n` | `node_bound[DIM_KH]` |
  | 7 | `kw_n` | `node_bound[DIM_KW]` |
  | 8 | `cin` | `tile_offset.get(DIM_CIN, 0)` |
  | 9 | `t_off` | `tile_offset.get(DIM_T, 0)` |
  | 10 | `t_n` | `node_bound[DIM_T]` |
  | 11 | `cout_off` | `tile_offset.get(DIM_COUT, 0)` |
  | 12 | `cout_n` | `node_bound[DIM_COUT]` |

  **There is no kernel-offset field.** `kh_n`/`kw_n` arrive as bounds and the
  generator always walks taps `0..kh_n-1`, so a tile holding one tap of a 3x3
  kernel is indistinguishable on the wire from a tile holding the whole window.
  `docs/weight_trace_gen_archs.md:262-267` records this as a known unchecked
  assumption: "Neither binary receives a KH or KW offset."

### 1.4 Exactly why one-tap tiles degenerate the prefix machinery

Under **config B**, `KH` and `KW` are omitted from
`mapspaces/prosperity.yaml`, which `constraints/node_capacity.py` treats as
barred (absent == cap 1), so a 3x3 layer gets
`node_bound[KH] = node_bound[KW] = 1` and `k = 1`. (Under config A, the file as
it stands, the same layer gets `k = 9` and none of the following applies to
it - but it still applies to every 1x1 layer, where the kernel is one tap
regardless of the cap.)

With `k = 1` every row's bitmask is one bit, so:

- Rows sort into all popcount-0 rows, then all popcount-1 rows.
- The **first** popcount-1 row finds a popcount-0 row as its prefix - the empty
  set is a subset of everything - so `pattern = {0} XOR {} = {0}`: one fetch.
- Every **later** popcount-1 row finds the previous popcount-1 row, whose single
  bit is a subset of its own single bit, so `pattern = {0} XOR {0} = 0`: **no
  fetch at all**.

So a tile emits exactly one fetch if any of its rows fires, and none otherwise.
The fetch rule collapses to "one fetch per input channel that fires anywhere in
the tile" - LoAS's any-fire rule, reached by a different route. Measured on
A08's classifier, sample 0: 1,175 records, the distinct
`(input channel, output slab)` pairs number 1,175, every pair appears exactly
once, and the channels are exactly the 235 that fire. This is caveat R1 in
`zoo/wt500_fig3cfg/CAVEATS.md`.

A measurement that distinguishes the degenerate case from real compression, on
B09/`loas_vgg16` `layer_10_core_features_34`, sample 0. Scope matters here,
because the two configurations tile that layer differently - config A gives
8,192 tiles at 64 per output-channel slab, config B gives 73,728 at 576 per
slab - so a fixed tile count is not a like-for-like slice. Both rows below are
**two whole output-channel slabs**:

| config | `k` | tiles measured | raw spike bits | fetches | ratio | mechanism |
|---|---:|---:|---:|---:|---:|---|
| B, kernel barred | 1 | 1,152 (2 slabs) | 42,228 | 11,880 | **3.55x** | **degenerate**: any-fire collapse, no prefix reuse |
| A, kernel capped at 4 | 9 | 128 (2 slabs) | 18,768 | 9,084 | **2.07x** | genuine multi-bit prefix reuse |

The ratio is **higher** in the degenerate case, which is why a ratio alone
cannot detect the problem - the bit width can. The 3.55x is one fetch per
firing channel standing in for many spikes; the 2.07x is real pattern reuse,
and it sits in the same range as the 2.52x and 1.49x that
`docs/weight_trace_gen_archs.md:255-256` records for this generator on two A08
layers.

(An unaligned 128-tile slice of config B gives 5,088 bits to 1,352 fetches,
3.76x. The qualitative conclusion is the same, but 128 tiles spans a fifth of
one slab there, so it is not comparable to config A's 128 and is not used
above.)

---

## 2. Target semantics after the swap

### 2.1 Rows and bits, and a verification against the paper model

Under the swap:

- A **bit** becomes one **input channel** from the tile's resident range, bit
  index `cin_local` over `0 .. cin_n-1`, with `cin_n <= 16` from the mapspace.
- A **row** must then range over everything else that varies inside the tile:
  `(ho, wo, t)` **and nothing else**, because the tile holds exactly one kernel
  tap. Row count stays `m = ho_n * wo_n * t_n` and the row-major order can stay
  as it is.
- A bit is set when that channel spikes at this row's output position and
  timestep through the tile's single tap:
  `index(t, sample, cin_off + cin_local, ho + kh_off - pad_h, wo + kw_off - pad_w)`.

**Verification against the documented model: this departs from it.**
`docs/weight_trace_gen_archs.md:92-95` states that a row's bitmask is "which
kernel positions see a spike, with `bit = kh*3 + kw`", and the section's worked
example is built on kernel-position bits. The code agrees. So the swap does not
restore a documented intent - it **changes which dimension ProSparsity
compresses over**, from kernel taps to input channels.

That is not automatically wrong. Reusing a prefix across input channels is
sound at the level this generator models, because a fetch is named by
`(kh, kw, cin, cout range)` and the prefix only has to identify weights already
fetched **within the same tile**. But it is a different architecture claim than
the one the repo currently documents and attributes to the paper, and the
docs would have to change with it. Whether the published design compresses over
channels or over taps is the first open question in section 5.

One consequence to note either way: with bits as channels, a "pattern" groups
channels that fire at the same output position and timestep, so the compression
exploits **cross-channel** coincidence. With bits as taps it exploits
**spatial** coincidence within one channel's receptive field. These are
different physical claims about what repeats in spiking data.

### 2.2 How a one-tap tile resolves input coordinates

The tile gains `kh_off` and `kw_off`. Coordinate resolution becomes:

```
hin = ho + kh_off - pad_h
win = wo + kw_off - pad_w
```

with `pad_h`, `pad_w` derived from the **layer's** kernel extent, not the
tile's. This is the substantive new requirement: today `pad_h = (kh_n - 1) / 2`
uses the tile bound, which is correct only because the tile bound equals the
whole kernel whenever the gate lets a tile through. A one-tap tile has
`kh_n = 1`, which would give `pad_h = 0` and silently shift every coordinate.

So the packed task must carry the **layer's** `KH`/`KW` as well as the tile's
offsets, or carry the padding directly. Carrying padding explicitly is the
better option and matches the fix sketch already recorded for caveat L3 in
`CAVEATS.md`.

Emitted records keep the same five fields, with `kh = kh_off` and `kw = kw_off`
constant for the tile, and `cin = cin_off + bit_idx`.

### 2.3 Tick and record semantics

Unchanged in form: one tick and one cycle per emitted bit, dense from zero
within a tile, `mac_cycles` equal to the record count.

Changed in content, and this is the regression risk: today a tile's ticks are
the concatenation of up to 16 per-channel walks, each numbered from zero and
shifted by the running total. After the swap there is **one** walk per tile, so
the tick sequence is a single run rather than 16 concatenated runs. For a tile
whose channel range is 1 the two coincide; for a wider range they do not, even
when the set of emitted records is identical.

### 2.4 Behaviour on 1x1 and GEMM layers (the regression gate)

For a 1x1 layer `kh_n = kw_n = 1` today, and after the swap the tile still holds
exactly one tap, which is the whole kernel, with `kh_off = kw_off = 0`. The
**required** outcome is byte-identical output to today.

It does not come for free, because of 2.3. Today a 1x1 tile with 16 resident
channels produces 16 concatenated one-bit walks, and the degenerate rule gives
each walk either one record or none, so the tile emits one record per firing
channel with ticks `0, 1, 2, ...` in channel order. After the swap the same tile
is one walk over 16-bit rows, and the prefix machinery over those rows must be
shown to emit the same records in the same order with the same ticks. That is
not obviously true: the popcount sort now orders rows by **how many channels**
fire, which is a different order from the per-channel concatenation.

**This is the single most important thing to verify before anything else**, and
it is a real possibility that byte-identity on 1x1 layers is unachievable
without special-casing. Section 4 makes it phase 0b, before any other trace work rather than a later check.

---

## 3. Change list by file

### 3.1 `prosperity/native_bridge.py`

- Delete `_expand_cin_tiles` and `_combine_cin_results`, and the call sites at
  `:150-151` and the unpack path that uses `origins`.
- Extend `_pack_task` from 12 to 15 ints per tile: add `cin_n`
  (`node_bound[DIM_CIN]`) beside the existing `cin_off`, add `kh_off` and
  `kw_off` (`tile_offset.get(DIM_KH, 0)`, `tile_offset.get(DIM_KW, 0)`), and add
  the layer's padding or kernel extent per 2.2. Field 8 changes meaning from
  "the one channel" to "the first channel of the range".
- The wire format is versionless and both sides are in this repo, so the layout
  change must land in the same commit as the generator change.

### 3.1a `prosperity/main.cpp` - the format's reader

Not a two-file change: `main.cpp` is the **parser** of the layout section 3.1
changes. It documents the 12-int tile record in its header comment and unpacks
the twelve fields one `read_i32` at a time, in order, with no field count and
no version tag on the wire. Every field added in 3.1 needs a matching
`read_i32` here, in the same position, and the header comment needs the same
update.

Because the format is positional and versionless, a packer/parser disagreement
**silently misparses** rather than failing: field 8 becoming a range start
instead of a scalar channel index, for example, shifts every later field by
one and produces plausible garbage. See phase 0.

### 3.2 `prosperity/ProsperityGen.h`

- `TileSpec`: replace scalar `cin` with `cin_off`/`cin_n`; add `kh_off`,
  `kw_off`; add the padding or layer-kernel fields.
- Row build: bit width becomes `k = cin_n`, bit index `cin_local`, and the
  inner loop walks channels at the tile's single tap instead of walking taps for
  one channel. The `uint64_t` mask still suffices since `cin_n <= 16`, but the
  bound is now a mapspace value rather than a kernel size, so an explicit
  `cin_n <= 64` guard is warranted.
- Address emission: `row.kh = tile.kh_off`, `row.kw = tile.kw_off`,
  `row.cin = tile.cin_off + bit_idx`.
- Padding: use the layer-derived padding rather than `(kh_n - 1) / 2`.
- The sort and the prefix walk are unchanged in logic - they operate on
  `row_bits` without knowing what a bit means, which is why this is a
  semantics change rather than an algorithm change.
- Update the header comment block, which currently documents kernel-position
  bits in detail, and `prosperity/__init__.py:14`, which states `k=16 (KH=4, KW=4)`. Note
  `docs/weight_trace_gen_archs.md:312-314` already flags the `k=16` comment in
  this header as misleading; after the swap `k = cin_n <= 16` makes it accurate
  for the first time.

### 3.3 The bridge gate in `zoo/wt500_fig3cfg/gen_inputs.py`

`_bridge_tile_violations` (`:391`) currently applies `kernel_offset` (`:416`)
and `kernel_tile_bound` (`:419`) to **every** arch, in the shared loop at
`:414`, unconditionally, before the per-arch
branch. These must become arch-aware:

- **Prosperity**: accept a split kernel. A non-zero kernel offset becomes legal
  and a `KH`/`KW` bound below the full kernel becomes legal; what must instead
  be checked is that the bound is exactly 1 (one tap per tile, since the
  generator emits a single `(kh_off, kw_off)` per tile) and that the resident
  channel count is within the 64-bit mask.
- **Every other arch**: keep the refusal exactly as it is. LoAS, PTB and
  SpinalFlow still have no kernel-offset field and still reconstruct the full
  window, so relaxing the check for them would reintroduce precisely the silent
  corruption that caveat L2 warns about.

This is the highest-risk edit in the plan: it moves a check that currently
protects four architectures into a per-arch form where a mistake silently
affects the other three. It should be a separate, reviewed commit from the
generator change.

### 3.4 Plumbing

`weight_trace.py` and `weight_trace_gen/cli.py` need **no change**:
`reconstruct_samples` dispatches by arch name and passes the tile list through,
and the tile list is unchanged - it is only the bridge's interpretation of it
that changes. The regroup step keys off `(dram_i, noc_i, core_id)`, which the
swap does not touch. Worth confirming that nothing downstream assumes the
per-channel expansion, since the expansion is currently visible only inside the
bridge.

### 3.5 Campaign-doc fallout

- `zoo/wt500_fig3cfg/prosperity_infeasibility.md`: section 3's accounting
  changes from 6 infeasible / 47 refused / 98 generated to **6 / 0 / 145**. The
  psum mechanism, boundary and IIS stay exactly as they are (section 4.3).
- `zoo/wt500_fig3cfg/CAVEATS.md`: R1 is resolved by the change and should be
  rewritten rather than deleted, recording what the degenerate behaviour was and
  that it no longer applies. R2 drops from "53 of 151 produce no trace" to "6 of
  151". L2's prosperity note needs rewriting, because after this change the gate
  no longer refuses split kernels for prosperity and so is no longer the
  backstop it is today.
- `zoo/wt500_fig3cfg/walkthroughs/prosperity.md`: sections 1.2, 1.3, 2.1 and
  2.2 all describe the current semantics and the rejection, and all need
  revising. The rejection demonstration becomes a historical record of a
  behaviour that no longer occurs, so it should be replaced by the new 3x3
  worked example from section 4.2.
- `docs/weight_trace_gen_archs.md`: sections 3 and the all-five-side-by-side
  table at `:460-468` describe kernel-position bits and "resident CIN range"
  tiles. Both change. Per section 2.1 this is a change to a documented paper
  attribution, not just to an implementation note.
- `zoo/wt500_fig3cfg/layer_dim_coverage.md`: its coverage matrix is already
  flagged as pre-finalization (P3 in `CAVEATS.md`); this change makes a second
  reason to refresh it.

---

## 4. Verification per phase

### Phase 0 - packer and parser agree on the wire format

Before any trace is compared, assert the two sides of the format match. The
format carries no field count and no version, so nothing detects a mismatch
today.

1. Add a field count or a magic int to the task header and have `main.cpp`
   reject a value it does not expect. This is the check whose absence the plan
   identifies as its own worst failure mode, and it is three lines.
2. Assert the packed task's byte length equals
   `header + n_tiles x fields x 4 + n_samples x 4` on the Python side, and that
   the parser consumes exactly that many bytes on the native side.
3. Only then proceed to phase 0b.

### Phase 0b - the 1x1 byte-identity gate, before any trace work

Per 2.4 this is the gate, not a later check.

1. Keep the current binary and a built swap binary side by side.
2. For A08's classifier and B09/`loas_vgg16`'s classifier, generate sample 0
   under both and compare the **full ordered record list per tile**, including
   ticks and `mac_cycles`, not just the record set. Today's A08 figures to match:
   160 tiles, 10 frames, 1,175 records, every `(channel, output slab)` pair once,
   235 distinct channels, `mac_cycles` 10 per frame.
3. Extend to all 98 currently-generating layers on one sample before trusting
   the change. A set comparison is not enough: order and ticks must match.
4. **If byte-identity fails**, stop and bring the ordering question back for a
   decision rather than special-casing. A 1x1 tile with 16 resident channels is
   the common case, not an edge case.

### Phase 1 - a hand-derivable 3x3 correctness check

Use the corner-pixel padding case, the same shape as the walkthrough examples.
On B09/`loas_vgg16` `features_34` (3x3, 2x2 output, 4 timesteps), for output
pixel `(0, 0)`:

- 5 of the 9 taps are padding and can never fire; the 4 real taps are
  `(1,1) -> (0,0)`, `(1,2) -> (0,1)`, `(2,1) -> (1,0)`, `(2,2) -> (1,1)`.
- After the swap those 4 taps are 4 **separate tiles** per channel group, each
  with its own `(kh_off, kw_off)`. The 5 padding taps are also tiles, and each
  must emit **zero** records - a tile whose every row is empty.
- The per-tap non-silent channel counts for that pixel are 264, 239, 282 and
  248, summing to 1,033, which is the figure both the LoAS and PTB walkthroughs
  derive by hand for this pixel. **The swap must not change that sum**, because
  it is the count of distinct firing `(tap, channel)` pairs and prefix reuse can
  only reduce fetches below it.
- So the check is two-sided: total fetches for the pixel must be `<= 1033`, the
  five padding tiles must contribute 0, and the `(kh, kw)` values emitted must
  be exactly the four real taps.

A separate check that the padding is right: compare against a run with the
padding passed explicitly versus derived from a tile bound of 1. The second must
be visibly wrong, which confirms the fields in 2.2 are actually being used.

### Phase 2 - the scheduler side is untouched

**Explicitly: this change does not touch the scheduler, the mapspace, or the
psum capacity constraint, so the infeasibility boundary does not move.** The
`psum` row of the A matrix in `scheduler/constants.py` is `COUT, HO, WO, T`;
`KH`, `KW` and `CIN` do not appear in it, so nothing about which dimension is
resident for the generator can change the psum footprint. The 6 infeasible
layers stay infeasible, the boundary stays `T <= 16` at `HO_resident = 8`, and
the IIS stays the 8 constraints recorded in `prosperity_infeasibility.md`.

Verification is cheap and should still be run: re-solve the 9 A08 `T = 32`
convolutions and confirm L1-L6 infeasible and L7-L9 feasible, unchanged.

### Phase 3 - cost of the 47 newly-generating layers

Measured on B09/`loas_vgg16` `features_34`, the 3x3 layer used throughout:

| config | tiles | note |
|---|---:|---|
| finalized today (KH/KW barred) | **73,728** | solves, then refused by the gate |
| after the swap | **73,728** | same tiling; the swap adds offsets, not tiles |
| KH/KW capped at 4 (section 5.1) | **8,192** | 9x fewer; kernel resident |

So the swap generates at the tiling the solver already produces: **9x the tiles
of a kernel-resident schedule**, because each of the 9 taps becomes its own
tile. Per-tile work falls by roughly the same factor, so total fetch work is
comparable; what grows 9x is tile count, and with it frame count, task payload
and per-tile overhead.

For the per-sample estimate, note the record count is bounded by the distinct
firing `(tap, channel, output slab)` triples and is **not** multiplied by the
tiling. The thing to measure before committing is per-tile overhead at 73,728
tiles against 8,192, since the earlier pilot's failure mode was overhead and
memory rather than arithmetic.

One real saving: dropping the per-channel expansion removes the 16x task-payload
multiplication recorded as caveat R3. For A07's heaviest layer that is 453 MB of
task payload down to about 28 MB plus the three new fields, roughly 35 MB.

---

## 5. Open questions, with recommendations

### 5.1 Mapspace change instead of a code change: ADOPTED

**Status: done.** `KH: 4` and `KW: 4` are in `mapspaces/prosperity.yaml` on
disk, so both stated outcomes - the 47 rejections gone and the compression no
longer degenerate on 3x3 layers - hold with no code change. The measurements
below are the evidence that established it.

**Measured on B09/`loas_vgg16` `layer_10_core_features_34` with the kernel
caps in place, sample 0:**

- The solve succeeds, and the tile comes back with `node_bound[KH] = 3`,
  `node_bound[KW] = 3` - the **whole kernel resident**.
- The campaign gate returns `passed=True`, 8,192 tiles checked, **zero
  violations**. The 47 rejections are gone with no gate edit.
- `k = 9`, so rows carry multi-bit patterns and prefix reuse is real: 18,768
  raw spike bits to 9,084 fetches, **2.07x**, in the same range as the 2.52x and
  1.49x this generator already records on two A08 layers.
- **8,192 tiles instead of 73,728** - 9x fewer than either the current config or
  the swap, because the kernel sits inside the tile instead of becoming nine
  separate tiles.
- The psum boundary is untouched for the same reason as phase 2: `KH`/`KW` are
  not in the psum A-matrix row. The 6 infeasible layers are unaffected.

The capacity question this raises has an answer: the weight footprint at
`KH = KW = 3`, `CIN = 16`, `COUT_spatial = 4` is `1 x 3 x 3 x 16 x 4 = 576 B`
against a 32,768 B node weight budget, so kernel residency costs nothing at
this node size.

**Consequence for the swap.** Measured against the configuration on disk the
swap is a **9x tile-count regression** on 3x3 layers - 73,728 tiles against
8,192 - and it keeps the gate's protection of the other three architectures
intact only if section 5.4's edit is skipped.

### 5.2 The taps-versus-channels question is a false binary

**What the vendored reference implementation does.** The upstream Prosperity
simulator is in this tree at
`neuro_cache_bench_trace/upstream/Prosperity/simulator/`, so this does not need
the paper:

- `networks.py:143` sets `eq_input_dim = kernel_size * kernel_size *
  input_channel`: a convolution is lowered to a matrix whose contraction
  dimension is the **flattened kernel-and-channel space**, not one or the other.
- `utils.py:69` builds it as
  `patches.permute(0, 2, 3, 1, 4, 5).reshape(N, -1, kernel_size*kernel_size*C)`,
  ordering that axis **channel-major, tap-minor**: column index is
  `c * k*k + kh * k + kw`.
- `simulator.py:207-215` hands the result to
  `find_product_sparsity(input_act, tile_size_M, tile_size_K)`, which
  compresses over a `tile_size_K`-wide block of **consecutive columns** of that
  axis. The value this repo attributes to the paper's Table III is 16.
- Rows of that matrix are `(output patch, timestep)` pairs - which is what this
  repo's rows already are.

So the published design compresses over **16 consecutive columns of the
flattened `CIN x KH x KW` space**. With `k*k = 9` a 16-wide block spans one
channel's nine taps plus seven taps of the next: it straddles tap and channel
boundaries by construction.

**Consequence.** Neither the current code nor the swap matches that. The code
compresses over taps within one channel; the swap would compress over channels
at one tap. Both are **projections of the same joint axis onto one of its two
factors**, and the reference respects neither factor's boundary. The
taps-versus-channels framing that organizes sections 1, 2 and 5 of this plan is
therefore a false binary, and the swap is **neither a bug fix nor a model
change** - it trades one projection for another.

**Recommendation: do not do the swap as specified.** If the goal is fidelity to
the published design, the change is a different one: flatten `(cin, kh, kw)`
channel-major into a single bit axis, tile it into 16-wide blocks of
consecutive columns, and run the existing prefix machinery over those blocks.
The sort and the subset test need no modification, since they do not know what
a bit means - which is the one piece of the swap's reasoning that carries over
intact. That is a larger change than the swap with a sharper justification. If
the goal was only to stop the degeneracy, section 5.1 already did it.

Sections 1, 2.2, 3 and 4 remain reusable: carrying a kernel offset and dropping
the per-channel expansion are mechanics a flattened-axis implementation needs
too.

### 5.3 If byte-identity on 1x1 layers cannot be met, what then?

**The question.** Per 2.4, today's 1x1 tiles emit 16 concatenated one-bit walks,
while the swap gives one walk over 16-bit rows with a different sort order.
Byte-identity is required but not obviously achievable.

**Recommendation: treat a failure here as a stop, not a special case.** If the
orders differ, the honest options are to accept that prosperity's existing
1x1 traces change (and re-generate everything, invalidating any prosperity
output already produced) or to abandon the swap. Special-casing 1x1 inside the
generator would leave two code paths with different semantics.

### 5.4 The per-arch gate relaxation: MOOT, and should not be made

**The question.** Section 3.3's per-arch gate is the riskiest edit here. An
alternative is to add `kh_off`/`kw_off` to all four task formats and have every
generator honour them, after which the gate's kernel checks could be dropped
uniformly rather than branched.

**Status: moot.** The relaxation exists only to let prosperity's split-kernel
schedules through, and prosperity no longer produces them - the kernel is
resident and the gate passes with zero violations on all 145 generating layers.
This is the plan's own highest-risk edit, moving a check that protects four
architectures into a per-arch form, and it now unblocks nothing, so it should
not be made. If a flattened-axis implementation (5.2) ever needs a kernel
offset, the uniform change is the one to evaluate then - that implementation
would need the offset for correctness rather than to bypass a check.

### 5.5 Who owns the doc fallout, and when?

**The question.** Section 3.5 lists five documents, three of which are
reviewed-pass campaign artifacts.

**Recommendation: one documentation row after the code lands and phases 0-2
pass, not alongside.** Editing these documents twice costs more than editing
them once late, and until phase 0 passes it is not certain the change lands at
all.
