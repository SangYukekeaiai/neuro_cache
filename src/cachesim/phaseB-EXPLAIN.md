> Recovered from commit ebc4029 (tests: cover Phase B, and record decisions B105-B126). This document explains increment Phase B.
> Provenance header added during the 2026-08-18 documentation recovery; the body below is byte-for-byte as committed.
# EXPLAIN: all of Phase B (plan units B1 `Port`, B2 `EventQueue`, B3 `MshrFile`)

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

This file covers **all three units of Phase B**, landed as one batch under B74.
Each gets its own part below and each part is readable on its own:

- **Part I, plan unit B1**, `Port`: occupancy as a next-free timestamp.
- **Part II, plan unit B2**, `EventQueue`: the five-part key and the min-heap.
- **Part III, plan unit B3**, `MshrFile`: entries, targets, the two wait indices,
  the refusal stamp, and the grant loop.

---

## A naming collision, stated once so nothing below is ambiguous

**The plan's Phase B units are named B1, B2, B3. `PROGRESS.md`'s board decisions
are also numbered B1 through B104. They are different things and they collide on
the first three numbers.**

- **plan unit B1** is `Port`. **Decision B1** is the ruling that `native_v1_archive/`
  keeps the old tree and that three build files are copied forward.
- **plan unit B2** is `EventQueue`. **Decision B2** is the ruling that `Tagged` has
  no default constructor.
- **plan unit B3** is `MshrFile`. **Decision B3** is the ruling that `RefusalOrder`'s
  `NONE` sentinel is `INT64_MAX`.

They are not even about the same subjects, so a reader who lands on the wrong one
gets a sentence that makes no sense rather than a plausible wrong answer. That is
luck, not design, and `PROGRESS.md`'s board already prints "B1 | `Port`" in one
table and "B1 | `native_v1_archive/` ..." in another.

Everywhere below, a plan unit is written **"plan unit B3"** and a board decision
is written **"decision B99"**. Neither is ever written bare. The production
headers follow the same rule where they cite both, and a later reader who finds a
bare "B3" in this tree should read the surrounding sentence before assuming which
one is meant.

---

Changed files, plan unit B1: `native/include/wcache/port.h` (new),
`native/src/port.cpp` (new).
Changed files, plan unit B2: `native/include/wcache/event.h` (new),
`native/include/wcache/types.h` (the tenth tagged scalar, `EventSeq`).
Changed files, plan unit B3: `native/include/wcache/mshr.h` (new),
`native/src/mshr.cpp` (new), `native/include/wcache/types.h` (the ninth tagged
scalar, `BurstIndex`).
Reviewer's files across the batch: `native/tests/test_port.cpp`,
`native/tests/test_event.cpp`, `native/tests/test_mshr.cpp` (all new),
`native/tests/compile_fail.sh`, `native/tests/mutation_check.sh`.

Plan reference: v3 Part 7's three Phase B rows (lines 1344-1346), Part 2.5b (the
default configuration), Part 3.3 (state), Part 3.4 (triage, retire, wake), Part
3.6 (total event order), Part 3.7 (the five outcomes and one wait population),
Part 3.8 (FIFO by first refusal), Part 4.1 (the wait sets have no storage), Part
4.3 (`ii` and two kinds of back-pressure), Part 4.6 (prefetch), and Appendix A's
I1 through I16.

**No build block in this file.** `PROGRESS.md` is owned by another role this
round and the verified counts belong in its Tested column. What is stated below
about *behaviour* is read from the sources and from the plan.

---

# Part I. Plan unit B1: `Port`

## 1. What landed

A class with two config numbers, one piece of state, and one three-line verb.

```cpp
class Port {
public:
    Port(SimTime ii, SimTime latency);   // throws invalid_argument on a negative either
    SimTime reserve(SimTime now);        // the cycle this port can accept
    SimTime ii() const;
    SimTime latency() const;
    SimTime next_accept() const;
private:
    SimTime ii_;
    SimTime latency_;
    SimTime next_accept_{0};
};
```

```cpp
SimTime Port::reserve(SimTime now) {
    const SimTime accept = (now < next_accept_) ? next_accept_ : now;
    next_accept_ = accept + ii_;
    return accept;
}
```

That is the whole unit. One class covers `l1_port[c]`, `l2_bank[b]` and `dram`
(plan 3.3); they differ only in the two numbers they are constructed with.

`ii` and `latency` are `SimTime` rather than raw integers, and that costs
nothing here because `SimTime` is the one tagged scalar carrying arithmetic
(`types.h:231-233`, added at A1a). So `accept + ii_` compiles and `accept +
some_core_id` does not, which is the point of the typing.

## 2. The occupancy arithmetic, walked with real numbers

Take `Port p(SimTime{3}, SimTime{10})`: an initiation interval of 3 cycles and a
latency of 10. `next_accept_` starts at 0, because the run starts at
`tile_origin[0] == 0` (plan Part 5) and a port that has never been used is free
at 0.

Now offer it six requests, at cycles **0, 0, 0, 10, 10, 100**:

| # | `now` | `now < next_accept_`? | `accept` | `next_accept_` after | returned |
|---|---|---|---|---|---|
| 1 | 0 | `0 < 0` no | 0 | 3 | **0** |
| 2 | 0 | `0 < 3` yes | 3 | 6 | **3** |
| 3 | 0 | `0 < 6` yes | 6 | 9 | **6** |
| 4 | 10 | `10 < 9` no | 10 | 13 | **10** |
| 5 | 10 | `10 < 13` yes | 13 | 16 | **13** |
| 6 | 100 | `100 < 16` no | 100 | 103 | **100** |

Accepts: **0, 3, 6, 10, 13, 100.**

Three things to read out of that table, because each is a property the plan
names rather than an artefact of the arithmetic.

**Three simultaneous offers become three cycles, not one stamp and not a
window.** Rows 1-3 all arrive at cycle 0 and are spread to 0, 3, 6. That is P3
made literal: "contention is occupancy, not quota". A quota port would have
admitted some number per window and then cliffed at the window edge; there is no
window here, so there is no window artefact.

**A port that has gone idle forgets nothing and charges nothing.** Row 4 arrives
at 10 with `next_accept_` at 9. The port has been free for one cycle and the
request is accepted at its own `now`, not at 9. Row 6 is the same effect after a
long gap: 84 idle cycles are simply not banked. The state is a next-free
timestamp, so idleness cannot accumulate into credit.

**The port never refuses and never schedules a wake-up.** Every row above
returns. That is why plan 3.1 has no `E_PortFree` event and why nothing ever
registers on a port: "subscribe, never predict" (P2) stays a statement about
MSHRs alone. It is also why `reserve` is safe to call from inside `reinject`
without any risk of the two-phase dance a refusing port would need.

## 3. `ii = 0` never delays; `ii = latency` serializes; and the in-flight count

These are the three exit criteria of the plan's B1 row, and all three fall out of
the same three lines.

**`ii = 0`.** `Port p(SimTime{0}, SimTime{100});`

| `now` | `accept` | `next_accept_` after |
|---|---|---|
| 0 | 0 | 0 |
| 0 | 0 | 0 |
| 0 | 0 | 0 |
| 5 | 5 | 5 |

`next_accept_` is assigned the accept time *unchanged*, so it can never get ahead
of `now` and every offer is accepted at its own cycle forever. That is the
unbounded baseline (V1), and it is reached **by configuration rather than by a
branch**: there is no `if (ii == 0)` anywhere. Keeping the baseline and the
bounded runs on one code path is D8's lesson, and it is what makes V1 a
calibration rather than a separate model that has to be kept in step.

**`ii = latency`.** `Port p(SimTime{100}, SimTime{100});`

| offer | `accept` | completes at `accept + latency` | `next_accept_` after |
|---|---|---|---|
| 0 | 0 | 100 | 100 |
| 0 | 100 | 200 | 200 |
| 0 | 200 | 300 | 300 |

One round trip at a time: the next request is accepted at exactly the cycle the
previous one completes. That is plan 2.4's non-pipelined channel, recovered from
the same structure with no second class and no flag.

**The in-flight count is `latency / ii`,** and the two settings above are its
extremes. Take the plan's own example, a channel with 100 cycles of latency and
an `ii` of 2, offered a saturating stream from cycle 0:

```
request k   accepted at 2k      completes at 2k + 100
```

At cycle 100 request 0 completes, and by then requests 0 through 49 have been
accepted (`2k < 100`) while request **50** is accepted at exactly 100. So **50
requests are in flight**, which is `100 / 2`. At `ii = latency = 100` the same
formula gives 1, which is the table above. At `ii = 0` it is unbounded, which is
the escape hatch.

That is why the two numbers are separate fields rather than one. A channel with
50 requests in flight and a channel that serializes 100-cycle round trips are
completely different machines, and a single "cost" number cannot tell them apart.

**`ii = 0` is accepted, deliberately** (N13). It is not a setting a real port can
have, so the plan asks for a warning on it; see section 16 for why that warning
is not in this constructor.

## 4. Why `reserve` returns the ACCEPT time and not the completion time

`reserve` hands back the cycle the port **takes** the request. The caller adds
the latency itself, exactly as plan 3.4 spells it:

```
accept = l2_bank[bank_of(r.line)].reserve(now);
schedule(E_L2Probe(r), accept + l2_latency);
```

The two halves cross different boundaries. The accept time is a fact about *this
port's occupancy*; the latency is how long the structure *behind* the port takes
to answer, which P4 makes a separate event rather than a return value. Folding
the latency into `reserve` would also make `ii = latency` unexpressible, since
one returned number would then be playing both roles.

**The plausible caller error is treating the returned value as the completion
time**, writing `schedule(E_L2Probe(r), accept)` and dropping the level's whole
latency. It is worth naming because of *when* it would be caught, which is: not
at the default configuration.

At plan 2.5b's defaults, **`l1_latency = 0`** and **`l2_to_l1_latency = 0`**. So
on the L1 probe path,

```
accept + l1_latency  ==  accept + 0  ==  accept
```

and the two spellings are **the same number**. A caller that confused them would
be right on every default run, right on the whole unbounded baseline, right on
the entire demand-only sweep grid, and wrong the moment someone sets
`l1_latency = 1` for the sensitivity run 2.5b describes and V27 has an exact
oracle for. The wrongness would then appear as the sensitivity run failing to
reproduce its own oracle, which reads as a problem with the oracle.

Two things in the header are there because of that. `latency()` is an accessor
**on the port** rather than a number kept beside each call site, so the caller
adds the same latency the port was built from and two spellings of one config
field cannot drift apart. And `next_accept()` is exposed (decision B20's reason,
plus V14) so the occupancy arithmetic is observable *directly* rather than only
through a sequence of `reserve` calls: without it, an implementation that
advanced `next_accept_` by the wrong amount and then compensated on the next call
would look identical from outside.

**Reservations are non-preemptive and are never released** (plan 4.3). A request
given an accept time keeps it, so `reserve` order **is** service order and is
never revisited. That is what makes I7b ("port reservation order == key order at
every retire") a property the merge-and-sort of 3.4 can be held to. It is also
why I7b is only testable at `ii >= 1`: at `ii = 0` every reservation returns
`now` and the ordering has nothing to express, so a test written at the default
`ii = 0` passes vacuously. That is the same trap as the plan's Q2 note about
`l2_banks` defaulting to 1.

---

# Part II. Plan unit B2: `EventQueue`

## 5. The five-part key, field by field

Plan 3.6: `key = (time, class, effective_age, core_id, seq)`.

```cpp
struct EventKey {
    SimTime      time;
    EventClass   cls;
    RefusalOrder age;
    CoreId       core;
    EventSeq     seq;
};

constexpr bool key_less(const EventKey& a, const EventKey& b) {
    if (!(a.time == b.time)) return a.time < b.time;
    if (a.cls != b.cls)      return a.cls < b.cls;
    if (!(a.age == b.age))   return a.age < b.age;
    if (!(a.core == b.core)) return a.core < b.core;
    return a.seq < b.seq;
}
```

**`time`** is P1's whole content: the engine has no tick and no cycle counter of
its own. `now` is the timestamp of the event being dispatched, and it is
non-decreasing because this is a min-heap.

**`cls`** is 3.6's four-row table, as an enum whose *enumerator order is the key
order*, so `<` on the enum is the comparison the key needs:

| value | class | events | why here |
|---|---|---|---|
| 0 | `Fill` | `E_L2Fill`, `E_L1Fill` | state changes land before anything looks at state; a core is served inside its last demand fill (3.4b), so services inherit class 0 |
| 1 | `Barrier` | `E_Barrier` | observes completed fills, and therefore completed services (V26) |
| 2 | `Probe` | `E_L1Probe`, `E_L2Probe` | lookups see this cycle's fills, which closes D4's "a queued miss became a hit" |
| 3 | `Issue` | `E_Issue` | new demand enters last |

At the 2.5b defaults these classes are the ordinary case rather than a corner:
with `l1_latency = 0`, an L1 hit issues, probes and serves the core all at one
timestamp, and `E_L2Probe` schedules `E_L1Fill` at its own timestamp. 4.6's
worked example is the live test: a prefetch fill and a demand probe both land at
cycle 111, and only `Fill` (0) before `Probe` (2) makes that a **hit** rather
than a second fetch and a 221 (V23).

**`age`** is the subject's refusal stamp, or `NoRefusal` when it has never been
refused. **One field carries the whole of 3.8's two-part `(refused_bit,
refusal)`**, because `NoRefusal` is `INT64_MAX` (decision B3): a fresh request
sorts after every refused one under plain `<`. The refused bit is not stored as a
second field that could disagree with the counter beside it.

**`core`** and **`seq`** are dead for class 2, and 3.8 says so: no two waiters can
tie on a monotonic counter, so once the age differs nothing after it is read.
They are kept because the other three classes have **no refusal stamp at all**,
where every event carries `NoRefusal` and something must still make the order
total.

## 6. One tie, broken at each level in turn

Nine events, scheduled in the order below. `seq` is not passed by the caller: it
is this queue's own counter, so the seq column *is* the schedule order.

| seq | `schedule(...)` | time | kind | class | age | core |
|---|---|---|---|---|---|---|
| 0 | `schedule(100, L2Probe, RefusalOrder{9}, CoreId{1}, ...)` | 100 | L2Probe | 2 | 9 | 1 |
| 1 | `schedule(100, L1Probe, RefusalOrder{9}, CoreId{4}, ...)` | 100 | L1Probe | 2 | 9 | 4 |
| 2 | `schedule(100, L1Fill, NoRefusal, CoreId{7}, ...)` | 100 | L1Fill | **0** | MAX | 7 |
| 3 | `schedule(90, L1Probe, NoRefusal, CoreId{5}, ...)` | **90** | L1Probe | 2 | MAX | 5 |
| 4 | `schedule(100, Barrier, NoRefusal, CoreId{0}, ...)` | 100 | Barrier | **1** | MAX | 0 |
| 5 | `schedule(100, L1Probe, RefusalOrder{2}, CoreId{6}, ...)` | 100 | L1Probe | 2 | **2** | 6 |
| 6 | `schedule(100, L2Probe, RefusalOrder{9}, CoreId{4}, ...)` | 100 | L2Probe | 2 | 9 | 4 |
| 7 | `schedule(100, L1Probe, NoRefusal, CoreId{0}, ...)` | 100 | L1Probe | 2 | MAX | 0 |
| 8 | `schedule(100, Issue, NoRefusal, CoreId{2}, ...)` | 100 | Issue | **3** | MAX | 2 |

Popping them all gives:

```
pop 1 -> seq 3    (90, 2, MAX, 5, 3)
pop 2 -> seq 2    (100, 0, MAX, 7, 2)
pop 3 -> seq 4    (100, 1, MAX, 0, 4)
pop 4 -> seq 5    (100, 2,   2, 6, 5)
pop 5 -> seq 0    (100, 2,   9, 1, 0)
pop 6 -> seq 1    (100, 2,   9, 4, 1)
pop 7 -> seq 6    (100, 2,   9, 4, 6)
pop 8 -> seq 7    (100, 2, MAX, 0, 7)
pop 9 -> seq 8    (100, 3, MAX, 2, 8)
```

Read the boundaries, because each one is a different field doing the work:

- **pop 1 vs pop 2: `time`.** seq 3 is at 90 and everything else at 100. Nothing
  else is consulted. Note that seq 3 is class 2 and seq 2 is class 0, so the
  *later* class wins here: time is above class and there is no exception.
- **pop 2 vs pop 3 vs pop 4 vs pop 9: `class`.** All at time 100, and the four
  classes come out 0, 1, 2, 3 in order. The Fill lands before the Barrier
  observes it; every Probe sees that Fill; the new Issue enters last.
- **pop 4 vs pop 5: `age`.** Both class 2 at time 100. seq 5 carries refusal
  stamp **2** and seq 0 carries **9**: the request refused earlier goes first.
  That is FIFO by first refusal (3.8) reaching all the way into the event order,
  not just into the wait-index sort.
- **pop 5 vs pop 6: `core`.** Both class 2, both stamp **9**. Cores 1 and 4, so
  core 1 first.
- **pop 6 vs pop 7: `seq`.** Both class 2, both stamp **9**, both **core 4**, so
  every earlier field is exhausted and only the schedule counter is left: seq 1
  before seq 6. **This is the field that makes the order total.** Remove it and
  these two events compare equal, the heap picks by its internal arrangement, and
  the run stops being reproducible in a way nothing in the output announces.
- **pop 7 vs pop 8: `age` again, at the sentinel.** seq 7 is a *fresh* class-2
  event (`NoRefusal == INT64_MAX`) on **core 0**, the lowest core id in the whole
  set. It still sorts after the stamp-9 events on core 4, because `age` is
  compared before `core`. **A refused request beats a fresh one regardless of
  core id**. This is exactly the v1-to-v3 divergence the plan flagged for
  sign-off in 3.8, and it is the reason V3's golden log is re-baselined once,
  deliberately.

One consequence of the `age` field's collapse: pops 5, 6 and 7 all tie on stamp
9 in this fixture, which cannot happen for real class-2 waiters (no two share a
stamp, I2). The fixture ties them on purpose, because `core` and `seq` are
*live* for the other three classes and the comparator has one body for all four.

## 7. Why `schedule()` assigns the `seq` and derives the class itself

```cpp
void schedule(SimTime time, EventKind kind, RefusalOrder age, CoreId core, Payload payload) {
    if (time < now_) throw std::logic_error(...);
    q_.push(Event<Payload>{EventKey{time, class_of(kind), age, core, EventSeq{next_seq_}},
                           kind, payload});
    ++next_seq_;
}
```

Two of the five key fields are **not parameters**, and neither omission is
convenience.

**`seq` cannot be passed.** 3.6 says it is "a monotonic counter assigned at
*schedule* time", and there is exactly one place that is. If a caller supplied
it, two events could be given the same value, and the effect would be invisible
until the exact case in section 6's pop 6 vs pop 7, where `seq` is the only field
left. Two events comparing fully equal is precisely where a tie needs breaking,
so a duplicated `seq` is wrong *only* at the moment it matters. Making it
unrepresentable is cheaper than a rule saying "always pass a fresh counter", and
there are seven scheduling sites in 3.4 alone.

**`class` cannot be passed either.** It is derived from the kind by `class_of`,
which is 3.6's table written once:

```cpp
constexpr EventClass class_of(EventKind kind) {
    switch (kind) {
        case EventKind::L2Fill:
        case EventKind::L1Fill:  return EventClass::Fill;
        case EventKind::Barrier: return EventClass::Barrier;
        case EventKind::L1Probe:
        case EventKind::L2Probe: return EventClass::Probe;
        case EventKind::Issue:   return EventClass::Issue;
    }
    throw std::logic_error("class_of: unknown EventKind");
}
```

A handler that scheduled a fill under the probe class would reverse 4.6's worked
example: the fill at 111 would land after the probe, the probe would miss, and
the run would report 221 with a wasted fetch. **That is a plausible, wrong, and
perfectly reproducible answer**: there is no crash and no warning, only a
different number in a results row. Writing the mapping once, beside the enum it
maps, is what stops that from being a per-call-site decision.

The `throw` after the exhaustive switch is the same shape `types.h`'s `Axis`
accessors use, and for the same reason: a kind silently given a fallback class
would reorder the run against itself and the output would still look like output.

**Two other refusals worth naming.**

`schedule` throws `std::logic_error` when `time < now_`. That is P1 violated: a
min-heap makes `now` non-decreasing only if nothing is inserted into the past,
and an event scheduled behind `now` would be dispatched **immediately and out of
order** rather than at the time it names. Scheduling **at** `now` is legal and
ordinary: with 2.5b's zero latencies, whole chains run inside one timestamp.

`pop_min` throws on an empty queue rather than returning a sentinel, because an
empty queue is the engine loop's **termination condition** (3.2), so reaching
that call with nothing in it means the loop was written wrong.

Both are `logic_error` and not `invalid_argument`: no config value produces
either, so they sit in decision B27's programmer-error tier. Both are `throw` and
not `assert`, because the sweep build is `-DNDEBUG` and a silently reordered run
still produces numbers.

**`Payload` is a template parameter**, and that is a scope decision rather than
generality. At plan unit B2 the hierarchy does not exist: what an event is *about*
is a `Request`, an `Mshr`, a core, or a tile, and every one of those belongs to a
later unit. Naming a concrete payload here would be this unit deciding a
downstream unit's storage; an opaque integer handle would be the same decision
wearing a disguise, and would additionally invent a handle table nobody asked
for. The ordering, all this unit owns, does not depend on the payload at all,
which is what makes the parameter free.

## 8. Determinism is NOT orderedness, and this is the important part of plan unit B2

The plan's exit criterion for this unit (Part 7, line 1345) is:

> total order; two identical runs produce identical event logs

**Those are two criteria of very unequal strength, and the second one alone can
be satisfied by a queue that is wrong.**

"Two identical runs produce identical logs" is a statement about **reproducibility**,
and it is invariant under *any* deterministic comparator. Reverse the comparator
and both runs reverse together. The logs still match. The test still passes.

Three mutations demonstrate it, and all three are in `mutation_check.sh` for this
round:

| mutation | what it does | survives a determinism-only suite? |
|---|---|---|
| `B2 key_less reverses the seq` | last field becomes `a.seq > b.seq` | **yes**: every tie at the deepest level flips, identically in both runs |
| `B2 key_less reverses the class` | `Issue` before `Probe` before `Barrier` before `Fill` | **yes**: 4.6's worked example now reports 221 instead of 111, in both runs |
| `B2 the queue is a max-heap` | the comparator inversion in `Later` is removed | **yes**: the queue pops the *latest* event first, reproducibly |

The middle one is the alarming one. It inverts D4 ("lookups see this cycle's
fills"), turns every same-cycle hit into a miss and a second fetch, and changes
hit rate, DRAM traffic and `tile_origin`, that is, it changes **every number the
study reports**, while passing a criterion the plan states as sufficient. The
max-heap mutation is worse still in one respect: `std::priority_queue`'s internal
arrangement is a pure function of the insert sequence, so a max-heap is exactly
as reproducible as a min-heap.

**What kills them is a separate, independent check**: pop order must equal
**sorted order under an oracle comparator written out from the plan text**, not
from `event.h`.

```cpp
// tests/test_event.cpp
bool oracle_earlier(const EventKey& a, const EventKey& b) {
    if (a.time.get() != b.time.get()) return a.time.get() < b.time.get();
    const int ca = static_cast<int>(a.cls);
    const int cb = static_cast<int>(b.cls);
    if (ca != cb) return ca < cb;
    if (a.age.get() != b.age.get()) return a.age.get() < b.age.get();
    if (a.core.get() != b.core.get()) return a.core.get() < b.core.get();
    return a.seq.get() < b.seq.get();
}
```

The independence is the whole value. **If the oracle called `key_less`, every
mutation of `key_less` would move the oracle with it**, and the comparison would
agree with itself while both halves were wrong. That is the same circularity
decision B102 caught in the probe-is-not-an-access test, in comparator form: a
before/after snapshot cannot catch a perturbation that also perturbs the
snapshot.

**What this means for anyone reading the plan's criterion.** Line 1345's two
clauses are not a restatement and a paraphrase; they are a strong claim and a
weak one, and the weak one is the memorable half. An implementer who reads the
row and builds "two runs, `diff` the logs" gets a green suite over a reversed
comparator or a max-heap. The total-order half needs a check with an *external*
notion of correct order, which means either a hand-written expected sequence or
an independently spelled comparator, and it must be **stated as the load-bearing
one**. This is recorded here rather than only in a test comment because the next
person to touch the ordering will read the plan row before they read the test.

One further thing determinism alone would not catch, worth stating because the
fix is a one-word change: `next_seq_` is **per queue** and is never reset. A
process-wide counter would also be deterministic, and would also be wrong the
moment two queues exist, since seq values from one would interleave with the
other's. It is `int64` for the refusal counter's reason (Q8): a full trace at 256
cores schedules more than 2^31 events, and a wrapped counter silently reorders
the heap.

---

# Part III. Plan unit B3: `MshrFile`

## 9. The file, and what this unit deliberately does not know

```cpp
class MshrFile {
    MshrFile(capacity, tgts_per_mshr, demand_reserve, RefusalCounter&);
    Mshr* find(LineId);
    bool  has_slot(const Request&) const;
    Mshr& allocate(LineId, Request& primary);
    bool  add_target(Mshr&, Request&);
    void  push_line_wait(Mshr&, Request&);
    void  push_slot_wait(Request&);
    bool  release_reservation(Request&);
    void  retire(Mshr&, RetireResult& out);
    // capacity(), tgts_per_mshr(), demand_reserve(), live(), reserved(), slot_wait_depth()
};
```

One class for both levels: plan 2.2's "L1 MSHR file" and 2.3's "L2 MSHR file" are
the same structure with different capacities, and 3.4's two triage functions are,
in the plan's own words, of "identical shape".

**What this unit does NOT do,** and the boundary is the unit's definition, since
Phase B is "timing primitives: clock exists, hierarchy does not": it never
reserves a port, never schedules an event, and never knows which level it is. So
`retire` **reports** who was satisfied and who wakes, in order, and the engine
decides what that means at its level: at the L2 an `E_L1Fill` per target, at the
L1 a `core_line_done` per target (3.4). Two consequences are load-bearing later:
this file cannot violate P2 by predicting a time, because it holds no clock; and
the merge-and-sort I7b rests on happens **here, once**, rather than in each
caller.

The wait indices hold `Request*` and nothing else, which is P5: "a request that
is refused is already held somewhere". At the L2 it is held by its own L1 MSHR
entry, at the L1 by its core's outstanding-burst registers. These vectors are
**selection sets over structures the engine already owns**. Copying a refused
request into a buffer here would have invented hardware, and 4.1's bound would
become an argument about simulator memory instead of about credits.

**The running configuration for everything below**, one L2 file:

```cpp
RefusalCounter counter;                     // issues 0, 1, 2, ... ; NoRefusal is INT64_MAX
MshrFile f(/*capacity=*/4, /*tgts_per_mshr=*/2, /*demand_reserve=*/1, counter);
```

so the prefetch budget is `capacity - demand_reserve == 3`, and an entry admits
its primary plus **one** later merge.

## 10. One miss, end to end: allocate, merge, refuse, retire, wake

Cycle numbers use 4.6's worked-example latencies (`l2_latency = 10`,
`l2_miss_latency = 100`, `ii = 1`), so the arithmetic is checkable against the
plan.

### t = 0: four allocations fill the file

Core 0's request `r0` for line **X** reaches the L2.

```
find(X)            -> nullptr
has_slot(r0)       -> r0.reserved == false
                      free = capacity 4 - live 0 - reserved 0 = 4
                      r0.demand -> free > 0 -> TRUE
allocate(X, r0)    -> Mshr{ line=X, core=0, demand=true, targets=[&r0], line_wait=[] }
                      live() == 1
```

`r0.reserved` was false, so nothing was spent. Three other cores do the same for
lines A, B, C. **`live() == 4`, `reserved_ == 0`, so `free == 0`.**

### t = 5: a third-party request is refused for want of any entry

Core 4's `r_s` wants line **Y**. There is no entry for Y and the pool is full.

```
find(Y)            -> nullptr
has_slot(r_s)      -> free = 4 - 4 - 0 = 0 ; demand -> 0 > 0 -> FALSE   (BLOCKED_POOL)
push_slot_wait(r_s):
    r_s.demand is true, so no throw
    mark_refused(r_s, Slot, counter):
        r_s.refusal == NoRefusal  ->  r_s.refusal = counter.next() = 0
                                      r_s.reason  = Slot
    slot_wait_ = [ r_s(stamp 0) ]
```

**Stamp 0 is the first stamp of the run.** `counter.issued()` is now 1.

### t = 6: an entry retires, and the grant loop pays for one waiter

Line A's fill arrives and the engine calls `retire(A_entry, out)`.

```
1. out.targets = A_entry.targets            (copied BEFORE the erase)
2. out.wake    = A_entry.line_wait          (empty here)
3. entries_.erase(it)                       live() 4 -> 3
4. collect_grants(out.wake):
       live 3 + reserved 0 < capacity 4, slot_wait not empty
       min_element under key_less  ->  r_s (stamp 0, the only member)
       slot_wait_.erase(oldest)
       r_s.reserved = true ;  reserved_ = 1
       out.wake.push_back(&r_s)
       next iteration: live 3 + reserved 1 < 4 is FALSE -> stop
5. stable_sort(out.wake)                    one element, nothing to do
```

The engine reinjects `r_s`: `l2_bank.reserve(6)` returns 6, and it schedules
`E_L2Probe(r_s)` at `6 + l2_latency == 16`. **`r_s` re-probes at 16, not at 6.**
That gap is what the next section is about.

### t = 7 and t = 9: a fresh request allocates Y, and a second merges onto it

`r_s` is asleep in the queue holding a reservation. Meanwhile core 5's `r_t`
arrives for line Y.

```
find(Y)            -> nullptr
has_slot(r_t)      -> free = 4 - live 3 - reserved 1 = 0 ...
```

That is a refusal, so let line B retire at t = 7 as well (its own fill lands),
taking `live()` to 2 and leaving `free = 4 - 2 - 1 = 1`. Then:

```
has_slot(r_t)      -> 1 > 0 -> TRUE
allocate(Y, r_t)   -> Mshr E_Y{ line=Y, core=5, demand=true, targets=[&r_t] }
                      live() == 3
```

At t = 9 core 6's `r_u` also wants Y:

```
find(Y)            -> &E_Y
add_target(E_Y, r_u):
    targets.size() == 1  <  tgts_per_mshr 2   -> push
    E_Y.demand = true || true = true
    returns TRUE                                        (MERGED)
E_Y.targets = [ &r_t, &r_u ]
```

**A secondary miss costs zero downstream traffic**: no port, no event, no second
fetch. That is D3, "subscribes, computes nothing".

### t = 12: a third requester is refused onto the line-wait index

Core 7's `r_v` wants Y.

```
find(Y)            -> &E_Y
add_target(E_Y, r_v):
    targets.size() == 2  >=  tgts_per_mshr 2  -> returns FALSE, changes nothing
push_line_wait(E_Y, r_v):                                (BLOCKED_TARGETS)
    mark_refused(r_v, Line, counter) -> r_v.refusal = 1, r_v.reason = Line
E_Y.line_wait = [ r_v(stamp 1) ]
```

`add_target` returning `false` **and changing nothing** is what lets the caller
fall through to `push_line_wait` without an undo. The bound lives inside
`add_target` so I3 (`|targets| <= tgts_per_mshr`) cannot be violated by a caller
that checked it and then pushed anyway.

### t = 16: `r_s` finally re-probes, and lands *behind* a younger waiter

```
find(Y)                     -> &E_Y            (it did not exist when r_s went to sleep)
release_reservation(r_s)    -> r_s.reserved was true
                               r_s.reserved = false ; reserved_ 1 -> 0 ; returns TRUE
add_target(E_Y, r_s)        -> FALSE, targets are full
push_line_wait(E_Y, r_s):
    mark_refused(r_s, Line, counter):
        r_s.refusal == 0, which is NOT NoRefusal  ->  DOES NOTHING
        stamp stays 0 ; reason stays Slot
E_Y.line_wait = [ r_v(1), r_s(0) ]
```

**Insert order is `[1, 0]`.** That is plan 3.8's out-of-order-insert
counterexample, reached exactly as the plan describes it: a slot waiter outlived
the allocation of an entry it later merged onto, and arrived carrying an older
stamp than what was already there.

Note also `release_reservation` returning **true**: a credit was genuinely freed,
so the caller knows to run the grant loop again and hand it to the next waiter.
3.4 calls it on every hit and every merge whether or not a reservation was held,
so a request that held none is not an error and returns `false`.

### t = 126: `E_Y` retires

`E_Y`'s own fill arrives 110 cycles after it was forwarded.

```
retire(E_Y, out):
  1. out.targets = [ &r_t, &r_u ]           copied before the erase
     out.wake    = [ &r_v(1), &r_s(0) ]     the line waiters, ALL of them
  2. entries_.erase(it)                     live() 3 -> 2
  3. collect_grants(out.wake):
         live 2 + reserved 0 < 4  BUT slot_wait_ is empty -> nothing appended
  4. stable_sort(out.wake) by  a.refusal < b.refusal
         [ r_v(1), r_s(0) ]  ->  [ r_s(0), r_v(1) ]
```

**Result:**

| group | members | what the engine does with them |
|---|---|---|
| `out.targets` | `r_t`, `r_u` (primary first, then merge order) | satisfied **directly** by the fill, no re-triage: at the L2 an `E_L1Fill` each, at the L1 `core_line_done` each |
| `out.wake` | `r_s`(0), then `r_v`(1) | reinjected **in this order**: each reserves a port and re-probes |

**Who wakes, in what order: `r_s` before `r_v`, stamp 0 before stamp 1**, even
though `r_v` was pushed onto the index first. Both will hit, since the line is
resident by the time they re-probe (3.7: a `LINE` waiter's re-triage is always a
hit), but the *order* is not cosmetic. Reinjection reserves a port, so at
`ii = 1` the two get accept times one cycle apart, and under LRU the order two
accesses to one set are serviced **is** the recency stack (D7). One flipped tie
leaves a different victim and every access after it diverges.

`out` is **replaced**, not appended to, so a caller may reuse one buffer across
retires; `out.targets` is assigned rather than swapped so that reuse keeps its
capacity.

## 11. Why `retire` erases the entry BEFORE running the grant loop

Step 2 above (erase) comes before step 3 (`collect_grants`), and the ordering is
load-bearing rather than tidy. `collect_grants`'s condition is:

```cpp
while (live() + reserved_ < capacity_ && !slot_wait_.empty()) { ... }
```

Take a full file (`capacity 4`, `live() == 4`, `reserved_ == 0`) with two slot
waiters, and retire one entry:

| order | `live()` when the loop runs | `4 + 0 < 4`? | grants handed out |
|---|---|---|---|
| **collect, then erase** | 4 | **false** | **0** |
| **erase, then collect** (what the code does) | 3 | `3 + 0 < 4` true | **1** |

**The credit this retire freed is the one the loop hands out.** Collecting first
would grant one waiter fewer *at every retire*, forever, so a file of capacity 4
would behave like a file of capacity 3 while `capacity()` and every stat kept
reporting 4.

That failure mode is worth stating in full because of how it would present. It
does not crash, does not assert, and does not produce an invalid state: I4
(`|entries| + reserved <= capacity`) still holds, and holds *more* comfortably.
What it produces is a permanently under-used entry and a permanently longer wait
queue. In a sweep over `l1_mshrs`, the knee would appear one entry early and
would be read as **a result about MSHR sizing** rather than as an off-by-one in
a loop's position.

The other half of the ordering: `collect_grants` runs **before** the sort, not
after, because the granted waiters are part of the same ordered wake list. Two
loops instead of one would stagger the wake by loop order rather than by age,
which is what I7b forbids.

And `collect_grants` uses `std::min_element` under 3.8's key rather than popping
the front, for the reason section 10 just demonstrated: `slot_wait_` is **not in
age order**. Taking the front would grant the wrong request in exactly the
out-of-order-insert case, and the sort in `retire` would then be ordering a wake
list that already had the wrong members in it. The loop terminates because every
iteration strictly increases `reserved_` while its own bound is fixed (I7).

## 12. The demand-reserve budget, in numbers

`has_slot` is three answers in one predicate:

```cpp
bool MshrFile::has_slot(const Request& r) const {
    if (r.reserved) return true;
    const std::int32_t free = capacity_ - live() - reserved_;
    return r.demand ? free > 0 : free > demand_reserve_;
}
```

At `capacity 4, demand_reserve 1`:

| `live() + reserved_` | `free` | demand admitted? | prefetch admitted? |
|---|---|---|---|
| 0 | 4 | yes | yes (`4 > 1`) |
| 1 | 3 | yes | yes (`3 > 1`) |
| 2 | 2 | yes | yes (`2 > 1`) |
| **3** | **1** | **yes** (`1 > 0`) | **no** (`1 > 1` is false) |
| 4 | 0 | no | no |

So a prefetch can hold **at most 3 entries**, which is `capacity -
demand_reserve` exactly, and **the last entry is always reachable by a demand
request**. That is 4.6's guarantee: prefetching can delay demand but can never
starve it (decision B12).

**`demand_reserve == capacity` is accepted and is the default configuration, not
an edge case.** `l1_demand_reserve` defaults to `lines_per_burst`, so at
`l1_mshrs == lines_per_burst` the budget is exactly zero and `free > capacity` is
never true, so prefetching is off however `prefetch_distance` is set (4.2). The
constructor refuses only `demand_reserve > capacity`, which would make the budget
*negative*, which is not "prefetching is off" but a bound that reads backwards. D1's
stricter rule (that `demand_reserve >= mshrs` throws) is a rule about a config
that **also** sets `prefetch_policy = next_burst`, and that is a field this class
never sees.

**The first branch, `if (r.reserved) return true`, is the reservation system
working.** A grantee is admitted unconditionally because the credit it is about to
spend is the one `collect_grants` already set aside, and is already counted in
`reserved_`. Without that case, a grantee would be refused **by its own
reservation**: at `live 3, reserved 1`, `free` computes to 0 for the very request
that reservation was made for.

`allocate` then spends it:

```cpp
if (primary.reserved) { primary.reserved = false; --reserved_; }
```

so `live + reserved` trades one for one and I4 is preserved through the
transition rather than around it.

## 13. Promotion to demand is idempotent by construction, not by discipline

```cpp
bool MshrFile::add_target(Mshr& e, Request& r) {
    if (as_count(e.targets.size()) >= tgts_per_mshr_) return false;
    e.targets.push_back(&r);
    e.demand = e.demand || r.demand;
    return true;
}
```

4.6's late-prefetch path is that one `||`. Its full truth table:

| `e.demand` before | `r.demand` | `e.demand` after | case |
|---|---|---|---|
| false | **true** | **true** | **the promotion**: the core's own demand request merges onto a prefetch entry that started early but not early enough |
| true | true | true | ordinary secondary miss |
| true | false | **true** | a prefetch merges onto a demand entry, **unchanged**, which is the half a naive assignment gets wrong |
| false | false | false | prefetch onto prefetch |

Idempotence is a property of `||` itself: `(x || y) || y == x || y`, so applying
the promotion a second time cannot change anything, whatever the order the merges
arrive in and however many of them there are. **Nothing has to check whether the
promotion already happened**, and there is no "promoted" flag that could disagree
with `e.demand`.

The bug this shape forecloses is the third row. Written as `e.demand = r.demand`,
an assignment one character shorter and the spelling a hurried edit reaches
for, a prefetch merging onto a **demand** entry would silently **demote** it.
The line would still be fetched and the targets still satisfied, so nothing would
fail; what would change is that a demand entry would be reported as a prefetch
entry, and any future rule keyed on `e.demand` (4.6's statistics split of timely
versus late versus wasted, for one) would attribute a demand fetch to the
prefetcher.

Promotion lives inside `add_target` for the same reason the target bound does: so
it cannot be forgotten at one of its call sites, and 3.4 has two of them.

---

# Part IV. The batch as a whole

## 14. Four design choices worth your eye

### The primary occupies `targets[0]`

```cpp
Mshr entry{line, primary.core, primary.demand, {}, {}};
entry.targets.push_back(&primary);
```

The allocating request is a **target**, not a separate field beside the target
list. Two things rest on that.

**4.1's capacity bound only works this way.** The plan writes the per-entry L2
bound as

```
|e.line_wait|  <=  n_cores - l2_tgts_per_mshr
```

which counts the primary as one of the `tgts_per_mshr`. Put the primary in its
own field and the bound is off by one, in the direction that under-reports the
wait depth. In this Part's running configuration, `tgts_per_mshr == 2` means the
primary plus **one** later merge, and `r_v` at t = 12 was refused with only one
non-primary target in the list.

**And it matches gem5** (Appendix B), which is the vocabulary anyone reviewing
this will arrive with.

The third benefit is local: the primary is satisfied by the fill through the same
loop as every later merge, so there is no second path that could satisfy it
differently, and `retire` needs no special case for it.

### `WaitReason::Line` deliberately carries no line

```cpp
enum class WaitReason : std::uint8_t { None = 0, Slot = 1, Line = 2 };
```

3.7's reason is written `{SLOT, LINE(l)}`, and the `l` is **not** stored. A
request only ever line-waits on the entry matching its own address, so the `l` of
`LINE(l)` is always `r.line`, which the request already holds. A second copy is a
field that can **disagree** with the one beside it, and there is no reading of
the model where the disagreement means anything. That is decision B89's shape
(`InsertResult::evicted` reported by construction) applied to a tag instead of a
flag.

The reason itself must survive, and this is the part that is not optional: it is
what prevents D5's livelock. A `LINE` waiter woken by an unrelated retire
re-blocks on the same condition, is popped again, and the freed slot is never
consumed. What actually releases a waiter, though, is **which vector holds it**,
not this field. See open question 3 below, where those two diverge.

### `push_line_wait` / `push_slot_wait` throw on a non-demand request

```cpp
if (!r.demand) caller_error("push_line_wait", "a prefetch is dropped, never queued (N16)");
```

A refused prefetch is **dropped**, never queued (4.6, N16, decision B11), and I15
states it as an invariant. Making it a throw rather than an assert or a comment
means **the drop rule is unrepresentable in this class**: there is no sequence of
calls that puts a `demand == false` request onto a wait index.

That is worth the two lines because of what the rule is holding up. 4.1's entire
bound is that the waiting population stays backed **one-for-one by demand
credits**: every waiter has a real L1 MSHR entry or a real core burst register
behind it, which is why the wait sets have no depth limit to design. A prefetch
permitted to wait would occupy a selection set with **nothing behind it**, and
4.1's argument would collapse from a hardware statement into a simulator-memory
statement, which is precisely the v1 error the plan corrected. Cheaper to make
it impossible here than to look for it in a sweep.

`mark_refused` is called **inside** these two functions for the same reason:
3.8's `mark_refused` immediately precedes every push in the plan, at both levels
and on both indices, and a push that skipped it would put an **unstamped**
request into a population ordered by stamp, where `NoRefusal == INT64_MAX` sorts
it last forever. That is a starvation bug produced by a missing call, and I10's
proof would not hold.

### `allocate` spends the primary's reservation itself

The plan writes the spend as a separate `consume_reservation(r, F)` call after
every `allocate`, at both levels, with no exception. Folding it in removes a
pairing a caller can forget, the same spirit as I3 living inside `add_target`.

The cost of forgetting it is not a crash: **a leaked reservation is a credit the
file never hands back.** `reserved_` stays permanently one higher, so
`collect_grants` stops one waiter short **for the rest of the run**, and the
symptom is a stall that gets attributed to the MSHR bound. It is the same class of
silent, plausible-looking error as section 11's ordering, and both are cheap to
make impossible.

## 15. What was deliberately NOT built, and why

**N13's `ii = 0` warning.** The plan's B1 row asks that config "rejects a
negative `ii` and warns on `ii = 0`". The rejection is in `Port`'s constructor;
**the warning is not**, and it belongs to config load at D1. Two reasons, and
they are independent:

- *It would fire hundreds of times for one typed value.* D1 reads one config; this
  constructor runs **once per port per core**, so a single `l1_ii = 0` would emit
  the warning up to `n_cores + l2_banks + 1` times, at the swept range's top, 256
  cores plus banks plus DRAM.
- *It would put logging in a library that has none.* Nothing in `native/` writes
  to a stream today. Adding the first one for a warning means choosing a stream, a
  format and a suppression story inside a class whose whole job is three lines of
  arithmetic.

`ii = 0` is **accepted**, which is N13 rather than an oversight: it is the
modelling escape hatch meaning infinite throughput, and it is what the unbounded
baseline (V1) is built from. `ii` is checked before `latency` in the constructor,
because `ii` is the field N13 rules on and the one a sweep varies, so a grid
point wrong in both reports the interesting half.

**`Request::seq`.** Plan 3.3 lists `core, line, seq` on the request. The `seq` is
not built, for two reasons stated together:

- **Nothing in Part 3 reads it.** No pseudocode, no key, no comparison.
- **The `seq` that IS load-bearing is the event's**, assigned at schedule time
  (3.6), and `event.h`'s `EventSeq` carries it. A second `int64` counter of the
  **same name** on the request would be N12's confusion in the one place a reader
  is most likely to conflate them, and it is exactly why `EventSeq` and
  `RefusalOrder` are two distinct tagged types despite both being monotonic
  `int64` counters that sit in the same key (see the `types.h` comment).

**`reinject`, `triage_L1`, `triage_L2`, and the engine half of `retire`.** All
four are plan unit C2's, by the schedule (Part 7 line 1353), and all four need
what Phase B does not have: a port to reserve, an event to schedule, and a level
to be at. `retire` here stops at "here is who was satisfied and here is who
wakes, in order"; the loop that turns that into `E_L1Fill`s or `core_line_done`s
is the engine's.

## 16. Open questions

**Two need your ruling (1 and 2). Three are records of a divergence (3 and 4) or
carried (5).**

---

### 1. U17, the `on_evict` plan defect, still open and still needs you

Carried unchanged from the A4c + A5 batch. Not resolved, not narrowed, and
repeated here because this file is where you read before ruling.

**Part 2.2**, the authoritative interface row, lists **four** verbs:

> `ReplacementPolicy { on_hit, on_fill, on_invalidate, pick_victim }`

**Part 3.4, line 619**, the `install()` pseudocode, calls a fifth:

```
cache.policy.on_fill(slot)          # line 617
if res.evicted:
    cache.policy.on_evict(slot)     # line 619
```

`on_evict(slot)` **after** `on_fill(slot)`, **on the same slot**. For any stamp
policy that clobbers the stamp the fill just wrote, so the freshly filled slot
looks like the oldest line in its set and every victim choice downstream of it is
wrong in a way that still produces plausible hit rates.

A5 built to Part 2.2's four and escalated (decision B97). Three outcomes are
coherent and the choice between them is a design call: drop `on_evict` and amend
3.4; keep it and rule that it fires **before** `on_fill`; or keep it and rule that
it takes the **evicted line's identity** rather than the slot, which is the
reading D2's victim-age distribution would want. **Nothing in Phase B touches
this**, and it stays a plan defect rather than a coding choice.

---

### 2. A plan erratum to confirm: 4.6's prose and the code disagree about the prefetch cut-off

**The code is right. The prose is looser, and someone will "fix" the code to
match it.** That is why this is here rather than in a comment.

Plan 4.6's refusal table, third row:

> no slot, or the entry's targets full, or **fewer than `demand_reserve` entries
> left** → drop

Read literally, "fewer than `demand_reserve` remain" is `free < demand_reserve`.
The code refuses at `free <= demand_reserve`:

```cpp
return r.demand ? free > 0 : free > demand_reserve_;
```

They differ by exactly one case, `free == demand_reserve`, and at this Part's
configuration (`capacity 4, demand_reserve 1`) that is `free == 1`:

| | refuse a prefetch when | at `capacity 4, demand_reserve 1` | prefetch may hold |
|---|---|---|---|
| **4.6's prose** | `free < 1` | only at `free == 0` | up to **4** entries |
| **the code** | `free <= 1` | at `free == 1` and `free == 0` | up to **3** entries |

Under the prose, a prefetch takes the **last** entry, which is the exact case the
reserve exists to prevent, and it makes `demand_reserve` inert at every value.

**The code matches 4.2's budget exactly**, and 4.2 states it twice:

> The budget is `l1_mshrs - l1_demand_reserve`, so at `l1_mshrs = lines_per_burst`
> the budget is zero and prefetching is off no matter what `prefetch_distance`
> says.

`free > demand_reserve` before allocation is the same statement as
`live + reserved <= capacity - demand_reserve` after it, so the prefetcher's
ceiling is `capacity - demand_reserve` and the zero-budget default falls out.
Under the prose's reading, at `demand_reserve == capacity` a prefetch would still
be admitted at `free == capacity`, and "prefetching is off" would be false.

**What is wanted from you:** confirm that 4.6's sentence is the erratum and 4.2's
budget is the intent, so the plan document can be corrected. The alternative, the
prose being right, contradicts 4.2, 4.6's own closing paragraph ("prefetch can
never take the last `l1_demand_reserve` entries"), and decision B12.

---

### 3. `Request::reason` records why a request ENTERED the waiting population, not which index holds it

`mark_refused` is write-once, and it writes **both** fields together:

```cpp
if (r.refusal == NoRefusal) { r.refusal = counter.next(); r.reason = reason; }
```

Section 10's `r_s` is the worked case: refused for a **slot** at t = 5, stamped 0
with `reason = Slot`; re-refused onto `E_Y`'s **line-wait** index at t = 16, where
`mark_refused` finds a stamp already present and changes nothing. So at t = 16,
`r_s.reason == Slot` while `r_s` is sitting in `E_Y.line_wait`.

**Correctness does not depend on it.** What releases a waiter is which vector
holds it: `E_Y.line_wait` is released by `E_Y` retiring, `slot_wait_` by any
retire's grant loop. The livelock 3.7 warns about is prevented by the **index
split**, which is structural, not by this field.

**Part 8 does depend on it**: "wait population reported separately by wait
reason". Under the current write-once rule, that report attributes `r_s` to
`Slot` for its whole life, so the two reported populations will not match the two
index depths whenever a request has moved between them. The divergence is
recorded rather than designed around, and the fix (if the report is meant to
track the index) is a rule change at D2 or a second field, neither of which this
unit may choose, since 3.8 explicitly makes `reason` part of the write-once
`mark_refused`.

### 4. `MshrFile` enforces neither I5 nor the dangling `mshr1` after retire: both are engine-level

Two invariants from Appendix A that this unit does **not** check, stated so
neither is later assumed to be covered here:

- **I5**, "a request is on at most one wait index, and holds at most one
  reservation". `push_line_wait` and `push_slot_wait` do not look at whether the
  request is already on the other index, since this class holds one file, and at the
  L1 versus L2 there are two, so a complete check needs a view this class does not
  have. The reservation half *is* structurally safe within one file
  (`allocate` and `release_reservation` both clear `r.reserved` as they adjust
  `reserved_`), but the index half is the engine's.
- **A dangling `Request::mshr1` after retire.** I6 is `r.level == L2 <=> r.mshr1
  != null`. `retire` erases the `Mshr` from `entries_` and does **not** walk the
  requests that pointed at it to null their `mshr1`. It cannot: it holds no list
  of them, since `mshr1` points from a request at *another* level's file.

Both belong to plan units C1 and C2, which own triage and the retire handlers and
are the only code that sees both levels at once. Recorded here because an
invariant listed in Appendix A with no owner named is the kind of thing that gets
assumed into the nearest class.

### 5. Carried, unchanged by this batch

- **The plan's Q2 plausibility bound** (representability versus plausibility),
  deferred to **D1** with one shared bound rather than several scattered ones,
  per decision B80. Phase B adds no new site: `MshrFile`'s counts are bounded by
  `capacity`, which the constructor bounds at 1, and `Port` holds two scalars.
- **U12** (which tier wins when a burst is both malformed and out of range).
- **U13's sibling** (the validation order at the front of `expand`, tested but
  stated nowhere).
- **U14** (does `locate` owe a check on `num_sets`).
- **U15's general count bound** (`count = INT32_MAX` at stride 1).

None of the five is touched by this batch, none blocks Phase C, and all five are
recorded on their rows in `PROGRESS.md`.

---

**Summary of what wants your attention.** Question 1 (U17) is a genuine
contradiction inside the plan and has been waiting a round. Question 2 is a new
plan erratum where **the code is correct and the prose is not**, which is the
dangerous direction: left uncorrected, the next reader reconciles them by
changing the code. Question 3 is a recorded divergence between a field's meaning
and one Part 8 report. Question 4 hands two Appendix A invariants explicitly to
C1/C2. Question 5 blocks nothing.

Beyond the questions, the one finding in this batch that changes how a later unit
should be *tested* rather than built is section 8: **the plan's stated exit
criterion for plan unit B2 is satisfiable by a wrong queue**, and only an
independently written oracle distinguishes them.
