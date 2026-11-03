# L2 Touch-Triggered Prefetch Plan

**Goal:** Replace the L2 `next_tile` trigger: instead of firing on an L2 demand miss, fire when a line's demand touch count within the current tile crosses `l2_prefetch_min_touches` (the 2nd access for min_touches=2, etc., typically an L1 hit). The prefetch target is unchanged: same (kh, kw, cin), cout+1, forward, `distance` deep, filled into L2 only (never promoted to L1 by the prefetch).

**User decisions (2026-11-01):** (1) touch trigger REPLACES the miss trigger; (2) the retrigger chain is DISABLED in touch mode; (3) default `l2_prefetch_min_touches` stays 3.

## Design

- New config key `l2_prefetch_trigger`: `"touch"` (default) | `"miss"` (legacy). `miss` must reproduce today's behavior bit-for-bit.
- `Prefetcher::on_access(LineId, tile)` now returns `bool fired` (base class returns false). `NextTilePrefetcher::on_access` keeps the lazy per-tile reset + increment, and returns true exactly when the post-increment count equals `max(min_touches, 1)`: this fires once per (line, tile) with no extra flag, and makes min_touches 0/1 both mean "fire on first touch". A new tile re-arms the line (reset ⇒ it can fire again).
- Engine (`on_l1_probe`, at the existing `on_access` call in the `r.demand` block): in touch mode, when `on_access` returns true, call `prefetch_on_demand(Level::L2, r.core, tile, r.burst, r.line, now)` right there. No change to `on_demand`'s filter is needed: at fire time count == threshold, so `count >= min_touches` passes naturally; `ctx.retrigger` stays false.
- Engine (`on_l2_probe`): in touch mode, skip BOTH the miss-trigger call (`engine.cpp:490`) and the retrigger block (`engine.cpp:492-501`). In miss mode both stay exactly as today.
- `validate()`: the `W_MIN_TOUCHES_FILTERS_ALL` warning applies ONLY in miss mode; in touch mode min_touches >= 2 is the intended configuration and must not warn.
- CSV: append `l2_prefetch_trigger` at the very END of the schema (after `l2_pf_filtered`); golden re-captured once, in the config task.
- Stats: no new counters. In touch mode `l2_pf_filtered` and `l2_pf_retriggers` legitimately read 0.

## Constraints

- Clean build under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow`.
- Phase 3 policy boundary holds: the policy counts and emits targets; all issue mechanics (ports, triage, drops) stay in the engine/level.
- `make test` and `make test-cli` green at every commit.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Tasks

### T10 - policy: firing on_access
Files: `include/cachesim/prefetch/prefetcher.h`, `include/cachesim/prefetch/next_tile.h`, `src/prefetch/next_tile.cpp`, `tests/prefetch/test_next_tile.cpp`.
Tests first: (a) min_touches=3: on_access returns false, false, TRUE, false, false on five same-tile touches; (b) fires once per line: two lines interleaved each fire on their own 3rd touch; (c) tile change re-arms: after firing in tile 0, three touches in tile 1 fire again on the 3rd; (d) min_touches 0 and 1 both fire on the 1st touch; (e) on_demand called at fire time emits the COUT neighbours (filter passes); (f) all existing tests still green (on_access's return is ignored by old callers).
Commit: `feat(cachesim): NextTilePrefetcher::on_access fires at the touch threshold`.

### T11 - engine: touch-mode wiring
Files: `src/core/engine.cpp` (+ whatever carries engine params, e.g. the params struct the config is copied into), `tests/core/test_engine.cpp`.
Tests first: (a) touch mode: a scenario where a line is demand-touched 3x in a tile (2 L1 hits after the fill) issues the cout+1 L2 prefetch with NO L2 miss on a prefetch-triggering line (l2_pf_issued > 0, l2_pf_retriggers == 0); (b) the prefetched line fills L2 only: a later demand on it misses L1 and hits L2; (c) miss mode: reuse an existing next_tile engine test's constants verbatim, bit-identical; (d) touch mode with min_touches high enough that no line qualifies ⇒ l2_pf_issued == 0.
Commit: `feat(cachesim): touch-triggered L2 prefetch replaces the miss trigger`.

### T12 - config knob, CSV column, warning scope, golden
Files: `include/cachesim/config.h`, `src/config.cpp`, `src/instrument/stats.*`, `tests/test_config.cpp`, `tests/cout_golden.csv`.
Tests first: default is `touch`; `"miss"`/`"touch"` round-trip; unknown value refused naming the offender; W_MIN_TOUCHES_FILTERS_ALL emitted in miss mode with min_touches>=2 but NOT in touch mode; column `l2_prefetch_trigger` appended last. Re-capture golden via `tests/cout_golden.sh`; diff must be the one new trailing column (+ sim_wall_seconds) only: the fixture runs no L2 prefetch, so trigger mode must not move any other cell.
Commit: `feat(cachesim): l2_prefetch_trigger knob (touch|miss, default touch)`.

### T13 - sweep: is min_touches a dial now?
Scratch only. Release build; R9/R16/V8 s00000; `next_tile`, distance 1, trigger `touch`, min_touches ∈ {1, 2, 3, 4, 6, 8}; include the miss-mode min_touches=0 row (old prefetch-on) and the no-prefetch row from the 2026-11-01 sweep as baselines. Report total_cycles, l2_pf_issued/timely/wasted, l2 hit rate, dram_bytes per x; check the metrics now grade with x instead of cliffing; recommend the best x (primary: cycles; tie-break: timely ratio and DRAM bytes).
