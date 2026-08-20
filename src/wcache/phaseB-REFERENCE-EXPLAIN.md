# Phase B construct reference

**What this is.** A per-construct reference for every public class, struct, enum
and function of Phase B: one entry each, organised by file and then by construct.
It answers "what is this thing, what does it promise, what does it refuse, and
what does it look like with real numbers in it" without asking you to read a
narrative first.

**What it is not.** It is not the narrative record. `phaseB-EXPLAIN.md` remains
alongside this file and stays the account of *how the batch was built and what
was decided in it*: the run walked end to end, the open questions, and the
"deliberately not built" list. The two are meant to be read for different
purposes. Where a worked example appears in both, it is the same example with the
same numbers, reorganised here under the construct it belongs to.

**The record of decisions is `PROGRESS.md`.** Every `Bnn` cited below is a row on
its board.

---

## A three-way naming collision, stated once

Three different numbering schemes in this tree use the same letters, and two of
them use the same numbers. Nothing below is ever written bare.

| written as | means | example |
|---|---|---|
| **plan unit B3** | a unit of the v3 plan's Part 7 build schedule | plan unit B1 is `Port`, B2 is `EventQueue`, B3 is `MshrFile`; plan units C1-C5 are `CacheLevel`, the engine, the core model, back-invalidation, the prefetcher |
| **decision B121** | a row on `PROGRESS.md`'s decision board, numbered B1 through B152 | decision B1 is the `native_v1_archive/` ruling; decision B3 is `NoRefusal == INT64_MAX` |
| **v3 change C1** | a change label inside the plan document itself, marking what v3 altered against v2 | decision B131 records that plan unit C3's self-timed recurrence "is v3's change C1" |

The first two collide on B1, B2 and B3, and they are not even about the same
subjects, so a reader who lands on the wrong one gets a sentence that makes no
sense rather than a plausible wrong answer. That is luck, not design. The second
and third collide on C1 and C2. Read the surrounding sentence before assuming
which is meant, and if a bare `B3` ever appears in this tree, treat it as
ambiguous.

## How to read an entry

Every entry has the same five parts.

1. **What it is** -- one or two sentences.
2. **Contract** -- the signature, what it promises, what it refuses and with which
   exception type, its preconditions, and the validation *order* where the order
   is load-bearing.
3. **Worked example** -- real numbers.
4. **Decisions** -- the `Bnn` rows that shaped it.
5. **Traps** -- the ways a caller or a later editor gets it wrong, with what the
   symptom looks like.

The exception tiers are uniform across Phase B and are decision B27's:

| exception | for |
|---|---|
| `std::invalid_argument` | a config field that is out of range or malformed |
| `std::out_of_range` | an index outside a structure's bounds |
| `std::logic_error` | a stub, and an engine invariant violated by the caller |

Everything in Phase B is a `throw` and never an `assert`, because the sweep build
is `-O2 -DNDEBUG` and a silently wrong run still produces numbers.

**Files covered.**

| file | constructs |
|---|---|
| `native/include/wcache/types.h` (Phase B additions only) | `BurstIndex`, `EventSeq` |
| `native/include/wcache/port.h`, `native/src/port.cpp` | `Port` |
| `native/include/wcache/event.h` | `EventClass`, `EventKind`, `class_of`, `EventKey`, `key_less`, `Event<Payload>`, `EventQueue<Payload>` |
| `native/include/wcache/mshr.h`, `native/src/mshr.cpp` | `Level`, `WaitReason`, `Request`, `Mshr`, `RefusalCounter`, `is_prefetch_at_issue`, `mark_refused`, `key_less(Request)`, `RetireResult`, `MshrFile` |

---

# `native/include/wcache/types.h` -- the two scalars Phase B added

Phase B added the ninth and tenth tagged scalars. The rest of `types.h` belongs
to Phase A and is documented in `A1-A2c-EXPLAIN.md`.

## `BurstIndex`

**What it is.** Which burst of a core's tile a request belongs to. The ninth
tagged scalar.

**Contract.**

```cpp
using BurstIndex = Tagged<std::int32_t, tags::burst_index>;
```

`int32`, matching `CoreId` under decision B5's width convention: a burst index
counts the bursts of one core inside one tile, which is tens in the corpus.
No default constructor (decision B2), so `BurstIndex{k}` must be written out.
No arithmetic operators -- only `SimTime` carries those.

**Worked example.** The reason it is tagged at all is adjacency, not width:

```cpp
Request r{CoreId{3}, LineId{800}, BurstIndex{7}};   // core 3, burst 7
Request r{CoreId{7}, LineId{800}, BurstIndex{3}};   // a transposition
```

Both compile and both are the same two `int32`s in the other order. `explicit`
cannot see the swap and the non-narrowing constructor cannot see it either,
because the two quantities are the same width and the same signedness. Naming
the quantity is what makes a later refusal about *meaning* rather than about
size -- the same argument `SetIndex` made one level up.

**Decisions.** B118 (two new tagged scalars; `BurstIndex` is the ninth, not the
eighth), B5 (int32 for small counts), B2 (no default constructor).

**Traps.** A prefetch carries a *future* burst index, so a `BurstIndex` on a
request in flight is not "the burst the core is currently working on". Reading it
as progress is wrong at any non-zero `prefetch_distance`.

## `EventSeq`

**What it is.** The value of an `EventQueue`'s own counter when an event was
scheduled: the last field of the total order, and the field that makes it total.
The tenth tagged scalar.

**Contract.**

```cpp
using EventSeq = Tagged<std::int64_t, tags::event_seq>;
```

`int64` for the refusal counter's reason (plan Q8): a full trace at 256 cores
schedules more than 2^31 events, and a wrapped counter would silently reorder the
heap. Never reset -- unique across the whole run, not merely within a tile.

**Worked example.** `EventSeq` and `RefusalOrder` are both monotonic `int64`
counters and they sit **in the same key**, three fields apart:

```
key = (time, class, effective_age, core_id, seq)
                     ^RefusalOrder          ^EventSeq
```

An implementation that compared them in the wrong order would be comparing two
counters of the same width and would produce a plausible, wrong, and perfectly
reproducible event order. That adjacency is the entire reason for the tag. The
two count different things: a refusal stamp is written **once per request** at
its first refusal and may be shared by several events of that request, while an
`EventSeq` is written **once per event** and is never reused.

**Decisions.** B118, B106/B107 (the queue assigns it), B121 (why a wrong-but-
deterministic order is the hazard this tag guards against).

**Traps.** Plan 3.3 also lists a `seq` on the *request*. It is deliberately not
built (decision B125, escalated to the human), precisely so that two `int64`
counters of the same name cannot be confused in the one place a reader is most
likely to conflate them.

---

# `native/include/wcache/port.h`, `native/src/port.cpp`

## `class Port`

**What it is.** A shared resource that accepts one request every `ii` cycles,
modelled as a single next-free timestamp. One class covers `l1_port[c]`,
`l2_bank[b]` and `dram` (plan 3.3); they differ only in the two numbers they are
constructed with.

It is principle P3 made literal: *contention is occupancy, not quota*. A quota
port would need a window, a window needs a periodic reset, and a periodic reset
is the tick loop principle D1 exists to remove. There is no window here, so there
is no window artefact: sixteen requests at `ii = 2` land at t, t+2, ... t+30
rather than all at one stamp with a cliff at the window edge.

**Contract.**

```cpp
class Port {
public:
    Port(SimTime ii, SimTime latency);
    SimTime reserve(SimTime now);
    SimTime ii() const;
    SimTime latency() const;
    SimTime next_accept() const;
private:
    SimTime ii_;
    SimTime latency_;
    SimTime next_accept_{0};
};
```

A port **never refuses and never schedules a wake-up.** `reserve` always returns,
immediately. Nothing registers on a port and nothing waits on one, which is why
plan 3.1 has no `E_PortFree` event and why P2's "subscribe, never predict" stays
a statement about MSHRs alone.

Reservations are **non-preemptive and are never released** (plan 4.3): a request
given an accept time keeps it, so `reserve` order **is** service order and is
never revisited.

**Decisions.** B105 (`reserve` returns the accept time; validation is `ii` then
`latency`, both `>= 0`, both `invalid_argument`), B126 (the `ii = 0` warning
belongs to config load, not here), B20 (`next_accept()` exposed).

### `Port::Port(SimTime ii, SimTime latency)`

**What it is.** Builds a port from its two config numbers.

**Contract.** Throws `std::invalid_argument`, naming the offending value, for a
negative `ii` or a negative `latency`.

Validation order: **`ii` first, then `latency`.** `ii` is the field N13 rules on
and the one a sweep varies, so a grid point that is wrong in both reports the
interesting half.

The bound is `>= 0` and not `>= 1` in both cases. A zero `ii` is N13's escape
hatch meaning infinite throughput and is what the unbounded baseline V1 is built
from; a zero `latency` is the *default* for both `l1_latency` and
`l2_to_l1_latency` (plan 2.5b). So the only thing either field can be wrong by is
sign.

`invalid_argument` and not `logic_error`, because both are config fields and a
sweep grid is a cross product: a combination nobody typed by hand reaching this
constructor is the expected case, not the exotic one.

**Worked example.**

```cpp
Port p(SimTime{3}, SimTime{10});     // ok
Port p(SimTime{0}, SimTime{100});    // ok -- the unbounded baseline
Port p(SimTime{-1}, SimTime{10});    // invalid_argument: "Port: ii must be >= 0, got -1"
Port p(SimTime{-1}, SimTime{-5});    // invalid_argument names ii, not latency
```

**Traps.** `ii = 0` is **accepted**, deliberately, and the warning N13 asks for is
**not** emitted here. A `Port` constructor runs once per port per core, so a
single typed `l1_ii = 0` would emit the warning up to `n_cores + l2_banks + 1`
times -- 256 cores plus banks plus DRAM at the swept range's top -- for one typed
value. It would also put the first stream write into a library that has none.
Decision B126 puts it at config load, once per config.

### `SimTime Port::reserve(SimTime now)`

**What it is.** The cycle this port can accept a request offered at `now`, and
the port's occupancy advanced by `ii`.

**Contract.**

```cpp
SimTime Port::reserve(SimTime now) {
    const SimTime accept = (now < next_accept_) ? next_accept_ : now;
    next_accept_ = accept + ii_;
    return accept;
}
```

Never throws. Returns `now` when the port is free and `next_accept_` when it is
not. Returns the **accept** time, not the completion time.

Written as a compare rather than a `max()` so the two directions read separately:
a port that is already free hands back `now`, and a busy one hands back its own
next-free stamp.

**Worked example.** `Port p(SimTime{3}, SimTime{10})`. `next_accept_` starts at 0,
because the run starts at `tile_origin[0] == 0` (plan Part 5) and a port that has
never been used is free at 0. Offer it six requests at cycles **0, 0, 0, 10, 10,
100**:

| # | `now` | `now < next_accept_`? | `accept` | `next_accept_` after | returned |
|---|---|---|---|---|---|
| 1 | 0 | `0 < 0` no | 0 | 3 | **0** |
| 2 | 0 | `0 < 3` yes | 3 | 6 | **3** |
| 3 | 0 | `0 < 6` yes | 6 | 9 | **6** |
| 4 | 10 | `10 < 9` no | 10 | 13 | **10** |
| 5 | 10 | `10 < 13` yes | 13 | 16 | **13** |
| 6 | 100 | `100 < 16` no | 100 | 103 | **100** |

Accepts: **0, 3, 6, 10, 13, 100.**

Three properties, each named by the plan rather than an artefact of the
arithmetic:

- **Three simultaneous offers become three cycles, not one stamp and not a
  window.** Rows 1-3 all arrive at cycle 0 and spread to 0, 3, 6.
- **A port that has gone idle forgets nothing and charges nothing.** Row 4
  arrives at 10 with `next_accept_` at 9: the port was free for one cycle and the
  request is accepted at its own `now`, not at 9. Row 6 is the same after 84 idle
  cycles. Idleness cannot accumulate into credit.
- **Every row returns.** The port never refuses.

**`ii = 0` never delays.** `Port p(SimTime{0}, SimTime{100})`:

| `now` | `accept` | `next_accept_` after |
|---|---|---|
| 0 | 0 | 0 |
| 0 | 0 | 0 |
| 0 | 0 | 0 |
| 5 | 5 | 5 |

`next_accept_` is assigned the accept time *unchanged*, so it can never get ahead
of `now` and every offer is accepted at its own cycle forever. That is the
unbounded baseline V1, reached **by configuration rather than by a branch** --
there is no `if (ii == 0)` anywhere. Keeping the baseline and the bounded runs on
one code path is D8's lesson.

**`ii = latency` serializes.** `Port p(SimTime{100}, SimTime{100})`:

| offer | `accept` | completes at `accept + latency` | `next_accept_` after |
|---|---|---|---|
| 0 | 0 | 100 | 100 |
| 0 | 100 | 200 | 200 |
| 0 | 200 | 300 | 300 |

One round trip at a time: the next request is accepted at exactly the cycle the
previous one completes. That is plan 2.4's non-pipelined channel, recovered from
the same structure with no second class and no flag.

**The in-flight count is `latency / ii`.** Take the plan's own example -- 100
cycles of latency, `ii = 2`, a saturating stream from cycle 0:

```
request k   accepted at 2k      completes at 2k + 100
```

At cycle 100, request 0 completes; by then requests 0 through 49 have been
accepted (`2k < 100`) and request **50** is accepted at exactly 100. So **50
requests are in flight**, which is `100 / 2`. At `ii = latency = 100` the formula
gives 1, which is the table above. At `ii = 0` it is unbounded.

That is why `ii` and `latency` are two fields rather than one. A channel with 50
requests in flight and a channel that serializes 100-cycle round trips are
completely different machines, and a single "cost" number cannot tell them apart.

**Traps.**

**`reserve` returns the ACCEPT time, not the completion time, so the caller adds
the latency.** Plan 3.4 spells it:

```
accept = l2_bank[bank_of(r.line)].reserve(now);
schedule(E_L2Probe(r), accept + l2_latency);
```

The plausible caller error is writing `schedule(E_L2Probe(r), accept)` and
dropping the level's whole latency. **The confusion is invisible at the default
configuration.** At plan 2.5b's defaults `l1_latency = 0`, so on the L1 probe path

```
accept + l1_latency  ==  accept + 0  ==  accept
```

and the two spellings are **the same number**. A caller that confused them would
be right on every default run, right on the whole unbounded baseline, right on
the entire demand-only sweep grid, and wrong the moment someone sets
`l1_latency = 1` for the sensitivity run 2.5b describes and V27 has an exact
oracle for. The wrongness would then surface as *the sensitivity run failing to
reproduce its own oracle*, which reads as a problem with the oracle.

Folding the latency into `reserve` is not the fix. The two halves cross different
boundaries -- the accept time is a fact about *this port's occupancy*, the latency
is how long the structure *behind* the port takes to answer, which P4 makes a
separate event rather than a return value -- and folding them would make
`ii = latency` unexpressible, since one number would then play both roles.

**I7b is only testable at `ii >= 1`.** "Port reservation order == key order at
every retire" has nothing to express at `ii = 0`, where every reservation returns
`now`, so a test written at the default `ii = 0` passes vacuously. Same trap as
the plan's Q2 note about `l2_banks` defaulting to 1.

### `SimTime Port::ii() const`, `SimTime Port::latency() const`

**What they are.** The two config numbers this port was built from.

**Contract.** Never throw. Pure reads.

**Worked example.** The call site is `accept + port.latency()`, never
`accept + l1_latency_read_from_somewhere_else`.

**Traps.** `latency()` lives **on the port** rather than beside each call site
deliberately: the caller adds the same latency the port was built from, so two
spellings of one config field cannot drift apart. A call site that keeps its own
copy reintroduces exactly the divergence the accessor removes.

### `SimTime Port::next_accept() const`

**What it is.** The next cycle this port is free -- the port's whole state.

**Contract.** Never throws. Zero before the first `reserve`.

**Worked example.** After the six-offer table above, `p.next_accept() == 103`.

**Decisions.** B20.

**Traps.** It is exposed for a reason worth restating: without it, the occupancy
arithmetic is observable **only** through a sequence of `reserve` calls, so an
implementation that advanced `next_accept_` by the wrong amount and then
compensated on the next call would look identical from outside. V14 ("port
busy-cycles <= elapsed cycles x port count") also needs the port's own state
rather than a count of calls.

---

# `native/include/wcache/event.h`

## `enum class EventClass : std::uint8_t`

**What it is.** Plan 3.6's four tie-break classes, which order event *kinds*
that land at the same cycle.

**Contract.**

```cpp
enum class EventClass : std::uint8_t { Fill = 0, Barrier = 1, Probe = 2, Issue = 3 };
```

The values are the plan's own and **the order of the enumerators is the order of
the key**, so `<` on this enum is exactly the comparison `key_less` needs. The
explicit `: std::uint8_t` fixes the width.

**Worked example.**

| value | class | events | why here |
|---|---|---|---|
| 0 | `Fill` | `E_L2Fill`, `E_L1Fill` | state changes land before anything looks at state; a core is served *inside* its last demand fill (3.4b), so services inherit class 0 |
| 1 | `Barrier` | `E_Barrier` | observes completed fills, and therefore completed services, so a core's last service of a tile is counted before `tile_origin[N+1]` is set from it (V26) |
| 2 | `Probe` | `E_L1Probe`, `E_L2Probe` | lookups see this cycle's fills, which closes D4's "a queued miss became a hit" |
| 3 | `Issue` | `E_Issue` | new demand enters last |

At the 2.5b defaults these classes are the **ordinary case, not a corner**: with
`l1_latency = 0` and `l2_to_l1_latency = 0`, an L1 hit issues, probes and serves
the core all at one timestamp, and `E_L2Probe` schedules `E_L1Fill` at its own
timestamp. Plan 4.6's worked example is the live test -- a prefetch fill and a
demand probe both land at **cycle 111**, and only `Fill` (0) before `Probe` (2)
makes that a **hit** rather than a second fetch and a 221 (V23).

**Decisions.** B107.

**Traps.** Reordering the enumerators reorders the run. There is no separate
table to keep in step, which is the point -- but it also means an "alphabetise the
enum" edit is a semantic change.

## `enum class EventKind : std::uint8_t`

**What it is.** Plan 3.1's alphabet: the six things that can happen.

**Contract.**

```cpp
enum class EventKind : std::uint8_t {
    Issue = 0, L1Probe = 1, L2Probe = 2, L2Fill = 3, L1Fill = 4, Barrier = 5,
};
```

Six kinds, and v3 changed none of them.

**Worked example.**

| kind | means |
|---|---|
| `Issue` | burst k becomes due at the core (4.5) |
| `L1Probe` | the L1 port accepted this request, `l1_latency` later |
| `L2Probe` | the L2 bank port accepted it, `l2_latency` later |
| `L2Fill` | the memory channel returns data |
| `L1Fill` | data reaches the L1 |
| `Barrier` | the last core clears a tile |

A prefetched burst travels the same chain as any other request, carrying
`demand = false`; there is no prefetch kind. Service is a **call inside
`E_L1Fill`** rather than an event of its own, which is what gives it class 0
automatically.

**Decisions.** B107, B130 (plan unit C2 has six handlers because Part 3.1 lists
six and adds none).

**Traps.** The enumerator *values* here are not the key order -- `class_of` is.
`Issue = 0` and `EventClass::Issue = 3` are not the same 0-versus-3.

## `constexpr EventClass class_of(EventKind kind)`

**What it is.** Plan 3.6's mapping table, written once.

**Contract.**

```cpp
constexpr EventClass class_of(EventKind kind);
```

Total over the enumerators. Throws `std::logic_error("class_of: unknown
EventKind")` after the exhaustive `switch` -- unreachable today, and reported
rather than given a fallback class.

`constexpr`, so it folds at compile time at every scheduling site.

**Worked example.** `class_of(EventKind::L1Fill) == EventClass::Fill` (0);
`class_of(EventKind::L2Probe) == EventClass::Probe` (2).

**Decisions.** B107.

**Traps.** The mapping lives here rather than at the **seven scheduling sites in
plan 3.4 alone**, so a boundary crossing cannot be given the wrong class at one
site. A handler that scheduled a fill under the probe class would reverse 4.6's
worked example: the fill at 111 would land *after* the probe, the probe would
miss, and the run would report 221 with a wasted fetch. **That is a plausible,
wrong, and perfectly reproducible answer** -- no crash, no warning, just a
different number in a results row.

The `throw` rather than a fallback is the same shape `types.h`'s `Axis` accessors
use and for the same reason: a kind silently dispatched at class 0 would reorder
the run against itself and the output would still look like output.

## `struct EventKey`

**What it is.** Plan 3.6's five-field key, `(time, class, effective_age, core_id,
seq)`, in the plan's order.

**Contract.**

```cpp
struct EventKey {
    SimTime      time;
    EventClass   cls;
    RefusalOrder age;
    CoreId       core;
    EventSeq     seq;
};
```

A plain data carrier. No constructor, no invariant, no validation -- the queue
builds it and `key_less` reads it.

**Worked example.** Field by field:

- **`time`** is principle P1's whole content. The engine has no tick and no cycle
  counter of its own: `now` is the timestamp of the event being dispatched, and
  it is non-decreasing because this is a min-heap.
- **`cls`** is the four-row table above.
- **`age`** is the subject's refusal stamp, or `NoRefusal` when it has never been
  refused. **One field carries the whole of plan 3.8's two-part `(refused_bit,
  refusal)` key**, because `NoRefusal` is `INT64_MAX` (decision B3): a fresh
  request sorts after every refused one under plain `<`. The refused bit is not a
  second field that could disagree with the counter beside it.
- **`core`** and **`seq`** are dead for class 2, and 3.8 says so: no two waiters
  can tie on a monotonic counter, so once the age differs nothing after it is
  read. They are kept because the other three classes have **no refusal stamp at
  all** -- every such event carries `NoRefusal` -- and something must still make
  the order total.

**Decisions.** B3 (`NoRefusal == INT64_MAX`), B118 (`EventSeq` distinct from
`RefusalOrder`).

**Traps.** `age` is the *subject's* stamp, not the event's. Several events of one
request share one stamp; that is exactly the asymmetry with `seq`, which is
per-event.

## `constexpr bool key_less(const EventKey& a, const EventKey& b)`

**What it is.** Strictly earlier in the total order. Field by field, in the key's
order.

**Contract.**

```cpp
constexpr bool key_less(const EventKey& a, const EventKey& b) {
    if (!(a.time == b.time)) return a.time < b.time;
    if (a.cls != b.cls)      return a.cls < b.cls;
    if (!(a.age == b.age))   return a.age < b.age;
    if (!(a.core == b.core)) return a.core < b.core;
    return a.seq < b.seq;
}
```

Never throws. It is a **total** order and not merely a consistent one: `seq` is
unique across the run, so no two keys compare equal and no tie is ever left to
the container. That is what makes the heap's internal arrangement unobservable
and a re-run byte-identical, which is what D11 asks for.

**Worked example -- one tie, broken at each level in turn.** Nine events,
scheduled in the order below. `seq` is not passed by the caller: it is the
queue's own counter, so the seq column **is** the schedule order.

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

Popping them all:

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

Each boundary is a different field doing the work:

- **pop 1 vs pop 2 -- `time`.** seq 3 is at 90, everything else at 100. Nothing
  else is consulted. Note that seq 3 is class 2 and seq 2 is class 0, so the
  *later* class wins here: time is above class and there is no exception.
- **pop 2 vs 3 vs 4 vs 9 -- `class`.** All at time 100, and the four classes come
  out 0, 1, 2, 3 in order. The Fill lands before the Barrier observes it; every
  Probe sees that Fill; the new Issue enters last.
- **pop 4 vs pop 5 -- `age`.** Both class 2 at time 100. seq 5 carries stamp **2**
  and seq 0 carries **9**: the request refused earlier goes first. FIFO by first
  refusal reaching all the way into the event order, not just the wait-index sort.
- **pop 5 vs pop 6 -- `core`.** Both class 2, both stamp 9. Cores 1 and 4, so core
  1 first.
- **pop 6 vs pop 7 -- `seq`.** Both class 2, both stamp 9, both **core 4**: every
  earlier field is exhausted and only the schedule counter is left, so seq 1
  before seq 6. **This is the field that makes the order total.** Remove it and
  these two compare equal, the heap picks by its internal arrangement, and the run
  stops being reproducible in a way nothing in the output announces.
- **pop 7 vs pop 8 -- `age` again, at the sentinel.** seq 7 is a *fresh* class-2
  event (`NoRefusal == INT64_MAX`) on **core 0**, the lowest core id in the whole
  set. It still sorts after the stamp-9 events on core 4, because `age` is
  compared before `core`. **A refused request beats a fresh one regardless of core
  id.** This is the v1-to-v3 divergence the plan flagged for sign-off in 3.8, and
  the reason V3's golden log is re-baselined once, deliberately.

One consequence of `age`'s collapse: pops 5, 6 and 7 all tie on stamp 9 in this
fixture, which cannot happen for real class-2 waiters (no two share a stamp, I2).
The fixture ties them on purpose, because `core` and `seq` are **live** for the
other three classes and the comparator has one body for all four.

**Decisions.** B3, B107, B121.

**Traps.** Its name means what it says -- "earlier than". The min-heap inversion
lives at the container, not here (see `EventQueue`). A future editor who "fixes"
the comparator because the queue is a max-heap adaptor breaks every reader of
this function and every oracle written against it.

## `template <typename Payload> struct Event`

**What it is.** One scheduled event: its key, what it is, and what it is about.

**Contract.**

```cpp
template <typename Payload>
struct Event {
    EventKey  key;
    EventKind kind;
    Payload   payload;
};
```

A plain data carrier. `Payload` is a **real type**, stored by value.

**Worked example.** `Payload` is a parameter because at plan unit B2 **the
hierarchy does not exist**. What an event is *about* is a `Request`, an `Mshr`
entry, a core or a tile, and every one of those belongs to plan unit C2 or C3.
Naming a concrete payload here would be this unit deciding a later one's storage.

The two ways to dodge that without a template are both worse:

| shape | why it is worse |
|---|---|
| `void*` | drops the type entirely, so nothing stops a `Request*` being popped as an `Mshr*` -- precisely the accident the whole `Tagged` apparatus exists to prevent |
| an opaque integer handle | looks type-safe and is not: it forces *this* unit to invent a handle table, a numbering and a lifetime rule for entries it knows nothing about. The same decision, taken anyway, hidden behind an `int` |

The ordering -- all this unit owns -- does not depend on the payload at all, which
is what makes the parameter free rather than speculative generality.

**Decisions.** B106.

**Traps.** Because the class is a template, **members are compiled only when
used.** A header-only unit is *not* tested by the library building: a clean build
of `libwcache` proves nothing about `event.h`. Only a test that instantiates it
does. That is decision B33's lesson in C++ form.

## `template <typename Payload> class EventQueue`

**What it is.** The min-heap the engine loop pops, and the total order it pops in.

This is the whole of principle P1: *time is carried by events, never by a loop.*
The engine has no tick and no current cycle of its own. Plan 3.2's loop is

```cpp
while (!queue.empty()) { e = queue.pop_min(); now = e.time; dispatch(e); }
```

and there is nothing else: no horizon, no scan over cores, no condition
re-evaluated on a schedule.

**Contract.**

```cpp
template <typename Payload>
class EventQueue {
public:
    void schedule(SimTime time, EventKind kind, RefusalOrder age, CoreId core, Payload payload);
    Event<Payload> pop_min();
    bool empty() const;
    std::size_t size() const;
    SimTime now() const;
    std::int64_t scheduled() const;
private:
    struct Later { bool operator()(const Event<Payload>& a, const Event<Payload>& b) const
                   { return key_less(b.key, a.key); } };
    std::priority_queue<Event<Payload>, std::vector<Event<Payload>>, Later> q_;
    std::int64_t next_seq_ = 0;
    SimTime now_{0};
};
```

`std::priority_queue` is a **max-heap** (`top()` is the element that compares
*greatest*). The comparator is therefore deliberately reversed -- `key_less(b, a)`
with the arguments swapped -- rather than the key being reversed. `key_less` stays
the plain "earlier than" every other reader expects, and the one inversion lives
at the single point where the container demands it.

The container also **cannot be iterated** -- there is no `begin()`. That is a
feature here: nothing can accidentally read the queue in container order and let
the heap's internal arrangement leak into a result. The only observable ordering
is the pop sequence.

**Decisions.** B106 (header-only template over the payload), B107 (min-heap by
reversing the comparator; `schedule` assigns `seq` and derives the class),
**B121** (determinism is not orderedness -- see the note below).

---

### Methodological note: determinism is **not** orderedness (decision B121)

**This is the most important thing in plan unit B2, and it generalises well past
this file.**

The plan's exit criterion for this unit (Part 7, line 1345) reads:

> total order; two identical runs produce identical event logs

**Those are two criteria of very unequal strength, and the second one alone is
satisfied by a queue that is wrong.**

"Two identical runs produce identical logs" is a statement about
**reproducibility**, and it is invariant under *any* deterministic comparator.
Reverse the comparator and both runs reverse together. The logs still match. The
test still passes.

Three real mutations demonstrate it, and all three are in `mutation_check.sh`:

| mutation | what it does | survives a determinism-only suite? |
|---|---|---|
| `B2 key_less reverses the seq` | the last field becomes `a.seq > b.seq` | **yes** -- every tie at the deepest level flips, identically in both runs |
| `B2 key_less reverses the class` | `Issue` before `Probe` before `Barrier` before `Fill` | **yes** -- 4.6's worked example now reports 221 instead of 111, in both runs |
| `B2 the queue is a max-heap` | the comparator inversion in `Later` is removed | **yes** -- the queue pops the *latest* event first, reproducibly |

The middle one is the alarming one. It inverts D4 ("lookups see this cycle's
fills"), turns every same-cycle hit into a miss and a second fetch, and changes
hit rate, DRAM traffic and `tile_origin` -- that is, **every number the study
reports** -- while passing a criterion the plan states as sufficient. The max-heap
mutation is worse in one respect: `std::priority_queue`'s internal arrangement is
a pure function of the insert sequence, so a max-heap is exactly as reproducible
as a min-heap.

**What kills all three is a separate, independent check**: pop order must equal
sorted order **under an oracle comparator written out from the plan's ordering
table**, not from `event.h`.

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

**The independence is the whole value. If the oracle called `key_less`, every
mutation of `key_less` would move the oracle with it**, and the comparison would
agree with itself while both halves were wrong. That is the same circularity
decision B102 caught in the probe-is-not-an-access test, in comparator form: a
before/after snapshot cannot catch a perturbation that also perturbs the
snapshot.

**What this means for anyone reading a plan criterion.** Line 1345's two clauses
are not a claim and its paraphrase; they are a strong claim and a weak one, and
**the weak one is the memorable half**. An implementer who reads the row and
builds "two runs, `diff` the logs" gets a green suite over a reversed comparator
or a max-heap. The total-order half needs a check with an *external* notion of
correct order -- a hand-written expected sequence or an independently spelled
comparator -- and it must be stated as the load-bearing one.

The rule generalises and is now standing practice in this tree: decision B124
applied it to plan unit B3's soak (an independent model that computes `retire`'s
answers from 3.4's four steps rather than by calling the class), decision B142
applied it across Phase C's fourteen oracles, and decision B146 goes one step
further by perturbing *both* the code and the oracle so the oracle cannot
silently mirror the code.

---

### `void EventQueue::schedule(SimTime time, EventKind kind, RefusalOrder age, CoreId core, Payload payload)`

**What it is.** Puts an event on the heap at `time`, assigning its `seq` from
this queue's own counter and deriving its class from its kind.

**Contract.** Throws `std::logic_error` when `time < now()`, naming both values.
Scheduling **at** `now` is legal and ordinary.

`logic_error` and not `invalid_argument`, because no config value produces it: it
is an engine that computed a time, which decision B27 puts in the
programmer-error tier.

**Two of the five key fields are not parameters, and neither omission is
convenience.**

`seq` **cannot be passed.** Plan 3.6 says it is "a monotonic counter assigned at
*schedule* time", and there is exactly one place that is. If a caller supplied
it, two events could be given the same value, and the effect would be invisible
until exactly the case of `key_less`'s pop 6 versus pop 7, where `seq` is the only
field left. Two events comparing fully equal is precisely where a tie needs
breaking, so a duplicated `seq` is wrong **only** at the moment it matters.
Making it unrepresentable is cheaper than a rule saying "always pass a fresh
counter", and there are seven scheduling sites in plan 3.4 alone.

`class` **cannot be passed either.** It is derived through `class_of` -- see that
entry for what a mis-classed fill costs.

**Worked example.** From the `key_less` fixture: nine `schedule` calls, and the
`seq` column of that table is not an argument to any of them. It is
`next_seq_` counting 0..8.

Scheduling behind `now` is P1 violated:

```cpp
q.pop_min();                                     // now() becomes 100
q.schedule(SimTime{90}, ..., payload);           // logic_error:
                                                 // "time 90 is behind now 100"
```

A min-heap makes `now` non-decreasing only if nothing is inserted into the past.
An event scheduled behind `now` would be dispatched **immediately and out of
order** rather than at the time it names.

**Traps.** `next_seq_` is **per queue** and is never reset. A process-wide
counter would also be deterministic -- and would also be wrong the moment two
queues exist, since seq values from one would interleave with the other's. It is
`int64` for the refusal counter's reason (Q8): a full trace at 256 cores schedules
more than 2^31 events, and a wrapped counter silently reorders the heap.

### `Event<Payload> EventQueue::pop_min()`

**What it is.** The earliest event in the total order, removed from the queue,
and the event whose timestamp becomes `now`.

**Contract.** Throws `std::logic_error("EventQueue::pop_min: the queue is
empty")` on an empty queue. Returns **by value**.

An empty queue is the engine loop's **termination condition** (plan 3.2), so
reaching this call with nothing in it is the loop having been written wrong
rather than a run that ended -- hence a throw rather than a sentinel.

**Worked example.** The nine-pop sequence in the `key_less` entry is a full
`pop_min` trace. After pop 1, `now()` is 90; after pop 2, it is 100 and stays
there.

Returning by value is forced by the container:

```cpp
Event<Payload> e = q_.top();   // top() is a const REFERENCE into the heap
q_.pop();                      // pop() returns void and invalidates it
now_ = e.key.time;
return e;
```

`top()` must be copied out before `pop()` invalidates it. That separation is not
an oversight in the standard library: a `pop()` that returned by value could
throw *after* it had already modified the container, losing the element.

**Traps.** `now_` is updated by `pop_min` and by nothing else, so a caller that
peeks without popping does not advance time -- which is correct, and is why there
is no `top()` on this class.

### `bool EventQueue::empty() const`, `std::size_t EventQueue::size() const`

**What they are.** The heap's occupancy.

**Contract.** Never throw.

**Worked example.** `while (!queue.empty()) { ... }` is plan 3.2's loop condition
in full.

**Traps.** `size()` is `std::size_t` -- the one unsigned quantity in this class,
inherited from the container.

### `SimTime EventQueue::now() const`

**What it is.** The timestamp of the last popped event: P1's `now`.

**Contract.** Never throws. **Zero before the first pop**, which is
`tile_origin[0]` and therefore the earliest time anything can be scheduled at
anyway.

**Worked example.** It is held here rather than in a variable of the engine loop
so that `schedule`'s monotonicity rule has something to check against. Move it to
the loop and the check has to be duplicated at every call site, or dropped.

**Traps.** It is the *last popped* time, not the *next* time. Between the last pop
of one cycle and the first pop of the next it lags.

### `std::int64_t EventQueue::scheduled() const`

**What it is.** How many events this queue has ever been given.

**Contract.** Never throws. It is `next_seq_`, which already exists, so reporting
it costs nothing.

**Worked example.** Part 8 reports the event count and events per simulated
cycle, which is the **measured** form of the cost win over the tick model rather
than the claimed one.

**Traps.** It counts scheduled, not dispatched. `scheduled() - size()` is the
number popped so far.

---

# `native/include/wcache/mshr.h`, `native/src/mshr.cpp`

## `enum class Level : std::uint8_t`

**What it is.** Which level a woken request **re-enters at** (plan 3.5).

**Contract.**

```cpp
enum class Level : std::uint8_t { L1 = 0, L2 = 1 };
```

It is a field on the **request**, not a fact about the wait index the request sat
in.

**Worked example.** The two L2 indices and the two L1 indices are the same code.
A request woken from `l2_mshr.slot_wait` must re-enter **at the L2** and not at
the top of the hierarchy. Re-triage at the L1 would find that request's own
entry, merge the request into itself, and leave it waiting for a fill nobody will
ever request.

**Traps.** `Request::level` is *where to re-enter on wake*, not *where the request
is now*. Invariant I6 ties it to `mshr1`: `r.level == L2 <=> r.mshr1 != null`.

## `enum class WaitReason : std::uint8_t`

**What it is.** Plan 3.7's wait reason, `{SLOT, LINE(l)}`.

**Contract.**

```cpp
enum class WaitReason : std::uint8_t { None = 0, Slot = 1, Line = 2 };
```

**`LINE(l)` carries no line**, and that is deliberate rather than a
simplification.

**Worked example.** A request only ever line-waits on the entry matching **its
own address**, so the `l` of `LINE(l)` is always `r.line`, which the request
already holds. A second copy is a field that can **disagree** with the one beside
it, and there is no reading of the model where the disagreement means anything.
That is decision B89's shape (`InsertResult::evicted` reported by construction)
applied to a tag instead of a flag.

The *reason* itself must survive, and that part is not optional: **two indices,
one population**. A `LINE` waiter woken by an unrelated retire would re-block on
the same condition, be popped again, and the freed slot would never be consumed --
D5's livelock. The two must stay distinguishable by **what releases them**.

**Decisions.** B112.

**Traps.** What actually releases a waiter is **which vector holds it**, not this
field. See `mark_refused` for where the two diverge, and what Part 8's
"reported separately by wait reason" pays for it.

## `struct Request`

**What it is.** One line request travelling the hierarchy (plan 3.3).

**Contract.**

```cpp
struct Request {
    CoreId       core;
    LineId       line;
    BurstIndex   burst;
    bool         demand         = true;
    RefusalOrder refusal        = NoRefusal;
    WaitReason   reason         = WaitReason::None;
    Level        level          = Level::L1;
    Mshr*        mshr1          = nullptr;
    bool         reserved       = false;
    bool         on_wait_index  = false;
};
```

The **first three fields have no defaults**, because the tagged scalars have no
default constructor (decision B2): a defaulted `CoreId` would mean core 0 and a
defaulted `BurstIndex` would mean the first burst of the tile, both of which are
valid values a forgotten initialiser would produce silently.

The rest carry plan 3.3's own defaults, so:

```cpp
Request{CoreId{c}, LineId{l}, BurstIndex{k}}          // a fresh demand request
Request{CoreId{c}, LineId{l}, BurstIndex{k}, false}   // a prefetch
```

Field by field:

| field | promise |
|---|---|
| `demand` | false for a prefetch. Nobody is waiting on it, and at issue it is **dropped** rather than refused (4.6, N16, decision B11) |
| `refusal` | the global counter's value at this request's **first** refusal, not a tick. **Write-once** |
| `reason` | the reason of that first refusal, write-once with it |
| `level` | where to **re-enter on wake** (3.5), not where it is now |
| `mshr1` | the L1 entry this request holds once it has been **forwarded**. Non-owning; the entry outlives the pointer by construction |
| `reserved` | holds a slot-grant reservation handed out by the grant loop (3.8) |
| `on_wait_index` | on a wait index right now -- I5's first half |

**Worked example -- write-once, demonstrated.** `r_s` is refused for a **slot** at
t = 5 and stamped 0 with `reason = Slot`. At t = 16 it is re-refused onto a
**line-wait** index. `mark_refused` finds a stamp already present and changes
nothing. So at t = 16, `r_s.reason == Slot` while `r_s` is sitting in
`E_Y.line_wait`. The stamp stays 0 forever after, which is what makes starvation
freedom provable (I10): the set of requests with a smaller stamp is finite and
never grows.

**Decisions.** B2 (no default constructor on the tagged scalars), B125
(`Request::seq` deliberately not built, escalated to the human), **B134**
(`on_wait_index` added by plan unit C2 to carry I5).

**Traps.**

**`reason` records why a request ENTERED the waiting population, not which index
holds it.** Correctness does not depend on it -- what releases a waiter is which
vector holds it, and the livelock is prevented by the **index split**, which is
structural. But **Part 8 does depend on it**: "wait population reported separately
by wait reason". Under the write-once rule, that report attributes `r_s` to
`Slot` for its whole life, so the two reported populations will not match the two
index depths whenever a request has moved between them. The divergence is
recorded rather than designed around; the fix, if the report is meant to track the
index, is a rule change or a second field, and plan 3.8 explicitly makes `reason`
part of the write-once `mark_refused`.

**`on_wait_index` is put on the REQUEST rather than in the engine** for the reason
I5 was hard to place at all: a request can sit on an index of the L1 file or of
the L2 file, and no one file can see the other's. A bit the request carries is
visible to both, so membership is one fact in one place instead of the engine
reconstructing the population across two files. It is set by `push_line_wait` /
`push_slot_wait` and cleared where a request **leaves** an index -- `retire` for a
line waiter, `collect_grants` for a slot waiter, the only two exits either index
has. The **refusal** is `CacheLevel::triage`'s, one level up.

## `struct Mshr`

**What it is.** One outstanding line (plan 3.3).

**Contract.**

```cpp
struct Mshr {
    LineId line;
    CoreId core;                       // unused at the L2, where entries are not per-core
    bool   demand;
    std::vector<Request*> targets;
    std::vector<Request*> line_wait;
};
```

`targets` and `line_wait` are **public data**, in the tree's plain-struct style,
and are appended to **only through `MshrFile`** -- which is what keeps I3
(`|targets| <= tgts_per_mshr`) in one place. Reading them is the point: the
engine iterates targets at retire and Part 8 reports both depths.

| field | promise |
|---|---|
| `demand` | true once **anything** waiting on this line is a demand request. **Mutable**, which is 4.6's promotion path |
| `targets` | the committed subentries, satisfied **directly** by the fill with no re-triage (3.7). The **primary occupies the first slot** |
| `line_wait` | requests that arrived after the target list filled, waiting on **this** entry's line (D5). Released by this entry retiring and by nothing else, **all of them at once**, as hits |

**Worked example.** At the running configuration below (`tgts_per_mshr == 2`),
`E_Y` after a primary, one merge and one refusal:

```
E_Y = { line = Y, core = 5, demand = true,
        targets   = [ &r_t, &r_u ],
        line_wait = [ &r_v ] }
```

**Decisions.** B110 (the primary occupies `targets[0]`; no separate `primary`
field), B111 (`targets` holds `Request*` at **both** levels), B114 (`add_target`
owns the bound and the promotion).

**Traps.**

**`targets` never drains incrementally**, so nothing is ever promoted from
`line_wait` into `targets`: the whole set resolves at retire. In a read-only cache
a target list has no partial completion, and a model that promoted on a free
target slot would be modelling a drain that cannot happen (3.7).

**At the L2, plan 3.4 stores the waiting L1 *entry* as a target**, which reads as
two different element types for one field. By I6b they are the **same object**:
the map from an L2 waiter to its `mshr1` is injective, so no two requests on any
L2 wait index share an L1 entry. One storage type rather than two turns that
bijection from a structural assumption into something a fixture can check, and
the engine reaches the entry with `r.mshr1` at the one site that needs it
(decision B111).

## `class RefusalCounter`

**What it is.** The global stamp source of plan 3.8. **One per run**, shared by
every `MshrFile`.

**Contract.**

```cpp
class RefusalCounter {
public:
    RefusalOrder next();               // the next stamp; the counter advances
    std::int64_t issued() const;       // how many have been issued
private:
    std::int64_t next_ = 0;
};
```

Neither throws. Stamps are `0, 1, 2, ...`, monotonic, never reused, never reset.
64-bit (plan Q8, closed): a run's total refusals over a full trace at 256 cores
can exceed 32 bits, and a wrap would silently reorder the FIFO.

**One per run, not one per file**, and that is the design: a request refused at
the L1 and again at the L2 keeps its original stamp and so carries L2 seniority
reflecting how long it has **genuinely** waited.

**Worked example.**

```cpp
RefusalCounter counter;
counter.issued();          // 0
counter.next();            // RefusalOrder{0}   -- the first stamp of the run
counter.issued();          // 1
counter.next();            // RefusalOrder{1}
```

`issued()` is also the value of the next stamp. V18 asserts that every waiter's
stamp is written exactly once and is unique across the run; this is the count
that check compares against.

**Traps.** Two counters would break the one property everything else rests on. If
the L1 and the L2 each had their own, two requests could share a stamp, the wake
sort would tie, and I2's uniqueness -- which is why `retire`'s `stable_sort`
costs nothing -- would fail silently.

## `inline bool is_prefetch_at_issue(const Request& r)`

**What it is.** True for a prefetch that is still **at issue** -- which is where
4.6's four differences apply and the only place a request may be dropped.

**Contract.**

```cpp
inline bool is_prefetch_at_issue(const Request& r) {
    return !r.demand && r.mshr1 == nullptr;
}
```

Never throws. **One spelling**, read by `has_slot`, by both wait pushes, and by
`CacheLevel::triage`, so the four cannot drift into disagreeing about what a
prefetch is.

**Worked example.** The distinction is `mshr1`, and it is I6 read as a fact
rather than as a check: a request holds an L1 MSHR entry exactly when it has been
**forwarded**, which is exactly when it is at the L2.

| request | `demand` | `mshr1` | `is_prefetch_at_issue` |
|---|---|---|---|
| fresh demand request at the L1 | true | null | false |
| fresh prefetch at the L1 | false | null | **true** |
| forwarded prefetch, now at the L2 | false | non-null | **false** |
| forwarded demand request | true | non-null | false |

**So this is false for every request the L2 ever sees.**

Why the L2 is different is 4.6's own last table row, "identical below this point".
A prefetch **at the L1** has nothing behind it, which is why it must be dropped
rather than queued: 4.1's argument is that a wait index is a view over structures
that already exist, and a prefetch waiting at the L1 would occupy a selection set
with **no entry behind it**. A prefetch **at the L2** has exactly the backing 4.1
asks for -- it holds an L1 entry, across the whole downstream round trip. Dropping
it there would also be an operation the plan never defines, since the L1 entry it
already took would then be unfillable and the run would deadlock at D12's check.

**Decisions.** **B135** -- this is a **widening** of plan unit B3's original
contract, forced by the review: the two pushes narrowed their refusal from
`!r.demand` to `is_prefetch_at_issue(r)`, so a **forwarded** prefetch may now be
queued.

**Traps.** `!r.demand` alone is the older, wrong spelling and it is still the one
in the narrative record's section 12 and section 14. Anything reading
`phaseB-EXPLAIN.md` for this predicate will find the pre-B135 form.

## `void mark_refused(Request& r, WaitReason reason, RefusalCounter& counter)`

**What it is.** Plan 3.8's `mark_refused`: stamps a request at its **first**
refusal, at any level.

**Contract.**

```cpp
void mark_refused(Request& r, WaitReason reason, RefusalCounter& counter) {
    if (r.refusal == NoRefusal) {
        r.refusal = counter.next();
        r.reason  = reason;
    }
}
```

Never throws. **Write-once**, and it writes **both** fields together. Idempotent:
a second call on a stamped request changes nothing and consumes no stamp.

A **free function** rather than a method, because it belongs to neither the
counter nor the file: it is the rule joining them. `MshrFile` calls it on every
push onto a wait index, so the pairing cannot drift.

**Worked example.** Continuing `r_s`:

```
t = 5   mark_refused(r_s, Slot, counter)
        r_s.refusal == NoRefusal  ->  r_s.refusal = counter.next() = 0
                                      r_s.reason  = Slot

t = 16  mark_refused(r_s, Line, counter)
        r_s.refusal == 0, which is NOT NoRefusal  ->  DOES NOTHING
        stamp stays 0 ; reason stays Slot
```

`reinject` never touches it either. So a request enters the waiting population
exactly once and is served in stamp order forever after, however many times it is
re-refused and whichever index holds it. That is FIFO by first refusal, and it is
what makes starvation freedom provable: if the stamp were reset on a wake, an aged
request would lose to every fresh arrival at high load, forever (I10).

**Decisions.** B115 (the pushes stamp the request themselves).

**Traps.** A push that skipped the stamp would put an **unstamped** request into a
population ordered by stamp, where `NoRefusal == INT64_MAX` sorts it **last
forever**. That is a starvation bug produced by a *missing call*, and I10's proof
would not hold. Calling `mark_refused` inside the two pushes is what makes the
omission unrepresentable.

## `inline bool key_less(const Request& a, const Request& b)`

**What it is.** Plan 3.8's arbitration key, `key(r) = (r.refusal == NONE,
r.refusal)`, collapsed to one compare.

**Contract.**

```cpp
inline bool key_less(const Request& a, const Request& b) { return a.refusal < b.refusal; }
```

Never throws. A strict total order over the requests actually present, because
stamps are unique across the run (I2).

**Worked example.** `NoRefusal` is `INT64_MAX` (decision B3), so a fresh request
sorts **after** every refused one under plain `<`, and the refused bit is not a
second field that could disagree with the counter beside it:

| a.refusal | b.refusal | `key_less(a, b)` |
|---|---|---|
| 0 | 1 | true -- older first |
| 1 | 0 | false |
| 0 | `NoRefusal` | true -- refused beats fresh |
| `NoRefusal` | `NoRefusal` | false -- two fresh requests tie, but neither is ever on a wait index |

**Decisions.** B3.

**Traps.** This is a **different function** from `event.h`'s `key_less`, which
takes an `EventKey` and has five fields. They are overloads of one name in one
namespace, distinguished only by argument type. Both are correct where they are
used; a reader skimming for "the comparator" will find whichever the compiler
would.

## `struct RetireResult`

**What it is.** What a retire hands back to the engine, in the **two groups** plan
3.4 separates.

**Contract.**

```cpp
struct RetireResult {
    std::vector<Request*> targets;   // satisfied directly by the fill
    std::vector<Request*> wake;      // reinjected, in this order
};
```

`retire` **replaces** both, rather than appending, so a caller may reuse one
buffer across retires.

**Two vectors and not one**, because the two groups are released differently and
acting on them alike is D5's livelock in the other direction: a **target** is
satisfied directly by the fill and never re-triages, while a **woken waiter** goes
back through its level's port and re-probes (3.7, N5).

**Worked example.**

| group | members | what the engine does with them |
|---|---|---|
| `targets` | the primary first, then the merges in merge order | satisfied **directly**, no re-triage: at the L2 an `E_L1Fill` each, at the L1 a `core_line_done` each |
| `wake` | this entry's line waiters, **all of them**, plus the slot waiters the grant loop could pay for, in **one key-ordered list** | reinjected in this order; each reserves a port and re-probes |

**The merge is mandatory rather than tidy, and the sort is not redundant.**
Reinjection reserves a port, so iterating the two indices separately would stagger
the wake by loop order instead of by age. And a wait set is **not** already in age
order, because a slot waiter can outlive the allocation of an entry it later
merges onto and arrive carrying an older stamp than what is already there -- plan
3.8's counterexample, walked under `MshrFile::retire` below.

**Decisions.** B109 (`retire`'s internal order), B119 (`stable_sort`).

**Traps.** `targets` is assigned rather than swapped, so a caller reusing one
buffer keeps its capacity. Swapping would hand the caller's old buffer to the
entry that is about to be destroyed.

## `class MshrFile`

**What it is.** The outstanding lines of **one** cache level, and who is waiting
on them: a CAM over outstanding line addresses, bounded by capacity.

One class for both levels. Plan 2.2's "L1 MSHR file" row and 2.3's "L2 MSHR file"
row name the same structure with different capacities, and 3.4's two triage
functions are, in the plan's own words, of "identical shape".

**What this unit deliberately does NOT do**, and the boundary is the unit's
definition -- Phase B is *timing primitives: clock exists, hierarchy does not*: it
**never reserves a port, never schedules an event, and never knows which level it
is.** `retire` therefore reports **who** was satisfied and **who** wakes, in
order, and the engine decides what that means at its level. Two consequences are
load-bearing later: this file cannot violate P2 by predicting a time, because it
holds no clock; and the merge-and-sort that I7b rests on happens **here, once**,
rather than in each caller.

**Contract.**

```cpp
class MshrFile {
public:
    MshrFile(std::int32_t capacity, std::int32_t tgts_per_mshr,
             std::int32_t demand_reserve, RefusalCounter& counter);
    Mshr* find(LineId line);
    bool  has_slot(const Request& r) const;
    Mshr& allocate(LineId line, Request& primary);
    bool  add_target(Mshr& e, Request& r);
    void  push_line_wait(Mshr& e, Request& r);
    void  push_slot_wait(Request& r);
    bool  release_reservation(Request& r);
    void  retire(Mshr& e, RetireResult& out);
    void  collect_grants(std::vector<Request*>& out);
    std::int32_t capacity() const;
    std::int32_t tgts_per_mshr() const;
    std::int32_t demand_reserve() const;
    std::int32_t live() const;
    std::int32_t reserved() const;
    std::int32_t slot_wait_depth() const;
private:
    std::int32_t capacity_, tgts_per_mshr_, demand_reserve_;
    std::int32_t reserved_ = 0;
    RefusalCounter& counter_;
    std::unordered_map<LineId, Mshr> entries_;
    std::vector<Request*> slot_wait_;
};
```

Entries are allocated on a primary miss and freed on fill **arrival**, held
across the whole downstream round trip (2.2). That is what makes L1 MSHR
occupancy mean the full round trip **including L2 queueing delay** (4.2), and it
is what makes the L2's wait sets free.

**The wait indices hold `Request*` and nothing else**, which is principle P5: *a
request that is refused is already held somewhere.* At the L2 it is held by its
own L1 MSHR entry, at the L1 by its core's outstanding-burst registers. These
vectors are **selection sets over structures the engine already owns**. Copying a
refused request into a buffer here would have invented hardware, and 4.1's bound
would become an argument about simulator memory instead of about credits -- which
is precisely the v1 error the plan corrected.

**The running configuration for every worked example below**, one L2 file:

```cpp
RefusalCounter counter;                     // issues 0, 1, 2, ... ; NoRefusal is INT64_MAX
MshrFile f(/*capacity=*/4, /*tgts_per_mshr=*/2, /*demand_reserve=*/1, counter);
```

so the prefetch budget is `capacity - demand_reserve == 3`, and an entry admits
its primary **plus one** later merge.

**Decisions.** B108 (constructor validation order), B109 (`retire`'s internal
order), B110, B111, B112, B113, B114, B115, B116, B117, B119, B120, B134, B135,
B136.

**Traps (class-wide).**

**`std::unordered_map` is never iterated, and that is a deliberate discipline.** A
hash map's iteration order is unspecified and may differ between library versions,
builds, or insertion histories. In a simulator whose exit criterion is
bit-identical re-runs, letting that order reach a result is a reproducibility bug
**that no test failure announces**. So every read of `entries_` is a lookup by
line or a `size()`. If a later unit ever needs to walk the file, it must sort what
it walks. (Decision B132 applies the same rule at plan unit C4: back-invalidation
walks a `std::vector` indexed by core id, **never** an unordered container,
because that walk order is observable in the event log.)

**Node-based is the requirement, not the hashing.** `Request::mshr1` and every
`Mshr&` handed to a caller must stay valid while other entries are allocated and
retired around them. `std::unordered_map` guarantees exactly that -- a rehash moves
*pointers*, not nodes -- so an `mshr1` taken at cycle 0 still points at a live
entry when its fill lands 110 cycles later, during which a dozen other lines were
allocated and retired. A `std::vector<Mshr>` reallocating would leave every held
pointer dangling; an index instead would work but replaces a pointer whose meaning
is fixed with an index whose meaning depends on what the vector does to erased
slots -- a policy this class would then have to invent and document (decision
B117).

**This class enforces neither I5 nor the dangling-`mshr1` rule.** It **records**
wait-index membership on `Request::on_wait_index`; the **refusal** is
`CacheLevel::triage`'s, the only code that sees both files (decision B134). And
`retire` erases the `Mshr` without walking the requests that pointed at it to null
their `mshr1` -- it cannot, since it holds no list of them. Decision B137 closes
that at both ends in the engine: `on_l1_fill` clears `mshr1` and resets the level
on every target **before** retire, and `Engine::release` refuses a request still
carrying an `mshr1`, a reservation, or an `on_wait_index`.

### `MshrFile::MshrFile(std::int32_t capacity, std::int32_t tgts_per_mshr, std::int32_t demand_reserve, RefusalCounter& counter)`

**What it is.** Builds a file from its three config numbers and binds it to the
run's single stamp source.

**Contract.** All three are config fields (`l1_mshrs` / `l2_mshrs`,
`l1_tgts_per_mshr` / `l2_tgts_per_mshr`, `l1_demand_reserve` /
`l2_demand_reserve`, plan 2.5b), so every rejection is
`std::invalid_argument`, naming the offending value.

**The order of the checks is load-bearing and is therefore stated rather than
left to be inferred** (decision B108, following B62's precedent):

1. **`capacity >= 1`.** A file that can hold nothing forwards nothing, and every
   check after this one compares against it.
2. **`tgts_per_mshr >= 1`.** The primary occupies a target slot, so a zero here is
   an entry that cannot record its own allocator.
3. **`demand_reserve >= 0`.**
4. **`demand_reserve <= capacity`**, which is a **relation between two fields** and
   only means anything once both have been accepted.

**Positivity first, because everything after compares against it; the cross-field
relation last, because it means nothing until both operands are known good.** A
grid point that is wrong in several places reports the most fundamental failure
rather than a derived one.

`counter` is held **by reference**: one counter per run, shared by both files.

**Worked example.**

```cpp
MshrFile f(4, 2, 1, counter);     // ok -- the running configuration
MshrFile f(4, 2, 4, counter);     // ok -- demand_reserve == capacity, the DEFAULT
MshrFile f(0, 2, 1, counter);     // invalid_argument: "capacity must be >= 1, got 0"
MshrFile f(0, 0, -1, counter);    // names CAPACITY, not tgts_per_mshr and not demand_reserve
MshrFile f(4, 2, 5, counter);     // invalid_argument: "demand_reserve 5 exceeds the
                                  //   file's capacity of 4 entries"
```

**`demand_reserve == capacity` is ACCEPTED, and it is the default configuration
rather than an edge case.** `l1_demand_reserve` defaults to `lines_per_burst`, so
at `l1_mshrs == lines_per_burst` the prefetch budget is exactly **zero** and
prefetching is off however `prefetch_distance` is set (4.2). A reserve *larger*
than the file is refused because it would make the budget **negative**, which is
not "prefetching is off" but a bound that reads backwards.

**Decisions.** B108, B116.

**Traps.**

**D1's stricter rule is not this constructor's.** D1 says `demand_reserve >=
mshrs` throws -- but that is a rule about a config that **also** sets
`prefetch_policy = next_burst`, which is a field this class never sees. Adding it
here would refuse the default demand-only configuration.

**`tgts_per_mshr = 1` is legal and permits no merging at all**, because the
primary occupies `targets[0]`. See `add_target`.

### `Mshr* MshrFile::find(LineId line)`

**What it is.** The entry for `line`, or null when there is none. Plan 3.4's
`F.entries.find`.

**Contract.** Never throws. Returns a pointer into `entries_` that stays valid
across other allocations and retires (the node-stability guarantee above).

**Worked example.** It is the **second** step of the probe order -- after the array
and before the next level -- and the step that makes a secondary miss cost **zero
downstream traffic**:

```
find(Y) -> nullptr     no entry: this is a primary miss, allocate and forward
find(Y) -> &E_Y        an entry exists: merge or line-wait, no port, no event,
                       no second fetch                       (D3, "subscribes,
                                                              computes nothing")
```

**Traps.** Non-const, deliberately: the caller mutates the entry it finds (via
`add_target` / `push_line_wait`). There is no const overload, so a const `MshrFile&`
cannot probe -- which is correct, since probing is not a read.

### `bool MshrFile::has_slot(const Request& r) const`

**What it is.** Whether `r` may allocate an entry now. Plan 3.4's `has_slot(F, r)`.

**Contract.**

```cpp
bool MshrFile::has_slot(const Request& r) const {
    if (r.reserved) return true;
    const std::int32_t free = capacity_ - live() - reserved_;
    return is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;
}
```

Never throws. `const`.

**Three answers in one predicate:**

1. **A grantee is admitted unconditionally.** The credit it is about to spend is
   the one `collect_grants` set aside for it, already counted in `reserved_`.
2. **A demand request** (and a **forwarded** prefetch -- see below) needs one free
   credit.
3. **A prefetch at issue** needs one **more** than `demand_reserve`, so it can
   never take the last `demand_reserve` entries.

**Worked example.** At `capacity 4, demand_reserve 1`:

| `live() + reserved_` | `free` | demand admitted? | prefetch-at-issue admitted? |
|---|---|---|---|
| 0 | 4 | yes | yes (`4 > 1`) |
| 1 | 3 | yes | yes (`3 > 1`) |
| 2 | 2 | yes | yes (`2 > 1`) |
| **3** | **1** | **yes** (`1 > 0`) | **no** (`1 > 1` is false) |
| 4 | 0 | no | no |

So a prefetch can hold **at most 3 entries**, which is `capacity -
demand_reserve` exactly, and **the last entry is always reachable by a demand
request**. That is 4.6's guarantee: prefetching can **delay** demand but can never
**starve** it (decision B12).

**The first branch is the reservation system working.** Without it, a grantee
would be refused **by its own reservation**: at `live 3, reserved 1`, `free`
computes to 0 for the very request that reservation was made for.

**Decisions.** B12, B116, **B135**.

**Traps.**

**The reserve applies to a prefetch AT ISSUE only.** A prefetch that has already
been forwarded holds an L1 entry and is a fetch this file cannot cancel, so
refusing it here would **strand that entry** rather than save a credit. That is
decision B135's widening, and it is the reason the predicate is
`is_prefetch_at_issue(r)` and not `!r.demand`.

**Plan 4.6's prose and this code disagree by exactly one case, and the code is
right.** 4.6's refusal table says "fewer than `demand_reserve` entries left →
drop", which read literally is `free < demand_reserve`; the code refuses at
`free <= demand_reserve`.

| | refuses a prefetch when | at `capacity 4, demand_reserve 1` | prefetch may hold |
|---|---|---|---|
| 4.6's prose | `free < 1` | only at `free == 0` | up to **4** entries |
| the code | `free <= 1` | at `free == 1` and `free == 0` | up to **3** entries |

Under the prose, a prefetch takes the **last** entry -- the exact case the reserve
exists to prevent -- and `demand_reserve` becomes inert at every value. The code
matches 4.2's budget (`l1_mshrs - l1_demand_reserve`) exactly. This is a recorded
plan erratum in the dangerous direction: left uncorrected, the next reader
reconciles them by changing the code.

### `Mshr& MshrFile::allocate(LineId line, Request& primary)`

**What it is.** Allocates the entry for `line` with `primary` as its **first**
target, and spends `primary`'s reservation if it held one.

**Contract.** Throws `std::logic_error` when:

- `line` already has a live entry -- I1, at most one live `Mshr` per line per
  level; or
- `has_slot(primary)` is false.

Both are **caller errors**: plan 3.4 checks `find` and `has_slot` first, in that
order, which decision B27 puts in the programmer-error tier. A throw and not an
assert, because a second entry for one line **double-fetches** it and a silently
over-full file reports an occupancy the sweep is measuring.

Returns a reference that stays valid across other allocations and retires.

**Worked example.**

```cpp
Mshr entry{line, primary.core, primary.demand, {}, {}};
entry.targets.push_back(&primary);          // the primary IS targets[0]

if (primary.reserved) {                     // spent here, not by a second call
    primary.reserved = false;
    --reserved_;
}
return entries_.emplace(line, std::move(entry)).first->second;
```

The refusal message carries the arithmetic *and* the prefetch rule, because at
`demand_reserve > 0` a prefetch is refused **while free entries remain**, and a
message reporting only the counts would read as arithmetic that does not add up:

```
MshrFile::allocate: no free entry: 3 live plus 1 reserved of 4,
                    and a prefetch may not take the last 1 entries
```

**Decisions.** B110 (the primary occupies `targets[0]`), B113 (`allocate` spends
the reservation itself).

**Traps.**

**The primary occupies `targets[0]`, so `tgts_per_mshr = 1` permits no merging at
all.** The allocating request is a **target**, not a separate field beside the
target list, and three things rest on that:

- **4.1's capacity bound only works this way.** The per-entry L2 bound is
  `|e.line_wait| <= n_cores - l2_tgts_per_mshr`, which counts the primary as one
  of the `tgts_per_mshr`. Put the primary in its own field and the bound is off by
  one, in the direction that **under-reports** the wait depth.
- **It matches gem5's meaning of the word** (Appendix B), which is the vocabulary
  anyone reviewing this will arrive with.
- **The primary is satisfied by the fill through the same loop as every later
  merge**, so there is no second path that could satisfy it differently, and
  `retire` needs no special case for it.

The consequence a caller must hold: at `tgts_per_mshr == 1` the entry is full the
moment it exists, so **every** secondary miss line-waits and nothing ever merges.
At the running configuration's `tgts_per_mshr == 2` it is the primary plus
**one**.

**Folding the reservation spend in removes a pairing a caller can forget.** The
plan writes it as a separate `consume_reservation(r, F)` call after **every**
`allocate`, at both levels, with no exception. The cost of forgetting it is not a
crash: **a leaked reservation is a credit the file never hands back.** `reserved_`
stays permanently one higher, so `collect_grants` stops one waiter short **for the
rest of the run**, and the symptom is a stall that gets attributed to the MSHR
bound.

### `bool MshrFile::add_target(Mshr& e, Request& r)`

**What it is.** Merges `r` onto `e` as a committed subentry, and promotes `e` to a
demand entry if `r` is a demand request.

**Contract.**

```cpp
bool MshrFile::add_target(Mshr& e, Request& r) {
    if (as_count(e.targets.size()) >= tgts_per_mshr_) return false;
    e.targets.push_back(&r);
    e.demand = e.demand || r.demand;
    return true;
}
```

Never throws. Returns **false, changing nothing**, when the target list is already
at `tgts_per_mshr` -- which is the caller's signal to line-wait instead (3.4's
`BLOCKED_TARGETS`). Returning false *and changing nothing* is what lets the caller
fall through to `push_line_wait` without an undo.

The bound lives here so I3 cannot be violated by a caller that checked it and then
pushed anyway, and the promotion lives here so 4.6's late-prefetch path cannot be
forgotten at one of its two call sites in plan 3.4.

**Worked example -- the promotion truth table.**

| `e.demand` before | `r.demand` | `e.demand` after | case |
|---|---|---|---|
| false | **true** | **true** | **the promotion**: the core's own demand request merges onto a prefetch entry that started early but not early enough |
| true | true | true | ordinary secondary miss |
| true | false | **true** | a prefetch merges onto a demand entry, **unchanged** -- the half a naive assignment gets wrong |
| false | false | false | prefetch onto prefetch |

**Idempotence is a property of `||` itself**: `(x || y) || y == x || y`, so
applying the promotion a second time cannot change anything, whatever order the
merges arrive in and however many of them there are. **Nothing has to check
whether the promotion already happened**, and there is no "promoted" flag that
could disagree with `e.demand`.

**Decisions.** B114.

**Traps.**

**The bug this shape forecloses is the third row.** Written as `e.demand =
r.demand` -- an assignment one character shorter, and the spelling a hurried edit
reaches for -- a prefetch merging onto a **demand** entry would silently **demote**
it. The line would still be fetched and the targets still satisfied, so nothing
would fail; what would change is that a demand entry would be reported as a
prefetch entry, and any rule keyed on `e.demand` (4.6's statistics split of timely
versus late versus wasted) would attribute a demand fetch to the prefetcher.

### `void MshrFile::push_line_wait(Mshr& e, Request& r)`

**What it is.** Registers `r` as waiting on `e`'s line (3.4's `BLOCKED_TARGETS`),
stamping its first refusal on the way in.

**Contract.** Throws `std::logic_error("MshrFile::push_line_wait: a prefetch is
dropped, never queued (N16)")` when `is_prefetch_at_issue(r)`.

Sets `r.on_wait_index = true` and does **not** check it. Calls `mark_refused(r,
WaitReason::Line, counter_)` before the push.

**Worked example.** Core 7's `r_v` wants Y, whose target list is full:

```
find(Y)            -> &E_Y
add_target(E_Y, r_v):
    targets.size() == 2  >=  tgts_per_mshr 2  -> returns FALSE, changes nothing
push_line_wait(E_Y, r_v):                                (BLOCKED_TARGETS)
    is_prefetch_at_issue(r_v) is false -> no throw
    mark_refused(r_v, Line, counter) -> r_v.refusal = 1, r_v.reason = Line
    r_v.on_wait_index = true
E_Y.line_wait = [ r_v(stamp 1) ]
```

**Decisions.** B115, B134, **B135**.

**Traps.** See `push_slot_wait` -- both traps are shared.

### `void MshrFile::push_slot_wait(Request& r)`

**What it is.** Registers `r` as waiting for **any** free entry (3.4's
`BLOCKED_POOL`), stamping its first refusal on the way in.

**Contract.** Throws `std::logic_error("MshrFile::push_slot_wait: a prefetch is
dropped, never queued (N16)")` when `is_prefetch_at_issue(r)`.

Sets `r.on_wait_index = true`. Calls `mark_refused(r, WaitReason::Slot,
counter_)` before the push. The index has **no depth limit** -- it is a selection
set, bounded by the credit supply (4.1).

**Worked example.** At t = 5, with the file full, core 4's `r_s` wants line Y:

```
find(Y)            -> nullptr
has_slot(r_s)      -> free = 4 - 4 - 0 = 0 ; demand -> 0 > 0 -> FALSE  (BLOCKED_POOL)
push_slot_wait(r_s):
    is_prefetch_at_issue(r_s) is false -> no throw
    mark_refused(r_s, Slot, counter):
        r_s.refusal == NoRefusal  ->  r_s.refusal = counter.next() = 0
                                      r_s.reason  = Slot
    r_s.on_wait_index = true
    slot_wait_ = [ r_s(stamp 0) ]
```

**Stamp 0 is the first stamp of the run.** `counter.issued()` is now 1.

**Decisions.** B115, B134, B135.

**Traps (shared with `push_line_wait`).**

**The drop rule is unrepresentable in this class, not merely documented.** A
refused prefetch at issue is **dropped**, never queued (4.6, N16, decision B11),
and I15 states it as an invariant. Making it a throw rather than an assert or a
comment means **there is no sequence of calls that puts a prefetch-at-issue onto a
wait index.** That is worth two lines because of what the rule holds up: 4.1's
entire bound is that the waiting population stays backed **one-for-one by demand
credits**, so every waiter has a real L1 MSHR entry or a real core burst register
behind it, which is why the wait sets have no depth limit to design. A prefetch
permitted to wait would occupy a selection set with **nothing behind it**, and
4.1's argument would collapse from a hardware statement into a simulator-memory
statement.

**Neither push checks `on_wait_index`; both set it.** I5's refusal belongs to
`CacheLevel::triage`, the only code that pushes in a run and the only code that
sees **both** files. Keeping the refusal out of here also keeps this class able to
express a state a fixture may want and the engine cannot reach (decision B134).

**A request first refused for a slot and later re-refused onto a line-wait index
still reports `Slot`.** See `mark_refused` and `Request::reason`.

### `bool MshrFile::release_reservation(Request& r)`

**What it is.** Releases a grant `r` turned out not to need, because it re-triaged
into a hit or a merge (plan 3.8).

**Contract.**

```cpp
bool MshrFile::release_reservation(Request& r) {
    if (!r.reserved) return false;
    r.reserved = false;
    --reserved_;
    return true;
}
```

Never throws. A request that held no reservation is **not an error** -- plan 3.4
calls this on **every** hit and merge whether or not one was held.

Returns **true when a credit was actually freed**, so the caller knows to run the
grant loop again and hand it to the next waiter.

**It does not re-grant by itself**, because granting **reinjects**, and
reinjection reserves a **port**, which is the hierarchy this unit does not have
and must not acquire.

**Worked example.** At t = 16, `r_s` re-probes holding its grant and finds an
entry for Y that did not exist when it went to sleep:

```
find(Y)                     -> &E_Y
release_reservation(r_s)    -> r_s.reserved was true
                               r_s.reserved = false ; reserved_ 1 -> 0 ; returns TRUE
```

The `true` tells the caller a credit is now free, and plan units C1 and C2 answer
it by calling `collect_grants` themselves.

**Decisions.** B120 (returns `bool` rather than re-granting), B136
(`collect_grants` made public so the caller can act on that `bool`).

**Traps.** Ignoring the return value is a silent capacity loss of exactly one
credit, held until the next unrelated retire happens to run the grant loop. It
does not crash, does not violate I4, and presents as a longer wait queue.

### `void MshrFile::collect_grants(std::vector<Request*>& out)`

**What it is.** Pops as many slot waiters as there are free credits, **oldest
first**, reserving one credit for each. Plan 3.8's `collect_grants`.

**Contract.**

```cpp
void MshrFile::collect_grants(std::vector<Request*>& out) {
    while (live() + reserved_ < capacity_ && !slot_wait_.empty()) {
        const auto oldest = std::min_element(
            slot_wait_.begin(), slot_wait_.end(),
            [](const Request* a, const Request* b) { return key_less(*a, *b); });
        Request* r = *oldest;
        slot_wait_.erase(oldest);
        r->on_wait_index = false;
        r->reserved      = true;
        ++reserved_;
        out.push_back(r);
    }
}
```

Never throws. **APPENDS** to `out`; it does not replace, and it does not inject --
injection reserves a port and this class has no hierarchy.

**Terminates** because every iteration strictly increases `reserved_` while the
loop's own bound is fixed (I7).

One of the **two** places a request leaves a wait index, so one of the two places
`on_wait_index` is cleared.

**Public rather than private**, which it was at plan unit B3, because **a retire is
not the only thing that frees a credit.** Plan 3.8: "a grantee that turns out not
to need its slot releases the reservation, immediately granting the next waiter."
`release_reservation` returns true at exactly that moment. With this private, plan
units C1 and C2 could not re-run the loop, and the freed credit would sit unspent
until the next unrelated retire.

**Worked example.** At t = 6, line A retires, taking `live()` from 4 to 3:

```
collect_grants(out.wake):
    live 3 + reserved 0 < capacity 4, slot_wait not empty
    min_element under key_less  ->  r_s (stamp 0, the only member)
    slot_wait_.erase(oldest)
    r_s.on_wait_index = false
    r_s.reserved      = true ;  reserved_ = 1
    out.wake.push_back(&r_s)
    next iteration: live 3 + reserved 1 < 4 is FALSE -> stop
```

**Decisions.** B120, **B136**.

**Traps.**

**`std::min_element` under 3.8's key, not a pop from the front.** The index is
**not in age order**, because a slot waiter can outlive the allocation of an entry
it later merges onto and be pushed back carrying an **older** stamp than what is
already there -- plan 3.8's counterexample, walked under `retire` below. Taking the
front would grant the wrong request in exactly that case, **and the sort in
`retire` would then be ordering a wake list that already had the wrong members in
it.** A sort cannot repair a wrong selection.

**Grant is reservation-based rather than optimistic**, which is why `reserved_`
exists at all: a wake never produces a thundering herd racing for one freed slot.

### `void MshrFile::retire(Mshr& e, RetireResult& out)`

**What it is.** Retires `e`: its targets are reported as satisfied, the entry is
erased, and everything that wakes is collected and sorted into one key-ordered
list.

**Contract.** Throws `std::logic_error("MshrFile::retire: line N is not a live
entry of this file")` when `e` is not an entry of **this** file -- checked by
identity, not just by line.

`out` is **REPLACED**, not appended to, so a caller may reuse one buffer across
retires. `out.targets` is assigned rather than swapped, so that reuse keeps its
capacity.

**The internal order is load-bearing and is plan 3.4's:**

1. **Copy the targets out**, before the entry is erased.
2. **Take the line waiters, all of them** -- they need no slot and will all hit,
   since the line is resident by the time they re-probe. Clear their
   `on_wait_index` here, since this is the exit.
3. **ERASE the entry, and only then run the grant loop**, so the credit this
   retire freed is the one the loop can hand out.
4. **`stable_sort`** the merged list by 3.8's key.

**Worked example -- a full miss, end to end.** The running configuration, with
4.6's worked-example latencies (`l2_latency = 10`, `l2_miss_latency = 100`,
`ii = 1`) so the arithmetic is checkable against the plan.

**t = 0 -- four allocations fill the file.** Core 0's `r0` for line X reaches the
L2.

```
find(X)            -> nullptr
has_slot(r0)       -> r0.reserved == false
                      free = capacity 4 - live 0 - reserved 0 = 4
                      not a prefetch at issue -> free > 0 -> TRUE
allocate(X, r0)    -> Mshr{ line=X, core=0, demand=true, targets=[&r0], line_wait=[] }
                      live() == 1
```

Three other cores do the same for lines A, B, C. **`live() == 4`, `reserved_ ==
0`, so `free == 0`.**

**t = 5 -- `r_s` is refused for want of any entry.** See `push_slot_wait`'s worked
example. `slot_wait_ = [ r_s(stamp 0) ]`.

**t = 6 -- line A retires, and the grant loop pays for one waiter.**

```
retire(A_entry, out):
  1. out.targets = A_entry.targets            (copied BEFORE the erase)
     out.wake    = A_entry.line_wait          (empty here)
  2. entries_.erase(it)                       live() 4 -> 3
  3. collect_grants(out.wake)                 -> grants r_s, reserved_ = 1
  4. stable_sort(out.wake)                    one element, nothing to do
```

The engine reinjects `r_s`: `l2_bank.reserve(6)` returns 6, and it schedules
`E_L2Probe(r_s)` at `6 + l2_latency == 16`. **`r_s` re-probes at 16, not at 6.**
That gap is what produces the counterexample below.

**t = 7 and t = 9 -- a fresh request allocates Y, and a second merges onto it.**
`r_s` is asleep in the queue holding a reservation. Line B also retires at t = 7,
taking `live()` to 2 and leaving `free = 4 - 2 - 1 = 1`. Then core 5's `r_t`
arrives for Y:

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
fetch.

**t = 12 -- a third requester is refused onto the line-wait index.** See
`push_line_wait`'s worked example. `E_Y.line_wait = [ r_v(stamp 1) ]`.

**t = 16 -- `r_s` finally re-probes, and lands *behind* a younger waiter.**

```
find(Y)                     -> &E_Y            (it did not exist when r_s went to sleep)
release_reservation(r_s)    -> returns TRUE, reserved_ 1 -> 0
add_target(E_Y, r_s)        -> FALSE, targets are full
push_line_wait(E_Y, r_s):
    mark_refused(r_s, Line, counter):
        r_s.refusal == 0, which is NOT NoRefusal  ->  DOES NOTHING
        stamp stays 0 ; reason stays Slot
E_Y.line_wait = [ r_v(1), r_s(0) ]
```

**Insert order is `[1, 0]`.** That is plan section 3.8's out-of-order-insert
counterexample, reached exactly as the plan describes it: a slot waiter outlived
the allocation of an entry it later merged onto, and arrived carrying an **older**
stamp than what was already there.

**t = 126 -- `E_Y` retires**, 110 cycles after it was forwarded.

```
retire(E_Y, out):
  1. out.targets = [ &r_t, &r_u ]           copied before the erase
     out.wake    = [ &r_v(1), &r_s(0) ]     the line waiters, ALL of them
     both waiters' on_wait_index cleared
  2. entries_.erase(it)                     live() 3 -> 2
  3. collect_grants(out.wake):
         live 2 + reserved 0 < 4  BUT slot_wait_ is empty -> nothing appended
  4. stable_sort(out.wake) by  a.refusal < b.refusal
         [ r_v(1), r_s(0) ]  ->  [ r_s(0), r_v(1) ]
```

**Result:**

| group | members | what the engine does with them |
|---|---|---|
| `out.targets` | `r_t`, `r_u` (primary first, then merge order) | satisfied **directly** by the fill, no re-triage |
| `out.wake` | `r_s`(0), then `r_v`(1) | reinjected **in this order**; each reserves a port and re-probes |

**Who wakes, in what order: `r_s` before `r_v`, stamp 0 before stamp 1**, even
though `r_v` was pushed onto the index first -- **`[1, 0]` in, `[0, 1]` out.** Both
will hit, since the line is resident by the time they re-probe, but the *order* is
not cosmetic: reinjection reserves a port, so at `ii = 1` the two get accept times
one cycle apart, and under LRU the order two accesses to one set are serviced
**is** the recency stack (D7). One flipped tie leaves a different victim and every
access after it diverges.

**Decisions.** B109, B119.

**Traps.**

**`retire` erases the entry BEFORE the grant loop, so the credit it freed is the
one it hands out.** `collect_grants`'s condition is `live() + reserved_ <
capacity_`. Take a full file (`capacity 4`, `live() == 4`, `reserved_ == 0`) with
two slot waiters, and retire one entry:

| order | `live()` when the loop runs | `... < 4`? | grants handed out |
|---|---|---|---|
| **collect, then erase** | 4 | `4 + 0 < 4` **false** | **0** |
| **erase, then collect** (what the code does) | 3 | `3 + 0 < 4` true | **1** |

Collecting first would grant one waiter fewer **at every retire, forever**, so a
file of capacity 4 would behave like a file of capacity 3 while `capacity()` and
every stat kept reporting 4. That failure mode is worth stating in full because of
**how it would present**: it does not crash, does not assert, and does not produce
an invalid state -- I4 (`|entries| + reserved <= capacity`) still holds, and holds
*more* comfortably. What it produces is a permanently under-used entry and a
permanently longer wait queue. In a sweep over `l1_mshrs`, **the knee would appear
one entry early and would be read as a result about MSHR sizing** rather than as
an off-by-one in a loop's position.

**`collect_grants` runs BEFORE the sort, not after**, because the granted waiters
are part of the same ordered wake list. Two loops instead of one would stagger the
wake by loop order rather than by age, which is what I7b forbids.

**`stable_sort` where `std::sort` would do today.** Stamps are unique across the
run (I2), so no two elements compare equivalent and the two sorts produce
identical output on every input the file can build -- the weaker guarantee is
**free**. What it buys is a *failure mode*: if the uniqueness invariant ever
weakens (a second stamp source, or a request reaching the list unstamped and
carrying `NoRefusal`), the answer stays a function of insertion order rather than
of the sort's internal pivot choices. Note that decision B122 reclassified the
mutation `B3 the wake sort is not stable` from `kill` to `allow` as a **proven
equivalent mutant** for exactly this reason.

### `std::int32_t MshrFile::live() const`, `reserved() const`, `slot_wait_depth() const`

**What they are.** The file's three observable counts.

**Contract.** None throws. `live()` is `entries_.size()`, `slot_wait_depth()` is
`slot_wait_.size()`, both narrowed to `int32` through one reviewable conversion
site (`as_count`). `reserved()` is the granted-but-not-yet-spent credit count.

The counts fit an `int32` because the constructor bounds `capacity` at one and
nothing here can exceed it: entries are refused past capacity, and the wait
indices are bounded by the credit supply (4.1).

**Worked example.** Part 8's headline instrument is the **MSHR occupancy histogram
per level**, sampled from `live()`. I4 (`|entries| + reserved <= capacity`) is
checked from `live()` and `reserved()` together. I11's global wait bound is checked
against `slot_wait_depth()` plus the per-entry `line_wait` depths.

**Traps.**

**`live()` alone is not occupancy.** A file at `live() == 3, reserved() == 1` with
`capacity() == 4` is **full**: `has_slot` refuses a fresh demand request. Reading
only `live()` under-reports occupancy by exactly the outstanding grants.

**The wait population is split across two structures.** `slot_wait_depth()` is the
file's own index; the line waiters live on their entries, one vector per `Mshr`,
and there is no aggregate accessor for them. A caller wanting the total must walk
the entries -- and see the class-wide trap about never iterating `entries_`: sort
what you walk.

### `std::int32_t MshrFile::capacity() const`, `tgts_per_mshr() const`, `demand_reserve() const`

**What they are.** The three config numbers this file was built from.

**Contract.** None throws. Pure reads, returning exactly what the constructor
accepted.

**Worked example.** `capacity() - demand_reserve()` is the prefetch budget: 3 at
the running configuration, and **0** at the default `l1_mshrs == lines_per_burst`.

**Traps.** They report the **configured** values, not the effective ones. At
`demand_reserve() == capacity()` prefetching is off entirely, and nothing in these
three numbers says so in one place -- the budget is a subtraction the reader has to
do.
