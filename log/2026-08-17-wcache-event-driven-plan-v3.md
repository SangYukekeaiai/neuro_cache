# 2026-08-17 wcache: event-driven rebuild plan, v3

**Status: proposal, for review. Phase A implementation is in flight against v2 (A1 complete,
A2a complete); nothing built so far is invalidated by v3.**

Supersedes `log/2026-08-14-wcache-event-driven-plan-v2.md` in full, and with it
`log/2026-08-13-wcache-event-driven-plan.md`, everything under
`log/2026-08-05-cachesim-redesign-plan.md` Parts 2-6, and all of
`log/2026-08-11-engine-full-spec.md`. **This file is the single authority.** The companion
pseudocode (`2026-08-13-wcache-control-flow-pseudocode.md`) and its explainer
(`2026-08-13-wcache-pseudocode-explained.md`) remain valid except where Appendix C lists a
correction; Part 3 here is the authority where they disagree.

The v1 tree is at `src/wcache/native_v1_archive/` and is **not** carried forward as code.

**What is new in v3.** Nothing from v2 is reversed. Two things are added, both raised
2026-08-17, and both concern the core rather than the cache:

| # | Topic | v2 | v3 |
|---|---|---|---|
| C1 | Intra-tile core schedule | `issue_time(c) = max(tile_origin + local_tick(c, cursor), ready_time[c])`: a stalled core re-syncs to the trace's absolute ticks, so a stall it has already paid can be absorbed | a core handles **one burst at a time** and its schedule is **self-timed**: `issue(k+1) = served(k) + max(gap_k, 1)`, where `gap_k` is the trace's own inter-burst spacing. A stall shifts the whole rest of the tile by the full stall (4.5, N14) |
| C2 | Pipelined burst fetch | absent. `prefetch` sat in 2.6's not-modeled list | a **prefetch policy inside the memory system**: the L1 fetches burst `k+1` early and holds it, and **the core is not changed at all**. Fetch time and demand-access time become separate quantities, and a prefetched line evicted before its use is a real and measured loss (4.6, N15, N16) |

The two are one mechanism seen from two ends: C1 fixes what the core does with time it lost,
C2 is the knob that lets the memory system spend that time fetching. The dividing line is
deliberate and was settled 2026-08-17: **the PE is untouched.** It still issues one burst,
stalls until served, computes, and issues the next, with no weight buffer, no run-ahead, and no
second burst in hand. Everything C2 adds lives at or below the L1. The consequence is that
`served(c, k+1) >= served(c, k) + 1` is satisfied by the core's own issue rule rather than
enforced against a policy trying to violate it, which is why a hit on burst `k+1` still cannot
overtake burst `k`.

**What was new in v2**, carried forward unchanged. Six things corrected or strengthened
against v1:

| # | Topic | v1 | v2 |
|---|---|---|---|
| R1 | Wait-list bounds | bounded because `stall_in_order` caps the total, and the total is small | the lists have **no storage at all**; they are views over structures that already exist. Per-list bound tightens to `n_cores` (4.1) |
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
core per unit of time is `O(cores × simulated_cycles)`. At 256 cores that is the exact
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

### Two further defects, found 2026-08-17 (v3)

Both were carried by v2 as well as by the original sketch. Neither is in the cache; both are
in what the core does with time.

**D13. The trace's local ticks are treated as a schedule the core can re-sync to.** v2's
`issue_time(c) = max(tile_origin + local_tick(c, cursor), ready_time[c])` lets a core that
stalled 60 cycles on burst `k` issue burst `k+1` at its original trace tick if that tick was
more than 60 cycles out. The stall is then paid once and forgotten.

That is not what the machine does. A PE issues a weight burst, **stalls at it until it is
served**, and only then begins the work that leads to the next burst. The spacing between two
bursts in the trace is compute, not a wall-clock appointment: it is the MAC work that burst
`k`'s weights feed. Late weights mean late compute, which means the next burst is needed late.
Stall accumulates within a tile and reaches the barrier, and v2 could discard it.

→ **Fix:** the core schedule is a self-timed recurrence off its own service times, and the
trace contributes spacing rather than absolutes (4.5, N14, Part 5).

**D14. Every request in the model is a demand request, so there is nowhere to put a pipelined
fetch.** In v2 a line request exists only because a core is waiting for it, and its completion
*is* that core's completion. A fetch issued for burst `k+1` while the core is still stalled on
burst `k` has no representation: it has no waiting core to complete, and if it is bolted on
naively it appears to let the core run ahead, which it cannot, because the PE is in-order with
one burst of weights in hand at a time.

→ **Fix:** admit non-demand requests, issued by the memory system, whose completion installs a
line and notifies nobody. The line is then found by the core's ordinary demand access later.
`fill(c, k)` and `served(c, k)` become two quantities separated by however long the core takes
to get there, and a line fetched early can also be **lost** to eviction before that (4.6, N15,
N16). The core's rule does not change and neither does its code.

---

## Part 1. Modeling principles

Six rules. Everything downstream is a consequence of one of them.

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

**P6 (new in v3). When a line is fetched is a policy; when a core consumes a burst is a rule.**
`fill(c, k)` is when the memory system installed burst `k`'s lines and is set by whatever
prefetch policy is configured, so it may be arbitrarily early. `served(c, k)` is when the core
takes delivery, is strictly increasing in `k`, and is never earlier than `served(c, k-1) + 1`.
Every prefetch-shaped idea in this model changes the first and none of them changes the second.
The two are joined only by residency: an early fill helps exactly if the line is **still there**
when the core's demand access arrives, which is why eviction-before-use is a measured loss and
not a corner case (4.6). Collapsing the two, which v2 did, leaves no way to express a fetch that
nobody is waiting for (D14).

---

## Part 2. Software to hardware mapping

The centre of this plan. Each row is a hardware structure, what it physically does, the
software object that stands for it, the parameters that shape it, and the statistic that
proves it is doing its job.

### 2.1 Compute side

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| PE / core compute stage | In-order, **one burst at a time**. Consumes burst `k`, computes for the trace's own inter-burst spacing, then needs burst `k+1`. An SNN PE has no reorder buffer and no second set of weights in hand. | `CoreState` (3.3); the service rule of 4.5 | `core_model = stall_in_order`, `core_accept_ii` | `core_stall[c]` split by cause, bursts-served-per-1000-cycles |
| L1 burst prefetcher | Fetches the lines of burst `k+1` into the L1 while the core is still stalled on burst `k`. Sits **in the memory system**; the PE has no buffer and no run-ahead | `Prefetcher ∈ {none, next_burst(d)}` plus `PrefetchState[c]`, a **separate module** from the core state machine (4.6) | `prefetch_policy`, `prefetch_distance`, `l1_demand_reserve` | coverage, timeliness, wasted fetches, extra evictions |
| Weight address generator | Turns a tensor coordinate run into line indices | `AddressMapper::expand(Burst) → [LineId]` | `cin_block`, `cout_block`, `weight_bytes` | `lines_per_burst` distribution |
| Tile / activation refill | A new activation tile arrives machine-wide; all PEs restart together | Hard barrier + `tile_origin[]` (Part 5) | `tile_sync = hard` | `barrier_slack_cycles[c]` |

`phase` is a state field rather than a time field on purpose. At the instant a core is
refused you must record *that* it is stalled; *when* it resumes is unknowable then. A single
`ready_time` cannot express "waiting, resume time unknown", which is the representational gap
that forced D2's polling. v3 removes `ready_time` outright: the next burst's `E_Issue` is
scheduled at the instant the previous burst is served, so there is no predicted time to
compare against and no `max()` to evaluate (P2, 4.5).

Two rows where one used to be is the whole of C1 and C2, and the split is the point. The compute
stage owns the service rule and cannot be configured out of it. The prefetcher owns everything a
prefetch-shaped idea can touch, and it lives below the L1 port, so **no row of this table
changes when it is switched on**: same `CoreState`, same issue rule, same events. The cost of
running ahead is paid in L1 capacity and L1 MSHR credits, which are cache resources that already
exist, rather than in new storage inside the PE.

### 2.2 L1: private, one per core

| Hardware | Physical behavior | Software model | Parameters | Instrument |
|---|---|---|---|---|
| L1 tag + data array | Set-associative SRAM; a line may sit in any way of one set | `CacheArray { probe, free_slot, victim_candidates, insert, invalidate }` | `l1_size_bytes`, `l1_assoc` | hit rate, per-set pressure |
| L1 replacement state | LRU recency stack / FIFO counter / LFSR | `ReplacementPolicy { on_hit, on_fill, on_invalidate, pick_victim }`, a **separate module** from the array | `l1_policy ∈ {lru, fifo}`; `random` is a placeholder, rejected at config load (A5) | victim age distribution |
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

**`l2_banks` defaults to 1** *(decided 2026-08-17)*, so the ordinary profiling run has a single
L2 bank and the banking machinery is present but not exercised. `bank_of()` takes the **low**
bits of the set index, and which end it takes is a config knob rather than a constant, because
the bank-conflict statistic exists to tell layouts apart and cannot do that if the banking is
hardwired to spread them. At `l2_banks = 1` the two settings of that knob are indistinguishable
by construction, so **any fixture asserting bank behavior must set `l2_banks >= 2` or it passes
vacuously**, the same trap N13 records for `ii = 0`. One consequence to keep visible in the
results: at `l2_banks = 1` every pair of simultaneous L2 accesses conflicts, so "bank-conflict
cycles" degenerates into L2 port queueing and should be reported under that name instead.

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

### 2.5b The default configuration *(new in v3, decided 2026-08-17)*

The values a run uses when nothing overrides them. A default is not a constant: every row here
is a knob, and the point of writing them down together is that the *totals* at the bottom are
what the model actually charges, and they are easy to lose across four sections.

| Parameter | Default | Why this value |
|---|---|---|
| `l1_latency` | 0 | **a differential, not an absolute** (see below): the extra cycles an L1 hit costs over the weight access the trace's schedule already assumes. 0 calibrates the cache against the scratchpad baseline. This does not make the L1 free, because `l1_ii` still charges a port slot per line |
| `l1_to_core_latency` | *(does not exist)* | folded into `l1_latency` on the hit path; the fill path charges nothing, modeling critical-word bypass. Stated here rather than left in a code comment |
| `l2_latency` | *(to set)* | tag plus data access of the shared L2 |
| `l2_to_l1_latency` | 0 | the return leg is not charged by default. The **knob stays**, so D10's split between "the L2 MSHR frees" and "the core finishes" remains structural and reopens by setting it nonzero |
| `l2_miss_latency` | *(to set)* | DRAM round trip |
| `l1_ii` | 1 | a single-ported L1 accepts one line per cycle. A burst of `n` lines therefore costs `n` cycles of acceptance before any latency, which is what makes `lines_per_burst`, and through it the `cout_block` layout sweep, cost real time |
| `l2_ii` | 1 | one L2 access per cycle per bank |
| `l2_banks` | 1 | ordinary profiling does not exercise banking (2.3) |
| `core_accept_ii` | 1 | one burst service per core per cycle (4.5) |
| `prefetch_policy` | `none` | the machine as built (4.6) |
| `prefetch_distance` | 0 | bursts fetched ahead of the one the core is on |
| `l1_demand_reserve` | `lines_per_burst` | L1 MSHR entries prefetch may never occupy, so one demand burst can always allocate. The prefetch budget is `l1_mshrs − l1_demand_reserve`, which is why prefetch does nothing at all unless `l1_mshrs > lines_per_burst` (4.6) |
| `l2_demand_reserve` | `lines_per_burst` | the same guarantee in the shared L2 file |
| `n_cores` | *(swept)* | **8 to 256**, decided 2026-08-17. Every scale claim in this plan is against that range, not the 1024 figure v2 quoted |
| `inclusion` | `non_inclusive` | *(changed 2026-08-17)* the sweep runs on this setting. A fill installs in both levels and the L2 never back-invalidates, so an L1 may keep serving a line the L2 dropped, which is correct here and is the source of the extra effective capacity (4.4). `inclusive` is still implemented and still tested (V9), it is simply not the grid |

Which collapses the timing model to three numbers plus queueing:

```
L1 hit            l1_latency                                            = 0
L1 miss, L2 hit   l1_latency + l2_latency + l2_to_l1_latency            = l2_latency
full miss         + l2_miss_latency
```

**Why `l1_latency` is a differential, and why that makes it 0** *(decided 2026-08-17)*. The
study exists to compare this cache against a **scratchpad**, and the weight trace's local ticks
were produced by a machine that already accessed its weights on every one of those ticks. So
`gap_k` is not pure compute: it is compute plus the scratchpad access. Charging an absolute L1
hit latency on top of it charges the access twice, and the burst-to-burst period becomes
`max(gap_k, core_accept_ii) + l1_latency`, which at `gap = 1` and `l1_latency = 1` is **2 cycles
against the scratchpad's 1**. Every cache configuration would then carry a 2x penalty that no
cache caused.

`l1_latency` therefore measures only what an L1 hit costs **above** the access the trace already
assumes, and at 0 the model has a property worth stating as a requirement rather than an
observation: **a 100% hit run reproduces the scratchpad timeline exactly.** `tile_origin[N]`
equals `tick_base[N]`, which is V1, already in the plan. The cache degrades to the scratchpad
when nothing misses, so every cycle it costs above the baseline is a miss and nothing else, and
V1 stops being only a regression test and becomes the calibration of the comparison.

Charging the tag-check cycle is still available as a **sensitivity run** at `l1_latency = 1`,
where the honest baseline is not `tick_base` but `tick_base` plus one cycle per burst, because
the scratchpad would pay that cycle too. V27 computes that number from the trace alone, so the
sensitivity run has an exact oracle rather than an argument. It is also the test that N14
accumulates rather than absorbs: under a self-timed schedule a per-burst constant compounds into
`tile_origin` instead of sitting in a corner.

**Zero-latency legs are legal and must not form a cycle within one timestamp**, and with both
`l1_latency` and `l2_to_l1_latency` at 0 this is the ordinary case rather than a corner. An L1
hit now issues, probes, and serves the core all at one tick, and `E_L2Probe` schedules
`E_L1Fill` at the same tick as itself. Neither breaks the order: a fill is class 0 against a
probe's class 2, so it is popped next and lands before any probe still queued at that tick,
which is what 3.6 wants. What keeps the run from looping forever at one timestamp is that
serving a burst schedules the next `E_Issue` at `now + max(gap_k, core_accept_ii)`, which
advances by at least 1. **That makes `core_accept_ii >= 1` a termination guard**, not only a
modeling choice, and it is the argument against setting it to 0 (4.5). Any future zero-latency
leg must preserve the same property.

### 2.6 Deliberately not modeled

Stated so a reviewer knows these are decisions, not oversights.

Writes, dirty bits, writebacks (weights are read-only in this study) · inter-L1 coherence
(**no writers, so there is nothing to keep coherent; note that this also removes the usual
justification for inclusion, see 4.4**) · peer-L1 forwarding (the one thing `non_inclusive`
would want and does not have, 4.4) · DRAM row buffers, bank conflicts, refresh (the channel is
a bandwidth-plus-latency abstraction) · NoC topology and contention · **address-predicting
prefetchers** (stream, stride, correlation): the pipelined burst fetch of 4.6 *is* modeled, and
it is not a predictor, it walks an address stream the core already holds; a prefetcher that
guesses is a separate `Prefetcher` implementation and nobody has asked for one · virtual memory and TLBs ·
the activation and output-feature path · **finite
bank input queues**: port serialization is timed correctly at `k × ii` but costs nothing
structurally, because requests waiting on a bank live as scheduled future events rather than in
a queue with a depth (4.3).

---

## Part 3. The control flow

### 3.1 Event alphabet

Six event kinds, unchanged in number by v3. Each is a crossing of a physical boundary (P4).

| Event | Fires when | Does |
|---|---|---|
| `E_Issue(core, k)` | burst `k` becomes due at the core: `served(c, k-1) + max(gap, 1)`, or the tile origin for the first burst (4.5) | expands the burst, reserves L1 port, schedules a **demand** `E_L1Probe` per line, and notifies the prefetcher (4.6) |
| `E_L1Probe(req)` | the L1 port accepted this request, `l1_latency` later | L1 array probe, then L1 MSHR triage |
| `E_L2Probe(req)` | the L2 bank port accepted it, `l2_latency` later | L2 array probe, then L2 MSHR triage |
| `E_L2Fill(mshr2)` | the memory channel returns data | install in L2 (victim, evict, back-invalidate if `inclusive`), retire the entry, wake its waiters |
| `E_L1Fill(mshr1)` | data reaches the L1 | install in L1, retire the entry, wake its waiters. On a **demand** entry, close out the line in its core's burst and serve the burst if it was the last one. On a **prefetch** entry, notify nobody |
| `E_Barrier(tile)` | the last core clears tile `N` | set `tile_origin[N+1]`, schedule every core's first `E_Issue` of tile `N+1` |

No `E_PortFree`. A port is a timestamp, not a queue: a request asks it for an accept time and
gets one immediately. That is the whole benefit of occupancy over quota.

**C2 adds no event kind**, which is the strongest evidence that it belongs where it now sits. A
prefetched burst travels the same `E_L1Probe` / `E_L2Probe` / `E_L2Fill` / `E_L1Fill` chain as
any other request, carrying `demand = false`, and the only difference is what happens at the
end: a demand fill completes a line for a waiting core, a prefetch fill installs a line and
stops. There is likewise no separate "serve" event: under every policy defined here the core is
served exactly when the last line of the burst it is waiting for lands, so service is a call
inside `E_L1Fill`, not a scheduled event (4.5, 4.6).

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
    burst     = k          # which burst of the core's tile this line belongs to. A demand
                           # request carries the core's current cursor; a prefetch request
                           # carries a future one, for attribution only
    demand    = true       # false for a prefetch: nobody is waiting on it, it never enters
                           # a wait set, and it is DROPPED rather than refused. 4.6
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

CoreState:                       # revised in v3, 4.5. v2's ready_time is gone
    tile
    cursor                       # the ONE burst the core is on. Trace order, always
    phase ∈ {Computing, Stalled, AtBarrier, Done}
    pending_lines                # lines of THIS burst still outstanding. N7 atomicity
    issued_at                    # SimTime the current burst was issued, for attribution
    served_time                  # SimTime of served(c, cursor - 1); NONE at a tile start

PrefetchState:                   # one per L1. MEMORY-SIDE state: not the core's. 4.6
    pf_cursor                    # next burst index to fetch ahead
    outstanding                  # prefetch lines in flight, <= l1_mshrs - l1_demand_reserve

refusal_counter                  # global monotonic; stamps Request.refusal. 3.8
tile_origin[]                    # simulated origin of each tile (Part 5)
```

`slot_wait` and `line_wait` are two indexes into **one** logically FIFO-ordered population
(3.7). The merge at 3.4 is an index join, not a priority reconciliation.

`CoreState` has one cursor and one set of `pending_lines` because the core has one burst in
flight, under every policy. The second cursor lives in `PrefetchState`, on the other side of the
L1 port, and `pf_cursor - cursor` is the fetch-ahead depth that the whole of C2 exists to move.
Keeping them in separate structs is not tidiness: it is the statement that the PE is unchanged,
checkable by the fact that no field of `CoreState` mentions prefetching. `phase` names the four
states of the compute stage; `Stalled` means the burst it issued has not come back.

### 3.4 Triage, retire, wake

One triage function per level, called on **first arrival** and again on **every wake** (D4).

```
triage_L1(r, now):
    F = l1_mshr[r.core]

    slot = l1[r.core].probe(r.line)                   # --- array ---
    if slot != NoSlot:
        l1_policy[r.core].on_hit(slot)
        release_reservation(r, F, L1, now)
        core_line_done(r, now)                        # D8: latency already paid
        return HIT                                    # v3: takes the REQUEST, which
                                                      # carries r.burst. 3.3

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
        else:           core_line_done(w, now)

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

### 3.4b The core side (new in v3)

Three functions, and between them they are the whole of C1. `core_accept_ii` is the minimum
number of cycles between two consecutive burst services at one core; it is `1` and is a
parameter only so that the number appears in the config rather than in the source (D8's
lesson).

```
core_line_done(r, now):                        # ONE line has landed for a waiting core
    if not r.demand: return                    # a prefetch completes nobody. 4.6
    cs = core[r.core]
    cs.pending_lines -= 1
    if cs.pending_lines > 0: return            # N7: the burst is atomic
    serve(r.core, now)


serve(c, now):                                 # the core takes delivery of burst cursor
    cs   = core[c]
    want = (cs.served_time == NONE) ? tile_origin[cs.tile] + local_tick(c, 0)
                                    : cs.served_time + max(gap(c, cs.cursor - 1),
                                                           core_accept_ii)
    assert now >= want                         # I13. Satisfied by construction: the core
                                               # issued this burst no earlier than want
    stats.core_stall[c]    += now - want       # >= 0. Sums to the tile stretch, Part 8
    stats.fetch_latency[c] += now - cs.issued_at

    cs.served_time = now                       # served(c, cursor) = now
    cs.cursor     += 1

    if cs.cursor == n_bursts(c, cs.tile):
        cs.phase       = AtBarrier
        cs.served_time = NONE                  # the floor does not cross a tile. 4.5
        barrier_arrive(c, now)                 # Part 5. No trailing compute tail, Q10
        return

    cs.phase = Computing
    schedule(E_Issue(c, cs.cursor), now + max(gap(c, cs.cursor - 1), core_accept_ii))


on E_Issue(c, k, now):
    cs    = core[c]
    lines = mapper.expand(trace_burst(c, cs.tile, k))        # N7: all or nothing
    cs.pending_lines = |lines|
    cs.issued_at     = now
    cs.phase         = Stalled
    for l in lines:
        accept = l1_port[c].reserve(now)                     # P3
        schedule(E_L1Probe(Request{core = c, line = l, burst = k, demand = true}),
                 accept + l1_latency)
    prefetcher.on_demand_issue(c, k, now)      # 4.6. Below the port; the core does not
                                               # wait for it and cannot observe it
```

Every line above would be identical if prefetching did not exist, except the last one, and that
last one returns nothing. That is what "the PE is not changed" means operationally: C2 is
reachable from the core only through a call that cannot affect it.

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
| 0 | `E_L2Fill`, `E_L1Fill` | state changes land before anything looks at state. A core is served inside its last demand fill, so services land here too |
| 1 | `E_Barrier` | the barrier observes completed fills, and therefore completed services |
| 2 | `E_L1Probe`, `E_L2Probe` | lookups see this cycle's fills; closes D4's "queued miss became a hit". Demand and prefetch probes share this class and are ordered against each other by the key like anything else |
| 3 | `E_Issue` | new demand enters last |

`seq` is a monotonic counter assigned at *schedule* time, so the order is total and a re-run
is byte-identical (D11). This ordering is not cosmetic: under LRU it *is* the eviction order
(D7).

For class 2 specifically, `effective_age` and the `core_id`/`seq` tiebreak collapse; see 3.8.

*(v3)* Service is a call inside `E_L1Fill` rather than an event of its own, so it inherits class
0 and lands ahead of the barrier automatically. That ordering is load-bearing rather than
incidental: a core's last burst of a tile is served, and only then does the core arrive at the
barrier, so a barrier resolving in the same cycle must observe the service or `tile_origin[N+1]`
is set one service too early. It is an exact-tick effect and it is reachable in the unbounded
baseline, where every latency is zero (V26).

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
  waiting population, up to `n_cores × lines_per_burst` entries, on a hot path.

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
   dead fields for class 3. Comparison is one small integer instead of a three-field tuple; in
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
`cores × lines_per_burst`, "nothing at any plausible core count". That conclusion is right and
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

**Both bounds are unchanged by C2**, and the reason is the single rule that a refused prefetch
is **dropped, never queued** (4.6). Nothing without a waiting core ever enters a wait index, so
the waiting population stays backed one-for-one by demand credits and the v2 arithmetic stands
verbatim at any `prefetch_distance`. This is the specific property that made "drop" the right
refusal rule rather than merely the simple one: a prefetch permitted to wait would occupy a
selection set with no L1 MSHR entry behind it, and 4.1's whole argument is that those sets are
views over entries that already exist.

I6b survives for a second reason worth stating, since prefetch does create same-line traffic
that a demand-only machine could not. If a prefetch for line `X` is outstanding when the core's demand
request for `X` arrives, the demand request finds that entry and **merges as a target**; no
second entry is allocated and only the primary ever reached the L2.

Corollary worth asserting (I12): **if `l2_tgts_per_mshr >= n_cores`, the L2 line-wait sets are
provably always empty.** That is a real design lever and it belongs in the sweep discussion.

*At the L1 the backing store is the core, not the L1 MSHR file.* A request in an L1 wait set
has not allocated an entry: `BLOCKED_TARGETS` means it waits to become someone else's target,
`BLOCKED_POOL` means there was no slot. I6 says this directly. Its physical home is the core's
outstanding-burst registers, bounded by N7:

```
|e.line_wait|  <=  lines_per_burst - l1_tgts_per_mshr, and 0 if expand deduplicates
```

**The coupling to the core model must be written down** *(revised in v3)*. A core with an
outstanding burst issues nothing further, so demand stops at the source and no queue ever has to
refuse anyone upstream. That is what makes the sets free, and C1 (4.5) is what guarantees it.

The prefetcher of 4.6 is the "run-ahead" v2 warned about here, and the warning is answered
rather than withdrawn, in two independent ways. Its requests never wait, so they cannot enter
these sets at all. And it is itself bounded, not by refusals but by a **credit budget**,
`l1_mshrs - l1_demand_reserve`: when the budget is exhausted it stops issuing and resumes as its
own fills retire. **A prefetcher that runs until something refuses it is not admissible** (N16),
because then the wait sets, rather than a budget, would be what stops it, and they would need a
depth limit that this model says is not hardware. The core model, the drop rule, the prefetch
budget, and "wait sets are free" are one decision, not four.

### 4.2 Consequence of holding the L1 MSHR across the L2 wait

L1 MSHR occupancy is the **full round trip including L2 queueing delay**, not just the
L1-to-L2 latency. Two things follow:

- `l1_mshrs` is coupled to `l2_mshrs`: L2 pressure lengthens L1 occupancy. A sweep must report
  both, and a result attributed to `l1_mshrs` alone is suspect.
- Under `prefetch_policy = none` with a single-line burst, `l1_mshrs > 1` is inert by
  construction. The pool binds only when a burst expands to more lines than the pool holds.
  That is permitted by the trace format and **does not occur in the current corpus**, so on
  that configuration `l1_mshrs` should be reported as inert-by-construction rather than swept.
- *(new in v3)* **The prefetcher is what makes `l1_mshrs` bind, and `l1_mshrs` is what lets the
  prefetcher exist.** The budget is `l1_mshrs - l1_demand_reserve`, so at
  `l1_mshrs = lines_per_burst` the budget is zero and prefetching is off no matter what
  `prefetch_distance` says; every entry above that is one more line the L1 may have in flight
  ahead of the core. `prefetch_distance` and `l1_mshrs` are therefore a two-dimensional sweep
  in which neither axis is interpretable alone, and a configuration whose budget cannot hold a
  full burst is measuring the pool rather than the policy. D1 warns on exactly that case, and
  the results table must carry the budget beside the distance.

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
that bank** in the window. It reaches the cores too: atomic bursts (N7) mean a burst is not
complete until its last line lands, so bank delay produces a later fill, a later `served(c, k)`,
and a later next `E_Issue`. The loop is closed. *(v3: C2 does not open it. The core's demand path
is untouched, so that chain is exactly as above. The prefetcher's own requests contend for the
same banks, and a saturated bank throttles prefetching too, through its credits rather than
through a queue: fills that are late return budget late, and the prefetcher stops issuing when
the budget is out, N16.)*

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
is the simulator's widest inner loop, though at the sweep range of 8 to 256 cores (2.5b) it is
a scan of at most 256 arrays rather than the scaling hazard v2 described.

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

### 4.5 A core handles one burst at a time, and its schedule is self-timed (new in v3)

**The rule.** A PE issues one weight burst, stalls at it until every line of it has been
delivered, computes on those weights, and only then needs the next burst. There is never a
second burst of weights in the PE unless an issue policy put it there (4.6), and even then the
PE consumes them one at a time, in trace order.

**The schedule.** Write `gap_k = local_tick(c, k+1) - local_tick(c, k)`, the spacing the weight
trace records between two consecutive bursts of core `c` inside one tile. Under
every prefetch policy, since prefetching changes when lines are *fetched* and never when the
core *asks*:

```
issue(c, 0)   = tile_origin[tile] + local_tick(c, 0)
issue(c, k+1) = served(c, k) + max(gap_k, core_accept_ii)
served(c, k)  = the cycle the last line of burst k lands at the core
                ( >= served(c, k-1) + core_accept_ii by construction, I13 )
```

**The trace contributes spacing, not appointments.** `gap_k` is the MAC work that burst `k`'s
weights feed. It is a duration the core owes after the weights arrive, so it is added to
`served(c, k)` and never to an absolute tick. v2 added it to an absolute tick, which let a core
that had already lost 60 cycles arrive at its next burst on schedule anyway, discarding the
loss (D13). Under v3 a stall shifts the whole remainder of the tile by the full stall, and the
shifts accumulate until the barrier collects them.

**The service floor, which is the half that survives every policy.**

```
served(c, k+1) >= served(c, k) + core_accept_ii,          core_accept_ii = 1
```

This holds whether burst `k+1` hits or misses, whether its line was fetched a thousand cycles
early or is still on its way, and under every prefetch policy. It is what an in-order PE with
one set of weight registers means, and it is the model's answer to "a hit cannot let a core
overtake itself".

It is **satisfied by construction rather than enforced**, and that is a property of the C2
decision, not a coincidence. Since the run-ahead lives in the memory system and never delivers
anything to the core, the core cannot receive burst `k+1` before it has asked for it, and it
does not ask before `served(c, k) + max(gap_k, 1)`. The floor therefore never binds and appears
in the code only as an assertion (I13), whose job is to catch a future core-side policy that
would violate it silently. Had the fetched-ahead data been delivered into the PE instead, this
would have been an active mechanism and a source of arguments about drain semantics; it is not.

**`core_accept_ii` is a parameter and its value is 1.** It is in the config rather than the
source for D8's reason: a structural constant that nobody can find is a structural assumption.

**What it costs to get this wrong**, and why it is not a detail: `stall_cycles` is the headline
per-core number, `tile_origin[N+1] - tile_origin[N]` is the headline per-tile number, and both
are integrals of this recurrence over a tile. A rule that absorbs stalls understates every
cache pressure result in the study, in the direction that makes the cache look adequate.

**The unbounded baseline still collapses exactly, so V1 is preserved, and at `l1_latency = 0`
that baseline is also the scratchpad comparison (2.5b).** With every access a hit,
`served(c, k) = issue(c, k)` and the floor is inert, so `issue(c, k+1) = issue(c, k) + max(gap_k, 1)`. That telescopes to
`tile_origin[tile] + local_tick(c, k)` for every `k` whenever `gap_k >= 1`, which is the trace's
own schedule, so `tile_origin[N] == tick_base[N]` for every tile exactly as v2 promised.
`gap_k = 0`, two bursts at one local tick, is the one case where v3 and the trace differ by
construction: the core serializes them one cycle apart. The trace format permits it, the
current corpus does not contain it, and V20 asserts the count of such pairs so that a future
corpus cannot introduce them silently.

**The tile boundary, twice.** A core arrives at the barrier at `served(c, last)`, and the tile
then waits out whatever compute is left *(revised 2026-08-17, Q10)*. A tile's length is its
`mac_cycles`; the ticks carrying weight bursts are a prefix of it, and the remainder,
`tile_tail[N] = mac_cycles[N] - max_tick[N]`, is compute the core still owes after its last
weights land. It is charged once at the tile level rather than per core, for two reasons: the
trace stores `mac_cycles` already reduced to the max over that tile's cores
(`src/tracegen.py:278`), so per-core tails do not exist on disk; and charging it at the boundary
leaves every core arriving at its own last service, so `barrier_slack_cycles` keeps measuring
what it measures. `tile_tail` is at least 1 by construction, which also subsumes the tile-seam
cycle discussed next.

Measured over the corpus on 2026-08-17: the tail is 0 for every sampled tile of loas,
prosperity, spinalflow, and most of ptb, and it is **20 cycles, 11.7% of a 172-cycle tile, on
every one of the 64 tiles of ptb `layer_01` and `layer_03`**. Charging nothing would end those
tiles 12% early, compounding across tiles and into every later layer, and V1 would fail there in
a way that looks like a cache bug.

The second boundary effect is the service floor, and it is switched **off** across the seam:
`served_time` is cleared at the barrier, so the first burst of tile `N+1` is floored by
`tile_origin[N+1] + local_tick(c, 0)` alone. Left on, the one core whose last service *defines*
`tile_origin[N+1]` would be unable to take its first burst of the new tile in that same cycle,
and every tile would gain a cycle over the trace unless `tick_base` happens to use the same
convention. The floor is a statement about one core's compute stage between two of its own
bursts, and a barrier already serializes everything it could have said. Making it stop at the
seam keeps V1 exact without depending on the trace generator's tile-base convention.

**This rule is what N7 and 4.1 were already resting on.** Burst atomicity, the credit bound on
the wait sets, and the claim that `l1_mshrs` is inert under the current corpus are all
consequences of one burst at a time. v2 stated them individually and derived them from
`core_model = stall_in_order`; v3 names the rule they come from.

### 4.6 Prefetch is a memory-system policy, and the core never learns about it (new in v3)

The pipelined burst fetch sketched on 2026-08-16 is a **prefetch policy**, in the precise sense
that it moves a fetch earlier than the consumption that needs it and changes nothing else. It
was decided on 2026-08-17 that it lives **at the L1, not in the PE**: the fetched line is held
in the cache like any other line, and the core reaches it through its ordinary demand access.
The PE keeps the behavior of 4.5 exactly, with no weight buffer, no run-ahead, and no second
burst in hand.

**`d` is `prefetch_distance`: how many bursts ahead of the one the core is working on the L1 may
fetch.** `d = 0` is `prefetch_policy = none`, the machine as it exists today. `d = 1` is the
2026-08-16 sketch: while the core is stalled on burst `k`, the L1 is already pulling in burst
`k+1`.

**The one assumption that makes it implementable.** The prefetcher must know burst `k+1`'s
addresses while burst `k` is still outstanding. It does not predict them: within a tile, the
weight address generator walks a spike queue that is resolved when the tile begins, so the
address run is derivable ahead of time and the prefetcher is fed by that generator running
ahead of the compute stage. **This is a claim about the hardware and it belongs in the
write-up.** The compute stage is untouched, which is the decision above; the address generator
is not, and a design whose spike queue is produced incrementally during the tile cannot run this
policy at all. Its honest fallback would be a stride or stream predictor, which is a different
policy with a different result, and it is not modeled (2.6). The policy also never crosses a
tile boundary, since the next tile's activations do not exist until the barrier resolves, so
the first burst of every tile is never prefetched and the fraction of bursts in that position
is a reported ceiling on how much this can win.

**The interface.** One hook, called from `E_Issue` (3.4b), returning nothing:

```
Prefetcher:
    on_demand_issue(c, k, now)

none:
    on_demand_issue(c, k, now): pass


next_burst(d):
    on_demand_issue(c, k, now):
        P = pf_state[c]
        P.pf_cursor = max(P.pf_cursor, k + 1)             # never behind the core
        while P.pf_cursor <= k + d and P.pf_cursor < n_bursts(c, tile(c)):
            for l in mapper.expand(trace_burst(c, tile(c), P.pf_cursor)):
                if P.outstanding >= l1_mshrs - l1_demand_reserve:
                    stats.pf_budget_exhausted += 1; return        # bounded HERE. N16
                accept = l1_port[c].reserve(now)                  # a REAL port slot
                schedule(E_L1Probe(Request{core = c, line = l, burst = P.pf_cursor,
                                           demand = false}), accept + l1_latency)
                P.outstanding += 1
            P.pf_cursor += 1
```

**What a prefetch request may and may not do.** It travels the ordinary triage path of 3.4 with
four differences, and each one exists to protect a property established elsewhere:

| At | A demand request | A prefetch request | Because |
|---|---|---|---|
| array hit | `policy.on_hit`, complete the core's line | **drop**, and do **not** touch replacement state | a prefetch is not a use; letting it promote recency would let the prefetcher rewrite LRU order (2.2's rule that `probe` is not an access) |
| matching MSHR entry | merge as a target, or wait on the line | **drop** | the line is already coming; nothing is waiting for this copy |
| no slot, or the entry's targets full, or fewer than `demand_reserve` entries left | refuse and register on a wait index | **drop**, counted by reason | keeps the wait population backed one-for-one by demand credits, which is 4.1's whole argument |
| otherwise | allocate and forward | allocate with `demand = false` and forward | identical below this point, including at the L2, where `l2_demand_reserve` applies the same way |

**Promotion.** When the core's demand request for burst `k+1` arrives and finds an outstanding
prefetch entry for that line, it merges as a target and sets `e.demand = true`. The fill then
completes the core's line as usual. This is the **late prefetch** case: the fetch started early
but not early enough, and the core still saves whatever part of the latency had already elapsed.
It is the reason `Mshr.demand` is a mutable field rather than a constructor argument.

**The worked example**, at the 2.5b defaults, one core, single-line bursts, `gap = 1`,
`l1_latency = 0`, `l1_ii = 1`, `l2_latency = 10`, `l2_miss_latency = 100`, so a full miss costs
110 cycles. Burst 1 misses in every column.

| cycle | `none` | `next_burst(1)`, timely | `next_burst(1)`, evicted before use |
|---|---|---|---|
| 0 | core issues b1, probes, misses, forwarded to L2 | same, **and the prefetcher issues b2's line**, which the L1 port accepts at 1 | same |
| 1 | idle | b2's prefetch probes, misses, forwarded to L2 | same |
| 110 | b1 fills, **`served(b1) = 110`** | b1 fills, `served(b1) = 110` | b1 fills, `served(b1) = 110` |
| 111 | core issues b2, probes: **miss**, forwarded | b2's prefetch fills the L1 and notifies nobody; the core issues b2 and probes: **HIT**, `served(b2) = 111` | b2's prefetch line was **evicted** before now; the core probes: miss, forwarded |
| 221 | b2 fills, `served(b2) = 221` | | b2 fills, `served(b2) = 221`, plus a wasted fetch and whatever it evicted |

110 cycles saved in the middle column, nothing saved in the right one, and the right column is
not hypothetical: it is what the policy does under L1 pressure, which is the regime the study
cares about. **Prefetching can lose here**, unlike in the PE-buffer design that was not chosen,
and that is the honest cost of leaving the data in the cache.

The middle column is also a live test of the class order (3.6). The prefetch fill and the demand
probe both land at cycle 111; the fill is class 0 and the probe class 2, so the fill installs
first and the probe hits. Reverse those classes and the same run reports a miss, a second
fetch, and 221. V23 asserts the cycle numbers for exactly this reason.

The middle column shows the service floor doing its work without being a mechanism. Burst 2's
line became resident at 111 and the core was served at 111 rather than earlier, because it could
not ask before 111. Had the line been resident since cycle 0 the answer would still be 111. That
is 4.5's rule and your original statement of it: a hit does not let a core overtake itself.

**What it costs.** The same lines are fetched, so aggregate DRAM traffic is unchanged and its
distribution over time is not, which is both the mechanism and the risk. Concretely: L1 port
slots, since at `l1_ii = 1` every prefetch takes a cycle the demand stream could have used; L1
MSHR credits, up to `l1_mshrs - l1_demand_reserve` of them, held across full round trips; L2
bank slots and DRAM bandwidth pulled earlier, arriving during what used to be idle stall; and
L1 capacity, since a line fetched early occupies a way for longer and may evict a line the core
was about to want. The reserve is what keeps all of this from starving demand: prefetch can
never take the last `l1_demand_reserve` entries, so a demand burst can always allocate.

**What to sweep and what to report** is in Part 8: coverage, timeliness split into timely versus
late versus wasted, extra evictions attributable to prefetched lines, and the budget-exhausted
count, which tells you whether `prefetch_distance` or `l1_mshrs` was the binding constraint.

---

## Part 5. Time, and why `tick_base` does not enter the engine

The old spec had two clocks (trace time and simulated time) and most of its defects lived at
the seam. The barrier decision removes the seam entirely.

**Trace time is only ever tile-local.** The engine never uses `tick_base`:

```
tile_origin[0]   = 0
tile_tail[N]     = mac_cycles[N] - max_tick[N]        # from the trace, >= 1. 4.5, Q10
tile_origin[N+1] = max over cores of served(c, last burst of tile N) + tile_tail[N]

issue(c, 0)      = tile_origin[tile(c)] + local_tick(c, 0)            # once per tile
issue(c, k+1)    = served(c, k) + max(gap_k, core_accept_ii)          # 4.5, EVERY policy
served(c, k)     = when the last line of burst k lands at the core
                   ( >= served(c, k-1) + core_accept_ii by construction, I13 )

pf_issue(c, j)   = issue(c, j - d), the demand issue of the burst d ahead    # 4.6, and
                   the only thing prefetching changes about time             # not a core
```

*(Revised in v3.)* v2 had `issue_time(c) = max(tile_origin + local_tick(c, cursor),
ready_time[c])`. Three things changed. Absolute local ticks now enter only at the first burst
of a tile, and every later burst gets `local_tick` as a **difference**, so a stall is carried
rather than absorbed (D13, 4.5). The `max` against a stored `ready_time` is gone, and with it
the last predicted timestamp in the engine: the next `E_Issue` is scheduled at the instant the
event that determines it fires, which is what P2 asks for. And the recurrence is now
**policy-independent**: C2 adds a second, lower line for the prefetcher and leaves this one
untouched, which is the formal statement of "the PE is not changed".

`tile_origin` is a **measured** quantity replacing `tick_base`, a *derived* one. Three things
at once:

1. **One clock.** `local_tick` is an offset, never an absolute, so no expression adds or
   compares trace time with simulated time. The type confusion the old spec flagged as an open
   risk cannot be written.
2. **A free regression, and the study's calibration.** Under the unbounded baseline
   `tile_origin[N]` must equal `tick_base[N]` exactly, for every tile: a strong, cheap,
   whole-run oracle. At `l1_latency = 0` (2.5b) this is more than a regression test, since a
   100% hit run then *is* the scratchpad timeline, so every cycle the cache costs above
   `tick_base` is a miss and nothing else. It holds under
   **both** issue policies, and the second case is the stronger statement: with every access
   free, `served(c, k) = issue(c, k)` and there is nothing left for a prefetcher to hide, so
   every `prefetch_distance` must produce the same timeline on that configuration. Its event log
   legitimately gains prefetch events; any change to a `served` time there is a bug in the
   policy, not a result (V22).
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
| N8 | *(revised in v2, default changed in v3)* **Inclusion is a parameter**, `{inclusive, non_inclusive}`, default and sweep setting **`non_inclusive`**; `inclusive` is implemented and tested but not crossed with the grid (Q6). No coherence justification exists in this study; the tradeoff is effective capacity against guaranteed L2 hits on peer-L1-resident lines, and it is a result to report. `exclusive` is not offered until G1 is resolved. | an unjustified capacity penalty presented as a correctness requirement |
| N9 | *(revised again in v3)* **One burst in flight per core, and therefore wait sets that need no storage** (P5, 4.1, 4.5). Prefetch does not weaken it: prefetch requests are dropped rather than queued, so the waiting population stays backed one-for-one by demand credits at any `prefetch_distance`. | the credit supply stops bounding the sets; they need depth limits, adding a third concurrency bound |
| N10 | **Total event order** `(time, class, effective_age, core_id, seq)` over four classes (3.6). A core is served inside its last demand fill, so services inherit class 0 and land before the barrier. For class 2 the last three fields collapse to `(refused_bit, refusal_counter)` (3.8). | non-reproducible sweeps; a barrier that closes one service early |
| N11 | **A trace coordinate outside `workload_dims` aborts the run**, naming tile/tick/core/coord. | silently drops demand; corrupts every downstream statistic |
| N12 | **Strong typedefs** for `SimTime` and `LocalTick` from day one, plus `RefusalOrder` for the counter (3.8), so the three are mutually uncomparable. | the class of bug the old spec left open at unit 4 |
| N13 | *(new in v2)* **`ii = 0` is a modeling escape hatch, not a physical setting.** Any fixture asserting reservation order runs at `ii >= 1`. | V7 and the I7b tests pass vacuously (4.3) |
| N14 | *(new in v3)* **One burst at a time, self-timed.** A core issues burst `k+1` at `served(c, k) + max(gap_k, 1)`, where `gap_k` is a trace *difference*. Absolute local ticks enter only at the first burst of a tile. A stall shifts the rest of the tile in full (4.5, D13). | stalls are absorbed rather than accumulated; every pressure result is understated in the direction that flatters the cache |
| N15 | *(new in v3)* **Prefetching happens at the L1 and the PE is not changed.** The fetched line waits in the cache, the core reaches it through its ordinary demand access, and a prefetched line evicted before use is a real loss (4.6). The service floor `served(c, k+1) >= served(c, k) + core_accept_ii` therefore holds by construction under every policy, hit or miss. | the alternative is delivery into a `1 + d` deep PE weight buffer, which guarantees the win, changes the PE, and costs `d x lines_per_burst x line_bytes` per core |
| N16 | *(new in v3)* **A prefetcher is bounded by a credit budget or it is not admissible.** `next_burst(d)` stops when `l1_mshrs - l1_demand_reserve` is exhausted, never at a downstream refusal, and a refused prefetch is **dropped** rather than queued. | 4.1's credit bound breaks, wait sets stop being backed by demand credits, and every one of them needs a depth limit, which is hardware this model says does not exist |

---

## Part 7. Rebuild schedule

Eleven units, four phases, C5 added by v3. Nothing from the old tree is reused. Each unit ends with its own tests
**and a mutation check**: the prior effort learned that 125 passing checks hid 6 live
mutations, so "tests pass" is not the exit criterion; "tests fail when the code is wrong" is.

### Phase A: untimed foundations *(no clock exists yet)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **A1** | `types.h`: `LineId`, `CoreId`, `SlotId`, strong `SimTime` / `LocalTick` / `RefusalOrder` (N12), `Coord`, `Burst`, `WeightShape` | round-trip and boundary tests; any mix of the three time-like types fails to compile |
| **A2** | `AddressMapper` + `BlockPackMapper`: `expand`, `locate`, `line_of` | out-of-range coordinate throws before any output is produced; `line == tag × num_sets + set_index` holds |
| **A3** | *(extended in v3)* `TraceReader`: format v2 headers, tile/tick/core/burst decode, `spatial_factors` core decode, **plus the per-(core, tile) ordered burst list that 4.5 needs**: `n_bursts(c, tile)`, `local_tick(c, k)`, `gap(c, k)` as a difference, and the tile's `mac_cycles`, from which `tile_tail` is derived (Q10) | reads a real corpus file; malformed header throws (N11); `gap` is non-negative everywhere in the corpus and the count of `gap == 0` pairs is reported, not assumed zero (V20); the `tile_tail` histogram is reported, since it is 0 on most of the corpus and 20 on ptb `layer_01` / `layer_03` (4.5) |
| **A4** | `CacheArray` + `SetAssociativeArray` with **`invalidate` in the interface from the start** (N8) | probe/free_slot/victim_candidates/insert/invalidate; non-exact size ÷ (line × assoc) throws |
| **A5** | *(narrowed in v3)* `ReplacementPolicy` + LRU and FIFO. **Random is a placeholder**: it stays in the enum, is rejected at config load, and is not implemented (Q5) | policy sees only `SlotId`; both policies drive one array unchanged; `pick_victim` is given a candidate **set** and no policy may rely on its order, which is what keeps the interface open for Random later; `policy = random` throws with a message saying it is not implemented |

Phase A gate: an **untimed reference model** (array + policy only, no MSHRs, no time) that
reports hit rates. This is the oracle Phase C is checked against, the single most valuable
artifact of the rebuild and the thing the previous effort did not have.

### Phase B: timing primitives *(clock exists, hierarchy does not)*

| Unit | Contents | Exit criterion |
|---|---|---|
| **B1** | `Port { ii, latency, next_accept, reserve() }` | occupancy arithmetic; `ii = 0` never delays; `ii = latency` serializes; config rejects a negative `ii` and warns on `ii = 0` (N13) |
| **B2** | `EventQueue`: min-heap on `(time, class, effective_age, core_id, seq)` (N10) | total order; two identical runs produce identical event logs |
| **B3** | `MshrFile`: entries, `targets`, `line_wait`, `slot_wait`, the refusal counter, `find/allocate/retire`, the grant loop. *(v3)* `Request` carries `burst` and `demand`, `Mshr` carries a **mutable** `demand` for the promotion path, and `allocate` honours `demand_reserve` (4.6) | grant loop terminates with a free slot; the line-wait set resolves atomically on retire; the 3.8 out-of-order-insert counterexample sorts correctly; a non-demand allocation is refused once fewer than `demand_reserve` entries remain, and promotion of an entry to demand is idempotent |

### Phase C: the engine

| Unit | Contents | Exit criterion |
|---|---|---|
| **C1** | `CacheLevel` = array + policy + port + MSHR file; `triage()` per level | the 3.4 triage table exercised branch by branch |
| **C2** | *(v3: seven)* The seven event handlers; `retire`/`reinject` with the re-entry-level rule (3.5) | the V-list below |
| **C3** | *(extended in v3)* Tile barrier, `tile_origin`, core state machine: `core_line_done` / `serve` / `E_Issue` of 3.4b, the self-timed recurrence, and the service floor asserted rather than enforced (4.5, N14, N15) | `tile_origin == tick_base` under the unbounded baseline; V20, V21, V26, V27 |
| **C4** | *(revised in v2)* Two-valued inclusion: back-invalidation across L1s under `inclusive`, and the `non_inclusive` path (N8, 4.4). *(v3: `non_inclusive` is the default and the swept setting, but both branches are built)* | both branches exercised; `back_invalidations == 0` under `non_inclusive` |
| **C5** | *(new in v3)* `Prefetcher` interface, `none`, and `next_burst(d)`; the `demand = false` triage rules and the drop rule (4.6, N15, N16). Eleven units, not ten | `none` reproduces C3's event log byte-identically; no prefetch ever appears on a wait index; V22 through V25 |

### Phase D: harness

| Unit | Contents | Exit criterion |
|---|---|---|
| **D1** | Config load + validation (N7, N11, N13, N14, N15, N16, G1), single source of truth for the parameter set. *(v3)* adds `core_accept_ii` (default 1), `prefetch_policy ∈ {none, next_burst}`, `prefetch_distance` (default 0), `l1_demand_reserve` and `l2_demand_reserve` (default `lines_per_burst`) | every invalid combination throws under `-DNDEBUG`; `inclusion = exclusive` is rejected, not silently downgraded; `core_accept_ii < 1` and `prefetch_distance < 0` throw; `prefetch_policy = next_burst` with `prefetch_distance = 0` throws rather than silently meaning `none`; `demand_reserve >= mshrs` at either level throws, since it would make prefetching unreachable while claiming to be on; a prefetch budget smaller than `lines_per_burst` **warns**, since the run then measures the pool rather than the policy (4.2) |
| **D2** | Statistics and the results CSV | every stat in Part 8 emitted, one row per config; the stall breakdown sums to total stall and `core_stall` sums to the tile stretch (V21) |
| **D3** | Sweep driver | a full grid point runs end to end and reproduces byte-identically |

**Critical path:** A1 → A2 → A4 → A5 → *(Phase A gate)* → B3 → C1 → C2 → C3. A3, B1, and B2 are
independent of that chain, though C3 cannot finish without A3's burst lists. C4 and C5 both
depend on C3. All of Phase D depends on C2.

**Where v3 lands in the schedule.** C1 and C2 of this document are core-side, so they touch C3
and add C5 and nothing before them changes shape. A1 is complete and stays complete; A2 is in
progress and is untouched; A3 gains a query surface; B3 gains two one-bit fields. **No work
already done is invalidated**, which is the reason v3 is being written now rather than after
Phase A.

### Verification list

| # | Fixture | Asserts |
|---|---|---|
| V1 | unbounded baseline, full trace | `tile_origin[N] == tick_base[N]` for every tile, equivalently `tile_origin[N+1] - tile_origin[N] == mac_cycles[N]` exactly, which is the form that also checks `tile_tail` (4.5, Q10); hit counts equal the Phase-A reference model. At `l1_latency = 0` this run is also the scratchpad baseline (2.5b) |
| V2 | *(restated for v3)* core stalled on the burst at trace tick 5 until cycle 39 | all 36 bursts of the tile are issued and served, in trace order, none dropped and none coalesced. Under N14 they do **not** arrive at their original ticks: the whole tail shifts, and the last one is served no earlier than 34 cycles after it would have been (V20 is the exact-shift version of this) |
| V3 | any sweep point, re-run | byte-identical event log (N10). **Re-baseline once against v1**, deliberately: the 3.8 key change alters exact-tick tie order |
| V4 | two blocked requests, same line | exactly one MSHR ever allocated for it |
| V5 | queued miss; another core's fill lands that line first | resolves as a hit, consumes no MSHR (D4) |
| V6 | queued L2 hit whose line is evicted before service | re-probes to a miss, keeps its refusal stamp (D4) |
| V7 | target list at capacity, entry retires, **at `ii >= 1`** (N13) | **all** line waiters resolve at once, none allocates, **and reservation order equals key order**. At `ii = 0` this passes vacuously (4.3) |
| V8 | two hits, one set, one cycle, LRU | eviction order matches service order (D7) |
| V9 | L2 evicts a line another core's L1 holds, `inclusion = inclusive` | that L1 is invalidated; its next access misses (N8) |
| V9b | *(new)* same fixture, `inclusion = non_inclusive` | that L1 still **hits**; `back_invalidations == 0` (G2) |
| V10 | full sweep point, at `prefetch_distance > 0` | wait-set occupancy never exceeds `cores x lines_per_burst`, unchanged by prefetching because a refused prefetch is dropped, **and** `|e.line_wait| <= n_cores - l2_tgts_per_mshr` per entry (I11, 4.1) |
| V11 | request woken from `l2_mshr.slot_wait` | re-enters at **L2**, does not merge into its own L1 entry (3.5) |
| V12 | `lines_per_burst > l1_mshrs` | throws at config load, under `-DNDEBUG` (N7) |
| V13 | any run | every issued line request reaches exactly one terminal state; no request is lost or double-counted |
| V14 | any run | port busy-cycles ≤ elapsed cycles × port count |
| V15 | coordinate outside `workload_dims` | aborts, naming tile/tick/core/coord (N11) |
| V16 | *(new)* `l2_tgts_per_mshr >= n_cores` | no request ever enters an L2 `line_wait` (I12) |
| V17 | *(new)* the 3.8 counterexample replayed | `B.line_wait` is out of age order on insert, and service order is nonetheless `r1` before `r2` |
| V18 | *(new)* any run | every waiter's `refusal` stamp is written exactly once and is unique across the run (I2, 3.8) |
| V19 | *(new in v2)* `inclusion = exclusive` | rejected at config load with a message naming G1, not silently treated as `non_inclusive` |
| V29 | *(new in v3)* `l1_policy = random` or `l2_policy = random` | rejected at config load with a message saying Random is a placeholder, not silently falling back to LRU (A5, Q5) |
| V20 | *(new in v3)* one core, every access free except burst 3, which is delayed `L` cycles | `served(c, k)` for every `k > 3` and `tile_origin[N+1]` shift by exactly `L` against the same run without the delay. The stall is carried, not absorbed (N14, D13). Also asserts the corpus's `gap == 0` pair count, which must be 0 for the shift to be exact (4.5) |
| V21 | *(new in v3)* any run | per core, `served` is strictly increasing in `k`, service order equals trace order, `served(k+1) >= served(k) + core_accept_ii`, and `Σ core_stall[c]` equals the core's contribution to the tile stretch (I13) |
| V22 | *(new in v3)* `prefetch_policy = none` against the pre-C5 engine, then `next_burst(d)` for `d ∈ {1, 2, 4}` on the unbounded baseline | `none` gives a byte-identical event log, so C5 is genuinely inert when off. On the unbounded baseline `next_burst(d)` gives identical `served` times and `tile_origin` for every `d`, since with every access free there is nothing left to hide; its event log legitimately contains extra prefetch events (Part 5, 4.6) |
| V23 | *(new in v3)* the 4.6 worked example, all three columns | `served(b2)` is 221, 111, and 221. The middle column is a class-order test as well: the prefetch fill and the demand probe both land at 111, and only the class 0 before class 2 rule makes it a hit (3.6). A line resident since cycle 0 would still be served at 111, not earlier (4.5, N15) |
| V24 | *(new in v3)* `next_burst(d)`, heavy contention | `pf_outstanding <= l1_mshrs - l1_demand_reserve` and `pf_cursor - cursor <= d` at every event; no prefetch is ever issued for a burst of the next tile; the prefetcher stops on its budget and never on a refusal (N16, I14) |
| V25 | *(new in v3)* a demand request arrives while a prefetch for the same line is outstanding | it merges as a target and promotes the entry to `demand = true`; exactly one MSHR entry ever exists for that line (I1), and the fill completes the core's burst |
| V26 | *(new in v3)* a core's last burst of a tile fills in the same cycle the barrier would resolve | `tile_origin[N+1]` equals that service cycle, not one event earlier: service happens inside a class-0 fill and the barrier is class 1 (3.6) |
| V28 | *(new in v3)* any run at `prefetch_distance > 0` | no `demand = false` request ever appears on a wait index, ever calls `core_line_done`, or ever touches replacement state on an array hit; every refusal of one is counted as a drop by reason (4.6) |
| V27 | *(new in v3)* the `l1_latency = 1` sensitivity run, everything else free, every access a hit | `tile_origin[N] - tick_base[N]` equals the sum over tiles before `N` of that tile's maximum per-core burst count, computed from the trace alone. The exact-drift companion to V1's exact-match at `l1_latency = 0`, and the check that N14 accumulates rather than absorbs (2.5b) |

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

**Core schedule (new, 4.5).** `core_stall[c] = Σ_k served(c, k) − want(c, k)`, the cycles the
core waited past its own self-timed schedule, which is the quantity that integrates to the tile
stretch. `fetch_latency[c] = Σ_k served(c, k) − issued_at(c, k)`, the memory system's
latency for the same bursts. With prefetching off these two are equal by construction and reporting
both is a free consistency check; with prefetching on, their **difference is the latency the
policy hid**, and it is the single number the policy should be judged on. Also: the
distribution of `gap_k` in the corpus, since a workload whose bursts are far apart cannot be
memory-bound whatever the cache does, and the count of `gap_k == 0` pairs, which are the only
places the model's `core_accept_ii` floor invents spacing the trace did not have.

**Prefetch (new, 4.6).** Every prefetch issued ends in exactly one of four states and the four
must sum: **timely** (the core's demand access hit it), **late** (the demand access merged onto
it while still outstanding, so only part of the latency was saved), **wasted** (evicted or
invalidated before the core got there), and **dropped** (refused at issue, broken out by reason:
array hit, matching entry, no slot, targets full, reserve exhausted). Coverage is timely plus
late over all bursts, and its ceiling is the fraction of bursts that are not first-in-tile,
which is reported beside it. Also: the distribution of `fill - served`, how early the data
arrived, whose zero bin is the fetch that did not make it in time; **extra L1 evictions
attributable to prefetched lines**, and how many of those evicted lines were themselves demanded
soon after, which is the pollution term; `pf_budget_exhausted`, which says whether
`prefetch_distance` or `l1_mshrs` was the binding constraint; and L1 MSHR occupancy split demand
versus prefetch, a reported constant with prefetching off and a result with it on (4.2).

**Inclusion (new, 4.4).** Back-invalidations and the L1 misses they induced; effective capacity
(distinct lines resident anywhere) under each `inclusion` setting; DRAM accesses that a peer L1
could have served under `non_inclusive`, which is the cost of not modeling peer forwarding and
bounds the argument in favour of inclusion.

**Model health.** **L2 port utilisation and the port-bound threshold** (new, Q14):
`miss_fraction x l2_miss_latency x l2_banks / l2_ii`, emitted per run beside the observed
`l2_mshrs` knee. An `l2_mshrs` value at or above that threshold cannot increase miss
concurrency, because the port cannot deliver accesses fast enough to keep the extra entries
occupied, so any flattening there is labelled a port effect rather than an MSHR result.
`hits_downgraded_to_miss` (D4), event count and events per simulated cycle
(the cost win over the tick model, measured rather than claimed), and max wait-set depth against
the I11 bound (a violation means the credit argument broke, most likely because `core_model`
changed).

---

## Part 9. Open questions for review

1. **`l1_mshrs` sweep** *(narrowed in v3)*. 4.2 argues it is inert by construction under the
   current corpus **with prefetching off**, and that the prefetcher is precisely what makes it
   bind, since the prefetch budget *is* `l1_mshrs - l1_demand_reserve`. Confirm the split:
   report it as a constant on the demand-only grid, sweep it jointly with `prefetch_distance`
   otherwise.
2. **L2 banking granularity.** Bank by low bits of the set index (spreads consecutive lines) or
   high bits (keeps a core's working set in one bank)? Opposite conflict behavior, and the
   choice interacts with the `cin_block`/`cout_block` sweep.
3. **`l2_to_l1_latency`** is implied by D10 and absent from the old table. Separate knob or
   `l2_latency` reused?
4. **Prefetch** *(closed 2026-08-17)*. No longer deferred and no longer open: it is the
   `Prefetcher` of 4.6, unit C5, and it lives **at the L1**. The PE is not changed, the fetched
   line waits in the cache, the core reaches it through its ordinary demand access, and a line
   evicted before that is a real loss the model measures. The rejected alternative, delivery
   into a `1 + d` deep PE weight buffer, guarantees the win and costs
   `d x lines_per_burst x line_bytes` of new storage per core; it is recorded in N15 rather than
   deleted, since it is the natural thing to reach for if the wasted-fetch rate turns out to
   dominate.
5. **Random policy reproducibility** *(deferred 2026-08-17: Random is a placeholder and is not
   implemented, so this blocks nothing until someone wants it)*. When it is built, the answer
   settled in discussion is: `random_seed` becomes an explicit config field emitted in every
   results row, so reproducing a point needs no knowledge of how the sweep was scheduled; each
   cache instance gets its own RNG seeded from `(random_seed, level, core_id)`, so no
   structure's draw sequence can perturb another's; and Random points run at three seeds with
   mean and spread reported, since one seed is one sample of a stochastic policy. Until then,
   the only obligation on A5 is to keep `pick_victim` order-agnostic.
6. **Inclusion sweep cost** *(closed 2026-08-17)*. The grid runs **`non_inclusive`** and does
   not cross `inclusion` with the other axes, which keeps the grid at its current size. Both
   branches are still built and still tested (C4, V9, V9b), so the setting remains a
   one-flag experiment rather than a rebuild. What is **not** decided, and is cheap whenever
   wanted, is a handful of `inclusive` calibration points at the smallest one or two `l2_size`
   values, where `n_cores x L1` is a material fraction of total capacity and the two settings
   should separate. Without at least one such point the capacity argument for `non_inclusive`
   is asserted rather than measured.
7. **Exclusive (new).** Is G1 worth resolving, or is `{inclusive, non_inclusive}` the honest
   scope? Exclusive needs an L2 removal path on L1 fill plus a victim path back, which is more
   than a knob.
8. **Refusal counter width (new in v2, closed).** A run's total refusals bound it; over a full
   trace at 256 cores this can still exceed 32 bits, and a wrap would silently reorder the
   FIFO. Use 64.
9. **Arbiter feasibility at the target scale** *(closed 2026-08-17: keep oldest-first, no
   round-robin option for now)*. v2 sized the select at `n_cores x l1_mshrs`, about 4096
   candidates, and worried it needed an age matrix or a deep comparator tree. **The plan's own
   invariants make it smaller than that**: I6b allows at most one request per core per line at
   the L2, and C1 (4.5) allows a core one burst in flight, so each core presents at most
   `lines_per_burst` candidates, which is 1 in the current corpus. The select is over `n_cores`
   candidates. The requesters are also physically distributed one per core, so the natural build
   is a hierarchical select, clusters then cores, which is an ordinary NoC arbiter rather than a
   concession. At the sweep range of 8 to 256 cores (2.5b) the feasibility worry does not bite, and FIFO by first refusal keeps its proof of starvation
   freedom (I10) and its one-integer key. `arbiter` is therefore **not** a config option; if a
   reviewer asks, the sensitivity run is a change to one sort key in `collect_grants` and the
   retire merge, and the honest position until then is that it was not measured.
10. **Trailing compute tail** *(new in v3, closed 2026-08-17 with corpus data)*. The tail is
    charged, tile-level, as `tile_tail[N] = mac_cycles[N] - max_tick[N]`, read from the trace
    (4.5). No format change was needed: `mac_cycles` is already in `TileWeightTrace`. Measured,
    the tail is 0 across loas, prosperity, spinalflow and most of ptb, and 20 cycles, 11.7% of
    the tile, on all 64 tiles of ptb `layer_01` and `layer_03`, so charging nothing was not a
    safe default. Per-core tails remain unavailable, since `mac_cycles` is stored reduced to the
    max over the tile's cores; if per-core barrier arrival ever needs to be exact rather than
    "at its last weight service", that is the trace format change this question originally
    contemplated.
11. **`gap_k == 0`** *(new in v3, closed 2026-08-17 with corpus data)*. Measured over four
    architectures and twelve layers, about 3.7M bursts: **every core emits exactly one burst per
    tick**, with no tick carrying two, so `gap_k >= 1` everywhere and the `core_accept_ii` floor
    is never the binding term. It is measured-absent rather than assumed-absent. The format
    still permits it, since `CoreEntry.weight_addresses` is a list per (core, tick), so A3
    reports the `gap == 0` count and it must be zero. `core_accept_ii = 1` stays, its real job
    now being the termination guard of 2.5b: with `l1_latency = 0` an all-hit chain runs inside
    one timestamp and `max(gap_k, core_accept_ii)` is the only thing advancing the clock.
12. **Catch-up drain semantics** *(new in v3, closed the same day by the answer to Q4)*. It
    asked what happens when several fetched-ahead bursts become available during one long stall:
    does the core drain them one per cycle, or re-pay its compute gap between each? The question
    only exists if fetched data is delivered to the core, and under the L1-side decision it is
    not. The core asks for one burst at a time and pays `max(gap_k, 1)` between them under every
    policy, so there is no drain and no divergence between C1 and C2. It returns only if N15 is
    ever reversed.
14. **When does one L2 bank stop being enough?** *(new in v3, closed 2026-08-17: it stays at 1)*
    `l2_banks = 1` and `l2_ii = 1` remain the defaults; raising them is a profiling-time
    decision, not a plan-time one. The reasoning matters more than the value, because an earlier
    draft of this question had it wrong.

    **A port limits the rate of acceptance, not the latency of a request.** N misses arriving
    together are accepted at cycles 0, 1, ... N-1 and then overlap their round trips, so they
    complete in `N - 1 + l2_miss_latency` rather than `N x l2_miss_latency`. The MSHR file is
    what overlaps them; the port only adds the skew. By Little's law the two ceilings are:

    ```
    max sustained L2 accesses/cycle  =  l2_banks / l2_ii                    = 1
    max sustained L2 misses/cycle    =  l2_mshrs / l2_miss_latency          = mshrs / 110
    ```

    At `l2_mshrs = 32` the second is 0.29 misses per cycle, far below the port's 1 access per
    cycle, so **for most of the sweep range the MSHR file binds first and the port is not the
    limiter**. The `l2_mshrs` sweep measures what it claims to.

    The port takes over only when

    ```
    l2_mshrs  >  miss_fraction  x  l2_miss_latency  x  (l2_banks / l2_ii)

    at 30% L2 miss, 110-cycle miss, 1 bank:   l2_mshrs > 33      (4 banks: > 132)
    ```

    because the port carries hits as well as misses and cannot deliver accesses fast enough to
    keep more MSHRs occupied. Above that threshold the `l2_mshrs` curve flattens and **the
    flattening is the port, not memory**. That threshold is computable per run from quantities
    the model already reports, so D2 emits it beside the knee rather than leaving it to be
    remembered. A knee at or above the threshold is labelled a port effect.

13. **Prefetch distance sweep**13. **Prefetch distance sweep** *(new in v3, closed 2026-08-17)*. The grid is the full cross
    product `l1_mshrs ∈ {2, 4, 8, 16, 32}` by `prefetch_distance ∈ {1, 2, 4, 8, 16, 32}`, plus
    `d = 0` once per `l1_mshrs` value as the demand-only reference.

    The two are not independent axes: the prefetcher's budget is
    `l1_mshrs - l1_demand_reserve`, and any `d` above it is inert, so steady-state throughput
    goes as `min(d, budget) + 1` bursts per miss latency. With single-line bursts, 15 of the 30
    points are distinct and the other 15 must be exact duplicates of the last distinct point in
    their row. **Those duplicates are the check, not waste**: if one of them differs, the
    `min(d, budget)` model is wrong and the grid says so.

    Two corners to expect. `d = 1` already doubles throughput on a miss-dominated stream, since
    it puts two bursts in flight per miss latency rather than one, so the interesting range runs
    much further than the `{0,1,2,4}` this question originally proposed. And at a narrow
    `cout_block`, where a burst expands to several lines, `l1_demand_reserve = lines_per_burst`
    drives the budget at `l1_mshrs = 2` to zero, so that row carries no prefetch information at
    all at those layout points; D1 warns rather than leaving it to be discovered.

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
I9   Σ over cores of pending_lines == outstanding DEMAND requests. Prefetch
     requests are counted separately, by pf_outstanding                    (3.3, 4.6)
I10  no starvation: the stamp is write-once (I2), so the set of requests with a
     smaller stamp is finite and never grows; eligibility always arrives      (3.8)
I11  |e.line_wait| <= n_cores - l2_tgts_per_mshr at L2;
     <= lines_per_burst - l1_tgts_per_mshr at L1                              (4.1)
I12  if l2_tgts_per_mshr >= n_cores then every L2 line_wait is empty           (4.1)
I13  per core, served() is strictly increasing in k, service order is trace order,
     and within a tile served(c,k+1) >= served(c,k) + core_accept_ii under every
     policy, by construction rather than by enforcement. Across a tile seam the
     barrier orders it instead                                                (4.5)
I14  0 <= pf_cursor(c) - cursor(c) <= 1 + prefetch_distance, and
     pf_outstanding(c) <= l1_mshrs - l1_demand_reserve. The budget, not a refusal,
     is what stops the prefetcher                                          (4.6, N16)
I15  a request with demand == false is never on a wait index, never calls
     core_line_done, and never mutates replacement state on an array hit   (4.6)
I16  a core has exactly one burst in flight: pending_lines > 0 <=> phase == Stalled,
     and Sum over cores of pending_lines == outstanding DEMAND requests    (3.3, 4.5)
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
| *(v3)* both documents, wherever a core's next burst is scheduled from an absolute trace tick | replace with the self-timed recurrence of 4.5. The absolute tick survives only for the first burst of a tile |
| *(v3)* both documents, wherever every request is assumed to have a waiting core | a request now carries `demand`, and a prefetch completes nobody (4.6). Any step that reads "the fill completes the core's access" holds for demand fills only |
| *(v3)* both documents, the phrase "the core's current burst" | still well-formed: the core has exactly one burst in flight under every policy. What is no longer well-formed is "the outstanding requests of a core", which now spans one demand burst plus up to `pf_outstanding` prefetch lines (3.3) |
