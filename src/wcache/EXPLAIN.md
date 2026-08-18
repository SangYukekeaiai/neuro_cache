# EXPLAIN: three landed increments (`Placement` typing, A4c, A5)

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

This file covers **three** landed increments rather than one, which B74 authorises
as a batch. Each gets its own part below and each part is readable on its own:

- **Part I, the `Placement`-typing increment** (U16). Not a unit of the plan: it
  is the A2-interface change A4a raised and A4b deferred, taken as its own
  increment so it does not hide inside A4c's diff.
- **Part II, unit A4c**, the five verb bodies of `SetAssociativeArray`.
- **Part III, unit A5**, `ReplacementPolicy` plus LRU and FIFO.

Changed files, Part I: `native/include/wcache/types.h`,
`native/include/wcache/layout.h`, `native/include/wcache/block_pack.h`,
`native/src/block_pack.cpp`.
Changed files, Part II: `native/include/wcache/set_associative.h`,
`native/src/set_associative.cpp`.
Changed files, Part III: `native/include/wcache/policy.h` (new),
`native/include/wcache/stamp_policy.h` (new), `native/src/stamp_policy.cpp`
(new).
Reviewer's files across the batch: `native/tests/test_set_associative.cpp`,
`native/tests/test_stamp_policy.cpp` (new), `native/tests/test_layout.cpp`,
`native/tests/test_block_pack.cpp`, `native/tests/check.h`,
`native/tests/compile_fail.sh`, `native/tests/mutation_check.sh`.

Plan reference: v3 Part 2.2 (the array/policy split, the four policy verbs, and
"`probe` is const and is **not** an access"), Part 2.3 (the same two structures
at the L2), Part 7 line 1333 (unit A4) and line 1334 (unit A5), Part 3.4's
`install()` pseudocode (which section 16 disputes), and board decisions B29,
B65, B67, B73, B74, B75, B76, B77, B78, B80, B83, B84.

**No build block in this file, deliberately.** A mutation sweep is running in
this tree and mutating production files in place, so any `make test` started
from this role would read mutated sources and report a number that is not the
tree's. The verified counts for this batch belong in `PROGRESS.md`'s Tested
column, written by the role that owns that file after the sweep finishes. What
is stated below about *behaviour* is read from the sources and from the plan,
not from a run.

---

# Part I. The `Placement`-typing increment (U16)

## 1. What landed

Two lines of `types.h` and one line of `block_pack.cpp`, and they close a
question that had been open across three rounds.

```cpp
// types.h: tags::set_index existed at A4a; tags::tag_id is new
using SetIndex = Tagged<std::int64_t, tags::set_index>;   // the seventh tagged scalar
using TagId    = Tagged<std::int64_t, tags::tag_id>;      // the eighth

// layout.h
struct Placement {
    SetIndex set_index;  // in [0, num_sets)
    TagId    tag;
};

// block_pack.cpp
return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};
```

Before this increment `Placement` was `{ std::int64_t set_index; std::int64_t
tag; }`: two raw integers, side by side, in the one struct in the tree whose
whole job is to hand them to a set-associative array.

**`SetIndex`** is which set of an array a line competes in, in `[0, num_sets)`.
It is the first half of `locate`'s answer. It is `int64` because `locate`'s
`num_sets` argument is `int64`, so no conversion sits between the argument and
the answer computed from it.

**`TagId`** is the other half: what tells a line apart from the other lines
mapping to its set, `line / num_sets`. Also `int64`, matching `LineId`, so no
width conversion sits between a line id and the tag derived from it.

## 2. Why the type is not called `Tag`

`Tag` is the obvious name and it is the one name this file cannot use, because
it is already spoken for **twice** inside `types.h`:

```cpp
template <typename Rep, typename Tag>   // (1) Tag is Tagged's second parameter
class Tagged { ... };

namespace tags {                        // (2) tags is the namespace of the
struct set_index;                       //     empty structs that fill it
struct tag_id;
}
```

So the declaration `using Tag = Tagged<std::int64_t, tags::tag>;` would define a
name out of two other live uses of itself: the template parameter it is an
instance of, and the namespace whose members supply that parameter. A reader who
then meets `Tag` in a signature has to work out which of the three is meant, and
a maintainer who later writes `template <typename Rep, typename Tag>` in a file
that also uses the scalar has shadowed one with the other. That is precisely the
class of naming accident the tagged types exist to prevent, and it would be
committing one in the machinery built to stop it.

**`TagId`** was chosen instead, and it is accurate rather than merely consistent
with `LineId` / `CoreId` / `SlotId`. Inside one set, a tag *is* what names the
line; it is an identity in exactly the sense those three are. (B75. Note for the
B3 obligation that owes a `BurstIndex`: that will be the ninth tagged scalar,
not the eighth, and this is where the count moved.)

## 3. The identity stays readable; the code pays in `.get()`

The pair is defined by one equation, and it is the plan's own exit criterion for
A2 (Part 7 line 1331):

```
line == tag * num_sets + set_index
```

`Tagged` has no arithmetic, which is the whole point of it, so the code cannot
spell the identity that way. It spells it:

```cpp
p.tag.get() * num_sets + p.set_index.get() == line.get()
```

`layout.h` therefore keeps the readable form in the comment on `Placement`, and
says outright that **the `.get()`s are the price of the naming and carry no
meaning of their own**. That sentence is load-bearing rather than polite: the
failure mode here is a later reader seeing three unwraps inside an arithmetic
identity, concluding some conversion is happening that matters, and either
"simplifying" the invariant away or writing a second one beside it. The same
holds for the bound `0 <= set_index < num_sets`, which is *not* vacuously true,
because the representation underneath stays signed. (B76.)

## 4. What this closed

**U16 is closed**, under the coordinator's warrant rather than a human answer:
B73 delegated exactly this class of question on 2026-08-18. It is recorded as a
coordinator call and not as a human ruling, because the difference matters if
anyone later reopens it.

**B29's obligation row is finished.** That row had been carried, corrected twice,
and left at "awaiting a ruling". Its state before this increment: five
`Tagged`-constructing `accept` cases in `compile_fail.sh`, of which only **two**
narrowed (int64 to int32) and flipped to `reject` when A4a's non-narrowing
constructor landed. The other three were int64 to int64, where nothing
narrows, so no narrowing rule could ever have reached them. Typing the fields is the only thing
that closes them, and it did, joined by a fourth deliberate flip, `:494 set_index
is a raw int64`. (B77.)

`:494` is **not** a duplicate of `:639`, and this is written down because it is
the kind of thing later read as duplication and deleted. `:639` tests that the
*type* exists. `:494` tests that the *field* has it, proven by reverting the
field to a raw `int64` and watching only `:494` go green.

**One live mutation survivor was found and closed** (B83). The mutation `TagId
aliases LineId` survived the entire suite: nothing anywhere distinguished a tag
from a line id. It is the most tempting alias of the whole set for two reasons
rather than one: both are signed 64-bit, and at `num_sets == 1` a tag genuinely
**is** the line, so the alias is not merely type-compatible but occasionally
true. That earned the one compile case added to the reject set this round, under
B74's budget: a case earns its place by pinning a contract someone could
plausibly violate, and a live survivor is the strongest evidence that someone
could.

**What it did *not* do**: it added no precondition on `tag`. That is a new
obligation row, not part of the answer, and it is section 16's Q3.

---

# Part II. Unit A4c: the five verb bodies

## 5. The geometry, and one line through the whole array

The running geometry is A4b's, and it is a real one: a `3 x 3 x 512 x 512` layer
at `cin_block = cout_block = 16`, `weight_bytes = 1`, with a 64 KB L1 at
associativity 8.

```cpp
const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);
SetAssociativeArray  l1(m, 65536, 8);
```

which A4b's constructor validates into:

```
line_size_bytes = 256      num_lines  = 9216       (the whole tensor)
total_lines     = 256      num_sets   = 32
associativity   = 8        num_slots  = 256
```

So: **32 sets of 8 ways, 256 slots, slot ids `[0, 256)`.**

Take `LineId{1000}`, which is in range because `1000 < 9216`. Everything below
follows from `locate`:

```
locate(1000, 32)  ->  Placement{ SetIndex{1000 % 32}, TagId{1000 / 32} }
                  ->  Placement{ SetIndex{8},         TagId{31}        }
```

Check the identity: `31 * 32 + 8 == 1000`. Good.

## 6. `base_slot`, and why a set is exactly `[base, base + associativity())`

`base_slot` is the one piece of geometry all three read-only verbs share:

```cpp
std::int32_t SetAssociativeArray::base_slot(LineId line) const {
    const std::int64_t set_index = mapper_.locate(line, num_sets_).set_index.get();
    return static_cast<std::int32_t>(set_index * associativity_);
}
```

For line 1000: `base_slot = 8 * 8 = 64`, so the slots that may hold line 1000 are
exactly

```
slot 64  65  66  67  68  69  70  71          <- set 8, all eight ways
```

**Why a set is a contiguous run.** Slots are laid out set-major: set 0 owns slots
`[0, 8)`, set 1 owns `[8, 16)`, … set 31 owns `[248, 256)`. Every set has the
same width, `associativity()`, so set *s* starts at `s * associativity()` and
ends one before `(s + 1) * associativity()`. Nothing else is needed: one
multiply gives the base, and every verb is that multiply plus a scan of at most
`associativity()` cells. There is no per-set indirection, no free list, and no
way index stored anywhere: the position in `slots_` *is* the way index.

Two facts make the cast in `base_slot` safe rather than hopeful. `locate`
range-checks the line and bounds the set index at `[0, num_sets_)`, so the
product is at most `(num_sets_ - 1) * associativity_`, which is `num_slots_ -
associativity_`. And the constructor bounded `num_slots_` at `INT32_MAX`. So the
multiply is done in `int64` and the result is *known* to fit an `int32` before
the cast, not assumed to.

`base_slot` is B65's `set_of`, written at last. A4b deliberately left it
unwritten because it reads `Placement` and U16 was open; Part I closed U16, so
it is written here, and written in the form its three callers actually need. It
returns the **base slot**, not the set index, because the set index alone is used
by nothing: `probe`, `free_slot` and `victim_candidates` each want the base, so
returning a `SetIndex` and multiplying at three call sites would be the same
expression written three times.

**It reads `set_index` and never `tag`**, and that is worth stating rather than
noticing. The identity `line == tag * num_sets + set_index` makes the tag look
like the natural thing to compare a resident line against, and forming `tag *
num_sets` is signed overflow for a large enough tag, which `Placement` has no
precondition against (section 16, Q3). **No expression anywhere in this class
forms that product.** The slot array stores whole line ids, so a way scan
compares line ids directly and the tag half of `locate`'s answer is never
touched. A4c avoids the hazard entirely by never reading the field.

## 7. Miss, fill, hit, invalidate, with actual slot numbers

Start from a cold array: all 256 slots hold `NoLine`.

### `probe(1000)`: miss

```cpp
SlotId SetAssociativeArray::probe(LineId line) const {
    const std::int32_t base = base_slot(line);
    for (std::int32_t w = 0; w < associativity_; ++w) {
        if (slots_[as_size(base + w)] == line) return SlotId{base + w};
    }
    return NoSlot;
}
```

`base = 64`. It compares `slots_[64] … slots_[71]` against `LineId{1000}`. All
eight hold `NoLine`, which is `LineId{INT64_MAX}`, so none matches.

```
probe(1000) -> NoSlot                       (SlotId{2147483647})
```

`NoLine` cannot be mistaken for a resident line here, and that is a fact rather
than a hope: it is `INT64_MAX`, one past what any mapper can produce, and
`locate` has already refused any line outside `[0, num_lines())`. That is what
makes "free" and "holds a line" a single comparison in the scan instead of a
second valid bit per slot.

### `free_slot(1000)`: the lowest free way

```
scan 64: NoLine  -> answer
free_slot(1000) -> SlotId{64}
```

### `insert(1000, SlotId{64})`: no eviction

```cpp
const std::int32_t s = slot_or_reject("insert", slot);   // 64, in [0, 256)
const LineId previous = slots_[64];                      // NoLine
slots_[64] = LineId{1000};
return InsertResult{false, NoLine};
```

```
insert(1000, 64) -> InsertResult{ evicted = false, evicted_line = NoLine }
```

### `probe(1000)` again: hit

`base = 64` as before; `slots_[64] == LineId{1000}` on the first comparison.

```
probe(1000) -> SlotId{64}
```

Note what did **not** happen: nothing recorded the hit. The engine calls
`policy.on_hit(SlotId{64})` itself. Section 9 is why.

### `invalidate(SlotId{64})`

```cpp
slots_[as_size(slot_or_reject("invalidate", slot))] = NoLine;
```

Slot 64 is free again, and a later `probe(1000)` returns `NoSlot`. Invalidating
a slot that is already free leaves it free and needs no branch: the write is the
same either way.

### The full set: `victim_candidates`

Now fill set 8. The lines that map to it are the ones with `line % 32 == 8`:

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

Each was placed by `free_slot` returning the lowest free way, so the eight
arrived in slot order. Now line 1000 is requested again:

```
probe(1000)      -> NoSlot        (none of slots 64..71 holds 1000)
free_slot(1000)  -> NoSlot        (none of slots 64..71 holds NoLine)
victim_candidates(1000, out):

  out = [ {64, 8}, {65, 40}, {66, 72}, {67, 104},
          {68, 136}, {69, 168}, {70, 200}, {71, 232} ]
```

Eight entries, the whole set, each pairing a slot with the line living in it. The
line travels **beside** the slot rather than being looked up afterwards, because
a policy that has to exclude a line (the one with an outstanding MSHR, say) would
otherwise need a reference back to the array and a slot-to-line accessor, which
puts the array inside the module the 2.2 split exists to keep out of it. It costs
nothing: the array is already reading exactly these cells to enumerate the set.

Free ways, when there are any, appear as candidates carrying `NoLine` rather
than being omitted. In the engine there are never any, because this verb is
reached only after `free_slot` answered `NoSlot`. Reporting them keeps the list
one **whole set**, which is what makes "every slot appears under exactly one set"
checkable from outside.

### `insert` over an occupant

Suppose the policy picks slot 65:

```cpp
const LineId previous = slots_[65];    // LineId{40}
slots_[65] = LineId{1000};
return InsertResult{true, LineId{40}};
```

```
insert(1000, 65) -> InsertResult{ evicted = true, evicted_line = LineId{40} }
```

and `probe(40)` now returns `NoSlot` while `probe(1000)` returns `SlotId{65}`.

## 8. Three design choices, and what each buys

### `free_slot` returns the **lowest** free way

The scan runs `w = 0` upward and returns the first `NoLine` it meets. It could
have returned any free way and still been correct.

What the ordering buys is that **the answer is a function of the array's state
alone**. Two arrays given the same insert sequence agree slot for slot, not just
set for set. An implementation free to return an arbitrary free way would still
satisfy every word of `CacheArray`'s contract and would make every fixture below
it unwritable: the table in section 7 could then only say "line 40 is *somewhere*
in `[64, 72)`", and a test that asserts that asserts almost nothing. It also
makes the cold-start behaviour of the whole model deterministic without a rule
anywhere else in the tree having to say so.

### `victim_candidates` computes `base_slot` **before** `out.clear()`

```cpp
const std::int32_t base = base_slot(line);   // the only thing here that can throw
out.clear();
for (...) out.push_back(...);
```

The order is the contract, not tidiness. `base_slot` calls `locate`, which throws
`std::out_of_range` for a line outside `[0, num_lines())`. It is the only
expression in the function that can throw. Putting it first means **a call that
throws leaves `out` exactly as it was** rather than emptied.

That matters because the caller's buffer is reused. With `clear()` first, a
caller that catches the exception and continues finds its buffer silently
emptied by a call that did nothing else, the same failure `expand` avoids with
its rule that "every range check must run before the first append", applied here
to a verb that *assigns* instead of appending.

The `clear()` itself is also the contract rather than tidiness, and it is the
opposite of `expand`'s choice deliberately. `expand` appends because its
documented use accumulates a whole tick across cores into one buffer. A candidate
list is one set's worth, consumed immediately by one `pick_victim` call. An
appending version would let a caller that forgot to clear pick a victim from a
previous fill in a **different set**, and the line would then be stored where
`probe` can never look for it: no crash, just a hit rate quietly below the truth
for the whole run. Buffer reuse is unaffected, since clearing keeps the capacity.

### `insert` reports `evicted == (evicted_line != NoLine)` **by construction**

```cpp
if (previous == NoLine) return InsertResult{false, NoLine};
return InsertResult{true, previous};
```

Two returns, and neither can produce a pair where the flag and the line disagree.
The alternative, writing `InsertResult{previous != NoLine, previous}` once, or
worse, setting the flag on one path and the line on another, leaves open a state
that has no meaning: `evicted = true` with `evicted_line = NoLine`, or `false`
with a real line. A caller handling the inclusive branch (4.4, N8) reads the flag
to decide whether to back-invalidate and reads the line to know *what* to
back-invalidate. Those two reads must agree, and here they cannot fail to,
because the only two `InsertResult`s this function can produce are both
consistent as literals.

Both fields are reported rather than only the bool, because the caller needs
both: the level counts evictions, and under `inclusion = inclusive` it has to
know **which** line left the L2 in order to back-invalidate it out of the L1s.
Reporting only a bool would force the caller to read the slot before inserting:
the same read done twice, and a rule that is easy to forget once and then
undercount for a whole sweep.

## 9. Why `probe` being `const` is real, and not a promise

Plan 2.2 requires that "`probe` is const and is **not** an access". The usual way
that requirement fails is not by someone writing `mutable`: it is by a probe
recording that it happened (a counter, a last-touched slot, a small cache of the
last looked-up line) and a later verb reading it back. The `const` keyword does
not stop that; `mutable` members and pointed-to state are both reachable from a
`const` member function.

Here it is not a promise, for one reason that can be checked by reading the
class's private section in full:

```cpp
const AddressMapper& mapper_;
std::int32_t associativity_ = 0;
std::int64_t num_sets_      = 0;
std::int32_t num_slots_     = 0;
std::vector<LineId> slots_;
```

**There is no mutable state at all.** Three geometry scalars fixed at
construction, one reference to a mapper whose own state is fixed at construction
(and whose `locate` is a `const` virtual, so an override cannot mutate it
either), and the slot array, which `probe` reads and only the two non-`const`
verbs write. There is nothing for a probe to record. The property is structural,
not a rule someone is keeping.

Two things rest on it. A speculative lookup must not perturb the recency stack,
which is why the engine calls `policy.on_hit` explicitly rather than having the
array do it. And 4.6's prefetcher tests residency on a path that must not touch
replacement state **at all**: a prefetch that finds the line resident drops it
and records nothing (I15). That is only implementable if probing and recording a
use are two separate calls, which is why the array never names a policy.

The same asymmetry runs through the rest of the class: `insert` range-checks the
slot and does **not** range-check the line. That is deliberate rather than an
omission. An out-of-range slot is an out-of-bounds write into `slots_`:
undefined behaviour, and reachable by one plausible mistake, since
`insert(line, free_slot(line))` without checking for `NoSlot` passes
`INT32_MAX` straight in. A line outside the mapper's range is merely a stored
value, and every path that reads it back goes through `locate` and is refused
there: wrong, but neither silent nor memory-unsafe.

---

# Part III. Unit A5: `ReplacementPolicy`, LRU and FIFO

## 10. The interface, and the one mechanism under both policies

`policy.h` holds the four verbs Part 2.2 names, in the order it names them:

```cpp
class ReplacementPolicy {
public:
    virtual ~ReplacementPolicy() = default;
    virtual void   on_hit(SlotId slot)        = 0;
    virtual void   on_fill(SlotId slot)       = 0;
    virtual void   on_invalidate(SlotId slot) = 0;
    virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;
};
```

Three notifications and one question, and that asymmetry is the design: the
array reports what happened to a slot, and the policy is asked only at the point
where the array genuinely cannot answer. Nothing returns state, because a
policy's state is its own: D2's victim-age instrument is a statistic computed at
the eviction site, not a getter on this interface.

`stamp_policy.h` holds the implementations, in a **separate header**, and for the
same specific reason `layout.h` / `block_pack.h` and `cache.h` /
`set_associative.h` are split rather than for symmetry: a `compile_fail.sh` case
compiled against `policy.h` alone proves the interface needs nothing but a
`SlotId` and a `Candidate`. Folding the implementations in would make that
unprovable.

**Both policies are the same machine under one different wire.** Each slot
carries a stamp; the victim is the smallest stamp among the candidates; the two
differ only in whether a hit refreshes the stamp. So they share an abstract base
rather than being written twice, which also means `pick_victim` and the
order-independence rule are written once and tested once instead of per policy.

```cpp
class StampPolicy : public ReplacementPolicy {          // abstract: no on_hit
    std::vector<std::int64_t> stamp_;   // one per slot, kNeverStamped when empty
    std::int64_t              next_stamp_;
protected:
    void stamp(SlotId slot);            // stamp_[slot] = next_stamp_++;
};

class LruPolicy  final : public StampPolicy { void on_hit(SlotId s) override; };  // stamp(s)
class FifoPolicy final : public StampPolicy { void on_hit(SlotId)   override; };  // {}
```

The counter starts at **1**, and `kNeverStamped` is **0**. That is not an
arbitrary sentinel: it makes "never filled" smaller than every stamp ever handed
out, so a never-filled slot is automatically the preferred victim, which is the
right preference on its merits, since such a slot holds no line and evicting it
costs nothing.

`on_invalidate` writes `kNeverStamped` back, so it is an **observable** verb
rather than a formality. Leaving the previous occupant's stamp in place would
make an invalidated slot compete on the age of a line that is gone.

`next_stamp_` is `int64` for the reason `RefusalOrder` is (Q8): it advances once
per hit or per fill across a whole sweep, and 32 bits is reachable at the corpus
size while 64 is not.

## 11. LRU and FIFO driving the same array, and diverging

Same array as Part II: 32 sets of 8, set 8 at slots `[64, 72)`. Same access
sequence, replayed once under each policy. Each policy is constructed with
`num_slots() == 256`, so `stamp_` has 256 entries, all `0`.

**Steps 1 to 8, the eight fills.** For each line, the engine gets `NoSlot` from
`probe`, a slot from `free_slot`, calls `insert`, then calls `on_fill`.

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

**Step 9: line 8 is accessed again.** `probe(8)` returns `SlotId{64}`, and the
engine calls `on_hit(SlotId{64})`. **Here the two diverge**, and this is the only
line of the whole run where they differ:

```
LRU   on_hit(64)  ->  stamp(64)  ->  stamp_[64] = 9,  next_stamp_ = 10
FIFO  on_hit(64)  ->  { }        ->  stamp_[64] = 1,  next_stamp_ =  9
```

**Step 10: line 1000 misses into the same set.** `free_slot` returns `NoSlot`,
`victim_candidates` produces the eight-entry list from section 7, and
`pick_victim` is called on it.

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

**LRU keeps line 8 because it was just used**, and throws out line 40, the
least recently *used*. **FIFO throws out line 8 anyway**, because it was
installed first and a hit is the event FIFO is defined to ignore. Two different
lines leave the cache, from two different slots, off one identical event
sequence, driving one unchanged array, which is the plan's A5 exit criterion
made concrete.

The fill that follows stamps the new occupant:

```
LRU  : on_fill(65) -> stamp_[65] = 10, next_stamp_ = 11
FIFO : on_fill(64) -> stamp_[64] =  9, next_stamp_ = 10
```

## 12. Why `pick_victim` breaks ties by the **smallest slot id**

This is the important one, and it is not a style choice.

```cpp
SlotId       victim = candidates[0].slot;
std::int64_t oldest = stamp_[index_or_reject("pick_victim", victim)];

for (std::size_t i = 1; i < candidates.size(); ++i) {
    const SlotId       slot = candidates[i].slot;
    const std::int64_t age  = stamp_[index_or_reject("pick_victim", slot)];
    if (age < oldest || (age == oldest && slot < victim)) {
        oldest = age;
        victim = slot;
    }
}
return victim;
```

`policy.h` states the obligation the plan puts on this unit: **no implementation
may depend on the order of `candidates`.** Permuting the vector may not change
the answer.

The natural way to write this loop is `if (age < oldest)`, keeping the **first**
minimum seen. That is where order dependence enters, and it is invisible in
practice until it is not. Two *occupied* slots can never tie, because each stamp
is a distinct value of a strictly increasing counter. But a slot that has never
been filled, or one that has been invalidated, carries `kNeverStamped`, and
**several of those can tie**. With `if (age < oldest)` alone, the answer among
them is whichever the vector happened to hold first, which is exactly the
dependency the criterion forbids.

Adding `|| (age == oldest && slot < victim)` makes the result the pair-wise
minimum of `(stamp, slot_id)` under lexicographic order. That is a **minimum over
a set**, and a minimum over a set does not depend on the order the set is
presented in. So order-independence is discharged **mechanically**, by the
structure of the comparison, rather than by an implementer promising to keep it.

Worked, on a set with a tie. Take the LRU stamps from section 11 and invalidate
slots 66 and 69 (their lines were back-invalidated by an L2 eviction, 4.4):

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

Now hand the *same* set in reverse, 71 → 64, which is a legal permutation the
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

Same answer. Without the tie-break the first run answers 66 and the second
answers 69, and both are "correct" in the sense that both evict an empty slot,
which is why this bug does not show up as a failure, only as two builds of the
same simulator disagreeing about which slot a line landed in.

**Why the criterion exists at all**, since with only LRU and FIFO built both pick
"oldest by a stamp" and an order-dependent implementation would pass every
fixture: it keeps the interface open for a policy that does **not** pick by age.
Random draws a candidate; if the candidate list's order carried meaning, Random's
draw would silently be a draw over an ordering the array chose rather than over
the set. Nothing else announces that regression, which is why the obligation is
stated on the interface where an implementer reads it rather than in a test.

Two more things `pick_victim` does, briefly. It seeds `victim` from
`candidates[0]` rather than from a sentinel stamp, so there is no "no victim yet"
state to get wrong and the answer is **one of the candidates by construction**.
And it refuses an empty candidate set with `std::invalid_argument`, and not as
defensive padding: the minimum of nothing has no answer, so the alternative to
refusing is returning a slot id that names no candidate, which the caller then
installs a line into.

## 13. Why `FifoPolicy::on_hit` is deliberately empty

```cpp
// stamp_policy.cpp
void FifoPolicy::on_hit(SlotId) {}
```

An empty override in a diff reads as an unfinished stub, so both the header and
the `.cpp` say outright that it is not one. FIFO orders by **insertion**, and
insertion is what `on_fill` records. A hit is exactly the event this policy is
*defined* to ignore, and it is the whole of its difference from LRU, and section 11
is that difference measured.

The parameter is unnamed so the empty body stays warning-clean without a
cast-to-void.

The cost of the empty body is section 16's Q2: it is also the one verb in the
policy that performs **no bound check**, because `index_or_reject` lives inside
`stamp()` and `stamp()` is never called. A foreign slot id is caught under LRU
and silently accepted under FIFO.

## 14. Random: a placeholder that refuses at config time

Plan Part 7 line 1334: "Random is a placeholder: it stays in the enum, is
rejected at config load, and is not implemented (Q5)." That is made literal.

```cpp
enum class PolicyKind : std::uint8_t { LRU = 0, FIFO = 1, RANDOM = 2 };

std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots) {
    switch (kind) {
        case PolicyKind::LRU:  return std::make_unique<LruPolicy>(num_slots);
        case PolicyKind::FIFO: return std::make_unique<FifoPolicy>(num_slots);
        case PolicyKind::RANDOM:
            reject("make_policy",
                   "policy 'random' is a placeholder and is not implemented; use 'lru' or 'fifo'");
    }
    throw std::logic_error("make_policy: unknown PolicyKind");
}
```

**`RANDOM` stays in the enum**, and that is the decision rather than an oversight.
Drop it and `policy = random` in a config file becomes an *unknown name*, so the
run reports a typo where it should report a missing feature. Keeping it makes the
refusal say the true thing (V29).

**`std::invalid_argument`, not `logic_error`.** `logic_error` is the tree's tier
for programmer error, a function called before it was written. This is a
**config value refused**: D1's config load reaches this call with a value a human
typed, and it must be refused under `-DNDEBUG` the same way
`SetAssociativeArray`'s geometry checks are.

**One refusal site.** This is the only place a `PolicyKind` becomes an object, so
no config path can pick a policy the enum admits and silently fall back to LRU.
The unreachable `logic_error` after the switch is there for the same reason
`types.h`'s `Axis` accessors have theirs: falling back to LRU is the one wrong
answer here, because a config naming a policy this build does not have would then
run to completion under a policy nobody selected, and the results row would
attribute a hit rate to the wrong one.

`pick_victim` is **not `const`**, and that is the openness the whole
order-independence criterion is protecting. A Random policy draws from an RNG,
which is state it must advance. `const` on a virtual is part of the signature, so
an override may not drop it, so a `const pick_victim` today would be
exactly the interface change adding Random would force tomorrow, across both
levels and every fixture built against it. It is left non-`const` now, once, for
a class that does not exist yet.

---

# Part IV. The batch as a whole

## 15. What is not built, and why

**`on_evict`.** The four verbs of Part 2.2 are built and there is no fifth. Part
3.4's `install()` pseudocode calls one. That is section 16's Q1 and it is a plan
defect rather than a coding choice, so it is laid out there rather than resolved
here.

**Random's implementation.** Deliberate, per the plan and Q5. What is built is
the refusal (section 14) and the interface shape Random needs: a non-`const`
`pick_victim`, and a candidate **set** whose order carries no meaning. The
answer to Random's reproducibility question is already settled in the plan and
costs nothing to keep waiting for: `random_seed` becomes an explicit config
field emitted in every results row, each cache instance gets its own RNG seeded
from `(random_seed, level, core_id)`, and Random points run at three seeds with
mean and spread reported. Until someone wants it, the only obligation on A5 is
the order-agnosticism section 12 discharges.

**No `num_slots()` accessor on `StampPolicy`**, and this is where B20's argument
for `BlockPackMapper`'s accessors does **not** apply. B20's point was that a
constructor whose arithmetic is unobservable cannot be checked. Here the sizing
*is* already observable: `index_or_reject` refuses the first slot id past the end
and names the count in its message. An accessor would be a second way to read a
fact the interface already reports.

## 16. Open questions

**Q1 and Q2 want a human eye. Q3 is a carried finding.**

---

### Q1. The plan's `on_evict` discrepancy: a plan defect that needs a ruling

The plan says two different things, and only one of them can be built.

**Part 2.2, line 289**, the authoritative interface row for L1 replacement state:

> `ReplacementPolicy { on_hit, on_fill, on_invalidate, pick_victim }`

Four verbs. Part 2.3's L2 row names the same interface. Nothing in Part 2 anywhere
mentions a fifth.

**Part 3.4, lines 615-619**, the `install()` pseudocode:

```
install(cache, line):
    slot = cache.free_slot(line)
    if slot == NoSlot:
        slot = cache.policy.pick_victim(cache.victim_candidates(line))
    res = cache.insert(line, slot)
    cache.policy.on_fill(slot)          # line 617
    if res.evicted:
        cache.policy.on_evict(slot)     # line 619
```

`on_evict(slot)` is called **after** `on_fill(slot)`, on the **same slot**.

**Why that ordering cannot be right for any stamp policy.** `on_fill(slot)`
writes the *new* occupant's stamp. An `on_evict(slot)` arriving afterwards, on
the same slot, would have to do one of two things, and both are wrong:

- If it records something about the line that *left* (its age, its stamp), it is
  reading a cell that `on_fill` has already overwritten one line earlier. Under
  the section 11 sequence, `on_fill(65)` sets `stamp_[65] = 10`; an `on_evict(65)`
  looking for line 40's age finds 10, the stamp of the line that just replaced it.
- If it *writes* the slot's state (resets it, ages it), it clobbers the stamp
  `on_fill` wrote one line earlier, and the freshly installed line inherits the
  eviction's bookkeeping instead of its own install time.

Either way the fill and the eviction fight over one cell, and the fill loses or
the evict does.

**Built to Part 2.2's four**, which is the more authoritative of the two: Part 2
is where the module interfaces are specified, and Part 3.4 is pseudocode for the
engine that will use them, written before either existed. Section 15 records the
omission rather than hiding it.

**The trade, so it can be ruled on.** The plausible motive for `on_evict` is
Part 2.2's own instrument column: **victim age distribution**, which D2 owes. The
question is where that statistic is computed.

| | Compute at the eviction site (no `on_evict`) | Add `on_evict` to the interface |
|---|---|---|
| Where the age comes from | the caller already holds `res.evicted_line` and the slot; the level computes the age from what it knows | the policy reports it, which means the policy needs a getter, or `on_evict` returns a value |
| Interface cost | none; four verbs stay four | a fifth verb on a base every policy must implement, including Random and any future one |
| Ordering | no ordering question exists | needs a ruling: `on_evict` **before** `on_fill`, or the two touch different state |
| Does it break the 2.2 split? | no | risks it: "nothing here returns state, because a policy's state is its own" is `policy.h`'s stated rule, and an `on_evict` that *reports* an age is a getter in disguise |

**If `on_evict` is wanted, the ruling needed is the ordering**, and the answer
that works is `on_evict(slot)` **before** `on_fill(slot)`, while the slot still
describes the line that is leaving. That is a change to the plan's line 619, not
to any code written here.

**This is a plan defect either way.** Whichever answer is taken, Part 2.2 and
Part 3.4 currently disagree, and the disagreement is silent: an implementer
reading only 3.4 builds five verbs, an implementer reading only 2.2 builds four,
and both believe they matched the plan. It should be corrected in the plan
document rather than resolved by whichever unit happens to notice.

---

### Q2. `FifoPolicy::on_hit` does no bound check, and that is pinned as behaviour rather than as a rule

Every other verb on `StampPolicy` routes through one shared check:

```cpp
std::size_t StampPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= stamp_.size()) {
        throw std::out_of_range(...);
    }
    return static_cast<std::size_t>(s);
}
```

`on_fill`, `on_invalidate`, `stamp` and `pick_victim` all call it, so there is one check and
no two verbs can disagree about the range. `LruPolicy::on_hit` calls `stamp()`,
so it inherits the check. **`FifoPolicy::on_hit` has an empty body, so it calls
nothing, so it checks nothing.**

The consequence, concretely: a policy sized for a 256-slot L1 handed
`on_hit(SlotId{9999})`, a slot id belonging to the L2's array, say, or to a
differently sized level, throws under LRU and is **silently accepted** under
FIFO. Same call, same mistake, two different outcomes depending on a config field.

It is not a memory-safety bug. The empty body writes nothing, so there is no
out-of-bounds access; the id is simply ignored. What it costs is the diagnostic:
the mistake that LRU catches on the first hit goes unreported under FIFO until
some *other* verb on the same policy is handed the same bad id.

**Why it is not simply fixed.** Adding a check to an empty body means adding a
call whose only purpose is to throw, on the hottest verb in the model, in the one
policy defined to do nothing on that event. That is defensible and it is also a
real cost. The alternatives are: check in the base by making `on_hit` non-virtual
and calling a protected hook (which changes the interface Part 2.2 specifies);
accept the asymmetry and state it as the contract; or state that bound-checking
is per-verb best effort and not a guarantee of the interface.

**What is true today**: it is pinned as *behaviour*, since the tests record what each
policy does with a foreign slot id, but no rule anywhere says which of the three
options above is the intended one. That is the gap. A later reader finding LRU
strict and FIFO permissive has nothing to tell them whether that is a decision or
an accident, which is exactly why it is written down here.

---

### Q3. Q2's plausibility bound, now with a **fourth** site, plus one hazard `Placement` still carries

This is the carried row, and this batch adds to it in two ways.

**The fourth site: `StampPolicy` is 8 bytes per slot.** `stamp_` is a
`std::vector<std::int64_t>`, one entry per slot. At the geometry A4b accepts
(`total_lines == INT32_MAX`, the largest a `SlotId` can name) that is

```
2147483647 slots x 8 bytes = 17,179,869,176 bytes  ~= 17.2 GB per policy instance
```

and it sits **beside** the array's own `slots_`, which is a
`std::vector<LineId>`, also 8 bytes per slot, also about 17.2 GB. Worse, the
engine holds **one L1 policy per core** over a swept range of 8 to 256 cores
(plan 2.5b), so the policy figure multiplies where the array figure already did.
Nothing refuses it. `StampPolicy`'s constructor checks `num_slots >= 1` and
allocates whatever it is given.

The four sites now on the same row:

| Site | What is representable and implausible | Raised |
|---|---|---|
| `BlockPackMapper` | a mapper reporting a 9.2-exabyte line size, from which D1 computes `num_sets == 0` | A2b |
| `expand` (U15) | `count = INT32_MAX` at stride 1 walks 2^31 elements into a local vector | A2d |
| `SetAssociativeArray` | `total_lines == INT32_MAX` allocates ~17.2 GB of `slots_` | A4b |
| **`StampPolicy`** | **the same geometry allocates ~17.2 GB of `stamp_`, once per core, over 8 to 256 cores** | **A5, this batch** |

**Owner: D1, by B80**, with **one shared bound** rather than four scattered ones,
because the question is a modelling one (what can a machine hold) rather than a
typing one (what can this integer represent), and D1 is where the size model
lives. That is a dated, reasoned deferral rather than an oversight; it is
recorded again here only because the site count moved, not because the owner
question reopened.

**U14 and U15's general bound stay open and unowned in the same sense.** A4b's
constructor guarantees `num_sets_ >= 1`, which closes the reachable division by
zero *through this array*; that is a narrowing of the reachable set, not an
answer. `locate`'s contract is untouched, any other caller computing a set count
is unaffected, and nothing in the tree stops `locate(l, 0)` today.

**And `Placement` still has no precondition on `tag`.** The typing increment
(Part I) typed the field; it did **not** give it a range. So `tag * num_sets` is
signed overflow, which is undefined behaviour and not a wrong number, for any `tag >
INT64_MAX / num_sets`. Typing makes the hazard harder to construct by accident
and not one bit less present, and reading a `TagId` as though it carried a range
is exactly the mistake this row exists to prevent.

**Worth saying explicitly: A4c avoids it entirely by never reading the tag.**
`base_slot` reads `set_index` and nothing else, and `slots_` stores whole line
ids so a way scan compares line ids directly. The product `tag * num_sets` is
formed nowhere in `set_associative.cpp`. That is the same defensive shape B63
took when it split one division in two precisely so the product `line_size_bytes
* associativity` would never be formed, so the fix, if D1 or whoever gives
`Placement` a constructor wants one, has a precedent in the tree. It is not a
defect today because no caller constructs a `Placement` by hand; it becomes one
the moment something other than `locate` does.

---

**Summary of what wants your attention.** Q1 is a genuine contradiction in the
plan document and needs your ruling on whether `on_evict` is wanted at all, and
if so on its ordering. Q2 is a small asymmetry that has been pinned as behaviour
and wants a stated rule so it does not read later as an accident. Q3 blocks
nothing and is carried forward with one new site and one restated hazard.
