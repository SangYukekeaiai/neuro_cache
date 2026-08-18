# 2026-08-13 wcache: event-driven rebuild plan

**Status: proposal, for review. No code is to be written against this until it is signed off.**

Supersedes everything under `log/2026-08-05-cachesim-redesign-plan.md` Parts 2-6 and
all of `log/2026-08-11-engine-full-spec.md`. Those described a tick loop that skipped
empty ticks; this describes a discrete-event simulator that has no tick loop at all.

The existing tree (`src/wcache/native/`, units 1-3, 171 checks) is **not** carried
forward as code. Where a prior finding is a fact about the *machine* or the *trace*
rather than about the old implementation, it is restated here and re-derived; where it
was a fact about the old design, it is dropped.

---

## Part 0. Verdict on the sketched control flow

The control flow you sketched is **structurally correct in its probe order and in its
three-way MSHR classification**, which are the two things homegrown cache models most
often get wrong. It is **not yet an event-driven model**, and three of its steps ask for
information that does not exist at the moment they ask for it.

### What is right, and should survive verbatim

1. **The probe order - array → own-level MSHR → next level.** This is exactly gem5's
   order and exactly the hardware's. Checking the MSHR file *before* forwarding is what
   makes a secondary miss cost zero downstream traffic; a model that forwards first and
   merges later reports inflated off-chip traffic.

2. **The three-way MSHR outcome - `blocked` / `hit` / `miss`.** Most models collapse
   this to two ("is there a matching entry, else allocate"), which silently allocates a
   second MSHR for a line that already has one when the target list is full. Your split
   names the three cases separately and is the correct shape.

3. **"If L2MSHR blocked: stay in L1 MSHR."** This is right and it is the non-obvious
   call. An L1 MSHR entry is allocated at miss *detection* and freed at fill *arrival*;
   it is held across the entire downstream round trip, including any time spent waiting
   for an L2 MSHR. Holding it is what makes L1 MSHR occupancy mean something.

4. **The instinct that a resolved request "returns a time."** Correct for the paths
   where the time is actually determined. See D3 for the paths where it is not.

### What is broken

Twelve defects, in descending order of how much they change the design.

---

**D1. `For Core [0 : core-number]` is the tick model wearing a disguise.**

Scanning every core per unit of time is `O(cores × simulated_cycles)`. At 1024 cores on
a re-timed timeline that is the exact blow-up you are trying to escape - the loop does
not care that you call the outer variable an "event" instead of a "tick".

In a discrete-event simulator **you never iterate over cores.** You pop the earliest
entry from a priority queue. A core appears in the computation only when it has an event
scheduled, and a stalled core has none: it is *referenced* by the structure it is waiting
on, and that structure will schedule its wake-up. Cost becomes `O(E log E)` in the number
of events, independent of how far the timeline stretches.

→ **Fix:** outer loop is `while (!queue.empty()) { e = queue.pop_min(); dispatch(e); }`.

---

**D2. "add a next possible queue time" is polling, and there is no correct value for it.**

A blocked request cannot know when its resource frees. Guess early and it re-blocks,
burning events and risking livelock; guess late and you have invented stall time that
the hardware would not have. Either way the number is fiction, and it is fiction that
lands directly in the quantity being measured.

The resource *does* know when it frees - at the instant it frees. So invert the
direction: the blocked request **registers** on the resource's wait list and computes
nothing. When the resource frees, it pops its wait list and schedules the wake-up.

→ **Fix:** replace every "add next query time" with "push onto the wait list of the thing
you are blocked on." Zero polling, zero predicted times, and the wait list is also the
occupancy instrument you want for the sweep.

---

**D3. Three of your branches return a time that is not knowable at that point.**

- `If L1MSHR hit: target++, add the scheduled serve time` - the primary entry's serve
  time exists only if the primary has already secured its downstream resource. If the
  primary is itself parked on the L2 MSHR wait list (which is your own next branch), it
  has no scheduled time. This branch reads a field that has not been written yet.
- `If L2MSHR hit: target++; return L1 MSHR release time` - same, one level down.
- `If L2MSHR blocked: stay in L1 MSHR, add next query time` - same as D2.

→ **Fix:** a merging request does not compute a completion time. It **subscribes**. The
time is *delivered to it* by the fill event, not *derived by it* at triage. This is the
same inversion as D2 and it removes the last place where the model would have to predict
the future.

---

**D4. A decision made at block time is not valid at service time.**

Between the moment a request blocks and the moment it is served, two things can happen
that invalidate its classification:

| At block time | While it waits | At service time |
|---|---|---|
| classified **L2 miss**, wants an MSHR | another core's fill lands that line | it is now a **hit** - allocating an MSHR would double-fetch |
| classified **L2 hit**, wants a port | the line is chosen as a victim and evicted | it is now a **miss** - serving it as a hit reports data that is not there |

→ **Fix**, stated as a hard rule:

> **Anything that waits re-triages from the top of its level when it wakes. It never acts
> on the classification it held when it blocked.**

It carries its original enqueue timestamp across the re-triage, so FCFS ordering stays
honest even though the classification changed.

---

**D5. `target++` is unbounded, and overflow is a *different* wait list.**

Real MSHRs have a fixed number of subentries. A request arriving at a full target list
does not merge and does not go to the pool queue - it blocks **on that specific entry**.
This is a second wait list and it must not be merged with the pool wait list, because the
two are released by different events:

| List | Waiting for | Released when | On release |
|---|---|---|---|
| pool wait | *any* MSHR entry | any entry retires | grant **one** per freed slot |
| entry deferred | *this* entry's target slot | *that* entry retires | **all** of them resolve at once, as hits |

Merging them is not just imprecise, it livelocks the grant loop: a popped request that
re-blocks on the same list is popped again forever with the free slot never consumed.

---

**D6. There is no fill path. Nothing is ever installed, evicted, or invalidated.**

The sketch ends at "return a time" and the line never enters the array. Missing:

- victim selection (free way first, only then consult the replacement policy);
- the eviction itself and its effect on the replacement state;
- **inclusive back-invalidation** - the L2 is shared, so an L2 eviction must invalidate
  the copies in *other cores'* L1s. This is reachable in a four-access example, not a
  corner case, and a model without it will serve L1 hits for lines the L2 believes are
  gone.

---

**D7. An L2 hit is treated as free. It is not, and the cost is not only bandwidth.**

An L2 hit consumes an L2 read port. More subtly: under LRU, **the order in which
simultaneous hits are serviced is the recency stack.** Two hits to the same set in the
same cycle, serviced in either order, leave different victims - so a later fill evicts a
different line and every subsequent access diverges. Same config, same trace, different
hit rate. Hit ordering must be deterministic even when bandwidth is unbounded.

---

**D8. "L1 hit → immediately served" is a structural assumption where it should be a parameter.**

An L1 hit costs an L1 access latency and an L1 port slot. Setting both to zero is a
legitimate config (and is what makes the unbounded baseline collapse exactly), but it
must be reachable *by configuration*, not baked into the control flow.

---

**D9. "Access Cacheline" is singular; one core event is not one line.**

A trace event is a burst. Under a layout narrower than the burst width it expands to
several lines. So the unit of issue is a *set* of lines, and the model needs a stated
rule for partial success. See decision N7: bursts are atomic.

---

**D10. MSHR release and core completion are conflated.**

The L2 MSHR frees when the fill lands at the L2. The core finishes later: fill → L2
install → L2→L1 transfer → L1 install → L1→core return. Treating them as one instant
overstates MSHR occupancy, which softens exactly the bound (`l2_mshrs`) that the study
exists to measure.

---

**D11. No determinism rule.** Multiple events at the same cycle need a *total* order, or
two runs of one config differ and no sweep result is attributable.

**D12. No termination or deadlock detection.** An empty event queue with work still
outstanding is a bug, and under a sweep build it must fail loudly rather than exit
quietly or hang.

---

## Part 1. Modeling principles

Four rules. Everything downstream is a consequence of one of them.

**P1 - Time is carried by events, never by a loop.** The engine has no notion of "the
current tick". It has `now`, which is the timestamp of the event being dispatched, and it
is monotonically non-decreasing because the queue is a min-heap.

**P2 - Nothing predicts; everything subscribes.** No component ever computes when another
component will become available. A blocked request registers on the blocking structure;
the structure schedules the wake-up when it actually frees. This is what makes P1 sound -
a predicted time would be a second, unreliable clock.

**P3 - Contention is occupancy, not quota.** A shared resource is a *next-free
timestamp*, not a per-window counter. This is your Q2 decision and it has teeth:

```
QUOTA   (old):  16 lines/tick, 16 requests arrive  →  all 16 land at the same stamp
OCCUPANCY(new): II = 2 cycles,  16 requests arrive  →  land at t, t+2, t+4, ... t+30
```

The quota model reports zero serialization *within* a window and a cliff *between*
windows; both are artifacts of the window, which has no hardware counterpart. Occupancy
has no window and therefore no artifact. It also removes the last structure that would
have needed a periodic reset event - which is a tick loop by another name.

**P4 - Every crossing of a physical boundary is an event.** A request does not fall
through the hierarchy inside one function call. It is *accepted* by the L1 port, and
some cycles later an event fires that probes the L1 array. This matters for correctness,
not only for realism: the array state at the moment of the probe is the state that the
probe must see, and a recursive function evaluates it at the caller's timestamp instead.

---

## Part 2. Software → hardware mapping

The centre of this plan. Each row is a hardware structure, what it physically does, the
software object that stands for it, the parameters that shape it, and the statistic that
proves it is doing its job.

### 2.1 Compute side

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| PE / core issue stage | In-order. Issues one weight burst per trace event, stalls until it is served. An SNN PE has no reorder buffer. | `CoreState { cursor, tile, phase ∈ {Ready, Waiting, AtBarrier, Done}, ready_time }` | `core_model = stall_in_order` | `stall_cycles[c]`, issue-rate histogram |
| Weight address generator | Turns a tensor coordinate run into line indices | `AddressMapper::expand(Burst) → [LineId]` | `cin_block`, `cout_block`, `weight_bytes` | `lines_per_burst` distribution |
| Tile / activation refill | A new activation tile arrives machine-wide over DRAM or the NoC; all PEs restart together | Hard barrier + `tile_origin[]` (Part 5) | `tile_sync = hard` | `barrier_slack_cycles[c]` |

`phase` is a state field rather than a time field on purpose. At the instant a core is
refused, you must record *that* it is stalled; *when* it resumes is unknowable then - it
depends on a grant that has not happened. A single `ready_time` cannot express "waiting,
resume time unknown", which is the representational gap that forced D2's polling.

### 2.2 L1 - private, one per core

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| L1 tag + data array | Set-associative SRAM; a line may sit in any way of one set | `CacheArray { probe, free_slot, victim_candidates, insert, invalidate }` | `l1_size_bytes`, `l1_assoc` | hit rate, per-set pressure |
| L1 replacement state | LRU recency stack / FIFO counter / LFSR | `ReplacementPolicy { on_hit, on_fill, on_invalidate, pick_victim }` - a **separate module** from the array | `l1_policy ∈ {lru, fifo, random}` | victim age distribution |
| L1 access port | One tag+data access per cycle, pipelined | `Port { initiation_interval, latency, next_accept }` | `l1_latency`, `l1_ii` | port utilisation |
| L1 MSHR file | CAM over outstanding line addresses. Entry allocated on primary miss, freed on fill arrival - **held across the whole downstream round trip** | `MshrFile { entries[], pool_wait }` | `l1_mshrs` | occupancy histogram, max |
| MSHR target list | Fixed subentries recording who else wants this line | `Mshr::targets`, capacity-bounded | `l1_tgts_per_mshr` | max observed depth |
| MSHR deferred list | Requests that arrived after the target list filled; blocked on *this* entry | `Mshr::deferred` | - | max depth, resolve burst size |

The array/policy split is a hard boundary: the array knows geometry and holds no
recency, timestamps, or insertion order; the policy holds all of those and knows nothing
about sets or ways. The handle that crosses between them is a dense, stable `SlotId`, so
a policy indexes its own state with a flat vector and never computes a set index. This is
what lets one array serve LRU, FIFO, and Random unchanged.

`probe` is const and is **not** an access. The engine calls `policy.on_hit` explicitly.
Without this, a speculative lookup (e.g. "is this line already resident?") would perturb
the recency stack.

### 2.3 L2 - shared, banked

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| L2 tag + data array | Shared set-associative SRAM, banked by set index | `CacheArray` + `bank_of(line)` | `l2_size_bytes`, `l2_assoc`, `l2_banks` | hit rate |
| L2 replacement state | as L1 | `ReplacementPolicy` | `l2_policy` | victim age |
| L2 bank ports | Each bank accepts one access per II; banks are independent | `Port[l2_banks]` | `l2_latency`, `l2_ii` | per-bank utilisation, **bank-conflict cycles** |
| L2 MSHR file | Bounds the number of distinct lines in flight to off-chip memory. **This is the headline knob.** | `MshrFile` | `l2_mshrs` | occupancy histogram - the primary result |
| L2 targets / deferred | as L1 | `Mshr::targets` / `::deferred` | `l2_tgts_per_mshr` | max depth |
| Inclusion | An L2 eviction must invalidate the copy in every L1 that holds it | `back_invalidate(line)` over all L1 arrays + `policy.on_invalidate` | `inclusion = inclusive` | back-invalidation count, induced L1 misses |

Banking is new relative to the old plan and it is what occupancy buys you. Under a quota
model, "64 lines per tick" is a single scalar with no structure. Under occupancy,
`l2_banks × (1 / l2_ii)` is the same aggregate throughput but with a *conflict* behavior:
two accesses to the same bank serialize, two to different banks do not. Bank-conflict
cycles become a directly measurable quantity, and it is the quantity that distinguishes a
layout that spreads sets from one that piles them up.

### 2.4 Off-chip

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| Memory channel | Fixed round-trip latency, finite sustained bandwidth | `Port { ii = line_bytes / bytes_per_cycle, latency = l2_miss_latency }` | `dram_bytes_per_cycle`, `l2_miss_latency` | channel utilisation, queueing delay |

Separating `ii` from `latency` is what lets requests pipeline: a channel with 100-cycle
latency and 2-cycle II has 50 requests in flight, which is a completely different machine
from one that serializes 100-cycle round trips. Setting `ii = latency` recovers the
non-pipelined case, so one structure covers both.

### 2.5 Parameter translation from the old quota model

| Old (quota) | New (occupancy) | Note |
|---|---|---|
| `l2_fill_lines_per_tick = N` | `dram_bytes_per_cycle = N × line_bytes` | `dram.ii = line_bytes / bytes_per_cycle` |
| `l2_hit_lines_per_tick = M` | `l2_banks`, `l2_ii` | aggregate `= l2_banks / l2_ii`; adds conflict structure the scalar could not express |
| `unbounded` | `ii = 0` | a port with zero II never delays; a latency of 0 makes it invisible |
| *(absent)* | `l1_ii`, `l1_latency` | closes D8 |

### 2.6 Deliberately not modeled

Stated so a reviewer knows these are decisions, not oversights.

Writes, dirty bits, writebacks (weights are read-only in this study) · inter-L1 coherence
(no writers, so inclusion alone suffices) · DRAM row buffers, bank conflicts, refresh (the
channel is a bandwidth-plus-latency abstraction) · NoC topology and contention · prefetch
(deferred to v2, but the MSHR file already carries a `demand_reserve` field so it does not
need restructuring) · virtual memory and TLBs · the activation and output-feature path.

---

## Part 3. The revised control flow

### 3.1 Event alphabet

Six event kinds. Each one is a crossing of a physical boundary (P4).

| Event | Fires when | Does |
|---|---|---|
| `E_Issue(core)` | core is free and its next burst's issue time arrives | expands the burst, reserves L1 port, schedules `E_L1Probe` per line |
| `E_L1Probe(req)` | the L1 port accepted this request, `l1_latency` later | L1 array probe, then L1 MSHR triage |
| `E_L2Probe(req)` | the L2 bank port accepted it, `l2_latency` later | L2 array probe, then L2 MSHR triage |
| `E_L2Fill(mshr2)` | the memory channel returns data | install in L2 (victim, evict, **back-invalidate**), retire the entry, wake its waiters |
| `E_L1Fill(mshr1)` | data reaches the L1 | install in L1, retire the entry, wake its waiters, complete the core's line |
| `E_Barrier(tile)` | the last core clears tile `N` | set `tile_origin[N+1]`, schedule every core's `E_Issue` |

No `E_PortFree`. A port is a timestamp, not a queue - a request asks it for an accept
time and gets one immediately. That is the whole benefit of occupancy over quota.

### 3.2 The engine loop

```
run():
    seed the queue with E_Issue for every core at tile_origin[0] + local_tick(c, 0)

    while (!queue.empty()):
        e   = queue.pop_min()          # total order, Part 3.6
        now = e.time                   # monotonically non-decreasing
        dispatch(e)

    if (any core not Done || any MSHR live || any wait list non-empty):
        throw DeadlockError(diagnostic dump)   # D12; throw, not assert --
                                               # the sweep build is -DNDEBUG
```

That is the entire loop. There is no tick, no horizon, no scan over cores, and no
condition that has to be re-evaluated on a schedule.

### 3.3 Triage at a level - the corrected version of your sketch

One function per level. Called on **first arrival** and again on **every wake** (D4).

```
triage_L1(req, now):

    # --- array ---
    slot = l1[req.core].probe(req.line)
    if slot != NoSlot:
        l1_policy[req.core].on_hit(slot)
        complete_line(req, now)                       # D8: latency already paid
        return HIT

    # --- MSHR file ---
    e = l1_mshr[req.core].find(req.line)
    if e:
        if e.targets.size() < l1_tgts_per_mshr:
            e.targets.push(req)                       # secondary miss: no traffic
            return MERGED                             # D3: subscribes, computes nothing
        mark_refused(req, now)                        # 3.7: sets enqueue_time ONCE
        e.deferred.push(req)                          # D5: blocked on THIS entry
        return BLOCKED_TARGETS                        # NOT the same as BLOCKED_POOL

    if l1_mshr[req.core].full():
        mark_refused(req, now)
        l1_mshr[req.core].pool_wait.push(req)         # D2: registers, predicts nothing
        return BLOCKED_POOL                           # released by ANY entry retiring

    e = l1_mshr[req.core].allocate(req.line, req)     # primary miss
    accept = l2_bank[bank_of(req.line)].reserve(now)  # P3: occupancy
    schedule(E_L2Probe(e), accept + l2_latency)       # P4: crossing is an event
    return FORWARDED


triage_L2(e1, now):                                   # e1 is the L1 MSHR entry,
                                                      # which stays allocated throughout
    # --- array ---
    slot = l2.probe(e1.line)
    if slot != NoSlot:
        l2_policy.on_hit(slot)                        # D7: order matters, see 3.6
        schedule(E_L1Fill(e1), now + l2_to_l1_latency)
        return HIT

    # --- MSHR file ---
    e2 = l2_mshr.find(e1.line)
    if e2:
        if e2.targets.size() < l2_tgts_per_mshr:
            e2.targets.push(e1)                   # the ENTRY: everyone on it is
            return MERGED                         # satisfied together. e1 still held.
        mark_refused(e1.req, now)
        e2.deferred.push(e1.req)                  # the REQUEST, so it can re-triage
        return BLOCKED_TARGETS

    if l2_mshr.full():
        mark_refused(e1.req, now)
        l2_mshr.pool_wait.push(e1.req)            # e1 still held. Your call, kept.
        return BLOCKED_POOL

    e2 = l2_mshr.allocate(e1.line, e1)
    accept = dram.reserve(now)                    # P3
    schedule(E_L2Fill(e2), accept + l2_miss_latency)
    return FORWARDED
```

Compare against your sketch: the shape is preserved exactly, and every branch that used
to end in "add a next query time" or "return a release time" now ends in a `push` onto a
named structure. Nothing computes a future timestamp except at the two points where the
timestamp is genuinely determined - the port reservations.

### 3.4 Retire and wake - the half your sketch was missing

```
retire(entry e, level L, now):
    # 1. everyone who merged onto THIS entry. The line is resident now,
    #    so they are all hits, simultaneously (D5).
    for w in e.targets:   satisfy(w, now)
    for w in e.deferred:  reinject(w, level = L, now)      # re-triage; will hit
    e.deferred.clear(); e.targets.clear()

    L.mshr.free(e)

    # 2. the POOL waiters. One slot freed, so grant while slots remain.
    while L.mshr.has_free_slot() and !L.pool_wait.empty():
        w = L.pool_wait.pop_min()                          # (enqueue_time, core_id, seq)
        reinject(w, level = L, now)                        # re-triage from the top (D4)
```

This loop cannot livelock: the guard guarantees a free slot, and a re-triage with a free
slot available always resolves - hit, merge, defer, or allocate - so a popped request can
never land back on the list it was popped from.

### 3.5 The re-entry-level trap

**A woken request must re-enter at the level it was blocked at, not at the top of the
hierarchy.** This is a real bug-trap and it is worth naming:

| Woken from | Holds | Re-enter at | If you got this wrong |
|---|---|---|---|
| `l1_mshr.pool_wait` | nothing | **L1** | - |
| `l1_mshr[x].deferred` | nothing | **L1** | - |
| `l2_mshr.pool_wait` | its L1 MSHR entry | **L2** | re-triage at L1 finds *its own* entry and merges the request into itself - it waits for a fill that will never be requested |
| `l2_mshr[x].deferred` | its L1 MSHR entry | **L2** | same |

A re-injected request goes back through its level's **port** (it costs a real lookup),
and carries its **original enqueue timestamp** so FCFS order is not reset by the wake.

### 3.6 Total event order

```
key = (time, class, enqueue_time, core_id, seq)
```

`class` breaks ties between event kinds at the same cycle:

| class | events | why here |
|---|---|---|
| 0 | `E_L2Fill`, `E_L1Fill` | state changes land before anything looks at state |
| 1 | `E_Barrier` | the barrier observes completed fills |
| 2 | `E_L1Probe`, `E_L2Probe` | lookups see this cycle's fills - closes D4's "queued miss became a hit" |
| 3 | `E_Issue` | new demand enters last |

`seq` is a monotonic counter assigned at *schedule* time, so the order is total and a
re-run is byte-identical (D11). `enqueue_time` before `core_id` means a request refused
earlier beats a lower-indexed request refused later - FCFS first, index only as tiebreak.

This ordering is not cosmetic. Under LRU it *is* the eviction order (D7): two hits to one
set, serviced in either order, leave different victims and diverge permanently.

### 3.7 The five outcomes, and why `BLOCKED_TARGETS` is not `BLOCKED_POOL`

Triage returns one of five states, distinguished **only** by what releases them, because
that is what decides which structure holds the request.

| Outcome | Holds | Parked on | Released by | On release |
|---|---|---|---|---|
| `HIT` | nothing | nothing | already served | terminal |
| `MERGED` | nothing | `e.targets` | `e` retiring | satisfied directly, **no re-triage** |
| `BLOCKED_TARGETS` | nothing | `e.deferred` | **that** entry retiring | re-triage, **always a hit** |
| `BLOCKED_POOL` | nothing | `F.pool_wait` | **any** entry retiring | re-triage, outcome unknown |
| `FORWARDED` | a new entry | nothing | its own fill | terminal at this level |

Two collapses look tempting and both are wrong.

**`MERGED` vs `BLOCKED_TARGETS`** wait on the same entry, so they look alike. They are
not: `MERGED` holds a committed subentry and the fill satisfies it directly, while
`BLOCKED_TARGETS` holds nothing and must go back through the port and re-probe. Counting
a deferred waiter as merged overstates target-list utilisation, which is the one number
`l2_tgts_per_mshr` is being swept to find.

**`BLOCKED_TARGETS` vs `BLOCKED_POOL`** are both "blocked", so they look alike. They are
released by *different events*, and merging their lists livelocks the grant loop: an
unrelated entry retires, the loop pops a `BLOCKED_TARGETS` request whose target list is
**still full**, it re-blocks onto the same list, and the freed pool slot is never
consumed. This is D5, and it is the reason for three structures rather than two.

There is a third, quieter reason the distinction is load-bearing. Because targets in a
read-only cache are satisfied only by the fill, a target list **never drains
incrementally** and `e.deferred` is never promoted into `e.targets`. The whole deferred
set resolves at once, at retire, as hits. A model that promotes on a free target slot is
modelling a drain that cannot happen.

### 3.8 Priority: aged requests beat fresh ones, everywhere

One key, and its single rule is that it is **never rewritten**:

```
key(r)          = (r.enqueue_time, r.core_id, r.seq)
r.enqueue_time := now  on FIRST refusal at any level; never reassigned, ever
```

It is applied at three points, which must agree or the ordering is not total:

1. `pool_wait.pop_min()`, deciding who gets a freed slot;
2. the event-queue tiebreak at equal timestamps (3.6), deciding whether a woken request
   or a fresh arrival probes first;
3. port reservation order, which follows from (2) since reservation happens inside the
   dispatched event.

```
cycle 100  R_old refused        -> enqueue_time = 100
cycle 500  R_old woken          -> event key (500, class 2, 100, ...)
cycle 500  R_new first arrival  -> event key (500, class 2, 500, ...)
           100 < 500            -> R_old probes first
```

If `enqueue_time` were reset on wake, `R_old` would lose to every fresh arrival at high
load, forever. Preserving it is what makes the model starvation-free, and it is also
what makes the FCFS claim honest across a level crossing: a request refused at the L1
pool and later refused again at the L2 pool carries its **original** timestamp, giving it
seniority at L2 that reflects how long it has genuinely been waiting.

**There is deliberately no rule ranking deferred waiters above pool waiters, or either
above fresh arrivals.** They are all re-injected as events at the same timestamp and the
one key sorts them. Section 10 of the pseudocode companion works an example where a pool
waiter is interleaved between two deferred waiters purely by age.

**Grant is reservation-based, not optimistic.** `try_grant` pops at most
`capacity - live - reserved` waiters and marks each with a reservation, so a wake never
produces a thundering herd of requests racing for one slot. A grantee that turns out not
to need its slot (it re-triaged into a hit or a merge) releases the reservation, which
immediately grants the next waiter. Full mechanics in the companion, sections 8 and 9.

> Complete pseudocode for every path above:
> `log/2026-08-13-wcache-control-flow-pseudocode.md`.

---

## Part 4. Two structural decisions worth arguing about

### 4.1 `stall_in_order` bounds the wait lists - and is the only thing that does

Under `core_model = stall_in_order`, a core with an outstanding burst issues nothing
further. Demand stops **at the source**, so no queue ever has to refuse anyone upstream,
and:

```
Σ |pool_wait| + Σ |targets| + Σ |deferred|   ≤   cores × lines_per_burst
```

At 1024 cores and a burst of 4, that is 4096 entries - nothing. So the wait lists can be
unbounded, and `l1_mshrs` / `l2_mshrs` remain the *only* concurrency bounds in the model,
which is what makes a sweep result attributable to one of them.

**This is a coupling, and it must be written down:** swap in a run-ahead core or a
decoupled prefetch engine and the lists grow without bound, hide the real bottleneck, and
need a depth limit after all. `core_model` and "wait lists are unbounded" are one
decision, not two.

### 4.2 Consequence of holding the L1 MSHR across the L2 wait

Your call (kept) means L1 MSHR occupancy is the **full round trip including L2 queueing
delay**, not just the L1→L2 latency. Two things follow:

- `l1_mshrs` becomes coupled to `l2_mshrs`: L2 pressure lengthens L1 occupancy. A sweep
  must report both, and a result attributed to `l1_mshrs` alone is suspect.
- Under `stall_in_order` with a single-line burst, `l1_mshrs > 1` is inert by
  construction. The pool binds only when a burst expands to more lines than the pool
  holds, or when a core issues multiple events per tick. Both are permitted by the trace
  format; neither occurs in the current corpus. **`l1_mshrs` should be reported as
  inert-by-construction rather than swept**, unless the layout sweep produces
  `lines_per_burst > 1`, which a narrow `cout_block` does.

---

## Part 5. Time, and why `tick_base` does not enter the engine

The old spec had "two clocks" (trace time and simulated time) and most of its defects
lived at the seam. The barrier decision lets that seam be removed entirely.

**Trace time is only ever tile-local.** The engine never uses `tick_base`. Instead:

```
tile_origin[0]   = 0
tile_origin[N+1] = max over cores of their tile-N completion time     (simulated)

issue_time(c) = max( tile_origin[tile(c)] + local_tick(c, cursor),
                     ready_time[c] )
```

`tile_origin` is a **measured** quantity that replaces `tick_base`, a *derived* one. This
gives three things at once:

1. **One clock.** `local_tick` is an offset, never an absolute, so there is no expression
   in which trace time and simulated time are added and compared. The type confusion the
   old spec flagged as an open risk cannot be written.
2. **A free regression.** Under the unbounded baseline, `tile_origin[N]` must equal
   `tick_base[N]` exactly, for every tile. That is a strong, cheap, whole-run oracle.
3. **A free result.** `tile_origin[N] − tick_base[N]` is the accumulated stretch at tile
   `N`, per tile, at no extra instrumentation cost.

The barrier is implemented as a countdown, not a scan: each tile holds `cores_remaining`;
a core clearing the tile decrements it and parks in `AtBarrier`; the decrement that
reaches zero schedules `E_Barrier`, which sets `tile_origin[N+1] = now` and schedules an
`E_Issue` for every core. No polling, and `barrier_slack_cycles[c] = tile_origin[N+1] −
(c's own tile-N completion)` falls out as the cost of the lock-step assumption.

---

## Part 6. Named decisions requiring sign-off

| # | Decision | Consequence if reversed |
|---|---|---|
| N1 | **Events only.** No tick loop, no per-window counters, no periodic reset. | reintroduces D1 |
| N2 | **Subscribe, never predict.** No component computes another's availability. | reintroduces D2, D3 |
| N3 | **Occupancy, not quota.** Every shared resource is `{ii, latency, next_accept}`. | reintroduces window artifacts; `l2_banks` loses meaning |
| N4 | **Hard tile barrier.** Tile `N+1` begins when the last core clears tile `N`. | `tile_origin` undefined; needs a new global clock story |
| N5 | **Re-triage on wake**, from the blocked level, preserving enqueue timestamp. | double-allocated MSHRs; hits served for evicted lines |
| N6 | **Three wait structures**: pool wait, per-entry deferred, and nothing else. | grant loop livelocks |
| N7 | **Bursts are atomic** - all lines placed or the core retries the whole burst. Config load rejects `lines_per_burst > l1_mshrs` with a `throw` (survives `-DNDEBUG`). | a half-issued burst and a much larger core state machine |
| N8 | **Inclusive L2**, with back-invalidation on eviction. | L1 serves lines the L2 has dropped |
| N9 | **`stall_in_order`**, and therefore unbounded wait lists. The two are one decision. | wait lists need depth limits, adding a third concurrency bound |
| N10 | **Total event order** `(time, class, enqueue_time, core_id, seq)`. | non-reproducible sweeps |
| N11 | **A trace coordinate outside `workload_dims` aborts the run**, naming tile/tick/core/coord. | silently drops demand; corrupts every downstream statistic |
| N12 | **Strong typedefs** for `SimTime` and `LocalTick` from day one. | the class of bug the old spec left open at unit 4 |

---

## Part 7. Rebuild schedule

Ten units, four phases. Nothing from the old tree is reused. Each unit ends with its own
tests **and a mutation check** - the prior effort learned the hard way that 125 passing
checks hid 6 live mutations, so "tests pass" is not the exit criterion; "tests fail when
the code is wrong" is.

### Phase A - untimed foundations *(no clock exists yet)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **A1** | `types.h`: `LineId`, `CoreId`, `SlotId`, strong `SimTime` / `LocalTick` (N12), `Coord`, `Burst`, `WeightShape` | round-trip and boundary tests; a `SimTime`/`LocalTick` mix fails to compile |
| **A2** | `AddressMapper` + `BlockPackMapper`: `expand`, `locate`, `line_of` | out-of-range coordinate throws before any output is produced; `line == tag × num_sets + set_index` holds |
| **A3** | `TraceReader`: format v2 headers, tile/tick/core/burst decode, `spatial_factors` core decode | reads a real corpus file; malformed header throws (N11) |
| **A4** | `CacheArray` + `SetAssociativeArray` with **`invalidate` in the interface from the start** (N8) | probe/free_slot/victim_candidates/insert/invalidate; non-exact size÷(line×assoc) throws |
| **A5** | `ReplacementPolicy` + LRU, FIFO, Random | policy sees only `SlotId`; all three drive one array unchanged; Random is seeded and reproducible |

Phase A gate: an **untimed reference model** (array + policy only, no MSHRs, no time) that
reports hit rates. This is the oracle Phase C is checked against - the single most
valuable artifact of the rebuild, and the thing the previous effort did not have.

### Phase B - timing primitives *(clock exists, hierarchy does not)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **B1** | `Port { ii, latency, next_accept, reserve() }` | occupancy arithmetic; `ii = 0` never delays; `ii = latency` serializes |
| **B2** | `EventQueue`: min-heap on `(time, class, enqueue_time, core_id, seq)` (N10) | total order; two identical runs produce identical event logs |
| **B3** | `MshrFile`: entries, `targets`, `deferred`, `pool_wait`, `find/allocate/retire`, the grant loop | grant loop terminates with a free slot; deferred set resolves atomically on retire |

### Phase C - the engine

| Unit | Contents | Exit criterion |
|---|---|---|
| **C1** | `CacheLevel` = array + policy + port + MSHR file; `triage()` per level | triage table (Part 3.3) exercised branch by branch |
| **C2** | The six event handlers; `retire`/`reinject` with the re-entry-level rule (3.5) | the V-list below |
| **C3** | Tile barrier, `tile_origin`, core state machine | `tile_origin == tick_base` under the unbounded baseline |
| **C4** | Inclusive back-invalidation across L1s (N8) | an L2 eviction of a line held in another core's L1 invalidates it |

### Phase D - harness

| Unit | Contents | Exit criterion |
|---|---|---|
| **D1** | Config load + validation (N7, N11), single source of truth for the parameter set | every invalid combination throws under `-DNDEBUG` |
| **D2** | Statistics and the results CSV | every stat in Part 8 emitted, one row per config |
| **D3** | Sweep driver | a full grid point runs end to end and reproduces byte-identically |

**Critical path:** A1 → A2 → A4 → A5 → *(Phase A gate)* → B3 → C1 → C2. A3, B1, and B2
are independent of that chain and can be built in parallel with it. C4 depends on C2. All
of Phase D depends on C2.

### Verification list

| # | Fixture | Asserts |
|---|---|---|
| V1 | unbounded baseline, full trace | `tile_origin[N] == tick_base[N]` for every tile; hit counts equal the Phase-A reference model |
| V2 | core stalled across trace ticks 5-39 | all 36 events issued, none dropped |
| V3 | any sweep point, re-run | byte-identical event log (N10) |
| V4 | two blocked requests, same line | exactly one MSHR ever allocated for it |
| V5 | queued miss; another core's fill lands that line first | resolves as a hit, consumes no MSHR (D4) |
| V6 | queued L2 hit whose line is evicted before service | re-probes to a miss, keeps its enqueue timestamp (D4) |
| V7 | target list at capacity, entry retires | **all** deferred waiters resolve at once, none allocates (D5) |
| V8 | two hits, one set, one cycle, LRU | eviction order matches service order (D7) |
| V9 | L2 evicts a line another core's L1 holds | that L1 is invalidated; its next access misses (N8) |
| V10 | full sweep point | wait-list occupancy never exceeds `cores × lines_per_burst` (4.1) |
| V11 | request woken from `l2_mshr.pool_wait` | re-enters at **L2**, does not merge into its own L1 entry (3.5) |
| V12 | `lines_per_burst > l1_mshrs` | throws at config load, under `-DNDEBUG` (N7) |
| V13 | any run | every issued line request reaches exactly one terminal state; no request is lost or double-counted |
| V14 | any run | port busy-cycles ≤ elapsed cycles × port count |
| V15 | coordinate outside `workload_dims` | aborts, naming tile/tick/core/coord (N11) |

V1's second clause is the one that repays the rebuild: an independent untimed model
agreeing with the DES on hit counts is a far stronger oracle than any unit test, and it
exists only because Phase A is being built fresh rather than inherited.

---

## Part 8. What the run reports

Beyond hit rates and cycles:

**Concurrency** - MSHR occupancy histogram per level (the headline result), max observed
target depth, max deferred depth, pool-wait length distribution, grant latency
distribution, fraction of grants that re-triaged into a hit or merge rather than an
allocate.

**Contention** - per-bank L2 utilisation, bank-conflict cycles, memory-channel
utilisation and queueing delay, L1 port utilisation.

**Time** - per-tile `tile_origin − tick_base` (stretch), `barrier_slack_cycles` per core,
per-core stall attribution split by cause: `{L1 pool, L1 targets, L2 pool, L2 targets,
L2 port, channel, barrier}`. The stall breakdown must sum to total stall - that is a V13-
class invariant, not a reporting convenience.

**Model health** - `hits_downgraded_to_miss` (D4, second row), back-invalidations and the
L1 misses they induced, event count and events per simulated cycle (the cost win over the
tick model, measured rather than claimed).

---

## Part 9. Open questions for review

1. **`l1_mshrs` sweep.** Part 4.2 argues it is inert by construction under the current
   corpus and should be reported rather than swept. Confirm, or name the layout points
   that make it bind.
2. **L2 banking granularity.** Bank by low bits of the set index (spreads consecutive
   lines) or by high bits (keeps a core's working set in one bank)? These give opposite
   conflict behavior and the choice interacts with the `cin_block`/`cout_block` sweep.
3. **`l2_to_l1_latency`** is a new parameter implied by D10 and does not exist in the old
   table. Is it a separate knob or `l2_latency` reused?
4. **Prefetch.** Deferred to v2 here. The MSHR file carries a `demand_reserve` field so it
   does not need restructuring later - confirm that is the right amount of forward
   provision.
5. **Random policy reproducibility** across a parallel sweep: seed per-run, or per
   (config, trace) pair?
