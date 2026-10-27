# Under review: STALL 2 fixes, then unit 3

> Rolling scratchpad. The signedness / D1 / D2 / tests explanation was erased
> when this replaced it; it is summarised permanently in `FINDINGS.md` under
> "Decisions closed 2026-08-06".

**Status:** the reviewer found 8 defects in the change set you approved last,
4 of them high. **I stalled the pipeline and fixed all 8 before letting unit
3 land.** Full detail in `FINDINGS.md` under STALL 2. Unit 3 is implemented
and unchanged by the stall; its review is Part A onward below.

---

# STALL 2, and what it changed

Two of the eight were correctness holes in the code **you already approved**,
and they are the same hole seen twice: a check that is correct but lives
where the sweep build cannot see it.

## The short version

| # | Defect | Fix |
|---|---|---|
| F8 | `expand` validated only the burst axis, so 3 of 4 anchor coordinates were unchecked under `-DNDEBUG` | `line_of` throws on all four |
| F9 | `locate` returned a **negative** `set_index` in the sweep build, which a cache array would subscript out of bounds | `locate`'s range check throws |
| F10 | `count < 0` was silently swallowed while `stride <= 0` threw | `count < 0` throws |
| F11 | **No shape in the suite had `KH != KW`**, so five KH/KW confusions passed 125/125 | new group J on `{2,5,8,8}` |
| F12 | the `throw` was tested only on the COUT axis | group H loops all four |
| F13 | "64,000 bursts" gave the production path only 2,778 non-trivial cases | generator rebalanced, now 22,843 |
| F14 | `make test` ran a **stale binary** after any change to `tests/check.h` | header prerequisites added |
| F15 | the partial-tick contract on a throw was undocumented | stated in `layout.h` |

## F8 and F9, with the numbers

D1 made the extent check a throw as "the only thing standing between a
malformed trace and line ids that are wrong but look fine." It covered one
coordinate of four. Measured against the release library, real layer, all
with a perfectly legal `axis=COUT, count=4, stride=1` burst and one bad
anchor coordinate:

```
legal   cin=0    -> [65536]   in_range=YES
BAD     cin=-1   -> [65536]   in_range=YES   <- identical to the legal line
BAD     cin=-4   -> [65408]   in_range=YES   <- a real neighbouring line
BAD     cin=512  -> [81920]   in_range=YES   <- one past CIN, still inside
BAD     kw=3     -> [98304]   in_range=YES   <- one past KW, still inside
BAD     cout=-1  -> THREW                    <- the only one checked
```

**This also falsifies something `types.h` was claiming**, and the reviewer
was right to call it out. Signedness does *not* keep a bad coordinate visibly
negative: integer division truncates toward zero, so any `cin` in
`[-(cin_block-1), -1]` lands on block 0 and produces an ordinary-looking
line. That is the `cin=-1` row above. Only the range check catches it. The
comment now says so.

F9 is the sharper one, because it is a **regression introduced by the
signedness change I recommended**. Signed `%` follows its dividend:

```
locate(-32767, 1024) -> set_index = -1023
```

Under the old `uint64_t` a garbage line still gave an in-range set index:
wrong line, safe index. And it is reachable end to end, which I verified:

```
expand(anchor kh=-1) -> line -32767
locate(that, 1024)   -> set_index -1023
a 32-way array subscripts slots_ at -1023 * 32 = -32736, against 32,768 slots
```

Out of bounds, not a wrong answer. I had recorded the widened assert as the
mitigation for exactly this and missed that an assert is what the sweep build
does not have.

**After the fix**, every row above throws with the coordinate and the shape
in the message, and the buffer is left untouched.

## F11, the one I would not have found by reading

Every shape in the suite was square, so nothing could tell `KH` from `KW`.
Five separate confusions passed all 125 checks:

| Mutation | Before | After |
|---|---|---|
| `line_stride(KH)` reads `shape_.KH` | **125, 0 failures** | 167, 4 failures |
| `line_of` flatten uses `shape_.KH` | **125, 0 failures** | 167, 5 failures |
| `WeightShape::extent(KH)` returns `KW` | **125, 0 failures** | caught |
| `line_of` kh bound compares against `KW` | **125, 0 failures** | 171, 2 failures |
| `line_of` kw bound compares against `KH` | **125, 0 failures** | caught |

The first is a real bug: on `{2,5,8,8}` a KH burst gives `[0, 32]` while
`line_of{1,0,0,0}` gives 80. They disagree by 48. Non-square kernels are
ordinary (1x3, 3x1, 7x1 factorized convolutions), so this would have bitten.

## F13, and a floor I set from structure rather than by tuning

The generator drew `stride` uniformly from `[1,9]` **before** knowing the
room, so 8 of 9 bursts took the strided path, and then derived the count from
what was left, which collapsed 76% of bursts to a single element. The
contiguous path, which per plan 1.1 is the **only** path production traffic
takes, was getting 2,778 non-trivial cases out of 64,000.

```
before:  64000 bursts, contiguous multi-line  2778   (4.3%)
after :  80000 bursts, contiguous multi-line 22843   (28.6%)
```

Three coverage floors are asserted now. They are uneven on purpose: of the 20
shape-by-axis combinations, **5 have a kernel extent of 1 or 2 and can never
emit a multi-line strided burst**, and 4 more at extent 3 manage it only at
stride 2. So ~10,000 is near the structural maximum for the strided path, not
a target to tune upward. I checked that before setting the number, because
the alternative is a floor chosen to make the run pass.

## F14, which is about this pipeline rather than the simulator

```
$ printf '#error THIS FILE IS BROKEN\n' >> tests/check.h
$ make test
125 checks, 0 failures     (exit 0)
```

The test binary did not depend on its own headers. A mutation applied to a
`tests/` header would have reported a clean pass against the previous binary.
The published mutation tables are unaffected, since every mutation in them
was to `layout.cpp` or a header under `include/`, both of which do trigger a
rebuild. Fixed and verified: `make test` now fails.

## What the reviewer checked and found clean

Worth stating, because a review that only lists problems is hard to
calibrate. It rebuilt the layout in Python from `layout.h`'s prose alone and
reproduced all 27 hand-computed values in groups A, B, D, E, F and I, so
those are genuine derivations rather than transcriptions of the
implementation. It found no defect in `expand`'s exception safety, no meaning
change in any of the ten removed casts, no reachable signed overflow, and
confirmed the two generator biases I had specifically asked about were both
unfounded.

## STALL 2 verification

```
171 checks, 0 failures    fixture build
171 checks, 0 failures    release build
0 warnings                both modes, full six-flag set
unit 3 exercise           fixture and release byte-identical, 221,184 accesses
```

One mutant is deliberately left alive: enforcing the lower bound only on
COUT still passes, and that is correct. `start_coord` is just the anchor's
coordinate, and `line_of` now validates all four, so it is an equivalent
mutant. `layout.cpp` records that so nobody chases it.

---

# Unit 3

**Status:** implementer stopped. Two new files, nothing else touched, and the
stall did not change either of them.

**Files**

| File | Lines | Contents |
|---|---|---|
| `include/wcache/cache.h` | 202, new | `SlotId`, `kNoSlot`, `kNoLine`, `Candidate`, `InsertResult`, `CacheArray`, `SetAssociativeArray` |
| `src/cache.cpp` | 190, new | `as_size`, constructor, `set_of`, `probe`, `free_slot`, `victim_candidates`, `insert` |

No test was written. Test design goes to you separately.

**Verification, my own, not the implementer's**

```
0 warnings          clean rebuild, both modes, full six-flag set
125 checks, 0 fail  units 1 and 2 undisturbed
fixture vs release  byte-identical output on a 221,184-access exercise
git status          only the two new files, nothing tracked modified
```

---

## The one-sentence version

`SetAssociativeArray` answers "which storage locations may hold this line,
what is in them now, and put this line here". It contains **no replacement
policy at all**, and the interesting content of the unit is the seam that
makes that possible.

---

# Part 1. The types

## `using SlotId = std::int64_t` (`cache.h:42`)

A storage location. This is the type that carries the whole geometry/policy
split, so it is worth being precise about what it has to do.

`ReplacementPolicy` is a separate module (plan 3.3) with `on_hit`, `on_fill`
and `pick_victim(candidates)`. An LRU has to remember something per location
and later say "evict that one". It must do both **without knowing what a set
or a way is**, otherwise the geometry has leaked back in and the split bought
nothing.

`SlotId` gives it exactly that, through two properties:

| Property | What it enables |
|---|---|
| **Dense** in `[0, num_slots)` | A policy sizes a flat `vector` from `num_slots()` and indexes it directly. No map, no set arithmetic. |
| **Stable** while the line is resident | A timestamp written on fill still describes the same physical location on the next access to it. |

`SetAssociativeArray` numbers slots `set_index * associativity + way`, and
`cache.h:34-37` states that nothing outside the file may rely on that.
`FullyAssociativeArray` will number differently and the same policies must
work unchanged.

**I verified this claim rather than accepting it.** I wrote a complete LRU
that touches only `SlotId`, `LineId` and `Candidate`, with no reference to
the array, no mapper, no associativity, no set index:

```cpp
class Lru {
    void on_hit(SlotId s)          { stamp_[s] = ++clock_; }
    void on_fill(SlotId s, LineId) { stamp_[s] = ++clock_; }
    SlotId pick_victim(const std::vector<Candidate>& c) const {
        // pick the smallest stamp
    }
    std::vector<std::int64_t> stamp_;   // sized from num_slots()
};
```

It compiles and behaves. The seam holds.

## `kNoSlot = -1` and `kNoLine = -1` (`cache.h:49, 54`)

Two sentinels, both `-1`, and both are only safe because the tree is one
signedness.

`kNoLine` is the sharper of the two. A slot holding nothing stores `-1`, and
a real `LineId` is a dense index into `[0, num_lines)` and therefore never
negative. So an empty slot **cannot** match any probe, and the probe loop
needs no validity test at all:

```cpp
if (slots_[base + way] == line) return base + way;   // no `&& valid[way]`
```

Under the old unsigned `LineId` this would not have worked: `-1` would have
been `18446744073709551615`, a value a line id could in principle take.
The alternative, a parallel `std::vector<bool>` of valid bits, costs a second
array and a second load per way.

`kNoSlot` being `-1` rather than a large value is the same reasoning as
everywhere else in the tree: a caller who forgets to check indexes out of
bounds loudly instead of at a real slot.

## `struct Candidate` (`cache.h:66-69`)

```cpp
struct Candidate {
    SlotId slot;
    LineId line;  // kNoLine if the slot is free
};
```

The question worth asking is why the line travels with the slot, when
`pick_victim` returns a slot and a policy like LRU never looks at the line.

The answer is `PinnedDecorator`, which plan 2.3 requires: a line with an
outstanding MSHR must not be evicted, and the MSHR pool is keyed by
**`LineId`**. With a bare `SlotId` that decorator would need a reference back
to the array plus a slot-to-line accessor, which puts an array reference into
the policy module. Pairing them here costs nothing, since the array is
already reading exactly those cells to enumerate the set.

## `struct InsertResult` (`cache.h:78-81`)

```cpp
struct InsertResult {
    bool   evicted;
    LineId evicted_line;  // kNoLine when evicted is false
};
```

Both fields are needed. `CacheLevel` counts evictions, and plan 2.3 fixes
inclusion as a design property, so an L2 eviction has to back-invalidate the
L1 copy, which means knowing **which** line left.

Returning only a `bool` would force the caller to read the slot before
inserting. That is the same read done twice, and a rule that is easy to
forget once and then undercount forever.

The two fields cannot disagree, because `evicted_line` is just the displaced
cell value and a free cell already holds `kNoLine`.

---

# Part 2. The interface, and why three verbs became four

Plan 3.3 lists `probe`, `insert`, `victim`. The implementer shipped five
methods, and argues the split is forced rather than chosen. I agree, and this
is the main thing I want your eye on.

```cpp
SlotId       probe(LineId) const;                      // kNoSlot on miss
SlotId       free_slot(LineId) const;                  // kNoSlot if the set is full
void         victim_candidates(LineId, std::vector<Candidate>& out) const;
InsertResult insert(LineId, SlotId);
std::int64_t num_slots() const;
```

**Why `victim` cannot survive as one verb.** Once replacement lives in
another module, this module cannot choose a victim. The only thing it can
offer is the candidate set. That much is unavoidable.

**Why the free case is separate.** A set with an empty way needs no policy at
all. It could have been folded into the candidate list, with free slots
appearing as `line == kNoLine`, and every policy carrying a "prefer an empty
way" rule. The implementer argues against it, and the argument is the right
shape: a policy that got that rule wrong would evict a live line while a way
sat empty. No crash, no wrong answer you can point at, just a hit rate
quietly below the truth across the whole sweep. That is this project's worst
failure mode, and it is the one the set-index bug already produced once.

So: `free_slot` for the case with no policy, `victim_candidates` for the case
with one. The cost is one extra virtual call per miss.

**The fill path a `CacheLevel` will write**, which is the real test of whether
the interface is usable:

```
s = probe(line)
    hit          -> policy.on_hit(s)
    miss         -> s = free_slot(line)
                    if s == kNoSlot:
                        victim_candidates(line, buf)
                        s = policy.pick_victim(buf)
                    r = insert(line, s)
                    policy.on_fill(s, line)
```

Nine lines. The array names no policy; the policy holds no geometry.

**`probe` is `const` and side-effect free**, which is a real payoff rather
than a stylistic note. Plan 2.9.4 drops a prefetch whose target is already
resident, and that test must **not** count as a use. Because recency lives in
the policy, there is one lookup and only a following `on_hit` makes it an
access. An array that owned recency would have needed a separate peek path,
and forgetting to use it would inflate every hit rate.

**One consequence needing your sign-off:** `pick_victim` returning `kNoSlot`
has to be legal, because `PinnedDecorator` can exclude every candidate when
every way of a set has an outstanding MSHR. `cache.h:44-48` documents that.
Handling it is `CacheLevel`'s job in a later unit, and it is exactly the
`NoTargets`-style block condition from plan Part 2, so it should fall out of
the MSHR work rather than needing new machinery.

---

# Part 3. The class

## `SetAssociativeArray` (`cache.h:158-200`)

**It is also the direct-mapped implementation.** YAML `cache_type:
direct_mapped` is this class at `associativity: 1`: every set has one way,
`free_slot` answers the cold case, and the candidate list has a single entry
every policy must return. Verified: `SetAssociativeArray(m, 32768, 1)` gives
2,048 sets and 2,048 slots. A separate class would be this code with the
loops unrolled once.

**It holds the mapper by reference**, not `num_sets` and `associativity` as
plain numbers. Two reasons, both good:

1. It needs the mapper regardless. `locate(line, num_sets)` is the only thing
   that turns a `LineId` into a set, and it is virtual precisely so a future
   hashed layout can state its own rule. Copying the current rule into this
   class is the sum-of-coordinates regression waiting to happen a second
   time, in a second place.
2. Given the mapper, `num_sets` is derivable here, so deriving it once inside
   the array is one place that can be wrong instead of one per construction
   site.

The cost: a reference member, so the class is not assignable, and the mapper
must outlive the array. The second is already true, since one mapper serves
the whole hierarchy. The first is worth watching, because plan 3.3 makes the
hierarchy a `vector<CacheLevel>`; if `CacheLevel` holds its array through a
`unique_ptr<CacheArray>`, which it must anyway to choose between
implementations, this never bites. Flagged, not a problem yet.

**Storage is one `LineId` per slot, not `SetIndex::tag`** (`cache.h:199`).
Within one set the set index is constant, so comparing line ids is exactly
comparing tags and is equally free of aliasing, which group I of the test
suite pins by checking the `(set, tag)` bijection over all 147,456 lines. It
also lets `insert` report the evicted line without reconstructing
`tag * num_sets + set_index`, and costs nothing since a tag is an `int64`
here too.

**Consequence worth recording:** `SetIndex::tag` now has no consumer anywhere
in the tree. It is not dead, since a future `FullyAssociativeArray` or a
tag-store model would want it, but it is unused today. The implementer
flagged this rather than proposing a change to `layout.h`, which was correct.

---

# Part 4. The functions, line by line with examples

Every example uses the plan's real geometry: layer `{3,3,512,512}`, blocks
4x4, so `line_size_bytes = 16` and `num_lines = 147,456`.

## `as_size` (`cache.cpp:21-24`)

```cpp
std::size_t as_size(std::int64_t v) {
    assert(v >= 0);
    return static_cast<std::size_t>(v);
}
```

`std::vector` subscripts with an unsigned `size_type`, so the signed slot ids
this class computes have to convert somewhere. Every such conversion in the
file goes through this one function.

**Why that matters and is not just tidiness.** There are five subscript
expressions. Spreading the conversion across them would answer
`-Wsign-conversion` with five casts rather than one reviewable site, and a
negative slot would silently become a huge in-range-looking index at each of
them. This is the same discipline that made the `LineId` signedness change
worth doing.

## The constructor (`cache.cpp:28-93`)

### `:38-47` the three positivity checks

`throw`, not `assert`, for all of them. `cache_size_bytes` and
`associativity` are YAML fields, and `line_size_bytes` comes from the layout
block of the same file, so all three are config-sourced and must fail in the
`-DNDEBUG` sweep build. This is the house rule from D1.

The reason it is not pedantic here: plan 3.5's sweep takes a **cross product**
of `l2.cache_size_bytes` and `l2.associativity`. A combination nobody typed
by hand reaching this constructor is the expected case, not the exotic one.

### `:54-58` the capacity must be a whole number of lines

```cpp
    if (cache_size_bytes % line_bytes != 0) { throw ... }
    const std::int64_t total_lines = cache_size_bytes / line_bytes;
```

Refused rather than floored. **This is the decision I most want you to look
at**, because rounding is the conventional choice.

The argument for refusing: plan 6.1 echoes `l1_size_bytes` and
`l2_size_bytes` verbatim into every results row. A silently floored geometry
would make the entire sweep attribute its hit rates to a capacity the
simulator never had, and nothing in the output would show it. Rounding up has
the same defect in the other direction.

**Example.** `cache_size_bytes: 100000` at 16-byte lines is 6,250 lines. At
`associativity: 4` that is 1,562.5 sets. Floored, you get 1,562 sets holding
6,248 lines, and the CSV says 100,000 bytes. The error is 0.03%, far too
small to notice and far too large to be honest about.

Verified: it throws with `cache_size_bytes 100 is not a whole number of
16-byte lines`, and the message carries both numbers.

### `:67-71` associativity larger than the whole cache

Checked **before** the even-division test, for two reasons. It gives the
message that says what is actually wrong rather than a confusing
divides-evenly complaint, and it is what bounds `line_bytes * associativity`
so that product cannot overflow later.

Verified: 64 bytes at associativity 32 throws `associativity 32 exceeds the
whole cache of 4 lines`.

### `:77-81` lines must divide evenly into sets

The likelier of the two exactness failures, because the sweep grid crosses a
power-of-two size with an associativity list. Verified: `associativity: 3`
against 32,768 bytes throws `2048 lines do not divide evenly into sets of 3`.

The two real configurations divide exactly:

| Level | bytes | assoc | lines | sets | slots |
|---|---|---|---|---|---|
| L1 | 32,768 | 4 | 2,048 | **512** | 2,048 |
| L2 | 524,288 | 32 | 32,768 | **1,024** | 32,768 |

Those 512 and 1,024 are the numbers every example in the last two reviews
used by hand. They are now derived, and I confirmed both.

### `:83-92` the derived state

```cpp
    num_sets_  = total_lines / associativity;
    num_slots_ = total_lines;
    assert(num_sets_ >= 1 && num_slots_ == num_sets_ * associativity_);
    slots_.assign(as_size(num_slots_), kNoLine);
```

`num_sets_ >= 1` needs no throw of its own: it follows from
`total_lines >= associativity >= 1` with an exact division. The assert states
that rather than leaving the reader to re-derive it. The smallest legal cache
is one line in one way, and I confirmed `SetAssociativeArray(m, 16, 1)` gives
1 set and 1 slot.

Every slot starts at `kNoLine`, which is the cold start the trace begins from.

## `set_of` (`cache.cpp:95-111`)

```cpp
    const std::int64_t set_index = mapper_.locate(line, num_sets_).set_index;
    assert(set_index >= 0 && set_index < num_sets_);
    return set_index;
```

The `tag` half of the returned `SetIndex` is discarded, per Part 3.

**Why the assert is here and not left to `BlockPackMapper`.** It is the
`AddressMapper` contract this class depends on, and a future mapper is free
to implement `locate` without asserting anything. And it matters concretely
because of the signedness change: signed `%` follows the sign of its
dividend, so a negative `line` yields a **negative** set index, and one line
later a subscript before the start of `slots_`. `assert`, not `throw`,
because a `LineId` arriving here came from `expand`, which already threw on
anything the trace got wrong.

## `probe` (`cache.cpp:113-127`)

```cpp
    const SlotId base = set_of(line) * associativity_;
    for (std::int64_t way = 0; way < associativity_; ++way) {
        if (slots_[as_size(base + way)] == line) return base + way;
    }
    return kNoSlot;
```

A linear scan, which is what set-associative hardware does in parallel.
Associativity is 4 at L1 and 32 at L2, so the scan is short and the slots are
contiguous. Anything cleverer, a per-set hash map say, costs more per access
than it saves at these widths.

**Example, L1 with 512 sets.** Line 65,536 gives `65536 % 512 = 0`, so
`base = 0 * 4 = 0`, and the probe reads slots 0, 1, 2, 3. Line 65,537 gives
set 1, `base = 4`, and reads slots 4 through 7. Adjacent lines, adjacent
sets, no interference, which is the property the dense flatten buys.

## `free_slot` (`cache.cpp:129-141`)

Same loop, matching `kNoLine` instead, returning the **lowest** free way.

Lowest rather than arbitrary so that cold-start placement is a property of
the trace alone. Two runs of the same sweep point then fill identically even
under `Random`, which only ever sees full sets. That is what makes a
`Random` policy reproducible at all.

## `victim_candidates` (`cache.cpp:143-159`)

```cpp
    out.clear();
    out.reserve(as_size(associativity_));
    for (std::int64_t way = 0; way < associativity_; ++way) {
        out.push_back(Candidate{base + way, slots_[as_size(base + way)]});
    }
```

**It replaces `out`, where `expand` appends.** The divergence is deliberate
and the reasoning is sound: `expand` appends because its documented use
accumulates a whole tick across cores into one buffer, while a candidate list
is one set's worth consumed immediately by one `pick_victim`. Appending would
let a caller who forgets to clear pick a victim from a previous fill, in a
**different set**, and the line would then be stored where `probe` can never
find it.

**And the `reserve` here is safe in a way F1's was not.** F1's sized a buffer
to the exact running total of an accumulation, leaving zero slack, so every
later append reallocated the whole vector: 1,024 reallocations in 1,024
appends. This one is bounded by associativity and cleared each call, so
capacity converges after the first call and it never allocates again. The
implementer caught the distinction unprompted, which is the right instinct
given F1's history.

Ways go out in index order so a policy breaking a tie by position gives the
same answer on a re-run.

## `insert` (`cache.cpp:161-188`)

Three asserts, then three lines of work.

```cpp
    assert(slot >= 0 && slot < num_slots_);
    assert(slot / associativity_ == set_of(line));
    assert(probe(line) == kNoSlot);
```

All asserts, per the house split: `slot` came from `free_slot` or from a
policy choosing among this array's own candidates, so a bad value could only
originate inside the simulator.

Each guards a **silent** failure, which is why they are worth writing:

| Assert | What it catches |
|---|---|
| slot in range | the obvious one |
| slot belongs to the line's set | stores the line where `probe` can never look. No crash, just a hit rate quietly below the truth |
| line not already resident | two copies in one set, after which `probe`'s answer depends on way order and the second copy's eviction is counted against a line that is still there |

The middle assert recomputes `set_of` inside the assert rather than reusing a
local, so the whole call, including a virtual `locate`, disappears under
`-DNDEBUG`.

```cpp
    LineId& cell = slots_[as_size(slot)];
    result.evicted      = (cell != kNoLine);
    result.evicted_line = cell;
    cell = line;
```

The displaced value **is** the report, so the two `InsertResult` fields
cannot disagree.

---

# Part 5. What I checked myself

I wrote an independent exercise rather than trusting the implementer's. It
runs an external LRU through the seam over 221,184 accesses. Fixture and
release output are byte-identical.

| Check | Result |
|---|---|
| L1 / L2 / direct-mapped geometry | 512, 1024, 2048 sets, matching the plan by hand |
| fill the whole L1 with distinct lines | 2,048 resident, **0 evictions**, so capacity is real |
| walk all 147,456 lines | **2,048 of 2,048 slots** used, no slot unreachable |
| LRU through the seam, 5 lines colliding in one 4-way set | evicts the true LRU, keeps the re-touched line |
| all 7 bad configurations | throw, with their numbers in the message, under `-DNDEBUG` too |
| residency independent of insertion order | yes |

**The check I would point at.** Three passes over a 3x3x64 `cin` sweep, each
a full 512-wide `cout` burst, through L1 then L2:

```
L1  hits=165888  misses=55296  hit rate 75.0%  evictions=53248
L2  hits= 36864  misses=18432  hit rate 66.7%  evictions=0
```

Every one of those numbers is predictable in advance, which is why it is
worth quoting:

- `cin_block` is 4, so `cin` 0, 1, 2, 3 map to the **same** block and produce
  identical line sets. Three of every four accesses must hit. **75.0%,
  exactly.**
- Distinct lines touched: `3 * 3 * 16 * 128 = 18,432`. That exceeds L1's
  2,048 slots, so no line survives to the next pass, and L1 misses must be
  `3 * 18,432 = 55,296`. **They are.**
- L2 sees exactly those 55,296 accesses over a working set of 18,432 lines,
  which **fits** in its 32,768 slots. So passes 2 and 3 hit entirely:
  `2 * 18,432 = 36,864` hits, `2/3 = 66.7%`, and **zero evictions**. All
  three match.

That is the array, the mapper, the LRU and the seam all agreeing with
arithmetic done independently.

---

# Open decisions

1. **The four-verb split.** `victim` became `free_slot` plus
   `victim_candidates`. I endorse it; the alternative makes every policy
   re-implement "prefer an empty way" and fail silently when it gets it
   wrong. Say the word if you want the plan's literal three verbs instead.
2. **Refusing a non-dividing cache size rather than rounding.** Rounding is
   the conventional choice. The argument for refusing is that plan 6.1 echoes
   the configured byte size into every results row, so rounding makes the CSV
   lie by a margin too small to notice. Yours.
3. **`Tick` is still `std::uint64_t`** (`types.h:22`), which the implementer
   raised and I think is right to raise. The engine will subtract ticks:
   stall time, `max(tick_base + tick, core_ready_time)`. An unsigned
   subtraction that goes negative wraps to a huge plausible value, which is
   the exact failure `LineId` was changed to avoid. Cheap now, expensive once
   the engine exists. **I recommend making `Tick` signed as well**, and
   `CoreId` if it ever meets a signed count.
4. **`locate` re-validates `num_sets > 0` on every call**, in the release
   build, and this array calls it up to three times per miss. The check is
   correct by the house rule, since `num_sets` is config-sourced, but the
   natural place for it is once at construction. Not urgent: the whole
   221,184-access exercise runs in 0.01 s. Worth revisiting only if it shows
   in a profile.
5. **No `invalidate` verb.** Plan 2.3 fixes inclusion, so an L2 eviction must
   back-invalidate the L1 copy, which probably means `CacheArray` grows an
   `invalidate`. The implementer deliberately did not add it, since nothing
   in this unit needs it and speculative interface surface is its own cost. I
   agree, and I want it on the record so it is a decision in the `CacheLevel`
   unit rather than a surprise.
6. **C2 is still open** and is not closed by this unit. The per-tick
   `reserve` obligation belongs to the engine's accumulate loop.
