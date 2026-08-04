# 2026-08-03 L1/L2 Cache Policy Plan

> Status: COMPLETE, implemented and verified 2026-08-03. This is **Stage 2**
> of the 2-level hierarchical cache design, following
> `log/2026-08-02-multinode-core-driven-weight-trace-plan.md` (**Stage 1**,
> the nested `tiles -> ticks -> cores -> weight_addresses` trace format).
>
> This plan **supersedes** `log/2026-07-28-set-index-and-cin-cout-layout-plan.md`
> in full: that plan's Stage 0 (set-index bug fix) is absorbed here as a
> prerequisite; its Stage 2 (burst-width-derived `cin x cout` layout) is
> replaced by the fixed 4x4 layout below. 07-28's plan is not implemented
> separately.

## Context

Stage 1 built the nested per-core, per-tick weight-fetch trace. The
existing `src/cachesim/` engine is single-level, single-inner-dim, and
reads the old flat schema (`_write_events` flattens `tile["weight_addresses"]`
directly) -- this was left untouched in Stage 1 pending this stage. This
plan replaces it with a two-level engine: private L1 per core, shared L2
(global-buffer substitute), consuming the Stage 1 nested format directly.

## Cache-line layout: hybrid cin x cout packing

Every cache line packs a fixed 4x4 block: 4 `cout` values (innermost) x 4
`cin` values (second-innermost), at one fixed `(kh, kw)`. `kh`/`kw` stay
exact.

```
tag = (kh, kw, cin // 4, cout // 4)
line_size_bytes = 16   # 4 x 4 elements, 1 byte/weight -> bytes == elements
```

One shared layout formula for L1 and L2. `line_size_bytes` is identical
(16) for both levels; only `cache_size_bytes` (capacity) differs between
them.

This also carries forward 07-28's set-index fix: the set-index formula
flattens using the layer's **true** `KH/KW/CIN/COUT` shape (already present
in every trace's `workload_dims`), not per-sample observed maxima, so all
sets stay reachable regardless of cache size/associativity.

## Structural sweep (applies to both L1 and L2, confirmed 2026-08-03)

- **Cache type/associativity**: 3 structures -- `fully_associative`,
  `set_associative` (32-way), `set_associative` (4-way).
- **L1 size**: 16KB or 32KB (private, one instance per core).
- **L2 size**: 128KB / 256KB / 512KB / 1024KB (shared, one instance).

Full grid: 3 structures x 2 L1 sizes x 4 L2 sizes = 24 (L1, L2) structural
+ size combinations, crossed with every (workload, layer, sample) in
scope.

## Two-level hierarchy semantics

- **Miss-fill**: inclusive. An L1 miss triggers an L2 lookup. An L2 hit
  fills the requesting core's L1. An L2 miss represents an off-chip fetch
  (unmodeled cost, matching Stage 1's deferred NoC-transaction costing)
  and fills both L2 and the requesting L1.
- **Tick-atomic L2 semantics** (corrects an earlier draft that let
  same-tick cores see each other's fills): every L1-missed core's L2
  lookup within one tick is resolved against the **snapshot of L2 from the
  start of that tick** -- lock-step cores are concurrent, not sequential,
  so none of them can hit off another core's fill from the same tick.
  Only after every core's lookup for the tick is resolved are that tick's
  fills (demand inserts, prefetch inserts, hit-touches) collected and
  applied, in core-ascending order, to produce the L2 state the *next*
  tick sees.
- **Same-tick pinning**: a tag that was an L2 hit this tick is protected
  from eviction by this tick's own fills (it was genuinely resident when
  read, even though bookkeeping applies updates after the fact).
  **Overflow fallback**: if every resident line in L2 is pinned this tick
  and a miss still needs to evict, protection degrades to a priority
  order -- evict the pinned line that was closest to LRU *before* this
  tick's touches. (Worked examples for both the normal and the overflow
  case were derived in planning chat; port them directly to the hand-made
  tests below.)
- **Stats collected**: per-core L1 hit rate, aggregate L1 hit rate, L2 hit
  rate (of L1-missed traffic only), overall effective hit rate.

## L2 cout-prefetch policy

- Triggered **only on an L2 miss** for tag `(kh, kw, cin_blk, cout_blk)`:
  after the demand fetch, also insert `(kh, kw, cin_blk, cout_blk + 1)` if
  within the layer's true `COUT` range. No-op at the boundary.
- Not triggered on L2 hits. One block ahead only, no chaining.
- Prefetch fills are tracked separately from demand accesses so they
  don't inflate the reported L2 hit rate.

## Implementation (file by file)

- **`src/cachesim/config.h` / `config.py`**: add hybrid-layout fields
  (fixed `cin_block=4`, `cout_block=4`) and per-layer true shape bounds
  (`kh_bound, kw_bound, cin_bound, cout_bound`) for the corrected
  set-index.
- **`src/cachesim/layout.h` / `layout.py`**: extend `tag_for_element`/
  `TagPacker` to collapse `cin` and `cout` together (fixed 4x4) and to
  flatten set-index using the real layer shape.
- **`src/cachesim/cache.h` / `cache.py`**: unchanged -- reused as the
  single-cache building block, instantiated once per core (L1) + once
  shared (L2) instead of once per replay.
- **New orchestration** (native + a Python reference twin): per-core L1s,
  shared L2, tick-atomic snapshot lookup, inclusive miss-fill, cout
  prefetch, same-tick pin/fallback.
- **New entry point** (e.g. `cache_replay_hierarchical`): reads the Stage
  1 nested JSON directly (`tiles -> ticks -> cores -> weight_addresses`),
  drives the hierarchy, reports per-core L1 / aggregate L1 / L2 / overall
  hit rates.
- **`src/cachesim/native_bridge.py`**: new function replacing
  `_write_events`'s flat-schema read; serializes the nested trace plus
  L1/L2/prefetch config to the new binary.

## Hand-made tests

Continuing the `debug/NN_verify_*.py` numbering (currently at 11):

1. `debug/12_verify_hybrid_layout_tags.py` -- hand-derived 4x4 tags.
2. `debug/13_verify_set_index_fix.py` -- no dead sets on the tiny fixture.
3. `debug/14_verify_l1_l2_miss_fill.py` -- the miss/hit sequence worked in
   planning chat (2 cores, 6 tags, tick-atomic snapshot behavior,
   including the "prefetch evicted then immediately re-fetched" churn
   case).
4. `debug/15_verify_l2_cout_prefetch.py` -- the prefetch-produces-a-hit
   case.
5. `debug/16_verify_same_tick_pin_fallback.py` -- both pinning examples:
   normal (one hit protected, a different line sacrificed instead) and
   the overflow case (every resident line hit in one tick, fallback
   evicts the one closest to pre-tick LRU).

## Milestones

1. Hybrid layout + set-index fix on the *existing* single-level engine,
   tiny-trace verified (tests 1-2).
2. Two-level orchestration (private L1s + shared L2, tick-atomic
   snapshot, inclusive miss-fill, no prefetch/pinning yet) consuming the
   Stage 1 nested format, tiny-trace verified (test 3).
3. L2 cout-prefetch + same-tick pinning/fallback added, tiny-trace
   verified (tests 4-5).
4. **Real-data smoke test**: run the hierarchy engine against the
   already-generated multi-core `loas` traces at
   `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/loas/` -- 4
   arch-config combos (`inst16`/`inst1024` instance count x
   `noc512kb`/`noc4096kb` NoC buffer size) x 31 layers (19 resnet19 + 12
   vgg16) x 5 samples each (124 combo/layer pairs, confirmed format
   matches Stage 1's nested schema, 2026-08-03). This is a smoke test,
   not a statistically robust sweep -- only 5 samples/layer, only `loas`,
   only these 4 arch-configs. Full canonical-100-sample, all-5-arch
   coverage is future work, not part of this plan.
   - **Preview and confirm before running**, per this repo's standing
     convention: print the full grid (24 (L1,L2) structural/size combos x
     124 combo/layer pairs x 5 samples = size of the run, and where
     results land) and wait for go-ahead before executing.
5. **Analysis + artifact**, built on the Milestone 4 results. Follows the
   `profiling/0728_status_replay/build_artifact.py` + `artifact/index.html`
   + `artifact/data.js` convention already used in this repo (precompute
   a data.js from the sweep's CSV/JSON output, static HTML+JS renders it).
   Shown:
   - **Workload config** selector (resnet19_T4_all / vgg16_T4_all).
   - **Arch config** selector -- the 4 `loas` combos
     (`inst16`/`inst1024` x `noc512kb`/`noc4096kb`); this is the only
     "arch" axis available since only `loas` has multi-core trace data
     today, not the 5 SNN-architecture families.
   - **L1/L2 cache config** sweep controls (the 24-combo structural/size
     grid from above).
   - **L1 (cross configs) overall hit rate per arch config**: one
     aggregate hit-rate number per (structure, size) point, faceted by
     arch config.
   - **L1 (one config) per-layer hit rate per arch config**: an
     interactive config selector (not a hardcoded single choice) picks
     which (structure, size) point to break down layer-by-layer, faceted
     by arch config.
   - **L2 (cross configs) overall hit rate per arch config**: same as the
     L1 cross-config view, for L2.
   - **L2 (one config) per-layer hit rate per arch config**: same as the
     L1 per-layer view, for L2.

## Open items resolved during planning (2026-08-03)

- Cache type/associativity: fully-associative, 32-way, 4-way -- for both
  L1 and L2.
- Line size: 16 bytes fixed (4x4 elements).
- L1 and L2 share `line_size_bytes`; only `cache_size_bytes` differs.
- Miss-fill: inclusive (confirmed).
- This plan supersedes 07-28's set-index-and-layout draft entirely.
- Real data location and format confirmed (see Milestone 4).

## Implementation result (2026-08-03)

- Hand-made tests 12-16 pass against the Python reference and native
  hierarchy; test 17 verifies every fixed-grid native sweep point against
  the corresponding single-config native replay.
- Milestone 4 completed as Slurm job 20823836 (`COMPLETED`, exit `0:0`,
  38:52): 124 arch/workload/layer units, five samples each, 24 hierarchy
  configurations, and 14,880 validated result rows.
- Milestone 5 artifact and its pooled-count data are under
  `profiling/0803_l1_l2_cache/artifact/`.
