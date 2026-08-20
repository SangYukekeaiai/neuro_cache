> Recovered from commit working tree (uncommitted Phase C EXPLAIN.md). This document explains increment Phase C.
> Provenance header added during the 2026-08-18 documentation recovery; the body below is byte-for-byte as committed.
# EXPLAIN: all of Phase C (plan units C1 `CacheLevel`, C2 the engine, C3 the core, C4 inclusion, C5 prefetch)

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

## Phase C is FIVE units, not three

The board's critical path reads `... -> B3 -> C1 -> C2 -> C3`. That is the
**critical path through** the phase, not the phase. Plan Part 7's Phase C table has
**five** rows:

| plan unit | what it is | where it lives |
|---|---|---|
| **C1** | `CacheLevel` = array + policy + port + MSHR file, and `triage()` | `cache_level.h/.cpp` |
| **C2** | the event loop, the **six** handlers, `retire`/`reinject` with the re-entry rule | `engine.h`, `engine.cpp` |
| **C3** | tile barrier, `tile_origin`, the core state machine and the self-timed recurrence | `engine.h`, `engine_core.cpp` |
| **C4** | two-valued inclusion: back-invalidation under `inclusive`, and the `non_inclusive` path | `engine.cpp` |
| **C5** | `Prefetcher`, `none`, `next_burst(d)`, the `demand = false` triage and the drop rules | `prefetcher.h/.cpp`, `engine_core.cpp` |

All five landed in this batch. C4 and C5 are *downstream of C3* in the dependency
order, which is not the same as being outside the phase, and both are load-bearing
for Phase D: D2 reports `back_invalidations` and the whole prefetch split, D3
sweeps `prefetch_distance`. Reading the chain as the scope would have declared
Phase C finished with the inclusion branch and the entire prefetcher missing.

Each part below reads on its own.

---

## Three naming collisions, stated once so nothing below is ambiguous

There are now **three** things called C1 and C2 in this project, and two of them
also collide with the decision numbers. Nothing below is ever written bare.

| the string | reading 1 | reading 2 | reading 3 |
|---|---|---|---|
| **C1** | **plan unit C1**: `CacheLevel` and `triage()` (Part 7) | **v3 change C1**: the intra-tile core schedule, 4.5's self-timed recurrence (the v3 header table, Parts 2.1, 3.1, 4.1) | - |
| **C2** | **plan unit C2**: the engine loop and the six handlers (Part 7) | **v3 change C2**: the pipelined burst fetch, 4.6's prefetcher | - |
| **B3** | **plan unit B3**: `MshrFile` | **decision B3**: `RefusalOrder`'s `NONE` sentinel is `INT64_MAX` | - |
| **B1**, **B2** | plan units `Port`, `EventQueue` | decisions about the archive and about `Tagged` | - |

Note the cruel part: **v3 change C1 is implemented by plan unit C3, and v3 change
C2 is implemented by plan unit C5.** The numbers do not line up and were never
meant to.

The conventions used everywhere below, and in every new source file's banner:

- a plan unit is **"plan unit C2"**,
- a board decision is **"decision B99"**,
- a v3 change is **"v3 change C1"**.

---

Changed files, new this batch:
`native/include/wcache/cache_level.h`, `native/src/cache_level.cpp` (plan unit C1);
`native/include/wcache/engine.h`, `native/src/engine.cpp` (plan units C2 and C4);
`native/src/engine_core.cpp` (plan unit C3, and C5's sink);
`native/include/wcache/prefetcher.h`, `native/src/prefetcher.cpp` (plan unit C5);
`native/include/wcache/trace.h` (the abstract stand-in for unit A3, see section 23).

Changed files, modified: `native/include/wcache/mshr.h`, `native/src/mshr.cpp`
(`Request::on_wait_index`, `is_prefetch_at_issue`, and the `has_slot` branch that
follows from it). No type was added: `BurstIndex` and `EventSeq` landed at Phase B.

Reviewer's files: `native/tests/engine_fixture.h`, `native/tests/test_cache_level.cpp`,
`native/tests/test_engine.cpp`, `native/tests/test_prefetch.cpp`, and the two
harness scripts.

Plan reference: Part 7's five Phase C rows, Part 3 in full including 3.4b, Part 4
(4.1 through 4.6), Part 5, Part 8, and Appendix A's I1 through I16.

**No build block in this file.** `PROGRESS.md` is owned by another role this round
and the verified counts belong in its Tested column. What is stated below about
*behaviour* is read from the sources and from the plan; section 24 separates what
is verified from what was merely observed once.

---

## Run W, the worked run used throughout

One configuration is walked in Parts I, II, III and V, so the same cycle numbers
mean the same thing everywhere.

| | value | why this value |
|---|---|---|
| cores | 2 | enough for one shared-line collision at the L2 |
| bursts | single-line, `gap = 1` between every pair, `local_tick(c, 0) = 0` | the corpus's shape (Q11: one burst per tick) |
| core 0's tile 0 | `b0 -> X`, `b1 -> Y`, `b2 -> Y`, `b3 -> X`, `mac_cycles = 4` | the repeats are what make two of the four prefetch drops reachable |
| core 1's tile 0 | `b0 -> X` | shares core 0's first line |
| L1, per core | 4 lines, `mshrs = 3`, `tgts_per_mshr = 2`, `demand_reserve = 1`, `ii = 1`, `latency = 0` | 2.5b's `l1_latency = 0` and `l1_ii = 1` |
| L2, shared | `mshrs = 1`, `tgts_per_mshr = 1`, `demand_reserve = 1`, `ii = 1`, `latency = 10`, `banks = 1` | `mshrs = 1` puts the whole machine under one credit, which is what exercises the wait indices |
| DRAM | `ii = 1`, `latency = 100` | 4.6's worked example uses the same 110-cycle full miss |
| other | `l2_to_l1_latency = 0`, `core_accept_ii = 1`, `inclusion = non_inclusive`, `prefetch = next_burst(1)` | 2.5b defaults, plus `d = 1` |

A full miss therefore costs `0 + 10 + 100 = 110` cycles, exactly as 4.6's table has it.

---

# Part I. Plan unit C1: `CacheLevel`

## 1. What a level is

Four objects behind one class, and the class is the same class at both levels:

```cpp
class CacheLevel {
    Level level_;                              // L1 or L2, read by triage for the re-entry rule
    const AddressMapper& mapper_;              // one mapper serves the whole hierarchy
    std::unique_ptr<CacheArray> array_;        // A4: geometry, no recency
    std::unique_ptr<ReplacementPolicy> policy_;// A5: recency, no geometry
    std::vector<Port> ports_;                  // one per bank; the L1 is the banks = 1 case
    MshrFile mshrs_;                           // plan unit B3
    // ... num_sets_, bank_high_bits_, sets_per_bank_, candidates_ scratch
};
```

Plan 2.2's "L1 MSHR file" row and 2.3's "L2 MSHR file" row name the same structure
with different capacities, and 3.4's two triage functions are, in the plan's own
words, of "identical shape". So there is one class, and the L1 is the
`banks = 1` case in exactly the way a direct-mapped array is
`SetAssociativeArray` at associativity 1.

**The construction order is load-bearing**, in decision B62's shape:

1. build the concrete `SetAssociativeArray`, read `num_sets()` and `num_slots()`
   **off it**, then move it behind the abstract handle. Recomputing the set count
   from the config here would be the same division written in two places that can
   disagree about a geometry the array has already accepted or refused, and
   decision B63 split that division precisely so the product
   `line_size_bytes * associativity` is never formed;
2. size the policy from the array's slot count, so a policy is never sized from a
   geometry the array refused. `make_policy` is what rejects `random` (Q5, V29);
3. build one `Port` per bank;
4. precompute `sets_per_bank_`, clamped to at least 1 so a set count smaller than
   the bank count divides rather than dividing by zero.

`LevelParams` is a plain struct with **no validation**. Every cross-field rule the
plan names (`lines_per_burst > l1_mshrs` throws, `demand_reserve >= mshrs` throws,
`policy = random` throws) is D1's, and duplicating any of it here would be the
second source of truth D1's row exists to prevent. What the four constructors
still refuse are their own preconditions, and all four are `throw`s rather than
asserts, so they survive the sweep build's `-DNDEBUG`.

## 2. Triage CLASSIFIES and returns; the engine REACTS

This is the one design choice in plan unit C1 worth arguing about, so it is stated
before the branch walk.

Plan 3.4 written literally puts two boundary crossings inside the level:

```
triage_L1(r, now):
    ...
    core_line_done(r, now)                        # reaches into a CORE
    ...
    accept = l2_bank[bank_of(r.line)].reserve(now)
    schedule(E_L2Probe(r), accept + l2_latency)    # reaches into the QUEUE and the OTHER level
```

Here, `triage` performs **every state change 3.4 makes, in 3.4's order**, and
returns which of 3.7's outcomes happened:

| 3.4's `triage_L1` | here |
|---|---|
| probe, `on_hit`, release, `core_line_done` | returns `Hit`, having done the probe, the `on_hit` and the release |
| find, release, `targets.push` | returns `Merged` |
| find, `mark_refused`, `line_wait.push` | returns `BlockedTargets` |
| `mark_refused`, `slot_wait.push` | returns `BlockedPool` |
| allocate, `mshr1 = e`, `level = L2`, consume, reserve, schedule | returns `Forwarded`, having set `mshr1` and `level` |

What is left to the engine is exactly the two lines that cross a boundary.

**What that buys**, and it is not tidiness:

- the level **knows nothing of ports below it, of cores, or of the event queue**.
  It reserves its own port never; the engine does that. So a fixture can drive
  `triage` through all nine outcomes with no clock, no queue and no core at all,
  which is why plan unit C1's exit criterion ("the 3.4 triage table exercised
  branch by branch") is reachable as a unit test rather than only as an engine run;
- the two things that differ between the levels, what a `Hit` means and what a
  `Forwarded` means, are the **engine's** business, because both end in scheduling
  an event (P4). That is what allows one class to serve both levels honestly
  rather than by a `if (level_ == L1)` ladder. The one place the level does
  branch on its level is 3.5's re-entry rule (`r.mshr1 = &e; r.level = L2` on an
  L1 allocate), and that is written where the request takes the entry, which is
  the only place that knows it happened;
- P4 stays true by construction. A request cannot fall through the hierarchy
  inside one function call, because the function that would have done it returns
  instead.

`granted` is an out-parameter that is **replaced, not appended to**, and is
non-empty only on the two outcomes that release a reservation (a grantee that
re-triaged into a hit or a merge). The next waiter cannot be injected from inside
the level, because injecting reserves a port (decision B120), so it is handed back.

## 3. The triage table, branch by branch, with a concrete line

Every row below is a real cycle of Run W. The last two rows need one variant each,
noted in the row.

| # | cycle | level | request | what triage found | outcome |
|---|---|---|---|---|---|
| 1 | 0 | L1(c0) | demand `X`, burst 0 | array miss, no entry, `free = 3 > 0` | **`Forwarded`** |
| 2 | 11 | L2 | demand `X` from **core 1** | array miss, entry `E2x` exists, `targets` full at `l2_tgts_per_mshr = 1` | **`BlockedTargets`** |
| 3 | 12 | L2 | the **prefetch** for `Y`, already forwarded | array miss, no entry, `free = 0` | **`BlockedPool`** |
| 4 | 111 | L1(c0) | demand `Y`, burst 1 | array miss, prefetch entry `E1y0` exists, `1 < tgts_per_mshr = 2` | **`Merged`**, and the entry is promoted to `demand = true` |
| 5 | 112 | L1(c0) | **prefetch** for `Y` (burst 2) | array miss, entry `E1y0` exists | **`DroppedEntry`** |
| 6 | 120 | L2 | core 1's `X`, re-triaged after its wake | array **hit**: `X` was installed at 110 | **`Hit`** |
| 7 | 223 | L1(c0) | **prefetch** for `X` (burst 3) | array **hit**: `X` resident since 110 | **`DroppedArrayHit`** |
| 8 | 224 | L1(c0) | demand `X`, burst 3 | array hit | **`Hit`** |
| 9 | *variant*, `d = 2` | L1(c0) | a prefetch arriving while `live = 2` | `free = 1`, and a prefetch needs `free > demand_reserve = 1` | **`DroppedReserve`** |
| 10 | *variant*, `demand_reserve = 0` | L1(c0) | a prefetch arriving while `live = 3` | `free = 0` | **`DroppedNoSlot`** |

Six of the rows are worth reading in full.

**Row 1, miss-and-allocate.** `array_->probe(X)` returns `NoSlot`;
`mshrs_.find(X)` returns null; `has_slot` computes `free = capacity(3) - live(0) -
reserved(0) = 3` and the request is a demand, so the test is `free > 0`. The entry
is allocated with this request as `targets[0]` (decision B110: the primary occupies
the first target slot, which is what makes I11's bound `n_cores - tgts_per_mshr`
rather than one less), and then the two fields of 3.5 are set together:
`r.mshr1 = &e; r.level = L2`. I6 pairs them, so they are written at one site and
nowhere else. The engine then reserves the L2 bank port at cycle 0 and schedules
`E_L2Probe` at `0 + l2_latency = 10`.

**Row 2, blocked on targets.** Core 1's request for `X` arrives at the L2 at cycle
11 and finds `E2x` already there. `add_target` refuses because `|targets| = 1` is
already `l2_tgts_per_mshr`, and refusing **inside** `add_target` is what makes I3
unbreakable by a caller that checks the bound and then pushes anyway (decision
B114). So it goes to `E2x.line_wait` and `mark_refused` stamps it: this is the
**first refusal of the run**, so its `RefusalOrder` is **0**. Set
`l2_tgts_per_mshr = 2` instead and the identical request is `Merged` at the same
cycle. That single-parameter difference is 3.7's warning made concrete: a
`Merged` request holds a committed subentry and is satisfied **directly** by the
fill; a `BlockedTargets` request holds nothing, must go back through the port and
re-probe, and counting it as merged overstates target-list utilisation, which is
the one number `l2_tgts_per_mshr` is swept to find.

**Row 3, blocked on pool.** The prefetch for `Y` was forwarded at the L1 at cycle
1 and reaches the L2 at 12, where `l2_mshrs = 1` is already spent on `E2x`. It is
stamped **1** and pushed onto `slot_wait`. Note what this row is: a request with
`demand == false` sitting on a wait index, which I15 and V28 say cannot happen.
It is reached here in three requests. That is open question **P1** in section 25,
and it is the reason `has_slot` dispatches on `is_prefetch_at_issue(r)` rather
than on `r.demand`.

**Row 4, merge and promotion.** The core's own demand for `Y` arrives 110 cycles
after the prefetcher asked for it. The array still misses (`Y` has not been filled;
its L2 probe is still to come at 121), the prefetch entry is found, there is a free
target slot, so it merges and `add_target` runs `e.demand = e.demand || r.demand`.
That is 4.6's **late prefetch**: the fetch started early but not early enough, and
the core saves whatever part of the round trip has already elapsed. Promotion is
idempotent by construction rather than by discipline, because it is an `or`.
Exactly **one** MSHR entry ever exists for `Y` (I1, V25).

**Rows 5 and 7, two of the four drops.** Both are prefetches at issue, and both
return before touching anything:

- `DroppedEntry` at 112: `Y` is already coming. Note it is dropped at the
  **matching entry**, one step before the target-list bound is consulted, which
  is why `DroppedEntry` subsumes 4.6's separate "targets full" row and why a
  prefetch can never produce a `BlockedTargets`;
- `DroppedArrayHit` at 223: `X` is resident. The drop happens **without calling
  `policy_->on_hit(slot)`**, and that omission is the whole point (4.6, I15,
  decision B11): a prefetch is not a use, and letting it promote recency would let
  the prefetcher rewrite LRU order. It is expressible only because `probe` is
  `const` and is not an access (2.2).

**Rows 9 and 10, the other two drops, and why they are different numbers.** The
prefetcher's own budget and the file's reserve are **two different bounds**, and
row 9 is the case where they disagree. At `d = 2`, `issue_prefetch` checks its
credit budget `cap = l1_mshrs - l1_demand_reserve = 3 - 1 = 2` and, with one
prefetch in flight, issues a second. By the time that second probe is triaged, the
file holds `live = 2` (the demand entry for `X` and the prefetch entry for `Y`),
so `free = 1` and a prefetch needs `free > demand_reserve = 1`, which is false.
The reason is recoverable at exactly this moment and nowhere later, which is why
the two are separate enumerators:

```cpp
const std::int32_t free = mshrs_.capacity() - mshrs_.live() - mshrs_.reserved();
return free > 0 ? TriageOutcome::DroppedReserve : TriageOutcome::DroppedNoSlot;
```

## 4. Two branches that a valid config cannot reach, argued rather than measured

Both belong in the results discussion, and both are arguments from the invariants,
not observations from a run. Flagged as such.

**An L1 `BlockedPool` for a demand request is unreachable at 2.5b defaults.** N7
has D1 reject `lines_per_burst > l1_mshrs`, and a core has one burst in flight
(4.5, I16), so at most `lines_per_burst` demand entries exist per L1 at any time.
A prefetch can never take the last `l1_demand_reserve = lines_per_burst` entries.
So a demand line always finds `free > 0`. The branch is real code, exercised by
fixtures, and inert on the grid.

**`DroppedNoSlot` is unreachable at 2.5b defaults too.** When a prefetch is
triaged it is itself counted in `pf_outstanding`, so live prefetch entries are at
most `cap - 1 = l1_mshrs - l1_demand_reserve - 1`; live demand entries are at most
`lines_per_burst = l1_demand_reserve`. The sum is at most `l1_mshrs - 1`, so
`free >= 1` and the refusal is always attributed to the reserve. It becomes
reachable only where D1 already warns: a `demand_reserve` below `lines_per_burst`.

## 5. `install`, and the fifth verb that is not called

```cpp
InsertResult CacheLevel::install(LineId line);   // free way first, only then the policy (D6)
```

Free way first is not an optimisation: folding the free case into the candidate
list would oblige every policy to re-implement "prefer an empty way", and a policy
that got it wrong would evict a live line while a way sat empty.

Two things about it:

- it **returns what was displaced**, because the caller needs it: under
  `inclusion = inclusive` an L2 eviction must be back-invalidated out of every L1,
  and that scan is the engine's, because only the engine sees the other level
  (Part IV);
- it **does not call `policy.on_evict(slot)`**, which 3.4 line 619 calls after
  `on_fill(slot)` on the same slot. That is **U17**, an unresolved contradiction
  inside the plan, not an oversight: Part 2.2's authoritative interface lists four
  verbs and does not include it, and for any stamp policy the pseudocode's order
  clobbers the stamp the fill just wrote, so the freshly filled slot would look
  like the oldest line in its set. A5 built 2.2's four (decision B97) and this call
  site stays with 2.2 until you rule.

`install` throws `std::logic_error` when the line is already resident. I1 makes
that impossible, and it is checked anyway because a duplicate line in one set is
the failure this model can least afford: nothing crashes, every later probe finds
one of the two copies, and the hit rate is quietly wrong for the rest of the run.

---

# Part II. Plan unit C2: the engine loop and the six handlers

## 6. The loop

```cpp
void Engine::run() {
    tile_origin_.at(0) = SimTime{0};
    if (trace_.n_tiles() > 0) start_tile(0, SimTime{0});

    while (!queue_.empty()) {
        const Event<EventPayload> e = queue_.pop_min();
        dispatch(e);
    }
    // ... D12's deadlock check
}
```

That is the whole of 3.2. **No tick, no horizon, no scan over cores, no condition
re-evaluated on a schedule.** A stalled core has no scheduled event at all: it is
referenced by the structure it waits on, and that structure schedules its wake-up.
`now` is `e.key.time` and is monotonically non-decreasing because the queue is a
min-heap; there is no `now_` member for a handler to advance by hand.

The deadlock check at the end is D12 and is a **throw, not an assert**: the sweep
build is `-DNDEBUG`, and a deadlocked run that returns quietly still produces
numbers. It names the core, its tile, its burst and its outstanding line count, or
the file that still holds live entries.

## 7. The six handlers

**Six, not seven.** Plan Part 7's C2 row says "(v3: seven) The seven event
handlers"; plan 3.1 says "Six event kinds, unchanged in number by v3", that "C2
adds no event kind", and that service is "a call inside `E_L1Fill`, not a
scheduled event". Six is right and six is what is built; the Part 7 row is a
slip, carried in section 25.

| handler | fires when | does |
|---|---|---|
| `on_issue(c, k, now)` | burst `k` becomes due | expands the burst, sets `pending_lines`, reserves an L1 port slot **per line**, schedules a demand `E_L1Probe` for each, then calls the prefetcher |
| `on_l1_probe(r, now)` | the L1 port accepted this request, `l1_latency` later | `triage`, then react: serve and release on a hit, count and release on a drop, reserve the L2 bank and schedule `E_L2Probe` on a forward, nothing on merged or blocked |
| `on_l2_probe(r, now)` | the L2 bank accepted it, `l2_latency` later | checks I6, `triage`, then react: schedule `E_L1Fill` on a hit, reserve DRAM and schedule `E_L2Fill` on a forward |
| `on_l2_fill(e, now)` | the channel returns data | install in the L2, back-invalidate if `inclusive`, retire, schedule one `E_L1Fill` per target, reinject the wake list |
| `on_l1_fill(e, now)` | data reaches the L1 | install in the L1, clear the targets' `mshr1`, retire, `core_line_done` per target, reinject the wake list |
| `on_barrier(tile, now)` | the last core cleared the tile, `tile_tail` later | set `tile_origin[N+1]`, start the next tile or mark every core `Done` |

## 8. One miss, end to end: L1 -> L2 -> fill -> retire -> wake

Run W's first 121 cycles, in dispatch order. `class` is 3.6's tie-break class.

| cycle | class | event | what happens |
|---|---|---|---|
| 0 | 3 | `Issue(c0, b0)` | expand -> `[X]`; `pending_lines = 1`; port accept 0; schedules the probe below; then the prefetcher issues `b1`'s line `Y`, whose port accept is **1** |
| 0 | 2 | `L1Probe(X, c0)` | `Forwarded`. L2 bank accept 0 -> `L2Probe` at **10** |
| 0 | 3 | `Issue(c1, b0)` | core 1 issues `X`; its own L1 port accept 0 |
| 0 | 2 | `L1Probe(X, c1)` | `Forwarded`. L2 bank accept **1** (the bank is busy at 0) -> `L2Probe` at **11** |
| 1 | 2 | `L1Probe(Y, pf, c0)` | prefetch, `free = 2 > demand_reserve = 1` -> `Forwarded`. Bank accept 2 -> `L2Probe` at **12** |
| 10 | 2 | `L2Probe(X, c0)` | `Forwarded`. DRAM accept 10 -> `L2Fill` at **110** |
| 11 | 2 | `L2Probe(X, c1)` | `BlockedTargets`, stamped **0** |
| 12 | 2 | `L2Probe(Y, pf, c0)` | `BlockedPool`, stamped **1** |
| 110 | 0 | `L2Fill(E2x)` | install `X` in the L2; retire; target -> `E_L1Fill` at 110; wake = [stamp 0, stamp 1] reinjected, bank accepts **110** and **111** -> probes at **120** and **121** |
| 110 | 0 | `L1Fill(E1x0)` | install `X` in core 0's L1; clear `mshr1`; retire; `core_line_done` -> `serve(c0, 110)`; next `Issue` at **111** |
| 111 | 3 | `Issue(c0, b1)` | `[Y]`; probe at 111; the prefetcher asks for `b2` (also `Y`), port accept **112** |
| 111 | 2 | `L1Probe(Y, c0)` | `Merged` onto the prefetch entry, which is **promoted** to demand |
| 112 | 2 | `L1Probe(Y, pf, c0)` | `DroppedEntry`; `pf_outstanding` 2 -> 1 |
| 120 | 2 | `L2Probe(X, c1)` | re-triaged: array **hit** -> `E_L1Fill` at 120 |
| 121 | 2 | `L2Probe(Y, pf, c0)` | re-triaged holding its grant: `has_slot` admits it unconditionally, allocate spends the reservation -> `Forwarded`, DRAM accept 121 -> `L2Fill` at **221** |

Four things this timeline shows that no prose does.

**The whole point of P4.** `X` crosses three boundaries and each one is an event
with real cycles between them: `0 -> 10 -> 110 -> 110`. Nothing evaluates the L2's
state at the L1's timestamp.

**D4 made concrete, twice.** Core 1's request was classified `BLOCKED_TARGETS` at
cycle 11, when the line was genuinely absent. It wakes at 110 and **re-triages from
the top of its level**, where the same line is now resident, so it resolves as a
hit at 120 and allocates nothing. That is V5. The mirror case, a queued hit whose
line was evicted before service, is V6 and is the same mechanism.

**The re-entry rule.** Both woken requests re-enter at **L2**, not at the L1,
because `r.level` says so. A wake re-triaged at the L1 would find its **own** entry
(`E1x1`, `E1y0`), merge the request into itself, and wait forever for a fill nobody
will request. That is 3.5's trap and V11.

**A prefetch that saved nothing.** `Y`'s prefetch was issued at cycle 1 and the
line still lands at 221, exactly when a demand-only run would have landed it,
because the single L2 MSHR was the binding resource and the prefetch spent 98
cycles on a wait index. Prefetching wins where the *fetch* is what is late, not
where the *credit* is.

## 9. Retire, wake, reinject, and I7b in numbers

`MshrFile::retire` hands back two vectors and the engine treats them differently,
which is D5 in the other direction: a **target** is satisfied directly by the fill
and never re-triages; a **waiter** goes back through its level's port and re-probes.

At cycle 110 the wake list is `[req(X, c1) stamp 0, req(Y, pf) stamp 1]`, already
key-ordered by `retire`'s `stable_sort`. `reinject_all` walks it in that order and
each `reinject` **reserves a port**:

| order | request | `l2_bank.reserve(110)` | probe scheduled |
|---|---|---|---|
| first | `X`, core 1, stamp 0 | accept **110** | 120 |
| second | `Y`, prefetch, stamp 1 | accept **111** | 121 |

Reverse the two and the accepts swap. **That is I7b**: port reservation order
equals key order, and it is observable only at `ii >= 1` (N13, 4.3) because at
`ii = 0` both would be accepted at 110 and the event key would do all the
ordering. The sort producing that list is not redundant either; 3.8's
counterexample is a slot waiter that outlives the allocation of an entry it later
merges onto and arrives carrying an **older** stamp than what is already on the
line-wait index.

One asymmetry the engine owns rather than the file: at cycle 110 the L1 targets'
`mshr1` pointers are nulled **before** `retire` erases the entry:

```cpp
for (Request* t : e.targets) { t->mshr1 = nullptr; t->level = Level::L1; }
lvl.mshrs().retire(e, retire_);
```

`retire` cannot do it, because `mshr1` points from a request at *another* level's
file into this one; and doing it after the erase would form a dangling pointer
even if nothing dereferenced it. This is the second half of the obligation plan
unit B3 recorded against plan unit C2. Every target is cleared, not only the
primary: a secondary merged at the L1 never held an entry, so its `mshr1` is
already null, and assigning unconditionally is one rule instead of a special case
that has to know which target is which.

## 10. The three things determinism rests on

The exit criterion that matters for D3 is a byte-identical re-run (D11, V3), and
three properties carry it. None of them is a test; all three are structural.

**1. The event key is total, so no two events tie.** 3.6's key is
`(time, class, effective_age, core_id, seq)` and `seq` is a monotonic counter
assigned at **schedule** time (decision B107). Two events can never compare equal,
so the heap's internal arrangement is unobservable: `std::priority_queue` makes no
promise about equal elements, and here there are none.

**2. Nothing iterates an unordered container.** `MshrFile::entries_` is a
`std::unordered_map`, whose iteration order is unspecified and may differ between
library versions or insertion histories. Every read of it is a lookup by line or a
`size()` (decision B117). The one O(cores) loop in the whole model, the
back-invalidation scan of Part IV, walks the `l1_` **vector** by core id. That
matters more than it sounds: under LRU the service order **is** the recency order
(D7), so one flipped tie leaves a different victim and every access after it
diverges. A run is either bit-identical or arbitrarily different, which is also why
the 3.8 key change needed a deliberate one-time re-baseline.

**3. Port reservations are non-preemptive, so reserve order is service order.**
`Port::reserve` never refuses and is never released. Once cycle 110 is handed to
core 1's request, nothing can take it back, so the order in which the engine calls
`reserve` fixes the order in which the bank serves. That is what makes point 1 and
the wake sort actually reach the results rather than merely ordering a list.

## 11. Request lifetime: a deque arena and three terminal sites

The plan does not say where a `Request` lives, and it has to live somewhere
stable: the wait indices, the target lists and `Request::mshr1` all hold raw
pointers into it (P5).

```cpp
std::deque<Request> arena_;
std::vector<Request*> free_;
```

A `std::deque` never moves the elements it already holds when it grows, so a
pointer taken at cycle 0 is still valid 110 cycles and a hundred allocations
later; a `std::vector` would dangle every one of them on its first reallocation.
The free list keeps a full-corpus run from growing one `Request` per line forever.
`acquire` assigns the whole struct rather than field by field, so a field added to
`Request` later cannot be left carrying the previous occupant's value; a stale
`refusal` would give a fresh request someone else's seniority and reorder the FIFO
for the rest of the run.

**A request reaches a terminal state at exactly three places**, and `release` is
called at those three and nowhere else: an L1 array hit, a prefetch drop, and the
target loop of an L1 retire. Everything else (merged, blocked at either level,
forwarded, a target of an L2 entry) ends up in that same L1 retire. `release`
refuses a request that is still held:

```cpp
if (r.on_wait_index || r.reserved || r.mshr1 != nullptr) engine_error("release", ...);
```

which is I5's and I6's bookkeeping checked at the one moment it is cheap to check.

---

# Part III. Plan unit C3: the core state machine and the barrier

## 12. The recurrence, walked

```
issue(c, 0)   = tile_origin[tile] + local_tick(c, 0)
issue(c, k+1) = served(c, k) + max(gap_k, core_accept_ii)
served(c, k)  = the cycle the last line of burst k lands at the core
```

`gap_k` is a **difference** of two trace ticks, and 4.5 reads it as the MAC work
burst `k`'s weights feed: a duration the core owes **after** the weights arrive.
So it is added to `served(c, k)` and never to an absolute tick. v2 added it to an
absolute tick, which let a core that had already lost 60 cycles arrive at its next
burst on schedule anyway and discard the loss (D13).

In code the recurrence is three functions and one helper:

```cpp
SimTime Engine::step_after(CoreId c, std::int32_t tile, BurstIndex k) const {
    const SimTime gap = as_duration(trace_.gap(c, tile, k));
    return gap < params_.core_accept_ii ? params_.core_accept_ii : gap;
}
```

`core_line_done` decrements `pending_lines` and returns unless it reached zero
(N7: the burst is atomic, so the core takes delivery when the **last** line
lands); `serve` computes `want`, charges the two Part 8 quantities, advances the
cursor, and schedules the next `E_Issue`; `on_issue` expands the burst, sets
`pending_lines`, and reserves one L1 port slot per line.

## 13. The unbounded-baseline identity, `tile_origin == tick_base`

Set every access to a hit and every latency and `ii` to 0 (V1's configuration).
Then `served(c, k) = issue(c, k)`, the service floor is inert, and the recurrence
becomes `issue(c, k+1) = issue(c, k) + max(gap_k, 1)`, which telescopes:

Run W's core 0, whose trace ticks are 0, 1, 2, 3 and whose `mac_cycles` is 4:

| burst | `local_tick` | `gap` | `issue` | `served` |
|---|---|---|---|---|
| 0 | 0 | 1 | `tile_origin[0] + 0 = 0` | 0 |
| 1 | 1 | 1 | `0 + max(1,1) = 1` | 1 |
| 2 | 2 | 1 | `1 + max(1,1) = 2` | 2 |
| 3 | 3 | - | `2 + max(1,1) = 3` | 3 |

`served(c, k) == local_tick(c, k)` for every `k`, which is the trace's own
schedule reproduced exactly. The barrier then adds
`tile_tail[0] = mac_cycles[0] - max_tick[0] = 4 - 3 = 1`, so

```
tile_origin[1] = 3 + 1 = 4 = mac_cycles[0] = tick_base[1]
```

which is V1 in the form that also checks `tile_tail`:
`tile_origin[N+1] - tile_origin[N] == mac_cycles[N]` exactly.

Two things worth naming about this identity. It holds **only** because
`gap_k >= 1` everywhere (Q11, measured over ~3.7M bursts); a `gap_k == 0` pair
would be two bursts at one local tick, which the model serialises one cycle apart
by the `core_accept_ii` floor, and V20 asserts the corpus's count of such pairs is
zero. And at `l1_latency = 0` this run is not only a regression oracle, it is the
**scratchpad baseline** (2.5b): a 100% hit run reproduces the scratchpad timeline,
so every cycle the cache costs above `tick_base` is a miss and nothing else.

## 14. A stall shifts the whole rest of the tile, and the stalls sum to the stretch

**The pure shift (V20's form).** Take the baseline above and delay burst 0 by
`L = 110` cycles, everything else free:

| burst | `want` | `served` | shift |
|---|---|---|---|
| 0 | 0 | 110 | +110 |
| 1 | `110 + 1 = 111` | 111 | +110 |
| 2 | 112 | 112 | +110 |
| 3 | 113 | 113 | +110 |

`tile_origin[1] = 113 + 1 = 114 = 4 + 110`. The stall is **carried**, in full, to
the barrier. Under v2's rule burst 1 would have been issued at its own absolute
tick if that tick was more than 110 cycles out, and the loss would have vanished.

**The accumulation (Run W itself).** Core 0 misses twice and pays one cycle for a
prefetch's port slot:

| burst | `want` | `served` | `served - want` | `served - issued_at` |
|---|---|---|---|---|
| 0 | 0 | 110 | **110** | 110 |
| 1 | `110 + 1 = 111` | 221 | **110** | 110 |
| 2 | `221 + 1 = 222` | 222 | **0** | 0 |
| 3 | `222 + 1 = 223` | 224 | **1** | 1 |

`core_stall[0] = 110 + 110 + 0 + 1 = 221`. Core 0's last service is 224, so the
barrier fires at `224 + tile_tail(1) = 225`:

```
tile_origin[1] - tick_base[1]  =  225 - 4  =  221  =  core_stall[0]
```

which is V21's "`core_stall` sums to the tile stretch", exact, with no fitting.
Core 1 finished at 120 and contributes `barrier_slack_cycles = 224 - 120 = 104`
instead, which is the cost of the lock-step assumption and is measured rather than
assumed.

The one-cycle term on burst 3 is worth its own sentence, because it is the whole
cost model of prefetching in one number: at `l1_ii = 1` the prefetch of burst 3
took the port slot at cycle 223, so the demand probe was accepted at 224. One
prefetch, one cycle of core stall, and the line it fetched was already resident
anyway (row 7 of the triage table).

## 15. The barrier, and a core with zero bursts

Part 5 asks for a **countdown, not a scan**, and that is what is built:

```cpp
void Engine::barrier_arrive(CoreId c, SimTime now) {
    cores_.at(idx(c)).phase = Phase::AtBarrier;
    if (--cores_remaining_ > 0) return;
    queue_.schedule(now + as_duration(trace_.tile_tail(tile)), EventKind::Barrier, ...);
}
```

A core arrives **at its own last service** (`serve` calls `barrier_arrive` when
the cursor reaches `n_bursts`), and the tile's remaining compute is charged once,
at the tile level, as `tile_tail[N] = mac_cycles[N] - max_tick[N]`. Charging it
per core is impossible: the trace stores `mac_cycles` already reduced to the max
over the tile's cores (Q10). Charging nothing would end ptb's `layer_01` and
`layer_03` tiles 20 cycles (11.7%) early, on all 64 of them, compounding into
every later layer, and V1 would fail there in a way that looks like a cache bug.

`on_barrier` then does the measurement: `tile_origin[N+1] = now`, and either
starts the next tile or marks every core `Done`.

**A core with zero bursts in a tile** is not in the plan, and the trace format
permits it (`n_bursts` is a count per `(core, tile)` and nothing makes it
positive). It clears the barrier **at the tile origin**, inside `start_tile`:

```cpp
if (trace_.n_bursts(cid, tile) == 0) { barrier_arrive(cid, now); continue; }
```

so it decrements the countdown immediately and never issues. Without that branch
the countdown would never reach zero and the run would end at D12's deadlock
check. Two consequences to keep visible: such a core's `barrier_slack_cycles` is
the whole tile length, and if **every** core has zero bursts the barrier fires at
`tile_origin[N] + tile_tail[N]`, which still advances the clock because
`tile_tail >= 1` by construction.

**The service floor stops at the tile seam**, deliberately. `serve` uses
`cursor == 0` to mean 3.3's "`served_time` is NONE at a tile start" (one field
carrying its own validity cannot disagree with a second field that says whether it
is valid). Left on, the one core whose last service **defines** `tile_origin[N+1]`
could not take its first burst of the new tile in that same cycle, and every tile
would gain a cycle over the trace.

## 16. The service floor is asserted, not enforced

```cpp
if (now < want) engine_error("serve", "... was served at N, before its own schedule allows (M) (I13)");
```

I13 says `served(c, k+1) >= served(c, k) + core_accept_ii` under every policy.
It is satisfied **by construction**: the run-ahead lives in the memory system and
never delivers anything to the core, so the core cannot receive burst `k+1` before
it has asked for it, and it does not ask before its own recurrence says so. The
check therefore never fires today and exists to catch a future core-side policy
that would violate it silently. It is a `throw` rather than an `assert` for the
usual reason: the sweep build is `-DNDEBUG`, and an assert compiled out turns a
violated floor into a plausible timeline.

`on_issue` carries the two matching checks, at the one place they could first
break: an issue for anything but the cursor, and an issue with lines of the
previous burst still outstanding (I16).

---

# Part IV. Plan unit C4: inclusion

## 17. Both branches, with counts

Take a two-core configuration whose **L2 holds exactly one line** and whose L1s
hold four, and this sequence:

| cycle | event | `inclusion = inclusive` | `inclusion = non_inclusive` |
|---|---|---|---|
| 110 | core 0's miss on `X` fills | `X` installed in the L2 and in L1(0) | identical |
| 300 | core 1's miss on `W` fills, and `W` maps to the L2's only set | `install` returns `evicted = true, evicted_line = X`; `back_invalidate(X)` scans both L1s, finds `X` in L1(0), invalidates it and calls `on_invalidate`; **`back_invalidations = 1`** | no scan; `X` stays in L1(0); **`back_invalidations = 0`** |
| 400 | core 0 accesses `X` again | L1 miss, L2 miss (`X` is gone from both), a full round trip: **110 cycles** | L1 **hit**: **0 cycles** |

That is V9 and V9b on one fixture. The `non_inclusive` hit at 400 is **correct**,
not an inflated hit rate, and it is the source of the extra effective capacity: the
machine holds `L2 + n_cores x L1` distinct lines (here `1 + 2 x 4 = 9`) rather
than roughly `L2` (here 1). v1 called the same hit a bug in three places; 4.4
corrected that, and the only argument left for inclusion in this study is that
`non_inclusive` sends a core to DRAM for a line a peer L1 holds, because peer-L1
forwarding is not modeled (2.6). Part 8 asks for that quantity by name, so the
argument is a measurement rather than a preference.

`on_invalidate` resets the slot's stamp to "never" (decision B96), so the freed
slot becomes the preferred victim again rather than sitting live in the recency
order.

## 18. Why `back_invalidations == 0` under `non_inclusive` is by construction

C4's exit criterion could be met by a run that happens not to evict. It is met
here by the call graph instead:

- `stats_.back_invalidations` is incremented at **exactly one site**, inside
  `Engine::back_invalidate`;
- `back_invalidate` has **exactly one call site**:

```cpp
if (res.evicted && params_.inclusion == Inclusion::Inclusive) back_invalidate(res.evicted_line);
```

So under `non_inclusive` the increment is unreachable, for any trace, any capacity
and any policy. That is a property a reader can check by grep in ten seconds, and
it is the difference between "the counter read zero in our fixture" and "the
counter cannot be nonzero on this branch". The code was already right at v2 time;
4.4 records that only the prose overreached.

Two smaller facts about the scan, both about the model's honesty rather than its
speed. It is the **widest inner loop in the model**, O(cores) per L2 eviction, at
most 256 arrays at the top of the sweep range, so it is a cost rather than a
scaling hazard. And it walks `l1_` **by core id over a vector**, because under LRU
an invalidation changes which slot is chosen next, so an unspecified scan order
would move victims (D7, D11).

The inclusion LRU pathology of G3 is present and unmitigated, which is realistic
and must be visible rather than incidental: `l2_policy.on_hit` fires only on an L2
probe hit, and L1 hits never reach the L2, so L2 recency is blind to lines that
are hot in some L1. That is exactly why an inclusive L2 evicts a line another core
is actively using. Nothing here mitigates it; Part 8 reports it.

---

# Part V. Plan unit C5: prefetching

## 19. `next_burst(d)`, walked at `d = 1` and `d = 2`

The policy is 4.6's pseudocode line for line. The state is one integer per core:

```cpp
void NextBurstPrefetcher::on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) {
    std::int32_t& cursor = pf_cursor_[core];
    const std::int32_t next = k.get() + 1;
    if (cursor < next) cursor = next;               // never behind the core

    const std::int32_t last    = k.get() + distance_;
    const std::int32_t n_burst = mem.n_bursts_in_tile(core);

    while (cursor <= last && cursor < n_burst) {
        if (!mem.issue_prefetch(core, BurstIndex{cursor}, now)) return;   // the BUDGET stops it
        ++cursor;
    }
}
```

A tile of four bursts, `n_bursts = 4`, with the budget never binding:

**`d = 1`**

| demand issue | `cursor` in | `last` | fetches | `cursor` out | `pf_cursor - cursor` |
|---|---|---|---|---|---|
| `k = 0` | 0 -> 1 | 1 | `b1` | 2 | 2 - 0 = 2 |
| `k = 1` | 2 | 2 | `b2` | 3 | 3 - 1 = 2 |
| `k = 2` | 3 | 3 | `b3` | 4 | 4 - 2 = 2 |
| `k = 3` | 4 | 4 | none (`4 < 4` is false) | 4 | 4 - 3 = 1 |

**`d = 2`**

| demand issue | `cursor` in | `last` | fetches | `cursor` out |
|---|---|---|---|---|
| `k = 0` | 0 -> 1 | 2 | `b1`, `b2` | 3 |
| `k = 1` | 3 (`max(3, 2)`) | 3 | `b3` | 4 |
| `k = 2` | 4 | 4 | none | 4 |
| `k = 3` | 4 | 5 | none | 4 |

Read out of the two tables:

- **every burst is fetched exactly once.** The `max(cursor, k+1)` line is what
  guarantees it: the cursor never goes backwards, so a burst already fetched is
  never fetched again, and a cursor that lagged would spend credits on lines the
  core has already asked for;
- **the tile boundary is never crossed**, because of `cursor < n_burst` and
  nothing else. The next tile's activations do not exist until the barrier
  resolves (4.6);
- **I14 holds with slack**: `pf_cursor - cursor` is at most 2 at `d = 1`, and its
  bound is `1 + prefetch_distance`;
- **the budget stops it, never a refusal** (N16). When `issue_prefetch` returns
  false the function `return`s **without advancing the cursor**, so the same burst
  is retried at the next demand issue, by which time its own fills have returned
  credits. That is why a partial burst is correct rather than a bug: the lines
  already in flight are dropped at their matching entries when the retry arrives.

## 20. The drop rules, and where each of the four is decided

4.6's four differences from a demand request, and the exact line that implements
each:

| at | a prefetch does | implemented by | why |
|---|---|---|---|
| array hit | **drop**, and do **not** touch replacement state | `if (at_issue) return DroppedArrayHit;` **before** `policy_->on_hit(slot)` | a prefetch is not a use; letting it promote recency would let the prefetcher rewrite LRU order |
| matching entry | **drop** | `if (at_issue) return DroppedEntry;` **before** the target-list bound | the line is already coming; nothing waits for this copy |
| no slot, or the reserve | **drop**, counted by reason | `free > 0 ? DroppedReserve : DroppedNoSlot` | keeps the wait population backed one-for-one by demand credits, which is 4.1's whole argument |
| otherwise | allocate with `demand = false` and forward | `MshrFile::allocate` | identical below this point |

`at_issue` is `is_prefetch_at_issue(r) = !r.demand && r.mshr1 == nullptr`, spelled
**once** in `mshr.h` and read by `has_slot`, by both wait pushes, and by
`triage`, so the four cannot drift into disagreeing about what a prefetch is.

Two guards make I15 unrepresentable rather than merely tested at the L1:
`push_line_wait` and `push_slot_wait` **throw** on a prefetch at issue, and the
engine's drop path decrements `pf_outstanding` and releases the request, so a
dropped prefetch cannot leak a credit. The engine counts the four reasons
separately because Part 8 asks for drops "broken out by reason", and a single
`Dropped` would make that a statistic nobody can recover.

**What the drop rule does not cover is the L2**, and that is open question P1.

## 21. `on_tile_start`: the hook the plan describes but never names

4.6 states the **behaviour** ("the policy never crosses a tile boundary... the
first burst of every tile is never prefetched") and gives an interface with
exactly one call, `on_demand_issue`. There is no hook for a tile start, and
without one the cursor is carried across the barrier, because nothing else ever
writes it downwards.

That is not cosmetic. Take a core whose tile 0 has **8** bursts and whose tile 1
has **12**, at `d = 1`:

| | with `on_tile_start` | without it |
|---|---|---|
| `pf_cursor` at the end of tile 0 | 8 | 8 |
| `pf_cursor` at tile 1's first demand issue (`k = 0`) | reset to 0, then `max(0, 1) = 1` | `max(8, 1) = **8**` |
| loop condition `cursor <= k + d` | `1 <= 1`, fetches `b1` | `8 <= 1` is false, **fetches nothing** |
| bursts 1 through 7 of tile 1 | fetched, one per demand issue | **never fetched at all** |
| when prefetching resumes | immediately | at `k = 7`, when `k + d` finally reaches 8 |

So the failure is silent and asymmetric: it costs nothing when tiles shrink, and
it silently loses **every burst of the next tile below the carried cursor** when
they grow. Nothing in the statistics announces it either, because the lost fetches
were never issued: coverage simply reads lower, which looks like a workload
property rather than a bug.

```cpp
void NextBurstPrefetcher::on_tile_start(CoreId core) { pf_cursor_[core] = 0; }
```

`start_tile` calls it for every core, beside the cursor reset for the core itself.
`NoPrefetcher` implements it as an empty body, so the engine has one code path.
The hook is on the abstract `Prefetcher`; carried as a plan gap in section 25.

## 22. What prefetching costs, in this run

4.6 lists four costs and Run W shows three of them:

- **L1 port slots.** One cycle of `core_stall` on burst 3 (section 14), because at
  `l1_ii = 1` every prefetch takes a cycle the demand stream could have used;
- **L1 MSHR credits**, held across full round trips: `E1y0` was live from cycle 1
  to 221, 220 cycles for a line the core asked for at 111;
- **L2 bank slots and DRAM bandwidth pulled earlier**: the `Y` prefetch took the
  bank at cycle 2 and then a wait-index slot at 12;
- **L1 capacity** is the fourth, and Run W's L1 is too large to show it. It is the
  right-hand column of 4.6's table, the prefetched line evicted before use, and it
  is not hypothetical: it is what the policy does under L1 pressure, which is the
  regime the study cares about.

The gain is 4.6's middle column, which this run does not reach because its single
L2 credit binds first: 110 cycles saved when the prefetched line is resident by the
time the core asks. That column is also a live test of the class order, since the
prefetch fill and the demand probe both land at cycle 111 and only "class 0 before
class 2" makes it a hit (V23).

The budget and the reserve are **two different bounds** and both are reported:
`pf_budget_exhausted` says the prefetcher stopped itself, a `DroppedReserve` says
the file stopped it. Which one dominates is what tells you whether
`prefetch_distance` or `l1_mshrs` was the binding constraint (4.2), and at
`l1_mshrs = lines_per_burst` the budget is exactly zero and prefetching is off no
matter what the distance says.

---

# Part VI. The batch as a whole

## 23. The A3 dependency: `trace.h` is a stand-in, and what A3 must implement

Plan unit A3 does not exist. The plan's own critical path says "C3 cannot finish
without A3's burst lists", so plan unit C3 is built against an **abstract**
`TileTrace` that names exactly the query surface A3's Part 7 row promises, and A3
implements it over the real corpus. This is the same split A2 already uses,
`AddressMapper` in `layout.h` against `BlockPackMapper` in `block_pack.h`
(decisions B10, B23): the engine holds the abstraction and never learns which
trace reader it has, which is also why the reviewer can drive a whole engine run
from a hand-written trace with no corpus file.

**What A3 must implement**, exactly:

| member | contract |
|---|---|
| `n_tiles()`, `n_cores()` | the barrier is machine-wide (N4), so every core walks the same tile sequence and `n_cores` is a property of the trace |
| `n_bursts(core, tile)` | count per `(core, tile)`. **Zero is legal** and the engine handles it (section 15) |
| `burst(core, tile, k)` | the `Burst` itself, by reference, in **trace order**, which is also service order (I13). Precondition `0 <= k < n_bursts` |
| `local_tick(core, tile, k)` | the trace's tick as an **offset inside the tile**. The engine reads it for `k == 0` only |
| `gap(core, tile, k)` | `local_tick(k+1) - local_tick(k)`, a **difference**, never an absolute. Precondition `0 <= k < n_bursts - 1` |
| `tile_tail(tile)` | `mac_cycles[tile] - max_tick[tile]`, **`>= 1` by construction** (Q10) |

Four obligations ride along with it, all already on `PROGRESS.md` rows:

1. decode the on-disk tuple by **header-declared field order**, never positionally,
   and throw on a malformed header (N11);
2. emit **only tile-local offsets**. Part 5 keeps one clock by removing absolute
   trace time from the design, not by typing it: an absolute tick typed as
   `LocalTick` would flow through `SimTime + LocalTick` with no compile error, and
   would produce a plausible timeline in which stalls are absorbed rather than
   carried, which is precisely D13;
3. report the count of `gap == 0` pairs, which must be **zero** for V20's shift to
   be exact. The engine does not assume it, because `max(gap, core_accept_ii)`
   advances the clock either way;
4. report the `tile_tail` histogram, since it is 0 across most of the corpus and
   20 on all 64 tiles of ptb `layer_01` and `layer_03`.

Until A3 lands, **every engine number in this tree comes from a hand-written
trace**, and that is the first thing to remember when reading any figure below.

## 24. Honesty: what is verified, and what was observed once

Three numbers were reported during implementation that **cannot be reproduced from
the tree**, because the smoke fixtures that produced them were not left in it.
They are listed with what survives and what does not, because the difference
matters more than the numbers.

**1. `tile_origin = 0, 3, 6`.**
*Verified:* the **identity** `tile_origin[N] == tick_base[N]` on the unbounded
baseline. It is confirmed independently, by `oracle_tile_origin` in the reviewer's
`engine_fixture.h`, which recomputes the origins from the trace and Part 5's
recurrence alone and never calls the engine.
*Not verified:* the triple `0, 3, 6`. No fixture in the tree produces those tiles.
Treat them as an anecdote about a fixture that no longer exists.

**2. `345 -> 238 -> 131`** for prefetch distances 0, 1, 2.
*Verified:* the **content**, a strictly monotone reduction as the distance grows.
*Not verified:* the three numbers. The reviewer's own oracle-pinned fixture gives
**`621 -> 342 -> 291`** for the same shape of run. What differs is the fixture
(trace, capacities, latencies), not the engine, and neither triple is a property of
the model. Any figure quoting cycles saved by distance must name the configuration
that produced it.

**3. The `4x` inclusive cycle cost.**
*Verified:* the **branch split** is exact. Both branches run, `back_invalidations`
is zero under `non_inclusive` by construction (section 18) and positive under
`inclusive`, and the induced L1 misses are counted.
*Not verified:* the factor. `4x` came from a fixture whose L2 held one line, which
maximises the effect by construction; a soak shows **1.07x**. The direction is a
result; the magnitude is a property of that fixture.

**The standing rule this batch is the occasion for: smoke evidence in a scratchpad
is not evidence.** A number that survives into a document must be reproducible from
something in the tree, which means a committed fixture with an oracle, not a
terminal buffer. The verified counts for this batch (checks, compile cases,
mutation cases and survivors) live in `PROGRESS.md`'s Tested column; this file
quotes none, deliberately.

## 25. Open questions

**Two block the study's reporting and need your ruling (P1 and P2). The rest are
carried or are plan slips to correct.**

---

### P1. A prefetch refused at the L2 has no defined outcome, and the obvious one deadlocks

**The contradiction.** 4.6's refusal table is written for a request at issue, and
its last row says the path is "identical below this point, **including at the L2,
where `l2_demand_reserve` applies the same way**". I15 says a `demand == false`
request "is never on a wait index". Both cannot hold: a forwarded prefetch the L2
refuses has to go somewhere, and the plan offers only "drop" and "wait".

**Drop at the L2 deadlocks, and this is proven rather than feared.** A forwarded
prefetch **holds an L1 MSHR entry** (I6: `r.level == L2 <=> r.mshr1 != null`), and
it holds it across the whole downstream round trip, which is what 4.1's entire
argument rests on. Drop the request at the L2 and that L1 entry is abandoned:

1. nothing will ever fill it, because the only path to `retire` is a fill and the
   only path to a fill is a forward that no longer exists;
2. the core's later demand for the same line **finds that entry** and merges onto
   it (or line-waits on it), so its burst never completes;
3. `pending_lines` never reaches zero, no further `E_Issue` is scheduled, the
   queue empties, and the run ends at D12's deadlock check.

The invariants forbid the alternative of letting it wait *without* being on a wait
index, so there is no third behaviour available inside the plan as written.
`on_l2_probe` refuses this state explicitly rather than implementing it.

**The resolution taken: the drop rules apply at the L1 only.** One predicate,
spelled once: `is_prefetch_at_issue(r) = !r.demand && r.mshr1 == nullptr`. A
prefetch at the L1 has nothing behind it and must be dropped; a prefetch at the L2
has exactly the backing 4.1 asks for and is treated as any other request.

**Two consequences to state plainly.**

- **`l2_demand_reserve` is now INERT.** Every request the L2 sees holds an L1
  entry, so `is_prefetch_at_issue` is false there, so `has_slot` always takes the
  `free > 0` branch and the reserve is never consulted. It is a 2.5b config field
  (default `lines_per_burst`) with no effect on any run. D1 should either drop it
  or document it as inert; leaving it in the results table implies a knob that is
  not one.
- **The resolution VIOLATES I15 and V28 as literally written.** A forwarded
  prefetch **can** sit on an L2 wait index: Run W reaches it at cycle 12, and a
  test reaches it in four bursts. I15 holds **exactly at the L1** and nowhere else.

**What is wanted from you**, one of two:

1. **amend I15, V28 and 4.6 to say "at issue"** (which is what the code does, and
   what Part 8 already implies when it asks for drops "refused at issue, broken out
   by reason"); or
2. **reject the resolution and specify a third outcome at the L2**, which must say
   what happens to the abandoned L1 entry: cancelling it needs a path that does not
   exist, and re-forwarding it is the wait this rule was meant to forbid.

---

### P2. `core_stall` and `fetch_latency` are equal by construction, so their difference measures nothing

Part 8 says of these two: "with prefetching on, their **difference is the latency
the policy hid**, and it is the single number the policy should be judged on."

**That number is identically zero, under every policy, in every run.** The proof is
four lines of `serve` and `on_issue`:

```
serve:      want = (cursor == 0) ? tile_origin[tile] + local_tick(c, 0)
                                 : served_time + max(gap_{k-1}, core_accept_ii)
serve:      schedules E_Issue(c, cursor) at  now + max(gap_k, core_accept_ii)   // now == served_time
on_issue:   issued_at = now
```

The next burst is issued at exactly the cycle `want` will be computed from, and the
first burst of a tile is issued at exactly `tile_origin + local_tick(c, 0)`, which
is that burst's `want`. So `issued_at == want` **term by term**, and therefore

```
core_stall[c]  = sum over k of (served - want)  ==  sum over k of (served - issued_at) = fetch_latency[c]
```

Run W's four terms are `(110, 110)`, `(110, 110)`, `(0, 0)`, `(1, 1)` (section 14):
equal in every row, including the row where a prefetch was outstanding for 220
cycles. A test in which a prefetch demonstrably hid **330 cycles** reports a
difference of **0**.

**Why, structurally.** Prefetching moves the *fetch* earlier and never the *ask*.
`issued_at` is the ask and `want` is also the ask, so any latency the policy hides
shortens both by the same amount. The two quantities are a genuine consistency
check (they must be equal, and a divergence means the recurrence was violated),
which is worth keeping. What they are not is a policy metric.

**Two candidates, recorded rather than chosen**, because the choice is D2's:

1. **`fetch_latency` against the `d = 0` baseline of the same configuration.** A
   cross-run difference. Q13's grid already runs `d = 0` once per `l1_mshrs` value
   as the demand-only reference, so the baseline exists by construction and costs
   nothing extra. It measures what was asked for, but only per configuration, not
   per burst;
2. **`served - fill_time` per burst.** An in-run number: how long the line sat
   resident before the core took delivery. Part 8 already asks for the distribution
   of `fill - served` and calls its zero bin "the fetch that did not make it in
   time", so this is the same quantity with its sign settled. It needs a field the
   engine does not carry today, the fill time per line.

Either way, **the Part 8 sentence needs correcting**, because as written it names
a quantity that is identically zero.

---

### Plan slips found by this batch, each needing a text correction rather than a ruling

**The "seven handlers" slip.** Part 7's C2 row says "*(v3: seven)* The seven event
handlers". 3.1 says six event kinds, "unchanged in number by v3", that "C2 adds no
event kind", and that service is "a call inside `E_L1Fill`, not a scheduled
event". **Six is right** and six are built. The row appears to have counted
service as a seventh handler.

**V26 is unreachable as specified.** V26 asks for a fixture where "a core's last
burst of a tile fills in the same cycle the barrier would resolve", to check that
the class 0 service lands before the class 1 barrier. It cannot be built:
`barrier_arrive` schedules `E_Barrier` at `now + tile_tail`, and `tile_tail >= 1`
by construction (Q10), so the barrier event is **always at least one cycle after**
the last service that scheduled it. The class ordering it tests is real and is
load-bearing for other reasons; the fixture as specified needs either
`tile_tail = 0` to be legal or a different construction, and V26 should be
restated.

**V27's closed form holds only under an extra assumption.** V27 says that at
`l1_latency = 1`, `tile_origin[N] - tick_base[N]` equals the sum over earlier tiles
of that tile's **maximum per-core burst count**. Under the self-timed recurrence
each burst costs one extra cycle, so core `c`'s last service shifts by
`n_bursts(c)`, and the tile's origin shifts by
`max_c (last_tick(c) + n_bursts(c)) - max_c last_tick(c)`. That equals
`max_c n_bursts(c)` only when the **same core attains both maxima**. A
counterexample in two cores: core A has 10 bursts at ticks 0..9, core B has 2
bursts at ticks 0 and 20. Baseline tile end 20; at `l1_latency = 1` core A ends at
19 and core B at 22, so the drift is **2**, not 10. The corpus's density (one burst
per tick, Q11) makes the two maxima coincide, so the closed form is right **on this
corpus**; it should say so.

**V22 is unbuildable as written.** It asks that `prefetch_policy = none` give "a
byte-identical event log **against the pre-C5 engine**". There is no pre-C5 engine:
under B74's batching, C5 landed in the same batch as C2 and C3, so no earlier
engine binary or recorded log exists to diff against, and the event log itself is
D2's, not built yet. The property is real and is worth keeping (`NoPrefetcher` is a
real class with an empty body rather than a null pointer the engine tests, so the
engine has one code path either way). The fixture needs restating as something
buildable: either a recorded log taken now and pinned, or a comparison of the two
policies' logs with prefetch events filtered out.

**`on_tile_start` is missing from 4.6's interface.** 4.6 gives `Prefetcher` exactly
one call and states the tile-boundary behaviour in prose. The behaviour is not
reachable without a second call, and its absence loses whole bursts silently
(section 21). 4.6's interface block wants the second line.

---

### Carried, unchanged by this batch

- **U17**, the `on_evict` plan defect: 2.2 lists four verbs, 3.4 line 619 calls a
  fifth, after `on_fill` and on the same slot. Still open, still needs you, and now
  has its second call site (`CacheLevel::install`) written against 2.2's four.
- **`Request::seq`** (decision B125): plan 3.3 lists it, nothing in Part 3 reads
  it, and the load-bearing `seq` is the event's. Either rule that it exists and say
  what reads it, or rule that 3.3's field is dead and correct the plan text. Phase
  C added no reader for it.
- **The plan's Q2 plausibility bound** (representability versus plausibility),
  deferred to **D1** with one shared bound rather than several scattered ones
  (decision B80). **Phase C found no fifth site**: the engine's own allocations are
  bounded by the config values D1 will bound, and the arena grows with outstanding
  requests, which the credit supply already bounds.
- **U12** (which tier wins when a burst is both malformed and out of range),
  **U13's sibling** (the validation order at the front of `expand`, tested but
  stated nowhere), **U14** (does `locate` owe a check on `num_sets`), and **U15's
  general count bound**. None is touched by this batch and none blocks Phase D.

---

**Summary of what wants your attention.** P1 is a genuine hole in the plan that the
code had to fill to run at all, and the fill is visible in two places you will
otherwise read as bugs: an inert `l2_demand_reserve`, and a prefetch on an L2 wait
index that I15 forbids. P2 is worse in a quieter way: Part 8 names a headline
number that is provably zero, so the prefetch study currently has no metric for the
thing it exists to measure, and picking the replacement is a D2 decision that
should be made before the grid runs. The five plan slips are text corrections. The
carried four block nothing.
