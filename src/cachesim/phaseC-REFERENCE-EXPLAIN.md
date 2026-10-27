# REFERENCE: Phase C, construct by construct

**What this file is.** A per-construct reference for Phase C: one entry for every
public class, struct, enum and function the phase ships, organised by file and
then by construct. It is the answer to "explain the code function by function,
class by class, struct by struct". It is not a narrative.

**What it is not.** `phaseC-EXPLAIN.md` sits alongside it and stays: that file is
the narrative record, built around one worked run ("Run W") walked end to end.
Where a number below is illustrative, it is the same Run W number, redistributed
to the construct it actually illustrates. Nothing here supersedes that file; the
two are the same batch read two ways.

**Erasable, like every EXPLAIN in this tree.** The durable record is
`PROGRESS.md`. The C++ language mechanics behind these constructs are
`CPP_NOTES.md` section 27 and are not repeated here.

---

## Phase C is FIVE plan units, not three

The board's critical path reads `... -> B3 -> C1 -> C2 -> C3`. That is the
critical path *through* the phase, not the phase. Plan Part 7's Phase C table has
five rows, and all five are built (decision **B127**).

| plan unit | what it is | where it lives |
|---|---|---|
| **C1** | `CacheLevel` = array + policy + port + MSHR file, and `triage()` | `cache_level.h`, `cache_level.cpp` |
| **C2** | the event loop, the **six** handlers, `retire`/`reinject` with the re-entry rule | `engine.h`, `engine.cpp` |
| **C3** | tile barrier, `tile_origin`, the core state machine, the self-timed recurrence | `engine.h`, `engine_core.cpp` |
| **C4** | two-valued inclusion: back-invalidation under `inclusive`, and the `non_inclusive` path | `engine.cpp` |
| **C5** | `Prefetcher`, `none`, `next_burst(d)`, the `demand = false` triage and the drop rules | `prefetcher.h`, `prefetcher.cpp`, `engine_core.cpp` |

C4 and C5 are downstream of C3 in the dependency order, which is not the same as
being outside the phase. Reading the chain as the scope would have declared Phase
C finished with the inclusion branch and the whole prefetcher missing.

A sixth file, `trace.h`, is not a plan unit at all: it is the abstract stand-in
for the unbuilt plan unit **A3** (decision **B128**), and it gets its own entry
below because plan unit C3 is written against it.

## Three naming collisions, stated once

Three different things in this project are called C1, and two of them collide
with decision numbers as well. Nothing below is ever written bare.

| the string | reading 1 | reading 2 |
|---|---|---|
| **C1** | **plan unit C1**: `CacheLevel` and `triage()` (Part 7) | **v3 change C1**: the intra-tile core schedule, 4.5's self-timed recurrence |
| **C2** | **plan unit C2**: the engine loop and the six handlers | **v3 change C2**: the pipelined burst fetch, 4.6's prefetcher |
| **B3** | **plan unit B3**: `MshrFile` | **decision B3**: `RefusalOrder`'s `NONE` sentinel is `INT64_MAX` |
| **B1**, **B2** | plan units `Port` and `EventQueue` | decisions about the archive and about `Tagged` |

The cruel part: **v3 change C1 is implemented by plan unit C3, and v3 change C2
is implemented by plan unit C5.** The numbers were never meant to line up.
Conventions used throughout: "plan unit C2", "decision B99", "v3 change C1".

## Run W, the configuration every worked example below uses

| | value | why |
|---|---|---|
| cores | 2 | enough for one shared-line collision at the L2 |
| bursts | single-line, `gap = 1` between every pair, `local_tick(c, 0) = 0` | the corpus's shape (Q11: one burst per tick) |
| core 0, tile 0 | `b0 -> X`, `b1 -> Y`, `b2 -> Y`, `b3 -> X`, `mac_cycles = 4` | the repeats make two of the four prefetch drops reachable |
| core 1, tile 0 | `b0 -> X` | shares core 0's first line |
| L1, per core | 4 lines, `mshrs = 3`, `tgts_per_mshr = 2`, `demand_reserve = 1`, `ii = 1`, `latency = 0` | 2.5b's `l1_latency = 0`, `l1_ii = 1` |
| L2, shared | `mshrs = 1`, `tgts_per_mshr = 1`, `demand_reserve = 1`, `ii = 1`, `latency = 10`, `banks = 1` | one credit for the whole machine, which is what exercises the wait indices |
| DRAM | `ii = 1`, `latency = 100` | 4.6's worked example uses the same 110-cycle full miss |
| other | `l2_to_l1_latency = 0`, `core_accept_ii = 1`, `inclusion = non_inclusive`, `prefetch = next_burst(1)` | 2.5b defaults plus `d = 1` |

A full miss costs `0 + 10 + 100 = 110` cycles. **The miss spine every entry
refers back to is `0 -> 10 -> 110 -> 111`**: issued at 0, the L2 probe at 10, the
data back at 110 (the L1 fill and the service both land at 110, because
`l2_to_l1_latency = 0`), and the core's next issue at 111.

Every engine number in this tree comes from a hand-written trace, because plan
unit A3 does not exist yet. That is the first thing to remember when reading any
figure below, and it is why the honesty note at the end exists.

---

# `native/include/wcache/trace.h`

## `TileTrace`

**What it is.** An abstract, read-only query surface over the per-`(core, tile)`
burst lists, and the whole interface half of the unbuilt plan unit A3. One
instance serves a whole run. Seven pure virtual functions, no `.cpp` file, and
nothing in the library implements it: the fixtures implement it now, plan unit A3
implements it later over the real corpus.

**Contract.**

```cpp
class TileTrace {
public:
    virtual ~TileTrace() = default;
    virtual std::int32_t n_tiles() const = 0;
    virtual std::int32_t n_cores() const = 0;
    virtual std::int32_t n_bursts(CoreId core, std::int32_t tile) const = 0;
    virtual const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
    virtual LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
    virtual LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
    virtual LocalTick tile_tail(std::int32_t tile) const = 0;
protected:
    // copy control protected and defaulted (decision B67's rule, third use)
};
```

| member | promises | precondition |
|---|---|---|
| `n_tiles`, `n_cores` | the barrier is machine-wide (N4), so every core walks the same tile sequence and `n_cores` is a property of the trace, not of a core | - |
| `n_bursts(core, tile)` | a count per `(core, tile)`. **Zero is legal**: a core that contributes nothing to a tile still has to clear the barrier | - |
| `burst(core, tile, k)` | the `Burst` by reference, in **trace order**, which is also service order (I13). Returned by reference because the engine hands it straight to `AddressMapper::expand` and never keeps it | `0 <= k < n_bursts(core, tile)` |
| `local_tick(core, tile, k)` | the trace's own tick as an **offset inside the tile**. The engine reads it for `k == 0` only; it is on the interface for every `k` because the diagnostic path wants the failing burst's tick (N11, V15) and because `gap` is defined from it | `0 <= k < n_bursts` |
| `gap(core, tile, k)` | `local_tick(k+1) - local_tick(k)`: a **difference**, a duration the core owes after the weights arrive, never an appointment it can be late for | `0 <= k < n_bursts - 1` |
| `tile_tail(tile)` | `mac_cycles[tile] - max_tick[tile]`, the compute the tile still owes after its last weight burst is served. **`>= 1` by construction** | - |

Refusals: none. The interface throws nothing; every precondition is the caller's,
and the engine satisfies all of them structurally.

**Worked example.** Run W's core 0, tile 0: `n_tiles() = 1`, `n_cores() = 2`,
`n_bursts(0, 0) = 4`, `n_bursts(1, 0) = 1`. Ticks are `0, 1, 2, 3`, so
`gap(0, 0, k) = 1` for `k` in `{0, 1, 2}` and `gap(0, 0, 3)` is out of contract.
`mac_cycles[0] = 4` and `max_tick[0] = 3`, so `tile_tail(0) = 1`.

**Decisions.** **B128** the abstract stand-in rather than blocking on plan unit
A3; **B10**/**B23** the same split `AddressMapper` versus `BlockPackMapper`
already uses; **B67** protected, defaulted copy control so `t1 = t2` through two
base references cannot slice.

**Traps.**

- **`tile_tail >= 1` is what makes the tile seam advance the clock.** A tile
  whose cores all issue nothing would otherwise leave the barrier firing at its
  own timestamp forever. It is also why V26 is unreachable as specified (**U21**).
- **An absolute tick typed as `LocalTick` compiles.** Neither the types nor the
  engine would catch a `gap` that returned an absolute trace tick; it would
  produce a plausible timeline in which stalls are absorbed rather than carried,
  which is exactly the defect D13 exists to close. Plan unit A3 owes tile-local
  offsets by discipline, not by type.
- **`gap == 0` is measured-absent, not assumed-absent** (Q11). The engine does
  not rely on it, since `max(gap, core_accept_ii)` advances the clock either way,
  but V20's exact shift does. Plan unit A3 owes the count of such pairs over the
  real corpus, and the fixture cannot discharge it.

---

# `native/include/wcache/cache_level.h` and `native/src/cache_level.cpp`

## `enum class TriageOutcome : std::uint8_t`

**What it is.** The nine things a triage can conclude: 3.7's five outcomes, plus
4.6's four prefetch drops. One enumerator per branch, so a missing case is a
compiler warning rather than a silent fall-through.

**Contract.**

```cpp
enum class TriageOutcome : std::uint8_t {
    Hit = 0, Merged = 1, BlockedTargets = 2, BlockedPool = 3, Forwarded = 4,
    DroppedArrayHit = 5, DroppedEntry = 6, DroppedNoSlot = 7, DroppedReserve = 8,
};
```

The five are "distinguished ONLY by what releases them" (3.7), and the two
collapses the plan warns about are **unrepresentable** rather than merely
avoided: `Merged` and `BlockedTargets` are separate although both wait on the
same entry; `BlockedPool` and `BlockedTargets` are separate although both are
"blocked". The four drops are separate because Part 8 asks for prefetch drops
"broken out by reason", and a single `Dropped` would make that a statistic nobody
can recover. Each names the step that refused, so the four partition the prefetch
path exactly once.

| enumerator | means |
|---|---|
| `DroppedArrayHit` | the line is already resident. **Not** counted as a hit and **not** reported to the policy: a prefetch is not a use |
| `DroppedEntry` | the line is already coming, so nothing waits for this copy. Subsumes 4.6's separate "targets full" row, because a prefetch is dropped at the matching entry one step earlier |
| `DroppedNoSlot` | the file is completely full |
| `DroppedReserve` | free entries remain but they are the demand reserve, which a prefetch may never take |

**Worked example.** Run W reaches all nine; see `CacheLevel::triage` below for
the table with cycles.

**Decisions.** **B129** nine outcomes; **B140**(2) one enumerator per branch;
**B11** a prefetch is not a use; **B12** the demand reserve a prefetch may never
take.

**Trap.** A prefetch can never produce `BlockedTargets`, because it is dropped at
the matching entry before the target-list bound is consulted. Reading the enum as
"nine independent possibilities at either level" is wrong: at the L2 only the
first five are reachable at all (see `Engine::on_l2_probe`).

## `constexpr bool is_dropped(TriageOutcome)`

**What it is.** True for the four 4.6 drops, false for 3.7's five.

**Contract.** `constexpr bool is_dropped(TriageOutcome o)`. Total, pure, never
throws. It is the test both the engine's counters and its request-lifetime rule
dispatch on: a dropped request is released here and now; anything else stays
alive and ends at an L1 retire.

**Worked example.** At Run W cycle 112 the `Y` prefetch returns `DroppedEntry`;
`is_dropped` is true, so `on_l1_probe` decrements `pf_outstanding` from 2 to 1,
bumps `pf_dropped_entry`, and releases the request.

**Decisions.** **B129** the outcome set this partitions.

**Trap.** Adding a tenth outcome without touching this function silently puts it
on the not-dropped side, where the engine will keep the request alive and expect
a fill for it.

## `struct LevelParams`

**What it is.** The config fields one level is built from (2.2, 2.3, 2.5b). A
plain struct with member initialisers and **no validation at all**.

**Contract.**

```cpp
struct LevelParams {
    std::int64_t cache_size_bytes = 0;
    std::int32_t associativity    = 1;
    PolicyKind   policy           = PolicyKind::LRU;
    SimTime      latency{0};
    SimTime      ii{1};
    std::int32_t banks           = 1;
    bool         bank_high_bits  = false;
    std::int32_t mshrs           = 1;
    std::int32_t tgts_per_mshr   = 1;
    std::int32_t demand_reserve  = 0;
};
```

Promises nothing and refuses nothing. Plan unit D1 owns "config load +
validation, single source of truth for the parameter set", so every rule of that
row (`lines_per_burst > l1_mshrs` throws, `demand_reserve >= mshrs` throws,
`policy = random` throws) belongs there. What the constructors reached *from*
this struct still refuse are their own preconditions, and all of them are throws
rather than asserts so they survive the sweep build's `-DNDEBUG`.

`ii = 0` is N13's escape hatch and is how the unbounded baseline of V1 is built.
`latency = 0` is 2.5b's default for `l1_latency` and is what makes a 100% hit run
reproduce the scratchpad timeline exactly.

**Worked example.** Run W's L1: `cache_size_bytes` for 4 lines,
`associativity = 4`, `latency = 0`, `ii = 1`, `banks = 1`, `mshrs = 3`,
`tgts_per_mshr = 2`, `demand_reserve = 1`. Run W's L2: `mshrs = 1`,
`tgts_per_mshr = 1`, `demand_reserve = 1`, `latency = 10`, `ii = 1`, `banks = 1`.

**Decisions.** **B140**(12-15) no validation here, D1 owns every rule, which is
decision **B80**'s one-shared-owner principle applied to the engine's parameters;
**B95** `make_policy` is what rejects Random.

**Trap.** At `banks = 1` the two settings of `bank_high_bits` are
indistinguishable **by construction**, so a fixture asserting bank behaviour must
set `banks >= 2` or it passes vacuously. Run W has `l2_banks = 1` and therefore
says nothing about banking.

## `class CacheLevel` (the class)

**What it is.** One level of the hierarchy: a set-associative array, a
replacement policy sized from it, one `Port` per bank, and an `MshrFile`. **One
class for both levels.** Plan 3.4 says the two triage functions are of "identical
shape", and they are: the only differences are what a `Hit` and a `Forwarded`
mean afterwards, and both of those are the engine's business, because both end in
scheduling an event (P4).

**Contract.** Members, and what each owns:

```cpp
Level level_;                               // read by triage for the re-entry rule only
const AddressMapper& mapper_;               // one mapper serves the whole hierarchy
std::unique_ptr<CacheArray> array_;         // geometry, no recency
std::unique_ptr<ReplacementPolicy> policy_; // recency, no geometry
std::vector<Port> ports_;                   // one per bank; the L1 is the banks = 1 case
MshrFile mshrs_;                            // plan unit B3
std::int64_t num_sets_; bool bank_high_bits_; std::int64_t sets_per_bank_;
std::vector<Candidate> candidates_;         // install's scratch, so a fill does not allocate
```

Move-only: the `unique_ptr` members delete the copy operations and the reference
member deletes both assignments. Nothing can reorder or remove a level, so
`l1_[c]` is core `c`'s L1 for the whole run by the type system rather than by
convention.

**What the class deliberately does not do**, and this boundary is the reason the
engine is testable at all: it never schedules an event, never touches another
level, and never touches a core.

**Worked example.** Run W builds three `CacheLevel`s: two L1s (4 lines each,
`banks = 1`) and one L2 (`banks = 1`), all sharing one `AddressMapper` and one
`RefusalCounter`.

**Decisions.** **B129** the composition; **B140**(1) `triage` returns rather than
schedules.

**Trap.** `candidates_` is per level and not per engine, because
`victim_candidates` **replaces** its out-parameter: two levels filling inside one
dispatch would otherwise interleave through one buffer.

## `CacheLevel::CacheLevel`

**What it is.** The constructor, and its order is load-bearing.

**Contract.**

```cpp
CacheLevel(Level level, const AddressMapper& mapper,
           const LevelParams& params, RefusalCounter& counter);
```

`mapper` and `counter` must outlive the level; one mapper serves the whole
hierarchy and one refusal counter serves the whole run, so both already do by
construction. Throws whatever the four constructors throw, **in the order they
run**:

1. `SetAssociativeArray`: `std::invalid_argument` for a geometry that is not a
   whole number of lines. Built as the **concrete** type first so `num_sets()`
   and `num_slots()` are read off it, then moved behind the abstract handle;
2. `make_policy`: `std::invalid_argument` for `policy = random`, sized from the
   array's slot count so a policy is never sized from a geometry the array
   refused;
3. the bank count: `std::invalid_argument` for `banks < 1`;
4. one `Port` per bank: `std::invalid_argument` for a negative `ii` or
   `latency`;
5. `MshrFile`: `std::invalid_argument` for a `demand_reserve` above capacity
   (constructed in the member-initialiser list, so in practice it runs first).

Then `sets_per_bank_ = max(num_sets_ / banks, 1)`, clamped so a set count smaller
than the bank count divides rather than dividing by zero.

**Worked example.** Run W's L2: the array is built and reports its set count; the
LRU policy is sized from the slot count; `banks = 1` passes; one `Port(ii = 1,
latency = 10)`; the `MshrFile(1, 1, 1, counter_)`.

**Decisions.** **B62** read the geometry off the concrete type; **B63** the
division is split precisely so `line_size_bytes * associativity` is never formed;
**B95** `make_policy` rejects Random rather than stubbing it.

**Trap.** Recomputing the set count from the config instead of reading it off the
array would be the same division written twice, in two places that can disagree
about a geometry the array has already accepted or refused.

## `CacheLevel::triage`

**What it is.** 3.4's triage, called on **first arrival and again on every wake**
(D4). The single most load-bearing function of plan unit C1.

**Contract.**

```cpp
TriageOutcome triage(Request& r, std::vector<Request*>& granted);
```

- performs **every state change 3.4 makes, in 3.4's order**, and returns which of
  3.7's or 4.6's outcomes happened;
- `granted` is an out-parameter that is **replaced, not appended to** (the callee
  clears it), and is non-empty only on the two outcomes that release a
  reservation, a grantee that re-triaged into a `Hit` or a `Merged`. The next
  waiter cannot be injected from here, because injecting reserves a port, so it
  is handed back for the engine to reinject;
- sets `r.mshr1` and `r.level` on a `Forwarded` **at the L1**, which is 3.5's
  re-entry rule written at the one place that knows the request has just taken an
  L1 entry. I6 pairs the two fields, so they are set together and nowhere else;
- refuses with `std::logic_error` a request that is already on a wait index (I5),
  before either wait push;
- carries the request's **original** refusal stamp untouched, which
  `mark_refused`'s write-once rule keeps true without this function doing
  anything (3.8).

Validation order, and it is the whole of Part 0's surviving verdict: **array,
then own-level MSHR, then the next level. Exactly gem5's order and exactly the
hardware's. Checking the MSHR file BEFORE forwarding is what makes a secondary
miss cost zero downstream traffic.**

The prefetch test is computed once at the top:

```cpp
const bool at_issue = is_prefetch_at_issue(r);   // !r.demand && r.mshr1 == nullptr
```

By I6 a request at the L2 holds an L1 entry, so `at_issue` is false there and the
four drop branches are **unreachable at the L2** ("identical below this point",
4.6's own last table row).

**Worked example.** All nine outcomes, at their Run W cycles. The last two need
one variant each, named in the row.

| # | cycle | level | request | what triage found | outcome |
|---|---|---|---|---|---|
| 1 | 0 | L1(c0) | demand `X`, burst 0 | array miss, no entry, `free = 3 > 0` | **`Forwarded`** |
| 2 | 11 | L2 | demand `X` from core 1 | array miss, entry `E2x` exists, targets full at `l2_tgts_per_mshr = 1` | **`BlockedTargets`**, stamped **0** |
| 3 | 12 | L2 | the prefetch for `Y`, already forwarded | array miss, no entry, `free = 0` | **`BlockedPool`**, stamped **1** |
| 4 | 111 | L1(c0) | demand `Y`, burst 1 | array miss, prefetch entry `E1y0` exists, `1 < tgts_per_mshr = 2` | **`Merged`**, entry promoted to `demand = true` |
| 5 | 112 | L1(c0) | prefetch for `Y` (burst 2) | array miss, entry `E1y0` exists | **`DroppedEntry`** |
| 6 | 120 | L2 | core 1's `X`, re-triaged after its wake | array **hit**: `X` installed at 110 | **`Hit`** |
| 7 | 223 | L1(c0) | prefetch for `X` (burst 3) | array **hit**: `X` resident since 110 | **`DroppedArrayHit`** |
| 8 | 224 | L1(c0) | demand `X`, burst 3 | array hit | **`Hit`** |
| 9 | variant, `d = 2` | L1(c0) | a prefetch arriving while `live = 2` | `free = 1`, and a prefetch needs `free > demand_reserve = 1` | **`DroppedReserve`** |
| 10 | variant, `demand_reserve = 0` | L1(c0) | a prefetch arriving while `live = 3` | `free = 0` | **`DroppedNoSlot`** |

Row 1 in full: `probe(X)` returns `NoSlot`; `find(X)` returns null; `has_slot`
computes `free = capacity(3) - live(0) - reserved(0) = 3` and the request is a
demand, so the test is `free > 0`. The entry is allocated with this request as
`targets[0]`, and then the two fields of 3.5 are set together.

Rows 9 and 10 differ by one comparison, and the reason is recoverable at exactly
this moment and nowhere later:

```cpp
const std::int32_t free = mshrs_.capacity() - mshrs_.live() - mshrs_.reserved();
return free > 0 ? TriageOutcome::DroppedReserve : TriageOutcome::DroppedNoSlot;
```

**Decisions.** **B129** classify and return, nine outcomes; **B140**(1) returns
rather than schedules; **B134** I5 refused here, at the only code that pushes
during a run and the only code with a level in hand; **B135** the wait pushes
narrowed their refusal from `!r.demand` to `is_prefetch_at_issue(r)`, which is a
real **widening** of what the file accepts; **B136** `collect_grants` made public
so this and the engine can re-run the grant loop; **B120** `release_reservation`
returns a `bool` rather than re-granting, because granting reinjects and
reinjection reserves a port; **B114** `add_target` refuses inside itself, so a
caller that checks the bound and pushes anyway cannot break I3; **B110** the
primary occupies the first target slot; **B11** a prefetch drops without calling
`on_hit`.

**Traps.**

- **`triage` CLASSIFIES and returns; the engine REACTS.** Plan 3.4 written
  literally puts `core_line_done(r, now)` inside `triage_L1` and
  `schedule(E_L2Probe(r), ...)` at the bottom of it, which reaches across two
  boundaries from inside a level. Here the level knows nothing of ports below it,
  of cores, or of the event queue: it reserves its own port never. That is why a
  fixture drives all nine outcomes with no clock, no queue and no core, and why
  plan unit C1's exit criterion is reachable as a unit test rather than only as a
  whole run. There is a correctness argument on top of the tidiness one: a
  callback would fire in the **middle** of `triage`, while the level's own state
  is half-updated.
- **Re-triage is the point, not an optimisation.** "Anything that waits
  re-triages from the top of its level when it wakes. It never acts on the
  classification it held when it blocked." Row 2 was classified
  `BlockedTargets` at 11 when the line was genuinely absent, and resolves as a
  `Hit` at 120 (V5). The mirror case, a queued hit whose line was evicted before
  service, is V6 and is the same mechanism.
- **An L1 `BlockedPool` for a demand request is unreachable at 2.5b defaults**,
  argued rather than measured: D1 rejects `lines_per_burst > l1_mshrs`, a core
  has one burst in flight, and a prefetch can never take the last
  `l1_demand_reserve` entries, so a demand line always finds `free > 0`. Real
  code, exercised by fixtures, inert on the grid.
- **`DroppedNoSlot` is unreachable at 2.5b defaults too.** A prefetch being
  triaged is itself counted in `pf_outstanding`, so live prefetch entries are at
  most `cap - 1`, live demand entries at most `lines_per_burst`, and the sum is
  at most `l1_mshrs - 1`. It becomes reachable only where D1 already warns: a
  `demand_reserve` below `lines_per_burst`.
- **Row 3 is the shape of open question U18.** A request with `demand == false`
  sitting on a wait index is what I15 and V28 forbid as literally written. See
  the open-questions section.

## `CacheLevel::install`

**What it is.** 3.4's `install`: free way first, only then the policy (D6).

**Contract.**

```cpp
InsertResult install(LineId line);
```

- refuses with `std::logic_error` when `line` is **already resident**. I1 makes
  that impossible (an entry exists for it only because a probe missed, and a
  second entry for one line cannot exist), and it is checked anyway;
- picks a free way first (`array_->free_slot`); only if there is none does it ask
  the policy (`victim_candidates` then `pick_victim`);
- inserts, then calls `policy_->on_fill(slot)`;
- **returns what was displaced**, because the caller needs it: under
  `inclusion = inclusive` an L2 eviction has to be back-invalidated out of every
  L1, and that scan is the engine's, because only the engine sees the other level;
- **does not call `policy.on_evict(slot)`**, which 3.4 line 619 calls after
  `on_fill(slot)` on the same slot. Not an oversight: **U17**.

**Worked example.** Run W cycle 110: `l2_.install(X)`. The L2 array has a free
way, so no candidate list is built and no policy `pick_victim` runs;
`on_fill(slot)` follows; `res.evicted` is false, so the inclusion branch in
`on_l2_fill` does nothing either way. In the inclusion fixture (see
`Engine::back_invalidate`) the same call at cycle 300 returns
`evicted = true, evicted_line = X`.

**Decisions.** **B138** the `on_evict` call is **not** made, the site carries a
comment naming U17, no fifth verb was invented, and the absence is **pinned by a
test** so a later edit that adds it goes red rather than quietly reordering every
victim choice; **B97** A5 built Part 2.2's four verbs and escalated the
contradiction; **B140**(10) `install` refuses a resident line rather than
overwriting it.

**Traps.**

- **Free way first is not an optimisation.** Folding the free case into the
  candidate list would oblige every policy to re-implement "prefer an empty way",
  and a policy that got it wrong would evict a live line while a way sat empty.
- **The resident-line check guards the failure this model can least afford.** A
  duplicate line in one set crashes nothing: every later probe finds one of the
  two copies, and the hit rate is quietly wrong for the rest of the run.

## `CacheLevel::bank_of`

**What it is.** Which bank port a line uses. Always 0 at the L1, which has one
port.

**Contract.**

```cpp
std::int32_t bank_of(LineId line) const;
```

Total, never throws. Returns 0 immediately at `banks == 1`. Otherwise the bank is
the **low** bits of the set index by default (`set % banks`) and the **high** bits
under `bank_high_bits` (`set / sets_per_bank_`), then **clamped** to `banks - 1`.
Q2, closed 2026-08-17: it stayed a knob because the two are opposite conflict
behaviours (low bits spread consecutive lines across banks, high bits keep a
contiguous run inside one), and which is right interacts with the
`cin_block` / `cout_block` sweep.

**Worked example.** Run W has `l2_banks = 1`, so every `bank_of` call in the run
returns 0 through the shortcut and the L2's single `Port` serves everything. That
is why the accepts at cycles 0, 1 and 2 for `X`(c0), `X`(c1) and `Y`(pf) are
consecutive: one port, `ii = 1`.

**Decisions.** **B140**(11) `bank_of` **clamps** rather than refusing, because a
bank index out of range is a configuration error D1 owns and refusing mid-run
would abort a sweep point; **B145** the mutation "`C1 bank_of` loses its
single-bank shortcut" was proven an **equivalent mutant** and reclassified `kill`
to `allow`.

**Traps.**

- **The comment at `cache_level.cpp:76-83` misdescribes the clamp.** It says
  every set lands in bank 0; the code makes the bank equal the set index, clamped
  at `banks - 1`. Reported and deliberately not fixed by the Phase C batch;
  carried as an obligation.
- **`banks = 1` makes bank behaviour vacuous.** A fixture that asserts anything
  about banking at Run W's L2 passes without testing.

## `CacheLevel` accessors

**What they are.** `level()`, `array()` (mutable and const), `policy()`,
`mshrs()` (mutable and const), `port(bank)`, `banks()`, `num_sets()`.

**Contract.** Plain forwarding. `port(bank)` is `ports_.at(bank)`, so an
out-of-range bank throws `std::out_of_range` rather than reading memory it does
not own, which is the safety net under `bank_of`'s clamp. `num_sets()` is read
off the array at construction rather than recomputed, so the set count the
banking uses is by construction the one the array actually has.

**Worked example.** `on_l1_probe` reaches `lvl.port(0).reserve(now)`;
`issue_prefetch` reaches `lvl.mshrs().capacity() - lvl.mshrs().demand_reserve()`
= `3 - 1 = 2` for Run W's L1.

**Decisions.** **B129** the composition these expose.

**Trap.** They hand out **mutable** references to the array, the policy and the
MSHR file, so nothing at the type level stops a future handler from mutating a
level outside `triage` and `install`. Reported and deliberately not fixed; it is
the same posture as `Engine::l1()` / `l2()` below.

---

# `native/include/wcache/engine.h`, `native/src/engine.cpp`, `native/src/engine_core.cpp`

## `enum class Inclusion : std::uint8_t`

**What it is.** `NonInclusive = 0`, `Inclusive = 1`. Plan unit C4's knob.

**Contract.** Two values. `exclusive` is deliberately **not** offered (G1, Q7).

**Worked example.** Run W runs `NonInclusive`; the inclusion fixture in
`back_invalidate` below runs both.

**Decisions.** **B132** the branch this guards.

**Trap.** It is a **knob and not an invariant**: "inclusion has no job in this
study", since weights are read-only and there are no invalidations to filter, so
the tradeoff is effective capacity against guaranteed L2 hits on peer-L1-resident
lines, and it is a result to report rather than a correctness setting.

## `enum class Phase : std::uint8_t`

**What it is.** 3.3's `CoreState.phase`: `Computing`, `Stalled`, `AtBarrier`,
`Done`.

**Contract.** A **state** field, not a time field. 2.1 argues this at length: at
the instant a core is refused you must record **that** it is stalled, and when it
resumes is unknowable then. A single `ready_time` cannot express "waiting, resume
time unknown", and that representational gap is what forced D2's polling in v2.
v3 removes `ready_time` outright.

**Worked example.** Run W, core 0: `Computing` at tile start, `Stalled` from
cycle 0 (`on_issue`), back to `Computing` at 110 (`serve` schedules the next
issue), and `AtBarrier` at 224 when the cursor reaches `n_bursts = 4`. Core 1 is
`AtBarrier` from 120 and waits 104 cycles.

**Decisions.** **B131** the state machine it belongs to.

**Trap.** I16 pairs it with a count: `pending_lines > 0 <=> phase == Stalled`.
Setting one without the other is unrepresentable only by discipline.

## `struct CoreState`

**What it is.** 3.3's per-core record, revised by v3. `ready_time` is gone.

**Contract.**

```cpp
struct CoreState {
    std::int32_t tile = 0;
    BurstIndex   cursor{0};      // the ONE burst the core is on, in trace order, always
    Phase        phase = Phase::Done;
    std::int32_t pending_lines = 0;
    SimTime      issued_at{0};
    SimTime      served_time{0}; // served(c, cursor - 1)
};
```

`cursor == 0` **is** 3.3's "`served_time` is NONE at a tile start": the cursor is
reset at every tile start and advanced at every service, so the two are the same
state. One field carrying its own validity cannot disagree with a second field
that says whether it is valid, and it is why the service floor stops at the tile
seam without anything having to clear it.

**Worked example.** Run W, core 0, immediately after the cycle-110 service:
`tile = 0`, `cursor = 1`, `phase = Computing`, `pending_lines = 0`,
`issued_at = 0`, `served_time = 110`.

**Decisions.** **B131** the state machine; **B140**(3) `cursor == 0` instead of a
sentinel, because a sentinel would be an eleventh tagged-scalar special value to
keep in sync and zero is already meaningful; **B89** the same shape decision that
made `InsertResult::evicted` unrepresentable-when-invalid.

**Trap.** There is **one** cursor here and one `pending_lines`, because the core
has one burst in flight under **every** policy. The second cursor lives in the
prefetcher, on the other side of the L1 port. Keeping them in separate structs is
not tidiness: it is the statement that the PE is unchanged, checkable by the fact
that no field here mentions prefetching.

## `struct EngineStats`

**What it is.** The quantities Part 3's own pseudocode writes by name, and
nothing else.

**Contract.**

```cpp
struct EngineStats {
    std::vector<std::int64_t> core_stall;      // per core
    std::vector<std::int64_t> fetch_latency;   // per core
    std::int64_t back_invalidations = 0;
    std::int64_t pf_budget_exhausted = 0;
    std::int64_t pf_dropped_array_hit = 0, pf_dropped_entry = 0,
                 pf_dropped_no_slot = 0, pf_dropped_reserve = 0;
    std::vector<std::int32_t> pf_outstanding;  // per core
};
```

- `core_stall[c] = sum over k of served(c, k) - want(c, k)`, the cycles the core
  waited past its **own** self-timed schedule, which is the quantity that
  integrates to the tile stretch (V21);
- `fetch_latency[c] = sum over k of served(c, k) - issued_at(c, k)`, the memory
  system's latency for the same bursts;
- `pf_outstanding` is held here rather than in the prefetcher because it is a
  **cache credit** and not policy state (3.3's `PrefetchState` is memory-side).
  It is I14's second half, `pf_outstanding(c) <= l1_mshrs - l1_demand_reserve`.

Part 8 asks for far more than this (occupancy histograms, per-bank
utilisation, the timely/late/wasted/dropped split, the stall breakdown by
cause), and all of it is plan unit D2's.

**Worked example.** Run W, at the end: `core_stall[0] = 110 + 110 + 0 + 1 = 221`,
`fetch_latency[0] = 110 + 110 + 0 + 1 = 221`, `back_invalidations = 0` (the run
is `non_inclusive`), `pf_dropped_entry = 1` (cycle 112),
`pf_dropped_array_hit = 1` (cycle 223), `pf_outstanding[0] = 0` at the end.

**Decisions.** **B131** the counters `serve` writes; **B129** the drop set
counted by reason.

**Traps.**

- **`core_stall` and `fetch_latency` are equal by construction under every
  policy**, so their difference, the number Part 8 calls "the single number the
  policy should be judged on", is identically zero. That is **U19**, and it is
  the most consequential open item in the phase. See the open-questions section.
- **`pf_dropped_*` are global rather than per core**, which plan unit D2 will
  want split. Reported and deliberately not fixed by this batch.

## `struct EventPayload` and `using EngineQueue`

**What it is.** What an event is *about*: one struct rather than a variant, in
the tree's plain-struct style. `EngineQueue` is `EventQueue<EventPayload>`.

**Contract.**

```cpp
struct EventPayload {
    Request*     req   = nullptr;
    Mshr*        entry = nullptr;
    BurstIndex   burst{0};
    std::int32_t tile  = 0;
};
```

Each kind reads one field and the rest are inert: `Issue` reads `burst` plus the
key's `core`; `L1Probe`/`L2Probe` read `req`; `L1Fill`/`L2Fill` read `entry`;
`Barrier` reads `tile`. Both pointers are **borrows**, valid for the interval
between `schedule` and `dispatch`.

**Worked example.** Run W cycle 110's `L2Fill` carries
`{nullptr, &E2x, burst 0, tile 0}`; the `Barrier` event carries
`{nullptr, nullptr, 0, 0}` under `CoreId{0}`.

**Decisions.** **B140**(6) the core is read out of the **key**, not duplicated
here, so two spellings of one core id cannot disagree, the same rule as decision
**B112**; **B107** the event `seq` that makes the key total.

**Trap.** The barrier is the one event with no core. It is scheduled under
`CoreId{0}` and nothing reads that field, since only one barrier event exists per
tile and there is no tie for it to break. Reading it as "the barrier belongs to
core 0" is wrong.

## `struct EngineParams`

**What it is.** The knobs the engine reads. A plain struct with **no validation**,
deliberately.

**Contract.**

```cpp
struct EngineParams {
    LevelParams l1, l2;
    SimTime l2_to_l1_latency{0};
    SimTime dram_ii{1};
    SimTime l2_miss_latency{0};
    SimTime core_accept_ii{1};
    Inclusion inclusion = Inclusion::NonInclusive;
    PrefetchKind prefetch_policy = PrefetchKind::None;
    std::int32_t prefetch_distance = 0;
};
```

Plan unit D1 owns every cross-field rule its row names: `lines_per_burst >
l1_mshrs` throws, `inclusion = exclusive` is rejected, `core_accept_ii < 1`
throws, `prefetch_policy = next_burst` with `prefetch_distance = 0` throws,
`demand_reserve >= mshrs` throws, and a prefetch budget below `lines_per_burst`
warns. Duplicating any of it here would be the second source of truth that row
exists to prevent.

`l2_to_l1_latency` is its own knob with default 0, so D10's split between "the L2
MSHR frees" and "the core finishes" stays **structural** and reopens by setting it
nonzero (Q3, closed). `dram_ii` is what lets requests pipeline: a channel with
100 cycles of latency and `ii = 2` has 50 requests in flight, and `ii = latency`
recovers the non-pipelined case from the same structure. `core_accept_ii` is 4.5's
floor and its value is 1; it sits in the config rather than the source for D8's
reason, that a structural constant nobody can find is a structural assumption.

**Worked example.** Run W: `l2_to_l1_latency = 0`, `dram_ii = 1`,
`l2_miss_latency = 100`, `core_accept_ii = 1`, `inclusion = NonInclusive`,
`prefetch_policy = NextBurst`, `prefetch_distance = 1`.

**Decisions.** **B140**(12-15) no validation, D1 owns every rule; **B126** N13's
`ii = 0` warning is D1's, once per config, not `Port`'s constructor's.

**Trap.** `core_accept_ii` is also the **termination guard** of 2.5b: with
`l1_latency = 0` an all-hit chain issues, probes and serves inside one timestamp,
and `max(gap_k, core_accept_ii)` is the only thing advancing the clock. Setting
it to 0 in a fixture does not merely change timing; it can stall the run inside
one cycle.

## `class Engine` (the class)

**What it is.** The event loop, the six handlers, the core state machine, the
inclusion branch, and the sink half of the prefetcher interface. Plan units C2,
C3, C4, and C5's sink. `final`, and publicly derived from `PrefetchIssuer`.

**Contract.** The loop is 3.2 and nothing else:

```cpp
while (!queue.empty()) { e = queue.pop_min(); now = e.time; dispatch(e); }
```

There is no tick, no horizon, no scan over cores, and no condition re-evaluated
on a schedule. A stalled core has **no scheduled event at all**: it is referenced
by the structure it waits on, and that structure schedules its wake-up (D2, P2).
`now` is `e.key.time` and is monotonically non-decreasing because the queue is a
min-heap; there is no `now_` member for a handler to advance by hand.

One class, **two `.cpp` files**: `engine.cpp` is the loop, the memory-side
handlers and inclusion (plan units C2 and C4); `engine_core.cpp` is the core side
and the prefetch hook (plan unit C3, and C5's sink). The split mirrors the plan's
own between 3.4 and 3.4b.

Determinism rests on three structural properties, none of them a test:

1. **the event key is total**, so no two events tie: `seq` is unique across the
   run, so the heap's internal arrangement is unobservable;
2. **nothing iterates an unordered container**: `MshrFile::entries_` is an
   `unordered_map` and every read of it is a lookup by line or a `size()`; the
   one O(cores) loop in the whole model walks a **vector** by core id;
3. **port reservations are non-preemptive**, so reserve order is service order.
   `Port::reserve` never refuses and is never released.

That matters more than it sounds: under LRU the service order **is** the recency
order (D7), so one flipped tie leaves a different victim and every access after
it diverges. A run is either bit-identical or arbitrarily different.

**Worked example.** Run W constructs one `Engine` holding two L1s, one L2, one
DRAM `Port(ii = 1, latency = 100)`, one `NextBurstPrefetcher(1, 2)`, and one
`RefusalCounter` shared by both levels.

**Decisions.** **B130** the loop, six handlers, the arena, D12's check;
**B117** the unordered map is never iterated; **B107** the event `seq`;
**B121** determinism is not orderedness, so the exit criterion needs an
independent sorted oracle and not a re-run;
**B141** the observation surface for the event log was **found** rather than
added: all five array verbs reach `mapper.locate` and both issue paths reach
`mapper.expand`, so a recorder on the **mapper** yields an ordered log of every
array operation plus a mid-run hook, with no logging hook in production code.

**Trap.** `l1(CoreId)` and `l2()` hand out **mutable** levels. Nothing at the
type level confines mutation to `triage` and `install`. Reported and deliberately
not fixed.

## `Engine::Engine`

**What it is.** The constructor. Builds the hierarchy, sizes every per-core
vector, and sizes `tile_origin_`.

**Contract.**

```cpp
Engine(const AddressMapper& mapper, const TileTrace& trace, const EngineParams& params);
```

`mapper` and `trace` must outlive the engine. Refusals, in order:

1. `std::invalid_argument` if `trace.n_cores() < 1`;
2. whatever `CacheLevel`, the policy, the ports and `make_prefetcher` throw:
   `std::invalid_argument`, naming the offending value;
3. `std::invalid_argument` if `trace.n_tiles() < 0`.

Then `cores_`, `stats_.core_stall`, `stats_.fetch_latency` and
`stats_.pf_outstanding` are sized to `n_cores`, and `tile_origin_` to
**`n_tiles + 1`**: the last entry is the end of the run, so tile N's length is
`tile_origin[N+1] - tile_origin[N]` for **every** tile including the last, which
is the form V1 compares against `mac_cycles[N]`.

`counter_` is declared **before** the levels, which hold a reference to it. `l1_`
is `reserve`d before the loop, not for speed: the engine hands out `CacheLevel&`
and `Port&` from that vector, and growth would move the elements.

**Worked example.** Run W: `n_cores = 2` builds two L1s; `n_tiles = 1` sizes
`tile_origin_` to 2 entries, both `SimTime{0}` until `run()` fills them.

**Decisions.** **B140**(12-15) the parameters carry no validation, so what throws
here is a constructor precondition and never a config rule.

**Trap.** One `RefusalCounter` serves the whole run **on purpose**: a request
refused at the L1 and again at the L2 keeps its original stamp, so its L2
seniority reflects how long it has genuinely waited (3.8). Giving each level its
own counter would silently reset seniority at the level boundary.

## `Engine::run`

**What it is.** 3.2. Seeds the queue with tile 0 and runs until the queue is
empty, then refuses a run that ended with work outstanding.

**Contract.**

```cpp
void run();
```

```cpp
tile_origin_.at(0) = SimTime{0};
if (trace_.n_tiles() > 0) start_tile(0, SimTime{0});
while (!queue_.empty()) { const Event<EventPayload> e = queue_.pop_min(); dispatch(e); }
```

Then D12's check, over every core and every MSHR file: throws
`std::logic_error` naming the core, its tile, its burst and its outstanding line
count if a core is not `Done`, or naming the file if any L1 or the L2 still holds
live entries or slot waiters. **A throw and not an assert**, because the sweep
build is `-DNDEBUG` and a deadlocked run that returns quietly still produces
numbers.

**Worked example.** Run W: `tile_origin_[0] = 0`, `start_tile(0, 0)`, then 15
dispatches through cycle 121 and on to the barrier at 225. At the end both cores
are `Done`, all three MSHR files are empty, and the check passes silently.

**Decisions.** **B130** six handlers and D12's check built in rather than left to
a timeout, **because U18 proved a deadlock is reachable by a plausible reading of
the plan**.

**Trap. `Engine::run()` is not idempotent and has no guard.** Calling it twice
re-seeds tile 0 at `SimTime{0}` over a hierarchy that is already full of lines,
already holds statistics, and whose cores are `Done`. Nothing refuses it, and the
second run's numbers are not a re-run of the first. Reported and deliberately not
fixed by the Phase C batch; treat one `Engine` as one run.

## `Engine::dispatch`

**What it is.** The switch from an event to its handler. Six cases.

**Contract.**

```cpp
void dispatch(const Event<EventPayload>& e);
```

`now` is `e.key.time`. Every case `return`s; falling past the switch throws
`std::logic_error("Engine::dispatch: unknown EventKind")`, which is unreachable
because the switch covers every enumerator and is reported rather than ignored,
since a silently dropped event is a run that ends early and still prints numbers.

| kind | handler | payload field read |
|---|---|---|
| `Issue` | `on_issue(e.key.core, e.payload.burst, now)` | `burst` + the key's core |
| `L1Probe` | `on_l1_probe(*e.payload.req, now)` | `req` |
| `L2Probe` | `on_l2_probe(*e.payload.req, now)` | `req` |
| `L2Fill` | `on_l2_fill(*e.payload.entry, now)` | `entry` |
| `L1Fill` | `on_l1_fill(*e.payload.entry, now)` | `entry` |
| `Barrier` | `on_barrier(e.payload.tile, now)` | `tile` |

**Worked example.** Run W cycle 110 dispatches **two class-0 events before any
class-2 event**: `L2Fill(E2x)` then `L1Fill(E1x0)`. The class order is what makes
the prefetch-timeliness case a hit at all (V23), because a prefetch fill and a
demand probe landing in the same cycle resolve in favour of the fill.

**Decisions.** **B130** six, not seven (see **U20**); **B107** the `seq` that
makes the key total, so the dispatch order within a cycle is fully determined.

**Trap.** **Six handlers, not seven.** Part 7's C2 row says "*(v3: seven)* The
seven event handlers"; 3.1 says six event kinds, "unchanged in number by v3",
that "C2 adds no event kind", and that service is "a call inside `E_L1Fill`, not
a scheduled event". Six is right and six are built; the row appears to have
counted service as a seventh. Carried as **U20**.

## `Engine::on_issue`

**What it is.** Plan unit C3's entry point: burst `k` of core `c` becomes due.

**Contract.**

```cpp
void on_issue(CoreId c, BurstIndex k, SimTime now);
```

Refuses, with `std::logic_error`, at the one place each could first break:

- `k != cs.cursor`: I13's "service order is trace order". The core has one burst
  in flight under every policy, so an issue for anything but the cursor is an
  engine that lost a service;
- `cs.pending_lines != 0`: I16, lines of the previous burst still outstanding.

Then: expand the burst, set `pending_lines` to the line count, set `issued_at =
now`, set `phase = Stalled`, and for each line acquire a `Request`, reserve an L1
port slot, and schedule an `L1Probe` at `accept + latency`. Finally, and it is
the **last line of 3.4b**, call `prefetcher_->on_demand_issue(*this, c, k, now)`.

`mapper_.expand` is wrapped in exactly one `catch (const std::out_of_range&)`
that re-throws with tile, tick, core and burst, U10 / decision B37's obligation,
discharged here. N7's all-or-nothing holds because `expand` appends nothing at
all when it throws, so a burst that leaves the layer cannot leave a partial one
behind.

**Worked example.** Run W cycle 0, core 0, `k = 0`: `expand` gives `[X]`;
`pending_lines = 1`; `issued_at = 0`; port accept 0, so the probe is scheduled at
`0 + 0 = 0`. Then the prefetcher issues `b1`'s line `Y`, whose port accept is
**1**, because the demand probe already took cycle 0 at `l1_ii = 1`.

**Decisions.** **B131** the core state machine; **B139** the U10 / decision B37
range re-throw is discharged here and was verified **live**, and its second half
is discharged by v3's shape rather than by code, because there is **no per-tick
accumulate buffer any more**.

**Traps.**

- **Everything above the prefetcher call would be identical if prefetching did
  not exist, and that last call returns nothing.** The core does not wait for it
  and cannot observe it. That is what "the PE is not changed" means operationally.
- **`lines_` and `pf_lines_` are two buffers on purpose.** `on_issue` walks
  `lines_` scheduling one probe per line, and the same handler then reaches
  `issue_prefetch`, which expands a **second** burst. With one shared buffer that
  call would clear and refill the vector the outer handler is working from, and
  the code would be correct today only because the loop happens to have finished
  first.

## `Engine::on_l1_probe`

**What it is.** The L1 port accepted this request, `l1_latency` later. Triage,
then react.

**Contract.**

```cpp
void on_l1_probe(Request& r, SimTime now);
```

`lvl.triage(r, granted_)`, then dispatch on the outcome:

| outcome | reaction |
|---|---|
| any of the four drops | `--pf_outstanding[core]`, bump the matching `pf_dropped_*`, `release(r)`, reinject `granted_`, **return** |
| `Hit` | `core_line_done(r, now)` then `release(r)`. D8: the L1 access latency has already been paid, by the port reservation that scheduled this probe; the core takes delivery **inside the probe**, because a hit is not a fill |
| `Merged`, `BlockedTargets`, `BlockedPool` | nothing. Subscribed or registered; nothing computes a completion time (D2, D3): the time is delivered to it by the fill |
| `Forwarded` | reserve the L2 bank, schedule `L2Probe` at `accept + l2_latency`, carrying `r.refusal` as the key's age |
| anything else | `std::logic_error("Engine::on_l1_probe: unknown TriageOutcome")` |

Then `reinject_all(granted_, now)` on every non-drop path.

**Worked example.** Run W:

| cycle | request | outcome | reaction |
|---|---|---|---|
| 0 | demand `X`, c0 | `Forwarded` | bank accept 0 -> `L2Probe` at **10** |
| 0 | demand `X`, c1 | `Forwarded` | bank accept **1** (the bank is busy at 0) -> `L2Probe` at **11** |
| 1 | prefetch `Y`, c0 | `Forwarded` (`free = 2 > demand_reserve = 1`) | bank accept 2 -> `L2Probe` at **12** |
| 111 | demand `Y`, c0 | `Merged` | nothing; the entry is promoted to demand |
| 112 | prefetch `Y`, c0 | `DroppedEntry` | `pf_outstanding` 2 -> 1, released |
| 223 | prefetch `X`, c0 | `DroppedArrayHit` | released; **`policy_->on_hit` was never called** |
| 224 | demand `X`, c0 | `Hit` | `core_line_done` -> `serve(c0, 224)`, released |

**Decisions.** **B129** the nine outcomes this switches on; **B120** the grant
list is reinjected here because injecting reserves a port; **B11** the array-hit
drop does not touch replacement state.

**Traps.**

- **P4 stays true by construction.** A request does not fall through the
  hierarchy inside one function call: it crosses the boundary as an event, so the
  L2 array state **at the moment of the L2 probe** is what the probe sees.
- **The drop path is the only place a prefetch credit comes back without a
  fill.** Forgetting the decrement leaks a credit and the prefetcher slowly turns
  itself off, with no error anywhere.

## `Engine::on_l2_probe`

**What it is.** The L2 bank accepted it, `l2_latency` later. Checks I6, triages,
reacts.

**Contract.**

```cpp
void on_l2_probe(Request& r, SimTime now);
```

Refuses first, with `std::logic_error`, when `r.level != Level::L2 || r.mshr1 ==
nullptr`, which is I6 at the one place it can be broken. Only a request holding an L1
entry ever reaches the L2, and it still holds it. 4.1's whole argument rests on
this, since it is what makes the L2's wait sets **views** over structures that
already exist rather than storage.

Then `l2_.triage(r, granted_)`:

| outcome | reaction |
|---|---|
| `Hit` | schedule `L1Fill` at `now + l2_to_l1_latency`, on **the L1 entry the request still holds** (`r.mshr1`) |
| `Merged`, `BlockedTargets`, `BlockedPool` | nothing |
| `Forwarded` | look the entry up (`l2_.mshrs().find(r.line)`; a null result throws), reserve DRAM, schedule `L2Fill` at `accept + dram_latency` |
| any drop | `std::logic_error`: "was dropped at the L2 while holding an L1 entry, which would leave that entry unfillable" |

Then `reinject_all(granted_, now)`.

**Worked example.** Run W: `L2Probe(X, c0)` at **10** forwards, DRAM accept 10,
`L2Fill` at **110**, the `0 -> 10 -> 110` legs of the miss spine.
`L2Probe(X, c1)` at **11** is `BlockedTargets`, stamped 0. `L2Probe(Y, pf)` at
**12** is `BlockedPool`, stamped 1. After the wake, `L2Probe(X, c1)` at **120**
re-triages into an array **hit** and schedules `L1Fill` at 120;
`L2Probe(Y, pf)` at **121** re-triages holding its grant, `has_slot` admits it
unconditionally, allocate spends the reservation, `Forwarded`, DRAM accept 121 ->
`L2Fill` at **221**.

**Decisions.** **B145** the mutation "`C2` the I6 guard at the L2 is removed" was
proven an **equivalent mutant** and reclassified `kill` to `allow`, so the guard
is a documented redundancy rather than an untested branch.

**Traps.**

- **The default case is unreachable by an invariant, not by the enum.** Every
  request at the L2 holds an L1 entry, so `is_prefetch_at_issue` is false for all
  of them and triage's four drop branches cannot be taken. It is checked because
  the failure it would produce is an L1 entry nobody will ever fill, which
  surfaces much later as D12's deadlock rather than here. This refusal is the
  code's stand against **U18**'s deadlocking reading.
- **The forwarded entry is looked up rather than returned**, which costs one hash
  probe on the coldest path in the model, a full miss, and keeps `triage` to a
  single return value.

## `Engine::on_l2_fill`

**What it is.** The channel returned data. Install at the L2, back-invalidate if
inclusive, retire, deliver.

**Contract.**

```cpp
void on_l2_fill(Mshr& e, SimTime now);
```

In 3.1's order: `l2_.install(line)`; if `res.evicted` **and**
`inclusion == Inclusive`, `back_invalidate(res.evicted_line)`;
`l2_.mshrs().retire(e, retire_)`; then one `L1Fill` per target at
`now + l2_to_l1_latency`, each on **that target's own** `mshr1`; then
`reinject_all(retire_.wake, now)`.

D10 is why the two are separated: the L2 MSHR frees when the fill lands at the
L2, and the core finishes later. `l2_to_l1_latency` is the knob that keeps the
split structural even at its default of 0.

**Worked example.** Run W cycle 110, `L2Fill(E2x)`: install `X` in the L2 (a free
way, nothing evicted); retire; one target, so one `L1Fill` at
`110 + 0 = 110`; the wake list is `[X c1 stamp 0, Y pf stamp 1]`, reinjected in
that order. At cycle 221 the same handler runs for `E2y`.

**Decisions.** **B144** a surviving mutation was fixed **in the tests, never in
the mutation**: `l2_to_l1_latency` is read on two lines and only the fill path
was covered.

**Trap.** `retire_` is one reused member buffer. Nothing here may call anything
that retires a second entry before `retire_.targets` and `retire_.wake` have been
walked.

## `Engine::on_l1_fill`

**What it is.** Data reached the L1. Install, restore I6's pairing, retire,
deliver to the core.

**Contract.**

```cpp
void on_l1_fill(Mshr& e, SimTime now);
```

Order, and the first two steps cannot be swapped:

```cpp
lvl.install(line);
for (Request* t : e.targets) { t->mshr1 = nullptr; t->level = Level::L1; }
lvl.mshrs().retire(e, retire_);
for (Request* t : retire_.targets) {
    if (!t->demand) --stats_.pf_outstanding.at(idx(t->core));
    core_line_done(*t, now);
    release(*t);
}
reinject_all(retire_.wake, now);
```

I6's pairing is restored **before** the entry is destroyed. `retire` cannot do
it, because `mshr1` points from a request at **another** level's file into this
one, and doing it after the erase would form a dangling pointer even if nothing
dereferenced it, and forming one is already undefined behaviour. **Every**
target is cleared, not only the primary: a secondary merged at the L1 never held
an entry, so its `mshr1` is already null and its level already L1, and assigning
both unconditionally is one rule instead of a special case that has to know which
target is which.

**Worked example.** Run W cycle 110, `L1Fill(E1x0)`: install `X` in core 0's L1;
clear `mshr1` on the one target; retire; `core_line_done` reaches
`serve(c0, 110)`; release. The next `Issue` is scheduled at **111**, the last
leg of the miss spine `0 -> 10 -> 110 -> 111`. At cycle 221, `L1Fill(E1y0)`
retires an entry that was **live from cycle 1 to 221**: 220 cycles of L1 MSHR
credit held for a line the core asked for at 111.

**Decisions.** **B137** the dangling `mshr1` closed at both ends: cleared on
every target before retire, and `release` refuses a request still carrying it.

**Trap.** The prefetch credit comes back **here** for a line that landed, and in
`on_l1_probe` for a line that was dropped. Those are the only two places, and
N16's rule is that the budget, not a refusal, is what stops the prefetcher.

## `Engine::on_barrier`

**What it is.** The last core cleared the tile, `tile_tail` later. Plan unit C3's
measurement.

**Contract.**

```cpp
void on_barrier(std::int32_t tile, SimTime now);
```

```cpp
tile_origin_.at(tile + 1) = now;
if (tile + 1 < trace_.n_tiles()) { start_tile(tile + 1, now); return; }
for (CoreState& cs : cores_) cs.phase = Phase::Done;
```

`tile_origin` is a **measured** quantity replacing the derived `tick_base`, and
this assignment is the measurement: `max over cores of served(c, last) +
tile_tail`, which is what `now` is here, because the last service is what
scheduled this event.

**Worked example.** Run W: core 0's last service is 224, `tile_tail(0) = 1`, so
this fires at **225** and sets `tile_origin[1] = 225`. On the unbounded baseline
the same handler sets `tile_origin[1] = 4`.

**Decisions.** **B131** the barrier and `tile_origin[]`.

**Trap.** **The class order is load-bearing rather than incidental.** A core is
served inside its last demand fill, which is class 0, and this event is class 1,
so a barrier resolving in the same cycle observes the service. Reverse the two
and `tile_origin[N+1]` is set one service too early, an exact-tick effect, and
reachable in the unbounded baseline where every latency is zero. That is what
V26 was meant to test, and V26 is unreachable as specified (**U21**).

## `Engine::reinject`

**What it is.** 3.4's `reinject`: put a woken request back through its level's
**port**, at `r.level` and **not** at the top of the hierarchy.

**Contract.**

```cpp
void reinject(Request& r, SimTime now);
```

At `Level::L1`: reserve `l1_[r.core].port(0)` and schedule `L1Probe` at
`accept + latency`. Otherwise: reserve `l2_.port(bank_of(r.line))` and schedule
`L2Probe` at `accept + latency`. Both carry `r.refusal` as the key's age.

**`r.refusal` is not touched here**, which is what makes the ordering FIFO by
**first** refusal (3.8) and starvation freedom provable (I10): the set of
requests with a smaller stamp is finite and never grows.

**Worked example.** Run W cycle 110, the two woken requests, in the order handed
over:

| order | request | `reserve(110)` | probe scheduled |
|---|---|---|---|
| first | `X`, core 1, stamp 0 | accept **110** | 120 |
| second | `Y`, prefetch, stamp 1 | accept **111** | 121 |

**Decisions.** **B144** the mutation "reinject drops the event key's `age`"
survived its **first, vacuous** fixture, where class ordering decided the
comparison before `age` was ever consulted; it was fixed in the test.

**Trap. 3.5's re-entry rule is the whole reason this reads `r.level`.** A request
woken from an L2 index and re-triaged at the L1 would find its **own** entry,
merge into itself, and wait for a fill nobody will request (V11). Reinjecting at
the top of the hierarchy is the natural-looking implementation and it deadlocks.

## `Engine::reinject_all`

**What it is.** Reinjects a wake list in the order handed over.

**Contract.**

```cpp
void reinject_all(std::vector<Request*>& wake, SimTime now);
```

The order is already 3.8's key order, because `retire` merges the two indices
into one list and **sorts** it. The sort is not redundant: a slot waiter can
outlive the allocation of an entry it later merges onto and arrive carrying an
**older** stamp than what is already there.

**Worked example.** Run W cycle 110: reversing the two entries of the wake list
swaps the accepts 110 and 111 and therefore the probes 120 and 121. **That is
I7b**: port reservation order equals key order, and it is observable **only at
`ii >= 1`**, because at `ii = 0` both would be accepted at 110 and the event key
would do all the ordering.

**Decisions.** **B121** determinism is a property of an independent oracle, not
of a re-run, which is why I7b is checked against a sorted oracle rather than
against a second execution.

**Trap.** Iterating this list in any other order changes results and nothing
crashes. It is one of the three places where an ordering slip produces a
plausible run rather than an error.

## `Engine::back_invalidate`

**What it is.** Plan unit C4. 4.4's back-invalidation scan, under
`inclusion == Inclusive` only.

**Contract.**

```cpp
void back_invalidate(LineId line);
```

For each core in **index order** over the `l1_` vector: probe; if resident,
`invalidate(slot)`, then `policy().on_invalidate(slot)`, then
`++stats_.back_invalidations`. The policy call is the **caller's**, exactly as
`on_hit` is after a probe. `on_invalidate` resets the stamp to "never", so the
freed slot becomes the preferred victim again rather than sitting live in the
recency order.

The scan covers **all** cores because the L2 is shared, so a core's fill can
evict a line another core's L1 still holds. Sharedness is why the scan is wide;
it is **not** why you must invalidate at all, which is the correction v2 made to
D6 and the reason this whole function sits behind a knob.

**Worked example.** Both inclusion branches, on a two-core fixture whose L2 holds
exactly one line and whose L1s hold four:

| cycle | event | `inclusive` | `non_inclusive` |
|---|---|---|---|
| 110 | core 0's miss on `X` fills | `X` installed in the L2 and in L1(0) | identical |
| 300 | core 1's miss on `W` fills, and `W` maps to the L2's only set | `install` returns `evicted = true, evicted_line = X`; the scan finds `X` in L1(0), invalidates it, calls `on_invalidate`; **`back_invalidations = 1`** | no scan; `X` stays in L1(0); **`back_invalidations = 0`** |
| 400 | core 0 accesses `X` again | L1 miss, L2 miss, a full round trip: **110 cycles** | L1 **hit**: **0 cycles** |

The `non_inclusive` hit at 400 is **correct**, not an inflated hit rate, and it
is the source of the extra effective capacity: the machine holds
`L2 + n_cores x L1` distinct lines (here `1 + 2 x 4 = 9`) rather than roughly
`L2` (here 1). v1 called the same hit a bug in three places; 4.4 corrected that.
Run W itself is `non_inclusive` and never evicts, so `back_invalidations = 0`.

**Why zero under `non_inclusive` is by construction**, not by a run that happened
not to evict: `stats_.back_invalidations` is incremented at exactly one site,
inside this function, and this function has exactly one call site:

```cpp
if (res.evicted && params_.inclusion == Inclusion::Inclusive) back_invalidate(res.evicted_line);
```

So under `non_inclusive` the increment is unreachable, for any trace, any
capacity and any policy. That is checkable by grep in ten seconds, and it is the
difference between "the counter read zero in our fixture" and "the counter cannot
be nonzero on this branch".

**Decisions.** **B132** back-invalidation is guarded by `inclusion == Inclusive`
and walks a `std::vector` indexed by core id; **B96** `on_invalidate` resets the
stamp so the freed slot becomes the preferred victim again.

**Traps.**

- **The scan walks a VECTOR by core id, and that is the whole of the
  determinism argument here.** It is the one O(cores) loop in the model, and
  under LRU an invalidation changes which slot is chosen next, so an unspecified
  scan order would move victims. Iterating an unordered container would make the
  walk order a function of the hash implementation, and the divergence would show
  up as a different hit rate rather than as an error.
- **It is the widest inner loop in the model**, O(cores) per L2 eviction, at most
  256 arrays at the top of the sweep range. A cost, not a scaling hazard.
- **The inclusion LRU pathology of G3 is present and unmitigated**, which is
  realistic and must be visible: `l2_policy.on_hit` fires only on an L2 probe hit
  and L1 hits never reach the L2, so L2 recency is blind to lines that are hot in
  some L1. That is exactly why an inclusive L2 evicts a line another core is
  actively using. Nothing here mitigates it; Part 8 reports it.

## `Engine::core_line_done`

**What it is.** One line of a burst landed at a core. Plan unit C3.

**Contract.**

```cpp
void core_line_done(Request& r, SimTime now);
```

- **returns immediately when `!r.demand`**: a prefetch completes nobody (4.6,
  I15). The check is here rather than at the two call sites so neither can forget
  it;
- refuses with `std::logic_error` when `pending_lines <= 0`;
- decrements `pending_lines`, and returns unless it reached zero. N7: the burst
  is atomic, so the core takes delivery only when the **last** line lands;
- at zero, calls `serve(r.core, now)`.

**Worked example.** Run W's bursts are single-line, so every call reaches
`serve`: at 110 (from `on_l1_fill`), at 221 (from `on_l1_fill`), at 222 (from
`on_l1_probe`, an array hit), and at 224 (from `on_l1_probe`, an array hit).

**Decisions.** **B131** the core state machine.

**Trap.** Two call sites, and they are not symmetric: `on_l1_probe` calls it on a
`Hit` (the core takes delivery **inside the probe**, because a hit is not a
fill), and `on_l1_fill` calls it per retired target. A third call site would have
to re-derive the prefetch rule, which is why the rule lives here.

## `Engine::serve`

**What it is.** The core has its whole burst. Charge the statistics, advance the
cursor, and either schedule the next issue or arrive at the barrier. Plan unit
C3's centre.

**Contract.**

```cpp
void serve(CoreId c, SimTime now);
```

```cpp
const SimTime want = cs.cursor == BurstIndex{0}
    ? tile_origin_[cs.tile] + trace_.local_tick(c, cs.tile, BurstIndex{0})
    : cs.served_time + step_after(c, cs.tile, BurstIndex{cs.cursor.get() - 1});
```

Then: refuse with `std::logic_error` if `now < want` (I13); charge
`core_stall[c] += now - want` and `fetch_latency[c] += now - issued_at`; set
`served_time = now`; advance the cursor; if the cursor reached `n_bursts`, call
`barrier_arrive(c, now)` and return; otherwise set `phase = Computing` and
schedule the next `Issue` at `now + step_after(...)`.

The floor is **asserted rather than enforced**, and the plan asks for exactly
that. I13 is satisfied **by construction**: the run-ahead lives in the memory
system and never delivers anything to the core, so the core cannot receive burst
`k+1` before it has asked for it, and it does not ask before its own recurrence
says so. A throw and not an assert, because the sweep build is `-DNDEBUG` and an
assert compiled out turns a violated floor into a plausible timeline.

**Worked example, Run W's core 0.** Four services, and the two Part 8 columns:

| burst | `want` | `served` | `served - want` | `served - issued_at` |
|---|---|---|---|---|
| 0 | 0 | 110 | **110** | 110 |
| 1 | `110 + 1 = 111` | 221 | **110** | 110 |
| 2 | `221 + 1 = 222` | 222 | **0** | 0 |
| 3 | `222 + 1 = 223` | 224 | **1** | 1 |

`core_stall[0] = 221`. Core 0's last service is 224, so the barrier fires at
`224 + 1 = 225`, and

```
tile_origin[1] - tick_base[1]  =  225 - 4  =  221  =  core_stall[0]
```

which is V21's "`core_stall` sums to the tile stretch", exact, with no fitting.
Core 1 finished at 120 and contributes `barrier_slack_cycles = 224 - 120 = 104`
instead, which is the cost of the lock-step assumption and is measured rather
than assumed.

**The pure shift, V20's form.** Take the unbounded baseline and delay burst 0 by
`L = 110`, everything else free:

| burst | `want` | `served` | shift |
|---|---|---|---|
| 0 | 0 | 110 | +110 |
| 1 | 111 | 111 | +110 |
| 2 | 112 | 112 | +110 |
| 3 | 113 | 113 | +110 |

`tile_origin[1] = 113 + 1 = 114 = 4 + 110`. The stall is **carried**, in full, to
the barrier. Under v2's rule burst 1 would have been issued at its own absolute
tick if that tick was more than 110 cycles out, and the loss would have vanished
(D13).

The one-cycle term on burst 3 is the whole cost model of prefetching in one
number: at `l1_ii = 1` the prefetch of burst 3 took the port slot at cycle 223,
so the demand probe was accepted at 224. One prefetch, one cycle of core stall,
and the line it fetched was already resident anyway.

**Decisions.** **B131** the self-timed recurrence; **B140**(3) `cursor == 0`
instead of a sentinel; **B146** a meta-verification pair on
`test_unbounded_baseline_reproduces_the_trace` perturbs **both the code and the
oracle**, so the oracle cannot silently mirror the code, red in both directions.

**Traps.**

- **The service floor is switched off across the tile seam deliberately.** Left
  on, the one core whose last service **defines** `tile_origin[N+1]` could not
  take its first burst of the new tile in that same cycle, and every tile would
  gain a cycle over the trace.
- **`core_stall` and `fetch_latency` are equal term by term**, in every row
  above, including the row where a prefetch was outstanding for 220 cycles. That
  is **U19**.

## `Engine::barrier_arrive`

**What it is.** A core cleared the tile. Part 5's countdown.

**Contract.**

```cpp
void barrier_arrive(CoreId c, SimTime now);
```

Sets `phase = AtBarrier`, decrements `cores_remaining_`, and returns if it is
still positive. At zero, schedules `Barrier` at `now + tile_tail(tile)` under
`CoreId{0}`.

**A countdown, not a scan.** No polling, and `barrier_slack_cycles` falls out as
the cost of the lock-step assumption rather than being computed.

A core arrives **at its own last service**; the tile's remaining compute is
charged once, at the tile level. Charging it per core is impossible, because the
trace stores `mac_cycles` already reduced to the max over the tile's cores (Q10).
Charging nothing would end ptb's `layer_01` and `layer_03` tiles 20 cycles
(11.7%) early, on all 64 of them, compounding into every later layer, and V1
would fail there in a way that **looks like a cache bug**.

**Worked example.** Run W: core 1 arrives at 120 (`cores_remaining_` 2 -> 1,
returns); core 0 arrives at 224 (1 -> 0), so `Barrier` is scheduled at
`224 + tile_tail(0) = 225`.

**Decisions.** **B131** the barrier; **B140**(7) a zero-burst core arrives at the
tile origin rather than being skipped, which keeps the barrier arithmetic
uniform.

**Trap.** Two call sites: `serve` when the cursor reaches `n_bursts`, and
`start_tile` for a core with zero bursts in the tile. Missing the second one
leaves the countdown short of zero forever and the run ends at D12's deadlock
check.

## `Engine::start_tile`

**What it is.** Begin a tile for every core. Part 5.

**Contract.**

```cpp
void start_tile(std::int32_t tile, SimTime now);
```

Sets `cores_remaining_ = n_cores`. Then, for each core in index order: reset
`tile`, `cursor = 0`, `pending_lines = 0`, `issued_at = now`,
`served_time = now`, `phase = Computing`; call
`prefetcher_->on_tile_start(cid)`; then either

- `n_bursts(cid, tile) == 0`: call `barrier_arrive(cid, now)` and continue; or
- schedule `Issue` at `now + local_tick(cid, tile, 0)`.

**This is the one place an absolute local tick enters, once per tile** (4.5,
N14). Every later burst gets its spacing as a difference.

**Worked example, the unbounded-baseline identity.** Set every access to a hit
and every latency and `ii` to 0 (V1's configuration). Then `served = issue`, the
floor is inert, and the recurrence telescopes. Run W's core 0, ticks 0, 1, 2, 3,
`mac_cycles = 4`:

| burst | `local_tick` | `gap` | `issue` | `served` |
|---|---|---|---|---|
| 0 | 0 | 1 | `tile_origin[0] + 0 = 0` | 0 |
| 1 | 1 | 1 | `0 + max(1,1) = 1` | 1 |
| 2 | 2 | 1 | `1 + max(1,1) = 2` | 2 |
| 3 | 3 | - | `2 + max(1,1) = 3` | 3 |

`served(c, k) == local_tick(c, k)` for every `k`, which is the trace's own
schedule reproduced exactly. The barrier then adds
`tile_tail[0] = 4 - 3 = 1`, so

```
tile_origin[1] = 3 + 1 = 4 = mac_cycles[0] = tick_base[1]
```

**the baseline identity `tile_origin == tick_base`**, which is V1 in the form
that also checks `tile_tail`. It holds **only** because `gap_k >= 1` everywhere
(Q11); a `gap_k == 0` pair would be two bursts at one local tick, which the model
serialises one cycle apart by the floor. And at `l1_latency = 0` this run is not
only a regression oracle, it is the **scratchpad baseline** (2.5b): every cycle
the cache costs above `tick_base` is a miss and nothing else.

**Decisions.** **B131** the tile machinery; **B133** the `on_tile_start` hook;
**B140**(7) the zero-burst core; **B140**(8) the hook, routed to the human as
**U24**.

**Traps.**

- **A core with zero bursts in a tile is not in the plan**, and the trace format
  permits it. It clears the barrier at the tile origin. Two consequences to keep
  visible: such a core's `barrier_slack_cycles` is the whole tile length, and if
  **every** core has zero bursts the barrier fires at
  `tile_origin[N] + tile_tail[N]`, which still advances the clock because
  `tile_tail >= 1`.
- **`prefetcher_->on_tile_start(cid)` is called for every core, unconditionally,
  before the zero-burst branch.** Moving it below the `continue` would leave a
  zero-burst tile's carried cursor in place. See `on_tile_start` below for what
  that costs.

## `Engine::step_after`

**What it is.** 4.5's `max(gap_k, core_accept_ii)`: the period from the service
of burst `k` to the issue of burst `k + 1`.

**Contract.**

```cpp
SimTime step_after(CoreId c, std::int32_t tile, BurstIndex k) const;
const SimTime gap = as_duration(trace_.gap(c, tile, k));
return gap < params_.core_accept_ii ? params_.core_accept_ii : gap;
```

Precondition: `0 <= k < n_bursts(c, tile) - 1`, inherited from `TileTrace::gap`.

**Worked example.** Run W: `gap = 1` and `core_accept_ii = 1`, so it returns 1
everywhere and the floor never binds. That is the expected case: `gap_k == 0` is
measured-absent from the corpus rather than assumed-absent.

**Decisions.** **B140**(4) `as_duration(LocalTick)` as **one** reviewable
crossing, which is decision **B4**'s rule applied honestly: the crossing is
needed, so it is named once and read once rather than being open-coded wherever
convenient.

**Trap.** `core_accept_ii`'s real job at the 2.5b defaults is not modelling but
**termination**: with `l1_latency = 0` an all-hit chain issues, probes and serves
inside one timestamp, and this is the only thing that advances the clock. The
floor not being expected to bind does not make it optional.

## `Engine::tile_origin`

**What it is.** Part 5's measured quantity, replacing the derived `tick_base`.

**Contract.**

```cpp
SimTime tile_origin(std::int32_t tile) const;   // tile_origin_.at(tile)
```

Sized `n_tiles + 1`, so the last entry is the end of the run and
`tile_origin[N+1] - tile_origin[N]` is tile N's length for every tile including
the last. `.at()`, so an out-of-range tile throws `std::out_of_range`.

**Worked example.** Run W: `tile_origin(0) = 0`, `tile_origin(1) = 225`. On the
unbounded baseline: `tile_origin(0) = 0`, `tile_origin(1) = 4 = tick_base[1]`.

**Decisions.** **B131** `tile_origin[]` as a measured array.

**Trap.** It is **measured, not derived**. Reading it as `tick_base` outside the
unbounded baseline is exactly the v2 error: the two agree only where nothing
stalls.

## `Engine::core`, `l1`, `l2`, `stats`, `queue`, `prefetcher`

**What they are.** Read access for fixtures and for plan unit D2.

**Contract.** `core(CoreId)` and `stats()`, `queue()`, `prefetcher()` are const.
`l1(CoreId)` and `l2()` return **mutable** `CacheLevel&`. `core` and `l1` use
`.at()`, so an out-of-range core id throws rather than reading memory it does not
own.

**Worked example.** A fixture checks `engine.core(CoreId{1}).phase ==
Phase::AtBarrier` after cycle 120, and reads
`engine.stats().back_invalidations == 0` for Run W.

**Decisions.** **B142** every self-comparison in the suite is labelled as one and
none stands alone, so what these accessors expose is checked against independent
oracles rather than against the engine's own arithmetic.

**Trap.** `l1()` / `l2()` hand out mutable levels. Reported and deliberately not
fixed; a fixture can mutate a level mid-run and nothing refuses it.

## `Engine::n_bursts_in_tile` (a `PrefetchIssuer` override)

**What it is.** Bursts in the tile the given core is on **now**.

**Contract.**

```cpp
std::int32_t n_bursts_in_tile(CoreId core) const override;
```

Reads `cores_.at(core).tile` and forwards to `trace_.n_bursts`. Never throws for
a valid core; `.at()` throws for an invalid one.

**Worked example.** Run W, core 0, tile 0: returns 4, which is what stops
`next_burst(1)` from fetching past `b3`.

**Decisions.** **B133** the two-call interface this half belongs to.

**Trap.** The policy needs it to stop at the end of a tile, because "the next
tile's activations do not exist until the barrier resolves". It is the **only**
way a prefetcher can learn anything about a tile, and deliberately so.

## `Engine::issue_prefetch` (a `PrefetchIssuer` override)

**What it is.** Fetch every line of burst `k` of a core's current tile as
`demand = false` requests, each through a **real** L1 port slot. Plan unit C5's
sink.

**Contract.**

```cpp
bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) override;
```

Expands the burst into `pf_lines_`, computes
`cap = l1_mshrs.capacity() - l1_mshrs.demand_reserve()`, and for each line:

- **if `in_fly >= cap`, bump `pf_budget_exhausted` and return `false`**: the
  budget, and nothing downstream, is what stops the prefetcher (N16, I14);
- otherwise `acquire(core, line, k, false)`, reserve an L1 port slot, schedule
  `L1Probe` at `accept + latency`, `++in_fly`.

Returns `true` when the whole burst was issued. A **partial** burst is what 4.6's
own pseudocode does, since its budget check `return`s from inside the per-line
loop.

No context wrap on `expand` here, and that is deliberate: a prefetch walks the
same address run the core will walk, so a coordinate that leaves the layer here
would leave it at the demand issue too, where `on_issue`'s catch names the tile,
tick and core. Wrapping twice would report the failure against a burst the core
has not reached yet.

**Worked example.** Run W's L1: `cap = 3 - 1 = 2`. At cycle 0, `in_fly = 0`, so
`Y`'s prefetch is issued at port accept **1** and `in_fly` becomes 1. At cycle
111 the prefetch for `b2` (also `Y`) is issued at accept **112**, `in_fly` 2. At
cycle 223 the prefetch for `b3` (`X`) takes accept **223**, which is why the
demand probe for `b3` is accepted at 224 and the core pays one cycle of stall.
`pf_budget_exhausted` stays 0 in this run: at `d = 1` the budget of 2 is never
the binding constraint.

**Decisions.** **B133** plan unit C5; **B140**(5) the arena `acquire` this uses.

**Traps.**

- **At `l1_mshrs == lines_per_burst` the budget is exactly zero and prefetching
  is off no matter what `prefetch_distance` says.** `pf_budget_exhausted` and a
  `DroppedReserve` are **two different bounds** and both are reported: the first
  says the prefetcher stopped itself, the second says the file stopped it. Which
  one dominates is what tells you whether `prefetch_distance` or `l1_mshrs` was
  the binding constraint.
- **A prefetch takes a real port slot.** It is one of the four costs 4.6 names,
  and at `l1_ii = 1` every prefetch takes a cycle the demand stream could have
  used.

## `Engine::acquire` and `Engine::release`

**What they are.** The request arena: a `std::deque` that never moves what it
already holds, plus a free list.

**Contract.**

```cpp
Request& acquire(CoreId c, LineId line, BurstIndex k, bool demand);
void release(Request& r);
```

`acquire` reuses a free request if there is one and **assigns the whole struct**,
`*r = Request{...}`, rather than field by field: a field added to `Request` later
cannot be left carrying the previous occupant's value, and the worst of those is
silent: a stale `refusal` gives a fresh request someone else's seniority and
reorders the FIFO for the rest of the run.

`release` **refuses**, with `std::logic_error`, a request that is still held:

```cpp
if (r.on_wait_index || r.reserved || r.mshr1 != nullptr) engine_error("release", ...);
```

Those three bits are the complete list of things that can still point at it, and
each is maintained by the structure that does the pointing. **A request reaches a
terminal state at exactly three places**, and `release` is called at those three
and nowhere else: an L1 array hit, a prefetch drop, and the target loop of an L1
retire. Everything else (merged, blocked at either level, forwarded, a
target of an L2 entry) ends up in that same L1 retire.

**Worked example.** Run W releases at 110 (L1 retire target), 112 (prefetch
drop), 221 (L1 retire target), 222 and 224 (L1 array hits), and 120 (core 1's
retire target). The arena reaches a high-water mark of five live requests and
never grows again.

**Decisions.** **B140**(5) a deque arena plus a free list with exactly **three**
terminal release sites, three because that is how many places a request can end
and naming them is what makes decision **B137**'s refusal checkable; **B137** the
refusal itself; **B117** the node-based map chosen for the same pointer-stability
reason.

**Trap.** The arena is **never erased from**. Freeing means pushing an address
onto `free_`, so `arena_` only grows to the high-water mark of simultaneously
live requests, which the credit supply already bounds. Erasing from the middle of
a deque **does** invalidate everything, so not erasing is the property that keeps
every outstanding `Request*` valid.

## `constexpr SimTime as_duration(LocalTick d)`

**What it is.** The one place a trace **spacing** becomes a simulated duration.

**Contract.** `constexpr SimTime as_duration(LocalTick d) { return SimTime{0} + d; }`.
Total, pure.

N12 asks that `SimTime` and `LocalTick` be mutually uncomparable, and they are:
no operator compares them and nothing yields a `LocalTick` from a `SimTime`. What
4.5 needs is different, and it is a comparison of two **durations** rather than
of two clocks. `SimTime{0} + d` is the crossing `types.h` already permits, used
with the origin that makes it the identity, and it is written **once** so the
crossing is one reviewable site rather than a cast at every call.

**Worked example.** Two callers: `step_after` (`gap` -> a duration) and
`barrier_arrive` (`tile_tail` -> a duration). Run W: `as_duration(1)` in both.

**Decisions.** **B140**(4) one reviewable crossing; **B4** the rule it applies.

**Trap.** It is the seam where a mistyped absolute tick would flow into `SimTime`
with no compile error. The type system stops the accidental crossing; it cannot
stop a `TileTrace` implementation that returns the wrong kind of number.

---

# `native/include/wcache/prefetcher.h` and `native/src/prefetcher.cpp`

## `enum class PrefetchKind : std::uint8_t`

**What it is.** 2.5b's `prefetch_policy`: `None = 0`, `NextBurst = 1`. `none` is
the machine as built and is the default.

**Contract.** Two values, consumed by `make_prefetcher` and by `EngineParams`.

**Worked example.** Run W sets `NextBurst` with `prefetch_distance = 1`. The
demand-only reference run of the same configuration sets `None` with distance 0.

**Decisions.** **B133** the two implementations and nothing more, per Q4's ruling
that fetched data lives at the L1 and the PE is unchanged.

**Trap.** `PrefetchKind::None` paired with a nonzero distance is accepted and the
distance ignored, because a sweep grid crosses the two axes. The cross-field rule
is D1's.

## `class PrefetchIssuer`

**What it is.** What a prefetcher may ask of the memory system, and the whole of
it. **Two calls and no more.**

**Contract.**

```cpp
class PrefetchIssuer {
public:
    virtual ~PrefetchIssuer() = default;
    virtual std::int32_t n_bursts_in_tile(CoreId core) const = 0;
    virtual bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) = 0;
protected: /* copy control protected and defaulted */
};
```

Implemented by `Engine`, which derives from it publicly and passes `*this` to the
prefetcher. It is the class that breaks the dependency cycle: `prefetcher.h`
includes **only `types.h`** and never learns what an engine is.

**Worked example.** Run W: `n_bursts_in_tile(0)` returns 4;
`issue_prefetch(0, BurstIndex{1}, 0)` returns `true` and schedules `Y`'s probe
for port accept 1.

**Decisions.** **B133** plan unit C5's shape.

**Traps.**

- **The narrowness is a design constraint expressed as a type.** A prefetcher
  that could read a core's cursor, a cache's contents or an MSHR's occupancy
  would be able to make decisions the PE can observe, and "the PE is not changed"
  would become an argument rather than a property.
- **Calling a virtual on `*this` is safe here and is not always.** During a base
  class's constructor the object is not yet of the derived type, so a virtual
  call dispatches to the base version, which for a pure virtual is undefined
  behaviour. `Engine`'s constructor never calls a virtual on itself; the hook
  fires from `on_issue`, long after construction.

## `class Prefetcher`

**What it is.** 4.6's interface: "One hook, called from `E_Issue` (3.4b),
returning nothing", plus a second hook the plan does not name.

**Contract.**

```cpp
class Prefetcher {
public:
    virtual ~Prefetcher() = default;
    virtual void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) = 0;
    virtual void on_tile_start(CoreId core) = 0;
protected: /* copy control protected and defaulted */
};
```

**Worked example.** Run W holds one `NextBurstPrefetcher(1, 2)` behind this
handle; the engine calls `on_demand_issue` four times for core 0 and once for
core 1, and `on_tile_start` twice (once per core) at the start of tile 0.

**Decisions.** **B133** the interface plus the new hook, routed to the human as
**U24**; **B67** protected, defaulted copy control.

**Trap.** The whole of 4.6 rests on one boundary and this class is where it is
drawn: the prefetcher lives at the L1, **below the port**, and has no way to
deliver anything to a core. That is why the service floor holds by construction
rather than by enforcement.

## `Prefetcher::on_demand_issue`

**What it is.** The hook, called at the end of `E_Issue`, **after** the demand
lines are already on their way.

**Contract.** Returns **nothing**, and that is what "the PE is not changed" means
operationally: plan unit C5 is reachable from the core only through a call that
cannot affect it.

**Worked example.** Run W cycle 0: `on_demand_issue(engine, 0, BurstIndex{0}, 0)`
issues `b1`'s prefetch and returns; the core has already scheduled its own probe
and never learns what happened.

**Decisions.** **B133** the one hook 4.6 specifies.

**Trap.** Its position in `on_issue` is load-bearing. Called before the demand
loop, the prefetch would take port slot 0 and the **demand** probe would be
accepted at cycle 1.

## `Prefetcher::on_tile_start`

**What it is.** A new tile began for a core, so any fetch-ahead cursor resets.
The hook 4.6 describes in prose but never names.

**Contract.** Returns nothing, throws nothing. Called by `Engine::start_tile` for
**every** core, before the zero-burst branch.

**Worked example, and it is why the hook exists.** A core whose tile 0 has **8**
bursts and whose tile 1 has **12**, at `d = 1`:

| | with `on_tile_start` | without it |
|---|---|---|
| `pf_cursor` at the end of tile 0 | 8 | 8 |
| `pf_cursor` at tile 1's first demand issue (`k = 0`) | reset to 0, then `max(0, 1) = 1` | `max(8, 1) = **8**` |
| the loop condition `cursor <= k + d` | `1 <= 1`, fetches `b1` | `8 <= 1` is false, **fetches nothing** |
| bursts 1 through 7 of tile 1 | fetched, one per demand issue | **never fetched at all** |
| when prefetching resumes | immediately | at `k = 7`, when `k + d` finally reaches 8 |

**Decisions.** **B133** the hook is built **and** recorded as a plan amendment;
**B140**(8) the same, grouped; the plan status is **U24**.

**Trap. `on_tile_start` is load-bearing and is absent from the plan's
interface.** 4.6 gives `Prefetcher` exactly one call and states the tile-boundary
behaviour in prose. Without the second call the cursor is carried across the
barrier, because nothing else ever writes it downwards, and the failure is
**silent and asymmetric**: it costs nothing when tiles shrink, and it silently
loses **every burst of the next tile below the carried cursor** when they grow.
Nothing in the statistics announces it either, because the lost fetches were
never issued: coverage simply reads lower, which looks like a workload property
rather than a bug.

## `class NoPrefetcher final`

**What it is.** 4.6's `none`: `on_demand_issue(c, k, now): pass`. Both overrides
are empty bodies with unnamed parameters. **No state at all.**

**Contract.**

```cpp
void NoPrefetcher::on_demand_issue(PrefetchIssuer&, CoreId, BurstIndex, SimTime) {}
void NoPrefetcher::on_tile_start(CoreId) {}
```

**Worked example.** The demand-only reference run of Run W's configuration: the
`Y` prefetch at cycle 1 never exists, so the L2 bank accepts `X`(c0) at 0 and
`X`(c1) at 1, the `BlockedPool` at cycle 12 never happens, and core 0's burst 3
probe is accepted at 223 rather than 224, one cycle less `core_stall`.

**Decisions.** **B140**(9) `pf_cursor` lives on `NextBurstPrefetcher` **only**,
so `NoPrefetcher` has no state at all and V22's restatement is a property of the
type.

**Trap.** It is **a real class rather than a null pointer the engine tests for**,
so the engine has one code path and plan unit C5's exit criterion is a property
of a call that does nothing rather than of a branch that is not taken. That
matters for **U23**: V22 as written asks for a comparison "against the pre-C5
engine", which does not exist.

## `class NextBurstPrefetcher final`

**What it is.** 4.6's `next_burst(d)`: while the core is stalled on burst `k`,
the L1 pulls in bursts up to `k + d`. One integer of state per core.

**Contract.**

```cpp
NextBurstPrefetcher(std::int32_t distance, std::int32_t n_cores);
void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) override;
void on_tile_start(CoreId core) override;
std::int32_t distance() const;
BurstIndex pf_cursor(CoreId core) const;
```

The constructor throws `std::invalid_argument` for `distance < 1` (`d = 0` is
`none` by another name, and a policy that claims to be on while fetching nothing
is the configuration D1's row refuses outright) and for `n_cores < 1`. Then
`pf_cursor_` is sized to `n_cores`, all zero.

`on_tile_start(core)` sets that core's cursor to 0.

`pf_cursor(core)` is half of I14, `0 <= pf_cursor(c) - cursor(c) <= 1 +
prefetch_distance`; the other half, `pf_outstanding(c) <= l1_mshrs -
l1_demand_reserve`, is the engine's, because the budget is a cache credit and not
policy state.

`on_demand_issue` is 4.6's pseudocode line for line:

```cpp
const std::int32_t next = k.get() + 1;
if (cursor < next) cursor = next;              // never behind the core
const std::int32_t last    = k.get() + distance_;
const std::int32_t n_burst = mem.n_bursts_in_tile(core);
while (cursor <= last && cursor < n_burst) {
    if (!mem.issue_prefetch(core, BurstIndex{cursor}, now)) return;   // the BUDGET stops it
    ++cursor;
}
```

**Worked example, both distances.** A tile of four bursts, `n_bursts = 4`, budget
never binding.

`d = 1`:

| demand issue | `cursor` in | `last` | fetches | `cursor` out | `pf_cursor - cursor` |
|---|---|---|---|---|---|
| `k = 0` | 0 -> 1 | 1 | `b1` | 2 | 2 - 0 = 2 |
| `k = 1` | 2 | 2 | `b2` | 3 | 3 - 1 = 2 |
| `k = 2` | 3 | 3 | `b3` | 4 | 4 - 2 = 2 |
| `k = 3` | 4 | 4 | none (`4 < 4` is false) | 4 | 4 - 3 = 1 |

`d = 2`:

| demand issue | `cursor` in | `last` | fetches | `cursor` out |
|---|---|---|---|---|
| `k = 0` | 0 -> 1 | 2 | `b1`, `b2` | 3 |
| `k = 1` | 3 (`max(3, 2)`) | 3 | `b3` | 4 |
| `k = 2` | 4 | 4 | none | 4 |
| `k = 3` | 4 | 5 | none | 4 |

Read out of the two tables:

- **every burst is fetched exactly once**, guaranteed by the `max(cursor, k+1)`
  line: the cursor never goes backwards, so a burst already fetched is never
  fetched again, and a cursor that lagged would spend credits on lines the core
  has already asked for;
- **the tile boundary is never crossed**, because of `cursor < n_burst` and
  nothing else;
- **I14 holds with slack**: `pf_cursor - cursor` is at most 2 at `d = 1`, and its
  bound is `1 + prefetch_distance`;
- **the budget stops it, never a refusal.** When `issue_prefetch` returns false
  the function `return`s **without advancing the cursor**, so the same burst is
  retried at the next demand issue, by which time its own fills have returned
  credits. A partial burst is correct rather than a bug: the lines already in
  flight are dropped at their matching entries when the retry arrives.

**Decisions.** **B133** the policy and its hook; **B140**(9) `pf_cursor` on the
concrete class only, because `none` has no cursor and inventing one would make
I14 pass by construction on the configuration where it has nothing to say;
**B95** a refused config value is a throw and not a stub.

**Traps.**

- **It does not predict.** "Within a tile, the weight address generator walks a
  spike queue that is resolved when the tile begins, so the address run is
  derivable ahead of time". That is a claim about the hardware, which 4.6 says
  belongs in the write-up. A design whose spike queue is produced incrementally during
  the tile cannot run this policy at all.
- **A prefetch that saved nothing is not a bug.** In Run W, `Y`'s prefetch was
  issued at cycle 1 and the line still lands at 221, exactly when a demand-only
  run would have landed it, because the single L2 MSHR was the binding resource
  and the prefetch spent 98 cycles on a wait index. Prefetching wins where the
  **fetch** is what is late, not where the **credit** is.
- **Run W's L1 is too large to show the fourth cost.** 4.6 lists four; this run
  shows three (port slots, MSHR credits held across a full round trip, L2 bank
  slots and DRAM bandwidth pulled earlier). L1 capacity, the prefetched line
  evicted before use, is the fourth, and it is what the policy does under L1
  pressure, which is the regime the study cares about.

## `make_prefetcher`

**What it is.** The `prefetch_policy` config value, as an object.

**Contract.**

```cpp
std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind kind, std::int32_t distance,
                                            std::int32_t n_cores);
```

- `None`: throws `std::invalid_argument` for `distance < 0`, otherwise returns a
  `NoPrefetcher` and **ignores** the distance, because 2.5b's default pairs
  `prefetch_policy = none` with `prefetch_distance = 0` and a sweep grid crosses
  the two axes. D1's row owns the cross-field rule; what this refuses is a
  distance that is not a number of bursts at all;
- `NextBurst`: constructs a `NextBurstPrefetcher(distance, n_cores)`, which
  throws for `distance < 1` or `n_cores < 1`;
- falling past the exhaustive switch throws `std::logic_error`.

**Worked example.** Run W: `make_prefetcher(NextBurst, 1, 2)`. The reference run:
`make_prefetcher(None, 0, 2)`.

**Decisions.** **B95** `make_policy`'s shape and reasoning, reused: a refused
config value must survive `-DNDEBUG` and must read as a rejected configuration
rather than as unfinished code.

**Trap.** The unreachable default throws rather than defaulting to `none`, which
is the **one wrong answer here**: a run that silently prefetched nothing would
look exactly like a result.

---

# OPEN QUESTIONS

Seven questions are open against Phase C, and two of them block reporting. Each
is flagged at the construct where it bites.

## U18: a prefetch refused at the L2 has no defined outcome, and the natural reading deadlocks

**Bites at:** `CacheLevel::triage` (row 3 of the table above),
`Engine::on_l2_probe` (the default case), `is_prefetch_at_issue`,
`LevelParams::demand_reserve` at the L2.

4.6's refusal table is written for a request **at issue**, and its last row says
the path is "identical below this point, **including at the L2, where
`l2_demand_reserve` applies the same way**". I15 says a `demand == false` request
"is never on a wait index". Both cannot hold: a forwarded prefetch the L2 refuses
has to go somewhere, and the plan offers only "drop" and "wait".

**Drop at the L2 deadlocks, proven rather than feared.** A forwarded prefetch
holds an L1 MSHR entry (I6), across the whole downstream round trip, which is
what 4.1's entire argument rests on. Drop it at the L2 and that L1 entry is
abandoned: nothing will ever fill it, because the only path to `retire` is a fill
and the only path to a fill is a forward that no longer exists; the core's later
demand for the same line **finds that entry** and merges onto it, so its burst
never completes; `pending_lines` never reaches zero, no further `Issue` is
scheduled, the queue empties, and the run ends at D12's deadlock check.

**The working resolution: the drop rules apply at the L1 only**, through one
predicate spelled once, `is_prefetch_at_issue(r) = !r.demand && r.mshr1 ==
nullptr`. A prefetch at the L1 has nothing behind it and must be dropped; a
prefetch at the L2 has exactly the backing 4.1 asks for and is treated as any
other request. That is decision **B135**'s widening, recorded as a change rather
than as a restatement.

**Two consequences, both real.**

- **`l2_demand_reserve` is now INERT.** Every request the L2 sees holds an L1
  entry, so `is_prefetch_at_issue` is false there, `has_slot` always takes the
  `free > 0` branch, and the reserve is never consulted. It is a 2.5b config
  field with no effect on any run. Plan unit D2 must not emit it as a live knob
  and D1 must not offer it as a sweep dimension unless the ruling goes the other
  way.
- **The resolution violates I15 and V28 as literally written.** A forwarded
  prefetch **can** sit on an L2 wait index: Run W reaches it at cycle 12, and a
  live test reaches it in four bursts. **I15 holds exactly at the L1** and
  nowhere else.

**What is wanted**, one of two: amend I15, V28 and 4.6's drop table to say "at
issue", which is what the code does, and what Part 8 already implies when it
asks for drops "refused at issue, broken out by reason", and admit
`l2_demand_reserve` is dead; **or** reject the resolution and specify a third
outcome for an L2-refused prefetch that is neither waiting nor dropping, saying
what happens to the abandoned L1 entry. **Blocking for D2's statistics wording.**

## U19: the headline metric is identically zero

**Bites at:** `EngineStats::core_stall` and `::fetch_latency`, `Engine::serve`.

Part 8 says of these two: "with prefetching on, their **difference is the latency
the policy hid**, and it is the single number the policy should be judged on."

**That number is identically zero, under every policy, in every run.** The proof
is four lines:

```
serve:      want = (cursor == 0) ? tile_origin[tile] + local_tick(c, 0)
                                 : served_time + max(gap_{k-1}, core_accept_ii)
serve:      schedules Issue(c, cursor) at  now + max(gap_k, core_accept_ii)   // now == served_time
on_issue:   issued_at = now
```

The next burst is issued at exactly the cycle `want` will be computed from, and
the first burst of a tile is issued at exactly `tile_origin + local_tick(c, 0)`,
which is that burst's `want`. So `issued_at == want` **term by term**, and
therefore `core_stall[c] == fetch_latency[c]`.

Run W's four terms are `(110, 110)`, `(110, 110)`, `(0, 0)` and `(1, 1)`: equal
in every row, including the row where a prefetch was outstanding for 220 cycles.
**A test in which a prefetch demonstrably hid 330 cycles reports a difference of
0.**

**Why, structurally.** Prefetching moves the *fetch* earlier and never the *ask*.
`issued_at` is the ask and `want` is also the ask, so any latency the policy
hides shortens both by the same amount. The two quantities remain a genuine
consistency check (they must be equal, and a divergence means the recurrence was
violated), which is worth keeping. What they are not is a policy metric.

**Two candidates, recorded rather than chosen**, because the choice is plan unit
D2's: `fetch_latency` against the `d = 0` baseline of the same configuration (a
cross-run difference; Q13's grid already runs `d = 0` once per `l1_mshrs` value,
so the baseline exists by construction), or `served - fill_time` per burst (an
in-run number, needing a field the engine does not carry today). Either way the
Part 8 sentence needs correcting, because as written it names a quantity that is
identically zero. **Until this is answered, D2 emits a column whose value is a
constant.**

## U17: `on_evict` ordering

**Bites at:** `CacheLevel::install`.

Part 2.2's authoritative interface table lists **four** verbs (`on_hit`,
`on_fill`, `on_invalidate`, `pick_victim`) and does not mention `on_evict`. Part
3.4's `install` pseudocode at line 619 calls `policy.on_evict(slot)` **after**
`on_fill(slot)` **on the same slot**. For **any** stamp policy the pseudocode's
order clobbers the stamp the fill just wrote, so the freshly filled slot would
look like the oldest line in its set immediately after being filled, and every
victim choice downstream is then wrong in a way that still produces plausible hit
rates.

Phase C is the first code to reach the disputed call site, and reaching it does
not change the answer: the call is **not** made, the site carries a comment
naming U17, no fifth verb was invented, and the absence is **pinned by a test**
so a later edit that adds it goes red (decision **B138**). Three outcomes are
coherent: drop `on_evict` and amend 3.4; keep it and rule that it fires
**before** `on_fill`; or keep it and rule that it takes the **evicted line's**
identity rather than the slot, which is the reading D2's victim-age distribution
would want. Carried unchanged.

## U20: six handlers or seven

**Bites at:** `Engine::dispatch`, and the six handler entries.

Part 7's C2 row says "*(v3: seven)* The seven event handlers". Part 3.1 lists
**six** event kinds, "unchanged in number by v3", says "C2 adds no event kind",
and says service is "a call inside `E_L1Fill`, not a scheduled event". Phase C
built six. Six is almost certainly right and the row appears to have counted
service as a seventh, but confirming it is amending the plan.

## U21: V26 is unreachable as specified

**Bites at:** `Engine::on_barrier` (the class-order note), `TileTrace::tile_tail`.

V26 asks for a fixture where "a core's last burst of a tile fills in the same
cycle the barrier would resolve", to check that the class 0 service lands before
the class 1 barrier. It cannot be built: `barrier_arrive` schedules `Barrier` at
`now + tile_tail`, and `tile_tail >= 1` by construction, so the barrier event is
**always at least one cycle after** the last service that scheduled it. The class
ordering it tests is real and is load-bearing for other reasons; the fixture
needs either `tail = 0` to be legal or a different construction. A verification
item that cannot fire is a green check that proves nothing.

## U22: V27's closed form holds only under an extra assumption

**Bites at:** `Engine::serve`, `Engine::start_tile` (the baseline identity).

V27 says that at `l1_latency = 1`, `tile_origin[N] - tick_base[N]` equals the sum
over earlier tiles of that tile's **maximum per-core burst count**. Under the
self-timed recurrence each burst costs one extra cycle, so core `c`'s last
service shifts by `n_bursts(c)`, and the tile's origin shifts by
`max_c (last_tick(c) + n_bursts(c)) - max_c last_tick(c)`. That equals
`max_c n_bursts(c)` **only when the same core attains both maxima**. A
counterexample in two cores: core A has 10 bursts at ticks 0..9, core B has 2
bursts at ticks 0 and 20. Baseline tile end 20; at `l1_latency = 1` core A ends
at 19 and core B at 22, so the drift is **2**, not 10. The corpus's density (one
burst per tick, Q11) makes the two maxima coincide, so the closed form is right
**on this corpus**; it should say so.

## U23: V22 is unbuildable as written

**Bites at:** `NoPrefetcher`, `make_prefetcher`.

V22 asks that `prefetch_policy = none` give "a byte-identical event log **against
the pre-C5 engine**". There is no pre-C5 engine: under decision **B74**'s
batching, plan unit C5 landed in the same batch as C2 and C3, so no earlier
engine binary or recorded log exists to diff against, and the event log itself is
plan unit D2's and is not built. The restatement that is both checkable **and
stronger** is recorded rather than adopted: "**`NoPrefetcher` issues nothing**",
stronger because it is a property of the class rather than of a build that no
longer exists, so it cannot rot.

## U24: `on_tile_start` is undocumented

**Bites at:** `Prefetcher::on_tile_start`, `NextBurstPrefetcher::on_tile_start`,
`Engine::start_tile`.

4.6 gives `Prefetcher` exactly one call and states the tile-boundary behaviour in
prose. The behaviour is not reachable without a second call, and its absence
loses whole bursts silently. Adding it is widening a plan interface, which
decisions **B97** and **B125** established a role may not silently do, so the
hook is built, plan unit C3 cannot work without it, **and** recorded as a plan
amendment. Either 4.6's interface block gains the second line, or the prefetcher
must be rebuilt without it.

---

# HONESTY NOTE

Three numbers were reported during Phase C's implementation and **cannot be
reproduced from this tree**, because the smoke fixtures that produced them were
not left in it. They are listed here with what survives and what does not,
because the difference matters more than the numbers (decision **B147**).

**1. `tile_origin = 0, 3, 6`.**
*Holds:* the **identity** `tile_origin[N] == tick_base[N]` on the unbounded
baseline. It is confirmed independently, by `oracle_tile_origin` in the
reviewer's `engine_fixture.h`, which recomputes the origins from the trace and
Part 5's recurrence alone and never calls the engine.
*Does not hold as stated:* the triple `0, 3, 6`. No fixture in the tree produces
those tiles. Treat them as an anecdote about a fixture that no longer exists.

**2. `345 -> 238 -> 131`** for prefetch distances 0, 1, 2.
*Holds:* the **content**, a strictly monotone reduction as the distance grows.
*Does not hold as stated:* the three numbers. The reviewer's own oracle-pinned
fixture gives **`621 -> 342 -> 291`** for the same shape of run. What differs is
the fixture (trace, capacities, latencies) and not the engine, and neither
triple is a property of the model. Any figure quoting cycles saved by distance
must name the configuration that produced it.

**3. The `4x` inclusive cycle cost.**
*Holds:* the **branch split**, exactly. Both branches run, `back_invalidations`
is zero under `non_inclusive` **by construction** (one increment site, one call
site, one guard) and positive under `inclusive`, and the induced L1 misses are
counted.
*Does not hold as stated:* the factor. `4x` came from a fixture whose L2 held one
line, which maximises the effect by construction; **a soak shows 1.07x**. The
direction is a result; the magnitude is a property of that fixture.

**The standing rule this establishes: scratchpad evidence that no longer exists
is not evidence.** A number that survives into a document must be reproducible
from something in the tree, which means a committed fixture with an oracle, not a
terminal buffer.

What *is* verified for this batch lives in `PROGRESS.md`'s Tested column and is
deliberately not quoted here: the test counts, the compile cases, the mutation
sweep (decision **B148**), the per-array-operation invariant soak with vacuity
guards (decision **B143**), the independent oracles (decision **B142**), and the
meta-verification pair that perturbs both the code and its oracle (decision
**B146**). Two further durable lessons from the same sweep sit in the record
rather than here: seven apparent survivors were **dead harness cases** rather
than test gaps (decisions **B149**, **B150**, **B151**), and **a mutation harness
keyed on exact source text rots silently under refactoring and reports the rot as
a passing result** (decision **B152**).

And the standing caveat above all of them: **plan unit A3 does not exist**, so
every engine number in this tree, including every cycle in this document, comes
from a hand-written trace. The fixture chooses its own `gap` values and its own
`tile_tail`, so the two things plan unit A3 owes against the **real corpus** are
still owed: the count of `gap == 0` pairs, which Q11 says must be zero and which
the fixture never generates, and the `tile_tail` histogram, on which U21's
reachability question now depends. A green Phase C suite is not evidence for
either.
