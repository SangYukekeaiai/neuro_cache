# 2026-08-14 wcache: event-driven rebuild plan, v2

> **Superseded 2026-08-17 by `log/2026-08-17-wcache-event-driven-plan-v3.md`. Do not implement
> against this file.** It is kept as the record of what was signed off on 08-14. v3 reverses
> nothing here; it adds C1, the core's one-burst-at-a-time self-timed schedule (v3 sections 4.5,
> D13, N14), and C2, the pluggable issue policy that separates fetch time from service time (v3
> sections 4.6, D14, N15, N16).

**Status: proposal, for review. No code is to be written against this until it is signed off.**

Supersedes `log/2026-08-13-wcache-event-driven-plan.md` in full, and with it everything
under `log/2026-08-05-cachesim-redesign-plan.md` Parts 2-6 and all of
`log/2026-08-11-engine-full-spec.md`. The companion pseudocode
(`2026-08-13-wcache-control-flow-pseudocode.md`) and its explainer
(`2026-08-13-wcache-pseudocode-explained.md`) remain valid except where Appendix C lists a
correction; Part 3 here is the authority where they disagree.

The existing tree (`src/wcache/native/`, units 1-3, 171 checks) is **not** carried forward
as code.

**What is new in v2.** Nothing is reversed. Six things are corrected or strengthened:

| # | Topic | v1 | v2 |
|---|---|---|---|
| R1 | Wait-list bounds | bounded because `stall_in_order` caps the total, and 4096 entries is small | the lists have **no storage at all**; they are views over structures that already exist. Per-list bound tightens to `n_cores` (4.1) |
| R2 | Arbitration | the 5-tuple key | the key implements **FIFO by first refusal**. Collapses to `(refused_bit, counter)` (3.8) |
| R3 | Wait structures | "three wait structures" (N6) | **one wait population, indexed by reason**. Same code, honest hardware description (3.7) |
| R4 | `ii` | throughput (N3) | correct, and `ii` **does** produce back-pressure, of the rate kind only. It makes wait sets longer, not shorter (4.3) |
| R5 | Inclusion | required; back-invalidation mandatory (N8, D6) | a **choice with no coherence justification in this study**. Now a swept knob (4.4) |
| R6 | Naming | `deferred`, `pool_wait` | `line_wait`, `slot_wait`. The old name collides with gem5 and means something different there (Appendix B) |

---

## Part 0. Verdict on the sketched control flow

The control flow originally sketched is **structurally correct in its probe order and in
its three-way MSHR classification**, which are the two things homegrown cache models most
often get wrong. It is **not** an event-driven model, and three of its steps ask for
information that does not exist at the moment they ask for it.

### What is right, and survives verbatim

1. **The probe order: array → own-level MSHR → next level.** Exactly gem5's order and
   exactly the hardware's. Checking the MSHR file *before* forwarding is what makes a
   secondary miss cost zero downstream traffic; a model that forwards first and merges
   later reports inflated off-chip traffic.

2. **The three-way MSHR outcome: `blocked` / `hit` / `miss`.** Most models collapse this to
   two, which silently allocates a second MSHR for a line that already has one when the
   target list is full.

3. **"If L2MSHR blocked: stay in L1 MSHR."** Right, and the non-obvious call. An L1 MSHR
   entry is allocated at miss *detection* and freed at fill *arrival*, held across the
   entire downstream round trip. Holding it is what makes L1 MSHR occupancy mean something,
   and in v2 it turns out to be what makes the wait sets free (4.1).

4. **The instinct that a resolved request "returns a time."** Correct for the paths where
   the time is actually determined. See D3 for the paths where it is not.

### What is broken

Twelve defects, in descending order of how much they change the design.

**D1. `For Core [0 : core-number]` is the tick model wearing a disguise.** Scanning every
core per unit of time is `O(cores × simulated_cycles)`. At 1024 cores that is the exact
blow-up being escaped; the loop does not care that the outer variable is called an "event".

In a discrete-event simulator **you never iterate over cores.** You pop the earliest entry
from a priority queue. A stalled core has no scheduled event: it is *referenced* by the
structure it waits on, and that structure schedules its wake-up. Cost becomes `O(E log E)`
in the number of events, independent of how far the timeline stretches.

→ **Fix:** the outer loop is `while (!queue.empty()) { e = queue.pop_min(); dispatch(e); }`.

**D2. "add a next possible queue time" is polling, and there is no correct value for it.** A
blocked request cannot know when its resource frees. Guess early and it re-blocks, burning
events and risking livelock; guess late and you have invented stall time. Either way the
number is fiction that lands directly in the quantity being measured.

The resource *does* know when it frees, at the instant it frees. Invert the direction: the
blocked request **registers** and computes nothing.

→ **Fix:** replace every "add next query time" with "register on the thing you are blocked
on." Zero polling, zero predicted times, and the registration is also the occupancy
instrument the sweep wants.

**D3. Three branches return a time that is not knowable at that point.** `If L1MSHR hit:
add the scheduled serve time` reads a field that has not been written, because the primary
may itself be parked on the L2. Same one level down, and `If L2MSHR blocked: add next query
time` is D2 again.

→ **Fix:** a merging request does not compute a completion time. It **subscribes**. The time
is *delivered to it* by the fill event.

**D4. A decision made at block time is not valid at service time.**

| At block time | While it waits | At service time |
|---|---|---|
| classified **L2 miss**, wants an MSHR | another core's fill lands that line | now a **hit**; allocating would double-fetch |
| classified **L2 hit**, wants a port | the line is chosen as a victim | now a **miss**; serving it as a hit reports data that is not there |

→ **Fix**, as a hard rule:

> **Anything that waits re-triages from the top of its level when it wakes. It never acts on
> the classification it held when it blocked.** It carries its original refusal stamp, so
> ordering stays honest even though the classification changed.

**D5. `target++` is unbounded, and overflow has a different release condition.** Real MSHRs
have a fixed number of subentries. A request arriving at a full target list does not merge
and does not join the slot queue: it waits on **that specific entry**.

| Waiting for | Released when | On release |
|---|---|---|
| *any* MSHR entry (`SLOT`) | any entry retires | grant **one** per freed slot |
| *this* entry's line (`LINE`) | *that* entry retires | **all** of them resolve at once, as hits |

The two release conditions must stay distinguishable. Waking a `LINE` waiter on an
unrelated retire livelocks the grant loop: it re-blocks, is popped again, and the freed slot
is never consumed. v1 called this "two lists"; v2 calls it one population with a wait
reason (3.7). The reason is what prevents the livelock; two indexes are one way to carry it.

**D6. There is no fill path. Nothing is ever installed, evicted, or invalidated.** Missing:
victim selection (free way first, only then the policy); the eviction and its effect on
replacement state; and **back-invalidation under `inclusion = inclusive`**, since the L2 is
shared and a core's fill can evict a line another core's L1 still holds. This is reachable
in a four-access example, not a corner case.

*v2 correction:* v1 stated this as "an L2 eviction **must** invalidate the copies in other
cores' L1s". Sharedness is why the scan must cover *all cores*; it is not why you must
invalidate at all. Under `non_inclusive` you do not, and the L1 legitimately keeps serving
lines the L2 dropped. See 4.4.

**D7. An L2 hit is treated as free.** It consumes an L2 read port, and more subtly: under
LRU, **the order in which simultaneous hits are serviced is the recency stack.** Two hits to
one set in one cycle, serviced in either order, leave different victims, so a later fill
evicts a different line and every subsequent access diverges. Hit ordering must be
deterministic even when bandwidth is unbounded.

**D8. "L1 hit → immediately served" is a structural assumption where it should be a
parameter.** An L1 hit costs an L1 access latency and a port slot. Zero for both is a
legitimate config and is what makes the unbounded baseline collapse exactly, but it must be
reachable *by configuration*.

**D9. "Access Cacheline" is singular; one core event is not one line.** A trace event is a
burst; under a layout narrower than the burst width it expands to several lines. The unit of
issue is a *set* of lines and needs a stated rule for partial success. See N7.

**D10. MSHR release and core completion are conflated.** The L2 MSHR frees when the fill
lands at the L2. The core finishes later: fill → L2 install → L2-to-L1 transfer → L1 install
→ return. Treating them as one instant overstates MSHR occupancy, softening exactly the
bound (`l2_mshrs`) the study exists to measure.

**D11. No determinism rule.** Multiple events at one cycle need a *total* order.

**D12. No termination or deadlock detection.** An empty event queue with work outstanding is
a bug and must fail loudly under a sweep build.

---

## Part 1. Modeling principles

Five rules. Everything downstream is a consequence of one of them.

**P1. Time is carried by events, never by a loop.** The engine has no "current tick". It has
`now`, the timestamp of the event being dispatched, monotonically non-decreasing because the
queue is a min-heap.

**P2. Nothing predicts; everything subscribes.** No component computes when another will
become available. A blocked request registers; the structure schedules the wake-up when it
actually frees. This is what makes P1 sound: a predicted time is a second, unreliable clock.

**P3. Contention is occupancy, not quota.** A shared resource is a *next-free timestamp*,
not a per-window counter.

```
QUOTA    (old):  16 lines/tick, 16 requests arrive  →  all 16 land at the same stamp
OCCUPANCY(new):  ii = 2 cycles,  16 requests arrive  →  land at t, t+2, t+4, ... t+30
```

The quota model reports zero serialization *within* a window and a cliff *between* windows;
both are artifacts of the window, which has no hardware counterpart. Occupancy has no window
and therefore no artifact, and it removes the last structure that would have needed a
periodic reset event, which is a tick loop by another name.

**P4. Every crossing of a physical boundary is an event.** A request does not fall through
the hierarchy inside one function call. It is *accepted* by the L1 port, and some cycles
later an event fires that probes the L1 array. This matters for correctness, not only
realism: the array state at the moment of the probe is what the probe must see, and a
recursive function evaluates it at the caller's timestamp instead.

**P5 (new in v2). Waiting is a state of an existing structure, never a new one.** A request
that is refused is already held somewhere: at the L2 by its own L1 MSHR entry, at the L1 by
its core's outstanding-burst registers. A wait list therefore stores nothing; it selects. It
is a bit and a reason field on a structure that already exists, plus an ordering rule. Any
design that allocates fresh storage to hold a refused request has invented hardware. This is
the principle that makes 4.1's bound a hardware argument rather than a memory-footprint one.

---

## Part 2. Software to hardware mapping

The centre of this plan. Each row is a hardware structure, what it physically does, the
software object that stands for it, the parameters that shape it, and the statistic that
proves it is doing its job.

### 2.1 Compute side

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| PE / core issue stage | In-order. Issues one weight burst per trace event, stalls until served. An SNN PE has no reorder buffer. | `CoreState { cursor, tile, phase ∈ {Ready, Waiting, AtBarrier, Done}, ready_time }` | `core_model = stall_in_order` | `stall_cycles[c]`, issue-rate histogram |
| Weight address generator | Turns a tensor coordinate run into line indices | `AddressMapper::expand(Burst) → [LineId]` | `cin_block`, `cout_block`, `weight_bytes` | `lines_per_burst` distribution |
| Tile / activation refill | A new activation tile arrives machine-wide; all PEs restart together | Hard barrier + `tile_origin[]` (Part 5) | `tile_sync = hard` | `barrier_slack_cycles[c]` |

`phase` is a state field rather than a time field on purpose. At the instant a core is
refused you must record *that* it is stalled; *when* it resumes is unknowable then. A single
`ready_time` cannot express "waiting, resume time unknown", which is the representational gap
that forced D2's polling.

### 2.2 L1: private, one per core

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| L1 tag + data array | Set-associative SRAM; a line may sit in any way of one set | `CacheArray { probe, free_slot, victim_candidates, insert, invalidate }` | `l1_size_bytes`, `l1_assoc` | hit rate, per-set pressure |
| L1 replacement state | LRU recency stack / FIFO counter / LFSR | `ReplacementPolicy { on_hit, on_fill, on_invalidate, pick_victim }`, a **separate module** from the array | `l1_policy ∈ {lru, fifo, random}` | victim age distribution |
| L1 access port | One tag+data access per `ii`, pipelined | `Port { ii, latency, next_accept }` | `l1_latency`, `l1_ii` | port utilisation |
| L1 MSHR file | CAM over outstanding line addresses. Allocated on primary miss, freed on fill arrival, **held across the whole downstream round trip** | `MshrFile { entries[], slot_wait }` | `l1_mshrs` | occupancy histogram, max |
| MSHR target list | Fixed subentries recording who else wants this line | `Mshr::targets`, capacity-bounded | `l1_tgts_per_mshr` | max observed depth |
| MSHR line-wait set | Requests that arrived after the target list filled; waiting on *this* entry's line. **Not storage:** at the L1 these live in the core's burst registers (P5, 4.1) | `Mshr::line_wait` | - | max depth, resolve burst size |

The array/policy split is a hard boundary: the array knows geometry and holds no recency,
timestamps, or insertion order; the policy holds all of those and knows nothing about sets or
ways. The handle that crosses between them is a dense, stable `SlotId`, so a policy indexes
its own state with a flat vector and never computes a set index. This is what lets one array
serve LRU, FIFO, and Random unchanged.

`probe` is const and is **not** an access. The engine calls `policy.on_hit` explicitly.
Without this, a speculative lookup would perturb the recency stack.

### 2.3 L2: shared, banked

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| L2 tag + data array | Shared set-associative SRAM, banked by set index | `CacheArray` + `bank_of(line)` | `l2_size_bytes`, `l2_assoc`, `l2_banks` | hit rate |
| L2 replacement state | as L1 | `ReplacementPolicy` | `l2_policy` | victim age |
| L2 bank ports | Each bank accepts one access per `ii`; banks are independent | `Port[l2_banks]` | `l2_latency`, `l2_ii` | per-bank utilisation, **bank-conflict cycles** |
| L2 MSHR file | Bounds the number of distinct lines in flight to off-chip memory. **This is the headline knob.** | `MshrFile` | `l2_mshrs` | occupancy histogram, the primary result |
| L2 targets / line-wait | as L1. **Not storage:** at the L2 these live in the L1 MSHR entries the requests still hold (P5, 4.1) | `Mshr::targets` / `::line_wait` | `l2_tgts_per_mshr` | max depth |
| Inclusion | Under `inclusive`, an L2 eviction invalidates the copy in every L1 that holds it. Under `non_inclusive`, it does not. **A swept parameter, not an invariant** (4.4) | `back_invalidate(line)` over all L1 arrays + `policy.on_invalidate` | `inclusion ∈ {inclusive, non_inclusive}` | back-invalidation count, induced L1 misses, effective capacity |

Banking is what occupancy buys. Under a quota model, "64 lines per tick" is a single scalar
with no structure. Under occupancy, `l2_banks × (1 / l2_ii)` is the same aggregate throughput
with a *conflict* behavior: two accesses to the same bank serialize, two to different banks do
not. Bank-conflict cycles become directly measurable, and that is the quantity distinguishing
a layout that spreads sets from one that piles them up.

### 2.4 Off-chip

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| Memory channel | Fixed round-trip latency, finite sustained bandwidth | `Port { ii = line_bytes / bytes_per_cycle, latency = l2_miss_latency }` | `dram_bytes_per_cycle`, `l2_miss_latency` | channel utilisation, queueing delay |

Separating `ii` from `latency` is what lets requests pipeline: a channel with 100-cycle
latency and 2-cycle `ii` has 50 requests in flight, a completely different machine from one
that serializes 100-cycle round trips. Setting `ii = latency` recovers the non-pipelined case,
so one structure covers both.

### 2.5 Parameter translation from the old quota model

| Old (quota) | New (occupancy) | Note |
|---|---|---|
| `l2_fill_lines_per_tick = N` | `dram_bytes_per_cycle = N × line_bytes` | `dram.ii = line_bytes / bytes_per_cycle` |
| `l2_hit_lines_per_tick = M` | `l2_banks`, `l2_ii` | aggregate `= l2_banks / l2_ii`; adds conflict structure the scalar could not express |
| `unbounded` | `ii = 0` | a port with zero `ii` never delays; `latency = 0` makes it invisible. **Not a physical setting**, see 4.3 |
| *(absent)* | `l1_ii`, `l1_latency` | closes D8 |

### 2.6 Deliberately not modeled

Stated so a reviewer knows these are decisions, not oversights.

Writes, dirty bits, writebacks (weights are read-only in this study) · inter-L1 coherence
(**no writers, so there is nothing to keep coherent; note that this also removes the usual
justification for inclusion, see 4.4**) · peer-L1 forwarding (the one thing `non_inclusive`
would want and does not have, 4.4) · DRAM row buffers, bank conflicts, refresh (the channel is
a bandwidth-plus-latency abstraction) · NoC topology and contention · prefetch (deferred to v2
of the model, but the MSHR file already carries a `demand_reserve` field so it does not need
restructuring) · virtual memory and TLBs · the activation and output-feature path · **finite
bank input queues**: port serialization is timed correctly at `k × ii` but costs nothing
structurally, because requests waiting on a bank live as scheduled future events rather than in
a queue with a depth (4.3).

---

## Part 3. The control flow

### 3.1 Event alphabet

Six event kinds. Each is a crossing of a physical boundary (P4).

| Event | Fires when | Does |
|---|---|---|
| `E_Issue(core)` | core is free and its next burst's issue time arrives | expands the burst, reserves L1 port, schedules `E_L1Probe` per line |
| `E_L1Probe(req)` | the L1 port accepted this request, `l1_latency` later | L1 array probe, then L1 MSHR triage |
| `E_L2Probe(req)` | the L2 bank port accepted it, `l2_latency` later | L2 array probe, then L2 MSHR triage |
| `E_L2Fill(mshr2)` | the memory channel returns data | install in L2 (victim, evict, back-invalidate if `inclusive`), retire the entry, wake its waiters |
| `E_L1Fill(mshr1)` | data reaches the L1 | install in L1, retire the entry, wake its waiters, complete the core's line |
| `E_Barrier(tile)` | the last core clears tile `N` | set `tile_origin[N+1]`, schedule every core's `E_Issue` |

No `E_PortFree`. A port is a timestamp, not a queue: a request asks it for an accept time and
gets one immediately. That is the whole benefit of occupancy over quota.

### 3.2 The engine loop

```
run():
    seed the queue with E_Issue for every core at tile_origin[0] + local_tick(c, 0)

    while (!queue.empty()):
        e   = queue.pop_min()          # total order, 3.6
        now = e.time                   # monotonically non-decreasing
        dispatch(e)

    if (any core not Done || any MSHR live || any wait set non-empty):
        throw DeadlockError(diagnostic dump)   # D12; throw, not assert:
                                               # the sweep build is -DNDEBUG
```

There is no tick, no horizon, no scan over cores, and no condition re-evaluated on a schedule.

### 3.3 State

```
Request:
    core, line, seq
    refusal   = NONE       # global refusal COUNTER value, not a tick. Set once. 3.8
    reason    = NONE       # SLOT | LINE(L), set at refusal. 3.7
    level     = L1         # where to RE-ENTER on wake. 3.5
    mshr1     = null       # the L1 entry it holds, once FORWARDED at L1
    reserved  = false      # holds a slot-grant reservation

Mshr:
    line, core                   # core unused at L2
    targets   = []               # bounded by tgts_per_mshr
                                 # L1: Requests;  L2: Mshr entries. Bijective, see I6b
    line_wait = []               # index into the wait population, reason == LINE(line)
                                 # NOT storage. L2 waiters live in L1 MSHRs; L1 waiters
                                 # live in core burst registers. P5, 4.1

MshrFile:                        # one per L1, one shared L2
    entries   = {}               # line -> Mshr, bounded by capacity
    slot_wait = []               # index into the wait population, reason == SLOT
    reserved  = 0                # granted-but-not-yet-dispatched slots

Port:                            # l1_port[c], l2_bank[b], dram
    ii, latency, next_accept     # ii = initiation interval, physically >= 1. 4.3

CoreState:
    cursor, tile, phase, pending_lines

refusal_counter                  # global monotonic; stamps Request.refusal. 3.8
tile_origin[]                    # simulated origin of each tile (Part 5)
```

`slot_wait` and `line_wait` are two indexes into **one** logically FIFO-ordered population
(3.7). The merge at 3.4 is an index join, not a priority reconciliation.

### 3.4 Triage, retire, wake

One triage function per level, called on **first arrival** and again on **every wake** (D4).

```
triage_L1(r, now):
    F = l1_mshr[r.core]

    slot = l1[r.core].probe(r.line)                   # --- array ---
    if slot != NoSlot:
        l1_policy[r.core].on_hit(slot)
        release_reservation(r, F, L1, now)
        core_line_done(r.core, now)                   # D8: latency already paid
        return HIT

    e = F.entries.find(r.line)                        # --- matching entry ---
    if e:
        release_reservation(r, F, L1, now)            # it needs no slot after all
        if |e.targets| < l1_tgts_per_mshr:
            e.targets.push(r)                         # secondary miss: no traffic
            return MERGED                             # D3: subscribes, computes nothing
        mark_refused(r, LINE(r.line))                 # 3.8: stamps ONCE
        e.line_wait.push(r)                           # D5: waits on THIS entry
        return BLOCKED_TARGETS

    if not has_slot(F, r):                            # --- no match ---
        mark_refused(r, SLOT)
        F.slot_wait.push(r)                           # D2: registers, predicts nothing
        return BLOCKED_POOL

    e       = F.allocate(r.line, primary = r)         # primary miss
    r.mshr1 = e
    r.level = L2                                      # 3.5
    consume_reservation(r, F)
    accept  = l2_bank[bank_of(r.line)].reserve(now)   # P3
    schedule(E_L2Probe(r), accept + l2_latency)       # P4
    return FORWARDED


triage_L2(r, now):                       # identical shape. The waiter unit is the L1
    F  = l2_mshr                         # ENTRY, because everyone merged onto r.mshr1
    e1 = r.mshr1                         # is satisfied together. Still held. Always.

    slot = l2.probe(r.line)
    if slot != NoSlot:
        l2_policy.on_hit(slot)                        # D7: order here IS the recency stack
        release_reservation(r, F, L2, now)
        schedule(E_L1Fill(e1), now + l2_to_l1_latency)
        return HIT

    e = F.entries.find(r.line)
    if e:
        release_reservation(r, F, L2, now)
        if |e.targets| < l2_tgts_per_mshr:
            e.targets.push(e1)                        # the ENTRY
            return MERGED
        mark_refused(r, LINE(r.line))
        e.line_wait.push(r)                           # the REQUEST, so it can re-triage
        return BLOCKED_TARGETS

    if not has_slot(F, r):
        mark_refused(r, SLOT)
        F.slot_wait.push(r)                           # e1 still held
        return BLOCKED_POOL

    e      = F.allocate(r.line, primary = e1)
    consume_reservation(r, F)
    accept = dram.reserve(now)                        # P3
    schedule(E_L2Fill(e), accept + l2_miss_latency)
    return FORWARDED
```

```
install(cache, line):
    slot = cache.free_slot(line)
    if slot == NoSlot:
        slot = cache.policy.pick_victim(cache.victim_candidates(line))
    res = cache.insert(line, slot)
    cache.policy.on_fill(slot)
    if res.evicted:
        cache.policy.on_evict(slot)
        if cache is l2 and inclusion == inclusive:            # N8, 4.4
            for c in cores:
                s = l1[c].probe(res.evicted_line)
                if s != NoSlot:
                    l1[c].invalidate(s); l1_policy[c].on_invalidate(s)
                    stats.back_invalidations += 1


retire(e, level, now):
    F = mshr_file(level, e.core)

    # 1. committed subentries: satisfied directly, no re-triage (D5)
    for w in e.targets:
        if level == L2: schedule(E_L1Fill(w), now + l2_to_l1_latency)
        else:           core_line_done(w.core, now)

    F.entries.erase(e)

    # 2. everything that wakes, in ONE key-ordered list.
    #    line_wait: all of them; they need no slot and will all hit.
    #    grants:    bounded by free slots, oldest first.
    #    The merge is mandatory: reinject reserves a port, so iterating the two
    #    indexes separately staggers them by loop order instead of by age.
    #    The list is NOT already sorted; see the counterexample in 3.8.
    wake = e.line_wait + collect_grants(F)
    sort wake by key(r)
    for r in wake:
        reinject(r, now)


collect_grants(F):                             # pops and reserves; does NOT inject
    out = []
    while |F.entries| + F.reserved < F.capacity and not F.slot_wait.empty():
        r = F.slot_wait.pop_min()              # key order
        F.reserved += 1; r.reserved = true
        out.push(r)
    return out


reinject(r, now):                              # re-enter at r.level, through the port
    if r.level == L1: accept = l1_port[r.core].reserve(now)
                      schedule(E_L1Probe(r), accept + l1_latency)
    else:             accept = l2_bank[bank_of(r.line)].reserve(now)
                      schedule(E_L2Probe(r), accept + l2_latency)
    # r.refusal is NOT touched. 3.8
```

Every branch that used to end in "add a next query time" or "return a release time" now ends
in a `push` onto a named structure. Nothing computes a future timestamp except at the two
points where it is genuinely determined: the port reservations.

### 3.5 The re-entry-level trap

**A woken request re-enters at the level it was blocked at, not at the top of the hierarchy.**

| Woken from | Holds | Re-enter at | If you got this wrong |
|---|---|---|---|
| `l1_mshr.slot_wait` | nothing | **L1** | - |
| `l1_mshr[x].line_wait` | nothing | **L1** | - |
| `l2_mshr.slot_wait` | its L1 MSHR entry | **L2** | re-triage at L1 finds *its own* entry and merges the request into itself; it waits for a fill that will never be requested |
| `l2_mshr[x].line_wait` | its L1 MSHR entry | **L2** | same |

A re-injected request goes back through its level's **port** (it costs a real lookup) and
carries its **original refusal stamp**, so ordering is not reset by the wake.

### 3.6 Total event order

```
key = (time, class, effective_age, core_id, seq)
```

`class` breaks ties between event kinds at the same cycle:

| class | events | why here |
|---|---|---|
| 0 | `E_L2Fill`, `E_L1Fill` | state changes land before anything looks at state |
| 1 | `E_Barrier` | the barrier observes completed fills |
| 2 | `E_L1Probe`, `E_L2Probe` | lookups see this cycle's fills; closes D4's "queued miss became a hit" |
| 3 | `E_Issue` | new demand enters last |

`seq` is a monotonic counter assigned at *schedule* time, so the order is total and a re-run
is byte-identical (D11). This ordering is not cosmetic: under LRU it *is* the eviction order
(D7).

For class 2 specifically, `effective_age` and the `core_id`/`seq` tiebreak collapse; see 3.8.

### 3.7 The five outcomes, and one wait population

Triage returns one of five states, distinguished **only** by what releases them.

| Outcome | Holds | Wait reason | Released by | On release |
|---|---|---|---|---|
| `HIT` | nothing | - | already served | terminal |
| `MERGED` | a committed subentry | - | `e` retiring | satisfied directly, **no re-triage** |
| `BLOCKED_TARGETS` | nothing | `LINE(l)` | **that** entry retiring | re-triage, **always a hit** |
| `BLOCKED_POOL` | nothing | `SLOT` | **any** entry retiring | re-triage, outcome unknown |
| `FORWARDED` | a new entry | - | its own fill | terminal at this level |

Two collapses look tempting and both are wrong.

**`MERGED` vs `BLOCKED_TARGETS`** wait on the same entry, so they look alike. They are not:
`MERGED` holds a committed subentry and the fill satisfies it directly, while
`BLOCKED_TARGETS` holds nothing and must go back through the port and re-probe. Counting a
line waiter as merged overstates target-list utilisation, which is the one number
`l2_tgts_per_mshr` is being swept to find.

**`SLOT` vs `LINE`** are both "blocked", so they look alike. They are released by *different
events*. Waking a `LINE` waiter on an unrelated retire livelocks the grant loop: it re-blocks
on the same condition, is popped again, and the freed slot is never consumed.

A third, quieter reason the distinction is load-bearing: because targets in a read-only cache
are satisfied only by the fill, a target list **never drains incrementally**, and `line_wait`
is never promoted into `targets`. The whole set resolves at once, at retire, as hits. A model
that promotes on a free target slot is modelling a drain that cannot happen.

**But this is one population, not three structures (revised from v1's N6).** Q5's own
conclusion is that no rule ranks line waiters above slot waiters; one key orders everything,
and 3.4 merges and re-sorts the two indexes at every retire. What the split actually bundles
is two separable things:

- **a wait reason**, `{SLOT, LINE(l)}`, which is real, must survive, and is what prevents the
  livelock above. It is a one-field tag.
- **an eligibility index**, which is also real and worth keeping: `e.line_wait` is an O(1)
  answer to "who waits on line X". A single flat list makes every retire O(W) over the whole
  waiting population, roughly 4096 entries at the 1024-core target, on a hot path.

**Decision: keep both indexes in code, describe them as one FIFO population with a reason.**
Do not flatten to a single list: that trades a contained merge-and-sort, already guarded by
I7b, for an O(W) scan on the hottest path. In RTL there is no list at all, only a wait bit, a
two-bit reason, and a stamp on each L1 MSHR entry, with oldest-ready select (P5, 4.1).

### 3.8 Priority: FIFO by first refusal

```
mark_refused(r, reason):
    if r.refusal == NONE:                  # FIRST refusal only, at any level
        r.refusal = refusal_counter++      # a COUNTER, not a tick
        r.reason  = reason

key(r) = (r.refusal == NONE, r.refusal)    # refused beats fresh; FIFO within refused
```

The stamp is write-once (I2) and `reinject` never touches it, so a request enters the waiting
population exactly once, at first refusal, and is served in stamp order forever after
regardless of how many times it is re-refused or which index holds it. **That is FIFO by
first refusal**, and it is what v1's 5-tuple key was implementing.

Making it explicit buys three things:

1. **Starvation freedom becomes provable** (I10). The set of requests with a smaller stamp is
   finite and never grows; every `LINE` waiter becomes eligible when its entry retires (DRAM
   always responds), every `SLOT` waiter as entries retire. If the stamp were reset on wake, an
   aged request would lose to every fresh arrival at high load, forever.
2. **The key collapses.** No two waiters can tie on a counter, so `core_id` and `seq` become
   dead fields for class 2. Comparison is one small integer instead of a three-field tuple; in
   RTL, a counter and a comparator rather than a tick-width datapath.
3. **Cross-level seniority stays honest.** A request refused at the L1 and again at the L2
   carries its original stamp, giving it L2 seniority reflecting how long it has genuinely
   waited.

**Sign-off required on one divergence.** Under v1, a fresh request arriving at tick T with a
low `core_id` beat a request refused *at that same tick* with a higher `core_id`. Under
`(refused_bit, counter)` the refused request always wins. Reachable only on exact-tick ties,
but it is a behavior change and will appear as a sweep diff. V3's golden log must be
re-baselined once, deliberately, with the reason recorded.

**There is deliberately no rule ranking line waiters above slot waiters, or either above
fresh arrivals.** They are all re-injected as events and the one key sorts them. Section 10 of
the pseudocode companion works an example where a slot waiter is interleaved between two line
waiters purely by age.

**A wait set is not automatically in age order.** This is why the sort at 3.4 is load-bearing
and not redundant:

```
t=5   r1 wants Y. No entry for Y, pool full   -> slot_wait, stamp 5
t=6   some core allocates B(Y)                   (r1 is asleep, does not notice)
t=8   r2 wants Y. Matches B, targets full     -> B.line_wait, stamp 8
t=10  an entry retires, a slot frees. collect_grants pops r1 (oldest), reinjects.
      r1 re-triages, now finds B(Y) with full targets
                                              -> B.line_wait.push(r1), stamp still 5

      B.line_wait = [r2(8), r1(5)]            <- out of age order
```

A slot waiter can outlive the allocation of an entry it later merges onto and arrive carrying
an older stamp than what is already there. Building a wait set as a literal FIFO gives the
wrong order in exactly this case.

**Grant is reservation-based, not optimistic.** `collect_grants` pops at most
`capacity - live - reserved` waiters and marks each with a reservation, so a wake never
produces a thundering herd racing for one slot. A grantee that turns out not to need its slot
(it re-triaged into a hit or a merge) releases the reservation, immediately granting the next
waiter.

---

## Part 4. Structural decisions worth arguing about

### 4.1 The wait sets have no storage, and that is what bounds them

v1 argued the wait lists could be unbounded because `stall_in_order` caps the total at
`cores × lines_per_burst`, "4096 entries at 1024 cores, nothing". That conclusion is right and
its reasoning was a *simulator memory* argument. The correct argument is a *hardware* one
(P5).

**A request blocked at the L2 never released its L1 MSHR entry** (`triage_L2`: `e1 = r.mshr1`,
still held, always). So `e.line_wait` and `l2_mshr.slot_wait` are not buffers. They are
**selection sets over L1 MSHR entries that already exist**. In RTL: a wait bit, a two-bit
reason, an age stamp, and an oldest-ready select. Nothing to size, nothing to allocate, no
overflow condition, no depth limit to design.

**The backing structure differs by level**, so a design document must cite the right one for
each.

*At the L2 the backing store is the L1 MSHR file.* Only the primary request of a core's L1
entry reaches `triage_L2`; a core's L1 `entries` is a `line -> Mshr` map, so there is at most
one L1 entry per (core, line), and every later same-line request from that core is absorbed at
the L1. Therefore **at most one request per core** arrives at the L2 for any given line:

```
|e.line_wait|  <=  n_cores - l2_tgts_per_mshr                      (per entry)

Σ over entries of (|targets| + |line_wait|) + |slot_wait|
               <=  n_cores × lines_per_burst                       (global)
```

Corollary worth asserting (I12): **if `l2_tgts_per_mshr >= n_cores`, the L2 line-wait sets are
provably always empty.** That is a real design lever and it belongs in the sweep discussion.

*At the L1 the backing store is the core, not the L1 MSHR file.* A request in an L1 wait set
has not allocated an entry: `BLOCKED_TARGETS` means it waits to become someone else's target,
`BLOCKED_POOL` means there was no slot. I6 says this directly. Its physical home is the core's
outstanding-burst registers, bounded by N7:

```
|e.line_wait|  <=  lines_per_burst - l1_tgts_per_mshr, and 0 if expand deduplicates
```

**The coupling to `core_model` still must be written down.** Under `stall_in_order` a core
with an outstanding burst issues nothing further, so demand stops at the source and no queue
ever has to refuse anyone upstream. Swap in a run-ahead core or a decoupled prefetch engine and
the credit supply is no longer the bound: the sets grow, hide the real bottleneck, and need a
depth limit after all. `core_model` and "wait sets are free" are one decision, not two.

### 4.2 Consequence of holding the L1 MSHR across the L2 wait

L1 MSHR occupancy is the **full round trip including L2 queueing delay**, not just the
L1-to-L2 latency. Two things follow:

- `l1_mshrs` is coupled to `l2_mshrs`: L2 pressure lengthens L1 occupancy. A sweep must report
  both, and a result attributed to `l1_mshrs` alone is suspect.
- Under `stall_in_order` with a single-line burst, `l1_mshrs > 1` is inert by construction. The
  pool binds only when a burst expands to more lines than the pool holds, or when a core issues
  multiple events per tick. Both are permitted by the trace format; neither occurs in the
  current corpus. **`l1_mshrs` should be reported as inert-by-construction rather than swept**,
  unless the layout sweep produces `lines_per_burst > 1`, which a narrow `cout_block` does.

### 4.3 `ii`, and two kinds of back-pressure

**`ii` is the initiation interval**, from software pipelining and modulo scheduling: the number
of cycles between successive initiations of a pipelined unit, the reciprocal of throughput,
independent of latency. The L2 bank's `ii` is the bank cycle time (JEDEC `tCCD` is the DRAM
analogue); `dram.ii = line_bytes / dram_bytes_per_cycle` is the data-bus burst occupancy.

**A physical `ii` is `>= 1`.** `ii = 0` is a modeling escape hatch meaning infinite throughput,
not a setting a real port can have (N13). Label it as such in the config docs, or a sweep over
`ii ∈ {0, 1, 2}` reads as three adjacent points when 0 and 1 differ by unbounded parallelism.

**`ii` does produce back-pressure, of the rate kind.** With `ii = 1`, a k-long wait set drains
through k successive `reserve()` calls on the same `l2_bank[bank_of(X)]`. All k are for the
same line, so all hit the same bank: k cycles, strictly sequential. `next_accept` is shared
bank state, so that drain pushes it forward by `k × ii` and delays **every unrelated request to
that bank** in the window. It reaches the cores too: atomic bursts (N7) hold `phase = Waiting`
until `pending_lines == 0`, so bank delay produces a later `core_line_done` and a later next
`E_Issue`. The loop is closed.

**`ii` produces no occupancy bound, and moves occupancy the wrong way.** `Port.reserve` always
returns; it never refuses. So nothing about `ii` constrains how many requests sit in a wait
set; that ceiling is 4.1's, set entirely by the credit supply. And raising `ii` makes each
request hold its L1 MSHR credit *longer*, so more credits are in flight at once and the window
for other cores to collide on a line widens. **Wait sets get longer with higher `ii`, not
shorter.** Any sizing argument must rest on the credit bound, never on the port.

**Test consequence.** At `ii = 0` the merge-and-sort at 3.4 is a no-op: everything probes at
one timestamp and the event key does all the ordering. It has teeth only at `ii >= 1`, when
`reserve` order becomes service order and is never revisited (reservations are non-preemptive
and never released). **V7 and any test of I7b must run at `ii >= 1` or they pass vacuously.**

### 4.4 Inclusion is a knob, not an invariant

v1 stated back-invalidation as a hard requirement in three places (Part 0 D6, the 2.3 table,
and Q11 of the explainer, which called an L1 hit on an L2-evicted line an inflated hit rate
counting "accesses that should have been misses"). That is only true if inclusion is chosen.
Under `non_inclusive` the same L1 hit is **correct**, and it is the source of the extra
effective capacity: `L2 + n_cores × L1` instead of roughly `L2`.

**Inclusion has no job in this study.** Its canonical justification is coherence: an inclusive
LLC is a snoop filter, so invalidations need not broadcast to every L1. 2.6 records that
weights are read-only and there are no writers, so **there are no invalidations to filter**.
What inclusion costs, by the model's own instruments: effective capacity collapses to roughly
the L2 size; back-invalidation-induced L1 misses; and an O(cores) scan per L2 eviction, which
is the hottest path in the simulator at 1024 cores.

**The one argument that survives for inclusion:** under `non_inclusive`, a core missing on a
line that a peer L1 holds but the L2 evicted goes all the way to DRAM, whereas inclusion
guarantees an L2 hit. Peer-L1 forwarding is not modeled (2.6). How much this matters depends
on inter-core working-set overlap, which the tile-barrier structure probably makes high.

That dependence is the argument for making inclusion a **measured knob**. It is a result, not
an assumption. Three gaps to close:

| # | Gap | Action |
|---|---|---|
| G1 | `exclusive` is **not implementable as written**: it needs `E_L1Fill` to remove the line from the L2 plus a victim path back, and no such path exists | restrict the enum to `{inclusive, non_inclusive}` until someone wants to build it, so nobody configures a mode that silently behaves as `non_inclusive` |
| G2 | V9 tests only the inclusive branch | add V9b (Part 7) |
| G3 | Q11's worked example is the classic **inclusion LRU pathology** presented as normal operation. `l2_policy.on_hit` fires only on an L2 probe hit; L1 hits never reach the L2, so L2 recency is blind to lines hot in L1. That is exactly why LRU evicts a line another core is actively using | document and report it. Real inclusive designs mitigate with temporal hints; this model does not, which is realistic but must be visible rather than incidental |

The **code** was already correct: `install()` guards the loop with `inclusion == inclusive`.
Only the prose overreached.

---

## Part 5. Time, and why `tick_base` does not enter the engine

The old spec had two clocks (trace time and simulated time) and most of its defects lived at
the seam. The barrier decision removes the seam entirely.

**Trace time is only ever tile-local.** The engine never uses `tick_base`:

```
tile_origin[0]   = 0
tile_origin[N+1] = max over cores of their tile-N completion time     (simulated)

issue_time(c) = max( tile_origin[tile(c)] + local_tick(c, cursor), ready_time[c] )
```

`tile_origin` is a **measured** quantity replacing `tick_base`, a *derived* one. Three things
at once:

1. **One clock.** `local_tick` is an offset, never an absolute, so no expression adds or
   compares trace time with simulated time. The type confusion the old spec flagged as an open
   risk cannot be written.
2. **A free regression.** Under the unbounded baseline `tile_origin[N]` must equal
   `tick_base[N]` exactly, for every tile: a strong, cheap, whole-run oracle.
3. **A free result.** `tile_origin[N] − tick_base[N]` is the accumulated stretch at tile `N`,
   at no extra instrumentation cost.

The barrier is a countdown, not a scan: each tile holds `cores_remaining`; a core clearing the
tile decrements it and parks in `AtBarrier`; the decrement reaching zero schedules `E_Barrier`,
which sets `tile_origin[N+1] = now` and schedules an `E_Issue` for every core. No polling, and
`barrier_slack_cycles[c]` falls out as the cost of the lock-step assumption.

---

## Part 6. Named decisions requiring sign-off

| # | Decision | Consequence if reversed |
|---|---|---|
| N1 | **Events only.** No tick loop, no per-window counters, no periodic reset. | reintroduces D1 |
| N2 | **Subscribe, never predict.** No component computes another's availability. | reintroduces D2, D3 |
| N3 | **Occupancy, not quota.** Every shared resource is `{ii, latency, next_accept}`. | reintroduces window artifacts; `l2_banks` loses meaning |
| N4 | **Hard tile barrier.** Tile `N+1` begins when the last core clears tile `N`. | `tile_origin` undefined; needs a new global clock story |
| N5 | **Re-triage on wake**, from the blocked level, preserving the refusal stamp. | double-allocated MSHRs; hits served for evicted lines |
| N6 | *(revised)* **One wait population, FIFO by first refusal, carrying a reason `{SLOT, LINE(l)}`**, materialised as two indexes (`slot_wait`, `line_wait`) for O(1) eligibility, and nothing else. | losing the reason livelocks the grant loop; losing the indexes costs O(W) per retire |
| N7 | **Bursts are atomic**: all lines placed or the core retries the whole burst. Config load rejects `lines_per_burst > l1_mshrs` with a `throw` (survives `-DNDEBUG`). | a half-issued burst and a much larger core state machine |
| N8 | *(revised)* **Inclusion is a swept parameter**, `{inclusive, non_inclusive}`, default `inclusive`. No coherence justification exists in this study; the tradeoff is effective capacity against guaranteed L2 hits on peer-L1-resident lines, and it is a result to report. `exclusive` is not offered until G1 is resolved. | an unjustified capacity penalty presented as a correctness requirement |
| N9 | *(revised)* **`stall_in_order`, and therefore wait sets that need no storage** (P5, 4.1). The two are one decision. | the credit supply stops bounding the sets; they need depth limits, adding a third concurrency bound |
| N10 | **Total event order** `(time, class, effective_age, core_id, seq)`. For class 2 the last three collapse to `(refused_bit, refusal_counter)` (3.8). | non-reproducible sweeps |
| N11 | **A trace coordinate outside `workload_dims` aborts the run**, naming tile/tick/core/coord. | silently drops demand; corrupts every downstream statistic |
| N12 | **Strong typedefs** for `SimTime` and `LocalTick` from day one, plus `RefusalOrder` for the counter (3.8), so the three are mutually uncomparable. | the class of bug the old spec left open at unit 4 |
| N13 | *(new)* **`ii = 0` is a modeling escape hatch, not a physical setting.** Any fixture asserting reservation order runs at `ii >= 1`. | V7 and the I7b tests pass vacuously (4.3) |

---

## Part 7. Rebuild schedule

Ten units, four phases. Nothing from the old tree is reused. Each unit ends with its own tests
**and a mutation check**: the prior effort learned that 125 passing checks hid 6 live
mutations, so "tests pass" is not the exit criterion; "tests fail when the code is wrong" is.

### Phase A: untimed foundations *(no clock exists yet)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **A1** | `types.h`: `LineId`, `CoreId`, `SlotId`, strong `SimTime` / `LocalTick` / `RefusalOrder` (N12), `Coord`, `Burst`, `WeightShape` | round-trip and boundary tests; any mix of the three time-like types fails to compile |
| **A2** | `AddressMapper` + `BlockPackMapper`: `expand`, `locate`, `line_of` | out-of-range coordinate throws before any output is produced; `line == tag × num_sets + set_index` holds |
| **A3** | `TraceReader`: format v2 headers, tile/tick/core/burst decode, `spatial_factors` core decode | reads a real corpus file; malformed header throws (N11) |
| **A4** | `CacheArray` + `SetAssociativeArray` with **`invalidate` in the interface from the start** (N8) | probe/free_slot/victim_candidates/insert/invalidate; non-exact size ÷ (line × assoc) throws |
| **A5** | `ReplacementPolicy` + LRU, FIFO, Random | policy sees only `SlotId`; all three drive one array unchanged; Random is seeded and reproducible |

Phase A gate: an **untimed reference model** (array + policy only, no MSHRs, no time) that
reports hit rates. This is the oracle Phase C is checked against, the single most valuable
artifact of the rebuild and the thing the previous effort did not have.

### Phase B: timing primitives *(clock exists, hierarchy does not)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **B1** | `Port { ii, latency, next_accept, reserve() }` | occupancy arithmetic; `ii = 0` never delays; `ii = latency` serializes; config rejects a negative `ii` and warns on `ii = 0` (N13) |
| **B2** | `EventQueue`: min-heap on `(time, class, effective_age, core_id, seq)` (N10) | total order; two identical runs produce identical event logs |
| **B3** | `MshrFile`: entries, `targets`, `line_wait`, `slot_wait`, the refusal counter, `find/allocate/retire`, the grant loop | grant loop terminates with a free slot; the line-wait set resolves atomically on retire; the 3.8 out-of-order-insert counterexample sorts correctly |

### Phase C: the engine

| Unit | Contents | Exit criterion |
|---|---|---|
| **C1** | `CacheLevel` = array + policy + port + MSHR file; `triage()` per level | the 3.4 triage table exercised branch by branch |
| **C2** | The six event handlers; `retire`/`reinject` with the re-entry-level rule (3.5) | the V-list below |
| **C3** | Tile barrier, `tile_origin`, core state machine | `tile_origin == tick_base` under the unbounded baseline |
| **C4** | *(revised)* Two-valued inclusion: back-invalidation across L1s under `inclusive`, and the `non_inclusive` path (N8, 4.4) | both branches exercised; `back_invalidations == 0` under `non_inclusive` |

### Phase D: harness

| Unit | Contents | Exit criterion |
|---|---|---|
| **D1** | Config load + validation (N7, N11, N13, G1), single source of truth for the parameter set | every invalid combination throws under `-DNDEBUG`; `inclusion = exclusive` is rejected, not silently downgraded |
| **D2** | Statistics and the results CSV | every stat in Part 8 emitted, one row per config |
| **D3** | Sweep driver | a full grid point runs end to end and reproduces byte-identically |

**Critical path:** A1 → A2 → A4 → A5 → *(Phase A gate)* → B3 → C1 → C2. A3, B1, and B2 are
independent of that chain. C4 depends on C2. All of Phase D depends on C2.

### Verification list

| # | Fixture | Asserts |
|---|---|---|
| V1 | unbounded baseline, full trace | `tile_origin[N] == tick_base[N]` for every tile; hit counts equal the Phase-A reference model |
| V2 | core stalled across trace ticks 5-39 | all 36 events issued, none dropped |
| V3 | any sweep point, re-run | byte-identical event log (N10). **Re-baseline once against v1**, deliberately: the 3.8 key change alters exact-tick tie order |
| V4 | two blocked requests, same line | exactly one MSHR ever allocated for it |
| V5 | queued miss; another core's fill lands that line first | resolves as a hit, consumes no MSHR (D4) |
| V6 | queued L2 hit whose line is evicted before service | re-probes to a miss, keeps its refusal stamp (D4) |
| V7 | target list at capacity, entry retires, **at `ii >= 1`** (N13) | **all** line waiters resolve at once, none allocates, **and reservation order equals key order**. At `ii = 0` this passes vacuously (4.3) |
| V8 | two hits, one set, one cycle, LRU | eviction order matches service order (D7) |
| V9 | L2 evicts a line another core's L1 holds, `inclusion = inclusive` | that L1 is invalidated; its next access misses (N8) |
| V9b | *(new)* same fixture, `inclusion = non_inclusive` | that L1 still **hits**; `back_invalidations == 0` (G2) |
| V10 | full sweep point | wait-set occupancy never exceeds `cores × lines_per_burst`, **and** `|e.line_wait| <= n_cores - l2_tgts_per_mshr` per entry (I11) |
| V11 | request woken from `l2_mshr.slot_wait` | re-enters at **L2**, does not merge into its own L1 entry (3.5) |
| V12 | `lines_per_burst > l1_mshrs` | throws at config load, under `-DNDEBUG` (N7) |
| V13 | any run | every issued line request reaches exactly one terminal state; no request is lost or double-counted |
| V14 | any run | port busy-cycles ≤ elapsed cycles × port count |
| V15 | coordinate outside `workload_dims` | aborts, naming tile/tick/core/coord (N11) |
| V16 | *(new)* `l2_tgts_per_mshr >= n_cores` | no request ever enters an L2 `line_wait` (I12) |
| V17 | *(new)* the 3.8 counterexample replayed | `B.line_wait` is out of age order on insert, and service order is nonetheless `r1` before `r2` |
| V18 | *(new)* any run | every waiter's `refusal` stamp is written exactly once and is unique across the run (I2, 3.8) |
| V19 | *(new)* `inclusion = exclusive` | rejected at config load with a message naming G1, not silently treated as `non_inclusive` |

V1's second clause is what repays the rebuild: an independent untimed model agreeing with the
DES on hit counts is a far stronger oracle than any unit test, and it exists only because Phase
A is built fresh rather than inherited.

---

## Part 8. What the run reports

Beyond hit rates and cycles:

**Concurrency.** MSHR occupancy histogram per level (the headline result); max observed target
depth; max line-wait depth and slot-wait length distribution, **reported separately by wait
reason** (3.7), because they point at different knobs (`tgts_per_mshr` versus `mshrs`); grant
latency distribution; fraction of grants that re-triaged into a hit or merge rather than an
allocate.

**Contention.** Per-bank L2 utilisation, bank-conflict cycles, memory-channel utilisation and
queueing delay, L1 port utilisation.

**Time.** Per-tile `tile_origin − tick_base` (stretch), `barrier_slack_cycles` per core,
per-core stall attribution split by cause: `{L1 slot, L1 line, L2 slot, L2 line, L2 port,
channel, barrier}`. The breakdown must sum to total stall: a V13-class invariant, not a
reporting convenience.

**Inclusion (new, 4.4).** Back-invalidations and the L1 misses they induced; effective capacity
(distinct lines resident anywhere) under each `inclusion` setting; DRAM accesses that a peer L1
could have served under `non_inclusive`, which is the cost of not modeling peer forwarding and
bounds the argument in favour of inclusion.

**Model health.** `hits_downgraded_to_miss` (D4), event count and events per simulated cycle
(the cost win over the tick model, measured rather than claimed), and max wait-set depth against
the I11 bound (a violation means the credit argument broke, most likely because `core_model`
changed).

---

## Part 9. Open questions for review

1. **`l1_mshrs` sweep.** 4.2 argues it is inert by construction under the current corpus and
   should be reported rather than swept. Confirm, or name the layout points that make it bind.
2. **L2 banking granularity.** Bank by low bits of the set index (spreads consecutive lines) or
   high bits (keeps a core's working set in one bank)? Opposite conflict behavior, and the
   choice interacts with the `cin_block`/`cout_block` sweep.
3. **`l2_to_l1_latency`** is implied by D10 and absent from the old table. Separate knob or
   `l2_latency` reused?
4. **Prefetch.** Deferred. The MSHR file carries a `demand_reserve` field so it does not need
   restructuring later; confirm that is the right amount of forward provision.
5. **Random policy reproducibility** across a parallel sweep: seed per-run, or per
   (config, trace) pair?
6. **Inclusion sweep cost (new).** N8 makes inclusion a swept parameter. Independent sweep, or
   only at the extremes of `l2_size`? A full cross product doubles the grid, and the interesting
   region is where the L2 is small enough that `n_cores × L1` is a material fraction of total
   capacity.
7. **Exclusive (new).** Is G1 worth resolving, or is `{inclusive, non_inclusive}` the honest
   scope? Exclusive needs an L2 removal path on L1 fill plus a victim path back, which is more
   than a knob.
8. **Refusal counter width (new).** A run's total refusals bound it; at 1024 cores over a full
   trace this can exceed 32 bits. Use 64.
9. **Arbiter feasibility at the target scale (new).** 3.8 makes the policy FIFO, but the
   structure is still oldest-ready select over `n_cores × l1_mshrs` entries, needing an age
   matrix or a comparator tree. Comfortable at 8 cores, uncomfortable at 1024. If round-robin is
   what would actually be built, add it as a config option and show the sensitivity is small.
   That is a much stronger claim than assuming the age order away.

---

## Appendix A. Invariants to assert

```
I1   a line has at most one live Mshr per level
I2   r.refusal is written at most once, and is unique across the run          (3.8)
I3   |e.targets| <= tgts_per_mshr
I4   |F.entries| + F.reserved <= F.capacity
I5   a request is on at most one wait index, and holds at most one reservation
I6   r.level == L2  <=>  r.mshr1 != null
I6b  at L2 the map (waiting request) -> r.mshr1 is injective: no two requests on any
     L2 wait index share an L1 entry. Each core holds at most one L1 entry per line,
     and only its primary reaches the L2. This is the formal statement of "the wait
     sets are views, not storage"                                        (P5, 4.1)
I7   collect_grants terminates: each iteration strictly increases F.reserved
I7b  port reservation order == key order at every retire (the merged wake list).
     Exists only because of the index split (3.7); testable only at ii >= 1 (4.3)
I8   a reinjected request never re-enters the index it was popped from in the same
     dispatch (guaranteed by the reservation for SLOT, by residency for LINE)
I9   Σ over cores of pending_lines == outstanding requests
I10  no starvation: the stamp is write-once (I2), so the set of requests with a
     smaller stamp is finite and never grows; eligibility always arrives      (3.8)
I11  |e.line_wait| <= n_cores - l2_tgts_per_mshr at L2;
     <= lines_per_burst - l1_tgts_per_mshr at L1                              (4.1)
I12  if l2_tgts_per_mshr >= n_cores then every L2 line_wait is empty           (4.1)
```

## Appendix B. Relationship to gem5, and why `deferred` was renamed

Verified against the local checkout at `/u/yyu9/gem5`, commit `cbf0eae2` (2026-07-28).

gem5 has a field called `MSHR::deferredTargets`. It means something different from this
model's old `deferred` and behaves differently, so the name was a live source of
misunderstanding for anyone with gem5 background.

| | this model (`line_wait`) | gem5 (`deferredTargets`) |
|---|---|---|
| what defers | target list at capacity | **coherence ordering only** (`mshr.cc:373-414`): cache-maintenance ops, a pending post-invalidate, a target needing writable when the fill will not deliver it. Capacity never routes here |
| what capacity does | wait set, re-probe on wake | **blocks the whole cache port** (`base.cc:400-404`, `setBlocked(Blocked_NoTargets)`); the requestor retries at `curTick()+1` (`base.cc:167-176`) |
| what happens on fill | re-probe, which hits because the line is now resident | `promoteDeferredTargets()` splices them into `targets`, clears the readable bit, and **reissues to memory** (`base.cc:640-648`) |

Two consequences worth keeping in the write-up:

- gem5's global port block is a **cruder** form of the same refusal this model performs, not a
  more faithful one. It refuses everyone rather than tracking who was refused. This model's
  wait sets record the refusal without adding storage (P5), which is closer to what an
  MSHR-credit-based interface actually does.
- The `targets` semantics agree everywhere. gem5's `serviceMSHRTargets` (`cache.cc:700-731`)
  copies straight out of the response packet with critical-word-first timing and no re-lookup,
  and real MSHRs forward from the fill buffer to each subentry the same way. `targets` keeps
  its name for that reason.

## Appendix C. Corrections to the 08-13 companion documents

`2026-08-13-wcache-control-flow-pseudocode.md` and `-pseudocode-explained.md` remain useful.
Where they disagree with Part 3 here, Part 3 wins. Specifically:

| Where | Correction |
|---|---|
| pseudocode line 95, `deferred = [] # unbounded` | rename to `line_wait`; the comment should read "selection set over L1 MSHRs, not storage; see I6b". "Unbounded" invites a future reader to bound it, which would add hardware that does not exist |
| pseudocode section 3, `enqueue_time` | becomes `refusal`, a `RefusalOrder` counter, not a tick (3.8) |
| pseudocode section 8, the sort before re-injection | correct and load-bearing. Add the 3.8 counterexample as a comment, because the sort looks redundant until you have seen it |
| explained Q5 | the answer is correct and stands. What changed is *why*: the ordering is FIFO by first refusal, and the deferred-versus-pooled symmetry it demonstrates is evidence the two are one population (3.7) |
| explained Q8, `ii` | correct. Add the full name (initiation interval) and that `ii = 0` is not physical (N13) |
| explained Q11 | replace "the hit rate is inflated by exactly the accesses that should have been misses" with: *"Inclusion is violated. Under `inclusion = inclusive` that L1 hit is a bug; under `non_inclusive` it is the intended behavior and the source of the extra effective capacity."* Also note that the t=22 step of its worked example is the inclusion LRU pathology (G3), not routine operation |
