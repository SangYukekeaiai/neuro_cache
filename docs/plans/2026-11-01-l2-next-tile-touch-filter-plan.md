# L2 NextTile Touch-Count Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate the L2 `next_tile` prefetcher behind a per-line, per-tile touch counter: only a cacheline the cores have touched at least `x` times in the current tile may trigger its COUT-neighbour prefetches, with `x` an adjustable config knob defaulting to 3.

**Architecture:** `NextTilePrefetcher` keeps a per-line `{tile, count}` touch record fed by a new no-op-by-default `Prefetcher::on_access(line, tile)` hook that the engine calls on every **L1 demand probe** (the full L1/L2 system's view of a touch: L1 hits count too, and an L2 eviction cannot erase the evidence of reuse). The count resets lazily when a line is first touched in a new tile. The filter is checked at emission time in `on_demand` with `count >= min_touches`; retrigger emissions are exempt so a chain started by a qualifying line stays alive. A new config field `l2_prefetch_min_touches` (default 3, 0 = filter off, reproducing today's behavior bit for bit) and a new stat `l2_pf_filtered` are appended at the end of the CSV schema.

**Tech Stack:** C++17, the existing native test harness (`tests/check.h`, `engine_fixture.h`), `make test` / `make test-cli` in `src/cachesim/native/`.

**Spec:** the Requirements section below (user request of 2026-11-01, revised same day); no separate spec document exists.

## Requirements (the spec)

1. Keep the current target selection: the same (kh, kw, cin) but next-COUT cacheline(s), forward only, `distance` deep (`next_tile.cpp:17-21`).
2. Add a filter: only a cacheline touched at least `x` times is allowed to trigger prefetch.
3. A touch is counted at the full L1/L2 system level (a core access, not an L2 access): intra-tile reuse absorbed by L1 hits must count, and an L2 eviction must not reset a line's evidence of reuse.
4. The touch window is one tile: counts reset at the tile boundary.
5. `x` is adjustable per run; the default is 3.

## Decisions (revised per user review of 2026-11-01)

| # | Decision | Why |
|---|---|---|
| D1 | A "touch" is a **demand L1 probe** of the line (same guard as `l1_accesses`, `engine.cpp:283-289`), fed to the shared L2 policy via a new `on_access(LineId, tile)` hook. L2 accesses are NOT counted separately: every L2 demand access was already an L1 probe first, so counting both would double-count. | User: the filter must see the full L1/L2 system. L1 absorbs most intra-tile reuse, so an L2-only count stays near 1 and an L2 eviction would wipe what little it saw; the count must be architectural (what the cores did), not cache-state-dependent. |
| D2 | Counts reset per tile, implemented lazily: the policy stores `{tile, count}` per line and resets the count the first time a line is touched in a new tile. No reliance on `on_tile_start` (16 cores each call it on the shared L2 policy; lazy reset has no ordering hazard). | User: per-tile window. Viable now because D1 counts L1 hits, so intra-tile counts accumulate fast. |
| D3 | The filter passes when `count >= min_touches`, count including the current touch. Default 3 ⇒ the 3rd touch onward may trigger. With `>=`, `min_touches = 0` passes always, so "0 = off" needs no special case. | User: `>=`, not strictly `>`. |
| D4 | Retrigger emissions (demand hit on a still-unused prefetched L2 line, `engine.cpp:485-495`) bypass the filter. `PrefetchContext` gains a `bool retrigger` field so the policy can tell. | The L2 policy is only consulted on an L2 miss or on this retrigger hit; a line's first L2 event in a tile is usually also its first L1-visible touches, so a filtered retrigger would kill every chain one hop in (the codebase measured the miss-only pathology at 50.0% vs 96.9% hit rate, `engine.cpp:477-481`). The filter gates which lines START a chain; a started chain sustains itself. |
| D5 | The knob lives on `NextTilePrefetcher` only; `neighbour` and the L1 policies ignore it. `min_touches = 0` is the exact current behavior and existing `next_tile` tests must pass unchanged with 0. | Scope = what was asked. |
| D6 | The default is 3, as requested, so a plain `next_tile` run after this change produces different numbers than the committed 80-row L2 demo (`data(demo)` commit 67420ba's comparison). Rows stay self-describing because the CSV carries `l2_prefetch_min_touches`. | User set the default. Re-running the old demo needs `l2_prefetch_min_touches: 0` in its grid. |

## Global Constraints

- Build must stay clean under the project flags: `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow` (native `Makefile`).
- New CSV columns are appended at the END of the schema, after `rrip_bits` (`stats.cpp:180-216`, rule stated at the `rrip_bits` comment).
- The Phase 3 policy boundary holds (`prefetcher.h:15-30`): the policy counts what the engine tells it, and never inspects cache contents, reserves a port, or touches an MSHR.
- The L1 prefetch path (`NextBurst`, the issue-site filter) is not modified; L1 prefetch probes are non-demand and must not count as touches.
- `make test` and `make test-cli` in `src/cachesim/native/` green at every commit; `cout_golden.csv` re-captured once, in the task that widens the schema.

## Review Focus

1. A woken request re-probes the L1 and is counted again (the hook mirrors `l1_accesses`), so contended lines cross the threshold slightly early - accepted; pinned by the unit test in Task 1 that counts exactly what `on_access` delivers.
2. `l2_prefetch_min_touches` set alongside `l2_prefetch_policy: neighbour` silently does nothing - pinned in Task 3 by a config test asserting the field parses and echoes regardless of policy.
3. `min_touches` large enough that nothing ever triggers must degrade to `none`-like behavior with the suppressions visible - pinned in Task 2 by the engine test asserting `l2_pf_issued == 0 && l2_pf_filtered > 0`.
4. A line's L2 miss can arrive BEFORE its count reaches `x` (the miss is often among the tile's first touches of that line); coverage then depends on later misses and retriggers, so the Task 4 sweep must report `l2_pf_timely`/`l2_pf_wasted` per `x` to make the default's coverage cost visible, not just the issue counts.
5. Negative `min_touches` must be refused at parse, not wrap through the comparison - pinned in Task 3's config test.

---

### Task 1: Touch counter and filter in `NextTilePrefetcher`

**Files:**
- Modify: `src/cachesim/native/include/cachesim/prefetch/prefetcher.h` (hook + context field + params field)
- Modify: `src/cachesim/native/include/cachesim/prefetch/next_tile.h`, `src/cachesim/native/src/prefetch/next_tile.cpp`
- Test: `src/cachesim/native/tests/prefetch/test_next_tile.cpp`

**Interfaces:**
- Consumes: existing `PrefetchContext`, `PrefetchTarget`, `AddressMapper::neighbour`.
- Produces:
  - `virtual void Prefetcher::on_access(LineId, std::int32_t /*tile*/) {}` - default no-op on the base class.
  - `bool PrefetchContext::retrigger` - new last field, `false` everywhere except the L2 retrigger call site (Task 2).
  - `std::int32_t PrefetchParams::min_touches = 0` - new field; `make_prefetcher` passes it to `NextTilePrefetcher(distance, min_touches)`.
  - `std::int64_t Prefetcher::filtered_triggers() const` - virtual, default 0; `NextTilePrefetcher` returns the number of `on_demand` calls its filter suppressed (read by Task 2's close-out).
  - `NextTilePrefetcher` state: `std::unordered_map<std::int32_t, TouchRecord>` keyed by `LineId::get()`, where `TouchRecord { std::int32_t tile; std::int32_t count; }`.

- [ ] **Step 1: Write the failing tests** in `test_next_tile.cpp`, following the file's existing style:

```cpp
// min_touches 0 keeps every existing behavior: construct with (distance, 0),
// reuse one existing emission case verbatim, assert identical output with
// zero on_access calls.
void test_min_touches_zero_is_the_current_policy();

// min_touches 3, all in tile 0: after 1 and 2 on_access(line, 0) calls,
// on_demand(ctx(line, tile 0)) emits nothing and filtered_triggers() grows
// by one each time; after the 3rd on_access (>=), on_demand emits exactly
// the distance COUT neighbours.
void test_filter_opens_at_min_touches_inclusive();

// Counts are per line: 3 touches on line A, 1 on line B, same tile.
// ctx(A) emits, ctx(B) does not.
void test_counts_are_per_line();

// Per-tile reset: 3 touches on the line in tile 0 (filter open), then one
// on_access(line, 1). on_demand with ctx.tile == 1 emits nothing until the
// line reaches 3 touches in tile 1.
void test_counts_reset_at_the_tile_boundary();

// ctx.retrigger == true bypasses the filter even at count 0.
void test_retrigger_is_exempt();

// Constructor refuses min_touches < 0 with std::invalid_argument.
void test_negative_min_touches_is_refused();
```

- [ ] **Step 2: Run to verify failure** - build and run the `test_next_tile` binary via the native Makefile's test path; expected: compile error on the missing constructor/hook.
- [ ] **Step 3: Implement.** `NextTilePrefetcher(std::int32_t distance, std::int32_t min_touches)`; `on_access(line, tile)` fetches the record, resets `count` to 0 when `record.tile != tile` (storing the new tile), then increments; `on_demand` returns early (and bumps the filtered counter) when `!ctx.retrigger && touches_of(ctx.line, ctx.tile) < min_touches_`, where `touches_of` reads 0 for a missing record or a stale tile; otherwise the existing emission loop runs unchanged. Header comment states D1-D4 in one line each.
- [ ] **Step 4: Run the test binary - all green; run the full `make test` to catch the `PrefetchContext` aggregate-init ripple** (the `ctx{...}` constructions in `engine.cpp` gain `false`; `make_prefetcher` in `prefetcher.cpp` gains the argument).
- [ ] **Step 5: Commit** - `feat(cachesim): per-tile touch-count filter inside NextTilePrefetcher`.

### Task 2: Engine wiring - feed touches from the L1, mark retriggers, surface the stat

**Files:**
- Modify: `src/cachesim/native/src/core/engine.cpp` (`on_l1_probe` demand block, the retrigger call site in `on_l2_probe`, `prefetch_on_demand` signature, `close_out_prefetch_stats`)
- Modify: `src/cachesim/native/include/cachesim/instrument/stats.h` / `src/instrument/stats.cpp` (field `l2_pf_filtered` only; column lands in Task 3)
- Test: `src/cachesim/native/tests/core/test_engine.cpp`

**Interfaces:**
- Consumes: `on_access`, `filtered_triggers()`, `PrefetchContext::retrigger` from Task 1.
- Produces: `stats_.l2_pf_filtered` (`std::int64_t`), filled at close-out from `l2_.prefetcher().filtered_triggers()`.

- [ ] **Step 1: Write the failing engine tests**, using the existing L2-prefetch scenarios in `test_engine.cpp` (the plan-0831 tests) as templates:

```cpp
// L1 HITS feed the counter: a line the core touches repeatedly while it is
// L1-resident still crosses the threshold, proven by a later L2 miss on it
// that is then allowed to emit (l2_pf_issued > 0).
void test_l1_hits_feed_the_l2_touch_counter();

// min_touches high enough: l2_pf_issued == 0, l2_pf_filtered > 0, and
// total_cycles equals the l2-policy-none run of the same fixture.
void test_fully_filtered_next_tile_degrades_to_none();

// min_touches 0: l2_pf_issued, l2_pf_timely and total_cycles are identical
// to the same fixture before this feature (copy the constants from an
// existing next_tile test).
void test_min_touches_zero_reproduces_old_numbers();
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** In `on_l1_probe`, inside the existing `if (r.demand)` stats block (`engine.cpp:283-289`, beside `access_log_->observe`), call `l2_.prefetcher().on_access(r.line, cores_.at(idx(r.core)).tile)`; non-demand (prefetch) probes never reach this block, which is the D1 guard. At the retrigger call site only (`engine.cpp:494`), pass `retrigger = true`, which means `prefetch_on_demand` grows a trailing `bool retrigger = false` parameter it forwards into the context. Close-out copies `filtered_triggers()` into `stats_.l2_pf_filtered`.
- [ ] **Step 4: `make test` green.**
- [ ] **Step 5: Commit** - `feat(cachesim): feed L1 demand touches to the L2 prefetch filter`.

### Task 3: Config knob, CSV columns, golden re-capture

**Files:**
- Modify: `src/cachesim/native/include/cachesim/config.h` (`l2_prefetch_min_touches = 3`), `src/cachesim/native/src/config.cpp` (parse + validate `>= 0`), `src/cachesim/native/src/core/engine.cpp:32-37` (copy into `p.l2.prefetch_params.min_touches`), `src/cachesim/native/src/instrument/stats.cpp` (append `l2_prefetch_min_touches` then `l2_pf_filtered` after `rrip_bits`)
- Modify: `src/cachesim/native/tests/cout_golden.csv` (re-capture)
- Test: `src/cachesim/native/tests/test_config.cpp`, plus whichever instrument test asserts the column list

**Interfaces:**
- Consumes: `PrefetchParams::min_touches` from Task 1, `stats_.l2_pf_filtered` from Task 2.
- Produces: config key `l2_prefetch_min_touches` (default **3**, `0` = off, negative refused at parse with the offending value named); two CSV columns, in this order, at the very end.

- [ ] **Step 1: Failing config tests:** default is 3; explicit 0 and 7 round-trip; `-1` refused; the key parses regardless of `l2_prefetch_policy` (Review Focus 2).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** parse, engine param copy, and the two appended columns.
- [ ] **Step 4: Re-capture the golden** with the recipe inside `tests/cout_golden.sh` (fixture build, `--run-id fixed --tier smoke`), then `make test && make test-cli` - both green. The golden diff must be: two new trailing columns, plus `sim_wall_seconds`; no other cell moves (the fixture runs no L2 prefetch).
- [ ] **Step 5: Commit** - `feat(cachesim): l2_prefetch_min_touches knob (default 3) and l2_pf_filtered column`.

### Task 4: Verification sweep on the loas 16-node streams

**Files:**
- Create: nothing tracked - scratch grid JSON + CSVs, summarized in the hand-back.

**Interfaces:** consumes the release binaries and `data/demo/loas/streams/`.

- [ ] **Step 1: Rebuild release** (`make -C src/cachesim/native MODE=release apps`).
- [ ] **Step 2: Sweep** R9/R16/V8 sample 0 with `l2_prefetch_policy: next_tile`, `l2_prefetch_distance: 1`, `l2_prefetch_min_touches ∈ {0, 1, 3, 8}`, everything else `configs/cache/base.json`.
- [ ] **Step 3: Check** (a) `min_touches=0` rows match a pre-change run of the same grid bit-for-bit except `sim_wall_seconds`; (b) as x grows, `l2_pf_issued` falls and `l2_pf_filtered` rises; (c) report `total_cycles`, `l2_pf_timely`, `l2_pf_wasted` per x so the default's coverage cost is visible (Review Focus 4).
- [ ] **Step 4: Commit** nothing unless a defect was fixed; paste the table in the hand-back summary.

---

## Self-review notes

- Spec coverage: Req 1 untouched by construction (Task 1 Step 3 reuses the emission loop); Req 2+3 are Tasks 1-2 (D1 hook at the L1); Req 4 is D2 (Task 1's reset test); Req 5 is Task 3.
- The one behavior change to existing configs is D6 (default 3); it is deliberate and the old demo is recoverable with `l2_prefetch_min_touches: 0`.
- Type consistency: `min_touches` is `std::int32_t` everywhere; the stat is `std::int64_t` like its sibling counters; `on_access` takes `(LineId, std::int32_t)` in both the base class and the engine call.
