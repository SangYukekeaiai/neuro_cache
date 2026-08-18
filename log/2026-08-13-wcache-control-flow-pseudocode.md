# wcache: full cache-access control flow

Companion to `2026-08-13-wcache-event-driven-plan.md`. This file is the complete
control flow and nothing else. Prose lives in the plan.

---

## 1. Outcome taxonomy

Five terminal outcomes per triage call. They are distinguished by **what releases
them**, which is the only distinction that matters, because that is what decides which
structure holds the request.

| Outcome | Holds | Parked on | Released by | Result when released |
|---|---|---|---|---|
| `HIT` | nothing | nothing | already served | terminal |
| `MERGED` | nothing | `e.targets` | `e` retiring | satisfied directly, **no re-triage** |
| `BLOCKED_TARGETS` | nothing | `e.deferred` | `e` retiring | re-triage, **always HIT** (line is now resident) |
| `BLOCKED_POOL` | nothing | `F.pool_wait` | **any** entry retiring | re-triage, outcome unknown |
| `FORWARDED` | a new entry | nothing | its own fill | terminal at this level |

`MERGED` and `BLOCKED_TARGETS` both wait on the same entry, but `MERGED` has a
committed subentry and is satisfied by the fill directly; `BLOCKED_TARGETS` has no
subentry and must re-triage. `BLOCKED_TARGETS` and `BLOCKED_POOL` are both "blocked",
but on **different resources with different release events**, which is why they cannot
share a list. See plan D5.

---

## 2. Priority

**One key, never rewritten:**

```
key(r, now) = (effective_age(r, now), r.core_id, r.seq)

effective_age(r, now) = r.enqueue_time   if it has ever been refused
                      = now              if fresh (zero seniority)

r.enqueue_time := now   on FIRST refusal only, at any level
               := never reassigned thereafter, including across levels
r.seq          := monotonic counter, assigned once at Request creation
```

A fresh request takes `now`, so it loses to anything that has waited and ties only with
other fresh requests, broken by `core_id` then `seq`.

**Applied at exactly three points, and they must agree:**

| Point | Effect |
|---|---|
| `pool_wait.pop_min()` | which waiter gets a freed slot |
| event-queue tiebreak at equal `time` | whether a woken request or a fresh arrival probes first |
| port reservation order | follows from the event order, since reservation happens inside the dispatched event |

**The property this buys:** an aged request beats a fresh one wherever they meet.

```
cycle 100:  R_old refused        -> enqueue_time = 100
cycle 500:  R_old woken          -> event key (500, class=2, 100, ...)
cycle 500:  R_new first arrival  -> event key (500, class=2, 500, ...)
            100 < 500            -> R_old probes first. Starvation-free.
```

An `enqueue_time` that were rewritten on wake would make `R_old` lose to every fresh
arrival, forever, at high load. This is the single most important invariant in the model.

**Full event-queue key** (plan 3.6):

```
(time, class, enqueue_time, core_id, seq)

class 0: E_L2Fill, E_L1Fill      state changes land first
class 1: E_Barrier
class 2: E_L1Probe, E_L2Probe    lookups see this cycle's fills
class 3: E_Issue                 new demand enters last
```

---

## 3. State

```
Request:
    core, line, seq
    enqueue_time = NONE          # set once, on first refusal
    level        = L1            # where to RE-ENTER on wake (plan 3.5)
    mshr1        = null          # the L1 entry it holds, once FORWARDED at L1
    reserved     = false         # holds a pool-grant reservation

Mshr:
    line, core                   # core is unused at L2
    targets  = []                # bounded by tgts_per_mshr; holds Requests (L1)
                                 #                        or Mshr entries (L2)
    deferred = []                # unbounded; blocked on THIS entry

MshrFile:                        # one per L1, one shared L2
    entries   = {}               # line -> Mshr, bounded by capacity
    pool_wait = []               # unbounded; blocked on ANY entry
    reserved  = 0                # granted-but-not-yet-dispatched slots

Port:                            # l1_port[c], l2_bank[b], dram
    ii, latency, next_accept

CoreState:
    cursor, tile, phase, pending_lines

tile_origin[]                    # simulated origin of each tile (plan Part 5)
```

---

## 4. Engine loop

```
run():
    tile_origin[0] = 0
    for c in cores: schedule(E_Issue(c), tile_origin[0] + local_tick(c, 0))

    while not queue.empty():
        e   = queue.pop_min()                  # total order, section 2
        now = e.time
        dispatch(e)

    if any core not Done or any entry live or any wait list non-empty:
        throw DeadlockError(dump)              # not assert: sweep build is -DNDEBUG
```

---

## 5. Ports

```
Port.reserve(now):
    accept        = max(now, next_accept)
    next_accept   = accept + ii
    return accept                              # data lands at accept + latency
```

`ii = 0` never delays. `ii = latency` serializes. No wait list, no free event: a port is
a timestamp, not a queue.

---

## 6. Event handlers

```
E_Issue(c):                                    # class 3
    lines = mapper.expand(burst(c, c.cursor))  # N7: |lines| > l1_mshrs rejected at load
    c.pending_lines = |lines|
    c.phase = Waiting
    for L in sorted(lines):
        r      = Request(core=c, line=L, seq=next_seq(), level=L1)
        accept = l1_port[c].reserve(now)
        schedule(E_L1Probe(r), accept + l1_latency)


E_L1Probe(r):        triage_L1(r, now)         # class 2
E_L2Probe(r):        triage_L2(r, now)         # class 2, r.mshr1 is held


E_L2Fill(e2):                                  # class 0
    install(l2, e2.line)                       # 7.1; may evict + back-invalidate
    retire(e2, L2, now)


E_L1Fill(e1):                                  # class 0
    install(l1[e1.core], e1.line)              # 7.1; L1 is a leaf, no back-invalidation
    retire(e1, L1, now)


E_Barrier(N):                                  # class 1
    tile_origin[N] = now
    for c in cores:
        c.tile = N; c.phase = Ready
        schedule(E_Issue(c), tile_origin[N] + local_tick(c, c.cursor))
```

---

## 7. Triage

### 7.1 L1

```
triage_L1(r, now):
    F = l1_mshr[r.core]

    # --- array ---
    slot = l1[r.core].probe(r.line)
    if slot != NoSlot:
        l1_policy[r.core].on_hit(slot)
        release_reservation(r, F, L1, now)
        core_line_done(r.core, now)
        return HIT

    # --- MSHR file: matching entry ---
    e = F.entries.find(r.line)
    if e:
        release_reservation(r, F, L1, now)     # it needs no slot after all
        if |e.targets| < l1_tgts_per_mshr:
            e.targets.push(r)
            return MERGED
        mark_refused(r, now)                   # sets enqueue_time if NONE
        e.deferred.push(r)
        return BLOCKED_TARGETS

    # --- MSHR file: no match ---
    if not has_slot(F, r):                     # capacity minus live minus reserved
        mark_refused(r, now)
        F.pool_wait.push(r)
        return BLOCKED_POOL

    e        = F.allocate(r.line, primary = r)
    r.mshr1  = e
    r.level  = L2                              # plan 3.5: re-enter at L2 from now on
    consume_reservation(r, F)
    accept   = l2_bank[bank_of(r.line)].reserve(now)
    schedule(E_L2Probe(r), accept + l2_latency)
    return FORWARDED
```

### 7.2 L2

Identical shape. The waiter unit is the **L1 entry**, not the request, because everyone
merged onto `r.mshr1` is satisfied together.

```
triage_L2(r, now):
    F  = l2_mshr
    e1 = r.mshr1                               # still held. Always.

    slot = l2.probe(r.line)
    if slot != NoSlot:
        l2_policy.on_hit(slot)                 # D7: order here IS the recency stack
        release_reservation(r, F, L2, now)
        schedule(E_L1Fill(e1), now + l2_to_l1_latency)
        return HIT

    e = F.entries.find(r.line)
    if e:
        release_reservation(r, F, L2, now)
        if |e.targets| < l2_tgts_per_mshr:
            e.targets.push(e1)
            return MERGED
        mark_refused(r, now)
        e.deferred.push(r)                     # the REQUEST, so it can re-triage
        return BLOCKED_TARGETS

    if not has_slot(F, r):
        mark_refused(r, now)
        F.pool_wait.push(r)
        return BLOCKED_POOL

    e      = F.allocate(r.line, primary = e1)
    consume_reservation(r, F)
    accept = dram.reserve(now)
    schedule(E_L2Fill(e), accept + l2_miss_latency)
    return FORWARDED
```

---

## 8. Install, retire, wake

```
install(cache, line):
    slot = cache.free_slot(line)
    if slot == NoSlot:
        cands  = cache.victim_candidates(line)
        slot   = cache.policy.pick_victim(cands)
    res = cache.insert(line, slot)
    cache.policy.on_fill(slot)
    if res.evicted:
        cache.policy.on_evict(slot)
        if cache is l2 and inclusion == inclusive:      # N8
            for c in cores:
                s = l1[c].probe(res.evicted_line)
                if s != NoSlot:
                    l1[c].invalidate(s); l1_policy[c].on_invalidate(s)
                    stats.back_invalidations += 1


retire(e, level, now):
    F = mshr_file(level, e.core)

    # 1. committed subentries: satisfied, no re-triage
    for w in e.targets:
        if level == L2: schedule(E_L1Fill(w), now + l2_to_l1_latency)
        else:           core_line_done(w.core, now)

    F.entries.erase(e)

    # 2. everything that wakes, in ONE key-ordered list.
    #    deferred:  all of them; they need no slot and will all hit.
    #    grants:    bounded by free slots, oldest first.
    #    They MUST be merged before re-injection: reinject reserves a port,
    #    so iterating the two lists separately would stagger them by loop
    #    order instead of by age. See explained.md Q5.
    wake = e.deferred + collect_grants(F)
    sort wake by key(r, now)
    for r in wake:
        reinject(r, now)


collect_grants(F):                             # pops and reserves; does NOT inject
    out = []
    while |F.entries| + F.reserved < F.capacity and not F.pool_wait.empty():
        r = F.pool_wait.pop_min()              # key order
        F.reserved += 1
        r.reserved  = true
        out.push(r)
    return out


try_grant(F, now):                             # for the release path, where no
    for r in collect_grants(F):                # deferred list is in play
        reinject(r, now)


reinject(r, now):                              # re-enter at r.level, through the port
    if r.level == L1: accept = l1_port[r.core].reserve(now)
                      schedule(E_L1Probe(r), accept + l1_latency)
    else:             accept = l2_bank[bank_of(r.line)].reserve(now)
                      schedule(E_L2Probe(r), accept + l2_latency)
    # r.enqueue_time is NOT touched. Section 2.
```

---

## 9. Helpers

```
mark_refused(r, now):
    if r.enqueue_time == NONE: r.enqueue_time = now      # FIRST refusal only

has_slot(F, r):
    live = |F.entries|
    if r.reserved: return live + F.reserved - 1 < F.capacity   # its own reservation
    return live + F.reserved < F.capacity

consume_reservation(r, F):
    if r.reserved: F.reserved -= 1; r.reserved = false

release_reservation(r, F, level, now):         # granted, but needed no slot
    if r.reserved:
        F.reserved -= 1; r.reserved = false
        try_grant(F, now)                      # hand it to the next waiter

core_line_done(c, now):
    c.pending_lines -= 1
    if c.pending_lines > 0: return             # N7: burst is atomic
    c.cursor += 1
    if c.cursor still inside c.tile:
        schedule(E_Issue(c), max(now, tile_origin[c.tile] + local_tick(c, c.cursor)))
    else:
        c.phase = AtBarrier
        stats.tile_completion[c] = now
        if --cores_remaining[c.tile] == 0: schedule(E_Barrier(c.tile + 1), now)
```

---

## 10. Worked example: the two questions, in situ

`l2_tgts_per_mshr = 2`, `l2_mshrs = 1`, all latencies 10, `ii = 0`.

```
t=0    C0 -> line X.  L2 miss, pool empty  -> FORWARDED, entry A{X, targets:[e1_C0]}
                                              pool now 1/1 (FULL)
t=1    C1 -> line X.  match A, room 1/2    -> MERGED         (waits for data)
t=2    C2 -> line X.  match A, targets FULL-> BLOCKED_TARGETS, A.deferred=[C2]
                                              enqueue_time(C2) = 2
t=3    C3 -> line Y.  no match, pool FULL  -> BLOCKED_POOL,  pool_wait=[C3]
                                              enqueue_time(C3) = 3
t=4    C4 -> line X.  match A, targets FULL-> BLOCKED_TARGETS, A.deferred=[C2,C4]
                                              enqueue_time(C4) = 4

t=10   E_L2Fill(A).  install X.  retire(A, L2):
         1. targets [e1_C0, e1_C1]  -> E_L1Fill each, no re-triage
         2. deferred [C2, C4]       -> reinject BOTH; neither needs a slot
         3. pool_wait               -> try_grant: 0 live + 0 reserved < 1
                                        pop C3 (only waiter), reserve, reinject

t=10   three E_L2Probe events now sit at the same timestamp.
       Event-queue tiebreak on enqueue_time:  C2(2) < C3(3) < C4(4)
       -> C2 probes X: HIT.        release_reservation: no-op (never reserved)
       -> C3 probes Y: MISS, pool has its reservation -> FORWARDED
       -> C4 probes X: HIT.
```

Note what the tiebreak did: **C3, a pool waiter, was interleaved between two deferred
waiters purely by age.** No rule ranks "deferred" above "pooled"; one key orders
everything, including any fresh request that happened to arrive at t=10 (its
`enqueue_time` would be 10, so it goes last).

---

## 11. Invariants to assert

```
I1  a line has at most one live Mshr per level
I2  r.enqueue_time is written at most once
I3  |e.targets| <= tgts_per_mshr
I4  |F.entries| + F.reserved <= F.capacity
I5  a request is on at most one wait list, and holds at most one reservation
I6  r.level == L2  <=>  r.mshr1 != null
I7  collect_grants terminates: each iteration strictly increases F.reserved
I7b port reservation order == key order at every retire (the merged wake list)
I8  a reinjected request never re-enters the list it was popped from
    in the same dispatch (guaranteed by the reservation for pool_wait,
    and by residency for deferred)
I9  sum over cores of pending_lines == outstanding requests
```

---

## 12. Path summary

```
E_Issue -> E_L1Probe -+-> HIT ------------------------------> core_line_done
                      |
                      +-> MERGED (targets) -----> [wait] ---> core_line_done
                      +-> BLOCKED_TARGETS ------> [wait] ---> E_L1Probe (re-triage)
                      +-> BLOCKED_POOL ---------> [wait] ---> E_L1Probe (re-triage)
                      |
                      +-> FORWARDED -> E_L2Probe -+-> HIT --> E_L1Fill
                                                  |
                                                  +-> MERGED ---------> [wait] -> E_L1Fill
                                                  +-> BLOCKED_TARGETS -> [wait] -> E_L2Probe
                                                  +-> BLOCKED_POOL ----> [wait] -> E_L2Probe
                                                  |
                                                  +-> FORWARDED -> E_L2Fill
                                                                     |
                                                     retire: targets -> E_L1Fill
                                                             deferred -> E_L2Probe
                                                             pool_wait -> E_L2Probe
E_L1Fill -> retire: targets  -> core_line_done
                    deferred -> E_L1Probe
                    pool_wait -> E_L1Probe
```

Every `[wait]` is a registration, never a timer. Every arrow out of a wait is scheduled
by the structure that freed, never by the request that waited.
