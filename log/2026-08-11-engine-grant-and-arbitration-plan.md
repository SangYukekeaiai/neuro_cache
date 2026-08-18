# 2026-08-11 Engine revision: grant notification and named arbitration

Amends `log/2026-08-05-cachesim-redesign-plan.md`, Part 2 and Part 5. A delta,
not a rewrite: everything not listed under "What changes" below stands as
written.

**Nothing here touches implemented code.** Units 1-3 (`BlockPackMapper`,
`locate`, `SetAssociativeArray`) are unaffected; the array holds no timing
state by design, so every change lands in the unimplemented engine. The
current tree stays at 171 checks, 0 failures.

---

## Part 0. What changes, and why

Three defects in Part 2 as written, and two calibration errors.

### A. Per-tick retry does work proportional to stalling

2.7's `stall_in_order` has a refused core "re-issue on the next tick". Cost is
`simulated_ticks x stalled_cores`, and both terms blow up in exactly the regime
this study exists to measure. Steady-state L2 fill throughput is
`l2_mshrs / l2_miss_latency_ticks` = 20/100 = **0.2 lines per tick** against
2.4's measured demand of 627 distinct lines per trace tick, so the re-timed
timeline stretches by a large factor and roughly a thousand cores re-ask every
tick of it. The exact factor depends on the L2 miss rate, which the sweep has
not measured; the direction does not.

### B. Arbitration is unstated

When one MSHR frees and hundreds of cores want it, Part 2 never says who wins.
Under per-tick polling the answer falls out of loop order, which means core 0
systematically beats core 900 in every tick, forever. That is a modeling
decision made by accident. 2.9 already names smaller decisions than this one:
2.9.1 pins `bound_check_order` over a divergence of a single slot.

### C. A wholesale queue stall cannot implement `hit_under_block = true`

2.9.2 defaults it true, on the reasoning in 2.2 that "a hit needs no MSHR, so
refusing it is a property of where gem5 places the block rather than a
requirement". If the L1-to-L2 path stalls as a unit when the MSHR pool is
full, a request behind the stall that would have hit in the L2 array waits
anyway. That is `false`, gem5's behavior, not the default the plan wants.

### D. Calibration: `tgts_per_mshr` is measured per tick, but accumulates over an MSHR lifetime

2.4 conclusion 3 expects it inert, from a maximum of 4 observed waiters per
line against gem5's convention of 12. **That measurement is per tick.** An
MSHR is occupied for `l2_miss_latency_ticks` = 100 ticks, and any core
requesting that line at any point in the window joins the target list. The
per-tick merge ratio is therefore a lower bound on target-list depth, not the
depth. Weight lines being re-requested across ticks is the phenomenon this
study measures, so the accumulation is the expected case.

**Change:** `Blocked_NoTargets` is implemented as a live block cause and the
observed maximum depth is instrumented and reported, rather than assumed inert.

### E. Calibration: the L1 pool is inert for this layout, not structurally

2.5 is right that a private L1 sees at most one outstanding line here. But it
also names two conditions that make it bind, both already permitted by the
trace format: a `cout_block` of 1 turns one burst into 4 line requests, and an
arch may emit multiple events per core per tick. The sweep crosses layouts, so
grid points exist where L1 binds while the default never does.

**Change:** none to the mechanism. The L1 pool stays, for the reason 2.5
already gives, that it is where per-core stall time is accumulated, and the
sweep reports whether it ever bound.

---

## Part 1. The revised mechanism

**Ticks stay.** The tile barrier makes cores lock-step by construction, 2.4
measures 16 to 1024 events in every tick so there is no idle time for an event
queue to skip, and `l2_fill_lines_per_tick` is a per-timestep budget with no
natural home in a pure event queue. What is removed is only the polling.

**Grants replace retries.** A refused request enqueues once and sleeps. When an
MSHR is released, the pool hands it to the waiting request directly. Cost per
release is O(1) instead of O(stalled cores) per tick.

```
for (Tick t = 0; t < horizon; ++t) {

    // 1. Fills completing at t, capped by l2_fill_lines_per_tick
    for (mshr : fills_due(t)) {
        insert the line into the array          // unit 3, may evict
        satisfy every target, advance each waiter's core_ready_time
        release the MSHR
        grant()                                 // replaces the retry storm
    }

    // 2. Tile barrier: tick 0 of a tile waits for every core
    if (tile_boundary(t)) barrier();

    // 3. Accumulate this tick's demand across cores
    buffer.clear();
    buffer.reserve(expected_lines_per_tick);    // C2 lands here, see Part 7
    for (core c : cores_with_event(t))
        if (core_ready_time[c] <= t)
            mapper.expand(burst_of(c, t), buffer);

    // 4. Triage
    for (req : buffer) triage(req, t);
}

triage(req, t):
    if (l1.probe(req.line) != kNoSlot)              return HIT;
    if (l1_mshr_matching(req.line) has target room) return MERGED;
    if (l1 pool full)                               enqueue(req, t, L1);
    // forward to L2
    if (l2.probe(req.line) != kNoSlot)              return HIT;   // hit_under_block
    if (l2_mshr_matching(req.line) has target room) return MERGED;
    if (l2 pool has a free slot)                    allocate, due at t + latency;
    else                                            enqueue(req, t, L2);

grant():
    while (a slot is free && !queue.empty()) {
        req = queue.pop_min();     // key = (enqueue_tick, l1_index)
        triage(req, now);          // re-run: state changed while it waited
    }
```

### Re-running triage on grant is required, not tidiness

A queued request must not blindly allocate when granted. While it waited, the
line may have become resident through someone else's fill, in which case it is
now a hit and consumes no slot, or another request for the same line may have
allocated an MSHR it should merge onto. Allocating blindly would put two MSHRs
on one line, double-count the miss, and consume a slot the bound is supposed to
protect.

This also makes `grant()` on MSHR release sufficient for **both** block causes.
A request blocked by `Blocked_NoTargets` is waiting for a specific MSHR to
retire; when it does, the line is resident, and re-triage returns a hit.

---

## Part 2. Arbitration, as a named decision

**`arbitration = fcfs_then_index`.** The wait list is ordered by the key

```
(enqueue_tick, l1_index)
```

- `enqueue_tick` is the simulated tick at which the request was **first**
  refused. A request never re-enqueues, so its key is stable for as long as it
  waits. This is what makes "first come" mean anything: under per-tick retry
  every re-issue looks newly arrived, so FCFS was not expressible at all.
- `l1_index` breaks ties among requests refused in the same tick.

Two properties follow.

**It is a total order**, so a re-run is byte-identical. That is the same
requirement `free_slot` already meets by returning the lowest free way
(`cache.cpp:133-137`), so that a cold-start fill reproduces even under the
Random replacement policy.

**It removes the systematic bias**, without pretending to be unbiased. Waiting
time now dominates, and core index decides only genuine ties. A low-index core
still wins every tie it enters, which is a stated property rather than an
accident of loop order.

**This changes results relative to Part 2 as written.** Stall distributions
will differ, and totals may. That is a correction, not a regression: the old
numbers came from an unnamed policy.

---

## Part 3. Triage at the L2 input

The L1-to-L2 path is a wait list, not a stalling pipe. Requests are classified
at the L2 rather than blocked as a group:

| Case | Needs an MSHR | Served while pool is full |
|---|---|---|
| hits in the L2 array | no | **yes**, this is `hit_under_block = true` |
| matches an in-service MSHR, target room | no | yes |
| matches an in-service MSHR, list full | no, but blocked | no, `Blocked_NoTargets` |
| misses, pool has a slot | yes | n/a |
| misses, pool full | yes | no, `Blocked_NoMSHRs` |

`hit_under_block = false` is then reproduced exactly by testing the blocked
flag **before** the probe rather than after, which is where gem5 puts it
(`base.cc:2606-2637`). One branch, both behaviors, which is what makes the
switch sweepable.

Because hits and merges never enter the wait list, the list holds only requests
competing for a new MSHR. They all want the identical resource, so strict FCFS
service causes no head-of-line blocking of traffic that could have proceeded.

---

## Part 4. Changes to the 2.8 parameter table

| Parameter | Change |
|---|---|
| `arbitration` | **new**, `fcfs_then_index`, fixed, not swept |
| `l1_to_l2_queue_depth` | **deliberately absent**, see below |
| `l2_tgts_per_mshr` | unchanged at 12, but reclassified from "expected inert" to instrumented, reporting observed max depth |
| everything else | unchanged |

**The wait list is unbounded, on purpose.** A bounded queue is a structural
limit that can fill and generate backpressure of its own, and it would be the
only knob in 2.8 with no gem5 convention or measurement behind it. It would
also interact with `l2_mshrs` in the sweep, so a result could not be attributed
to either. Unbounded keeps it a pure wait list: the only bounds are `l2_mshrs`
and `l2_tgts_per_mshr`, which is the separation 2.6 argues for on bandwidth
versus concurrency.

Instrument the maximum list length. If it stays small the decision was free; if
it grows to thousands, that is a finding about the machine, not a reason to cap
it.

---

## Part 5. New named decisions for 2.9

Continuing the existing numbering, which ends at 4.

5. **`arbitration = fcfs_then_index`.** Part 2 above. Ordered by first refusal,
   ties by L1 index, total and therefore reproducible.
6. **Grants are delivered by notification on MSHR release, not by per-tick
   retry.** Ticks are retained for the compute side, the tile barrier and the
   fill-bandwidth budget.
7. **Triage happens at the L2 input**, so `hit_under_block` is a one-branch
   switch rather than a property of the queue.
8. **The L1-to-L2 wait list is unbounded**, so that `l2_mshrs` and
   `l2_tgts_per_mshr` remain the only concurrency bounds.
9. **`Blocked_NoTargets` is live and instrumented**, not assumed inert, because
   2.4's merge measurement is per tick while target lists accumulate over a
   100-tick MSHR lifetime.

---

## Part 6. Verification changes to Part 5

The existing forced-refusal fixture (plan Part 5) verified a shifted timeline.
It now has to verify who shifted.

| # | Fixture | Asserts |
|---|---|---|
| V1 | forced refusal, two cores refused in the same tick | the lower `l1_index` is granted first |
| V2 | forced refusal, two cores refused in different ticks | the earlier `enqueue_tick` wins regardless of index |
| V3 | two queued requests for the **same** line | exactly one MSHR allocated, the second merges on grant |
| V4 | queued request whose line is filled by another core while it waits | granted as a hit, no MSHR consumed |
| V5 | pool full, request that hits the array | served when `hit_under_block = true`, refused when `false` |
| V6 | target list at `tgts_per_mshr` | blocks with `NoTargets`, and unblocks as a hit when that MSHR retires |
| V7 | `baseline_unbounded` | timeline still collapses exactly onto the trace's own ticks |
| V8 | full re-run of any sweep point | byte-identical, from the total order in decision 5 |

V7 is the regression that matters most: it is the existing requirement that the
timing machinery adds nothing when its mechanisms are disabled, and this
revision must not disturb it.

**Reported per run, new:** maximum wait-list length, maximum observed target
depth, grant latency distribution, and the fraction of grants that re-triaged
into a hit or a merge rather than an allocation. That last one directly
measures whether the re-triage rule of Part 1 is doing real work.

---

## Part 7. What this does not change, and what stays open

**Unchanged:** Part 1 (trace format), Part 3 (architecture, module inventory,
directory layout), Part 4 (build order), Part 6 (deliverable and results CSV).
No parameter defaults move. Units 1-3 need no edit.

**C2 is untouched and still lands here.** The per-tick accumulate loop of 2.4
survives this revision intact, so the `reserve` obligation that F1 moved out of
`expand` still belongs at step 3 of the tick loop, marked in the pseudocode
above. This revision does not dissolve it.

**Also carried into the engine:** `CoreId` signedness (decision 3, 2026-08-11),
and `invalidate` on `CacheArray` once 2.3's inclusion fix makes an L2 eviction
back-invalidate the L1 copy (decision 5).

**Raised, deliberately not acted on:** trace time and simulated time are both
`Tick`, and `max(tick_base + tick, core_ready_time)` mixes them in one
expression. Distinct types would make a wrong-direction subtraction a compile
error rather than a plausible number. This is the same shape as the signedness
class that has now cost three findings, but it is speculative until the engine
exists and may be overkill. Decide when unit 4's types are written, not before.
