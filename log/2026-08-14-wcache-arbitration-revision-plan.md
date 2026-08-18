# 2026-08-14 wcache: arbitration and inclusion revision plan

Supersedes parts of `2026-08-13-wcache-event-driven-plan.md` and corrects
`2026-08-13-wcache-pseudocode-explained.md` Q5 and Q11. The 08-13 control flow
(`2026-08-13-wcache-control-flow-pseudocode.md`) is amended, not replaced: sections 3, 8,
9, and 11 change, everything else stands.

Nothing here reverses a decision from 08-13. Every item either strengthens an argument
that was already correct but justified on weaker grounds, corrects a claim that was stated
too broadly, or renames something that collides with prior art.

---

## Part 0. What changed, in one table

| # | Topic | 08-13 position | Revised position |
|---|---|---|---|
| R1 | Wait-list bounds | bounded because `stall_in_order` caps the total at `cores x lines_per_burst`, and 4096 entries is "nothing" (4.1) | correct, but the real argument is stronger: **the lists have no storage at all**. They are views over structures that already exist. Per-list bound tightens to `n_cores` |
| R2 | Arbitration | ordered by the 5-tuple key (N10) | the key is doing the work of a **FIFO by first refusal**. Collapses to `(refused_bit, counter)`; `core_id` and `seq` are dead fields for the probe class |
| R3 | Wait structures | "three wait structures" (N6) | **one logical FIFO with a wait reason**, indexed two ways. Keep both indexes in code; change the description and the names |
| R4 | `ii` and back-pressure | `ii` is throughput (N3) | correct, and `ii` **does** produce back-pressure, of the rate kind. It produces none of the occupancy kind, and it makes wait lists longer, not shorter |
| R5 | Inclusion | inclusive L2 is required; back-invalidation is mandatory (N8, 141, 275, Q11) | inclusion is a **choice with no coherence justification in this study**, because there are no writers. Make it a measured knob |
| R6 | Naming | `deferred` | collides with gem5's `MSHR::deferredTargets`, which means something different and behaves differently. Rename |

---

## Part 1. The waiting population is not a data structure

### 1.1 The insight

`triage_L2` line 231: `e1 = r.mshr1  # still held. Always.` A request blocked at the L2
never released its L1 MSHR entry. So `e.deferred` and `l2_mshr.pool_wait` are not buffers
holding requests. They are **selection sets over L1 MSHR entries that already exist**.

In RTL this is a wait bit, a two-bit reason field, and an age stamp on each L1 MSHR entry,
plus an oldest-ready select. There is no queue to size, no allocation, no overflow
condition, and no depth limit to design.

This replaces the argument in 4.1. That section justified unbounded lists by showing the
total is small (4096 entries at 1024 cores). That is a *simulator memory* argument. The
correct argument is a *hardware* one: the lists cost zero storage because their contents
are already allocated elsewhere. 4.1's conclusion survives; its reasoning is upgraded.

### 1.2 The bounds, at both levels

The backing structure differs by level, so the two bounds cite different hardware.

**At the L2, the backing store is the L1 MSHR file.** Only the primary request of a core's
L1 entry reaches `triage_L2` (control flow 214-220); a core's L1 `entries` is a
`line -> Mshr` map, so there is at most one L1 entry per (core, line), and every later
same-line request from that core is absorbed at the L1. Therefore at most **one request
per core** arrives at the L2 for any given line:

```
|e.line_wait|  <=  n_cores - l2_tgts_per_mshr        (per entry)

sum over entries of (|targets| + |line_wait|) + |slot_wait|
               <=  n_cores x lines_per_burst          (global, = 4.1)
```

Corollary worth asserting: **if `l2_tgts_per_mshr >= n_cores`, the L2 wait sets are
provably always empty.** That is a real design lever and it should appear in the sweep
discussion.

**At the L1, the backing store is the core, not the L1 MSHR file.** A request in an L1 wait
set has not allocated an entry: `BLOCKED_TARGETS` means it is waiting to become someone
else's target, `BLOCKED_POOL` means there was no slot. Invariant I6 says this directly
(`r.level == L2 <=> r.mshr1 != null`). Its physical home is the core's outstanding-burst
registers, bounded by N7:

```
|e.line_wait|  <=  lines_per_burst - l1_tgts_per_mshr     (per entry)
                   and 0 if mapper.expand deduplicates
```

Both are free and both are already-existing hardware, but a design document must cite the
right structure for each.

### 1.3 New invariant

```
I6b at L2, the map (waiting request) -> r.mshr1 is injective: no two requests on any
    L2 wait set share an L1 entry. Each core holds at most one L1 entry per line, and
    only its primary reaches the L2.
    => |e.line_wait| <= n_cores - l2_tgts_per_mshr, with zero backing storage
```

I6b also makes the type asymmetry at the L2 harmless: `targets` holds L1 entries (control
flow 244) while the wait set holds Requests (247). By I6b those are in bijection, so they
are the same identifier wearing two hats. Note it so it does not read as an oversight.

### 1.4 Documentation fix

Control flow line 95 currently reads `deferred = []  # unbounded; blocked on THIS entry`.
That comment invites a future reader to "fix" it into a bounded ring buffer, which would
add a structure that does not exist. Replace with:

```
line_wait = []      # selection set over L1 MSHRs, not storage. See I6b.
```

---

## Part 2. Arbitration is FIFO by first refusal

### 2.1 What the key is actually doing

`mark_refused` is write-once (control flow 334-335, invariant I2) and `reinject` explicitly
does not touch the stamp (326). A request therefore enters the waiting population exactly
once, at first refusal, and is served in stamp order forever after, regardless of how many
times it is re-refused or which set it is parked in.

That is first-refused-first-served. The 5-tuple key in N10 is an implementation of FIFO,
not a policy in its own right.

### 2.2 Starvation freedom, which was never stated

```
I10 no starvation: enqueue_time is write-once (I2), so the set of requests with a
    strictly smaller stamp is finite and never grows. Every LINE waiter becomes
    eligible when its entry retires (DRAM always responds); every SLOT waiter becomes
    eligible as entries retire. Therefore every waiter is served in bounded time.
```

N6's cost column names "grant loop livelocks" as what the wait structures prevent, but
nothing in the plan states why the *ordering* is starvation-free. FIFO is the reason and
the proof is one line. This belongs in section 11 next to I7.

### 2.3 The key collapses

Because order depends only on refusal order, the stamp does not need to be a simulation
tick. Use a single global refusal counter, `enqueue_time = refusal_counter++` at first
refusal. Then:

- No two waiters can tie, so `core_id` and `seq` become **dead fields in the key for the
  probe class**. They were only breaking `enqueue_time` ties, and ties are now impossible.
- The key collapses to `(refused_bit, counter)`: refused always beats fresh (already the
  semantics, since a fresh request gets `now`, which is `>=` every stamp), FIFO within
  refused.
- Comparison is one small integer instead of a three-field tuple. In RTL that is a counter
  and a comparator rather than a tick-width datapath.

**One divergence to sign off deliberately.** Today a fresh request arriving at tick T with
a low `core_id` beats a request refused *at that same tick* with a higher `core_id`. Under
`(refused_bit, counter)` the refused request always wins. Reachable only on exact-tick
ties, but it is a behavior change and it will show up as a sweep diff. Decide it now, not
during debugging.

N10 stands as the *event queue* order. This changes only how `effective_age` is computed
and what the probe-class tiebreak needs.

### 2.4 Why the sort at drain cannot be removed

A wait set is **not** guaranteed to be in age order, so the merge-and-sort at control flow
300-302 is load-bearing. The reachable counterexample:

```
t=5   r1 wants Y. No entry for Y, pool full   -> slot_wait, stamp 5
t=6   some core allocates B(Y)                   (r1 is asleep, does not notice)
t=8   r2 wants Y. Matches B, targets full     -> B.line_wait, stamp 8
t=10  an entry retires, a slot frees. collect_grants pops r1 (oldest), reinjects.
      r1 re-triages, now finds B(Y) with full targets
                                              -> B.line_wait.push(r1), stamp still 5

      B.line_wait = [r2(8), r1(5)]            <- out of age order
```

A slot waiter can outlive the allocation of an entry it later merges onto and arrive
carrying an older stamp than what is already there. Building the wait set as a literal
FIFO gives the wrong order in exactly this case. Add this counterexample as a comment
next to the sort at 301, because the sort looks redundant until you have seen it.

---

## Part 3. One wait list with a reason tag

### 3.1 The separation is not semantic

Q5's own punchline (explained 158-162) is that no rule ranks "deferred" above "pooled";
one key orders everything. If the two structures never affect relative order, the split
carries no semantic weight, and control flow 300-302 merges and re-sorts them at every
retire anyway. The code pays a tax for a separation it immediately undoes.

What the split actually bundles is two different things:

**A wait reason**, which is real and must survive: a LINE waiter wakes when its line
becomes resident; a SLOT waiter wakes when any slot frees. This is a one-field tag.

**An eligibility index**, which is also real and worth keeping: `e.line_wait` is an O(1)
answer to "who is waiting on line X". A single flat list makes every retire O(W) over the
whole waiting population, which at the stated 1024-core target is roughly 4096 entries
scanned per retire on a hot path. Explained 450-451 already flags the O(cores)
back-invalidation scan as the hottest path in the simulator; this would add a second,
larger one.

### 3.2 Decision

**Keep both indexes in code. Change the description and the names.**

- The wait population is **one logical FIFO**, ordered by first refusal (Part 2), with a
  wait reason in `{SLOT, LINE(L)}`.
- `F.slot_wait` and `e.line_wait` are two indexes into that one population, chosen for O(1)
  eligibility lookup. They are not three structures and they are not queues.
- Statistics stay separable by reason. Blocked-on-targets and blocked-on-slots point at
  different knobs (`l2_tgts_per_mshr` versus `l2_mshrs`, the latter being what line 273
  calls the headline knob), so the results must distinguish them. The tag preserves this
  exactly.

Do **not** flatten to a single list. That trades a contained three-line merge-and-sort,
already guarded by I7b, for an O(W) scan on the hottest path. Wrong trade at this scale.

N6 is amended, not reversed: its decision was "three structures **and nothing else**", a
cap against adding a fourth. Describing the same code as one FIFO with two indexes does
not contradict it and does not risk the livelock N6 guards against.

---

## Part 4. Ports, `ii`, and two kinds of back-pressure

### 4.1 `ii` is the initiation interval

Full name, for the write-up: **initiation interval**, from software pipelining and modulo
scheduling. The number of cycles between successive initiations of a pipelined unit, the
reciprocal of throughput, independent of latency. The L2 bank's `ii` is the bank cycle time
(the SRAM's minimum access-to-access gap; JEDEC `tCCD` is the DRAM analogue), and
`dram.ii = line_bytes / dram_bytes_per_cycle` is the data bus burst occupancy.

**A physical II is `>= 1`.** `ii = 0` is a modeling escape hatch meaning infinite
throughput, not a setting a real port can have. Label it as such in the config docs, or a
sweep over `ii` in `{0, 1, 2}` will be read as three adjacent points when 0 and 1 differ by
unbounded parallelism.

### 4.2 `ii` produces rate back-pressure, not occupancy back-pressure

Both halves matter and the plan currently says neither.

**It does produce back-pressure.** With `ii = 1`, a k-long wait set drains through k
successive `reserve()` calls on the same `l2_bank[bank_of(X)]` (control flow 321-325). All
k are for the same line, so they are all the same bank: k cycles, strictly sequential. And
`next_accept` is shared bank state (102-103), so that drain pushes `next_accept` forward by
`k x ii` and delays **every unrelated request to that bank** in the window. It reaches the
cores too: atomic bursts (N7) hold `phase = Waiting` until `pending_lines == 0`, so bank
delay produces a later `core_line_done` (350-352) and a later next `E_Issue`. The loop is
closed. That is back-pressure in the dataflow sense.

**It produces no occupancy bound.** `Port.reserve` always returns; it never refuses. So
nothing about `ii` constrains how many requests sit in a wait set. That ceiling is Part 1's,
set entirely by the credit supply.

**And the direction is the opposite of intuition.** Raising `ii` makes each request hold its
L1 MSHR credit longer, so more credits are in flight at once, so the window for other cores
to collide on a line widens. **Wait sets get longer with higher `ii`, not shorter.** Any
sizing argument must rest on the credit bound, never on the port.

### 4.3 Test consequence

At `ii = 0` the merge-and-sort at 300-302 is a no-op: everything probes at the same
timestamp and the event-queue key does all the ordering. It has teeth only at `ii >= 1`,
because that is when `reserve` order becomes service order and is never revisited
(reservations are non-preemptive and never released).

**V7 and any test of I7b must run at `ii >= 1`, or they pass vacuously.** Add this as an
explicit condition on the fixture, not a comment.

### 4.4 Recorded fidelity gap

The serialization is *timed* correctly (`k x ii`) but costs nothing *structurally*: the k
requests waiting on the bank live as scheduled future events, which is an infinitely deep,
free input queue. Real hardware has a finite bank input queue that stalls or NACKs when it
fills. So the model gets bank throughput right and bank buffering wrong.

This is the correct trade for this study; it just means the model cannot answer how deep to
build that queue. Add it to the not-modeled list at 308-313 so it is visibly a decision.

---

## Part 5. Inclusion is a knob, not an invariant

### 5.1 The overstated claim

Three places state back-invalidation as a hard requirement rather than a consequence of a
choice:

- explained 441-443: "the hit rate is inflated by exactly the accesses that should have
  been misses"
- plan 141: "the L2 is shared, so an L2 eviction must invalidate the copies in other
  cores' L1s"
- plan 275: "An L2 eviction must invalidate the copy in every L1 that holds it"

Line 141's justification is a non-sequitur. Sharedness is why the loop must scan *all
cores*; it is not why you must invalidate at all. Under non-inclusive (NINE) or exclusive,
you do not: the L1 legitimately keeps serving lines the L2 dropped, and effective capacity
becomes `L2 + n_cores x L1` instead of roughly `L2`.

The **code** is already correct: `install()` guards the loop with `inclusion == inclusive`
(control flow 401). Only the prose overreaches. N8 (643) does record inclusion as a
decision and names the alternative in its cost column, so the plan knows; the problem is
that the cost column frames the alternative as a downside and Q11 then argues it is a
correctness bug.

### 5.2 The larger problem: inclusion has no job here

Plan 308-309 puts in the not-modeled list:

> Writes, dirty bits, writebacks (weights are read-only in this study) - inter-L1 coherence
> (**no writers, so inclusion alone suffices**)

That parenthetical is backwards. Inclusion's canonical justification *is* coherence: an
inclusive LLC is a snoop filter, so invalidations need not broadcast to every L1. **With no
writers there are no invalidations to filter.** Inclusion is not "sufficing" for anything
here; it has no job.

What it costs, by the note's own accounting:

- effective capacity collapses to roughly the L2 size;
- back-invalidation-induced L1 misses, which explained 446-448 already measures;
- an O(cores) scan per L2 eviction, which explained 450-451 calls the hottest path in the
  simulator at 1024 cores.

For a read-only, streaming, capacity-bound weight cache, that is a lot of cost for no
coherence benefit.

**The one argument that survives for inclusion:** under NINE, a core missing on a line that
a peer L1 holds but the L2 evicted goes all the way to DRAM, whereas inclusion guarantees
an L2 hit. Peer-L1 forwarding is not modeled. How much this matters depends on inter-core
working-set overlap, which the tile-barrier structure probably makes high.

That dependence is exactly the argument for making inclusion a **measured knob rather than
a fixed decision**. It is a result, not an assumption.

### 5.3 Three concrete gaps

| # | Gap | Action |
|---|---|---|
| G1 | `inclusion = inclusive` is written as a config value (275) implying an enum, but **exclusive is not implementable as written**: it requires `E_L1Fill` to remove the line from the L2, and no such path exists (`install(l1[core], ...)` never touches the L2) | either add the removal path or restrict the enum to `{inclusive, non_inclusive}`, so nobody configures a mode that silently behaves as NINE |
| G2 | V9 tests only the inclusive branch | add V9b: L2 evicts a line another core's L1 holds under `non_inclusive` -> that L1 still hits, `back_invalidations == 0` |
| G3 | Q11's worked example is the classic **inclusion LRU pathology** presented as normal operation. `l2_policy.on_hit` fires only on an L2 probe hit (triage 235); L1 hits never reach the L2, so L2 recency is blind to lines hot in L1. That is exactly why LRU picks line 0 at t=22 while C3 is actively using it | document it as a known, measurable effect and report it. Real inclusive designs mitigate with temporal hints; this model does not, which is realistic but must be visible |

### 5.4 Prose fix for Q11

Keep the mechanism explanation. Replace "should have been misses" with:

> Inclusion is violated. Under `inclusion = inclusive` that L1 hit is a bug; under
> `non_inclusive` it is the intended behavior and the source of the extra effective
> capacity.

Then the loop reads as enforcing a policy, which is what it does.

---

## Part 6. Naming

`deferred` collides with gem5's `MSHR::deferredTargets`, verified against the local
checkout at `/u/yyu9/gem5` (commit `cbf0eae2`, 2026-07-28). The collision is not cosmetic,
because gem5's field means something different and behaves differently:

| | this model | gem5 |
|---|---|---|
| what defers | target list at capacity | **coherence ordering only** (`mshr.cc:373-414`): cache-maintenance ops, pending post-invalidate, target needs writable when the fill will not deliver it. Capacity never routes here |
| what capacity does | wait set, re-probe on wake | **blocks the whole cache port** (`base.cc:400-404`, `setBlocked(Blocked_NoTargets)`); the requestor retries at `curTick()+1` (`base.cc:167-176`) |
| what happens on fill | re-probe, hits because the line is resident | `promoteDeferredTargets()` splices them into `targets`, clears the readable bit, and **reissues to memory** (`base.cc:640-648`) |

Anyone with gem5 background reads `A.deferred` and concludes the model reissues to memory.

**Rename to `line_wait`, and rename `pool_wait` to `slot_wait`.** This kills the collision,
makes the wait reason self-documenting, and makes the symmetry between the two indexes
visible at every use site. Committed targets keep the name `targets`, which matches both
gem5 and hardware.

For the record, the model's `targets` semantics are correct against both: gem5's
`serviceMSHRTargets` (`cache.cc:700-731`) copies straight out of the response packet with
critical-word-first timing and no re-lookup, and real MSHRs forward from the fill buffer to
each subentry the same way.

---

## Part 7. Amended state block

Replacing control flow section 3:

```
Request:
    core, line, seq
    enqueue_time = NONE      # refusal COUNTER, not a tick. Set once. Part 2.3
    reason       = NONE      # SLOT | LINE(L), set at refusal. Part 3
    level        = L1
    mshr1        = null
    reserved     = false

Mshr:
    line, core                   # core unused at L2
    targets   = []               # bounded by tgts_per_mshr
                                 # L1: Requests;  L2: Mshr entries. Bijective, see I6b
    line_wait = []               # index into the wait population, reason == LINE(line)
                                 # NOT storage: L2 waiters live in L1 MSHRs,
                                 # L1 waiters live in core burst registers. Part 1

MshrFile:
    entries   = {}
    slot_wait = []               # index into the wait population, reason == SLOT
    reserved  = 0

Port:
    ii, latency, next_accept     # ii = initiation interval, physically >= 1. Part 4.1

CoreState:
    cursor, tile, phase, pending_lines

refusal_counter                  # global monotonic; stamps enqueue_time. Part 2.3
tile_origin[]
```

`slot_wait` and `line_wait` are two indexes into **one** logically FIFO-ordered population.
The merge at section 8 is an index join, not a priority reconciliation.

---

## Part 8. Amended decisions

| # | Change |
|---|---|
| N6 | Reworded: **one wait population, FIFO by first refusal, indexed by reason** (`slot_wait`, `line_wait`), and nothing else. Same code, same livelock guard, honest hardware description |
| N8 | Reworded: **inclusion is a swept parameter**, default `inclusive`, alternative `non_inclusive`. No coherence justification exists in this study (no writers); the tradeoff is effective capacity against guaranteed L2 hits on peer-L1-resident lines, and it is a result to report, not an assumption. `exclusive` is not offered until G1 is resolved |
| N9 | Reworded: wait sets are unbounded **because they have no storage** (Part 1), not merely because the total is small. `core_model` coupling stands exactly as written in 4.1 |
| N10 | Amended: total event order stands. `effective_age` becomes a refusal counter, and the probe-class tiebreak collapses to `(refused_bit, counter)`; `core_id` and `seq` remain only for the event queue's other classes. Sign off the exact-tick divergence in Part 2.3 |
| N13 | **New.** `ii = 0` is a modeling escape hatch, not a physical setting. Any fixture asserting reservation order runs at `ii >= 1` |

---

## Part 9. Amended invariants

Additions to control flow section 11:

```
I6b  at L2 the map (waiting request) -> r.mshr1 is injective (Part 1.3)
I10  no starvation: FIFO by write-once stamp, eligibility always arrives (Part 2.2)
I11  |e.line_wait| <= n_cores - l2_tgts_per_mshr at L2;
     <= lines_per_burst - l1_tgts_per_mshr at L1
I12  if l2_tgts_per_mshr >= n_cores then every L2 line_wait is empty
```

`I7b` stays, since Part 3 keeps the two indexes. Note against it that it exists only
because of the index split, and that flattening would remove it at an O(W) cost that is not
worth paying.

---

## Part 10. Amended verification list

| # | Fixture | Asserts |
|---|---|---|
| V7 | **now at `ii >= 1`** | all LINE waiters resolve at once, none allocates, **and reservation order equals key order** (Part 4.3). At `ii = 0` this passes vacuously |
| V9b | **new.** L2 evicts a line another core's L1 holds, `inclusion = non_inclusive` | that L1 still hits; `back_invalidations == 0` (G2) |
| V10 | unchanged bound, **new second clause** | additionally `|e.line_wait| <= n_cores - l2_tgts_per_mshr` for every entry (I11) |
| V16 | **new.** `l2_tgts_per_mshr >= n_cores` | no request ever enters an L2 `line_wait` (I12) |
| V17 | **new.** the Part 2.4 counterexample, replayed | `B.line_wait` is out of age order on insert, and service order is nonetheless `r1(5)` before `r2(8)` |
| V18 | **new.** any run | every waiter's `enqueue_time` is written exactly once and is unique across the run (I2 + Part 2.3) |
| V3 | unchanged, **but re-baseline** | the key change in Part 2.3 alters exact-tick tie order; regenerate the golden event log once, deliberately, and record why |

---

## Part 11. What did not change

Stated so review does not have to re-derive it: N1 through N5, N7, N11, N12 stand as
written. Sections 4.1 (the coupling between `core_model` and unbounded wait lists), 4.2
(L1 MSHR occupancy includes L2 queueing delay, and `l1_mshrs` is inert by construction
under the current corpus), Part 5 (time and `tile_origin`), and Part 8 (what the run
reports) are unaffected. The rebuild schedule in Part 7 is unaffected except that unit C4
now implements a two-valued inclusion knob and unit D1's config validation gains the `ii`
and inclusion checks.

Q5's core answer is correct and stands: there is no separate sorting step, one key orders
everything, and a slot waiter can legitimately interleave between two line waiters purely
by age. This plan changes why that is true, not whether it is.

---

## Part 12. Open questions

Carrying forward the five in the 08-13 plan's Part 9, plus:

6. **Inclusion sweep cost.** N8 now makes inclusion a swept parameter. Does it sweep
   independently, or only at the extremes of the `l2_size` sweep? A full cross product
   doubles the sweep, and the interesting region is probably where the L2 is small enough
   that `n_cores x L1` is a material fraction of total capacity.
7. **Exclusive.** Is G1 worth resolving, or is `{inclusive, non_inclusive}` the honest
   scope? Exclusive needs an L2 removal path on L1 fill plus a victim path back, which is
   more than a knob.
8. **Refusal counter width.** A run's total refusals bound it. At 1024 cores over a full
   trace this could exceed 32 bits. Use 64, or use the existing `SimTime` strong typedef
   (N12) with a distinct `RefusalOrder` typedef to keep the two uncomparable?
9. **Arbiter feasibility at the target scale.** Part 2 makes the policy FIFO, but the
   structure is still oldest-ready select over `n_cores x l1_mshrs` entries, which needs an
   age matrix or a comparator tree. Comfortable at 8 cores, uncomfortable at 1024. If
   round-robin is what would actually be built, add it as a config option and show the
   sensitivity is small. That is a much stronger claim than assuming it away.
