# wcache: pseudocode walkthrough

Answers to the questions raised on `2026-08-13-wcache-control-flow-pseudocode.md`.
Read alongside it; section numbers below refer to that file.

---

## Q1. Do `E_L2Fill` / `E_L1Fill` mean DRAM to L2, and L2 to L1?

Yes, with one clarification on `E_L1Fill`.

| Event | Data moves | Fired by |
|---|---|---|
| `E_L2Fill(e2)` | DRAM to L2 | the memory channel, `l2_miss_latency` after the request was accepted |
| `E_L1Fill(e1)` | L2 to L1 | the L2, `l2_to_l1_latency` after the L2 could supply the line |

The clarification: **`E_L1Fill` has two producers, not one.**

```
(a) L2 HIT       triage_L2 -> schedule E_L1Fill(e1) at now + l2_to_l1_latency
(b) L2 MISS      ... E_L2Fill(e2) -> retire(e2) -> for each target e1:
                                     schedule E_L1Fill(e1) at now + l2_to_l1_latency
```

So `E_L1Fill` means "the L2 is handing this line to this L1", and it does not care
whether the L2 had the line all along (a) or had just received it from DRAM (b). That is
the point of having it as its own event: path (b) is where **one** DRAM fill turns into
**many** L1 fills, one per core that merged onto the entry.

Naming, to be exact: an `E_L2Fill` fills *the L2*. An `E_L1Fill` fills *the L1*. The event
is named for its destination, not its source.

---

## Q2. Does `E_Barrier` mean the tile barrier?

Yes. One `E_Barrier(N)` fires per tile transition, and only when the **last** core has
finished tile `N-1`.

It is not scheduled on a timer and nothing polls for it. Each tile carries a countdown:

```
core finishes its last burst in tile N-1
    -> phase = AtBarrier
    -> if (--cores_remaining[N-1] == 0):  schedule E_Barrier(N) at now
```

The decrement that happens to reach zero is the one that schedules the event. When it
dispatches it does two things: sets `tile_origin[N] = now` (see Q9), and schedules an
`E_Issue` for every core, releasing them all together.

---

## Q3. Do `E_L1Probe` / `E_L2Probe` mean "look up the cache line"?

They mean slightly more than a lookup: **"the request has arrived at this level; resolve
it completely."** That is the array lookup *and* the MSHR decision, because the two
cannot be separated. Whether the request needs an MSHR is knowable only after the array
says "miss", and whether it needs a *new* MSHR is knowable only after the MSHR file says
"no match".

```
E_L1Probe(r)  ->  triage_L1(r, now)  ->  array probe
                                     ->  MSHR find / targets / pool
                                     ->  one of the five outcomes
```

Why they are events rather than function calls: the array state at the moment of the
probe must be the state the probe sees. A request accepted by the L2 port at cycle 40
with `l2_latency = 8` probes at cycle 48, and if a fill landed at cycle 44 the probe must
see it. A recursive call would evaluate the probe at the caller's timestamp (40) and miss
a line that was physically there.

---

## Q4. Is the L1 lookup easy because it only serves the core?

Mostly, but not quite. **The L1 has the same three input sources as the L2**, it just sees
far less traffic on two of them:

| Source | L1 | L2 |
|---|---|---|
| fresh demand | from its own core, via `E_Issue` | from any core's L1, via `FORWARDED` |
| `pool_wait` wake | yes, when `l1_mshrs` fills | yes |
| `deferred` wake | yes, when `l1_tgts_per_mshr` fills | yes |

What makes the L1 quiet is `stall_in_order`, not the structure. A core has at most one
burst outstanding, so its private L1 sees at most `lines_per_burst` requests at a time.
With `cout_block >= 4` that is exactly 1, so `l1_mshrs` never fills and `l1_pool_wait` is
always empty. Narrow the layout to `cout_block = 1` and one burst becomes 4 lines, and
the L1 pool starts binding.

So: the L1 uses the identical code path, and the identical sorting rule, and on the
current corpus that machinery is inert. Do not special-case it. The moment it is
special-cased, the `cout_block` sweep silently stops being valid.

---

## Q5. How do `deferred`, `pool_wait`, and fresh requests get sorted at the L2?

**There is no separate sorting step.** All three become events in the one global event
queue, and the queue's key orders them. That is the whole mechanism.

```
key = (time, class, effective_age, core_id, seq)

effective_age(r) = r.enqueue_time  if it has been refused before
                 = now             if this is a fresh request
```

Fresh requests get `now`, so they have zero seniority: they lose to anything that has
been waiting, and tie only with other fresh requests, broken by `core_id` then `seq`.

### A worked example

Config: `l2_mshrs = 2`, `l2_tgts_per_mshr = 2`, `l2_miss_latency = 40`,
`l2_to_l1_latency = 5`, `l2_latency = 0`, `ii = 0`.

**Build-up.**

| t | Core | Line | What triage_L2 finds | Outcome | State after |
|---|---|---|---|---|---|
| 0 | C0 | X | miss, pool 0/2 | `FORWARDED` | entry **A**(X), targets `[C0]`, due t=40 |
| 0 | C1 | Y | miss, pool 1/2 | `FORWARDED` | entry **B**(Y), targets `[C1]`, due t=40. **Pool full** |
| 3 | C2 | X | matches A, targets 1/2 | `MERGED` | A.targets `[C0,C2]`. **Targets full** |
| 6 | C3 | X | matches A, targets full | `BLOCKED_TARGETS` | A.deferred `[C3]`, age **6** |
| 9 | C4 | Z | no match, pool full | `BLOCKED_POOL` | pool_wait `[C4]`, age **9** |
| 12 | C5 | X | matches A, targets full | `BLOCKED_TARGETS` | A.deferred `[C3,C5]`, age **12** |
| 15 | C6 | W | no match, pool full | `BLOCKED_POOL` | pool_wait `[C4,C6]`, age **15** |

Also: C7 issues a fresh request for line Y whose `E_L2Probe` happens to land at t=40.

**t = 40, `E_L2Fill(A)` dispatches.** `retire(A, L2, 40)` does three things:

```
1. A.targets = [C0, C2]     -> satisfied directly. E_L1Fill each at t=45.
                               No re-triage: they hold committed subentries.

2. A.deferred = [C3, C5]    -> both re-injected. Neither needs a slot
                               (X is now resident), so both are woken.

3. try_grant(pool)          -> A is gone, so live = {B} = 1, capacity 2,
                               reserved 0  ->  ONE free slot.
                               pop_min(pool_wait) = C4 (age 9 < 15).
                               reserve it. Now live+reserved = 2 = capacity.
                               Loop stops. C6 stays parked.
```

**Four `E_L2Probe` events now sit at t = 40.** The queue sorts them:

| Request | Came from | effective_age | Key | Order |
|---|---|---|---|---|
| C3 | `A.deferred` | **6** | (40, 2, 6, 3) | **1st** |
| C4 | `pool_wait` (granted) | **9** | (40, 2, 9, 4) | **2nd** |
| C5 | `A.deferred` | **12** | (40, 2, 12, 5) | **3rd** |
| C7 | fresh | **40** | (40, 2, 40, 7) | **4th** |

**This is the answer to your question.** Note what did *not* happen: no rule ranked
"deferred" above "pooled". C4, a pool waiter, landed **between** C3 and C5, two deferred
waiters, purely because it was refused at t=9 and they were refused at t=6 and t=12. And
the fresh request went last despite arriving at the same instant, because it had been
waiting for nothing.

**What each then does:**

```
1st  C3 probes X  -> HIT (X installed at t=40). Held no reservation.
2nd  C4 probes Z  -> miss, no match, holds its reservation -> FORWARDED,
                     allocate entry C(Z), due t=80.
3rd  C5 probes X  -> HIT.
4th  C7 probes Y  -> matches B, targets 1/2 -> MERGED.

Final: pool = {B, C} = 2/2 full. C6 still parked at age 15,
       first in line for the next retire.
```

### Where the port enters

With `ii = 0` above, all four probe at t=40. With a real `ii = 2`, they cannot: the bank
accepts one every 2 cycles. The **reservation order must equal the key order**, or the
port would stagger them by whatever order the retire loop happened to iterate its lists:

```
key order   C3(6), C4(9), C5(12)      # C7 is fresh, reserves on its own path
reserve     C3 -> accept 40
            C4 -> accept 42
            C5 -> accept 44
probe at    40+l2_latency, 42+l2_latency, 44+l2_latency
```

So `retire` must **merge `deferred` and the pool grants into one list, sort by key, and
only then re-inject.** Iterating the two lists separately would give C3, C5, C4 -- the
right requests, the wrong order, and a different LRU outcome. See section 8 of the
pseudocode file, which now does this.

---

## Q6. What is the difference between `Mshr` and `MshrFile`?

One entry versus the whole structure.

```
Mshr       = ONE entry. Tracks ONE line that is currently being fetched.
             Holds: the line, its targets list, its deferred list.
             Hardware: one row of the MSHR CAM.

MshrFile   = the whole structure at one level.
             Holds: up to `capacity` Mshr entries, the pool_wait list,
                    and the reserved counter.
             Hardware: the CAM plus its allocator and its stall logic.
```

There is one `MshrFile` per L1 (private) and one shared `MshrFile` at the L2.

```
l2_mshr : MshrFile  capacity = 4
  |
  +-- entries
  |     A -> Mshr{line X, targets [C0,C2],  deferred [C3,C5] }
  |     B -> Mshr{line Y, targets [C1],     deferred []      }
  |
  +-- pool_wait  [C6]        <- blocked on the FILE (no free entry)
  +-- reserved   0
```

The distinction matters because the two levels of "full" are different resources:
`|A.targets| == l2_tgts_per_mshr` means **entry A** is full; `|entries| == capacity`
means **the file** is full. That is exactly the `BLOCKED_TARGETS` vs `BLOCKED_POOL` split.

---

## Q7. What does `reserved` mean in `MshrFile`?

It counts slots that have been **promised to a woken waiter but not yet consumed.**

It exists because a grant and the allocation it enables happen at different times:

```
t=40   retire frees a slot. try_grant pops C4 and re-injects it.
       But C4 does not allocate NOW -- it must go back through the L2 bank
       port and re-probe, so its E_L2Probe fires at, say, t=48.

t=40..48   the slot is free but spoken for.
```

Without `reserved`, that 8-cycle window is wrong in one of two ways:

| No reserved counter | What goes wrong |
|---|---|
| grant everyone whose turn it could be | 1024 waiters wake for 1 slot; 1023 re-block. Thundering herd, O(N) work per retire |
| grant one, then treat the slot as free | a second retire at t=44 grants the same slot again; two requests allocate into one slot and `capacity` is violated |

`reserved` closes the window: `has_slot()` tests `live + reserved < capacity`, so the slot
is invisible to everyone except the waiter it was promised to.

Two ways a reservation ends:

```
consume_reservation   the waiter allocated. reserved--, live++.  Net: no change.
release_reservation   the waiter re-triaged into a HIT or a MERGE and needs no
                      slot after all. reserved--, and try_grant runs immediately
                      to hand the slot to the next waiter.
```

The release path is the one that is easy to forget and it is not rare: it is exactly the
`BLOCKED_POOL` request whose line was filled by someone else while it waited.

---

## Q8. What are `ii`, `latency`, and `next_accept`?

Three properties of a pipelined resource.

```
latency       accept -> data. How long ONE access takes end to end.
ii            accept -> next accept. The minimum gap between two consecutive
              accesses. This is the THROUGHPUT: 1/ii accesses per cycle.
next_accept   the earliest time this port can accept anything. The port's
              entire mutable state, one integer.
```

`ii` and `latency` are independent, and that is the point. A pipelined SRAM bank with
`latency = 8`, `ii = 1` accepts a new access every cycle with 8 in flight. A blocking
resource is `ii == latency`.

```
ii = 2, latency = 10, four requests all arriving at t = 0:

req  accept   data
 A     0       10
 B     2       12
 C     4       14
 D     6       16

  t: 0    2    4    6    8   10   12   14   16
  A  [====accept, 10 cycles in flight====] data
  B       [==============================] data
  C            [=============================] data
  D                 [============================] data
```

Special cases:

| Setting | Meaning |
|---|---|
| `ii = 0` | infinite throughput; the port never delays anyone |
| `latency = 0` | the access is instantaneous once accepted |
| `ii = latency` | fully blocking; one access at a time |

The memory channel uses `ii = line_bytes / dram_bytes_per_cycle`, so `ii` **is** the
bandwidth and `latency` is the round-trip time. This is what replaced the old
`l2_fill_lines_per_tick` quota: the quota could only say "N per window", which lands all
N at the same timestamp and creates a cliff at the window edge. Occupancy staggers them
by `ii` with no window and no cliff.

---

## Q9. What is `Port.reserve`?

Three lines, and it is the whole contention model.

```
Port.reserve(now):
    accept      = max(now, next_accept)   # wait if the port is still busy
    next_accept = accept + ii             # claim it for the next ii cycles
    return accept                         # caller schedules data at accept + latency
```

Line by line, with `ii = 2`, `next_accept = 0`:

```
call            max(now, next_accept)   accept   next_accept becomes   delay
reserve(0)      max(0, 0)  = 0            0            2                0
reserve(0)      max(0, 2)  = 2            2            4                2
reserve(0)      max(0, 4)  = 4            4            6                4
reserve(9)      max(9, 6)  = 9            9           11                0   <- port was idle
```

`max(now, next_accept)` is the whole contention model: if the port went idle
(`next_accept < now`), you are served immediately; if it is still busy, you wait exactly
until it frees.

Two things it deliberately is **not**:

- **It is not a queue.** There is no list of waiters and no `E_PortFree` event. A caller
  asks once and gets a definite answer immediately. Ordering is decided *before* the
  call, by which event dispatched first (Q5).
- **It never refuses.** A port always returns an accept time. Only MSHR files refuse,
  which is why they are the only structures with wait lists.

---

## Q10. What does `lines = mapper.expand(...)` mean?

The trace does not store addresses. It stores a **burst**: a run of weight-tensor
coordinates that the core fetches together. `expand` turns that run into the set of
distinct cache lines it touches, under the current layout.

```
on disk    [kh, kw, cin, cout_start, cout_end]
           e.g. [1, 1, 0, 0, 4]  =  kh=1, kw=1, cin=0, cout in [0,4)
                                    4 weight elements

layout     BlockPackMapper packs a cin_block x cout_block sub-block into one line
line id    (kh, kw, cin/cin_block, cout/cout_block), row-major
```

The same burst produces a different number of lines depending on the layout, and that is
the entire reason the trace stores coordinates instead of addresses:

| `cout_block` | cout 0..3 falls in | `expand` returns | Meaning |
|---|---|---|---|
| 4 | one block | **1 line** | the burst is one cache line. `l1_mshrs` inert |
| 2 | two blocks | **2 lines** | one core event needs 2 MSHRs |
| 1 | four blocks | **4 lines** | one core event needs 4 MSHRs; the pool binds |

That last column is why `E_Issue` reads:

```
lines = mapper.expand(burst(c, c.cursor))
c.pending_lines = |lines|
for L in sorted(lines): ... one Request each
```

One trace event becomes `|lines|` independent requests, each of which probes, misses, and
allocates separately. The core resumes only when **all** of them are done, which is
decision N7 (bursts are atomic), and it is why config load must reject
`lines_per_burst > l1_mshrs`: at `cout_block = 1` and `l1_mshrs = 2`, a 4-line burst can
never be placed and the core never advances.

If addresses had been baked into the 7.7 GB corpus, sweeping `cout_block` would mean
regenerating the corpus. Keeping coordinates makes the layout a swept parameter.

---

## Q11. Explain the eviction and back-invalidation block

```cpp
if (res.evicted):
    cache.policy.on_evict(slot)
    if (cache is l2 and inclusion == inclusive):
        for c in cores:
            s = l1[c].probe(res.evicted_line)
            if (s != NoSlot):
                l1[c].invalidate(s); l1_policy[c].on_invalidate(s)
                stats.back_invalidations += 1
```

**`if res.evicted`** -- `insert` returns `{evicted, evicted_line}`. It is false when the
line went into a free way (no victim was needed) and true when it displaced a live line.
Returning the *identity* of the displaced line, not just a flag, is what makes the rest of
this block possible without a second lookup.

**`cache.policy.on_evict(slot)`** -- the array and the replacement policy are separate
modules. The array has just changed what occupies `slot`; the policy holds the recency or
counter state for that slot and must be told, or it will pick victims using stale
metadata. The array cannot do it itself because it does not know a policy exists.

**`if cache is l2 and inclusion == inclusive`** -- this is the inclusion invariant:
*every line in an L1 is also in the L2*. The clause runs only at the L2 because the L1 is
a leaf; nothing caches below it, so an L1 eviction invalidates nothing.

**`for c in cores: probe / invalidate`** -- and here is why it is mandatory rather than
tidy. The L2 is **shared**; the L1s are **private**. Core 0 can trigger the fill that
evicts a line that **core 3's** L1 still holds:

```
t=10  C0 misses line 0. Fills L2 set 0 way 0, and C0's L1.
t=10  C3 misses line 0. Merges. Fills C3's L1 too.
      Now line 0 sits in: L2, C0's L1, C3's L1.

t=12  C0 accesses line 4, which maps to C0's L1 set 0 -> evicts line 0
      from C0's L1 ONLY. C3's L1 still holds it. L2 still holds it. Fine.

t=22  C0's line-4 fill reaches the L2. L2 set 0 is full {line 0, line 2}.
      LRU picks line 0 -> EVICTED FROM L2.

      *** C3's L1 still holds line 0. ***
```

Without the loop, C3's next access to line 0 is an L1 hit for a line the L2 believes is
gone. Inclusion is violated, and the hit rate is inflated by exactly the accesses that
should have been misses. Note the trigger was C0's activity and the victim was C3's copy:
no per-core reasoning can catch this, which is why the loop scans **all** cores.

**`stats.back_invalidations`** -- this is a real cost of inclusion, not bookkeeping. Each
one converts a future L1 hit into a miss, and the count says how much the inclusive
policy costs on this workload. Report it next to the L1 misses it induced.

**Cost note.** The loop is O(cores) per L2 eviction, which at 1024 cores is the hottest
path in the simulator. The obvious optimisation is a per-line sharer bitmask maintained
on L1 fill and eviction, turning the scan into a popcount over the bits that are set. Do
not build it first: build the scan, measure it, and add the bitmask only if the profile
says so. The scan is obviously correct and the bitmask has a coherence bug waiting in it
if the fill and eviction paths ever disagree.

---

## Q12. `phase` and `pending_lines`

Both live in `CoreState` and both exist because a core is not always simply "running".

### `phase`

```
Ready       has work, may issue when its issue time arrives
Waiting     has an outstanding burst; issues nothing further (stall_in_order)
AtBarrier   finished its tile, parked until every other core does too
Done        trace exhausted
```

It is a **state**, not a time, and that is deliberate. At the instant a core is refused you
know *that* it is stalled but not *when* it will resume, because that depends on a grant
that has not happened yet. A single `ready_time` field cannot represent "waiting, resume
time unknown", and that representational gap is exactly what forces a model into
polling ("add a next possible query time"). Naming the state removes the need to guess.

`Waiting` is also the mechanism behind the wait-list bound: a `Waiting` core issues
nothing, so demand stops at the source and no queue can exceed
`cores x lines_per_burst` entries.

### `pending_lines`

A countdown implementing burst atomicity (N7).

```
E_Issue         lines = expand(burst)        # say 4 lines under cout_block = 1
                pending_lines = 4
                phase = Waiting

core_line_done  pending_lines -= 1
                if pending_lines > 0: return          # 3 of 4 done: still waiting
                cursor += 1                           # all 4 done: burst complete
                schedule next E_Issue
```

The 4 lines resolve independently and out of order: line 2 might hit in the L1 at cycle
41 while line 0 is still waiting on DRAM until cycle 130. The core does not advance at
41. `pending_lines` is what makes "the burst completes when its slowest line completes"
true without tracking which lines finished.

At `cout_block >= 4` it is always 1 and the countdown is trivial. It becomes load-bearing
only under the narrow-layout sweep points, which is precisely where the L1 MSHR pool
starts to bind.

---

## Q13. What is `tile_origin`?

The **simulated** start time of each tile. It replaces the trace's `tick_base`.

The trace's time is tile-local: `tick` restarts at 0 in every tile, and the trace makes
it global by adding `tick_base`, the prefix sum of preceding tiles' `mac_cycles`. That sum
is valid only if tiles do not overlap, and only if the trace's own timing was right. The
simulator is re-timing the trace, so the second condition fails by construction.

`tile_origin` fixes both by *measuring* what `tick_base` *assumed*:

```
tile_origin[0]   = 0
tile_origin[N+1] = the simulated time at which the LAST core cleared tile N
                   (set by E_Barrier, which is why the barrier is load-bearing)

issue_time(c) = max( tile_origin[c.tile] + local_tick(c, c.cursor),
                     ready_time[c] )
```

So `local_tick` is only ever an **offset within a tile**, never an absolute time. Trace
time never enters the engine as an absolute quantity, and there is no expression anywhere
that adds a trace timestamp to a simulated one. This is what dissolved the old design's
"two clocks" problem, which was the source of most of its defects.

Two things fall out for free:

```
regression   under the unbounded baseline, tile_origin[N] must equal tick_base[N]
             EXACTLY, for every tile. A whole-run oracle, no fixtures needed.

result       tile_origin[N] - tick_base[N] is the accumulated timeline stretch
             at tile N. Per tile, at zero instrumentation cost.
```

Numerically:

```
tile 0: mac_cycles 1618   tick_base 0      tile_origin 0
tile 1: mac_cycles 1594   tick_base 1618   tile_origin 2042   stretch +424
tile 2: ...               tick_base 3212   tile_origin 4103   stretch +891
```

The gap widens monotonically, and the per-tile increment is that tile's stall. That
column is the deliverable.
