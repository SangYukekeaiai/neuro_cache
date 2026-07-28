# 2026-07-28 Set-Index Fix and cin x cout Layout Implementation Plan

Status: DRAFT, awaiting review. Nothing in this document has been
implemented. This plan depends on and sequences two earlier documents:
`log/2026-07-28-cold-miss-classification-plan.md` (Part A, finding 5,
first flagged the set-indexing bug) and the published design artifact
"Packing cin x cout into one cache line" (the layout proposal itself,
which explicitly should not be evaluated until this fix lands, since it
makes the same bug worse).

## Before any sweep run: preview and confirm

Every stage below that actually executes a sweep (Stage 1's
re-baseline, Stage 4's full comparison, and any one-off run in between)
prints a preview before it starts and waits for confirmation, rather
than launching straight into computing statistics:

- the cache config grid about to run (cache_type x associativity x
  size_bytes x line_size, and whether fully_associative is included per
  Stage 0c)
- which arch(s), workload(s), and layer(s) are in scope
- how many samples per layer, and whether that's the full canonical set
  or a restricted slice
- which output columns/statistics the run will produce, and where they
  land (results directory, whether it's fresh per the reproducibility
  caveat about `merge_results` concatenating mismatched schemas)

This is a standing requirement for this project, not just this plan:
any script or run that produces sweep statistics should show this
summary and get a go-ahead first.

## Why this ordering

The set index is currently `sum(kh, kw, cin, cout // line_size) %
num_sets` (`src/cachesim/cache.py:49-60`,
`profiling/0726/native/cache_sweep.cpp:295`). Summing a 4-dimensional
coordinate onto one integer collapses most of the possible sums into a
narrow range, so most sets are never reachable at low associativity
(measured: 71 of 256 sets used for one real layer at 4-way, size 32768,
line 32). Every associativity comparison drawn from the existing
`results_cout_test*` CSVs is therefore suspect. The cin x cout layout
proposal divides `cin` as well as `cout`, which shrinks that reachable
range further, so evaluating it before this fix would make a sound
layout look worse than it is.

## Stage 0: Fix the set index

### 0a. Quick isolating fix (no format change, do this first)

`profiling/0726/native/cache_sweep.cpp` already computes a flattened
mixed-radix index per deduped access, `packed[i]`, at lines 243-253, but
throws it away and uses `dtag_sum[i]` (the plain component sum) for set
selection at line 295. Change line 295 from `dtag_sum[i] % num_sets` to
`dpacked[i] % num_sets`. This uses per-sample observed maxima (`max_kh,
max_kw, max_cin, max_cout`) as radices rather than the layer's true
declared shape, so it is not the final fix, but it isolates one
question cleanly: how much of the associativity distortion comes from
summing instead of flattening, independent of whether the radices are
exactly right. One line, no input-format change, safe to run today.

### 0b. Real fix: flatten using the layer's true shape

The per-sample observed maxima in 0a can undercount a dimension's true
range (e.g. if a particular sample never touches the last few `cin`
values), which would make set assignment sample-dependent. The layer's
real `KH, KW, CIN, COUT` already exist in every sample JSON as
`workload_dims` (written by `src/tracegen.py:189,202,235`) and are
already parsed into memory by `profiling/0726/cache_sweep.py:110`, but
are dropped one line later because the binary format handed to the
native binary has no slot for them.

Changes needed:

- `profiling/0726/cache_sweep.py:107-116`: add `KH, KW, CIN, COUT` (read
  from the already-loaded `data["workload_dims"]`) to the packed binary
  header sent to the native process.
- `profiling/0726/native/cache_sweep.cpp`'s `read_sample`/`main`: read
  the four new header fields and use them as the flatten radices instead
  of the per-sample maxima computed at lines 243-253.
- `profiling/0726/native/cache_sweep.cpp:295`: use the real-radix
  `dpacked[i] % num_sets` (same call site as 0a, now backed by real
  bounds).
- `src/cachesim` reference path is the more invasive half, since
  `Cache._set_index` (`cache.py:49-60`) and the native equivalent
  (`native/cache.h:46-50`) currently see only the tag tuple, not the
  layer shape. Add `kh_bound, kw_bound, cin_bound, cout_bound` (or similar) to
  `CacheConfig` (`src/cachesim/config.py`, currently frozen/validated in
  `__post_init__`), thread them into `Cache`'s constructor, and mirror
  the same fields in `native/config.h`. This touches `config.py`,
  `cache.py`, `native/config.h`, `native/cache.h`, `native/main.cpp`, and
  whatever YAML loader populates `CacheConfig`.
- One derivation detail worth stating explicitly rather than assuming:
  the flatten order must put the swept `inner_dim` last (fastest
  varying), matching what `packed[i]` already does by dividing the inner
  dim before packing. A naive `((kh*KW+kw)*CIN+cin)*COUT+cout` only
  agrees with `tag_for_element`'s per-dim floor division when
  `inner_dim == cout`; for `inner_dim` in `{kh, kw, cin}` the inner dim
  needs to move to the last position in the flatten before dividing by
  `line_size`.

### 0c. Always include a fully-associative run

`fully_associative` is already a complete, working cache type on both
the Python reference (`cache.py:24-37`) and the native path
(`native/cache.h:15-31`, `cache_sweep.cpp:126-158`), and the C++ sweep's
own default struct list already includes it:

```cpp
// cache_sweep.cpp:90-98
static const StructConfig STRUCTS[6] = {
    {"direct_mapped", 0},
    {"set_associative", 4},
    {"set_associative", 8},
    {"set_associative", 16},
    {"set_associative", 32},
    {"fully_associative", 0},
};
```

It is excluded from the current results by three separate filters, all
outside `cache_sweep.cpp` itself:

1. `profiling/0726/cache_sweep_persample.py:30`: hardcoded
   `STRUCT_IDS = "0,1,3,4"`. Change to `"0,1,2,3,4,5"` (or drop
   whichever subset isn't wanted, but include `5`).
2. Whichever `--struct-ids` value was used to launch the `cout_test`
   sweep (not recorded in any file; the CSVs show only
   `set_associative` at 4/16/32). Any future sweep invocation should
   either omit `--struct-ids` (native default is all six) or explicitly
   include `5`.
3. `profiling/0726/plot_cout_hit_rate.py:26-41`: `ASSOCIATIVITIES = [4,
   16, 32]` and a filter that drops any row where `cache_type !=
   "set_associative"`. Needs a fully-associative series added
   explicitly (it has no `associativity` value, since `assoc == 0` in
   `STRUCTS`), rendered as a reference line/ceiling rather than a fourth
   bar in the associativity group.

Purpose: fully-associative has `num_sets = 1`, so `_set_index` always
returns 0 (`cache.py:56-58`) and it is completely immune to the
set-indexing bug. It becomes a ceiling: the ratio of a set-associative
run's hit rate to the fully-associative run's hit rate at the same
(size, line_size) tells you how much of the gap is a true associativity
effect versus indexing overhead, before and after Stage 0's fix.

### 0d. Verification

Extend the per-set occupancy check already scoped as idea 3.5 in this
conversation's locality-analysis discussion: after 0a and again after
0b, confirm `sets_used == num_sets` for every configuration where
`distinct_tags >= num_sets`, and that `max_set_load / ideal_load` is
close to 1 rather than the 4-9x skew measured under the current sum
formula. If dead sets remain after 0b, the flatten is still wrong;
don't proceed to Stage 2 until this passes.

## Stage 1: Re-baseline before touching the layout

Re-run the `cout_test`-style sweep (fresh results directory, per the
existing reproducibility caveat about `merge_results` blindly
concatenating old and new schemas) with Stage 0's fix and the
fully-associative baseline included. This produces the first
trustworthy associativity comparison for all four archs, and is the
reference the layout proposal in Stage 2+ gets compared against.

## Stage 2: Implement the cin x cout layout, Path A only

Per the published design artifact, build the low-risk path first: leave
`address.py`'s bursts unchanged (still one fixed `cin`, 16 ascending
`cout` values per burst), and change only `tag_for_element`
(`src/cachesim/layout.py:95-97` and the native equivalent) to divide
both `cin` and `cout`:

```
B_cout(L) = min(L, W)          # W = burst width, 16 for LoAS
N_cin(L)  = max(1, L / W)
tag = (kh, kw, cin // N_cin(L), cout // B_cout(L))
```

Needs a new `CacheConfig` field (`layout_mode: cout_only |
cin_cout_2d`, or equivalent) rather than overloading the existing
single-dimension `inner_dim`, since two dimensions now change shape per
line instead of one. `W` should be read from the tile's declared
`node_bound[COUT]` rather than hardcoded, so the formula still holds if
a future arch's burst width differs from LoAS's 16. Reject
`line_size < 16` explicitly (the packing constraint can't be met below
the burst width) rather than silently degrading.

No change needed to `address.py`, the event wire format, or the dedup
logic for Path A: the existing "cout emitted ascending, so same-tag
elements are contiguous within one event" invariant still holds,
because nothing about burst shape changes.

## Stage 3: Tiny-trace verification

Before running Stage 2's change across the sweep, extend the
hand-checkable tiny trace from `log/2026-07-28-debug-pipeline-plan.md`
(or a small variant of it with `CIN > 1`, since the existing tiny trace
uses `CIN=1` and can't exercise cross-cin merging) and hand-derive the
expected tags at `line_size` 16, 32, and 64 under the new scheme, the
same way the existing worked example does for the current scheme.
Assert the implementation matches exactly.

## Stage 4: Full comparison

Re-run the sweep from Stage 1's fresh baseline with the new
`layout_mode=cin_cout_2d` added as an additional swept configuration,
same (arch, layer, size, line_size) grid, fully-associative baseline
included. Compare hit rate and `mean_accesses` (once the cold-miss
plan's B4 columns land) between `cout_only` and `cin_cout_2d` at
matching line sizes, on the now-trustworthy set-indexed results.

## Deferred

- Path B of the layout (widening the burst itself to a true multi-cin
  hardware transaction) stays out of scope here; it needs the event
  wire format and dedup ordering changes described in the design
  artifact, and is a separate follow-on decision.
- The five locality-analysis ideas from earlier in this conversation
  (reuse-distance histogram, cold-miss fraction, inter-reference gap,
  cross-inner_dim comparison, per-set occupancy as a standing metric)
  stay suspended, per explicit instruction, until this plan is reviewed.
