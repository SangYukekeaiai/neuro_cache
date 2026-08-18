# EXPLAIN: increment A4a, the non-narrowing `Tagged`, `SetIndex`, and the `CacheArray` interface

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

Changed files, implementer: `native/include/wcache/types.h`,
`native/include/wcache/cache.h` (new).
Changed files, reviewer: `native/tests/test_cache.cpp` (new),
`native/tests/test_types.cpp`, `native/tests/compile_fail.sh`,
`native/tests/mutation_check.sh`, `native/Makefile`.

A4 as the plan states it is `CacheArray` + `SetAssociativeArray`. This increment
is the **first third of it**, and section 9 says plainly what the other two
thirds are and why I stopped where I did.

Plan reference: v3 Part 7 unit A4 ("`CacheArray` + `SetAssociativeArray` with
`invalidate` in the interface from the start (N8)"), Part 2.2 (the array/policy
split, `probe` is const and is not an access), Part 2.3, N8, and board decisions
B2, B3, B5, B9, B29 with its carried obligation, and A1a's carried obligation
for a seventh tagged type.

```
$ make clean && make test
188 compile cases, 0 failures
10500 checks, 0 failures       (test_block_pack)
   23 checks, 0 failures       (test_cache, new)
 9593 checks, 0 failures       (test_layout)
  294 checks, 0 failures       (test_types)
exit 0
```

Warning-clean under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion
-Wshadow`, and green under `MODE=release` as well. No cast was added anywhere to
silence anything.

---

## 1. What landed

Two headers. No `.cpp`, no executable code at all: this increment is a
compile-time rule and an abstract interface, which is the same shape A2a had.

**`types.h`**, three additions:

```cpp
namespace detail {
template <typename To, typename From, typename = void>
struct converts_without_narrowing : std::false_type {};
template <typename To, typename From>
struct converts_without_narrowing<To, From, std::void_t<decltype(To{std::declval<From>()})>>
    : std::true_type {};
}

// inside Tagged, replacing  constexpr explicit Tagged(Rep v) : v_(v) {}
template <typename U,
          typename = std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>>
constexpr explicit Tagged(U v) : v_{v} {}

using SetIndex = Tagged<std::int64_t, tags::set_index>;   // the seventh tagged type
inline constexpr LineId NoLine{INT64_MAX};                // the array's free marker
```

**`cache.h`**, new: `Candidate`, `InsertResult`, and the abstract `CacheArray`
with five verbs.

That is the whole diff. It is small and its consequences are not, which is what
sections 3 through 8 are for.

---

## 2. The running example

`Placement`, A2a's two-field result struct, is where the gap lives, because both
of its fields are raw `std::int64_t` (B9 settled that deliberately: two fields do
not read as an "index").

```cpp
struct Placement {
    std::int64_t set_index;  // in [0, num_sets)
    std::int64_t tag;
};
```

Two values to carry through the examples:

```
p.set_index = 3
p.tag       = 4294967303          which is 2^32 + 7
```

The tag is chosen so the failure is legible rather than plausible-looking. The
corpus does not produce a tag this large today (the biggest layer,
`3x3x512x512` at blocks 16/16, has 9216 lines and a maximum tag of 287), but
`WeightShape` carries four independent `int32`s decoded from a trace header, and
B15 already records the realistic route to a huge derived number: **A3 reading a
header at the wrong offset**. This is the number that route produces, not one
anybody would type.

---

## 3. Worked example one: `SlotId s{p.tag}`, and why it is now rejected

`SlotId` is `Tagged<std::int32_t, tags::slot>`. `p.tag` is an `int64`. So this
line asks a 64-bit value to become a 32-bit one.

### What it did before this increment

Not a thought experiment. I compiled and ran it against the old constructor:

```
$ g++ -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow ...
types.h:78:41: warning: narrowing conversion of 'v' from 'long int' to 'int' [-Wnarrowing]
types.h:78:41: warning: conversion from 'long int' to 'int' may change value [-Wconversion]

$ ./trunc
p.tag    = 4294967303
s.get()  = 7
```

**A tag of 4,294,967,303 became slot 7.** That is the whole defect in two lines
of output. Note what makes it dangerous rather than merely wrong: 7 is a
perfectly ordinary slot number. Any array with eight or more slots has one. So
the truncation does not crash, does not throw, and does not produce a value that
looks out of place in a debugger. It produces a hit or a miss against the wrong
storage location, for the rest of the run.

And note the second thing: **g++ did say something.** The board's older phrasing,
"`Tagged` narrows silently", is imprecise, and correcting it is a carried
obligation against whoever next edits `HANDOFF.md`. The compiler emitted
`-Wnarrowing`. The problem is that `compile_fail.sh` runs without `-Werror`, so
a warning is not a rejection, and the case sat in the suite recorded as `accept`,
which was honest bookkeeping of a real gap, not an endorsement.

### Why it is rejected now, step by step

The compiler sees `SlotId s{p.tag}` and has to find a constructor. There is
exactly one candidate, the constructor template. It works through it in order:

1. **Deduce `U`.** The parameter is `U v`, taken by value, and the argument is an
   lvalue of type `std::int64_t`. So `U = std::int64_t`.

2. **Substitute into the default template argument.** That argument is
   `std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>`, with
   `Rep = std::int32_t` and `U = std::int64_t`. So the compiler must first
   compute `converts_without_narrowing<std::int32_t, std::int64_t>::value`.

3. **Evaluate the trait.** It tries the partial specialization, whose third
   argument is `std::void_t<decltype(std::int32_t{std::declval<std::int64_t>()})>`.
   The expression inside is *braced initialization of an `int32_t` from an
   `int64_t`*. Braced initialization is the one context where the language
   forbids a narrowing conversion outright, so that expression is ill-formed, so
   the specialization does not apply, so the compiler falls back to the primary
   template, which is `std::false_type`. **`value` is `false`.**

4. **`enable_if_t<false>` has no member `type`.** Substituting it therefore fails.

5. **Substitution failure removes the candidate rather than erroring in place.**
   That is the SFINAE rule, and it is the reason this works at all (section 6
   explains what it buys). Having removed the only candidate, the compiler has no
   constructor to call.

The message:

```
error: no matching function for call to 'wcache::Tagged<int, wcache::tags::slot>::Tagged(
       <brace-enclosed initializer list>)'
    7 |     SlotId s{p.tag};
note: candidate: 'template<class U, class> constexpr wcache::Tagged<Rep, Tag>::Tagged(U)
      [with Rep = int; Tag = wcache::tags::slot]'
note:   template argument deduction/substitution failed
```

It names the exact instantiation, `Tagged<int, tags::slot>`, so you can see the
target is the 32-bit one, and it points at the constructor whose comment says
why. It does **not** contain the word "narrowing", and that is a real cost of
the design I accepted rather than paid to avoid; section 10 has the alternative
and the reason I did not take it.

---

## 4. Worked example two: `LineId l{p.set_index}`, still accepted, and this is the open question

Run the same five steps with `LineId`, which is `Tagged<std::int64_t, tags::line>`:

```
Rep = std::int64_t
U   = std::int64_t        (p.set_index is an int64)
trait: is  std::int64_t{ declval<std::int64_t>() }  well formed?   YES
value = true  ->  enable_if_t<true>::type exists  ->  the constructor is viable
```

**It compiles.** A set index becomes a line id, and nothing in this increment
stops it.

This is not an oversight; it is the boundary of what a rule about *narrowing*
can reach. Nothing narrows here. Both are 64 bits. The two quantities are
different in **meaning** and identical in **representation**, and a rule written
about representation cannot tell them apart.

The same is true of `SimTime t{p.tag}`, for the same reason.

This is the finding the open questions in section 10 lead with, because the
board currently claims otherwise, and it is the one thing in this increment I
need you to rule on.

---

## 5. The trait, for a reader who has not met SFINAE

Four pieces of C++ machinery appear in six lines. None of them has a C analogue,
so here is each one on its own. `CPP_NOTES.md` section 23 has the fuller
treatment; this is the part you need to read the code.

### `std::declval<T>()`: "a value of type T, hypothetically"

You cannot always *make* a `T` (`Tagged` has no default constructor, for one).
`std::declval<T>()` names a value of type `T` without constructing one. It has no
body and can never be called at run time; it exists only inside `decltype`,
where the compiler asks "what type would this expression have?" and never
evaluates anything.

### `decltype(...)`: "the type of this expression, without running it"

`decltype(std::int32_t{std::declval<std::int64_t>()})` asks: *if* I braced-initialized
an `int32_t` from an `int64_t`, what type would come out? The answer is either
`int32_t` or "that is ill-formed". We only care which of the two.

### `std::void_t<...>`: "throw away the type, keep the well-formedness"

`std::void_t<X>` is `void` for any valid `X`. It looks pointless and it is
precisely the point: it discards the answer and keeps only the *question of
whether there was one*. If `X` is ill-formed, `void_t<X>` is ill-formed too, and
that failure is what we are detecting.

### Partial specialization as an if/else

```cpp
template <typename To, typename From, typename = void>
struct converts_without_narrowing : std::false_type {};              // the fallback

template <typename To, typename From>
struct converts_without_narrowing<To, From, std::void_t<...>>        // the preferred case
    : std::true_type {};
```

Read it as: "by default, false. But if this third argument can be computed, use
the more specific one instead, which is true." The compiler always prefers a
partial specialization when it applies. So the whole trait asks one question,
*is that braced initialization well formed?*, and wires the two answers to
`true_type` and `false_type`.

### Why `declval` NOT being a constant expression is load-bearing

This is the subtle part, and it is the reason the trait is written with `declval`
rather than with an actual value.

C++ has a deliberate exception to the narrowing rule: a **constant expression**
whose value fits is not a narrowing conversion. So this is legal C++:

```cpp
std::int32_t x{5L};        // legal: 5L is a constant, and 5 fits in an int32
std::int32_t y{big};       // ill-formed: big is a run-time int64
```

Both are `int64` sources. The first is allowed because the compiler can see the
value; the second is not, because it cannot.

That exception is right for values and **wrong for a rule about types**. If the
trait were written against a real constant, then `SlotId{5L}` and `SlotId{p.tag}`
would get different answers, and the rule would be "may an int64 become a
SlotId?" Answer: *it depends on where the int64 came from*. That is not a rule
anybody can reason about, and it would leave `SlotId{p.tag}` rejected while a
`5L` spelling of the same idea slipped through.

`std::declval<From>()` is deliberately not a constant expression. It names a
value of the type and tells the compiler nothing about which value. So the trait
answers the question about the **type**, uniformly, and the constant-fits
exception never enters. That is why it is `declval` and not `From{}` or a
literal.

---

## 6. Why the plain `Tagged(Rep)` had to be removed, not shadowed

The obvious way to close this gap is to leave the existing constructor alone and
add a deleted one beside it for the bad cases:

```cpp
constexpr explicit Tagged(Rep v) : v_(v) {}          // keep
template <typename U> Tagged(U) = delete;            // and refuse the rest
```

That does not work, and the reason is the same GCC behaviour that created the
gap. In `SlotId s{p.tag}`, the compiler is converting an `int64` argument to an
`int32` *constructor parameter*. g++ treats narrowing in that position as
`-Wnarrowing`, a warning, rather than an error. So `Tagged(Rep)` stays viable,
it is a better match than any deleted template, and it is exactly what the bad
call binds to. Keeping it keeps the hole open.

Removing it is what makes the difference: with only the constrained template,
there is no overload that will perform the conversion, and "no matching function"
is a hard error under every flag combination.

### Why copy construction still works

The obvious worry about replacing a normal constructor with a template one is
that the template will start stealing calls that belong to the copy constructor.
It is a real hazard: for `SlotId b{a}` where `a` is a non-`const` lvalue, a
template deducing `U = SlotId` is an exact match, while the implicit
`Tagged(const Tagged&)` needs a qualification adjustment. The template would win,
and construction would recurse into itself.

The constraint is what prevents it. For `U = SlotId`, the trait asks whether
`std::int32_t{declval<SlotId>()}` is well formed. `Tagged` has no conversion
operator to its representation (`get()` is the only exit, by design), so that
expression is ill-formed, the trait is `false`, and the template is removed from
consideration. The implicit copy constructor is left holding the call, which is
what we want.

Checked, not assumed:

```
ACCEPT  SlotId a{1}; SlotId b{a};      (direct-init copy)
ACCEPT  SlotId a{1}; SlotId b = a;     (copy-init copy)
```

This is also why a plain `static_assert` inside an unconstrained template
constructor is not an alternative: it would fire, but only after the template had
already hijacked copy construction.

---

## 7. `SetIndex`: a name, not a width

A1a's carried obligation asked A4 for a seventh tagged type, and gave the exact
failure it exists to stop: without it "a set index and a way index are the same
type, so `policy.on_hit(SlotId{set_index})` compiles."

```cpp
using SetIndex = Tagged<std::int64_t, tags::set_index>;
```

Now look at what the narrowing rule alone would have done to that named failure.
A set index is `int64` and a `SlotId` is `int32`, so `SlotId{set_index}` narrows,
and section 3's mechanism already rejects it. The obligation looks discharged by
accident.

It is not, and the demonstration is one line:

```
REJECT   SetIndex i{3};  LineId l{i};        both are int64 -- nothing narrows
```

`LineId` and `SetIndex` have the *same* representation. The narrowing rule has
nothing to say about that pair. It is rejected because the trait asks whether
`std::int64_t{declval<SetIndex>()}` is well formed, and it is not: a `SetIndex`
is not an integer and never converts to one implicitly. **The refusal is about
the name, not the size.**

That distinction matters for the future rather than for today: if `SlotId` ever
widened to 64 bits, a width-based rule would go quiet and a name-based one would
not. This is exactly the argument B1b already made for having `Tagged` at all
rather than six `enum class`es, applied one level down.

`SetIndex` has no user yet. It is A4b's, where `SetAssociativeArray::set_of`
returns one. I introduced it here because A1a's obligation asks for it before
slots exist, and because introducing it in the same increment as the constructor
rule is what let the reviewer test the two halves of the wall against each other.

---

## 8. `NoLine`, and where sentinels live

```cpp
inline constexpr SlotId NoSlot{INT32_MAX};
inline constexpr LineId NoLine{INT64_MAX};      // new
```

`NoLine` is what a slot holding nothing reports. Its whole job is to make "free"
and "holds a line" one comparison in the array's way scan, rather than a second
valid bit per slot.

**Why `INT64_MAX` and not `-1`.** The archived v1 tree used `-1`, and its stated
reason was that a caller who forgets to check would index out of bounds loudly
instead of at a real slot. That argument died with A1's typing: `LineId` is a
`Tagged`, so it cannot be used as a subscript at all without an explicit
`.get()`, and there is no forgetting to check. What replaces it is B3's
convention, already written for `NoSlot` and `NoRefusal`: sentinels sit at the
top of their range so that an ordinary `<` sorts them last, which is what lets a
single comparison implement a whole ordering key without a second field.

**Why it cannot collide with a real line.** A `LineId` is in `[0, num_lines())`,
and `num_lines()` is itself an `int64` that A2b's overflow guard bounds at
`INT64_MAX`. So the largest id any mapper can produce is `INT64_MAX - 1`, and
`INT64_MAX` is one past every one of them.

**Why it is in `types.h` and not `cache.h`.** v1 put both sentinels in `cache.h`.
Here `NoSlot` was already in `types.h` from A1a, so putting `NoLine` in `cache.h`
would split one convention across two files. It is also genuinely part of the
shared vocabulary rather than an array-internal detail: `Candidate::line` is
documented as `NoLine` when the slot is free, so every policy in A5 and every
caller in C1 reads it.

---

## 9. `cache.h`: the interface, and what A4a deliberately does not build

### The three declarations

```cpp
struct Candidate {
    SlotId slot;
    LineId line;          // NoLine when the slot is free
};

struct InsertResult {
    bool   evicted;
    LineId evicted_line;  // NoLine when `evicted` is false
};

class CacheArray {
    virtual SlotId probe(LineId line) const = 0;
    virtual SlotId free_slot(LineId line) const = 0;
    virtual void victim_candidates(LineId line, std::vector<Candidate>& out) const = 0;
    virtual InsertResult insert(LineId line, SlotId slot) = 0;
    virtual void invalidate(SlotId slot) = 0;
    virtual std::int32_t num_slots() const = 0;
};
```

### Five verbs where the plan's earlier text said three

Plan 2.2 lists exactly these five, and two of them are one idea that had to
split. With replacement living in another module (A5), this module **cannot
choose a victim**, and all it can offer is the candidate set. But the one case that
needs no policy at all, a set with a free way, still has to be answered by the
module that knows which ways are free. Folding the free case into the candidate
list would oblige every policy to re-implement "prefer an empty way", and a
policy that got it wrong would evict a live line while a way sat empty: silent,
and visible only as a hit rate slightly below the truth. Hence `free_slot` for
the no-policy case and `victim_candidates` for the policy case.

### `invalidate` is on the interface from the start (N8)

The plan says so explicitly, and the reason is worth stating because it looks
like premature work: `invalidate` is not used until C4 builds the `inclusive`
branch of inclusion. A level that cannot invalidate cannot implement that branch
at all, and an interface that gains a verb later gets **one** implementation of
it rather than every implementation. It is also the verb v1's own test design
recorded as "not on the interface yet, decision 5 deferred it", and that
deferral is what N8 reverses.

### `probe` is `const` and is not an access

Plan 2.2 states it outright: "`probe` is const and is **not** an access. The
engine calls `policy.on_hit` explicitly. Without this, a speculative lookup would
perturb the recency stack." Two things rest on it. The obvious one is that a
lookup used to decide something must not itself count as a use. The less obvious
one is the prefetcher of 4.6: B11 and I15 require that a prefetch which hits the
array touches no replacement state at all, and that is only expressible if
testing residency is separable from recording a use.

### `num_slots()` returns `int32`, which is a decision I made

Slot ids are exactly `[0, num_slots())` and `SlotId`'s representation is `int32`.
A slot count a `SlotId` cannot name would be a geometry whose upper slots are
unreachable: storage the sweep paid for and never used, showing up only as a hit
rate a few points below the truth. Returning `int32` makes that unrepresentable
and pushes the refusal into A4b's constructor, where the geometry is validated
anyway. Reversible now; expensive after A5 sizes per-slot state against it.

### What A4a does not build

- **A4b: `SetAssociativeArray` construction and validation.** The geometry
  (`num_sets = cache_size_bytes / (line_size_bytes * assoc)`), and the six
  rejections, including the plan's own A4 exit criterion, "non-exact size ÷
  (line × assoc) throws". This is also where the A2b obligation lands (section
  10).
- **A4c: the five bodies.** The way scan, the lowest-free-way rule, the
  replace-not-append candidate list, the insert report.

**Why I stopped here.** Two reasons. First, this is the A2a shape: support
structs plus an abstract interface, no implementation, testable through
conforming and deliberately non-conforming fakes, and the reviewer's new
`test_cache.cpp` is exactly that, so the boundary was a real one and not a
convenient one. Second and more important, the constructor rule re-rules code
that was already written, already reviewed and already green, and it surfaced a
counting error on the board (section 10) whose resolution could change
`Placement`'s field types. `Placement` is what `SetAssociativeArray::set_of`
reads. Building A4b before you rule on that would mean building it against a
struct that may be about to change shape.

---

## 10. The comment that was wrong, and the measurement that corrected it

Recorded rather than quietly fixed, because the error was mine and the reasoning
that produced it is the reasoning a later reader will repeat.

I had written that the member initialiser was a second line of defence:

> `v_{v}` rather than `v_(v)`: the member initialiser is itself a list
> initialisation, so a narrowing source that somehow got past the constraint is
> still rejected one line later.

The reviewer challenged it. It is false, and the measurement is decisive. I built
two variants of `types.h` and compiled `SlotId s{p.tag}` against each:

| Variant | Result |
|---|---|
| constraint **removed**, braces kept (`v_{v}`) | **compiles**, with `-Wnarrowing` and `-Wconversion` and nothing else |
| constraint kept, braces **removed** (`v_(v)`) | rejected |

So the constraint is solely load-bearing, and the braces enforce nothing. The
reason is the same GCC permissiveness section 6 describes: narrowing in that
position is a warning there too. **The braces are defeated by exactly the
behaviour the mechanism exists to route around**, which is worth stating in the
file, because reaching for braces is the natural first fix and it does not work.

I kept `v_{v}` and corrected the comment to say what is true: it states the rule
where the value lands, and it is not what enforces it.

---

## 11. What the reviewer's round added

- **`tests/test_cache.cpp`**, new, 23 checks, driving the interface through a
  minimal conforming fake: every verb dispatches, `Candidate` carries a line
  beside a slot with `NoLine` on the free ones, `InsertResult`'s two fields never
  disagree (`evicted == (evicted_line != NoLine)`), destruction through the base
  actually runs the derived destructor, and the one I would point you at: a
  *checkable* statement of the replace-not-append contract, with a deliberately
  appending fake proving the check catches it.
- **58 new compile cases**, 130 to 188, in four named sections: 6 for the width
  rejects, 11 for the accepts the change must not have broken, 13 for `SetIndex`
  as a name rather than a width, and 28 for the `CacheArray` interface keeping
  its shape.
- **The two accept cases flipped to reject**, which is B29's obligation
  discharged on the test side.
- **`test_types.cpp`** grew from 263 to 294 checks.

Two operational notes from my own runs, both worth knowing before anyone asks
for a mutation sweep:

- While the gate was red between my landing and the reviewer's, **every mutation
  reported `killed`**, because `mutation_check.sh` judges a kill by `make test`
  failing. Proven rather than inferred: B50's intentional `allow`, which must
  survive by construction, reported `killed but was expected to survive`. That
  window is closed now the gate is green, but it is a standing trap for any
  future increment that lands a deliberate red.
- The mutation case `'explicit dropped'` targeted the text
  `constexpr explicit Tagged(Rep v)`, which no longer exists, and reported
  `sed matched nothing; the mutation is not real`, the same failure mode B45
  deleted four A2b cases for.

---

## 12. Open questions

The stride question that led this file at A2d is **gone, and settled**: U11 ruled
`stride < 1` illegal, B49 recorded it, and `expand` rejects it. It is removed
rather than carried forward, because a settled ruling sitting in a file you
review from is the one way it could be un-settled by accident.

**Q1. B29's obligation row is wrong, and only you can decide what replaces it.**
This is the one I need an answer to.

The row says six `accept` cases in `compile_fail.sh` flip to `reject` when the
non-narrowing constructor lands. **Two did.** The row is wrong twice over.

*The arithmetic.* It counts "3 original + 1 from A2c + 2 from A2d". The A2d round
added only **one** such case, so the sum is five, not six. (A sixth candidate is
`set_index is a raw int64`, but that is `std::int64_t s = p.set_index`, not a
`Tagged` construction at all, and no rule about `Tagged` can ever flip it.)

*The substance, which matters more.* The row treats one fix as closing one gap.
There are two gaps:

| case | conversion | flipped? |
|---|---|---|
| `SlotId s{p.tag}` | int64 → **int32** | **yes** |
| `SlotId s{m.line_stride(Axis::KH)}` | int64 → **int32** | **yes** |
| `LineId l{p.set_index}` | int64 → int64 | no |
| `SimTime t{p.tag}` | int64 → int64 | no |
| `LineId l{m.locate(...).set_index}` | int64 → int64 | no |

The three that did not flip do not narrow (section 4). **No rule about narrowing
can ever close them.** B29's own decision text is precise where its obligation row
is not: it decided that "`SlotId s{p.tag}` on an int64 fails to compile", which
is exactly what now happens.

*The trade, so you can decide from this file alone.* Closing the remaining three
means giving `Placement` tagged fields:

```cpp
struct Placement { SetIndex set_index; Tag tag; };     // instead of two raw int64
```

- **What it buys.** A set index could no longer become a line id or a `SimTime`
  by any spelling, and the refusal would be about meaning rather than width,
  the section 7 property, extended from `SetIndex` to the whole result struct.
  It would also make `SetIndex` load-bearing immediately rather than at A4b.
- **What it costs.** `Placement` is A2's interface, so this is an edit to
  `layout.h` reaching `tests/test_layout.cpp` and `tests/test_block_pack.cpp`,
  plus three further compile cases that would need rewriting rather than flipping
  (`Placement braced`, `set_index is a raw int64`, `Placement from locate`). It
  also costs `layout.h:22-24`'s stated reason for the current shape: that both
  fields are raw and signed so `line == tag * num_sets + set_index`, the plan's
  own A2 exit criterion, holds **without a cast**. Under tagged fields that
  identity is written with two `.get()` calls. It needs a second tag type for the
  `tag` field, which nothing has named or reserved.
- **What it does not affect.** `CacheArray`'s verbs take `LineId` and `SlotId`
  only, so cache.h does not change either way. `SetAssociativeArray::set_of` does,
  which is why I would rather have your answer before A4b.

My recommendation, and it is only that: **do it, but not now and not as part of
A4.** The gap is real but it is one level less dangerous than the one just
closed: a same-width mix-up produces a wrong-but-plausible value exactly as a
truncation does, but there is no reachable path to it in the tree today, whereas
`SlotId{tag}` was one line away in every array. It wants its own increment
against `layout.h`, with the second tag type named deliberately.

**Q2. `CacheArray` is a sliceable polymorphic base.** It has a virtual destructor
and no copy or move control, so the compiler generates all four. A derived array
assigned or copied through a `CacheArray&` would slice, and for a class holding a
`std::vector<LineId>` of slot contents that is a silently half-copied cache
rather than a crash. `AddressMapper` has the same shape, and `compile_fail.sh`
already carries reject cases for passing one by value, so the tree has been
guarding this by test rather than by construction. Deleting the copy and move
operations on the base is the construction-level fix, it is four lines, and it
belongs with A4b where a real derived class with real storage first exists. Raised
here so it is not discovered by a slice.

**Q3. The A2b exactness-message obligation is designed but not built.** The board
requires that the `cache_size_bytes / (line_size_bytes * assoc)` rejection name
`cin_block`, `cout_block` and `weight_bytes`, not only their product, because a
non-power-of-two line size is legal (B16), so "65536 is not a multiple of 96" is
only actionable if the 96 traces back to `12 * 8`. That check lives in A4b's
constructor, which holds a `const AddressMapper&` and cannot see those three.
The fix I intend is a `virtual std::string line_size_terms() const` on
`AddressMapper` with an **inline default** returning the bare product; the
default is what keeps the blast radius at zero, since a pure virtual would break
all thirteen non-conforming fakes and the four `subclass omits ...` reject cases.
Flagging the shape now in case you would rather it went to D1 instead.

**Q4. U14 is partly overtaken but not answered.** A4b's constructor will
guarantee `num_sets >= 1` before it ever calls `locate(line, num_sets_)`, so the
reachable division by zero *through this array* closes as a side effect. `locate`'s
contract is untouched and the owner question, an A2b plausibility bound, a D1
bound, or a guard in `locate`, is exactly where A2d left it.

Q2, Q3 and Q4 are all A4b's to act on and none of them blocks it. **Q1 is the one
that does**, and only because of what it might do to `Placement`.
