# EXPLAIN: increment A4b, `SetAssociativeArray` construction and validation

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

Changed files, implementer: `native/include/wcache/set_associative.h` (new),
`native/src/set_associative.cpp` (new), `native/include/wcache/cache.h`,
`native/include/wcache/layout.h`, `native/include/wcache/block_pack.h`,
`native/src/block_pack.cpp`.
Changed files, reviewer: `native/tests/test_set_associative.cpp` (new),
`native/tests/mapper_conformance.h`, `native/tests/test_layout.cpp`,
`native/tests/compile_fail.sh`, `native/tests/mutation_check.sh`.

A4 as the plan states it is `CacheArray` + `SetAssociativeArray`. A4a built the
interface; this increment is the **second third**, the concrete class's
construction and validation. Section 10 says what the last third is.

Plan reference: v3 Part 7 unit A4 ("`CacheArray` + `SetAssociativeArray` with
`invalidate` in the interface from the start (N8)", exit criterion "non-exact
size ÷ (line × assoc) throws"), Part 2.2 (the array/policy split; the array
knows geometry and holds no recency), Part 2.3 (the same structure at the L2),
and board decisions B2, B10, B16, B18, B19, B20, B54, plus the two carried
obligation rows that name A4b.

```
$ make clean && make test
202 compile cases, 0 failures
10521 checks, 0 failures       (test_block_pack)
   23 checks, 0 failures       (test_cache)
 9607 checks, 0 failures       (test_layout)
   81 checks, 0 failures       (test_set_associative, new)
  294 checks, 0 failures       (test_types)
exit 0
```

Warning-clean under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion
-Wshadow`, and green under `MODE=release` as well.

---

## 1. What landed

One class, one constructor, seven checks, and two obligation rows discharged.

```cpp
class SetAssociativeArray final : public CacheArray {
public:
    SetAssociativeArray(const AddressMapper& mapper,
                        std::int64_t  cache_size_bytes,
                        std::int32_t  associativity);

    SlotId probe(LineId) const override;                       // A4c stub
    SlotId free_slot(LineId) const override;                   // A4c stub
    void victim_candidates(LineId, std::vector<Candidate>&) const override;  // A4c stub
    InsertResult insert(LineId, SlotId) override;              // A4c stub
    void invalidate(SlotId) override;                          // A4c stub

    std::int32_t num_slots()     const override { return num_slots_; }
    std::int64_t num_sets()      const { return num_sets_; }
    std::int32_t associativity() const { return associativity_; }

private:
    const AddressMapper& mapper_;
    std::int32_t associativity_ = 0;
    std::int64_t num_sets_      = 0;
    std::int32_t num_slots_     = 0;
    std::vector<LineId> slots_;
};
```

Plus, elsewhere: copy and move control on `CacheArray` (section 8), and a new
`AddressMapper::line_size_terms()` with an inline default (section 6).

---

## 2. The running example: one construction, end to end

The configuration is a real one. Take a `3 x 3 x 512 x 512` layer at
`cin_block = cout_block = 16`, `weight_bytes = 1`, which is B22's own worked
layout, and give it a 64 KB L1 at associativity 8:

```cpp
const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);
SetAssociativeArray  l1(m, 65536, 8);
```

Measured, not computed by hand:

```
line_size_bytes = 256        line_size_terms = cin_block 16 x cout_block 16 x weight_bytes 1
num_lines       = 9216       (the whole tensor; the cache holds a fraction of it)

L1 65536 / assoc 8   OK   num_sets=32  associativity=8  num_slots=256
```

Walk the constructor with those numbers in hand.

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
| - | assign | `associativity_ = 8`, `num_sets_ = 256 / 8 = 32`, `num_slots_ = 256` |
| - | `slots_.assign(256, NoLine)` | 256 free slots, the cold start |

The three numbers the class then reports are `num_sets() == 32`,
`associativity() == 8`, `num_slots() == 256`, and the last of them is what a
`ReplacementPolicy` at A5 will size its per-slot state from.

**Why all three accessors exist**, which is B20's argument reused rather than
tidiness: `num_slots` alone is the same 256 whatever the associativity, so an
implementation that put the associativity where the set count belongs, or that
floored a division it should have refused, would look identical from outside
until A4c's verbs existed to contradict it. Reporting the two factors separately
is what lets this increment be checked on its own terms. `num_sets` and
`associativity` are deliberately **not** on `CacheArray`: a fully associative
array has no meaningful set count, and putting them on the interface would
invite a policy to read them, which is the 2.2 split leaking.

---

## 3. The running example: one refusal, end to end

Same mapper, ask for a size that is not a whole number of lines:

```cpp
SetAssociativeArray l1(m, 65000, 8);
```

Step 4 fires, and the message is:

```
SetAssociativeArray: cache_size_bytes 65000 is not a whole number of 256-byte lines
                     (cin_block 16 x cout_block 16 x weight_bytes 1)
```

Two halves, and the second one is the whole of section 6. Without it the reader
knows only that 65000 is not a multiple of 256; with it they know which three
config fields multiplied to 256 and can change one of them. A non-power-of-two
line size is deliberately legal (B16), so the bracketed half is not decoration:
`12 x 8 x 1 = 96` is a legal line, and "not a whole number of 96-byte lines" on
its own is a dead end.

Two more refusals on the same geometry, both measured:

```
65536 / assoc 3      256 lines do not divide evenly into sets of 3
65536 / assoc 512    associativity 512 exceeds the whole cache of 256 lines
```

These two are why the checks stay separate rather than being folded. Both are
"the associativity is wrong", and one message says *the cache cannot be cut into
sets of that width*, the other says *the cache is smaller than one set*. An
implementation that dropped either check would still throw on the other case,
which is exactly the state in which the suite cannot tell that one of them is
gone.

---

## 4. The seven checks, in order, and what breaks if each runs later

The order is load-bearing, so it is stated in the file rather than left to be
inferred from the sequence. Taking them in order, with the failure that ordering
prevents:

**1-3, the three positivity checks** (`cache_size_bytes`, `associativity`,
`mapper line_size_bytes`). They come first because *every* check after them
divides by one of the three. Move check 3 after check 4 and `65536 % 0` is a
division by zero, which is not a diagnosable refusal but a crash or, under
optimisation, undefined behaviour. All three share one spelling,
`positive_or_reject`, so the three messages cannot drift apart into three
slightly different statements of one rule, which is the A2b constructor's recorded
defect (`KH extent must be >= 1, got 0` beside `cin_block must be >= 1, got 0`),
not repeated here.

**4, byte exactness**, before `total_lines` is derived. A line count computed
from a division that was not exact is a number with no meaning, and every check
after it is written against `total_lines`. Run it later and check 6 compares the
associativity against a floored count, so an over-associative point could pass
check 6 on the strength of lines the cache does not have. Refusing rather than
flooring is D2's requirement: `cache_size_bytes` is echoed verbatim into every
results row, so a silently floored geometry would make a whole sweep attribute
its hit rates to a capacity the simulator never had.

**5, the slot-count bound**, `total_lines > INT32_MAX`. Placed here because it is
a fact about the size and the line size **alone**. Move it after checks 6 and 7
and a cache too large for a `SlotId` to index gets reported as an associativity
problem whenever the associativity also fails to divide, which sends the reader
to the wrong config field. Section 7 has the rest of this one.

**6, associativity against the whole cache**, before check 7. This is the one
check that adds no rejection: every input it catches also fails check 7, since
`total_lines % associativity` is `total_lines` itself when the associativity is
larger, and `total_lines >= 1` here. It exists **only** to change the message.
Run it after check 7 and `associativity = 512` on a 256-line cache reports "256
lines do not divide evenly into sets of 512", which describes a rounding problem
where the real problem is a cache too small to hold a single set. The reviewer
confirmed this reading independently: step 6 adds no rejection the single
division would not make, and only changes what the message says.

**7, lines into sets.** Last of the rules, and the likeliest to fire in practice:
a sweep grid crosses `cache_size_bytes` with `associativity`, and a
non-power-of-two associativity against a power-of-two size never divides.

Then, and only then, the assignments. That ordering is the same "check, then
derive" discipline `block_pack.h` records for `num_lines_`: everything computed
from a validated value is assigned in the body, after the checks, never in the
initialiser list which runs before them. The three derived members are
zero-initialised at their declarations so a constructor that throws leaves
nothing indeterminate.

**One consequence worth stating, because it closes a live hazard.** After check
4 gives an exact division, check 6 gives `associativity <= total_lines`, and
check 7 gives an exact second division, `num_sets_ >= 1` follows without a check
of its own. That is what makes `locate(line, num_sets_)` safe from A2d's
unvalidated division by `num_sets`, **for calls through this array**. It does not
answer who owns that guard in general; `locate`'s contract is untouched and U14
stays open, exactly where A2d left it.

---

## 5. The split division, and an overflow that is not a wrong number

The plan's exit criterion is one division:

> non-exact size ÷ (line × assoc) throws

Checks 4 and 7 are that division split in two. They are exactly equivalent, and
the identity is worth writing out because "I split your check in two" is the kind
of claim that should not be taken on trust. Write `size = q(L·A) + r`:

- If `size % L != 0` then `size % (L·A) != 0`, because `L` divides `L·A`.
- If `size % L == 0`, then with `total = size / L`, the remainder
  `size % (L·A)` is exactly `L · (total % A)`.

So `size % (L·A) == 0` holds precisely when `size % L == 0` **and**
`total % A == 0`, which is the conjunction of checks 4 and 7. The reviewer
verified this exhaustively rather than reading the algebra: 14,400,000 triples,
0 mismatches.

The split buys two things.

**Two distinguishable messages**, which section 3 already showed: one division
can only say "this combination is wrong", and the two checks say which of the two
config fields to change.

**The product is never formed, and that is not a micro-optimisation.**
`line_size_bytes()` is bounded only by `int64`. The mapper

```cpp
BlockPackMapper(WeightShape{1,1,1,1}, INT32_MAX, INT32_MAX, 2)
```

is accepted by A2b today and reports `line_size_bytes() == 9223372028264841218`,
about 9.2 exabytes per line. Multiply that by any associativity above 1 and the
result is **signed overflow**, which in C++ is undefined behaviour rather than
wraparound: the compiler is entitled to assume it did not happen and to optimise
on that basis, so the failure is not "a wrong number" that a later check might
catch, it is a program with no defined meaning. No cast rescues it either, since
both operands are already `int64`. This is a different trap from the one
`CPP_NOTES.md` section 22 records, where the fix is to widen an operand before
the multiply.

The split form only ever *divides* by that number, and the exabyte mapper is
refused at check 4 with a well-formed message:

```
SetAssociativeArray: cache_size_bytes 65536 is not a whole number of
                     9223372028264841218-byte lines
                     (cin_block 2147483647 x cout_block 2147483647 x weight_bytes 2)
```

which is also the reachable route to `num_sets == 0` closed. The reviewer
confirmed by grep that no such product is formed anywhere in the file.

---

## 6. The exactness message, `line_size_terms()`, and one thing it does not do

The A2b carried obligation to this unit: the exactness refusal must name
`cin_block`, `cout_block` and `weight_bytes`, not only their product. The
constructor holds a `const AddressMapper&` and cannot see any of the three, so
the mapper has to be asked.

```cpp
// layout.h, on AddressMapper
virtual std::string line_size_terms() const { return std::to_string(line_size_bytes()); }

// block_pack.cpp
std::string BlockPackMapper::line_size_terms() const {
    return "cin_block " + std::to_string(cin_block_) + " x cout_block " +
           std::to_string(cout_block_) + " x weight_bytes " + std::to_string(weight_bytes_);
}
```

**Why an inline default and not a pure virtual**, which is the part the A4a
review designed and which I re-checked before building rather than inheriting:
a pure virtual would oblige *every* `AddressMapper` in the tree to implement a
function about diagnostics. That is sixteen deliberately non-conforming fakes in
`test_layout.cpp` and the four `subclass omits ...` reject cases in
`compile_fail.sh` broken at once, for a message. (A4a's row said thirteen fakes;
the suite reports sixteen caught now, so the count moved and the argument did
not.) The default is always correct if uninformative, so a mapper whose line size
does not decompose into named factors says nothing more and still produces a
well-formed message. Measured blast radius of the actual change: zero. No fake
changed, no reject case changed, and the gate did not move on the implementer's
side of the round.

**And the thing it does not do, which the reviewer caught and I had claimed
otherwise.** I wrote in `set_associative.cpp` that `line_size_bytes()` is read
once, "and a mapper free to compute it per call is a mapper free to answer
differently at step 2 than at step 5". That is true of the **arithmetic** and
false of the **message**. The inline default's body is
`std::to_string(line_size_bytes())`, so for a mapper that does not override
`line_size_terms`, the refusal path asks the mapper a *second* time. Measured
with a counting fake:

```
reads=2   ... is not a whole number of 96-byte lines (96)
```

and with a fake whose second answer differs:

```
reads=2   ... is not a whole number of 96-byte lines (7)
```

One message, two reads, and the two halves contradict each other. No geometry
comes out wrong, since the constructor's own arithmetic still uses the single
local `line_bytes` and nothing is built on the second answer, but the diagnostic can
be self-inconsistent for an inconsistent mapper, which is the exact property the
read-once comment claims to have bought. `BlockPackMapper` is unaffected, since
its override reads its own members and never calls `line_size_bytes()` at all.
This is a **known limitation, not a clean property**, and the honest fix if
anyone wants one is for the default to take the already-read value as an
argument rather than fetching its own.

---

## 7. The `INT32_MAX` slot bound

A4a decided that `num_slots()` returns `int32`, matching `SlotId`'s
representation, and pushed the refusal of anything larger into "the constructor,
where the geometry is validated anyway". This is that refusal:

```
2147483648 lines exceeds the 2147483647 slots a SlotId can name
```

Slot ids are exactly `[0, num_slots())`. A geometry with more lines than that has
upper slots no `SlotId` can name: storage the sweep paid for and never used,
visible only as a hit rate a few points below the truth.

**Why the bound is `INT32_MAX` and not `INT32_MAX - 1`**, which looks like an
off-by-one and is not. `NoSlot` is `SlotId{INT32_MAX}` (B3's convention, sentinels
at the top of the range). At `total_lines == INT32_MAX` the largest *valid* slot
id is `INT32_MAX - 1`, one short of the sentinel, so no real slot can ever be
mistaken for `NoSlot`. Admitting that last value costs nothing and refusing it
would be a rule with no failure behind it.

**Why the accepted side of this bound can only be tested by discrimination.**
`SetAssociativeArray(one_byte_line_mapper, 2147483647, 1)` is accepted, and I ran
it: it constructs, reports `num_sets = 2147483647`, and allocates
`2^31 - 1` `LineId`s, about **17 GB**. So a test that constructs it is a test that
needs 17 GB. The suite therefore checks the rejected side by message and the
accepted side by the fact that the message *differs*, which is the same technique
A2d used for the far-end check. That 17 GB is itself a finding, and it is in
section 12.

---

## 8. Copy and move on `CacheArray`: a measurement, not a style choice

A4a left this as A4b's call: `CacheArray` has a virtual destructor and no copy or
move control, so the compiler generates all four, and the row warned that "a
by-value copy of a derived array through the base compiles and silently drops the
derived state".

I measured it before acting, and **the row's mechanism is half wrong**.

**By-value copy through the base was never reachable.** `CacheArray` is abstract,
so no object of it can exist:

```
error: cannot allocate an object of abstract type 'wcache::CacheArray'
```

The `compile_fail.sh` reject cases that pass a base by value are proving
abstractness, not copy control.

**Assignment through base references was reachable, and it sliced.** This
compiled, before the change:

```cpp
A a1;  A a2;  a2.derived_state = 9;
CacheArray& r1 = a1;  CacheArray& r2 = a2;
r1 = r2;                    // compiles
return a1.derived_state;    // 7, not 9
```

Exit status 7: the assignment copied the base subobject, which holds nothing, and
left the derived state untouched. A silent partial write. For an array that is a
half-assigned cache still answering probes, and it reports a hit rate for a
geometry no level ever had.

**The fix, and why protected rather than deleted:**

```cpp
protected:
    CacheArray()                             = default;
    CacheArray(const CacheArray&)            = default;
    CacheArray(CacheArray&&)                 = default;
    CacheArray& operator=(const CacheArray&) = default;
    CacheArray& operator=(CacheArray&&)      = default;
```

Deleting them would take the operations away from **derived** classes as well.
The engine holds one L1 per core over a swept range of 8 to 256 cores (plan
2.5b), so a container of concrete arrays is the ordinary case rather than a
hypothetical one, and `std::vector<SetAssociativeArray>` needs the derived class
to be copyable or movable. Protected leaves a derived array copyable **as
itself**, where a copy is whole and correct, and makes the base unusable as the
source or target of one, where it would not be. Both halves verified:

```
r1 = r2;                              error: 'operator=' is protected within this context
SetAssociativeArray b = a;            compiles and runs
std::vector<SetAssociativeArray> v;   compiles and runs
```

**Why the defaulted default constructor had to be declared alongside them**, and
this is the trap in the change rather than a detail: declaring *any* constructor
suppresses the implicitly generated default constructor. Delete or default a copy
constructor and `CacheArray()` stops existing, so every derived array in the
tree, the fakes in `test_cache.cpp`, the `ARRAY` fake in `compile_fail.sh`, and
`SetAssociativeArray` itself, stops constructing. The one line
`CacheArray() = default;` is what keeps the rest of the change invisible.

The reviewer proved the new reject case is non-vacuous by reverting `protected`
to `public` and showing that the case then compiles, which is the only way to
know a reject case is rejecting for the reason it names.

---

## 9. Where the class lives, and why it is not in `cache.h`

v1 put `CacheArray` and `SetAssociativeArray` in one header. This tree does not,
and the reason is specific rather than symmetry with `layout.h` / `block_pack.h`.

`SetAssociativeArray` holds a `const AddressMapper&`, so putting it in `cache.h`
would make `cache.h` include `layout.h`. `compile_fail.sh`'s `tryC` preamble
exists precisely to notice that:

> cache.h includes types.h and nothing else, so a case compiled with it proves
> the array interface needs no layout header. If `CacheArray` ever grows a
> dependency on `AddressMapper`, the A4a cases start failing here rather than
> being carried silently by a preamble that already included it.

Folding the concrete class in would not have broken those cases; it would have
quietly made them stop meaning anything, which is worse. So the concrete array
gets `set_associative.h` and its own `.cpp`, and the reviewer's new
`test_set_associative.cpp` is a separate file for the same reason: it keeps
`test_cache.cpp` including only `cache.h`, which is what makes that file evidence
rather than habit.

**Holding the mapper by reference rather than taking `num_sets` as a number**, in
one line each: the array needs the mapper regardless, because `locate` is the only
thing that turns a `LineId` into a set and it is virtual so a future hashed layout
states its own rule; and given the mapper, `num_sets` is derivable from the two
config fields, so deriving it once inside the array is one place that can be wrong
instead of one per construction site. The mapper must outlive the array, which
costs nothing: one mapper instance serves the whole hierarchy.

`final`, for B10's reason applied one class over: a class deriving from this one
would be inheriting the set-associative geometry in order to disagree with part of
it, which is the arrangement that makes a bug in one override invisible in the
others. A fully associative array is a **sibling** implementation of `CacheArray`.

---

## 10. What A4b did not build

**A4c: the five verb bodies.** The way scan, the lowest-free-way rule, the
replace-not-append candidate list, the insert report, and the invalidate. They
are declared with `override` and defined as `std::logic_error` stubs naming the
increment that replaces them, which is exactly B19's convention from A2b:

```cpp
SlotId SetAssociativeArray::probe(LineId) const {
    throw std::logic_error("SetAssociativeArray::probe: not implemented (increment A4c)");
}
```

`logic_error` and not one of the other two tiers, per B27: calling a function
nobody has implemented is programmer error, not a malformed argument and not a
value outside a range.

**`set_of`, deliberately.** The private helper that turns a `LineId` into a set
index reads `Placement`, and whether `Placement`'s fields become tagged is U16,
which the human has not ruled on. A4a stopped where it did partly to avoid
building against a struct that may change shape; writing `set_of` now would have
walked straight into that. The constructor never calls `locate`, so A4b touches
nothing U16 affects.

**The slot fill is built but unobservable.** `slots_.assign(num_slots_, NoLine)`
runs in the constructor, because splitting construction across two increments
would be worse than one member that nothing can read yet. `slots_` is private and
the three verbs that could report it are A4c stubs, so at A4b nothing in the tree
can tell a correct initial fill from a wrong one. That has a consequence for the
sweep, in section 12.

---

## 11. What the reviewer's round added

- **`tests/test_set_associative.cpp`**, new, 81 checks, in its own file so
  `test_cache.cpp` keeps including only `cache.h` (section 9).
- **Conformance contract 9**, `c_line_size_terms_is_informative`, plus two
  non-conforming fakes. `line_size_terms` is a new `AddressMapper` virtual, so it
  belongs in the suite parameterised over the abstract base rather than only in
  A4b's own file. That is what moved `test_block_pack` to 10521 and `test_layout`
  to 9607.
- **14 new compile cases**, 188 to 202, under a new `tryS` preamble, including
  `base assignment through references` as a **reject** and `a whole derived copy`
  as an **accept**, which are the two halves of section 8 pinned.
- **Both obligations I reported were discharged**: `set_associative.{h,cpp}` are
  in `mutation_check.sh`'s `FILES`, so the unit is not untested code wearing a
  passing number (B59's failure mode), and the compile cases above exist.
- **49 A4b mutation cases written, not swept**, since B56 defers the sweep to the
  Phase A gate. Every `sed` was verified to actually match, which catches the
  B45/B59 dead-case failure mode at writing time rather than at the gate.
- **One meta-verification pair, on the exactness check**, and it is the
  interesting one: three *other* sites were incidentally killing that mutation, so
  the weaken/restore pair only proved the check load-bearing after those three
  were disabled. Same masking shape as B60, one round later.
- **My equivalence claim checked rather than believed**: 14,400,000 triples, 0
  mismatches, and the no-product claim confirmed by grep.
- **My read-once claim corrected**, which is section 6.

---

## 12. Open questions

**Q1. U16 is still unruled, and it is carried forward unchanged from A4a.**
Should `Placement`'s fields be typed (`SetIndex set_index` and a tagged tag), so
that the three remaining `Tagged` accept cases in `compile_fail.sh` can close?
Nothing in A4b touched it and nothing in A4b depends on it: the constructor never
calls `locate`, and `set_of` is A4c's. It blocks nothing today. It shapes A2's
interface, so it is cheapest to answer before A4c writes the first code that
reads a `Placement`, and it costs `layout.h`'s cast-free
`line == tag * num_sets + set_index`. A4a's recommendation stands and is only
that: do it, but as its own increment against `layout.h`, with the second tag
type named deliberately.

**Q2. A third site for representability versus plausibility, and it is still
unowned.** A4b bounds what a `SlotId` can *name*, which is a type fact. It does
not bound what a machine can *hold*. `SetAssociativeArray(m, 2147483647, 1)` at a
one-byte line is accepted, constructs, and allocates about **17 GB**; I ran it and
it succeeded. That is the same shape as the `A2b | D1, unowned` row (a mapper
reporting a 9.2-exabyte line) and as U15 (`expand` walking 2^31 elements): three
places now where a value is representable, implausible, and refused by nobody.
The owner question is unchanged (A2b, D1, or the site itself) and A4b
deliberately did not answer it.

**Q3. The exactness message can read two different line sizes** (section 6). The
default `line_size_terms()` calls `line_size_bytes()` a second time, so for a
mapper that does not override it and does not answer consistently, the two halves
of one message disagree. Measured: `reads == 2`, and a drifting fake produces
"not a whole number of 96-byte lines (7)". No geometry is wrong, only the
diagnostic, and `BlockPackMapper` is unaffected. The fix is one signature change
(pass the already-read value in) and it is not made, because it changes an
`AddressMapper` virtual that the conformance suite now has a contract for, which
is a reviewer-visible interface change rather than a comment fix.

**Q4. Three mutations stay unkillable until A4c lands.** The initial slot fill is
unobservable at A4b (section 10), so three cases the reviewer wrote as `kill`
will survive if anyone sweeps A4b before A4c exists. They are correct as written
and should not be weakened to `allow`: the standing rule is that a survivor is
fixed in the test, and here the test that fixes it is A4c's `probe`. What this
needs is for the Phase A gate to know that A4b's sweep is only meaningful after
A4c, rather than reading three survivors as a test gap.

Q1 is the one that wants an answer from you. Q2 and Q3 are recorded findings
that block nothing, and Q4 is a note to the gate.
