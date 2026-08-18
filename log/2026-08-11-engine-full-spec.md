# 2026-08-11 Unit 4: TimedEngine, full specification

Supersedes `log/2026-08-11-engine-grant-and-arbitration-plan.md`, which was a
delta against plan Part 2 and carried four correctness defects of its own. This
is the whole engine, written against the interfaces that actually exist.

Amends `log/2026-08-05-cachesim-redesign-plan.md` Parts 2, 5 and 6. Parts 1
(trace format), 3 (architecture) and 4 (build order) stand as written.

**Nothing here changes implemented code.** Units 1-3 are unaffected; the tree
stays at 171 checks, 0 failures in both build modes.

---

## Part 0. What exists, and what this plan is allowed to assume

Read directly from the tree, not from the plan.

| Unit | Files | State |
|---|---|---|
| 1. `BlockPackMapper` | `layout.h`, `layout.cpp` | built, reviewed, tested |
| 2. `locate` | same | built, reviewed, tested |
| 3. `SetAssociativeArray` | `cache.h`, `cache.cpp` | built, reviewed clean, **no tests yet** |
| 4. `TimedEngine` + `CacheLevel` + `ReplacementPolicy` | - | this document |

The four verbs unit 4 may call (`cache.h:109-136`):

```cpp
SlotId       probe(LineId line) const;              // kNoSlot if absent, NO side effect
SlotId       free_slot(LineId line) const;          // kNoSlot if the set is full
void         victim_candidates(LineId, std::vector<Candidate>& out) const;  // replaces
InsertResult insert(LineId line, SlotId slot);      // {evicted, evicted_line}
std::int64_t num_slots() const;
```

and from unit 1 (`layout.h:48-63`):

```cpp
void         expand(const Burst& b, std::vector<LineId>& out) const;   // APPENDS
SetIndex     locate(LineId line, std::int64_t num_sets) const;
LineId       num_lines() const;
std::int64_t line_size_bytes() const;
```

Four properties of those interfaces drive the whole design, and each one is a
constraint the engine cannot negotiate:

1. **`probe` is `const` and is not an access.** `cache.h:103-108` is explicit:
   "the caller decides whether to follow it with `ReplacementPolicy::on_hit`,
   and only that call makes it an access." The engine therefore *owns* recency
   ordering. See Part 6, which is the sharpest consequence in this document.
2. **`expand` appends and does not de-duplicate across calls**
   (`layout.h:27-36`). A tick's buffer must be sorted and uniqued by the
   engine before it means "distinct lines this tick".
3. **`expand` throws before its first append** (`layout.h:38-47`), which leaves
   the buffer holding a well-formed but *partial* tick. The header says the
   engine must decide between discarding the tick and aborting the run and
   "must not silently simulate the partial one". Part 11 decides.
4. **`free_slot` before `victim_candidates`** (`cache.h:111-114`). A free way
   costs no eviction and consults no policy.

### Running example configuration

Every numbered example below uses this, so the numbers compose.

```
shape        KH=3, KW=3, CIN=512, COUT=512,  weight_bytes = 1
mapper       BlockPackMapper(cin_block=1, cout_block=4)
             line_size_bytes = 1 * 4 * 1 = 4
             n_cin_blocks = 512, n_cout_blocks = 128
             num_lines = 3*3*512*128 = 589,824

L1  (private, one per core)   cache_size_bytes =  8, assoc = 1  ->  2 sets,  2 slots
L2  (shared)                  cache_size_bytes = 16, assoc = 2  ->  2 sets,  4 slots

l1_mshrs = 1     l2_mshrs = 2     l2_tgts_per_mshr = 3
l1_miss_latency_ticks = 2         l2_miss_latency_ticks = 10
l2_fill_lines_per_tick = 1        l2_hit_lines_per_tick = unbounded
replacement = LRU                 4 cores, C0..C3
```

`locate(line, num_sets)` satisfies `line == tag * num_sets + set_index`
(`layout.h:15-17`), so at `num_sets = 2`: **even lines to set 0, odd to set 1.**

---

## Part 1. The two clocks

The single largest defect in the previous draft came from conflating these, so
they are separated first and everything else is built on the separation.

| | Trace time | Simulated time |
|---|---|---|
| Symbol | `tick_base + tick` | `t` |
| Source | the trace file, fixed | the engine, computed |
| Meaning | when the generator said the event happens | when it actually happens |
| Under `baseline_unbounded` | equal | equal |
| Under any real config | earlier | later, by the stall being measured |

`tick_base` is the prefix sum of preceding tiles' `mac_cycles`
(plan 1.4 line 141), so trace time is only globally monotonic **if tiles do not
overlap** - which is what the tile barrier guarantees. The barrier is not a
modeling nicety layered on top; it is the precondition that makes trace time
well defined at all. See Part 10.

Both are `Tick = std::int64_t` today (`types.h:34`). Part 14 records why they
are not yet distinct types and what would change that.

### The defect this replaces

The previous draft wrote:

```
for (core c : cores_with_event(t))            // t is SIMULATED time
    if (core_ready_time[c] <= t)
        mapper.expand(burst_of(c, t), buffer);
```

`burst_of(c, t)` indexes the trace by simulated time, and when the guard fails
the event is **dropped**, not deferred - at `t+1` the loop asks for
`burst_of(c, t+1)`, a different and later event.

**Example 1 - the dropped events.** C0 is stalled from simulated tick 5 to 40.
Its trace has one event per tick.

| | Old loop | Correct |
|---|---|---|
| trace events 5..39 | **skipped, never issued** | issued at 40, 41, 42, ... |
| lines requested | 1 | 36 |
| effect on results | fewer misses, shorter run | the stall being measured |

It fails in the flattering direction: heavier stall means more events silently
discarded, so the config that looks best is the one that lost the most work.
2.7's `stall_in_order` already says the right thing - a refused core re-issues
"without advancing its trace pointer" - but the loop had no trace pointer.

---

## Part 2. State

```cpp
// One per core. `cursor` is the trace pointer stall_in_order refers to.
struct CoreState {
    std::size_t cursor;         // index into this core's event list, monotonic
    Tick        ready_time;     // earliest simulated tick it may issue at
    bool        blocked;        // true while a request of its is outstanding
    std::int32_t tile;          // which tile the cursor sits in, for the barrier
};

// One outstanding miss. Targets are cores waiting on this exact line.
struct Mshr {
    LineId              line;
    Tick                alloc_tick;     // fill ordering key, Part 5
    Tick                due_tick;       // alloc_tick + l2_miss_latency_ticks
    std::vector<CoreId> targets;        // bounded by l2_tgts_per_mshr
    std::vector<Waiter> deferred;       // NoTargets overflow, Part 7, UNBOUNDED
};

// A request that is waiting for something.
struct Waiter {
    Tick   enqueue_tick;   // simulated tick of FIRST refusal, never rewritten
    CoreId l1_index;        // tie-break
    LineId line;
    // ordering key is exactly (enqueue_tick, l1_index) -- Part 5
};
```

`blocked` is a separate field from `ready_time` on purpose. At the moment a
core is refused you must record that it is stalled, but the time it will resume
is unknowable then - it depends on a grant that has not happened. A single
`ready_time` field cannot express "waiting, resume time unknown", which is why
the previous draft could not write down the refusal path.

---

## Part 3. The loop

```
run():
    while (!quiescent()) {
        t = next_event_time()
        if (t == kNever) throw std::logic_error("engine deadlock at ...")
        step(t)
    }

quiescent():
    every core's cursor is exhausted
      && no MSHR outstanding
      && every wait list is empty

next_event_time():
    min over
      - earliest due_tick among outstanding MSHRs
      - earliest issue time among cores that are not blocked:
            max(tick_base + trace_tick(c, cursor[c]), ready_time[c])
    kNever if both sets are empty

step(t):
    1. land every fill due at t, capped by l2_fill_lines_per_tick,
       in (alloc_tick, line) order                       # Part 5
    2. grant() once, after ALL of step 1                 # Part 5
    3. service the hit queue, capped by l2_hit_lines_per_tick   # Part 6
    4. advance the tile barrier if every core has cleared the tile  # Part 10
    5. accumulate this tick's demand from ready cores    # Part 11
    6. triage each request                               # Part 4
```

### `horizon` is gone

The previous draft wrote `for (Tick t = 0; t < horizon; ++t)`. There is no
correct value for `horizon`. Under `baseline_unbounded` it would be
`Σ mac_cycles` (316,280 for `inst16`, 7,158 for `inst1024`), but re-timing is
the entire point of `TimedEngine`, and how much longer the run gets **is the
measurement**. A fixed bound either truncates the run - throwing away exactly
the stall being studied - or requires guessing a padding factor.

### Why the deadlock check throws rather than asserts

If the wait list is non-empty but nothing is scheduled, the run cannot proceed.
That is an internal invariant, so the STALL 2 rule ("`assert` is only for
values this code produced itself") points at `assert`. It is overruled here for
one reason: `assert` vanishes under `-DNDEBUG`, which is the sweep build, which
is the run that would then hang silently for hours on a cluster node. A hang is
worse than either diagnostic. `throw`.

### The skip is where the "event-based" half lives

`next_event_time` jumps over ticks in which nothing can happen. Ticks are
retained for the compute side, the barrier and the per-tick fill budget; what
is removed is iterating over them.

This also repairs the cost argument. The original defect A said per-tick retry
costs `simulated_ticks × stalled_cores`. But the previous draft still scanned
`for core c : cores_with_event(t)` every tick - 1024 cores across a stretched
timeline, the same blowup it claimed to remove. Driving step 5 from a min-heap
over issue times, and skipping empty ticks entirely, is what makes the win real.

**Example 2 - the skip.** From Example 9 below: at simulated tick 0 all four
cores become blocked and the earliest fill is due at 10. `next_event_time`
returns 10 directly. Ticks 1-9 are never constructed.

---

## Part 4. Triage

One function, called on a request's first arrival and again every time it is
granted.

```
triage(req, t):

    # ---- L1 ----
    if (l1[c].probe(req.line) != kNoSlot):
        policy_l1.on_hit(slot)                     # Part 6: order matters
        complete(req, t)                           # L1 hit costs nothing
        return

    m1 = l1_mshr_matching(c, req.line)
    if (m1):
        if (m1.targets.size() < l1_tgts_per_mshr): m1.targets.push(c); return
        else:                                      m1.deferred.push(waiter); return
    if (l1_pool_full(c)):
        enqueue(l1_wait[c], waiter); return        # <-- RETURN. see below
    allocate l1 mshr

    # ---- L2 ----
    if (l2.probe(req.line) != kNoSlot):
        enqueue(hit_queue, waiter)                 # bandwidth, not the MSHR pool
        return

    m2 = l2_mshr_matching(req.line)
    if (m2):
        if (m2.targets.size() < l2_tgts_per_mshr): m2.targets.push(c)
        else:                                      m2.deferred.push(waiter)
        return                                     # <-- never falls through
    if (l2_pool_has_free_slot()):
        allocate m2, alloc_tick = t, due_tick = t + l2_miss_latency_ticks
        return
    enqueue(l2_wait, waiter)
```

Three fixes from the previous draft are visible here.

**The missing `return` after the L1 enqueue.** The old text read
`if (l1 pool full) enqueue(req, t, L1);` and then fell straight through to the
L2 path, so a request blocked at L1 was *also* forwarded to L2. It consumed L2
resources on behalf of a core that was not actually issuing.

**The MSHR match and the target-room test are now one branch.** The old text
was:

```
if (l2_mshr_matching(req.line) has target room) return MERGED;
if (l2 pool has a free slot)                    allocate;      # <-- reachable!
```

A match with a *full* target list fell through to `allocate`, putting **two
MSHRs on the same line**. That double-counts the miss, issues two off-chip
fetches for one line, and consumes a slot the bound exists to protect -
precisely the failure the "re-run triage on grant" paragraph said must not
happen.

**An L2 hit joins the hit queue, not nothing.** See Part 6.

### `hit_under_block` is one branch, and it is here

`hit_under_block = false` is reproduced by testing the blocked flag *before*
the L2 probe rather than after, which is where gem5 puts it
(`base.cc:2606-2637`):

```
if (!hit_under_block && l2_pool_full()):  enqueue(l2_wait, waiter); return
```

"Blocked" is defined as: the L2 MSHR pool has no free slot. One line, both
behaviors, sweepable.

**Example 3 - defect C, why a stalling queue could not do this.**

```
L1 -> [ R1(miss)  R2(miss)  R3 ] -> L2      MSHR pool full, queue stalled
                             ^ would have HIT in the L2 array
```

Under the original wholesale-stall design, `R3` sits behind `R1` and never
reaches the array to discover it would have hit. Head-of-line blocking silently
converts a hit into a wait - that is `hit_under_block = false` behavior,
produced by accident, while the config says `true`. The reason a queue cannot
express it: **a queue stalls in FIFO order, but "does this need an MSHR?" is a
per-request property you cannot evaluate until after the probe.**

Triage-at-the-input fixes it because only requests that genuinely need a new
MSHR ever enter `l2_wait`:

| Case | Needs MSHR | Enters `l2_wait` |
|---|---|---|
| hits in L2 array | no | **no** - goes to `hit_queue` |
| merges onto a live MSHR | no | no |
| matches a live MSHR, targets full | no, but blocked | no - `m2.deferred` |
| misses, pool has a slot | yes | no, allocates |
| misses, pool full | yes | **yes** |

Everything in `l2_wait` is blocked on the identical resource, so strict FCFS
service over it causes no head-of-line blocking of traffic that could have
proceeded.

---

## Part 5. One ordering rule, three service points

**`arbitration = fcfs_then_index`**, key `(enqueue_tick, l1_index)`, applied at
**every** point where the engine picks among ready work:

| Service point | Ordered by | Why it needs an order |
|---|---|---|
| MSHR grants (`l2_wait`) | `(enqueue_tick, l1_index)` | who gets the freed MSHR |
| fills landing in one tick | `(alloc_tick, line)` | `l2_fill_lines_per_tick` caps them |
| hit responses | `(enqueue_tick, l1_index)` | `l2_hit_lines_per_tick`, **and `on_hit` order** |

The previous draft ordered only the first and then claimed V8 (byte-identical
re-run). It did not earn it: two of the three were unordered.

### Why `enqueue_tick` needs the grant mechanism to exist

Under per-tick retry, a refused core re-issues every tick, so at any instant
every waiting request *looks newly arrived*. There is no record of who has
waited longest - FCFS was not merely unspecified, it was **inexpressible**.
Once a request enqueues once and sleeps, its arrival time is stored and "first
come" means something. The two changes are not independent: decision 6 (grants)
is what makes decision 5 (FCFS) definable.

**Example 4 - arbitration.** The L2 pool is full. Refusals arrive:

```
tick 40   C900 refused
tick 55   C3  refused
tick 55   C12 refused
tick 55   C700 refused

l2_wait sorted:   (40,900)  (55,3)  (55,12)  (55,700)
```

An MSHR frees at tick 61. **C900 wins** - longest wait, despite the highest
index. Under the old loop order C3 would win and C900 would starve forever,
which was a policy nobody chose.

It is a **total order**: no two requests share a key, since one L1 cannot
enqueue twice in one tick (a core has at most one request outstanding, Part 8).
So a re-run is byte-identical. That is the same requirement `free_slot` already
meets by returning the lowest free way (`cache.cpp:133-137`), so a cold-start
fill reproduces even under Random replacement.

It removes the systematic bias **without claiming to be unbiased**: waiting
time dominates, index decides only genuine ties, and a low-index core still
wins every tie it enters. That is now a stated, reportable property.

### `grant()` runs once per tick, after all fills

```
grant():
    while (l2_pool_has_free_slot() && !l2_wait.empty()):
        w = l2_wait.pop_min()
        triage(w, now)          # NEVER re-enters l2_wait -- see below
```

Two changes from the previous draft, both required:

**Hoisted out of the fill loop.** The old text called `grant()` after each
individual release, so the outcome depended on the order fills were iterated -
which was unstated. Landing all fills first also makes the engine *more*
correct: a queued request should see a line filled earlier in the same tick.

**It cannot livelock.** The old `grant()` popped a request whose triage could
re-enqueue it, and `pop_min` would return the same request forever with the
free slot never consumed. With Part 4's triage, a popped request always
resolves - hit, merge, defer-onto-MSHR, or allocate - because the loop
condition guarantees a free slot and the only consumer inside is this triage.
This is also what makes Part 5's claim "a request never re-enqueues, so its key
is stable" actually true; before the fix it was false.

---

## Part 6. The hit path

The original 2.6 borrowed gem5's split - bandwidth in the crossbar, concurrency
in the cache - and then implemented only the **fill** half.
`l2_fill_lines_per_tick` covers DRAM→L2. Nothing covered L2→L1. So 627
simultaneous L2 hits all completed in the same tick, for free: infinite L2 read
bandwidth, unmodeled, in exactly the hit-dominated regime the large-L2 sweep
points occupy. gem5 does not do this; hit responses traverse the same 32-byte
crossbar as everything else (`XBar.py:154-163`).

**New parameter `l2_hit_lines_per_tick`**, default `unbounded` so
`baseline_unbounded` is untouched and V7 still holds.

**This is not `hit_under_block`.** They are easy to conflate and must not be:

| | Waits on | Answer |
|---|---|---|
| `hit_under_block` | the MSHR pool | hits never wait on it |
| `hit_queue` | the L2 read port | hits may wait on it |

Different resources, different queues. Defect C's argument is untouched.

### The part that bites even at unbounded bandwidth

`cache.h:109` declares `probe` as `const`, and `cache.h:103-108` says a probe
is **not** an access - the engine calls `ReplacementPolicy::on_hit` itself.

**Under LRU, the order of those calls *is* the recency stack.** So hit order is
observable even when bandwidth is free, and V8 is not satisfied by ordering the
MSHR wait list alone.

**Example 5 - hit order changes the answer.** L2 set 0 holds line 0 (way 0,
filled tick 10) and line 2 (way 1, filled tick 20). At tick 30, C0 hits line 0
and C1 hits line 2. Bandwidth is unbounded, so both complete at tick 30.

| Service order | `on_hit` calls | LRU victim at tick 31 |
|---|---|---|
| C0 then C1 | line 0, then line 2 | **line 0** is LRU → evicted |
| C1 then C0 | line 2, then line 0 | **line 2** is LRU → evicted |

At tick 31 a fill for line 4 (set 0, both ways occupied) needs a victim. The two
orders evict different lines, and every subsequent access to the survivor
diverges. Same config, same trace, **different hit rate**. `fcfs_then_index` on
the hit queue is what pins it.

### A queued hit can be evicted before it is served

**Example 6 - hit downgraded to miss.** `l2_hit_lines_per_tick = 1`.

```
tick 30   C0 probes line 6 -> HIT.  C1 probes line 8 -> HIT.
          budget is 1: C0 served.  C1 -> hit_queue, enqueue_tick = 30.
tick 31   a fill for line 10 lands in set 0; free_slot returns kNoSlot;
          pick_victim over the candidates returns line 8; insert evicts it.
tick 32   C1 reaches the front of hit_queue.
          Re-probe:  line 8 is GONE.  It is now a MISS.
```

Serving C1 as a hit would report data that is not there and lose a miss. So the
rule from Part 1 of the previous draft generalizes to its full form:

> **Anything that waits re-triages when it is served. It never acts on the
> classification it held when it enqueued.**

C1 moves from `hit_queue` to `l2_wait` **keeping `enqueue_tick = 30`**. It has
genuinely been waiting since then; reusing the timestamp keeps the key stable
and the FCFS order honest.

Whether this fires depends on the policy. Under LRU a just-probed line is poor
victim material; under Random it is fair game - and `free_slot` returning the
lowest free way exists precisely so Random stays reproducible. So the
transition is reachable. Instrument it: `hits_downgraded_to_miss`. If it is ~0
the concern was free; if it is not, that is a finding about the machine.

The inverse is already covered by V4: a queued miss becomes a hit when someone
else's fill lands.

---

## Part 7. Three waiting structures, not one

The previous draft had one queue and it could not work.

| Structure | Holds | Released by | Bounded? |
|---|---|---|---|
| `l2_wait` | `Blocked_NoMSHRs` - want a new MSHR | `grant()` on MSHR release | by Part 8 |
| `Mshr::deferred` | `Blocked_NoTargets` - want *this* MSHR | that MSHR retiring | by Part 8 |
| `hit_queue` | want an L2 read port | `l2_hit_lines_per_tick` budget | by Part 8 |

Merging the first two livelocks `grant()` (Part 5). It is also *wrong on the
merits*: everything on `Mshr::deferred` is waiting for one specific line, and
at the instant that MSHR retires the line is resident, so **every deferred
waiter re-triages into a hit simultaneously**. They were never competing for
the MSHR pool at all. gem5 has exactly this split (`MSHR::targets` vs
`MSHR::deferredTargets`).

### Example 7 - defect D, worked

Calibration error D said 2.4's conclusion 3 ("`tgts_per_mshr` expected inert,
max observed 4 against a limit of 12") measured the wrong thing. Here it is at
the running example's `l2_tgts_per_mshr = 3`, `l2_miss_latency_ticks = 10`.
Line X is wanted by 8 cores, spread across trace ticks 0-3, two per tick:

```
t=0   C0,C1 miss X   -> MSHR #A allocated, targets {C0,C1}   (2/3)  due t=10
t=1   C2      -> merge, targets {C0,C1,C2}                    (3/3)  FULL
      C3      -> #A.deferred = {C3}
t=2   C4,C5   -> #A.deferred = {C3,C4,C5}
t=3   C6,C7   -> #A.deferred = {C3,C4,C5,C6,C7}
t=10  fill lands. targets C0,C1,C2 satisfied. X is now resident.
      #A retires -> all 5 deferred waiters re-triage -> all HIT, no new MSHR.
```

**Per-tick merge count never exceeds 2**, comfortably under the limit of 3 -
which is exactly what 2.4's instrument would report. Yet the target list hits
its limit and **5 cores block**.

The error in one sentence: **the measurement window is 1 tick; the MSHR's
window is `l2_miss_latency_ticks`.** An MSHR collects every request for its
line across its whole lifetime, so a per-tick merge ratio is a lower bound on
target depth, not the depth. Nothing exotic is needed - no re-timing, no
stretching; this happens at 1:1 timing. Re-timing makes it worse (a stretched
timeline pulls more of the trace's spread inside one 100-tick window) and
`stall_in_order` damps it (a blocked core issues nothing further). Which way
the two net out is unknown, which is why the change is "implement it live and
report the observed max", not "assume a different number".

---

## Part 8. Back pressure, and why every queue is bounded

There is **no structural back pressure** between L1 and L2 - no queue depth, no
refusal upstream. What supplies it instead is `stall_in_order` (2.7): a core
waiting on its own request issues nothing further, so new demand stops **at the
source** and no queue ever needs to refuse anyone.

| | Structural back pressure | Demand back pressure |
|---|---|---|
| Source | a queue depth limit | `stall_in_order` |
| Mechanism | queue full → refuse upstream | core waits on its own request |
| In this design | **absent** | **present** |

That is what bounds an unbounded list:

```
|l2_wait| + Σ|targets| + Σ|deferred| + |hit_queue|   ≤   cores × l1_mshrs
```

One outstanding request per core; 1024 cores; so no queue can exceed the core
count. 1024 entries is nothing to hold.

Three results fall out.

**The unbounded choice is safe rather than merely defensible.** Part 4 of the
previous draft left it as an open worry ("if it grows to thousands, that is a
finding"). It cannot.

**`l2_mshrs` sweep points above 1024 are identical to `unbounded`**, so the top
of the 2.8 range is redundant grid points. Drop them.

**Decisions 8 and `stall_in_order` are coupled, and that must be written down.**
The unbounded list is safe *because of* the in-order core model. Swap in an
out-of-order issue stage or a decoupled prefetch engine that keeps fetching
under a miss, and the list grows without bound, hides the real bottleneck, and
needs a depth limit after all. Right now that dependency is implicit across two
sections of two documents.

Why not just add a depth limit anyway: it would be the only knob in the 2.8
table with no gem5 convention and no measurement behind it, and it would
interact with `l2_mshrs` in the sweep so a result could not be attributed to
either. Leaving it out keeps `l2_mshrs` and `l2_tgts_per_mshr` as the only
concurrency bounds - the separation 2.6 argues for.

---

## Part 9. Latency composition

Stated explicitly because the previous drafts never did, and the MSHR occupancy
window is the quantity the whole study turns on.

```
L1 hit                     completes at t
L1 miss, L2 hit            completes at t + l1_miss_latency_ticks
L1 miss, L2 miss           MSHR occupied  [t, t + l2_miss_latency_ticks)
                           fill lands at  t + l2_miss_latency_ticks
                           core completes at  fill + l1_miss_latency_ticks

core_ready_time[c] = completion time
next issue          = max(tick_base + next_trace_tick, ready_time[c])
```

The MSHR is occupied for **exactly** `l2_miss_latency_ticks`, not the full core
round trip. That is what makes defect A's steady-state arithmetic
(`l2_mshrs / l2_miss_latency = 20/100 = 0.2` lines per tick) mean what it says,
and it matches 2.7's "these are what make an MSHR occupied long enough for the
bound to bind."

An L1 hit costing zero is what makes `baseline_unbounded` collapse exactly:
`ready_time = t`, so the next issue is `max(t+1, t) = t+1`, the event's own
trace time. V7 holds by construction rather than by luck.

---

## Part 10. The tile barrier

**A tile's tick 0 begins after every core has cleared the previous tile.** Three
reasons, weakest first.

**It is what the generator assumed.** A tile's `mac_cycles` is the **max over
cores** of their cycle count, and `ticks` is dense `0 .. mac_cycles-1` with
`len(ticks) == mac_cycles`, confirmed on all 128 tiles of the 16-core file
(1.2). The generator already collapsed per-core variation into one tile length
and padded the fast cores out to it. The trace *is* a lock-step block.

**It is physically real.** A tile boundary is indexed by `dram_i` / `noc_i` - a
new activation tile arriving over DRAM or the NoC. That refill is machine-wide.

**Without it `tick_base` is meaningless, and `tick_base` is the entire global
clock.** `tick` is tile-local and restarts at 0 every tile (1.1). The only
thing making time global is `tick_base + tick` with `tick_base` a prefix sum of
preceding `mac_cycles`. That sum is valid *only if tiles do not overlap*. Let a
fast core enter tile 1 at global tick 1400 when tile 0 has
`mac_cycles = 1618`, and its timestamp reads 1618 + something - a number that
is now fiction, inherited by every `max(tick_base + tick, core_ready_time)`
downstream.

**It is a per-core condition, not a global tick.** The previous draft wrote
`if (tile_boundary(t)) barrier()`, which assumes every core crosses at the same
`t`; re-timing is what breaks that. Correct form: core `c` may not advance its
cursor into tile `N+1` until `max` over all cores of their tile-`N` completion
time.

---

## Part 11. Accumulating a tick, and the two obligations `expand` hands up

```
buffer.clear();                       // keeps capacity
for (core c : ready_cores(t)) {       // from the min-heap, not a scan
    try { mapper.expand(burst_of(c, cursor[c]), buffer); }
    catch (...) { throw; }            // see below
}
std::sort(buffer.begin(), buffer.end());
buffer.erase(std::unique(...), buffer.end());
```

**C2, the reserve obligation.** F1 removed the `reserve` from inside `expand`,
transferring the obligation to the accumulate loop or paying ~log2(N)
reallocations per tick (11 measured for 1024 lines). It lands **here**, and it
belongs *outside* the `while` loop, not inside `step`: `clear()` keeps
capacity, so one `buffer.reserve(expected_lines_per_tick)` before the run
serves every tick. The previous draft put it inside the loop, where it is a
no-op after the first tick - harmless but misleading. **C2 is closed by this
document.**

**The partial-tick obligation.** `layout.h:41-47` states that a burst throwing
part way through a tick leaves the buffer holding a well-formed but PARTIAL
tick - the earlier cores only - and that the engine "must decide whether such a
tick is discarded or the run aborts, and must not silently simulate the partial
one."

**Decision: the run aborts.** `expand` throws only on a coordinate outside the
tensor, which means the trace disagrees with its own `workload_dims` header.
That is a value arriving from outside the simulator, so by the standing rule it
is already a `throw`; discarding the tick would silently drop real demand and
corrupt every downstream statistic, and a sweep that quietly skips malformed
ticks reports a hit rate for a workload that was never run. Abort, name the
tile, tick, core and coordinate.

---

## Part 12. Bursts are atomic

2.5 names two conditions under which the L1 pool binds, both already permitted
by the format: a `cout_block` of 1 turns one 4-wide burst into **4 line
requests**, and an arch may emit multiple events per core per tick. In those
cases `stall_in_order` becomes ambiguous - does the core stall if *any* of the
4 lines cannot be placed, or issue what fits and stall on the rest?

**Decision: atomic.** All of a burst's lines are placed, or the core stalls and
retries the whole burst. The event is the instruction and 2.7 already models
the core as an in-order issue stage; partial issue means a half-completed burst
and a much larger core state machine for no modeling gain.

Atomicity carries a config constraint that deadlocks if unchecked:

**Example 8 - the deadlock config.**

```
cout_block = 1  ->  a 4-wide cout burst expands to 4 distinct lines

l1_mshrs = 4    ->  fits exactly, zero margin
l1_mshrs = 2    ->  the burst can NEVER be placed; the core never advances;
                    next_event_time() returns kNever with work outstanding
```

`lines_per_burst > l1_mshrs` must be rejected at config load. Both operands
come from outside the simulator (YAML and the trace header), so by the standing
rule this is a **`throw`**, not an `assert` - and it must survive `-DNDEBUG`,
since the sweep build is where a bad grid point would otherwise hang.

Note the sweep already contains `l1_mshrs ∈ {4, 8, unbounded}` and layouts are
swept independently, so this combination is reachable by construction, not
hypothetically.

---

## Part 13. Full walkthrough

The running example config, 4 cores, one tile, `tick_base = 0`. Trace:

```
trace tick 0:   C0->line 0   C1->line 1   C2->line 2   C3->line 0
trace tick 1:   C0->line 4   C1->line 5   C2->line 2   C3->line 3
```

Recall: even lines → L2 set 0, odd → set 1; L2 is 2-way, so each set holds 2.

### Example 9 - simulated ticks 0 through 22

**t = 0.** All four cores ready, all cursors at trace tick 0. Triage in
`l1_index` order (all four share `enqueue_tick = 0`).

| Core | Line | L1 | L2 | Outcome |
|---|---|---|---|---|
| C0 | 0 | miss, MSHR ok | miss, pool 0/2 | **allocate #A**, due 10, targets {C0} |
| C1 | 1 | miss, MSHR ok | miss, pool 1/2 | **allocate #B**, due 10, targets {C1} |
| C2 | 2 | miss, MSHR ok | miss, **pool 2/2 full** | `l2_wait` ← (0, C2, line 2) |
| C3 | 0 | miss, MSHR ok | #A matches, 1/3 room | **merge**, targets {C0,C3} |

All four cores now blocked. `next_event_time()` = 10.

**t = 1..9.** Never constructed. (Example 2.)

**t = 10.** Two fills due, `l2_fill_lines_per_tick = 1`. Order by
`(alloc_tick, line)`: #A `(0,0)` beats #B `(0,1)`. **#B defers to t=11.**

- #A lands: `free_slot(0)` → set 0 way 0, free. `insert` → no eviction.
  `policy.on_fill(slot 0)`.
- Targets C0, C3 satisfied. `ready_time = 10 + l1_miss_latency = 12`.
- #A released, pool 1/2.
- `grant()`: pop `(0, C2, line 2)`. **Re-triage at t=10** - `probe(2)` is still
  a miss (only line 0 resident), no MSHR matches, pool has room →
  **allocate #C**, `alloc_tick = 10`, due 20. Grant latency: 10 ticks.

**t = 11.** #B lands, set 1 way 0. C1 satisfied, `ready_time = 13`. #B
released. `grant()`: `l2_wait` empty.

**t = 12.** C0 and C3 resume, cursors advance to trace tick 1. Note their
natural trace time was 1; they issue at `max(1, 12) = 12`. **This is the
re-timing.**

- C0 → line 4. C0's L1 (direct-mapped, 2 sets) holds line 0 at set 0; line 4
  also maps to set 0 → **L1 miss and L1 eviction of line 0**. Forward.
  `l2.probe(4)` miss, no match, pool 1/2 → **allocate #D**, due 22.
- C3 → line 3. L1 miss. `l2.probe(3)` miss, no match, **pool 2/2 full** →
  `l2_wait` ← (12, C3, line 3).

**t = 13.** C1 resumes → line 5. L1 miss, L2 miss, pool full →
`l2_wait` ← (13, C1, line 5).

```
l2_wait:   (12, C3, line 3)   (13, C1, line 5)
```

C3 is ahead of C1 **despite the higher index**, because it was refused a tick
earlier. Example 4's rule, in situ.

**t = 20.** #C (line 2) lands. Set 0 holds line 0 at way 0; way 1 is free →
`free_slot` → way 1, no eviction. C2 satisfied, `ready_time = 22`. #C released.
`grant()`: pop (12, C3, line 3) → re-triage → still a miss → **allocate #E**,
due 30. Pool full again (#D, #E), loop exits, C1 keeps waiting.

**t = 22.** #D (line 4) lands. Set 0 now holds line 0 (way 0) and line 2
(way 1) - **full**. `free_slot(4)` → `kNoSlot`. `victim_candidates(4)` →
`[{slot 0, line 0}, {slot 1, line 2}]`. LRU: line 0 filled at t=10 and never
hit; line 2 filled at t=20 → **evict line 0**.
`insert(4, slot 0)` → `{evicted: true, evicted_line: 0}`.

> **This is where `invalidate` becomes mandatory.** Line 0 left the L2, but
> **C3's L1 still holds it** (C0's L1 evicted it at t=12; C3's did not). Under
> the inclusive hierarchy of 2.3, the L2 eviction must back-invalidate C3's
> copy or the L1 will later serve a line the L2 no longer believes is resident.
> `CacheArray` has no `invalidate` verb today. Part 14.

C0 satisfied, `ready_time = 24`. #D released. `grant()`: pop (13, C1, line 5) →
**allocate #F**, due 32.

### What the walkthrough demonstrates

| Mechanism | Where |
|---|---|
| skipping empty ticks | t = 1..9 |
| fill ordering under a bandwidth cap | t = 10, #A before #B |
| grant with re-triage | t = 10, C2 |
| target-list merge | t = 0, C3 onto #A |
| FCFS beating index | t = 13, C3 before C1 |
| `free_slot` before `victim_candidates` | t = 20 vs t = 22 |
| LRU eviction and `InsertResult` | t = 22 |
| the missing `invalidate` | t = 22 |
| re-timing | trace ticks 0-1 spanning simulated 0-32 |

**Timeline stretch:** 2 trace ticks became 32+ simulated ticks. With
`baseline_unbounded` the same trace completes at simulated tick 1 - which is
V7, and Example 10.

### Example 10 - `baseline_unbounded` collapse (V7)

```
l1_mshrs = l2_mshrs = unbounded,  l1_miss_latency = l2_miss_latency = 0,
l2_fill_lines_per_tick = l2_hit_lines_per_tick = unbounded
```

Every triage allocates immediately, every MSHR is due the tick it was
allocated, no queue is ever non-empty, so `grant()` and the hit queue are
no-ops. Completion time is `t`, `ready_time = t`, and the next issue is
`max(tick_base + tick + 1, t) = tick_base + tick + 1` - the trace's own tick.
The timeline collapses exactly.

The regression that matters: **the timing machinery must add nothing when its
mechanisms are disabled.** Every mechanism in this document is off in this
config by construction, not by a special-cased branch.

---

## Part 14. Parameter table (2.8, revised)

| Parameter | Default | Sweep | Change |
|---|---|---|---|
| `l1_mshrs` | 4 | {4, 8, unbounded} | - |
| `l1_tgts_per_mshr` | 20 | fixed | - |
| `l2_mshrs` | 20 | {16, 32, 64, 128, 256, 512, 1024} | **`unbounded` and >1024 dropped as redundant, Part 8** |
| `l2_tgts_per_mshr` | 12 | fixed | **reclassified: live and instrumented, not "expected inert", Part 7** |
| `demand_mshr_reserve` | 1 | fixed | - |
| `l2_fill_lines_per_tick` | unbounded | {1, 4, 16, 64, unbounded} | - |
| **`l2_hit_lines_per_tick`** | **unbounded** | **{4, 16, 64, 256, unbounded}** | **new, Part 6** |
| `l1_miss_latency_ticks` | 2 | {2, 10} | composition pinned, Part 9 |
| `l2_miss_latency_ticks` | 100 | {50, 100, 200} | = MSHR occupancy exactly, Part 9 |
| `hit_under_block` | true | {true, false} | one branch, Part 4 |
| `bound_check_order` | before_allocate | fixed | - |
| **`arbitration`** | **`fcfs_then_index`** | **fixed** | **new, applied at 3 points, Part 5** |
| `l1_to_l2_queue_depth` | - | - | **deliberately absent, Part 8** |

---

## Part 15. Named decisions (2.9, continued)

Decisions 1-4 stand as written.

5. **`arbitration = fcfs_then_index`**, key `(enqueue_tick, l1_index)`, applied
   at *every* service point: MSHR grants, fill landing, and hit responses.
   Total, therefore reproducible. (Part 5)
6. **Grants are delivered by notification on MSHR release**, not per-tick
   retry. Ticks are retained for the compute side, the barrier and the
   bandwidth budgets; polling is removed and empty ticks are skipped. (Parts 3, 5)
7. **Triage happens at the L2 input**, so `hit_under_block` is a one-branch
   switch rather than an emergent property of a queue. (Part 4)
8. **The wait lists are unbounded**, so `l2_mshrs` and `l2_tgts_per_mshr` stay
   the only concurrency bounds. **This depends on `stall_in_order`** and is not
   safe without it. (Part 8)
9. **`Blocked_NoTargets` is live and instrumented**, because 2.4's merge
   measurement is per tick while target lists accumulate over an MSHR lifetime.
   (Part 7)
10. **Three waiting structures, not one**: `l2_wait`, `Mshr::deferred`,
    `hit_queue`. Merging the first two livelocks `grant()`. (Part 7)
11. **Anything that waits re-triages when served.** A queued hit may become a
    miss; a queued miss may become a hit. `enqueue_tick` is preserved across
    the move. (Part 6)
12. **Bursts are atomic**, and `lines_per_burst > l1_mshrs` throws at config
    load. (Part 12)
13. **A trace coordinate outside `workload_dims` aborts the run**, discharging
    the partial-tick obligation of `layout.h:41-47`. (Part 11)

---

## Part 16. Verification (Part 5, revised)

| # | Fixture | Asserts |
|---|---|---|
| V1 | two cores refused in the same tick | lower `l1_index` granted first |
| V2 | two cores refused in different ticks | earlier `enqueue_tick` wins regardless of index (Example 9, t=13) |
| V3 | two queued requests for the same line | exactly one MSHR; the second merges on grant |
| V4 | queued miss, line filled by another core while it waits | granted as a hit, no MSHR consumed |
| V5 | pool full, request that hits the array | served when `hit_under_block = true`, refused when `false` |
| V6 | target list at `l2_tgts_per_mshr` | blocks with `NoTargets`; **all** deferred waiters become hits when that MSHR retires (Example 7) |
| V7 | `baseline_unbounded` | timeline collapses exactly onto trace ticks (Example 10) |
| V8 | full re-run of any sweep point | byte-identical - requires all three orderings, not just `l2_wait` |
| **V9** | **two hits in one tick, LRU, unbounded bandwidth** | **eviction order matches service order (Example 5)** |
| **V10** | **queued hit whose line is evicted before service** | **re-probes to a miss, allocates, keeps `enqueue_tick` (Example 6)** |
| **V11** | **stalled core with events at trace ticks 5..39** | **all 36 events issued, none dropped (Example 1)** |
| **V12** | **`lines_per_burst > l1_mshrs`** | **throws at config load, under `-DNDEBUG` too (Example 8)** |
| **V13** | **wait list occupancy across a full sweep point** | **never exceeds `cores × l1_mshrs` (Part 8)** |
| **V14** | **coordinate outside `workload_dims` mid-tick** | **aborts; no partial tick is simulated (Part 11)** |

V11 is the one that would have caught the defect that motivated this rewrite,
and it is cheap: a 40-tick fixture with one core and a forced stall.

### New statistics, reported per run

```
max wait-list length            (V13's bound, observed)
max observed target depth       (defect D, observed vs the assumed 4)
max deferred-list length
grant latency distribution
fraction of grants that re-triaged into a hit or merge rather than an allocate
hits_downgraded_to_miss         (Example 6)
ticks skipped by next_event_time  (the cost win, measured)
timeline stretch factor          simulated_ticks / Σ mac_cycles
```

The re-triage fraction directly measures whether decision 11 is doing real
work. The skip count directly measures whether decision 6 paid for itself.

---

## Part 17. Build order for unit 4

Each step ends with tests, following the units 1-3 pattern, and mutation
testing is a standing requirement (STALL 2: 125 passing checks hid 6 live
mutations).

| Step | Module | Depends on |
|---|---|---|
| 4a | `ReplacementPolicy` (`on_hit`, `on_fill`, `pick_victim`) + LRU, FIFO, Random | unit 3 |
| 4b | `CacheLevel` = array + policy + MSHR pool; no time yet | 4a |
| 4c | `MshrPool` with targets, deferred lists, and the bound checks | 4b |
| 4d | `TimedEngine`: the loop, the three queues, arbitration | 4c |
| 4e | config load + validation (decisions 12, 13) | 4d |
| 4f | statistics and the results CSV (plan 6.1) | 4d |

**4a is blocked on nothing and is the natural next unit** - but unit 3 still
has no test suite. `TEST_DESIGN_CACHE.md` is written and has four open
questions; the blocking one is that `test_layout.cpp:662` owns `int main()`
while the Makefile links all of `tests/*.cpp` into one binary. Resolving that
(option B: move `main` into `tests/main.cpp`, add `tests/suites.h`) is a
prerequisite for every test file this plan implies.

---

## Part 18. What stays open

**`invalidate` on `CacheArray` is now mandatory, not optional.** Example 9's
t=22 shows an L2 eviction of a line another core's L1 still holds. Under 2.3's
inclusive hierarchy that must back-invalidate. `cache.h` has four verbs and no
fifth; adding one changes a reviewed, clean interface, so it wants its own
review pass rather than being slipped in during 4b.

**`CoreId` stays `std::uint32_t`** (`types.h:29`). The reviewer's
recommendation to sign it was conditional on it meeting a signed count. In this
document it becomes the tie-break half of an ordering key and is compared
against `l1_index` - still no arithmetic, still no subtraction. Revisit at 4d
if that changes.

**Trace time and simulated time are still both `Tick`.** Part 1 separates them
conceptually; the type system does not. `max(tick_base + tick, core_ready_time)`
mixes them in one expression, and a wrong-direction subtraction would be a
plausible number rather than a compile error. This is the same shape as the
signedness class that has now cost three findings (`LineId`, `SetIndex::tag`,
`Tick`). It is no longer speculative - Part 1's defect was exactly this
confusion - but two distinct strong typedefs touch every line of the engine, so
the call belongs at 4d when the types are written, not before.

**C2 is closed** by Part 11.
