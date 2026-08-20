# Phase A construct reference

**What this is.** One entry per public construct - class, struct, enum, free
function, member function, sentinel - built by Phase A of the C++ harness. The
organising unit is the **construct**, not the increment and not a narrative run.
A reader who has a construct name and wants to know *what it does, what it will
refuse, and why it is shaped that way* navigates here by that name.

**Not a replacement for the increment docs.** The five per-increment narratives
stay alongside this file as the historical record, and they are the only place
that records what a round *found* as it was building:

| File | Covers |
|---|---|
| `A1-A2c-EXPLAIN.md` | the flatten helpers (`line_stride`, `block_len`, `line_of`) |
| `A2d-EXPLAIN.md` | `expand` and `locate` on `BlockPackMapper` |
| `A4a-EXPLAIN.md` | the non-narrowing `Tagged`, `SetIndex`, `NoLine`, the `CacheArray` interface |
| `A4b-EXPLAIN.md` | `SetAssociativeArray` construction and validation |
| `A4c-A5-EXPLAIN.md` | `Placement` typing, the five verb bodies, `ReplacementPolicy` + LRU/FIFO |

Where an increment doc and this file disagree, **the sources are the ground
truth and this file follows them**: several later decisions edited Phase A code
after those docs were written, and each such case is called out in the entry it
touches (the three largest are `stride < 1` becoming illegal, `Placement`'s
fields becoming tagged, and `line_size_terms` gaining its argument).

---

## Read this before reading any decision number: the three-way naming collision

One spelling carries three unrelated senses across the plan and the board. They
are never merged and never renumbered.

| Spelling | Sense | Example |
|---|---|---|
| **plan unit** | a build unit of the plan's Part 7: `A1a`…`A5`, `B1`…`B3`, `C1`…`C5` | "plan unit A4c builds the five verb bodies" |
| **decision** | a numbered row of `PROGRESS.md`'s decisions table, `B1`…`B152` | "decision B49 made `stride < 1` illegal" |
| **v3 change** | plan Parts 2.1 / 3.1 / 4.1 label v3's two *changes* over v2 `C1` and `C2` | v3's C1 is 4.5's self-timed core model; v3's C2 is 4.6's L1-side prefetcher |

So a bare `B3` is ambiguous between plan unit B3 (`MshrFile`) and decision B3
(the `NoRefusal` sentinel), and a bare `C1` is ambiguous three ways: plan unit
C1 is `CacheLevel`, decision B131 notes that **v3's change C1 is implemented by
plan unit C3**, not by plan unit C1. In this file every reference is written out
in full: **"decision Bnn"** for a board row, **"plan unit A4c"** for a build
unit. Every `Bnn` in a **Decisions** subsection below is a *decision*.

---

## The exception vocabulary, stated once

`layout.h` states the tree's three tiers and every construct below follows them
(decision B27, B18):

| Type | Meaning | Typical case |
|---|---|---|
| `std::invalid_argument` | the argument is malformed **whatever layer** it is applied to | a constructor parameter `< 1`; a burst with `count < 1` or `stride < 1`; an empty candidate set; `PolicyKind::RANDOM` |
| `std::out_of_range` | the argument is well formed but names something **outside this layer** | a coordinate past an extent; a `LineId` outside `[0, num_lines())`; a `SlotId` outside `[0, num_slots())` |
| `std::logic_error` | programmer error: a stub, or a state the code proves unreachable | an `Axis` outside the enumerators; an unknown `PolicyKind` after an exhaustive switch |

Everything **throws**; nothing asserts. All of these read config fields, and an
`assert` compiled out under the sweep build's `-DNDEBUG` turns a rejected
configuration into a silently wrong simulation (decision B62).

---
---

# `native/include/wcache/types.h`

The scalar vocabulary. Nothing here allocates and nothing here has a `.cpp`.

## `detail::converts_without_narrowing<To, From>`

**What it is.** A compile-time trait answering one question: *is `To x{v}` well
formed for a `v` of type `From`, or would that initialisation narrow?* It is the
gate on `Tagged`'s only constructor.

**Contract.**

```cpp
template <typename To, typename From, typename = void>
struct converts_without_narrowing : std::false_type {};

template <typename To, typename From>
struct converts_without_narrowing<To, From, std::void_t<decltype(To{std::declval<From>()})>>
    : std::true_type {};
```

`::value` is `true` exactly when braced initialisation of a `To` from a `From`
is well formed. It throws nothing and cannot fail: an ill-formed inner
expression makes the partial specialisation not apply, and the primary template
answers `false`. It asks the *compiler* its own question rather than
enumerating widths and signednesses by hand, which is the enumeration that gets
one entry wrong.

**Worked example.** Two evaluations, one per answer:

```
converts_without_narrowing<std::int32_t, std::int64_t>::value
    inner: std::int32_t{ declval<std::int64_t>() }     ill-formed (narrows)
    -> the specialisation does not apply -> false_type -> value == false

converts_without_narrowing<std::int64_t, std::int64_t>::value
    inner: std::int64_t{ declval<std::int64_t>() }     well formed
    -> the specialisation applies         -> true_type  -> value == true
```

**Decisions.**

- **B55** - the mechanism for decision B29's non-narrowing rule is SFINAE over
  `std::void_t<decltype(To{declval<From>()})>`, and three alternatives were
  rejected with reasons: a deleted narrowing overload never gets reached
  (g++ makes a narrowing *argument* conversion a `-Wnarrowing` warning, so the
  call binds to the surviving plain constructor); a plain template plus
  `static_assert` hijacks copy construction; `is_same_v<U, Rep>` is too strict
  and kills `LineId{5}`, which is most call sites in the tree.

**Traps.**

- **`std::declval` NOT being a constant expression is load-bearing, not
  incidental.** C++ permits a narrowing conversion when the source is a constant
  that fits, so `std::int32_t x{5L}` is legal while `std::int32_t y{big}` is not.
  A trait written against a real value would therefore answer "may an int64
  become a `SlotId`?" with *it depends where the int64 came from* - `SlotId{5L}`
  accepted, `SlotId{p.tag}` rejected. `declval` names a value of the type and
  tells the compiler nothing about *which* value, so the trait answers about the
  **type**, uniformly.

## `Tagged<Rep, Tag>`

**What it is.** A distinct type over a representation `Rep`. `Tag` is only ever
an incomplete `struct` in namespace `tags`: it names the quantity and is never
instantiated. Every id and every time-like scalar in the tree is an instance.

**Contract.**

```cpp
template <typename Rep, typename Tag>
class Tagged {
public:
    using rep_type = Rep;
    Tagged() = delete;
    template <typename U,
              typename = std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>>
    constexpr explicit Tagged(U v) : v_{v} {}
    constexpr Rep get() const { return v_; }
private:
    Rep v_;
};
```

Promises: no default construction; no implicit conversion in either direction
(`explicit` in, `get()` the only way out); no arithmetic at all; and a
construction that would narrow, **or that names a different quantity**, has no
viable constructor and fails to compile under every flag combination. Refuses at
compile time only - it throws nothing.

**Worked example.** The construction the whole mechanism exists for, with the
number decision B15 records as the realistic route to it (plan unit A3 reading a
trace header at the wrong offset), not one anybody would type:

```
p.set_index = 3
p.tag       = 4294967303          which is 2^32 + 7
```

*Before* the non-narrowing constructor, compiled and run rather than argued:

```
$ g++ -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow ...
types.h: warning: narrowing conversion of 'v' from 'long int' to 'int' [-Wnarrowing]
$ ./trunc
p.tag    = 4294967303
s.get()  = 7
```

**A tag of 4,294,967,303 became slot 7** - and 7 is a perfectly ordinary slot
number, so the truncation does not crash, does not throw, and does not look out
of place in a debugger. It produces a hit or a miss against the wrong storage
location for the rest of the run.

*After*, the same line, step by step: `U` deduces to `std::int64_t`; the default
template argument substitutes
`enable_if_t<converts_without_narrowing<std::int32_t, std::int64_t>::value>`;
the trait's inner `std::int32_t{declval<std::int64_t>()}` is ill-formed, so the
trait is `false_type`; `enable_if_t<false>` has no member `type`; substitution
fails, which *removes the candidate* rather than erroring in place; and there is
no other constructor.

```
error: no matching function for call to 'wcache::Tagged<int, wcache::tags::slot>::Tagged(
       <brace-enclosed initializer list>)'
    7 |     SlotId s{p.tag};
note: candidate: 'template<class U, class> constexpr wcache::Tagged<Rep, Tag>::Tagged(U)
      [with Rep = int; Tag = wcache::tags::slot]'
note:   template argument deduction/substitution failed
```

And the refusal that is about the **name** rather than the width, both operands
being `int64` so nothing narrows:

```
REJECT   SetIndex i{3};  LineId l{i};
```

rejected because `std::int64_t{declval<SetIndex>()}` is ill-formed: a `SetIndex`
is not an integer and never converts to one implicitly.

**Decisions.**

- **B1b** - one template rather than six hand-written classes or six
  `enum class`es: the template gives one definition of each operator, so a typo
  cannot affect one type in isolation. `enum class` was the near miss, rejected
  because it forces a hand-written cast on every legal arithmetic operation,
  which lets `SimTime + RefusalOrder` compile silently in the exact shape N12
  exists to stop.
- **B2** - no default constructor: a defaulted `SlotId` would silently mean slot
  0 and a defaulted `SimTime` the start of the run, both valid values a forgotten
  initialiser produces silently. Containers spell the fill out:
  `std::vector<SlotId>(n, NoSlot)`.
- **B5** - every scalar is signed. This is a convention, not a preference: the
  v1 tree's `line_of` bug was an unsigned flatten in an expression that mixed
  signedness, and one signedness across the whole layout class removes the class
  of bug rather than the instance.
- **B29** - the policy that `SlotId s{p.tag}` must fail to compile; **B55** the
  mechanism.

**Traps.**

- **The plain `Tagged(Rep)` had to be removed, not shadowed.** Keeping it beside
  a deleted template leaves the hole open, because the narrowing call binds to
  the plain constructor (g++ warns and compiles). Removing it is what makes
  "no matching function" a hard error.
- **`v_{v}` is NOT a second line of defence, and the obvious reading is wrong.**
  Measured, two variants built and compiled against `SlotId s{p.tag}`:
  constraint **removed** and braces kept → *compiles*, carrying `-Wnarrowing`
  and `-Wconversion` and nothing else; constraint kept and braces removed to
  `v_(v)` → *rejected*. The constraint is solely load-bearing. The braces are
  defeated by exactly the permissiveness the mechanism exists to route around,
  which is why reaching for them as the fix does not work. They are kept for
  stating the rule where the value lands.
- **Copy construction still works, and that is not luck.** For `SlotId b{a}` a
  template deducing `U = SlotId` would be an exact match and would beat the
  implicit copy constructor, recursing into itself. The constraint prevents it:
  `std::int32_t{declval<SlotId>()}` is ill-formed, the trait is `false`, the
  template is removed, and the implicit copy constructor is left holding the
  call. Checked, not assumed: `SlotId b{a}` and `SlotId b = a` both ACCEPT.
- **The diagnostic never contains the word "narrowing".** That is an accepted
  cost of the design, not an oversight.

## The comparison operators on `Tagged`

**What it is.** Six `constexpr` free operators - `==`, `!=`, `<`, `<=`, `>`,
`>=` - each taking two `Tagged<Rep, Tag>` of the **same instantiation**.

**Contract.** Deduction requires both operands to be the same `Tagged<Rep, Tag>`.
That is what makes `SimTime{1} == LocalTick{1}` a **compile error** rather than
`true`, which is requirement N12: simulated time, trace-local time and an
arbitration counter are three different quantities that all happen to be
`int64`, and no expression may silently mix them.

**Traps.**

- There is no mixed-type overload and there must never be one. A single
  `template <typename A, typename B>` comparison would quietly re-open every
  pair N12 closed.

## The tagged scalars

**What they are.** Ten aliases of `Tagged`, one per quantity the model names.

**Contract.**

| Alias | Rep | What it names |
|---|---|---|
| `LineId` | `int64` | a line address in the flat weight space, `tag * num_sets + set_index` |
| `CoreId` | `int32` | a core |
| `SlotId` | `int32` | a dense, stable index over the slots of **one** array; the only handle crossing between `CacheArray` and `ReplacementPolicy` |
| `SetIndex` | `int64` | which set of a set-associative array a line competes in, in `[0, num_sets)`; first half of `locate`'s answer |
| `TagId` | `int64` | what tells a line apart from the others mapping to its set, `line / num_sets`; second half of `locate`'s answer |
| `BurstIndex` | `int32` | which burst of a core's tile, in trace order |
| `SimTime` | `int64` | simulated time; the engine has no tick, `now` is the timestamp of the event being dispatched |
| `LocalTick` | `int64` | trace time, and only ever an offset **within one tile**; there is no absolute `LocalTick` |
| `RefusalOrder` | `int64` | arbitration order (3.8): a global counter's value at a request's **first** refusal, not a tick |
| `EventSeq` | `int64` | schedule order (3.6): the event queue counter's value when an event was **scheduled** |

**Worked example.** Why `SetIndex` had to be a *name* and not a width. A1a's
carried obligation gave the failure it exists to stop:
`policy.on_hit(SlotId{set_index})` compiling. Under the narrowing rule alone
that pair is already refused - a set index is `int64` and a `SlotId` is `int32`,
so it narrows - and the obligation looks discharged by accident. It is not:

```
REJECT   SetIndex i{3};  LineId l{i};        both int64 - nothing narrows
```

Rejected on the **name**. If `SlotId` ever widened to 64 bits, a width-based
rule would go quiet where a name-based one does not.

The same argument at one level up produced `BurstIndex`: a `Request` holds a
core id and a burst index side by side, both small counts, so
`Request{..., burst = c}` with two arguments swapped is a spelling the struct
invites, and neither `explicit` nor the non-narrowing constructor can see it -
same width, same signedness.

**Decisions.**

- **B5** - the widths: `int64` for line ids, set indices, tags and the time-like
  types; `int32` for `CoreId`, `SlotId`, `BurstIndex`.
- **B9** - the placement *struct* is named `Placement`; `SetIndex` is reserved
  for the tagged scalar, because two fields do not read as an "index" and the
  scalar is the one that must own the obvious name.
- **B75** - the tag scalar is `TagId`, **not** `Tag`. `Tag` is already spoken
  for twice inside this file: it is `Tagged`'s second template parameter, and
  `tags` is the namespace of the empty structs that fill it. `using Tag =
  Tagged<std::int64_t, tags::tag>` would define a name out of two other live uses
  of itself - committing exactly the naming accident the tagged types exist to
  prevent, inside the machinery built to stop it.
- **B118** - `BurstIndex` and `EventSeq` are added later, and `BurstIndex` is the
  **ninth** tagged scalar, not the eighth; decision B75's `TagId` is where the
  count moved.

**Traps.**

- **`RefusalOrder` and `EventSeq` are two monotonic `int64` counters sitting in
  the same sort key, and that adjacency is exactly why both are tagged.** 3.6's
  key is `(time, class, effective_age, core_id, seq)`, whose third field is a
  refusal stamp and whose fifth is an event sequence. An implementation
  comparing them in the wrong order would compare two counters of the same width
  and produce a plausible, wrong, and perfectly reproducible event order. They
  count different things: a refusal stamp is written **once per request** at its
  first refusal and may be shared by several of that request's events; an
  `EventSeq` is written once per event and never reused.
- **A rule about narrowing can never separate two `int64` quantities.**
  `LineId l{p.set_index}` and `SimTime t{p.tag}` were accepted at plan unit A4a
  and only closed later by typing `Placement`'s fields (decision B75/B77). The
  narrowing rule reached exactly two of the five cases; the boundary is real.

## `NoSlot`, `NoLine`, `NoRefusal`

**What they are.** Three sentinels, each sitting at the **top** of its range so
that ordinary `<` puts it last.

**Contract.**

```cpp
inline constexpr SlotId       NoSlot   {INT32_MAX};
inline constexpr LineId       NoLine   {INT64_MAX};
inline constexpr RefusalOrder NoRefusal{INT64_MAX};
```

`NoSlot` is what `probe` and `free_slot` return when they find nothing.
`NoLine` is what a slot holding nothing reports. `NoRefusal` is what a request
that has never been refused carries.

**Worked example.** `NoRefusal` at the top of the range is what collapses a
two-field key into one comparison. 3.8's ordering key is
`(r.refusal == NONE, r.refusal)` - refused beats fresh, FIFO within refused -
and with `NONE` at `INT64_MAX`, plain `a.refusal < b.refusal` computes that
**whole** key, so the "refused" bit is not carried as a second field that could
drift out of sync with the counter.

`NoLine` at `INT64_MAX` is what makes "free" and "holds a line" one comparison
in a way scan rather than a second valid bit per slot. It cannot collide with a
resident line: a real `LineId` is in `[0, num_lines())` and `num_lines()` is
itself an `int64` the layout's overflow guard bounds at `INT64_MAX`, so the
largest id any mapper can produce is `INT64_MAX - 1`.

**Decisions.**

- **B3** - sentinels sit at the top of their range so plain `<` sorts them last,
  which is what lets a single comparison implement a whole ordering key.
- **B64** - `SetAssociativeArray` bounds its line count at exactly `INT32_MAX`
  and not `INT32_MAX - 1`, because at `total_lines == INT32_MAX` the largest
  valid slot id is `INT32_MAX - 1`, one short of `NoSlot`.

**Traps.**

- **`NoLine` is `INT64_MAX` and not `-1`, and the v1 argument for `-1` died with
  the typing.** v1 used `-1` so that a caller who forgot to check would index out
  of bounds loudly. `LineId` is a `Tagged`, so it cannot be used as a subscript
  at all without an explicit `.get()`, and there is no forgetting to check.
- **Both sentinels live in `types.h`, not in `cache.h`.** v1 put both in
  `cache.h`; here `NoSlot` was already in `types.h`, so splitting them would
  split one convention across two files. `Candidate::line` is documented as
  `NoLine` when the slot is free, so every policy and every level reads it - it
  is shared vocabulary, not an array-internal detail.

## The time arithmetic

**What it is.** The only arithmetic anywhere on a `Tagged`, written out as free
operators for the two time-like types.

**Contract.**

```cpp
constexpr SimTime   operator+ (SimTime a,      SimTime b);
constexpr SimTime   operator- (SimTime a,      SimTime b);
constexpr SimTime&  operator+=(SimTime& a,     SimTime b);
constexpr SimTime   operator+ (SimTime origin, LocalTick offset);   // the one crossing
constexpr LocalTick operator+ (LocalTick a,    LocalTick b);
constexpr LocalTick operator- (LocalTick a,    LocalTick b);
```

Simulated durations are `SimTime` values, so a latency added to an accept time
is the same quantity as the time it advances. No operation yields a `LocalTick`
from a `SimTime`, and there is still no way to *compare* the two.

**Worked example.** The one expression in plan Part 5 that needs the crossing:

```
issue_time(c) = tile_origin[tile(c)] + local_tick(c, cursor)
                  ^ SimTime            ^ LocalTick        -> SimTime
```

**Decisions.**

- **B4** - `SimTime + LocalTick -> SimTime` is the one permitted crossing.
  N12 requires the time-like types be *uncomparable*, which this does not weaken.

**Traps.**

- There is deliberately **no** `LineId` arithmetic. A stride is a delta and a
  line id is an address; they have different algebra, exactly as `ptrdiff_t` and
  a pointer do. `BlockPackMapper::line_stride` returning `std::int64_t` rather
  than `LineId` is that distinction made mechanical, and it is why `line_of`
  does all its work in plain `int64` and constructs the `LineId` once, on the
  return statement.

## `Axis`

**What it is.** The four axes of the weight tensor, in **row-major nesting
order, outermost first**.

**Contract.**

```cpp
enum class Axis : std::uint8_t { KH = 0, KW = 1, CIN = 2, COUT = 3 };
```

The logical shape is `[KH][KW][CIN][COUT]`. **Declaration order is the flatten
order**, and `BlockPackMapper` depends on that: four `static_assert`s at
`block_pack.cpp:33-36` pin the enumerator values so that reordering the
enumerators here **stops the build in the file that would otherwise have been
silently wrong**.

**Decisions.**

- **B17** - flatten order is KH, KW, cin block, cout block, matching this
  declaration order with the two blocked axes replaced by block indices; the
  four `static_assert`s pin it.
- **B22** - *why* that is the right order, which is the half decision B17 left
  out. Any permutation of the four axes is a bijection onto `[0, num_lines)`, so
  flatten order changes neither what a line contains, nor `num_lines`, nor the
  set of lines a burst touches. It changes only **which axis owns the low bits**
  of `line`, and therefore `set_index = line % num_sets`. Putting COUT at radix 1
  makes a COUT-walking burst a contiguous run of ids, and every trace in the
  corpus bursts along COUT with stride 1, so the order is alias-free **by
  construction rather than by luck**.
- **B24** - flatten order is not a swept parameter: of the 24 permutations
  roughly two are physically plausible and one of those is decision B22's
  known-bad case. Order is an assumption the study wants to be safe *from*, not
  a hypothesis it tests.

**Traps.**

- **Reordering the enumerators changes line ids and nothing announces it.**
  Decision B22 measured the damage: swapping `cin_block` and `cout_block` in the
  flatten on the `3x3x512x512` running layer turns the burst's ids 5280..5311
  (32 sets, one line each) into ids 5125..6117 at stride 32, which is **2
  distinct sets holding 16 lines each**, so at 8-way the burst evicts half its
  own lines while they are still being fetched. The failure is total rather than
  graceful because CIN and COUT are always in {64, 128, 256, 512} across all 155
  corpus layers and the blocks are powers of two, so every radix is a power of
  two and a strided walk aliases perfectly against a power-of-two set count.

## `Coord`, `WeightShape`, `Burst`

**What they are.** The tensor-geometry structs: one element, the layer's
extents, and one run of elements fetched together.

**Contract.**

```cpp
struct Coord       { std::int32_t kh, kw, cin, cout; };
struct WeightShape { std::int32_t KH, KW, CIN, COUT; };

struct Burst {
    Coord        anchor;  // the run's first element
    Axis         axis;    // which axis the run walks (header burst_dim)
    std::int32_t count;   // number of elements in the run
    std::int32_t stride;  // step along `axis` between elements (burst_stride)
};
```

Plain `int32` coordinates rather than six more tagged types, and that is forced
rather than chosen: the four axes are addressed **generically** through `Axis`,
so `coord_on` and `extent_on` must return one type, and tagging them per axis
would make exactly the code that needs to be generic impossible to write.

`Burst` is the **unit of issue** (plan D9): one trace event is a burst, not a
line, and under a layout narrower than the burst it expands to several lines.

**Worked example.** The trace's on-disk 5-tuple is a *different* shape, and the
decode is plan unit A3's, not the model's. Today it is
`[kh, kw, cin, cout_start, cout_end]`, decoded to:

```
Burst{ anchor = {kh, kw, cin, cout_start},
       axis   = COUT,
       count  = cout_end - cout_start,
       stride = 1 }
```

Format v2 carries `burst_dim` and `burst_stride` as **header fields**, so a
future architecture bursting along CIN is the same struct with a different
`axis`; `axis` and `stride` are read from the header and never assumed.

**Decisions.**

- **B8** - `Burst::count` and `::stride` stay `int32`, matching `WeightShape`'s
  extents: one width across the whole coordinate and block arithmetic, so the
  mixed-signedness, mixed-width expression that produced the v1 `line_of` bug has
  nowhere to form.
- **B10** - trace tuple order is a *decode* concern, not a model concern. The
  canonical `Coord` and `Burst` are fixed and the on-disk field order arrives
  from the header, which keeps layout compatibility in one unit instead of a
  format branch in every consumer. A differently **nested** memory layout, as
  opposed to a differently **ordered** tuple, is a new `AddressMapper` subclass.

**Traps.**

- `Burst::stride` is a plain `int32`, so "stride >= 1" has **no compile-time
  spelling** - the value is not in the type and nothing about `Burst{c, a, 4, -1}`
  is ill-formed. Decision B53 records that the stride rule therefore carries
  **no** `compile_fail.sh` case, deliberately, and is pinned by runtime tests and
  five mutation cases instead. A value-range rule belongs there.

## `extent_on`, `coord_on`, `with_coord_on`, `axis_name`

**What they are.** The four per-axis accessors. They are where the tree's
four-way `switch` over `Axis` lives, so no consumer open-codes it.

**Contract.**

```cpp
constexpr std::int32_t extent_on(const WeightShape& shape, Axis a);
constexpr std::int32_t coord_on (const Coord& c,          Axis a);
constexpr Coord        with_coord_on(Coord c, Axis a, std::int32_t v);
constexpr const char*  axis_name(Axis a);
```

Each is an exhaustive `switch` with a `throw std::logic_error` **after** it. The
throw is unreachable for any legal `Axis`, and `-Wswitch` is what makes that
cheap: adding a fifth enumerator is a build failure here rather than a
fall-through at run time.

**Worked example.** Why the unreachable arm **refuses** instead of returning a
default, taking the worst of the four:

```
coord_on with a fallback of 0:
    expand reads the anchor through this function
    -> a burst would silently walk from coordinate 0
    -> and emit valid-looking line ids
```

`extent_on` with a fallback of 0 is nearly as bad in the other direction: it
would turn every range check into a check against an *empty* tensor, rejecting
everything rather than failing where the fault is.

**Decisions.**

- **B6** - `with_coord_on` stays (the user: "good to have"): `expand` walks a
  burst by stepping one axis, which needs a **write** as well as `coord_on`'s
  read, and keeping it here puts all of the axis knowledge in one file rather
  than open-coded inside `expand`.
- **B7** - `axis_name` keeps returning `const char*` and does **not** carry the
  extent. The N11 message needs axis, coordinate and extent together and only
  the *thrower* holds all three; making `axis_name` carry an extent would force
  it to take a `WeightShape` it does not otherwise need and would still leave the
  coordinate to the caller.

## `std::hash<wcache::Tagged<Rep, Tag>>`

**What it is.** A specialisation of `std::hash` forwarding to `hash<Rep>`, so a
tagged scalar can key an unordered container.

**Contract.**

```cpp
namespace std {
template <typename Rep, typename Tag>
struct hash<wcache::Tagged<Rep, Tag>> {
    size_t operator()(wcache::Tagged<Rep, Tag> v) const noexcept { return hash<Rep>{}(v.get()); }
};
}
```

`noexcept`, and it needs no equality helper because `operator==` on the same
instantiation already exists.

**Decisions.**

- **B117** - the MSHR file's entries are a `std::unordered_map<LineId, Mshr>`,
  which is what this specialisation exists for. Node-based storage is the
  requirement rather than the hashing: `Request::mshr1` and every `Mshr&` the
  engine holds must stay valid across other insertions **and** erasures.

**Not covered by any recovered increment doc.** This specialisation and the
`BurstIndex` / `EventSeq` scalars post-date every Phase A narrative.

---
---

# `native/include/wcache/layout.h`

The abstract layout interface. Header-only, and deliberately abstract: a layout
is a **hypothesis** about how weights are arranged in memory, and the study
compares hypotheses. The engine holds an `AddressMapper` and never learns which
one it has.

## `Placement`

**What it is.** Where a line sits in a set-associative array: which set holds
it, and the value that tells it apart from the other lines mapping to that set.
It is `locate`'s return type.

**Contract.**

```cpp
struct Placement {
    SetIndex set_index;  // in [0, num_sets)
    TagId    tag;
};
```

The identity that **defines** the pair, and the plan's own exit criterion for
plan unit A2:

```
line == tag * num_sets + set_index
```

`layout.h` keeps that readable form in a comment; the code spells it
`p.tag.get() * num_sets + p.set_index.get() == line.get()`. The bound
`0 <= set_index < num_sets` is **not vacuously true**, because the
representation underneath stays signed.

**Worked example.** One line at two levels of the same hierarchy, from the
`3x3x512x512` running layer at `cin_block = cout_block = 16`:

```
locate(LineId{5280},  32)  ->  Placement{ SetIndex{ 0}, TagId{165} }   165*32 +  0 = 5280
locate(LineId{5311},  32)  ->  Placement{ SetIndex{31}, TagId{165} }   165*32 + 31 = 5311
locate(LineId{5280}, 128)  ->  Placement{ SetIndex{32}, TagId{ 41} }    41*128 + 32 = 5280
locate(LineId{5311}, 128)  ->  Placement{ SetIndex{63}, TagId{ 41} }    41*128 + 63 = 5311
```

Same mapper, same ids, two answers, no state carried between the calls.

**Decisions.**

- **B9** - the struct is named `Placement`, not `SetIndex`: it holds two fields
  and "index" reads as one.
- **B75** - both fields are **tagged** (`SetIndex`, `TagId`) rather than raw
  `int64`. Before this, `Placement` was two raw integers side by side in the one
  struct in the tree whose whole job is to hand them to a set-associative array,
  so a set index flowed into a `LineId`, a `SimTime`, a future 64-bit slot
  handle, or the other field, with no diagnostic and no width to catch it.
- **B76** - `locate` returns `Placement{SetIndex{v % num_sets}, TagId{v / num_sets}}`.
- **B77/B83** - typing the fields is what finally closed the three int64-to-int64
  `accept` cases no narrowing rule could reach; the mutation
  `TagId aliases LineId` had survived the **entire** suite, because nothing
  anywhere distinguished a tag from a line id. It is the most tempting alias of
  the whole set for two reasons: both are signed 64-bit, and at `num_sets == 1`
  a tag genuinely **is** the line, so the alias is not merely type-compatible but
  occasionally true.

**Traps.**

- **The `.get()`s in the identity are the price of the naming and carry no
  meaning of their own** - `layout.h` says so outright, and that sentence is
  load-bearing rather than polite. The failure mode is a later reader seeing
  three unwraps inside an arithmetic identity, concluding some conversion is
  happening that matters, and either "simplifying" the invariant away or writing
  a second one beside it.
- **`tag` has no precondition and none was added.** `tag * num_sets` is signed
  overflow - undefined behaviour, not a wrong number - for any
  `tag > INT64_MAX / num_sets`. Typing the field made the hazard harder to
  construct by accident and not one bit less present. `SetAssociativeArray`
  avoids it entirely by **never reading the field** (see `base_slot`). It is not
  a defect today only because no caller constructs a `Placement` by hand; it
  becomes one the moment something other than `locate` does.

## `AddressMapper`

**What it is.** The abstract layout interface: logical tensor coordinates to
cache lines. Five virtuals, four of them pure.

**Contract.** One instance serves the **whole hierarchy**. L1 and L2 differ in
size and associativity, not in how the tensor is laid out, so the set count is a
`locate` **argument** rather than mapper state. The three exception tiers above
are stated on this class, because which type is thrown is part of what an
implementation promises and is what the engine's re-throw one level up is
written against.

**Decisions.**

- **B23** - **no user-programmable index function**: the mapping is chosen by
  naming an `AddressMapper` subclass, never by a config-supplied index
  expression. Rejected on correctness, not effort. Three invariants the engine
  rests on require the mapping to be a bijection onto `[0, num_lines)`:
  `num_lines()` being exact, since it is the bound every later range check is
  written against; `locate`'s identity; and one `expand` call's ids being
  strictly increasing and distinct. An arbitrary expression guarantees none of
  the three, and bijectivity of a black box cannot be validated without
  enumerating the whole domain. **A named subclass is checkable; an expression is
  not.**
- **B32** - the stale citations were corrected: "Plan v2 Part 2.1" became v3,
  and the "measured merge ratio 1.13 at 1024 cores" figure went, since the core
  range settled at 8 to 256; the sentence keeps its point by saying the merge
  ratio is measured above 1 rather than quoting a number with no run behind it.

**Traps.**

- **`AddressMapper` is a polymorphic base with a virtual destructor and *public*
  implicit copy/move**, unlike `CacheArray` and `ReplacementPolicy`, which were
  given protected ones. The tree guards it by `compile_fail.sh` reject cases that
  pass one by value rather than by construction. Noted rather than changed: it is
  a real asymmetry a reader will notice.

### `AddressMapper::expand`

**What it is.** The address generator: turn one burst into the distinct lines it
touches.

**Contract.**

```cpp
virtual void expand(const Burst& b, std::vector<LineId>& out) const = 0;
```

- **Accepts a burst along ANY axis.** `b.axis` and `b.stride` come from the
  format v2 header. Today's corpus always says COUT with stride 1, but a trace
  written as `[kh, kw, cout, cin_start, cin_end]` bursts along CIN and is the
  same struct. An implementation reads the walked axis out of the burst; it may
  **not** assume COUT, and it may **not** assume the walked axis is one it
  blocks. A burst along KH is legal and, under a block-packed layout, touches
  `count` distinct lines because KH is not blocked.
- **Appends** the distinct lines to `out`. The ids appended by a **single call**
  are strictly increasing and distinct; that guarantee is **per call** and does
  not extend to the buffer as a whole.
- **Refuses** `count < 1` and `stride < 1` with `std::invalid_argument`; a
  coordinate outside the layer's shape with `std::out_of_range`.
- **Every range check runs before the first append**, so a call that throws
  appends nothing and leaves `out` exactly as it was.

**Worked example.** Why it appends rather than assigns, and what that obliges a
caller to do: the documented use accumulates a whole tick's demand across cores
into one reused buffer. Such a buffer is neither sorted nor unique *across*
calls - different cores in one tick touch lines out of order and touch the same
line, and the merge ratio is measured above 1. **A caller accumulating across
cores must sort and unique before counting distinct lines.**

**Decisions.**

- **B31** - "strictly increasing" is an obligation on the **implementation**,
  not a property a layout is free to have. `tests/mapper_conformance.h` is
  parameterised over the abstract base and **cannot check a guarantee that varies
  by implementation**, which would defeat the design the interface was built
  around. An implementation whose natural walk order does not produce increasing
  ids sorts before it appends.
- **B38** - `count < 1` throws `invalid_argument`; v1's permissive empty-run
  reading is dropped. A core asking for nothing is malformed at every layer, and
  under plan unit C1's serialization an empty burst would need a *served time*
  for a request with no lines, so every consumer downstream would carry that
  special case. Rejecting at the mapper makes it unrepresentable instead.
- **B49** - `stride < 1` is illegal, **resolved by an explicit user answer**
  rather than by delegation, and the provenance is part of the decision: every
  other resolution below decision B26 was reached by handing the question to a
  recommendation, which the board records as the weaker warrant and the first
  thing to reopen. A stride of 0 asks for the same element `count` times and a
  negative stride walks backwards, while `burst_stride` in the header is the step
  to the next element of the **run**, so neither is a run any trace can describe.

**Traps.**

- **The obligation this does NOT discharge is one level up.** In the accumulate
  pattern, a burst that throws part way through a tick leaves the buffer holding
  a well-formed but **PARTIAL** tick - the earlier cores only. The engine must
  decide whether such a tick is discarded or the run aborts, and **must not
  silently simulate the partial one** (decision B37 assigns that catch-and-
  re-throw to whichever unit owns the per-tick accumulate buffer, because the
  same catch block must settle both questions).

### `AddressMapper::locate`

**Contract.**

```cpp
virtual Placement locate(LineId line, std::int64_t num_sets) const = 0;
```

Precondition `0 <= line.get() < num_lines()`. An id outside that throws
`std::out_of_range`, and **the check runs BEFORE the division**.

**Traps.**

- **The check-before-divide is what makes the postcondition a fact rather than
  an assumption.** `LineId` is signed (decision B5), so a negative id would come
  back out of `line % num_sets` as a *negative* set index and index an array from
  below. See `BlockPackMapper::locate` below for the worked numbers.
- **`num_sets` is not validated here** and `v % num_sets` with `num_sets == 0` is
  undefined behaviour. `SetAssociativeArray`'s constructor guarantees
  `num_sets_ >= 1` before it ever calls `locate`, which closes the reachable path
  **through that array** - a narrowing of the reachable set, not an answer. The
  owner question (a mapper-side plausibility bound, a D1 config bound, or a guard
  in `locate` itself) is recorded as open and unowned.

### `AddressMapper::num_lines`

**Contract.**

```cpp
virtual LineId num_lines() const = 0;
```

One past the largest `LineId` this mapper can produce. It is the bound the
engine checks tags against and what D2 divides by for coverage, so **everything
downstream that compares against it is only meaningful if it is exact**.

### `AddressMapper::line_size_bytes`

**Contract.**

```cpp
virtual std::int64_t line_size_bytes() const = 0;
```

Bytes held by one line. On the **interface** rather than on the concrete mapper
because `CacheLevel` holds an `AddressMapper` and needs this to turn the config's
`cache_size_bytes` into a set count. Only the layout knows how many elements a
line packs, so only the layout can answer.

### `AddressMapper::line_size_terms`

**What it is.** The factors `line_size_bytes()` is the product of, named and
with their values, for a diagnostic that has to be **actionable** rather than
only true.

**Contract.**

```cpp
virtual std::string line_size_terms(std::int64_t line_bytes) const {
    return std::to_string(line_bytes);
}
```

A **default**, not a pure virtual, and the default is the bare product.

**Worked example.** Why the message needs it at all. A non-power-of-two line
size is deliberately legal (decision B16), so

```
"65536 is not a whole number of 96-byte lines"
```

leaves a reader with **no way to reach the config field that produced the 96**.
`12 x 8 x 1 = 96` is a legal line. With the terms:

```
SetAssociativeArray: cache_size_bytes 65000 is not a whole number of 256-byte lines
                     (cin_block 16 x cout_block 16 x weight_bytes 1)
```

now the reader knows which three config fields multiplied to 256 and can change
one of them.

**Decisions.**

- **B66** - an inline default, and the pure-virtual alternative was rejected
  **by measurement**: it would break **sixteen** deliberately non-conforming
  fakes (the obligation row had estimated thirteen; the count moved and the
  argument did not) plus four `subclass omits ...` reject cases, for a message.
  Paying for a diagnostic with the suite's own negative half is paying with the
  part of the harness hardest to rebuild. Measured blast radius of the change
  actually made: **zero**. The opt-in needed a conformance contract of its own
  (contract 9, `c_line_size_terms_is_informative`, decision B68) to stop it being
  silently skipped.
- **B79** - the signature takes `std::int64_t line_bytes`, the value the
  **caller already read**.

**Traps.**

- **`line_bytes` is an argument so that one refusal message is built from one
  read** - this is the entry to read if the argument looks redundant. Without it
  the default's body is `std::to_string(line_size_bytes())`, so one message asks
  one mapper for its line size **twice**. Measured with a counting fake before
  the fix:

  ```
  reads=2   ... is not a whole number of 96-byte lines (96)
  ```

  and with a fake whose second answer differs:

  ```
  reads=2   ... is not a whole number of 96-byte lines (7)
  ```

  One message, two reads, and the two halves contradict each other. No geometry
  came out wrong - the constructor's arithmetic used the single local
  `line_bytes` - but the diagnostic could be self-inconsistent, which is the
  exact property the read-once discipline claims to buy. `A4b-EXPLAIN.md`
  records this as a *known limitation*; decision B79 closed it, and the source is
  the fixed version.
- An override naming its own factors does not need the value and **may ignore
  it** - `BlockPackMapper`'s does exactly that.

---
---

# `native/include/wcache/block_pack.h` + `native/src/block_pack.cpp`

The block-packed layout: the concrete `AddressMapper`. It packs a
`cin_block x cout_block` sub-block of the `[KH][KW][CIN][COUT]` tensor into one
line, so a line is named by `(kh, kw, cin / cin_block, cout / cout_block)`
flattened row-major in that order.

**This is the first header in the tree with a matching `.cpp`**, and the reason
is specific: the constructor is the only place the layout's invariants are
established, and a body in the header would let a caller with a different `-D`
or a different include order compile a **different constructor** into their
translation unit than the library was built with.

## The running geometry, used by every example in this file

Layer `3x3x512x512` at `cin_block = cout_block = 16` - decision B22's own worked
case on the board, so these numbers were written before the code was:

```
n_cin_blocks  = ceil(512 / 16) = 32
n_cout_blocks = ceil(512 / 16) = 32
num_lines     = 3 * 3 * 32 * 32 = 9216
```

| Axis | `line_stride` | why | `block_len` | why |
|---|---|---|---|---|
| KH | `KW * n_cin * n_cout` = `3 * 1024` = **3072** | one step in kh skips a whole kw row of planes | **3** | KH is not blocked |
| KW | `n_cin * n_cout` = `32 * 32` = **1024** | one step in kw skips a whole 32x32 block plane | **3** | KW is not blocked |
| CIN | `n_cout` = **32** | one step in cin skips a whole run of 32 cout blocks | **32** | the block count, not 512 |
| COUT | **1** | innermost: consecutive cout blocks are consecutive lines | **32** | the block count, not 512 |

**Verified empirically on the real object rather than on paper**: enumerating
all `3 * 3 * 512 * 512 = 2359296` coordinates and counting how often each line
id comes out gives every one of the 9216 lines hit exactly **256** times,
`256 = 16 * 16` being the elements in a block, and no line unreached. That is
the surjectivity onto `[0, num_lines)` decision B23 says the engine rests on.

## File-local helpers in `block_pack.cpp`

**What they are.** Six pieces in the anonymous namespace, each existing so a
rule is written once.

| Helper | Contract |
|---|---|
| `constexpr Axis kAxes[4]` | the four axes in declaration order, written out once so the validation loop is written once and the order this file depends on is **stated** rather than inlined into a loop body |
| four `static_assert`s | pin `Axis::KH == 0` … `Axis::COUT == 3`; swap any two enumerators in `types.h` and the build stops **at the file that would have been wrong** |
| `reject(what)` | `[[noreturn]]`, throws `std::invalid_argument("BlockPackMapper: " + what)` |
| `reject_range(what)` | `[[noreturn]]`, throws `std::out_of_range("BlockPackMapper: " + what)` |
| `positive_or_reject(name, v)` | `v < 1` → `reject(name + " must be >= 1, got " + v)` |
| `checked_mul(a, b, what)` | `b > INT64_MAX / a` → `reject(what + " overflows a signed 64-bit value: a * b")`, else `a * b` |
| `blocks_covering(extent, block)` | `(int64(extent) + block - 1) / block` - blocks needed to cover `extent`, rounding **up** |
| `block_size_on(a, cin_block, cout_block)` | the divisor turning a coordinate into a block index: **1** for KH and KW, the block for CIN and COUT |

**Worked example.** One prefix, one spelling, so every message this file
produces is findable by grepping for the class name and no two of them disagree
about the punctuation. `expand` reuses the **constructor's** `positive_or_reject`
for its stride rule, so `"burst stride must be >= 1, got 0"` and
`"cin_block must be >= 1, got 0"` cannot drift into two slightly different
statements of one rule.

**Decisions.**

- **B13** - non-divisible extents **round up** rather than being rejected, and
  the corpus was measured first: all 155 layer directories have KH = KW = 3 and
  CIN, COUT in {64, 128, 256, 512}, so the rounding path is unreachable for any
  power-of-two block up to 64 and first bites at `cout_block = 128` on the
  COUT = 64 layers. Rejecting would leave D3's grid **ragged**, with different
  cells covering different subsets of the 155 layers, so a cross-layer aggregate
  would compare a 155-layer mean against a 140-layer mean and say nothing about
  it. Ceiling also keeps the tiny `3x3x1x4` fixture usable at `cin_block > 1`,
  and padding is what hardware does. Its cost is carried as D2's
  padding-fraction obligation.
- **B14** - a block larger than its extent is legal, not an error:
  `ceil(1/4) = 1` falls out of decision B13 with no special case, and rejecting
  would need a second rule that does not follow from the first.
- **B15** - both products go through `checked_mul`, which names the two factors.
  Overflow is reachable **from the type though not from the corpus**: the corpus
  maximum is 2359296 lines, twelve orders below the bound, but `WeightShape`
  carries four independent `int32`s decoded from a trace header, and the
  realistic route is plan unit A3 reading at the wrong offset. Signed overflow is
  undefined behaviour rather than wraparound, and `num_lines_` is the bound every
  later range check is written against. **v1 checked neither product** and
  `FINDINGS.md` never mentions it, which fits a corpus that never came close.

**Traps.**

- **`checked_mul` omits the `a != 0` guard the general form needs**, deliberately:
  both arguments are known positive at every call site, because the caller has
  already run `positive_or_reject` or a ceiling division of positive operands.
- **`blocks_covering`'s widening cast is placed before the `+ block - 1`**, so a
  large extent cannot wrap into a small block count.
- **`block_size_on` refuses an unknown axis rather than defaulting to 1.** A
  fallback of 1 would make an unknown axis flatten *as if it were unblocked*,
  which is a plausible wrong line id rather than a visible failure. Decision B41
  records the resulting mutation as an intentional **`allow`**: the function is
  file-local, its only caller is `line_of`, and `line_of` walks `kAxes`, so no
  input reaches the mutated branch and **no test can kill it**. The standing rule
  "a surviving mutation is a gap in the tests" is not being bent - there is no
  test to write, and the alternative, deleting an unreachable arm to satisfy a
  mutation, is a production change made for the harness's convenience.

## `BlockPackMapper::BlockPackMapper`

**What it is.** The only place the layout's invariants are established.

**Contract.**

```cpp
BlockPackMapper(WeightShape shape,
                std::int32_t cin_block,
                std::int32_t cout_block,
                std::int32_t weight_bytes);
```

Throws `std::invalid_argument`, naming the offending parameter **and its value**,
for a non-positive extent, block or element width, and for a configuration whose
line size or line count does not fit in `int64`.

**Validation order is load-bearing** and runs in the body, never the initialiser
list:

1. **every** extent `>= 1` - all four, looped over `kAxes` so the message names
   the axis without four copies of the message;
2. `cin_block >= 1`, `cout_block >= 1`, `weight_bytes >= 1`;
3. derive `n_cin_blocks_`, `n_cout_blocks_` (ceiling);
4. `line_size_bytes_ = checked_mul(checked_mul(cin_block, cout_block), weight_bytes)`;
5. `num_lines_ = checked_mul(checked_mul(checked_mul(KH, KW), n_cin_blocks_), n_cout_blocks_)`;
6. the four strides, filled **innermost first**, **after** `num_lines_`.

**Deliberately NOT checked**: `cin_block > CIN`, `cout_block > COUT`, and a block
that does not divide its extent. All are legal and all mean the same thing, one
short block. **The cost is padding, not incorrectness**, and padding is a
statistic (D2) rather than a configuration error.

**Worked example.** The asymmetric shape, which is the one that hides nothing -
with `n_cin == n_cout` a swapped stride pair changes nothing and with
`KH == KW` a dropped factor can cancel. Layer `3x5x100x50` at `cin_block = 32`,
`cout_block = 8`:

```
n_cin_blocks  = ceil(100 / 32) = 4     (floor would give 3)
n_cout_blocks = ceil(50 / 8)   = 7     (floor would give 6)
num_lines     = 3 * 5 * 4 * 7 = 420
```

| Axis | `line_stride` | `block_len` |
|---|---|---|
| KH | `5 * 4 * 7` = **140** | **3** |
| KW | `4 * 7` = **28** | **5** |
| CIN | `7` | **4** |
| COUT | **1** | **7** |

Every one of the eight numbers is distinct here. Note that
`line_stride(CIN) == 7` and `block_len(COUT) == 7` are the same number for an
unrelated reason, which is a reminder that the two functions answer different
questions and a test conflating them would still pass on this layer.

And the degenerate case the tiny verification trace needs, `3x3x1x4` at
`cin_block = cout_block = 1`:

```
n_cin = 1, n_cout = 4, num_lines = 36
strides:   KH 12, KW 4, CIN 4, COUT 1
block_len: KH  3, KW 3, CIN 1, COUT 4
```

Here `line_stride(CIN) == line_stride(KW) == 4`, because CIN has only one block
and so contributes no depth at all. **A stride table with a duplicate in it is
legal, and this is when it happens.**

**Decisions.**

- **B18** - construction failures are `std::invalid_argument` prefixed
  `BlockPackMapper: `, every message printing the offending value, and
  `std::out_of_range` is reserved for coordinate failures. The type alone then
  says whether the config or the access was wrong.
- **B16** - `line_size_bytes` is a function of the three layout parameters
  **only, never the shape**. A line size varying per layer would make L1 and L2 a
  different cache per layer and would make the size axis of the sweep
  incomparable across layers. A non-power-of-two line size is legal: `2*3*2 = 12`
  constructs fine, and a power-of-two rule would reject working configurations
  such as `12 * 8 * 64`.
- **B20** - six accessors exist on the class, otherwise the constructor's
  arithmetic is **unobservable**: `num_lines()` is the product of the two block
  counts, so swapping them, or taking a floor in one and a ceiling in the other
  and compensating, stays invisible until the flatten exists.
- **B26** - the two `checked_mul` guards on the stride fills are kept although
  they are provably unreachable today.

**Traps.**

- **Every extent is checked, not only the two that are blocked.** KH and KW are
  radices in the flatten just as much as the block counts are, so a KW of 0
  collapses the KH stride to zero and makes two different `(kh, kw)` pairs name
  the same line - a silently wrong hit rate rather than a crash.
- **A negative block is rejected explicitly rather than trusted to signedness.**
  Integer division truncates toward zero, so a negative block makes the block
  index follow the *sign of the coordinate* and the damage is a plausible
  neighbouring line rather than an obviously wrong one. Signedness alone does not
  keep a bad value visible; only a check does.
- **`weight_bytes` is not a layout radix at all** - it only scales
  `line_size_bytes`. It is checked anyway because a zero would make
  `line_size_bytes` zero, and D1 **divides** `cache_size_bytes` by it.
- **`num_lines_` is a plain `int64` member and not a `LineId`.** `Tagged` has no
  default constructor (decision B2), so a `LineId` member would have to be given
  its value in the **initialiser list**, which runs *before* the body where the
  validation lives. Storing the `int64` and wrapping it in `num_lines()` keeps
  the order **"check, then derive"** rather than "derive, then check". Every
  derived member is zero-initialised at its declaration so a constructor that
  throws leaves nothing indeterminate.
- **The strides are filled AFTER `num_lines_`, and the two `checked_mul`s there
  are provably unreachable.** `num_lines_ == KH * stride_[KH]` with `KH >= 1`
  already validated, so every stride is bounded above by `num_lines_`. They are
  written anyway because **the bound is an argument about the order of two blocks
  of code, not something the code states**: move the stride block above
  `num_lines_`, or let a later edit relax the KH check, and the guard is the
  difference between a diagnosed refusal and undefined behaviour. Two divisions,
  once per mapper. One consequence for a reviewer: a test asserting a
  `"KH line stride overflows"` message **cannot be written**, and that is a
  statement about the arithmetic rather than a gap in the suite.

## `BlockPackMapper::line_stride`

**What it is.** The radix of one axis: how far one step along it moves the line
id.

**Contract.**

```cpp
std::int64_t line_stride(Axis a) const;
```

Returns `std::int64_t` and **NOT** `LineId`. Throws `std::logic_error` for an
`Axis` outside the enumerators - an exhaustive `switch` with the throw after it,
exactly the shape `types.h`'s accessors use.

**Worked example.** Stepping one **block** on an axis moves the line id by
exactly that axis's stride, which is a second way to state what a stride is:

```
line_of(1, 2, 80, 48) = 5283
line_of(1, 2, 96, 48) = 5315    cin crosses into block 6:   5283 + 32 = + line_stride(CIN)
line_of(1, 2, 80, 64) = 5284    cout crosses into block 4:  5283 +  1 = + line_stride(COUT)
```

**Decisions.**

- **B22** - the four radices, and why COUT sits at radix 1.
- **B24** - the strides live in `stride_[4]` **indexed by
  `static_cast<int>(Axis)`**, not four named members. With the radices in an
  array, a future permutation parameter is an edit to the **one** function that
  fills the array, and `line_of`, `expand` and `locate` read it without knowing
  the order. Four named members would put the order into every reader instead.

**Traps.**

- **The `switch` looks redundant next to a plain array index, and it is not.**
  `static_cast<Axis>(9)` is well-defined C++, a raw subscript is unchecked, and
  `std::array::operator[]` is unchecked too - so the out-of-enumerator cast would
  be a **read past the end of the object**. That is the price the array form of
  decision B24 introduces and has to pay.
- **`LineId` here would not work, and that is a consequence of the typing rather
  than a style preference.** v1 returned `LineId`. `Tagged` has no arithmetic, so
  `stride * block_index` would not compile and the flatten's only spelling would
  be `.get()` at every use - and a tag that has to be stripped before every use
  is not carrying anything. The deeper reason: **a stride is a delta and a line
  id is an address**, and they have different algebra.

## `BlockPackMapper::block_len`

**What it is.** The extent along an axis measured in **whole lines**: the "how
many distinct block indices exist on this axis" number.

**Contract.**

```cpp
std::int64_t block_len(Axis a) const;
```

KH and KW report the raw extent; CIN and COUT report their **block counts**.
Throws `std::logic_error` for an `Axis` outside the enumerators.

**Worked example.** The identity worth pinning, on the running layer: the
product of the four `block_len`s is `3 * 3 * 32 * 32 = 9216`, and
`block_len(KH) * line_stride(KH) = 3 * 3072 = 9216` as well. **That second
identity holds for the outermost axis only**, and it is exactly what a swapped
pair of strides breaks.

**Decisions.**

- **B35** - `block_len` stays **public**. Decision B25 deliberately declined to
  route `line_of` through it, so a **direct** test is the only thing that can
  catch a mutation to it; making it private would make the one check that covers
  it impossible to write.
- **B46** - decision B35's closing sentence ("it gains a real library caller at
  A2d regardless") is **struck as false**. It gained none and will not, because
  decision B25 keeps `line_of` off it. Decision B25's accepted cost - that
  `block_len` needs direct tests - was recorded as *expiring* at plan unit A2d
  and **does not expire**. The next unit to assume otherwise would drop the
  direct tests.

**Traps.**

- **`block_len` is deliberately NOT what a range check compares against**, and
  this is the single most reachable mistake in the file. A burst carries
  **element** coordinates, so `expand` and `line_of` both check the **shape**,
  which is the strictly stronger bound. See `line_of`'s Traps for the numbers.
- **`block_len` has no caller inside the library.** A reader looking at the tree
  sees a public function nothing calls. That is decision B25's accepted cost,
  recorded rather than left to be rediscovered, and a mutation to `block_len`
  alone will **not** redden `line_of`.

## `BlockPackMapper::line_of`

**What it is.** The flatten: one element coordinate to one line id. Decision
B17's order made arithmetic.

**Contract.**

```cpp
LineId line_of(const Coord& c) const;

    line = sum over the four axes of  block_index(c, a) * line_stride(a)
```

where `block_index` is the raw coordinate on KH and KW and the coordinate
divided by the block size on CIN and COUT. Throws `std::out_of_range` - **not**
the constructor's `invalid_argument` - for a coordinate outside the layer's
shape. The `LineId` is constructed **once, at the end**, out of arithmetic done
in plain `int64`.

**Worked example one, an ordinary flatten** on the running layer:

```
c = (kh = 1, kw = 2, cin = 80, cout = 48)

KH:   coord 1,  in [0, 3)   ok,  block index = 1        (KH is unblocked)
KW:   coord 2,  in [0, 3)   ok,  block index = 2        (KW is unblocked)
CIN:  coord 80, in [0, 512) ok,  block index = 80 / 16 = 5
COUT: coord 48, in [0, 512) ok,  block index = 48 / 16 = 3

line = 1 * 3072 + 2 * 1024 + 5 * 32 + 3 * 1
     = 3072 + 2048 + 160 + 3
     = 5283
```

Cross-checked against the Horner spelling in `block_pack.cpp`'s header comment,
which is documentation and deliberately **not** the implementation, since it
hardcodes the order into the expression:

```
((1 * 3 + 2) * 32 + 5) * 32 + 3 = (5 * 32 + 5) * 32 + 3 = 165 * 32 + 3 = 5283
```

**Worked example two, mid-block, where the division matters.** Three coordinates
that are different elements and the same line:

```
c1 = (1, 2, 80, 48)   ->  80 / 16 = 5,  48 / 16 = 3   ->  5283
c2 = (1, 2, 85, 50)   ->  85 / 16 = 5,  50 / 16 = 3   ->  5283
c3 = (1, 2, 80, 51)   ->  80 / 16 = 5,  51 / 16 = 3   ->  5283
```

This is the whole point of the layout and not a rounding accident: a line holds
the `16 x 16` tile `cin in [80, 96) x cout in [48, 64)`, so every one of those
256 elements is the same fetch.

The boundary is what a test pushes on, since "the division truncates" and "the
division is a shift by 4" agree everywhere except at the edges:

```
line_of(1, 2, 95, 63) = 5283    the last element of that tile
line_of(1, 2, 96, 48) = 5315    cin crosses into block 6:   5283 + 32
line_of(1, 2, 80, 64) = 5284    cout crosses into block 4:  5283 +  1
```

The two extremes of the layer:

```
line_of(0, 0,   0,   0) = 0
line_of(2, 2, 511, 511) = 2*3072 + 2*1024 + 31*32 + 31 = 6144 + 2048 + 992 + 31 = 9215
```

and 9215 is `num_lines - 1`, the **tight** end of the range. A flatten with a
stride one too small produces a maximum below 9215 and nothing crashes; the ids
are just aliased, several coordinates sharing a line that should not.
**That is the failure this function is most exposed to, and it is invisible in
every check that only asks whether the answer is in range.**

Three flattens on the asymmetric `3x5x100x50` layer:

```
line_of(0, 0, 96, 48):  0*140 + 0*28 + (96/32)*7 + (48/8)*1 = 0 + 0 + 21 + 6 = 27
line_of(1, 3, 64, 16):  1*140 + 3*28 + (64/32)*7 + (16/8)*1 = 140 + 84 + 14 + 2 = 240
line_of(2, 4, 99, 49):  2*140 + 4*28 + (99/32)*7 + (49/8)*1 = 280 + 112 + 21 + 6 = 419
```

The last is `num_lines - 1 = 419` and is the interesting one: `cin = 99` is the
last legal element, `99 / 32 = 3`, the fourth block, holding only `100 - 96 = 4`
real columns out of 32; `cout = 49` gives `49 / 8 = 6`, the seventh block,
holding `50 - 48 = 2` real rows out of 8. **Line 419 is `4 * 2 = 8` real
elements in a `32 x 8 = 256` element line, and it is still a whole line.** That
is decision B13's ceiling rule and D2's padding obligation meeting in one id.

**Worked example three, a negative coordinate, and what truncation hides.**

```
line_of(1, 2, -1, 48)
```

Without the explicit check: C++ integer division truncates toward zero, so
`-1 / 16 == 0`, not `-1`, and the flatten computes

```
line = 1 * 3072 + 2 * 1024 + 0 * 32 + 3 * 1 = 5123
```

which is a **perfectly ordinary line id inside `[0, 9216)`**, belonging to the
tile `cin in [0, 16) x cout in [48, 64)`. Nothing about 5123 announces that it
came from a coordinate the tensor does not have, and the whole range
`cin in [-15, -1]` maps to block 0 the same way. What actually happens:

```
BlockPackMapper: CIN coordinate out of range [0, 512), got -1
```

thrown as `std::out_of_range`, carrying the prefix, the axis name, the legal
half-open range and the offending value. Three more, to show the check is a
range and not a sign test:

```
line_of(1, 2, -15, 48)  ->  "CIN coordinate out of range [0, 512), got -15"
line_of(0, 0, 512,  0)  ->  "CIN coordinate out of range [0, 512), got 512"
line_of(3, 0,   0,  0)  ->  "KH coordinate out of range [0, 3), got 3"
```

The overshoot matters as much as the negative: `cin = 512` divides to block 32,
`32 * 32 = 1024`, and the flatten would return **1024 more than it should**,
which on this layer walks into the next `kw` plane. **Overshoot aliases just as
silently as undershoot.**

**Decisions.**

- **B25** - `line_of` validates each coordinate against `extent_on(shape_, a)`
  and **never** against `block_len(a)`. Under `CIN = 100` with `cin_block = 32`
  there are 4 blocks: a `cin` of 100 divides to block 3 and would pass a
  `block_len` check while naming an element the layer does not have, and every
  coordinate in the padded tail `cin in [100, 128)` gets through the same way;
  `cin = -1` divides to block 0 and would pass it too. **So the `block_len`
  version passes exactly the two cases the check exists to catch.** They are also
  different quantities - a coordinate is an element index, `block_len` counts
  blocks - and comparing them is a category error that happens to typecheck
  because everything here is an integer. Tested rather than asserted: a mutation
  writing the rejected alternative was added and **dies**.
- **B34** - a coordinate inside a layer's padding is **illegal**, and the
  earlier surjectivity worry is **struck as false**: `line_of` reaches every line
  in `[0, num_lines())` even for a non-dividing layer, because the largest block
  index a coordinate produces, `(extent - 1) / block`, always equals the largest
  index the mapper allows, `ceil(extent / block) - 1`. Verified by exhaustive
  enumeration on `3x5x100x50` at 32/8: 420 lines, all 420 reached, zero
  unreachable. The surviving finding is the **fan-in histogram**: 270 lines hold
  256 coordinates, 45 hold 64, 90 hold 32, and 15 corner lines hold 8 of 256, so
  the worst line is 3 percent useful against an aggregate padding fraction of
  0.3025 - **a single scalar understates the worst line by an order of
  magnitude**, and D2's obligation is extended accordingly.

**Traps.**

- **A shared range-check path would be a shared failure mode.** Routing the check
  through `block_len` would mean one mutation to `block_len` reddens both the
  range check and the flatten at once, which is a real testability gain and is
  the argument on the other side. It also means the range check can no longer
  **disagree** with the flatten - and disagreeing is precisely its job here: the
  check is about elements, the flatten is about blocks.
- **The quotient's widening cast sits before the multiply**, so the product is
  formed in `int64` and not in `int32`.
- **The message names axis, range and value, but not the layer.** V15 wants tile,
  tick and core too; decision B37 assigns that catch-and-re-throw to whichever
  unit owns the per-tick accumulate buffer, and there is exactly **one** wrap
  site, because `expand` is the engine's only entry point and `line_of` is a
  helper the mapper calls on itself.

## `BlockPackMapper::expand`

**What it is.** The burst walk: anchor, anchor + stride, … along `b.axis`, each
element flattened, duplicates removed.

**Contract.**

```cpp
void expand(const Burst& b, std::vector<LineId>& out) const override;
```

**Validation order, which is the answer rather than something to infer**
(decision B51):

1. `b.count < 1` → `std::invalid_argument`, `"burst count must be >= 1, got N"`;
2. `b.stride < 1` → `std::invalid_argument`, `"burst stride must be >= 1, got N"`;
3. the far end `start + int64(count - 1) * stride` against `extent_on(shape_, b.axis)`
   → `std::out_of_range`;
4. the walk, each element through `line_of`, which range-checks **all four**
   coordinates.

So the malformed tier beats out-of-range, and count beats stride. Ends with
`sort`, `unique`, then one `insert` into `out`.

**Worked example one, a whole COUT burst** - the shape every trace in the 7.7 GB
corpus actually emits, so it is the case the model spends its time in:

```
b = { anchor = (kh 1, kw 2, cin 80, cout 0),  axis = COUT,  count = 512,  stride = 1 }
```

Step by step, in the order the code runs:

```
1.  count check:   512 >= 1                                        ok
2.  stride check:    1 >= 1                                        ok
3.  n     = extent_on(shape, COUT)                = 512
    start = coord_on(anchor, COUT)                =   0
    last  = start + (count - 1) * stride = 0 + 511 = 511
    far-end check: 0 <= 511 < 512                                  ok
4.  the walk, 512 elements, each flattened by line_of:
        cout =   0  ->  block 0  ->  5280
        cout =   1  ->  block 0  ->  5280
        ...
        cout =  15  ->  block 0  ->  5280
        cout =  16  ->  block 1  ->  5281
        ...
        cout = 511  ->  block 31 ->  5311
5.  sort:    already in order, so this is one comparison pass
6.  unique:  512 values collapse to 32, each id having appeared 16 times
7.  insert:  those 32 ids appended to the caller's buffer
```

The base id by hand, so 5280 is not taken on trust:

```
line = 1 * 3072 + 2 * 1024 + (80 / 16) * 32 + (0 / 16) * 1
     = 3072 + 2048 + 5 * 32 + 0
     = 5280
```

**32 contiguous ids from 512 elements.** The collapse factor is exactly
`cout_block`, 16 elements per line, which is the layout doing its job - and the
de-duplication is what makes `lines_per_burst` a real number: the engine issues
32 probes rather than 512.

**Worked example two, the same burst along CIN, correct and pathological.** The
format v2 header can say CIN and `layout.h` promises to accept it:

```
b = { anchor = (0, 0, 0, 0),  axis = CIN,  count = 512,  stride = 1 }
    -> 512 elements collapse to 32 lines at stride 32:  0, 32, 64, ..., 992
```

Strictly increasing, distinct, all inside `num_lines`. Everything `expand`
promises holds. But under the 32-set L1 every one of those lines has
`line % 32 == 0`, so **all 32 lines land in set 0**, and at 8-way the burst
evicts three quarters of itself while it is still being fetched. The spread ratio
is `1/32 = 0.031`. **The instinct on meeting this in a result is to suspect
`expand`; the response is to change the layout order, never to reject the
trace**, precisely because the mapper is behaving correctly.

**Worked example three, a burst along an axis the layout does not block:**

```
b = { anchor = (0, 0, 0, 0),  axis = KH,  count = 3,  stride = 1 }
    ->  lines 0, 3072, 6144
```

Three elements, three lines, **no de-duplication at all**, because KH's block
size is 1. The bound `lines <= count` is hit exactly here.

**Worked example four, what each check catches**, in the order the code can
produce them:

```
expand({ (1,2,80,0), COUT, count = 0, stride = 1 })
  ->  std::invalid_argument   "BlockPackMapper: burst count must be >= 1, got 0"

expand({ (1,2,80,0), COUT, count = 4, stride = 0 })
  ->  std::invalid_argument   "BlockPackMapper: burst stride must be >= 1, got 0"

expand({ (0,0,0,4), COUT, count = 4, stride = -4 })
  ->  std::invalid_argument   "BlockPackMapper: burst stride must be >= 1, got -4"

expand({ (0,0,0,511), COUT, count = 2, stride = 1 })
  ->  std::out_of_range       "BlockPackMapper: COUT coordinate out of range [0, 512), got 512"

expand({ (0,0,512,0), COUT, count = 1, stride = 1 })
  ->  std::out_of_range       "BlockPackMapper: CIN coordinate out of range [0, 512), got 512"
```

> **Correction to `A2d-EXPLAIN.md`.** That doc's negative-stride example
> (`stride = -4`) is shown there reaching the *far-end* check and reporting
> `"COUT coordinate out of range [0, 512), got -8"`. Decision B49 later made
> `stride < 1` illegal, so the stride check now fires **first** and the message
> is the stride one above. The source is the ground truth.

In the last case the far end is a perfectly legal 0, so the far-end check passes
and `line_of` catches it on the first element. **The two checks are
complementary, not redundant**: one covers the walk, the other covers the three
coordinates the walk never touches.

In every one of the five, **`out` is exactly as it was** - nothing appended, not
even the ids of elements that were legal.

**Decisions.**

- **B38** - `count < 1` is `invalid_argument`.
- **B49** - `stride < 1` is `invalid_argument`, by explicit user answer. v1's
  `TEST_DESIGN.md` group H already specified stride 0 (H3) and stride -1 (H4) as
  `invalid_argument`, and the reviewer's reference mapper `PackedRowMajor`
  **already** threw `invalid_argument` on `stride < 1`, so the reference needed
  no change at all - independent support from code written before the question
  was asked.
- **B42** - the far end is validated in `int64` **before** walking, and **the
  reason is not the obvious one**. Deleting the check does **not** stop `expand`
  throwing: `line_of` validates every element, and the monotone walk reaches an
  out-of-range coordinate while still inside `int32`, so the throw survives the
  mutation. What the check buys is the **reported value**:

  ```
  b = { (0,0,0,0), COUT, count = 5, stride = 2^30 }
      elements: 0, 2^30, 2^31, 3*2^30, 2^32

  with the far-end check:     "COUT coordinate out of range [0, 512), got 4294967296"
  without it, from the walk:  "COUT coordinate out of range [0, 512), got 1073741824"
  ```

  4294967296 is a number only 64-bit arithmetic can produce and says the burst's
  own count and stride are wrong; 1073741824 is the second element, which is
  where a one-at-a-time walk happens to stop - true, but not the fault. For a
  corpus bisect on a trace header decoded at the wrong offset, that difference
  is the whole diagnostic. **Consequence for the suite: a mutation deleting the
  check is visible only through the message text, so any future test that stops
  checking the reported coordinate silently retires the check.**
- **B43** - `expand` builds a **local** vector, sorts, uniques, then inserts into
  `out`; it does not append as it walks.
- **B51** - the validation order above.

**Traps.**

- **`expand` sorts unconditionally, and under this mapper the sort is
  unreachable.** Since `stride >= 1` (decision B49) and every line stride is
  positive, the walk is uphill for **any** radix permutation, so the sort runs
  over an already-ordered range and costs one comparison pass. It is kept, and
  decision **B50** records the `A2d expand drops the sort` mutation as an
  intentional **`allow`**: unreachable, not untested. Four reasons: decision B31
  makes strictly-increasing an obligation on the *implementation*, so removing
  the sort moves that obligation out of the code and into an unwritten argument
  about walk order; the unreachability is permutation-proof rather than lucky;
  `std::unique` removes only **ADJACENT** equals, so **de-duplication
  correctness**, not merely ordering, would come to rest on that unwritten
  argument, and a broken de-dup silently over-counts distinct lines; and the cost
  is one pass over a vector that already exists for decision B43's guarantee. The
  `allow` carries a comment recording what would make it killable again - a
  non-monotone (hashed or swizzled) mapper - so the second condition is a test to
  write rather than a decision to revisit.
- **The lines are built to the side and committed at the end, and that is not
  interchangeable with a rollback.** The alternative is `try`/`catch` with a
  `resize` back to the remembered size, and it is one line of thought away from
  being wrong (restore the size, but the caller may also have observed a
  reallocation; get the rethrow wrong and the exception type changes). Building
  to the side **cannot** be wrong: if the walk throws, `out` was never touched,
  because the only statement that touches it is the last one. The cost is one
  allocation per call.
- **The local vector is deliberately NOT `reserve`d to `b.count`.** The count is
  untrusted, and reserving it would turn a burst with a wild count into a
  `bad_alloc` **before the walk could name the coordinate that was wrong**.
- **`>= n` and `> n` in the far-end check are indistinguishable on any ordinary
  burst** - both refuse the one value they disagree on, since the walk's last
  element is then the coordinate `n`, which `line_of` rejects with the same axis
  and value. What separates them is which check fires *first*, so the burst that
  separates them has to be wrong **twice on purpose**:

  ```
  b = { (0, 0, 512, 0), COUT, count = 3, stride = 256 }
      far end = 0 + 2*256 = 512, exactly on the extent   ->  the check names COUT
      anchor's cin = 512, one past the layer             ->  the walk names CIN
  ```

  That was a surviving mutation until this case was written.

## `BlockPackMapper::locate`

**Contract.**

```cpp
Placement locate(LineId line, std::int64_t num_sets) const override;
```

Two operations, deliberately: it is called **once per line per probe, at both
levels, for the whole run**. The range check runs **before** the division.

**Worked example.**

```
num_lines() = 9216

locate(LineId{0},    32)  ->  { set 0,  tag 0 }
locate(LineId{9215}, 32)  ->  { set 31, tag 287 }      287 * 32 + 31 = 9215
locate(LineId{9216}, 32)  ->  std::out_of_range
                              "BlockPackMapper: line id out of range [0, 9216), got 9216"
locate(LineId{-1},   32)  ->  std::out_of_range
                              "BlockPackMapper: line id out of range [0, 9216), got -1"
```

**Decisions.**

- **B30** - `locate` range-checks `0 <= line < num_lines()` and throws
  `out_of_range`. The postcondition `0 <= set_index < num_sets` then holds
  because the precondition is **enforced rather than assumed**.
- **B76** - the two constructions, `SetIndex{v % num_sets}` and
  `TagId{v / num_sets}`, are the only place this file names either quantity,
  which is what keeps the arithmetic above them plain `int64`.

**Traps.**

- **The negative case is the reason the check exists, not a formality, and a test
  on the identity alone would not catch it.** `LineId` is signed (decision B5),
  C++ division truncates toward zero, and the remainder takes the sign of the
  **dividend**, so without the check:

  ```
  -1 % 32  ==  -1        (not 31)
  -1 / 32  ==   0
    ->  Placement{ set_index = -1, tag = 0 }
  ```

  `set_index = -1` then indexes a set array **from below** - and **the identity
  even still holds** (`0 * 32 + (-1) == -1`), so a test that only checked
  `line == tag * num_sets + set_index` would pass. What the range check buys is
  that the postcondition every array access is written against is a **fact**.
- **`num_lines_` is an exact bound only because the constructor's `checked_mul`s
  made it one.**

## `BlockPackMapper::num_lines`, `line_size_bytes`

**Contract.**

```cpp
LineId       num_lines()       const override { return LineId{num_lines_}; }
std::int64_t line_size_bytes() const override { return line_size_bytes_; }
```

Both are **pure derivation** from the constructor arguments, so they are
one-liners over members the constructor already checked. Neither reads the shape
at call time and **neither can fail**.

## `BlockPackMapper::line_size_terms`

**Contract.**

```cpp
std::string line_size_terms(std::int64_t /*line_bytes*/) const override;
```

Returns the three constructor arguments the line size is the product of, in the
order the constructor multiplies them. **Out of line** rather than beside the
one-liner accessors in the header, because it builds a string, which is the
constructor's file's business.

**Worked example.**

```
BlockPackMapper(WeightShape{3,3,512,512}, 16, 16, 1).line_size_terms(256)
    -> "cin_block 16 x cout_block 16 x weight_bytes 1"
```

**Traps.**

- **The product itself is not repeated, and the passed-in `line_bytes` is
  deliberately ignored.** The caller has already printed the product, and a
  second copy is a second thing that can disagree with the first. This override
  names the factors it multiplies **its own members** out of, so it needs nothing
  from the caller; the parameter exists for the interface's default.

## The derived-state accessors

**What they are.** Six one-liners: `shape()`, `cin_block()`, `cout_block()`,
`weight_bytes()`, `n_cin_blocks()`, `n_cout_blocks()`.

**Contract.** `const`, non-failing, returning the constructor's inputs and the
two derived block counts. The engine never sees them - it only ever uses the
four `AddressMapper` members.

**Decisions.**

- **B20** - they exist because **without them the constructor's arithmetic is
  unobservable**. `num_lines()` is `KH * KW * n_cin_blocks * n_cout_blocks`, so
  swapping `n_cin_blocks_` and `n_cout_blocks_`, or taking a floor where the
  layout takes a ceiling in one of them and compensating in the other, leaves
  `num_lines()` **unchanged**. Reporting the two block counts separately is what
  lets construction be checked on its own terms rather than through code that did
  not exist yet.

**Traps.**

- **The block-count members are `int64`, not `int32`.** A block count is a factor
  of a line count and the line count is a `LineId`, which is `int64`; **keeping
  the factors narrower than the product is the boundary the v1 signedness class
  lived on** - v1's `n_cin_blocks()` returned `int64` while `num_lines()` returned
  `uint64` and both fed the same expression.

---
---

# `native/include/wcache/cache.h`

The array interface. **`cache.h` includes `types.h` and nothing else**, and that
is a checked property, not a habit: `compile_fail.sh`'s `tryC` preamble compiles
a translation unit including `cache.h` alone, so a case compiled with it
**proves** the array interface needs no layout header. If `CacheArray` ever grows
a dependency on `AddressMapper`, those cases start failing rather than being
carried silently by a preamble that already included it.

## `Candidate`

**What it is.** One entry of the set competing for replacement, as handed to
`ReplacementPolicy::pick_victim`.

**Contract.**

```cpp
struct Candidate {
    SlotId slot;
    LineId line;  // NoLine when the slot is free
};
```

**Worked example.** Why the line travels **beside** the slot rather than being
looked up afterwards: a policy that has to exclude a line - the one with an
outstanding MSHR, say - would otherwise need a reference back to the array and a
slot-to-line accessor, which puts the array **inside the module the array/policy
split exists to keep out of it**. Pairing them costs nothing: the array is
already reading exactly these cells to enumerate the set.

## `InsertResult`

**What it is.** What an insert displaced.

**Contract.**

```cpp
struct InsertResult {
    bool   evicted;       // the slot held a line, which this insert displaced
    LineId evicted_line;  // that line, or NoLine when `evicted` is false
};
```

**Worked example.** Why both fields, when a bool looks sufficient: the level
counts evictions, **and** under `inclusion = inclusive` it has to know **WHICH**
line left the L2 in order to back-invalidate it out of the L1s. Reporting only a
bool would force the caller to read the slot **before** inserting - the same read
done twice, and a rule that is easy to forget once and then undercount for the
whole sweep.

**Traps.**

- The two fields must never disagree, and the implementation guarantees that
  **by construction** rather than by discipline. See `SetAssociativeArray::insert`.

## `CacheArray`

**What it is.** The abstract array: geometry and storage. What is here is the map
from a `LineId` to the **locations that may hold it**, plus one `LineId` per
location.

**Contract.** The array/policy split named in plan 2.2 is a **hard constraint**
on this file rather than a description of it: *"the array knows geometry and
holds no recency, timestamps, or insertion order; the policy holds all of those
and knows nothing about sets or ways."* So nothing a `ReplacementPolicy` would
own may appear here.

The handle that crosses the split is `SlotId`, and that is what makes the split
implementable at all: it is **dense** in `[0, num_slots())` so a policy indexes a
flat vector with it and never computes a set index, and it is **stable** while a
line stays resident so a stamp a policy wrote on a fill still names the same
location on the next access.

Nothing below mentions a set or a way, because a **fully associative array** is
the other implementation this interface is shaped to admit.

**Decisions.**

- **B54** - all five verbs are in the interface from the start, including
  `invalidate`, per N8. Deferring `invalidate` is the v1 mistake the plan
  reversed.
- **B67** - copy and move are `protected` and `= default`, with a defaulted
  default constructor declared alongside.

**Traps.**

- **The verb count is five where an earlier reading said three, and two of the
  five are one idea split.** With replacement in another module this class
  **cannot choose a victim**, so all it can offer is the candidate set - but the
  case that needs no policy at all, a set with a free way, still has to be
  answered by the module that knows which ways are free. Folding the free case
  into the candidate list would oblige **every** policy to re-implement "prefer
  an empty way", and a policy that got it wrong would evict a live line while a
  way sat empty: silent, and visible only as a hit rate slightly below the truth.

### `CacheArray::probe`

**Contract.**

```cpp
virtual SlotId probe(LineId line) const = 0;
```

The slot holding `line`, or `NoSlot` if it is not resident. `const`, **and free
of side effects**, which plan 2.2 states outright: *"probe is const and is NOT an
access. The engine calls policy.on_hit explicitly."*

**Traps.**

- **The usual way this requirement fails is not by someone writing `mutable`.**
  It is by a probe **recording that it happened** - a counter, a last-touched
  slot, a small cache of the last looked-up line - and a later verb reading it
  back. The `const` keyword does not stop that: `mutable` members and pointed-to
  state are both reachable from a `const` member function. In this tree the
  property is **structural** and can be checked by reading the concrete class's
  private section in full - see `SetAssociativeArray::probe`.
- Two things rest on it: a speculative lookup must not perturb the recency stack,
  and 4.6's prefetcher tests residency on a path that must not touch replacement
  state **at all** (decision B11, I15) - a prefetch that finds the line resident
  drops it and records nothing, which is only implementable if probing and
  recording a use are two separate calls.

### `CacheArray::free_slot`

**Contract.**

```cpp
virtual SlotId free_slot(LineId line) const = 0;
```

A free slot among those that may hold `line`, or `NoSlot` when they are all
occupied. **Call it before `victim_candidates`**: a free slot costs no eviction,
so no policy is consulted and none can get it wrong.

### `CacheArray::victim_candidates`

**Contract.**

```cpp
virtual void victim_candidates(LineId line, std::vector<Candidate>& out) const = 0;
```

**Replaces** the contents of `out` with the slots competing to hold `line`. The
candidate set is handed over whole, and **no policy may depend on its order**.

**Traps.**

- **Replaces rather than appends, which is the opposite of
  `AddressMapper::expand`, and deliberately so.** `expand` appends because its
  documented use accumulates a whole tick across cores into one buffer; a
  candidate list is **one set's worth**, consumed immediately by one
  `pick_victim` call. An appending version would let a caller that forgot to
  clear pick a victim from a previous fill **in a DIFFERENT set**, and the line
  would then be stored where `probe` can never look for it: no crash, just a hit
  rate quietly below the truth for the whole run. Buffer reuse is unaffected,
  since clearing keeps the capacity.

### `CacheArray::insert`

**Contract.**

```cpp
virtual InsertResult insert(LineId line, SlotId slot) = 0;
```

Stores `line` in `slot`, which **must** be one of the slots that may hold `line`,
obtained from `free_slot` or from `pick_victim` over `victim_candidates`. That
membership is a **caller precondition** the interface states and the
implementation does not check.

### `CacheArray::invalidate`

**Contract.**

```cpp
virtual void invalidate(SlotId slot) = 0;
```

Drops whatever `slot` holds, leaving it free. Invalidating a free slot is a
no-op only in the sense that it leaves it free. **The policy's `on_invalidate` is
the caller's to make**, exactly as `on_hit` is after a probe: this module does
not name a policy.

**Traps.**

- On the interface from the start (N8) although nothing uses it until plan unit
  C4 builds inclusion, because **a level that cannot invalidate cannot implement
  the inclusive branch at all**, and an interface that gains a verb later gets
  **one** implementation of it rather than every implementation.

### `CacheArray::num_slots`

**Contract.**

```cpp
virtual std::int32_t num_slots() const = 0;
```

Slot ids are exactly `[0, num_slots())`. Present so a policy can size its
per-slot state **from this interface alone**; handing it `num_sets` and
`associativity` instead would put the geometry back into the module the split
keeps free of it.

**Traps.**

- **`int32`, matching `SlotId`'s representation rather than the `int64` the
  geometry is computed in.** A slot count a `SlotId` cannot name is a geometry
  whose upper slots are **unreachable** - storage the sweep paid for and never
  used, showing up only as a hit rate a few points below the truth. Returning
  `int32` makes that unrepresentable and pushes the refusal into the concrete
  constructor (decision B64).

### `CacheArray`'s protected copy/move block

**Contract.**

```cpp
protected:
    CacheArray()                             = default;
    CacheArray(const CacheArray&)            = default;
    CacheArray(CacheArray&&)                 = default;
    CacheArray& operator=(const CacheArray&) = default;
    CacheArray& operator=(CacheArray&&)      = default;
```

**Worked example.** Decided by measurement, and **the original premise was half
wrong**. By-value copy through the base was *never* reachable, because the class
is abstract:

```
error: cannot allocate an object of abstract type 'wcache::CacheArray'
```

so the `compile_fail.sh` cases that pass a base by value are proving
**abstractness**, not copy control. What *was* reachable is assignment through
base **references**, and it compiled and sliced:

```cpp
A a1;  A a2;  a2.derived_state = 9;
CacheArray& r1 = a1;  CacheArray& r2 = a2;
r1 = r2;                    // compiles
return a1.derived_state;    // 7, not 9
```

Exit status **7**: the assignment copied the base subobject, which holds nothing,
and left the derived state untouched. **A silent partial write** - for an array
that is a half-assigned cache still answering probes, reporting a hit rate for a
geometry no level ever had. Both halves of the fix verified:

```
r1 = r2;                              error: 'operator=' is protected within this context
SetAssociativeArray b = a;            compiles and runs
std::vector<SetAssociativeArray> v;   compiles and runs
```

**Decisions.**

- **B67** - protected rather than **deleted**, and that is the half worth
  stating: deleting would take the operations away from **derived** classes as
  well, and the engine holds one L1 per core over a swept range of 8 to 256
  cores, so a container of concrete arrays is the ordinary case rather than a
  hypothetical one. Protected leaves a derived class copyable **AS ITSELF**,
  where a copy is whole, and leaves the base unusable as the source or target of
  one. Non-vacuity was proven by reverting `protected` to `public` and watching
  the two guarding compile cases stop failing.

**Traps.**

- **The defaulted default constructor is not decoration; it is the trap in the
  change.** Declaring **any** constructor suppresses the implicitly generated
  default one, so without `CacheArray() = default;` every array in the tree - the
  fakes, the `ARRAY` fake in `compile_fail.sh`, and `SetAssociativeArray` itself
  - **stops constructing**. That one line is what keeps the rest of the change
  invisible.

---
---

# `native/include/wcache/set_associative.h` + `native/src/set_associative.cpp`

The set-associative `CacheArray`. **This is also the direct-mapped
implementation**, at associativity 1: every set has one way, `free_slot` answers
the cold case, and the candidate list has a single entry that every policy must
return. A third class would be this code with the loops unrolled to one
iteration.

## File-local helpers in `set_associative.cpp`

| Helper | Contract |
|---|---|
| `reject(what)` | `[[noreturn]]`, `std::invalid_argument("SetAssociativeArray: " + what)` |
| `positive_or_reject(name, v)` | one spelling of the positivity rule for the three non-positive cases, which differ only in which quantity they name |
| `as_size(v)` | the **one** `int32` to `std::size_t` conversion in the file |

**Traps.**

- **`as_size` exists so the arithmetic above it stays signed.** `std::vector`
  sizes with an unsigned `size_type`, so the signed slot count has to convert on
  the way into storage. With the cast spread across subscript expressions
  instead, a negative count would silently become a huge in-range-looking size at
  **each** of them, and `-Wsign-conversion` would be answered with several casts
  rather than one reviewable site.

## `SetAssociativeArray::SetAssociativeArray`

**What it is.** The geometry: turn `cache_size_bytes` and `associativity` into
sets, ways and slots, or refuse.

**Contract.**

```cpp
SetAssociativeArray(const AddressMapper& mapper,
                    std::int64_t cache_size_bytes,
                    std::int32_t associativity);
```

Holds the mapper **by reference**; the mapper must outlive the array, which costs
nothing since one mapper instance serves the whole hierarchy. Throws
`std::invalid_argument`, naming the offending value, for a non-positive size,
associativity or line size; a size that is not a whole number of lines; an
associativity larger than the whole cache; a line count that does not divide into
sets; and a geometry with more slots than a `SlotId` can name.

**Validation order, load-bearing and stated in the file rather than inferred:**

1. `cache_size_bytes >= 1`, `associativity >= 1` - **first, because every check
   after them divides by one of the three values**;
2. `line_bytes = mapper.line_size_bytes()`, **read once**, `>= 1` - a line size
   of 0 is a division by zero at step 3 rather than a diagnosable refusal;
3. **byte exactness**, `cache_size_bytes % line_bytes`, before `total_lines` is
   derived, **because the line count means nothing if the division that produced
   it was not exact**;
4. `total_lines > INT32_MAX` - placed here because it is a fact about the size
   and the line size **alone**, so a cache too large for a `SlotId` is reported as
   that whatever the associativity is;
5. `associativity > total_lines`, **BEFORE** the divides-into-sets check;
6. `total_lines % associativity`;
7. then, and only then, the assignments and `slots_.assign(num_slots_, NoLine)`.

**Worked example, one construction end to end.** A real configuration: the
`3x3x512x512` layer at `cin_block = cout_block = 16`, `weight_bytes = 1`, with a
64 KB L1 at associativity 8.

```cpp
const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);
SetAssociativeArray  l1(m, 65536, 8);
```

Measured, not computed by hand:

```
line_size_bytes = 256   line_size_terms = cin_block 16 x cout_block 16 x weight_bytes 1
num_lines       = 9216  (the whole tensor; the cache holds a fraction of it)
```

| Step | What runs | Value |
|---|---|---|
| 1 | `cache_size_bytes >= 1` | 65536, passes |
| 2 | `associativity >= 1` | 8, passes |
| 3 | `line_bytes = mapper.line_size_bytes()`, `>= 1` | **256**, read once, passes |
| 4 | `65536 % 256 != 0` ? | 0, passes |
| - | `total_lines = 65536 / 256` | **256** |
| 5 | `total_lines > INT32_MAX` ? | no, passes |
| 6 | `associativity > total_lines` ? | 8 > 256 is false, passes |
| 7 | `total_lines % associativity != 0` ? | 256 % 8 = 0, passes |
| - | assign | `associativity_ = 8`, `num_sets_ = 32`, `num_slots_ = 256` |
| - | `slots_.assign(256, NoLine)` | 256 free slots, the cold start |

So: **32 sets of 8 ways, 256 slots, slot ids `[0, 256)`.**

**Worked example, the four refusals, all measured on that same geometry:**

```
SetAssociativeArray l1(m, 65000, 8);
  SetAssociativeArray: cache_size_bytes 65000 is not a whole number of 256-byte lines
                       (cin_block 16 x cout_block 16 x weight_bytes 1)

SetAssociativeArray l1(m, 65536, 3);
  SetAssociativeArray: 256 lines do not divide evenly into sets of 3

SetAssociativeArray l1(m, 65536, 512);
  SetAssociativeArray: associativity 512 exceeds the whole cache of 256 lines

(a one-byte-line mapper at 2147483648 bytes)
  SetAssociativeArray: 2147483648 lines exceeds the 2147483647 slots a SlotId can name
```

The middle two are why steps 5 and 6 stay **separate** rather than being folded.
Both are "the associativity is wrong", and one says *the cache cannot be cut into
sets of that width* while the other says *the cache is smaller than one set*. An
implementation that dropped either check would still throw on the other case,
which is exactly the state in which the suite cannot tell that one of them is
gone.

**Decisions.**

- **B61** - the class lives in its own header/`.cpp` pair, **not** as a second
  class in `cache.h`. Not a style call: it holds an `AddressMapper`, so declaring
  it in `cache.h` would make `cache.h` include `layout.h`, and `tryC` exists to
  fail exactly then. Folding it in would not have *broken* those cases; it would
  have quietly made them **stop meaning anything**, which is worse.
- **B62** - the seven-step order above, and **every one throws, none asserts**,
  because all seven read config fields and an `assert` compiled out under
  `-DNDEBUG` turns a rejected configuration into a silently wrong simulation.
  Step 6 was checked and adds **no** rejection the single division would not have
  made; it only changes which message comes out, which makes it a **message**
  decision rather than a validation one.
- **B63** - the plan's single division `size / (line * assoc)` is **split in
  two**, and the equivalence was verified rather than asserted: **14,400,000
  triples, 0 mismatches**, plus a `grep` confirming no `*` in the constructor
  forms the product.
- **B64** - `total_lines > INT32_MAX` throws: a rejection the plan does not list,
  forced by `num_slots()` returning `int32`. The bound is **exactly** `INT32_MAX`
  and not one less, because the largest slot id at that count is `INT32_MAX - 1`,
  one short of `NoSlot`.
- **B65** - `associativity` is `int32` (a way count, and a way index is the same
  quantity class as a slot id) and `cache_size_bytes` is `int64` (it is divided
  by `line_size_bytes()`, which is `int64`); slot storage is allocated **here**,
  not deferred, because a validated geometry that allocates nothing is a
  computation with no witness.
- **B66/B79** - the exactness message names the **terms**, built from the single
  read.
- **B72** - the `INT32_MAX` boundary is pinned by **message discrimination in
  both directions**, with a second refusal waiting behind each, because the
  obvious test allocates about 17.2 GB and the obvious pair allocates it twice.

**Traps.**

- **Splitting the division is a correctness change, not a rearrangement.**
  `line_size_bytes()` is bounded only by `int64`. The mapper

  ```cpp
  BlockPackMapper(WeightShape{1,1,1,1}, INT32_MAX, INT32_MAX, 2)
  ```

  is accepted and reports `line_size_bytes() == 9223372028264841218` - about 9.2
  exabytes per line. Multiplying that by any associativity above 1 is **signed
  overflow**, which is undefined behaviour rather than wraparound: the compiler
  is entitled to assume it did not happen and optimise on that basis, so the
  failure is not "a wrong number" a later check might catch, it is **a program
  with no defined meaning**. No cast rescues it, since both operands are already
  `int64`. The split form only ever *divides* by that number, and the exabyte
  mapper is refused at step 3 with a well-formed message. That also closes the
  reachable route to `num_sets == 0`.
- **Refusing rather than flooring is a requirement, not fastidiousness.** D2
  echoes `cache_size_bytes` **verbatim** into every results row, so a silently
  floored geometry would make the whole sweep attribute its hit rates to a
  capacity the simulator never had.
- **`num_sets_ >= 1` follows from the checks rather than needing one of its
  own**: `total_lines >= 1` because `cache_size_bytes >= 1` divided exactly by
  `line_bytes`, `associativity <= total_lines`, and the second division is exact.
  That is what makes `locate(line, num_sets_)` safe from `locate`'s unvalidated
  division **for calls through THIS array**. It does not answer who owns that
  guard in general.
- **`slots_` is a `std::vector` filled with an explicit `NoLine` rather than
  sized and left to value-initialise**, because `LineId` has no default
  constructor (decision B2).
- **The accepted side of the `INT32_MAX` bound can only be tested by
  discrimination.** `SetAssociativeArray(one_byte_line_mapper, 2147483647, 1)` is
  accepted, and it was run: it constructs, reports `num_sets = 2147483647`, and
  allocates about **17 GB**. A test that constructs it is a test that needs 17 GB.
  That figure is itself a finding: it bounds what a `SlotId` can **name**, which
  is a type fact, and does not bound what a machine can **hold**. Four sites now
  share that row (the exabyte mapper, `expand` walking `2^31` elements, this
  array's `slots_`, and `StampPolicy`'s `stamp_`), and decision **B80** assigns
  all four to D1 with **one shared bound** rather than four scattered ones,
  because the question is a modelling one (what can a machine hold) rather than a
  typing one.

## `SetAssociativeArray::base_slot` (private)

**What it is.** The lowest slot id of the set `line` competes in, so the set's
slots are exactly `[base_slot(line), base_slot(line) + associativity())`. The one
piece of geometry all three read-only verbs share.

**Contract.**

```cpp
std::int32_t base_slot(LineId line) const;
```

Throws `std::out_of_range`, **from `locate`**, for a line outside
`[0, mapper.num_lines())`. It adds no rejection of its own.

**Worked example.** Take `LineId{1000}` on the 32-set, 8-way L1 above
(`1000 < 9216`, so it is in range):

```
locate(1000, 32)  ->  Placement{ SetIndex{1000 % 32}, TagId{1000 / 32} }
                  ->  Placement{ SetIndex{8},         TagId{31}        }
                                                       31 * 32 + 8 == 1000

base_slot(1000) = 8 * 8 = 64

slot 64  65  66  67  68  69  70  71          <- set 8, all eight ways
```

**Why a set is a contiguous run:** slots are laid out **set-major** - set 0 owns
`[0, 8)`, set 1 owns `[8, 16)`, … set 31 owns `[248, 256)`. Every set has the
same width, so set *s* starts at `s * associativity()`. There is no per-set
indirection, no free list, and no way index stored anywhere: **the position in
`slots_` IS the way index.**

**Decisions.**

- **B85** - the helper is `base_slot(line)` returning the **base slot** as an
  `int32`, not decision B65's `set_of` returning a set index. The name deviation
  is recorded rather than glossed. It returns the base because **the set index
  alone is used by nothing**: `probe`, `free_slot` and `victim_candidates` each
  want the base, so returning a `SetIndex` and multiplying at three call sites
  would be the same expression written three times.
- **B90** - the `tag * num_sets` signed-overflow hazard is **AVOIDED** at this
  layer, not bounded.

**Traps.**

- **It reads `set_index` and never `tag`, and that is worth stating rather than
  noticing.** The identity `line == tag * num_sets + set_index` makes the tag look
  like the natural thing to compare a resident line against, and forming
  `tag * num_sets` is signed overflow for a large enough tag, which `Placement`
  has **no precondition against**. **No expression anywhere in this class forms
  that product** - `slots_` stores whole line ids, so a way scan compares line ids
  directly. That is the same defensive shape decision B63 took when it split one
  division in two precisely so `line_size_bytes * associativity` would never be
  formed.
- **The cast is safe rather than hopeful, and both halves are needed.** `locate`
  range-checks the line and bounds the set index at `[0, num_sets_)`, so the
  product is at most `(num_sets_ - 1) * associativity_ == num_slots_ -
  associativity_`; and the constructor bounded `num_slots_` at `INT32_MAX`. So
  the multiply is done in `int64` and the result is **known** to fit an `int32`
  before the cast.

## `SetAssociativeArray::slot_or_reject` (private)

**Contract.**

```cpp
std::int32_t slot_or_reject(const char* verb, SlotId slot) const;
```

The shared bound check of `insert` and `invalidate`. Returns the slot's
representation, so a caller that has checked it does not unwrap it a second time;
throws `std::out_of_range` naming `verb` otherwise:

```
SetAssociativeArray::insert: slot 2147483647 is outside [0, 256)
```

**Traps.**

- **One check, so the two verbs cannot disagree about whether the top of the
  range is open or closed.** It is named for the **verb** rather than for the
  class, because a caller with a stray slot id needs to know which call it
  reached.

## `SetAssociativeArray::probe`

**Contract.**

```cpp
SlotId probe(LineId line) const override;
```

Scans at most `associativity()` cells from `base_slot(line)`; returns the slot
holding `line`, or `NoSlot`. Throws only what `locate` throws.

**Worked example.** Cold array, all 256 slots hold `NoLine`:

```
probe(1000)  ->  base = 64; compares slots_[64..71] against LineId{1000}
             ->  all eight hold NoLine
             ->  NoSlot                       (SlotId{2147483647})
```

After `insert(1000, SlotId{64})`:

```
probe(1000)  ->  base = 64; slots_[64] == LineId{1000} on the first comparison
             ->  SlotId{64}
```

**Note what did NOT happen: nothing recorded the hit.** The engine calls
`policy.on_hit(SlotId{64})` itself.

**Decisions.**

- **B86** - `probe` scans the ways and returns `NoSlot` on a miss, and 2.2's
  "const and not an access" is **enforceable here rather than asserted**.
- **B102** - the property is proven with **two arrays built in lockstep**, not a
  before/after snapshot: one array is hit with 20,000 random probes and then
  compared **both** to its own pre-storm snapshot **and** to the untouched twin.

**Traps.**

- **`probe` is `const` AND non-accessing because the class has no mutable state
  at all** - that is structural, not a rule someone is keeping, and it is
  checkable by reading the private section in full:

  ```cpp
  const AddressMapper& mapper_;
  std::int32_t associativity_ = 0;
  std::int64_t num_sets_      = 0;
  std::int32_t num_slots_     = 0;
  std::vector<LineId> slots_;
  ```

  Three geometry scalars fixed at construction, one reference to a mapper whose
  own state is fixed at construction (and whose `locate` is a `const` virtual, so
  an override cannot mutate it either), and the slot array, which `probe` reads
  and only the two non-`const` verbs write. **There is nothing for a probe to
  record.**
- **Compares whole line ids rather than tags.** Within one set the set index is
  constant, so comparing line ids **is** exactly comparing tags and is equally
  free of aliasing; it also means no expression in this file forms
  `tag * num_sets`, and it lets `insert` report the evicted line without
  reconstructing it. It costs nothing, since a tag is an `int64` here too.
- **`NoLine` cannot be mistaken for a resident line here, and that is a fact
  rather than a hope**: it is `INT64_MAX`, one past what any mapper can produce,
  and `locate` has already refused any line outside `[0, num_lines())`.

## `SetAssociativeArray::free_slot`

**Contract.**

```cpp
SlotId free_slot(LineId line) const override;
```

Returns the **LOWEST** free way of the set, or `NoSlot`. Throws only what
`locate` throws.

**Worked example.**

```
cold set 8:  scan slot 64: NoLine -> answer
free_slot(1000) -> SlotId{64}
```

**Decisions.**

- **B87** - the lowest, not an arbitrary one. The plan does not say which free
  way and any choice works, so the decision is to pick the one that makes the
  answer a **function of the array's state alone**.

**Traps.**

- **The ordering is what makes fixtures below this class writable at all.** An
  implementation free to return an arbitrary free way would satisfy every word of
  `CacheArray`'s contract, and a test could then only say "line 40 is *somewhere*
  in `[64, 72)`" - which asserts almost nothing. Two arrays given the same insert
  sequence agree **slot for slot**, not just set for set, and the cold-start
  behaviour of the whole model is deterministic without a rule anywhere else
  having to say so.

## `SetAssociativeArray::victim_candidates`

**Contract.**

```cpp
void victim_candidates(LineId line, std::vector<Candidate>& out) const override;
```

Computes `base_slot` **BEFORE** `out.clear()`, then pushes one `Candidate` per
way of the set. Throws only what `locate` throws.

**Worked example.** Fill set 8 completely. The lines that map to it are the ones
with `line % 32 == 8`, and each was placed by `free_slot` returning the lowest
free way, so the eight arrived in slot order:

| line | tag | slot |
|---|---|---|
| 8 | 0 | 64 |
| 40 | 1 | 65 |
| 72 | 2 | 66 |
| 104 | 3 | 67 |
| 136 | 4 | 68 |
| 168 | 5 | 69 |
| 200 | 6 | 70 |
| 232 | 7 | 71 |

Now line 1000 is requested again:

```
probe(1000)      -> NoSlot        (none of slots 64..71 holds 1000)
free_slot(1000)  -> NoSlot        (none of slots 64..71 holds NoLine)
victim_candidates(1000, out):

  out = [ {64, 8}, {65, 40}, {66, 72}, {67, 104},
          {68, 136}, {69, 168}, {70, 200}, {71, 232} ]
```

**Decisions.**

- **B88** - `base_slot` runs **before** `out.clear()`. It is the assign-side
  analogue of `expand`'s rule that a range failure throws before any output is
  produced.

**Traps.**

- **The order is the contract, not tidiness.** `base_slot` is the **only**
  expression in the function that can throw. Putting it first means **a call that
  throws leaves `out` exactly as it was** rather than emptied - which matters
  because the caller's buffer is reused, and with `clear()` first a caller that
  catches and continues finds its buffer silently emptied by a call that did
  nothing else.
- **Free ways are reported as candidates carrying `NoLine` rather than
  omitted.** In the engine there are never any, because this verb is reached only
  after `free_slot` answered `NoSlot`. Reporting them keeps the list one **whole
  set**, which is what makes "every slot appears under exactly one set" checkable
  from outside.

## `SetAssociativeArray::insert`

**Contract.**

```cpp
InsertResult insert(LineId line, SlotId slot) override;
```

Range-checks the **slot** via `slot_or_reject` (`std::out_of_range`); reads the
previous occupant; writes; returns one of exactly two literals.

**Worked example, no eviction:**

```cpp
const std::int32_t s = slot_or_reject("insert", slot);   // 64, in [0, 256)
const LineId previous = slots_[64];                      // NoLine
slots_[64] = LineId{1000};
return InsertResult{false, NoLine};

insert(1000, 64) -> InsertResult{ evicted = false, evicted_line = NoLine }
```

**and over an occupant**, when the policy picks slot 65 from the full set above:

```cpp
const LineId previous = slots_[65];    // LineId{40}
slots_[65] = LineId{1000};
return InsertResult{true, LineId{40}};

insert(1000, 65) -> InsertResult{ evicted = true, evicted_line = LineId{40} }
```

and `probe(40)` now returns `NoSlot` while `probe(1000)` returns `SlotId{65}`.

**Decisions.**

- **B89** - `evicted == (evicted_line != NoLine)` **by construction**, not as a
  second flag.
- **B91** - the deliberate asymmetry in range checking.

**Traps.**

- **`evicted` is derived from `evicted_line` so the two cannot disagree.** Two
  returns, and neither can produce a pair that has no meaning (`evicted = true`
  with `evicted_line = NoLine`, or `false` with a real line). The alternative -
  writing `InsertResult{previous != NoLine, previous}` once, or worse, setting the
  flag on one path and the line on another - leaves that state open. A caller
  handling the inclusive branch reads the **flag** to decide whether to
  back-invalidate and the **line** to know what to back-invalidate; those two
  reads must agree, and here they cannot fail to, because both producible
  `InsertResult`s are consistent as literals.
- **The slot is range-checked and the line is NOT, which is deliberate rather
  than an omission.** An out-of-range slot is an **out-of-bounds write** into
  `slots_` - undefined behaviour, and reachable by one plausible mistake, since
  `insert(line, free_slot(line))` without checking for `NoSlot` passes
  `INT32_MAX` straight in. A line outside the mapper's range is merely a **stored
  value**, and every path that reads it back goes through `locate` and is refused
  there: wrong, but neither silent nor memory-unsafe.
- **What is NOT checked, and is a caller precondition `cache.h` states: that
  `slot` is one of the slots that may hold `line`.** Checking it costs a `locate`
  on every fill, and the callers that can get it wrong are `pick_victim`
  implementations.

## `SetAssociativeArray::invalidate`

**Contract.**

```cpp
void invalidate(SlotId slot) override;
```

One line: `slots_[as_size(slot_or_reject("invalidate", slot))] = NoLine;`.

**Worked example.** After `invalidate(SlotId{64})`, slot 64 is free again and a
later `probe(1000)` returns `NoSlot`.

**Traps.**

- **Invalidating a slot that is already free needs no branch**: the write is the
  same either way, which is why `cache.h`'s "no-op" wording is literal.

## `num_slots`, `num_sets`, `associativity`

**Contract.**

```cpp
std::int32_t num_slots()     const override { return num_slots_; }   // on CacheArray
std::int64_t num_sets()      const { return num_sets_; }             // NOT on CacheArray
std::int32_t associativity() const { return associativity_; }        // NOT on CacheArray
```

**Decisions.**

- **B20's argument reused** - all three exist because **without them the
  constructor's arithmetic is unobservable**: `num_slots` alone is the same 256
  whatever the associativity, so an implementation that reported `num_sets` where
  the associativity belongs, or that floored where it should refuse, would look
  **identical from outside** until the verbs existed to contradict it.

**Traps.**

- **`num_sets` and `associativity` are deliberately NOT on `CacheArray`.** A
  fully associative array has no meaningful set count, and putting them on the
  interface would **invite a policy to read them**, which is the array/policy
  split leaking.

---
---

# `native/include/wcache/policy.h`

The abstract replacement policy. The mirror constraint of `cache.h`'s: *"the
policy holds all of the recency, timestamps and insertion order, and knows
nothing about sets or ways."* So **nothing about sets, ways, associativity or
line addresses may appear in what a policy is TOLD.**

## `ReplacementPolicy`

**What it is.** The four verbs of plan 2.2, in the order it lists them.

**Contract.**

```cpp
class ReplacementPolicy {
public:
    virtual ~ReplacementPolicy() = default;
    virtual void   on_hit(SlotId slot)        = 0;
    virtual void   on_fill(SlotId slot)       = 0;
    virtual void   on_invalidate(SlotId slot) = 0;
    virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;
protected:
    // copy/move protected and defaulted, for decision B67's reason
};
```

**Three notifications and one question, and that asymmetry is the design**: the
array reports what happened to a slot, and the policy is asked only at the point
where the array genuinely cannot answer. **Nothing here returns state**, because
a policy's state is its own and no other module reads it - D2's victim-age
instrument is a statistic computed **at the eviction site**, not a getter on this
interface.

**Decisions.**

- **B92** - the abstract interface lives in its own `policy.h`, with the
  concrete stamp policies in `stamp_policy.h`/`.cpp`. Not symmetry: a
  `compile_fail.sh` case compiled against `policy.h` **alone** proves the
  interface needs nothing but a `SlotId` and a `Candidate`, and folding the
  implementations in would make that **unprovable**.
- **B103** - that proof is the `tryR` preamble, 11 cases, all 9 rejects proven
  non-vacuous. It is the mirror of `tryC`.
- **B67 reused** - copy and move are protected and defaulted for exactly
  `CacheArray`'s measured reason: through two base references `p1 = p2` would
  compile and assign the base subobject only, leaving the derived recency state
  untouched. **For a policy that is a half-assigned eviction order, reporting a
  plausible hit rate for a history it never had.** Protected rather than deleted
  keeps a derived policy copyable as itself, which matters because the engine
  holds one L1 policy per core over 8 to 256 cores. The default constructor is
  declared alongside because declaring any constructor suppresses the implicit
  one.

### `ReplacementPolicy::on_hit`

**Contract.** `virtual void on_hit(SlotId slot) = 0;` - `slot` was hit by an
access. **Called by the engine explicitly, never by the array**, and that is plan
2.2's rule rather than a convention.

**Traps.**

- **The prefetcher of 4.6 is the case that makes it bite** (decision B11, I15): a
  prefetch that finds the line resident **drops it and must not touch replacement
  state**, and it can only do that if probing and recording a use are two
  separate calls.

### `ReplacementPolicy::on_fill`

**Contract.** `virtual void on_fill(SlotId slot) = 0;` - `slot` now holds a
newly installed line. **One verb for the fill, whether or not the insert
evicted**: what was displaced is gone, and a policy's state for a slot describes
its **CURRENT** occupant, so an eviction leaves nothing for the policy to
remember about the line that left.

**Traps.**

- **There is no `on_evict`, and that is an escalated plan defect rather than an
  omission.** Plan 2.2 lists four verbs; plan 3.4's `install()` pseudocode calls
  `on_evict(slot)` **after** `on_fill(slot)`, on the **same slot**. That ordering
  cannot be right for any stamp policy: if `on_evict` **records** something about
  the line that left, it reads a cell `on_fill` overwrote one line earlier (under
  the worked sequence below, `on_fill(65)` sets `stamp_[65] = 10`, and an
  `on_evict(65)` looking for line 40's age finds 10 - the stamp of the line that
  just replaced it); if it **writes** the slot's state, it clobbers the stamp
  `on_fill` just wrote and the freshly installed line inherits the eviction's
  bookkeeping. Either way the fill and the eviction fight over one cell.
  Decisions **B97** and **B138**: built to Part 2.2's four, the call site carries
  a comment naming the open question, no fifth verb was invented, and the
  behaviour is pinned by a test. The ruling belongs to the human.

### `ReplacementPolicy::on_invalidate`

**Contract.** `virtual void on_invalidate(SlotId slot) = 0;` - `slot` no longer
holds a line. **The caller makes this call**, exactly as it makes `on_hit` after
a probe; the array does not name a policy.

### `ReplacementPolicy::pick_victim`

**Contract.**

```cpp
virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;
```

Given a candidate **SET**, and **no implementation may depend on its order**.
Concretely: permuting `candidates` may not change the answer, so a policy whose
natural rule can tie needs a tie-break that is a function of the **candidates
themselves** and not of where they sit in the vector.

`candidates` is the whole of one set, including any free ways, which carry
`NoLine`. The engine reaches this verb only after `free_slot` has answered
`NoSlot`, so **in the engine there are none**.

**Decisions.**

- **B94** - **not `const`, on purpose**, and that is the openness the criterion
  is protecting. A Random policy draws from an RNG, which is state it must
  advance; `const` on a **virtual** is part of the signature and binds every
  future override, not just today's two. A `const pick_victim` today would be
  exactly the interface change adding Random would force tomorrow, across both
  levels and every fixture built against it. It is left non-`const` now, once,
  for a class that does not exist yet.

**Traps.**

- **The order-independence rule is load-bearing rather than stylistic, and with
  only LRU and FIFO built it is unfalsifiable by fixture.** Both pick "oldest by a
  stamp", so an implementation that quietly relied on the list being in slot
  order would compile, pass every fixture, and fail only when a policy that does
  **not** pick by age is added - Random draws a candidate, and if the list's order
  carried meaning, Random's draw would silently be a draw over an ordering the
  array chose rather than over the set. Nothing else announces that regression,
  which is why the obligation is stated **on the interface where an implementer
  reads it** rather than in a test.

---
---

# `native/include/wcache/stamp_policy.h` + `native/src/stamp_policy.cpp`

**Both policies are the same machine under one different wire**, which is why
they share a base rather than being written twice: each slot carries a stamp, the
victim is the smallest stamp in the candidate set, and the two differ **only** in
whether a hit refreshes the stamp. Writing them separately would be two copies of
`pick_victim`, and a rule that "no policy may depend on candidate order" is worth
stating once and testing once.

## `kNeverStamped` (file-local)

**Contract.**

```cpp
constexpr std::int64_t kNeverStamped = 0;   // and the counter starts at 1
```

**Traps.**

- **That is not an arbitrary sentinel, and it is the right preference on its own
  merits rather than an accident.** "Never filled" is smaller than every stamp
  ever handed out, so a never-filled slot is automatically the **preferred
  victim** - which is correct, because such a slot holds no line and evicting it
  costs nothing.

## `StampPolicy::StampPolicy`

**Contract.**

```cpp
explicit StampPolicy(std::int32_t num_slots);
```

`num_slots` is `CacheArray::num_slots()`, **the only thing a policy is told about
the array it serves**. Throws `std::invalid_argument` for a non-positive count:

```
StampPolicy: num_slots must be >= 1, got 0
```

Then `stamp_.assign(num_slots, kNeverStamped)` and `next_stamp_ = 1`.

**Traps.**

- **It has to be a `throw` and not an `assert`** for `SetAssociativeArray`'s
  reason: it is a config-derived geometry and must be refused under `-DNDEBUG`.
  A zero-slot array is a cache that can hold nothing.
- **There is deliberately no `num_slots()` accessor, and decision B20's argument
  for `BlockPackMapper`'s accessors does NOT apply here.** Decision B20's point
  was that a constructor whose arithmetic is unobservable cannot be checked; here
  the sizing **is** already observable, because `index_or_reject` refuses the
  first slot id past the end and **names the count in its message**. An accessor
  would be a second way to read a fact the interface already reports.
- **`next_stamp_` is `int64` for `RefusalOrder`'s reason**: it advances once per
  hit or fill over a whole sweep, and 32 bits is reachable at the corpus size
  while 64 is not.
- **`stamp_` is 8 bytes per slot**, and at the geometry the array accepts
  (`total_lines == INT32_MAX`) that is `2147483647 * 8 = 17,179,869,176` bytes,
  about **17.2 GB per policy instance** - sitting **beside** the array's own
  `slots_`, also about 17.2 GB, and the engine holds **one L1 policy per core**
  over 8 to 256 cores, so this figure multiplies where the array's already did.
  Nothing refuses it; the constructor checks `num_slots >= 1` and allocates
  whatever it is given. This is the fourth site on decision B80's row, deferred to
  D1 with one shared bound.

## `StampPolicy::index_or_reject` (private)

**Contract.**

```cpp
std::size_t index_or_reject(const char* verb, SlotId slot) const;
```

The bound check shared by every verb, so no two of them can disagree about the
range. Throws `std::out_of_range`:

```
StampPolicy::on_invalidate: slot 9999 is outside [0, 256)
```

**Traps.**

- **`out_of_range` and not `invalid_argument`**: a slot id belonging to a
  **different array** is well formed but names something outside this layer -
  the same rule and the same tier `SetAssociativeArray::insert` applies to the
  same quantity.
- **It is checked on every verb, including `on_hit`, which is the hottest call in
  the model.** The check is one predictable compare against a member already in
  cache, and what it prevents is an **out-of-bounds write** into `stamp_`: a
  policy handed the slot ids of a differently sized array would otherwise corrupt
  memory silently rather than say so.

## `StampPolicy::stamp` (protected)

**Contract.**

```cpp
void stamp(SlotId slot);   // stamp_[slot] = next_stamp_++;
```

Records `slot` as the most recently touched. **The subclasses' `on_hit` is this
call or nothing, which is the whole of the difference between LRU and FIFO.**

## `StampPolicy::on_fill`

**Contract.** `void on_fill(SlotId slot) override { stamp(slot); }` - neither
subclass overrides it.

## `StampPolicy::on_invalidate`

**Contract.** Writes `kNeverStamped` back to the slot.

**Decisions.**

- **B96** - resetting to "never" makes an invalidated slot the preferred victim
  again.

**Traps.**

- **This verb is observable rather than a formality, and leaving the stamp alone
  is what would make it one.** The slot now holds nothing, so if it is ever
  offered as a candidate it should be taken first - which is exactly what the
  smallest possible stamp means. Leaving the previous occupant's stamp would make
  an invalidated slot **compete on the age of a line that is gone**.
- **Decision B100** records the gap this hid: every runtime `on_invalidate` in
  the entire suite ran through an `LruPolicy`, so `FifoPolicy`'s "overrides no
  other verb" was checked by **nothing**. Two new cases, both blind, both now
  killed.

## `StampPolicy::pick_victim`

**Contract.**

```cpp
SlotId pick_victim(const std::vector<Candidate>& candidates) override;
```

The smallest stamp among `candidates`, **ties broken by the smallest slot id**.
Throws `std::invalid_argument` for an empty candidate set
(`"StampPolicy::pick_victim: the candidate set is empty"`), and
`std::out_of_range` for a candidate naming a slot this policy does not have.

```cpp
SlotId       victim = candidates[0].slot;
std::int64_t oldest = stamp_[index_or_reject("pick_victim", victim)];

for (std::size_t i = 1; i < candidates.size(); ++i) {
    const SlotId       slot = candidates[i].slot;
    const std::int64_t age  = stamp_[index_or_reject("pick_victim", slot)];
    if (age < oldest || (age == oldest && slot < victim)) { oldest = age; victim = slot; }
}
return victim;
```

**Worked example, the tie-break earning its keep.** Take the LRU stamps of the
full set 8 below and invalidate slots 66 and 69 (their lines were
back-invalidated by an L2 eviction):

```
slot:   64  65  66  67  68  69  70  71
stamp:   9   2   0   4   5   0   7   8
                 ^           ^   two-way tie at kNeverStamped
```

In the array's natural order, 64 → 71:

```
init  victim=64 oldest=9
i=65  2 <  9                     -> victim=65 oldest=2
i=66  0 <  2                     -> victim=66 oldest=0
i=67  4 <  0 ? no
i=68  5 <  0 ? no
i=69  0 <  0 ? no; 0==0 && 69<66 ? no   -> unchanged
i=70  7 <  0 ? no
i=71  8 <  0 ? no
                                 -> SlotId{66}
```

Now hand the **same set** in reverse, 71 → 64, which is a legal permutation the
interface explicitly allows:

```
init  victim=71 oldest=8
i=70  7 <  8                     -> victim=70 oldest=7
i=69  0 <  7                     -> victim=69 oldest=0
i=68  5 <  0 ? no
i=67  4 <  0 ? no
i=66  0 <  0 ? no; 0==0 && 66<69 ? YES  -> victim=66 oldest=0
i=65  2 <  0 ? no
i=64  9 <  0 ? no
                                 -> SlotId{66}
```

**Same answer.** Without the tie-break the first run answers 66 and the second
answers 69 - **and both are "correct"** in the sense that both evict an empty
slot, which is why this bug does not show up as a failure, only as **two builds
of the same simulator disagreeing about which slot a line landed in**.

**Decisions.**

- **B93** - smallest stamp, ties by the **smallest slot id**, which discharges
  the plan's order-independence rule **mechanically**.
- **B95** - an empty candidate set throws `invalid_argument`.

**Traps.**

- **Two occupied slots can never tie, which is exactly why the tie-break looks
  unnecessary.** Each stamp is a distinct value of a strictly increasing counter.
  But a slot that has never been filled, **or one that has been invalidated**,
  carries `kNeverStamped`, and several of those **can** tie. The natural loop
  `if (age < oldest)` keeps the **first** minimum seen, and that is where order
  dependence enters. Adding `|| (age == oldest && slot < victim)` makes the result
  the pairwise minimum of `(stamp, slot_id)` under lexicographic order - **a
  minimum over a set, which does not depend on the order the set is presented
  in**. Order-independence is then structural rather than a promise an implementer
  keeps.
- **`victim` is seeded from `candidates[0]` rather than from a sentinel stamp**,
  so there is no "no victim yet" state to get wrong and **the answer is one of
  the candidates by construction**.
- **Refusing an empty set is not defensive padding.** The minimum of nothing has
  no answer, so the alternative to refusing is returning a slot id that names no
  candidate - which the caller then **installs a line into**.
- **Decision B99** reclassified the mutation
  `A5 a never-filled slot becomes the last victim` from `kill` to `allow` as a
  **proven equivalent mutant**, and replaced its intent with five new cases that
  each move **one** site and leave the other two.

## `LruPolicy`

**Contract.**

```cpp
class LruPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;
    void on_hit(SlotId slot) override;    // stamp(slot)
};
```

Least recently **used**: a hit refreshes the stamp, so the victim is the slot
whose last **USE** is oldest.

## `FifoPolicy`

**Contract.**

```cpp
class FifoPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;
    void on_hit(SlotId) override;         // {}
};
```

First in, first out: a hit does **not** refresh the stamp, so the victim is the
slot whose **INSTALL** is oldest, however heavily it has been used since.

**Worked example: LRU and FIFO driving the same array, and diverging.** Same
array as above - 32 sets of 8, set 8 at slots `[64, 72)`. Same access sequence,
replayed once under each policy. Each policy is constructed with
`num_slots() == 256`, so `stamp_` has 256 entries, all `0`.

**Steps 1 to 8, the eight fills.** For each line the engine gets `NoSlot` from
`probe`, a slot from `free_slot`, calls `insert`, then calls `on_fill`:

| step | line | slot | `on_fill` writes | `next_stamp_` after |
|---|---|---|---|---|
| 1 | 8 | 64 | `stamp_[64] = 1` | 2 |
| 2 | 40 | 65 | `stamp_[65] = 2` | 3 |
| 3 | 72 | 66 | `stamp_[66] = 3` | 4 |
| 4 | 104 | 67 | `stamp_[67] = 4` | 5 |
| 5 | 136 | 68 | `stamp_[68] = 5` | 6 |
| 6 | 168 | 69 | `stamp_[69] = 6` | 7 |
| 7 | 200 | 70 | `stamp_[70] = 7` | 8 |
| 8 | 232 | 71 | `stamp_[71] = 8` | 9 |

Identical under both policies: `on_fill` is `StampPolicy`'s and neither subclass
overrides it.

**Step 9: line 8 is accessed again.** `probe(8)` returns `SlotId{64}` and the
engine calls `on_hit(SlotId{64})`. **Here the two diverge, and this is the only
line of the whole run where they differ:**

```
LRU   on_hit(64)  ->  stamp(64)  ->  stamp_[64] = 9,  next_stamp_ = 10
FIFO  on_hit(64)  ->  { }        ->  stamp_[64] = 1,  next_stamp_ =  9
```

**Step 10: line 1000 misses into the same set.** `free_slot` returns `NoSlot`,
`victim_candidates` produces the eight-entry list, and `pick_victim` runs on it:

| slot | line | stamp under LRU | stamp under FIFO |
|---|---|---|---|
| 64 | 8 | **9** | **1**  ← smallest under FIFO |
| 65 | 40 | **2**  ← smallest under LRU | 2 |
| 66 | 72 | 3 | 3 |
| 67 | 104 | 4 | 4 |
| 68 | 136 | 5 | 5 |
| 69 | 168 | 6 | 6 |
| 70 | 200 | 7 | 7 |
| 71 | 232 | 8 | 8 |

```
LRU  : pick_victim -> SlotId{65}    insert(1000, 65) -> {true, LineId{40}}
FIFO : pick_victim -> SlotId{64}    insert(1000, 64) -> {true, LineId{8}}
```

**LRU keeps line 8 because it was just used** and throws out line 40, the least
recently *used*. **FIFO throws out line 8 anyway**, because it was installed
first and a hit is the event FIFO is defined to ignore. Two different lines
leave the cache, from two different slots, off one identical event sequence,
driving one unchanged array. The fill that follows stamps the new occupant:

```
LRU  : on_fill(65) -> stamp_[65] = 10, next_stamp_ = 11
FIFO : on_fill(64) -> stamp_[64] =  9, next_stamp_ = 10
```

**Traps.**

- **`FifoPolicy::on_hit` is empty on purpose and is NOT a stub**, which is why
  both the header and the `.cpp` say so outright: an empty override in a diff
  reads as unfinished work. FIFO orders by **insertion**, and insertion is what
  `on_fill` records. The parameter is unnamed so the empty body stays
  warning-clean without a cast-to-void.
- **The cost of the empty body: `FifoPolicy::on_hit` is the ONE verb in the
  policy that performs no bound check.** `index_or_reject` lives inside `stamp()`
  and `stamp()` is never called. Concretely, a policy sized for a 256-slot L1
  handed `on_hit(SlotId{9999})` - a slot id belonging to the L2's array, say -
  **throws under LRU and is silently accepted under FIFO**: same call, same
  mistake, two outcomes depending on a config field. It is **not** a
  memory-safety bug (the empty body writes nothing; the id is ignored); what it
  costs is the diagnostic. It is not simply fixed either: adding a check to an
  empty body means adding a call whose only purpose is to throw, on the hottest
  verb in the model, in the one policy defined to do nothing on that event. **It
  is pinned as *behaviour* by the tests, and no rule anywhere says which of the
  three options - check in the base via a protected hook, accept the asymmetry as
  contract, or state that bound-checking is per-verb best effort - is intended.**
  A later reader finding LRU strict and FIFO permissive has nothing to tell them
  whether that is a decision or an accident.

## `PolicyKind`

**Contract.**

```cpp
enum class PolicyKind : std::uint8_t { LRU = 0, FIFO = 1, RANDOM = 2 };
```

The config vocabulary for plan 2.2's `l1_policy` / `l2_policy`.

**Traps.**

- **`RANDOM` is an enumerator with no class behind it, and keeping it is the
  decision rather than an oversight.** Drop it and `policy = random` in a config
  file becomes an **unknown name**, so the run reports a *typo* where it should
  report a *missing feature* (V29).

## `make_policy`

**Contract.**

```cpp
std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots);
```

Throws `std::invalid_argument` for `PolicyKind::RANDOM`:

```
make_policy: policy 'random' is a placeholder and is not implemented; use 'lru' or 'fifo'
```

and `std::logic_error("make_policy: unknown PolicyKind")` after the exhaustive
switch.

**Decisions.**

- **B95** - `invalid_argument` rather than `logic_error`, and the type is the
  decision: `logic_error` is the tree's tier for programmer error, a function
  called before it was written. This is a **config value refused** - D1's config
  load reaches this call with a value a human typed, and it must be refused under
  `-DNDEBUG` the same way the array's geometry checks are.

**Traps.**

- **This is the ONE refusal site, which is what stops a silent fallback.** It is
  the only place a `PolicyKind` becomes an object, so no config path can pick a
  policy the enum admits and quietly fall back to LRU.
- **The unreachable `logic_error` after the switch is reported rather than
  papered over with a fallback, and falling back to LRU is the one wrong answer
  here**: a config naming a policy this build does not have would then **run to
  completion under a policy nobody selected**, and the results row would attribute
  a hit rate to the wrong one. `types.h`'s `Axis` accessors refuse the same way
  for the same reason.
