# 2026-07-28 Debug Pipeline Plan

## Goal

`profiling/0723/` and `profiling/0726/` grew into a pile of one-off sweep
and diagnostic scripts whose cache-hit-rate output was only ever checked
end-to-end. This plan archives that pile, promotes the already-working
C++ ports to be the sole implementation of archmodels and cachesim, and
replaces end-to-end trust with a small set of debug scripts that verify
each pipeline stage in isolation on a tiny, hand-checkable input trace.

## Background: what `native_bridge.py` does

Each arch (`loas`, `ptb`, `prosperity`, `spinalflow`, `gustavsnn`) and
`cachesim` has a working C++ port, wired in through a `native_bridge.py`
that follows the same three-step pattern: pack the relevant Python data
into a compact fixed-width binary blob (`struct.pack`, not JSON/pickle),
invoke the compiled binary as a subprocess with that blob on stdin or in
a temp file, then unpack its binary output back into the same Python
objects (`TileWeightTrace`/`LayerWeightTrace` dataclasses, or a plain
hit-rate float) the pure-Python function would have returned. Neither
bridge imports the pure-Python compute modules it replaces -
`cachesim/native_bridge.py` only imports `.config` (`CacheConfig`), and
each arch's `native_bridge.py` only imports shared plumbing
(`parsers.layer`, `NodeTileSpec`, `tracegen`'s dataclasses), so moving
the pure-Python compute files elsewhere doesn't break either bridge's
imports.

## Part 1: Archive ad hoc profiling scripts

Move `profiling/0723/` and `profiling/0726/` into `dump/profiling/`,
using `git mv` for tracked files and a plain move for the untracked ones
(`cache_sweep_persample.py`, its compiled binary, `results_persample/`),
so history is preserved. `src/archmodels/`, `src/cachesim/`,
`src/tracegen.py`, `src/mip_solver/`, and `scripts/solve_schedules.py` /
`scripts/generate_weight_traces.py` stay in place, they're the library
code and pipeline drivers the new debug scripts build on.

## Part 1b: Repackage archmodels & cachesim: promote C++, pack Python

Each module's C++ sources currently live in a nested `native/`
subfolder. Since C++ becomes the sole implementation, they move up one
level, out of `native/`:

- `src/cachesim/native/*` -> `src/cachesim/*`
- `src/archmodels/{arch}/native/*` -> `src/archmodels/{arch}/*` (all 5 archs)

The superseded pure-Python compute files move into a kept reference
folder, not deleted:

- `src/cachesim/{cache.py, layout.py, policy.py, sweep.py}` -> `dump/python_reference/cachesim/`
- `src/archmodels/{arch}/{model.py, reconstruct.py, address.py, cycles.py}` -> `dump/python_reference/archmodels/{arch}/` (x5)

Stay in place: `config.py` (cachesim's `CacheConfig`, imported directly
by `native_bridge.py`), `trace.py`, `native_bridge.py`, `__init__.py`,
`tracegen.py` (schedule solving is Gurobi/Python with no C++ port and
isn't in scope here).

Two path constants need a one-line update once their directories
flatten: `cachesim/native_bridge.py`'s `_NATIVE_BIN` and each arch's
`_BINARY`, both currently pointing at `.../native/<binary>`.

`generate_weight_traces.py`'s Python fallback (`_NATIVE_BRIDGE_MODULES`,
used when an arch has no registered native bridge) becomes a hard
failure: with all 5 archs now backed by a native bridge and the Python
compute path packed away, a missing or broken native binary should raise
loudly, matching how `cachesim/native_bridge.py` already behaves, rather
than silently falling back to a path that's no longer meant to run.

Cachesim's hit-rate replay changes from per-weight-value to per-burst
accounting (see "Concrete worked example" below for the derivation and
why the two give very different numbers): `sample_hit_rate` (still
pure Python, `cachesim/sweep.py`, kept alongside `cache.py`/`layout.py`/
`policy.py` before those move to `dump/python_reference/`) and the
native `cache_replay.cpp`/`cache_sweep.cpp` both need to process one
event's expanded elements at a time, collapse consecutive identical
tags within that event to their first occurrence, and replay the
deduplicated per-event tag sequence rather than every individual
expanded element. This fix lands in both implementations before Stage
1's parity check runs, since that check only means something if both
sides are being held to the same, correct definition of an access.

## Part 1c: Fix the set-index function

`Cache._set_index` (`src/cachesim/cache.py:49-60`, mirrored in native
`cache.h` and `profiling/0726/native/cache_sweep.cpp`) picks which set a
tag maps to. The formula sums the tag's four components (`kh, kw, cin,
cout // line_size`) and takes it mod `num_sets`. Measured directly
against real weight traces: `layer_01_layer1_0_conv1` at 4-way/32KB/32B
line (256 sets) reaches only 70-71 of 256 sets under this formula,
reproduced independently across three archs (prosperity: 71, spinalflow:
71, gustavsnn: 70), so it's a structural property of that layer's shape
(small CIN), not a fluke or an artifact of one arch's addressing.
Deeper/wider layers (`layer_09`, `layer_19`) already reach all 256 sets
under the same formula, so the failure is layer-shape-dependent, not
universal, and every associativity comparison drawn from a small-CIN
layer's results is the one that's actually suspect.

**Adopted fix**: use the flattened mixed-radix `packed` value (the same
value already computed for the cache-line tag itself, one dense int
covering all four dimensions) for set selection instead of the raw
component sum, in both places Part 1b already commits to touching:
`src/cachesim` (`cache.py`'s `_set_index` and native `cache.h`) and
`profiling/0726/native/cache_sweep.cpp`. The native sweep already
computes and uses `packed` this way; this makes it the reviewed,
intentional choice across both implementations rather than something
only one of them does. Radices for the flatten come from each sample's
own observed per-dimension maxima, matching what's already implemented;
this is a deliberately scoped-down pass, not a claim that this is the
best possible index function.

Measured effect of adopting `packed` over `sum` on the same worst-case
layer: 71 -> 240 of 256 sets used, skew (max set load / ideal average)
6-8x -> 2.6-4.8x. A real, measured improvement, not a complete fix.

**Explicitly deferred, not part of this pass**: flattening using the
layer's true declared `KH/KW/CIN/COUT` shape (available in
`workload_dims`) instead of per-sample observed maxima, and any switch
to a different index function entirely (e.g. XOR-folding or
skewed-associativity-style indexing). Literature research on cache
set-index/hashing schemes, especially for DNN accelerator address
patterns, is in progress; revisit this fix once that concludes rather
than guessing at a better formula now. This scope boundary also applies
to the cin x cout line-layout proposal and the cold-miss classification
work described in the separate draft plans
`log/2026-07-28-set-index-and-cin-cout-layout-plan.md` and
`log/2026-07-28-cold-miss-classification-plan.md`: both stay out of
scope here.

**Verification**: not an assertion of perfect uniformity, since the
measurement above already shows the adopted fix doesn't achieve that.
Instead, record both formulas' distinct-sets-used and skew per config as
a documented before/after baseline, so a future hash change has a
concrete number to improve on rather than a vague "it's better now."

**Kept regardless of which index function is in use**: always include a
fully-associative run in every sweep. `num_sets = 1` there, so
`_set_index` always returns 0 and it's immune to this bug by
construction, making it a ceiling that any set-associative config's hit
rate can be checked against, both before and after this fix.

## Part 2: Debug pipeline

### Stage 0: Build a tiny input trace

Dependency: none. Pure numpy, no Gurobi, no native binaries. Only needs
to match the `meta.json` + `<layer>.npy` format `src/archmodels/trace.py`'s
`load_layer_trace` expects.

Script: `debug/00_make_tiny_trace.py` synthesizes the tiny two-layer
trace directory specified in "Concrete worked example" below (`layer_00`
is the one every later stage exercises; `layer_01` exists purely to
supply `layer_00`'s COUT via `build_workload_from_trace`'s `next_cin`
lookup, matching how real multi-layer captures work). Output:
`debug/traces/tiny/meta.json` + `debug/traces/tiny/layer_00.npy` +
`debug/traces/tiny/layer_01.npy`.

```bash
conda run -n base python debug/00_make_tiny_trace.py
```

### Concrete worked example (LoAS)

A fully hand-derived example, worked through `src/archmodels/loas`'s
actual `reconstruct.py`/`address.py` logic and `configs/arch/loas.yaml`
(which forces `KH`/`KW`/`CIN`/`T` fully resident per node visit and caps
`COUT` at a 16-wide spatial pass, with `HO`/`WO` each getting their own
node visit). This is the concrete data every stage's scripts run against
and the expected values their assertions check.

**Trace shape:** `KH=KW=3` (`src/archmodels/trace.py`'s fixed
assumption), `PAD=1` (same-padding), `CIN=1`, `T=2`, `Hin=Win=2` so
`HO=WO=2` (4 output-pixel tiles total). `COUT=4` for `layer_00`, supplied
by a second placeholder layer, `layer_01` (`CIN=4`, same `Hin=Win=2`
shape, content unused since only `layer_00` is reconstructed).

`meta.json`:
```json
{
  "captured_at": "synthetic",
  "arch": "loas",
  "timestep": 2,
  "batch_size": 1,
  "dataset": "debug-tiny",
  "layers": {
    "layer_00": [2, 1, 1, 2, 2],
    "layer_01": [2, 1, 4, 2, 2]
  }
}
```

`layer_00.npy`, shape `[T=2, B=1, Cin=1, Hin=2, Win=2]`, as two 2x2
grids (`trace[t, 0, 0, h, w]`), chosen so exactly one of the 4 input
positions never spikes across `T`, to exercise LoAS's silent-neuron
compression, not just the always-non-silent case:

```
t=0:  h\w  0  1        t=1:  h\w  0  1
       0   1  0               0   0  0
       1   0  1               1   1  0
```

`layer_01.npy`: any array of shape `[2, 1, 4, 2, 2]` (e.g. all zeros).
Its values are never read; only its declared `CIN=4` in `meta.json`
matters, since `layer_00` is never the last layer in this two-layer
trace.

**Expected reconstruction, per output-pixel tile** (`node_bound =
{KH:3, KW:3, CIN:1, T:2, COUT:4}`, `tile_offset = {HO:ho, WO:wo,
COUT: 0}` for each of the 4 tiles; `weight_addresses` is
`(kh, kw, cin, cout_start=0, cout_end=4)` per non-silent line, in
`(kh asc, kw asc)` order). Every tile has exactly 3 non-silent lines and
1 silent one, since this 2x2 image's only silent position, `(h=0,w=1)`,
falls inside every output pixel's 3x3 receptive field:

| tile (ho,wo) | non-silent (kh,kw) -> weight_addresses | silent (kh,kw), dropped |
|---|---|---|
| (0,0) | (1,1),(2,1),(2,2) -> `(1,1,0,0,4)`,`(2,1,0,0,4)`,`(2,2,0,0,4)` | (1,2) |
| (0,1) | (1,0),(2,0),(2,1) -> `(1,0,0,0,4)`,`(2,0,0,0,4)`,`(2,1,0,0,4)` | (1,1) |
| (1,0) | (0,1),(1,1),(1,2) -> `(0,1,0,0,4)`,`(1,1,0,0,4)`,`(1,2,0,0,4)` | (0,2) |
| (1,1) | (0,0),(1,0),(1,1) -> `(0,0,0,0,4)`,`(1,0,0,0,4)`,`(1,1,0,0,4)` | (0,1) |

`debug/01_inspect_weight_trace.py` checks the generated
`sample_00000.json.gz` against this table exactly (4 tiles, 3 lines
each, these exact tuples, in this order). `debug/04_diff_reconstruction.py`
(Stage 1) diffs the packed-Python and native-C++ paths against each
other; either path disagreeing with this table is a bug worth stopping
on, not just a Python/C++ mismatch.

**Expected elements and hit rate** (Stage 3), using a dedicated tiny
cache config (not `configs/cache/cache_config.yaml`, which is sized for
the real sweep):

```yaml
cache:
  cache_size_bytes: 16   # capacity_lines = 16/4 = 4 lines (4-way fully-associative)
  line_size_bytes: 4     # absorbs all 4 COUT values into 1 line
  cache_type: fully_associative
  inner_dim: cout
  # policy: lru (default)
```

Concatenating all 4 tiles' `weight_addresses` in raster tile order
`(0,0),(0,1),(1,0),(1,1)` gives 12 events (bursts). Hit rate is defined
**per burst, not per individual weight value**: a burst is one physical
memory transaction (`address.py`'s own docstring calls it "a single
contiguous line of weight data"), so it contributes exactly one hit/miss
decision, however many weight values it logically covers.
`expand_events`/`element_tags` still expand a burst into its underlying
`Element`s to compute cache-line tags (`cout=0..3` here), but before
replay those per-event tags are deduplicated down to the DISTINCT
consecutive tags that one burst touches: since `line_size_bytes=4`
absorbs the whole COUT range into one line, all 4 elements of every
event collapse to the identical tag `(kh, kw, cin, 0)`, so each event
contributes exactly one deduplicated access, not four. (A burst wide
enough to span multiple lines would still contribute one access per
distinct line it touches; that case just never arises here.) Replaying
the resulting 12 per-burst tags through a 4-way fully-associative LRU
cache (worked by hand, front = MRU):

| # | tag | result | cache after (MRU -> LRU) |
|---|---|---|---|
| 1 | (1,1,0,0) | MISS | [A] |
| 2 | (2,1,0,0) | MISS | [B,A] |
| 3 | (2,2,0,0) | MISS | [C,B,A] |
| 4 | (1,0,0,0) | MISS | [D,C,B,A] |
| 5 | (2,0,0,0) | MISS (evict A) | [E,D,C,B] |
| 6 | (2,1,0,0) | HIT | [B,E,D,C] |
| 7 | (0,1,0,0) | MISS (evict C) | [F,B,E,D] |
| 8 | (1,1,0,0) | MISS (evict D) | [A,F,B,E] |
| 9 | (1,2,0,0) | MISS (evict E) | [G,A,F,B] |
| 10 | (0,0,0,0) | MISS (evict B) | [H,G,A,F] |
| 11 | (1,0,0,0) | MISS (evict F) | [D,H,G,A] |
| 12 | (1,1,0,0) | HIT | [A,D,H,G] |

**2 hits / 12 accesses = 1/6 = 0.166666... hit rate.**
`debug/03_verify_hit_rate.py` asserts the per-burst hit-rate path
returns this exact value for this sample and cache config; a mismatch
means a real bug, not rounding noise, since every number here is exact.

This is a different number from what `src/cachesim/sweep.py`'s current
`sample_hit_rate` (and the native `cache_replay`/`cache_sweep` binaries
it mirrors) actually compute today: as written, they replay every
individual expanded weight value as its own access (48 accesses here,
giving 38/48 = 0.7917), because `expand_events` flattens every event's
burst into individual `Element`s before replay ever sees event
boundaries, so a burst that resolves to one already-resident line still
counts as 1 real access plus 3 free repeat hits. Adopting the per-burst
definition above requires an actual code change, not just a documentation
one: `sample_hit_rate` (Python) and `cache_replay.cpp`/`cache_sweep.cpp`
(C++) need to process one event's elements at a time, collapse
consecutive identical tags within that event down to their first
occurrence, and only then feed the deduplicated per-event tag sequence
to the cache replay. See Part 1b for where this lands in the
repackaging work.

### Stage 1: Repackage + Python/C++ parity check

Dependency: Stage 0's tiny trace; Part 1b's move and per-burst
hit-rate fix both applied to the packed Python reference and the
relocated C++ path, with a fresh `make` run in each relocated directory
(binaries need rebuilding at the new location); the packed
`dump/python_reference/` copies stay importable for this one
comparison.

- `debug/04_diff_reconstruction.py` (new): runs the tiny trace through
  both the packed Python `reconstruct_samples_for_schedule` path and the
  relocated `native_bridge.reconstruct_samples_native`, and diffs every
  tile's `weight_addresses` and `tick_ids` exactly.
- `debug/05_diff_hit_rate.py` (new): runs the same tiny weight trace
  through the packed Python `cache.py`/`layout.py`/`sweep.py` path and
  the relocated `native_bridge.native_sample_hit_rate`, and diffs the
  hit rate.

Passing both diffs is what makes the C++ path trustworthy as ground
truth for everything after this stage.

```bash
conda run -n base env PYTHONPATH=src python debug/04_diff_reconstruction.py \
  --arch loas --trace-dir tiny --layer layer_00

conda run -n base env PYTHONPATH=src python debug/05_diff_hit_rate.py \
  --sample debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz \
  --cache-config configs/cache/cache_config.yaml
```

### Stage 2: Archmodel verification (native C++ path)

Dependency: Stage 1 passed; a working Gurobi license
(`GRB_LICENSE_FILE`) for schedule solving; `src/mip_solver`,
`src/archmodels/loas` (starting arch), `src/tracegen.py`.

- `scripts/solve_schedules.py` (reused): solves the tiny layer's
  schedule once, caches it to `debug/schedules/loas/tiny/layer_00.json`.
- `scripts/generate_weight_traces.py` (reused): loads that schedule and
  reconstructs 1 sample via the native path (now the only path, per Part
  1b's hard-failure change).
- `debug/01_inspect_weight_trace.py` (new): loads the generated sample
  and prints every tile's `weight_addresses` in full, checking each
  stays within the tiny layer's known bounds.

```bash
conda run -n base env PYTHONPATH=src python scripts/solve_schedules.py \
  --trace-root debug/traces --trace-dirs tiny --archs loas \
  --cache-dir debug/schedules

conda run -n base env PYTHONPATH=src python scripts/generate_weight_traces.py \
  --arch loas --trace-dir tiny --layer layer_00 \
  --trace-root debug/traces --schedule-cache debug/schedules \
  --out-dir debug/weight_traces --sample-count 1

conda run -n base python debug/01_inspect_weight_trace.py \
  --sample debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz
```

### Stage 3: Cache verification (native C++ path)

Dependency: Stage 2's inspected sample; `cachesim/native_bridge.py` and
its relocated `cache_replay` binary.

- `debug/02_inspect_elements.py` (new): uses the packed Python
  `layout.py` purely as a debugging aid (not the production path) to
  print every individual `(kh, kw, cin, cout)` element and its
  cache-line tag for the one sample, before deduplication, so you can
  see by hand which elements collapse to the same tag within a burst.
- `debug/03_verify_hit_rate.py` (new): calls
  `native_bridge.native_sample_hit_rate` directly (now computing the
  per-burst definition, per Part 1b's fix) and reports the resulting
  hit rate as the number of record. The independent cross-check role is
  already filled by Stage 1's parity check, so no second from-scratch
  counter is needed here.

```bash
conda run -n base env PYTHONPATH=src python debug/02_inspect_elements.py \
  --sample debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz \
  --cache-config configs/cache/cache_config.yaml

conda run -n base env PYTHONPATH=src python debug/03_verify_hit_rate.py \
  --sample debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz \
  --cache-config configs/cache/cache_config.yaml
```

## Follow-on (not in this plan's scope)

Once Stage 3 passes, replaying the same tiny case through the archived
`profiling/0726` native `cache_sweep` binary and confirming agreement
with `native_bridge.native_sample_hit_rate` is the natural next check
before trusting the full-scale sweep again.
