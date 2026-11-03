# L2 Prefetch-Protecting Replacement Plan (pf_lru)

**Goal:** A new L2 replacement policy with two priority classes. Lines filled by the L2 next_tile prefetch and not yet consumed are the protected class; everything else (demand fills, L1-prefetch fills, and prefetched lines after their first use) is the normal class. The victim always comes from the normal class, by LRU; only a set whose ways are all protected victimizes a protected line, again by LRU. Within each class the order is plain LRU.

**User decisions (2026-11-02):** (1) L1-prefetch and on-demand lines are ONE class: once a line is consumed into L1 its L2 copy has no near reuse (T17: L2 hit rate is exactly 0 at 512KB with prefetch off on all four streams). (2) Unused L2-prefetch lines get the higher keep priority (T17: l2_pf_wasted 19.6k/18.1k/51.2k lines on R16/V8/V9 at the best cells, exactly 0 at 8MB; ceiling 6.3-11.2% of baseline cycles). (3) LRU inside each class.

**Evidence base:** scratch T17 (reviewed pass): 512KB vs 8MB L2 at the best L1xL2 cells, four streams, reproduction cells byte-identical to the T14/T16 matrices.

## Design

- **Class membership is one bit per slot, owned by the policy, told by the engine.** New optional verb on `ReplacementPolicy`: `note_protected(SlotId, bool)`, default no-op, mirroring the `note_next_use` precedent: the engine calls it where it already knows the fact, and every existing policy is untouched. The policy is still told nothing about sets, ways, or line addresses (plan 2.2's split holds).
- **New policy `PfLruPolicy`** (`include/cachesim/replacement/pf_lru.h`, `src/replacement/pf_lru.cpp`): a stamp-LRU (reuse `StampPolicy`) plus a flat `protected` bit vector indexed by slot. `pick_victim`: minimum stamp among unprotected candidates; if every candidate is protected, minimum stamp among all. Free ways are handled before the policy is asked, as today. Order-independent by construction (stamps are unique). `on_fill` clears the slot's bit (new occupant starts normal); `on_invalidate` clears it too.
- **Engine wiring, at the three places the engine already touches `l2_prefetched_`:**
  - Set: at the L2 fill that inserts into `l2_prefetched_` (engine.cpp:609), also call `note_protected(slot, true)` on the L2 policy. Same condition, no new rule: protected if and only if the fill is tagged as an unused L2 prefetch.
  - Clear on consumption: on EVERY L2 hit, at the same point the LRU stamp refreshes, call `note_protected(slot, false)`. A hit means the line was just consumed toward L1 (by demand or by an L1 prefetch holding its L1 entry), so its protection ends. Unconditional and mode-independent: for an untagged line it is a no-op.
  - Clear on eviction: nothing to do; the evicting insert's `on_fill` resets the slot's bit (and the existing `l2_prefetched_` erase at engine.cpp:616-618 keeps the stats set in step).
- **Accounting fix (touch mode only):** today the `l2_prefetched_` tag clears only on DEMAND hits, so with L1 prefetch on, lines consumed by L1-prefetch probes die still tagged and are miscounted as `l2_pf_wasted`. In touch mode, an L2 hit by an L1 prefetch (`!r.demand && r.mshr1 != nullptr`) on a tagged line now erases the tag and counts `++l2_pf_timely`. Miss mode is untouched: its tag lifecycle feeds the retrigger chain and must stay bit-for-bit legacy. Historical touch-mode CSVs (T13/T14/T15/T16) undercount timely and overcount wasted in every L1-d4 cell; cycles are unaffected.
- **Config:** `PolicyKind::PF_LRU`, name `"pf_lru"`, accepted ONLY via `l2_policy`. `policy: "pf_lru"` is refused naming the key: at the L1 nothing ever sets protection, so it would silently behave as plain LRU, and this codebase refuses silently-inert configs. CSV: `l2_policy` does NOT print today (T20 finding; the plan's first draft conflated it with `l2_prefetch_policy`), so T20 appends an `l2_policy` column at the very end of the schema, after `l2_prefetch_trigger`, per the positional-stability precedent in stats.cpp, and re-captures the golden once; the diff must be the one new trailing column (+ sim_wall_seconds) only.
- **Stats:** no new counters. The policy's effect is read through the existing `l2_pf_timely` / `l2_pf_wasted` / `l2_hits` / `dram_accesses` / `total_cycles`.

## Constraints

- Clean build under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow`.
- The array/policy split holds: the array keeps geometry only; the bit lives in the policy; the engine side (Engine or CacheLevel, the orchestration layer) is the only caller of `note_protected`. (T19 review: the consume-side clear lives beside `on_hit` in CacheLevel::triage, the plan's escape hatch.)
- Miss-mode behavior and all existing policies bit-identical: every pre-existing test green untouched, except tests that must ADD coverage.
- `make test` and `make test-cli` green at every commit.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Tasks

### T18 - policy: PfLruPolicy + note_protected hook
Files: `include/cachesim/replacement/policy.h`, `include/cachesim/replacement/pf_lru.h`, `src/replacement/pf_lru.cpp`, `tests/replacement/test_pf_lru.cpp`, build lists.
Tests first: (a) an older protected line survives; the LRU unprotected line goes; (b) all candidates protected: plain LRU wins; (c) `note_protected(slot, false)` returns the line to the normal class and it is victimized next; (d) `on_fill` resets a slot's bit (evict a protected line, refill, new occupant is normal); (e) permuting the candidate vector never changes the pick; (f) existing policies compile and pass unchanged (default no-op hook).
Commit: `feat(cachesim): PfLruPolicy, two-class LRU behind a note_protected hook`.

### T19 - engine: protect on prefetch fill, consume on hit, touch-mode timely fix
Files: `src/core/engine.cpp` (and `cache_level.*` only if the hit-stamp point lives there), `tests/core/test_engine.cpp`.
Tests first: (a) with `l2_policy: pf_lru` in touch mode, an unused prefetched line outlives eviction pressure that removes older demand lines, and a later demand on it hits L2; (b) after a demand hit consumes it, it is evictable (normal class); (c) an L1-prefetch hit consumes it too, and in touch mode that hit counts `l2_pf_timely`, not `l2_pf_wasted`; (d) miss-mode constants from an existing engine test, bit-identical (tag lifecycle and retrigger untouched); (e) `l2_policy: lru` runs bit-identical to today with the new calls in place (no-op hook).
Commit: `feat(cachesim): L2 pf_lru wiring and touch-mode timely credit for L1-prefetch hits`.

### T20 - config knob
Files: `include/cachesim/config.h`, `include/cachesim/enum_names.h`, `src/config.cpp`, `tests/test_config.cpp`.
Tests first: `"pf_lru"` round-trips through `l2_policy`; `policy: "pf_lru"` refused naming the offending key; unknown values still refused; `make_policy` builds PfLruPolicy for the L2; golden diff empty (assert, do not re-capture).
Commit: `feat(cachesim): l2_policy pf_lru`.

## Follow-up (2026-11-02, user decision after T22/T23): random fallback

T23 (reviewed) showed pf_lru's regression is targeted: the all-protected fallback picks the LRU-oldest protected line, and the deterministic core-ascending fill order makes that the SAME core's line in 32/32 sets, stripping core 0's coverage while cores 1-15 keep 32 lines each; the barrier prices the one straggler at 16x. User decision: keep two classes, but pick the fallback victim at RANDOM within the protected class instead of by LRU, so forced evictions spread ~uniformly (~2 lines/core/bad-tile instead of 32 on one core).

### T24 - policy: pf_lru_rand
Files: `include/cachesim/replacement/pf_lru.h`, `src/replacement/pf_lru.cpp`, `include/cachesim/replacement/policy.h` (PolicyKind::PF_LRU_RAND), `include/cachesim/enum_names.h`, `src/replacement/policy.cpp`, `src/config.cpp` (L2-only refusal, mirror pf_lru's), tests (`test_pf_lru.cpp`, `test_config.cpp`).
Behavior: identical to PfLruPolicy EXCEPT the all-protected fallback, which picks a deterministic pseudo-random candidate. Requirement: order-independent (a function of the candidate SET, per the pick_victim contract), deterministic across runs and platforms, no global RNG: e.g. victim = argmin over candidates of splitmix64(line ^ fixed_seed ^ draw_counter), draw_counter advancing per fallback draw (pick_victim is non-const for exactly this reason). The unprotected path must stay byte-identical to PfLruPolicy.
Tests first: (a) all-protected draws spread across slots over repeated draws (no fixed victim); (b) two identical call sequences give identical victims (determinism); (c) permutation invariance of each draw; (d) scripted mixed sequence: victims identical to PfLruPolicy whenever an unprotected candidate exists; (e) config: "pf_lru_rand" round-trips via l2_policy, refused via policy naming the key; l2_policy CSV cell prints pf_lru_rand (no schema change).
Commit: `feat(cachesim): pf_lru_rand, random fallback within the protected class`.

### T25 - sweep: does the random fallback recover the barrier?
Scratch only. Release build; 4 streams x L1 {off, d4} x touch min_touches {8..12} x l2_policy {lru, pf_lru, pf_lru_rand} at 512KB; gate: lru and pf_lru cells byte-identical to T21. Headline: (1) V9 d4 mt8 stall_barrier delta vs lru (T23 predicts collapse from +282.7k toward ~0) and the identity check delta_cycles ~ delta_core_stalls/16; (2) best cells vs both lru and pf_lru (predictions if barrier fully recovers: V9 mt12 ~ -1.4k vs lru, R16 mt12 ~ -2.2k); (3) --barrier-log at V9 d4 mt8+mt12: argmax-core histogram flattens, per-core tile-19 coverage ~uniform (~30/32), no new pinned victim; (4) wasted/dram stay at or below pf_lru levels.

### T21 - sweep: pf_lru vs lru against the T17 ceiling
Scratch only. Release build; R9/R16/V8/V9 s00000; L1 {off, d4} x touch min_touches {8, 9, 10, 11, 12} x `l2_policy` {lru, pf_lru} at 512KB. Reproduce the lru cells byte-for-cell against T14/T16 first. Report per cell: total_cycles, l2_pf_timely/wasted, l2 hit rate, dram_accesses; headline: cycles recovered by pf_lru at each stream's best cell as a fraction of the T17 ceiling (R16 41,751 / V8 27,678 / V9 27,793 / R9 525 cycles). Also check whether pf_lru moves the best min_touches (protection may make lower thresholds viable, since over-issued prefetches no longer evict each other's demand victims first).
