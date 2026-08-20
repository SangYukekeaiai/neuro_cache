> Recovered from commit 3f162a6 (wcache A2d: expand and locate on BlockPackMapper). This document explains increment A2d.
> Provenance header added during the 2026-08-18 documentation recovery; the body below is byte-for-byte as committed.
# EXPLAIN: increment A2d, `expand` and `locate`

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

Changed files, implementer: `native/include/wcache/layout.h`,
`native/include/wcache/block_pack.h`, `native/src/block_pack.cpp`.
Changed files, reviewer: `native/tests/test_block_pack.cpp`,
`native/tests/mapper_conformance.h`, `native/tests/compile_fail.sh`,
`native/tests/mutation_check.sh`.

This increment carries two functions rather than one, at your instruction to
forward the work rather than stop between them. They are the last two members of
`AddressMapper`, so **A2 is now complete** and the critical path moves to A4.

Plan reference: v3 Part 2.1 (address-generator row), Part 7 unit A2 and its exit
criterion ("out-of-range coordinate throws before any output is produced;
`line == tag x num_sets + set_index` holds"), N11, V15, and board decisions B27,
B28, B30, B31, B32, B38.

```
$ make clean && make test
130 compile cases, 0 failures
10283 checks, 0 failures       (test_block_pack)
 9452 checks, 0 failures       (test_layout)
  263 checks, 0 failures       (test_types)
exit 0
```

Warning-clean under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion
-Wshadow`, with no cast added to silence anything. `test_block_pack` went from
413 checks to 10283 because the conformance suite now runs over seven real
mappers and an oracle sweeps 32,000 bursts; `test_layout` grew by 182 because
the new malformed-burst contract runs over every fake that was already there.

---

## 1. What landed

Two member functions, no new state, no new members.

```cpp
void      BlockPackMapper::expand(const Burst& b, std::vector<LineId>& out) const;
Placement BlockPackMapper::locate(LineId line, std::int64_t num_sets) const;
```

They were `std::logic_error` stubs naming this increment (B19). Both are now
built entirely out of the three A2c pieces (`line_of`, `line_stride`,
`block_len`; see section 8 for the one of those three that turned out not to be
needed) plus the constructor's `num_lines_`.

`layout.h` was edited once, for five things at once, which is the whole of what
it owed A2d:

1. a new **"what an implementation throws"** block naming the three tiers
   (B27/B28), so the exception vocabulary is part of the interface instead of a
   comment in `tests/check.h`;
2. `locate`'s precondition, `0 <= line < num_lines()`, throwing
   `std::out_of_range` **before** the division (B30);
3. "strictly increasing" restated as an obligation on the *implementation*
   rather than a property a layout may or may not have (B31);
4. `count < 1` throwing `std::invalid_argument` (B38);
5. the two stale citations (B32): `Plan v2 Part 2.1` became `Plan v3 Part 2.1`,
   and `(measured merge ratio 1.13 at 1024 cores)` became `and the merge ratio
   is measured above 1`, which keeps the point and drops the figure that no
   longer has a run behind it.

Three stale statements in `block_pack.*` went with it: the `open question U1`
citations in both the header and the `.cpp` (U1 is closed by B27/B28), "All
three parameters" over a four-parameter signature, and a sentence claiming
`block_len` is what A2d's range check compares against. It does not, and
section 8 is why.

---

## 2. The running example

The same layer A2c's explanation used, so the numbers are already familiar and
can be checked against a board row (B22) written before any of the code:
`3x3x512x512` at `cin_block = cout_block = 16`, `weight_bytes = 2`.

```
n_cin_blocks  = ceil(512 / 16) = 32
n_cout_blocks = ceil(512 / 16) = 32
num_lines     = 3 * 3 * 32 * 32 = 9216
line_size_bytes = 16 * 16 * 2   = 512
```

| Axis | `line_stride` |
|---|---|
| KH | `3072` |
| KW | `1024` |
| CIN | `32` |
| COUT | `1` |

Two caches to place lines into, sized so the arithmetic is checkable:

```
L1  128 KB, 8-way, 512 B lines  ->  256 lines / 8 ways  =  32 sets
L2    1 MB, 16-way, 512 B lines -> 2048 lines / 16 ways = 128 sets
```

Note that the two levels differ only in the set count, which is why `num_sets`
is an argument to `locate` and not a field on the mapper. One mapper serves the
whole hierarchy.

---

## 3. Worked example one: a whole COUT burst

This is the shape every trace in the 7.7 GB corpus actually emits, a run along
COUT with stride 1, so it is the case the model spends its time in.

```
b = { anchor = (kh 1, kw 2, cin 80, cout 0),  axis = COUT,  count = 512,  stride = 1 }
```

Step by step, in the order the code runs:

```
1.  count check:   512 >= 1                                        ok
2.  n     = extent_on(shape, COUT)                = 512
    start = coord_on(anchor, COUT)                =   0
    last  = start + (count - 1) * stride = 0 + 511 = 511
    far-end check: 0 <= 511 < 512                                  ok
3.  the walk, 512 elements, each flattened by line_of:
        cout =   0  ->  block 0  ->  5280
        cout =   1  ->  block 0  ->  5280
        ...
        cout =  15  ->  block 0  ->  5280
        cout =  16  ->  block 1  ->  5281
        ...
        cout = 511  ->  block 31 ->  5311
4.  sort:    already in order, so this is one comparison pass
5.  unique:  512 values collapse to 32, each id having appeared 16 times
6.  insert:  those 32 ids appended to the caller's buffer
```

The base id, by hand, so the 5280 above is not taken on trust:

```
line = 1 * 3072 + 2 * 1024 + (80 / 16) * 32 + (0 / 16) * 1
     = 3072 + 2048 + 5 * 32 + 0
     = 5280
```

So `expand` appends `5280, 5281, ..., 5311`: 32 contiguous ids, strictly
increasing, from 512 elements. The collapse factor is exactly `cout_block`,
16 elements per line, which is the layout doing its job.

Now place the two ends of that run.

```
locate(LineId{5280}, 32)  ->  Placement{ set_index = 0,  tag = 165 }
locate(LineId{5311}, 32)  ->  Placement{ set_index = 31, tag = 165 }
```

Check the identity the plan's exit criterion names, `line == tag * num_sets +
set_index`: `165 * 32 + 0 = 5280` and `165 * 32 + 31 = 5311`. Both hold.

The interesting part is the shape of the whole burst at the L1: the 32 lines
land in **32 different sets, one line each, all sharing tag 165**. That is B22's
alias-free claim, now visible as output rather than as an argument. At the L2,
the same 32 ids under 128 sets:

```
locate(LineId{5280}, 128) ->  Placement{ set_index = 32, tag = 41 }   (41 * 128 + 32 = 5280)
locate(LineId{5311}, 128) ->  Placement{ set_index = 63, tag = 41 }   (41 * 128 + 63 = 5311)
```

sets 32 to 63, again one line each. Same mapper, same ids, two answers, no state
carried between the calls.

### The same burst along CIN, which is correct and pathological

The format v2 header can say CIN, and `layout.h` promises to accept it. Under
this layout:

```
b = { anchor = (0, 0, 0, 0),  axis = CIN,  count = 512,  stride = 1 }
```

`line_stride(CIN)` is 32, so the 512 elements collapse to 32 lines at a stride
of 32: `0, 32, 64, ..., 992`. Strictly increasing, distinct, all inside
`num_lines`. Everything `expand` promises holds. But under the 32-set L1 every
one of those lines has `line % 32 == 0`, so **all 32 lines land in set 0**, and
at 8-way the burst evicts three quarters of itself while it is still being
fetched. The spread ratio is `1/32 = 0.031`, which is the number B24 already
records as the value D2 must report for this case.

This is worth seeing here because the instinct on meeting it in a result is to
suspect `expand`. The board (B22's obligation to A3 and A5) says the response is
to change the layout order, never to reject the trace, and the reason is
precisely that the mapper is behaving correctly.

### A burst along an axis the layout does not block

The A2a-to-A2d carried obligation, armed since 2026-08-17 because the corpus
never produces one:

```
b = { anchor = (0, 0, 0, 0),  axis = KH,  count = 3,  stride = 1 }
     ->  lines 0, 3072, 6144
```

Three elements, three lines, no de-duplication at all, because KH's block size
is 1. The bound `lines <= count` is hit exactly here, and the conformance suite
now checks it against the real mapper.

---

## 4. Worked example two: what each check catches

Four refusals, in the order the code can produce them.

**A burst asking for nothing** (B38, and the tier is the point):

```
expand({ (1,2,80,0), COUT, count = 0, stride = 1 })
  ->  std::invalid_argument
      "BlockPackMapper: burst count must be >= 1, got 0"
```

`invalid_argument` and not `out_of_range`: a request for no elements is
malformed whatever layer it is applied to, which is B27's dividing line. v1
treated it as a legal empty run; the cost of that reading is that every consumer
downstream inherits a request with no lines to special-case, and C1 would have to
invent a served time for it.

**A burst that starts legal and leaves the tensor:**

```
expand({ (0,0,0,511), COUT, count = 2, stride = 1 })
  ->  std::out_of_range
      "BlockPackMapper: COUT coordinate out of range [0, 512), got 512"
```

**A burst walking backwards past zero**, which is the lower half of the same
check and is separately observable, since the far end is -8 while the first
element the walk would reject is -4:

```
expand({ (0,0,0,4), COUT, count = 4, stride = -4 })
  ->  "BlockPackMapper: COUT coordinate out of range [0, 512), got -8"
```

**An anchor out of range on an axis the burst does not walk:**

```
expand({ (0,0,512,0), COUT, count = 1, stride = 1 })
  ->  "BlockPackMapper: CIN coordinate out of range [0, 512), got 512"
```

The far end here is a perfectly legal 0, so the far-end check passes and
`line_of` catches it on the first element. The two checks are complementary, not
redundant: one covers the walk, the other covers the three coordinates the walk
never touches.

In every one of the four, **`out` is exactly as it was**. Nothing is appended,
not even the ids of elements that were legal, which is what `layout.h` promises
the accumulate pattern (one buffer, one tick, several cores).

---

## 5. Worked example three: `locate`, and the check that runs before the divide

```
num_lines() = 9216

locate(LineId{0},    32)  ->  { set 0,  tag 0 }
locate(LineId{9215}, 32)  ->  { set 31, tag 287 }      287 * 32 + 31 = 9215
locate(LineId{9216}, 32)  ->  std::out_of_range
                              "BlockPackMapper: line id out of range [0, 9216), got 9216"
locate(LineId{-1},   32)  ->  std::out_of_range
                              "BlockPackMapper: line id out of range [0, 9216), got -1"
```

The negative case is the one worth dwelling on, because it is the reason the
check exists rather than a formality. `LineId` is signed by convention (B5).
C++ integer division truncates toward zero and the remainder takes the sign of
the **dividend**, so without the check:

```
-1 % 32  ==  -1        (not 31)
-1 / 32  ==   0
  ->  Placement{ set_index = -1, tag = 0 }
```

`set_index = -1` is then used to index a set array from below. The identity
even still holds (`0 * 32 + (-1) == -1`), so a test that only checked the
identity would pass. What the range check buys is that the postcondition
`0 <= set_index < num_sets`, which `layout.h` states and which every array
access in A4 will be written against, is a fact rather than an assumption.

`locate` is otherwise two operations, and deliberately so: it is called once per
line per probe, at both levels, for the whole run.

---

## 6. The three choices inside `expand`

### Sort and unique, unconditionally

B31 settled that "strictly increasing" is an obligation on the implementation
rather than a property of a layout, because `tests/mapper_conformance.h` is
parameterised over the abstract base and cannot check a guarantee that varies by
implementation. So `expand` ends with:

```cpp
std::sort(lines.begin(), lines.end());
lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
out.insert(out.end(), lines.begin(), lines.end());
```

There is an argument that this layout does not need the sort: a block index is
non-decreasing in its coordinate and every line stride is positive, so a
positive-stride walk is already increasing and `std::sort` does one comparison
pass over an already ordered range. I wrote it unconditionally anyway, and the
reason is not the cost. It is that the argument above is a proof about *this
layout under a positive stride*, and the code would silently stop being correct
if either half changed. A negative stride is the case that is live today: nothing
in `layout.h` forbids one, the walk then runs downhill, and the sort is the only
thing standing between that and a decreasing list. See the open questions.

The de-duplication is not incidental either. It is what makes `lines_per_burst`
a real number: 512 elements became 32 lines above, and the engine issues 32
probes rather than 512.

### The lines are built to the side and committed at the end

`layout.h` asks that every range check run **before the first append**. There are
two ways to get that: append into `out` and roll back on a throw, or build into a
local vector and copy in once at the end. I took the second.

The first is a `try`/`catch` with a `resize` back to the remembered size, and it
is one line of thought away from being wrong (restore the size, but the caller
may also have observed a reallocation; get the catch clause's rethrow wrong and
the exception type changes). The second cannot be wrong: if the walk throws,
`out` was never touched at all, because the only statement that touches it is the
last one. The cost is one allocation per call, which I am accepting and flagging
rather than hiding: if `expand` ever shows up in a profile, a caller-supplied
scratch buffer is the fix, and it is a change to this function alone.

### The far end is computed and checked in 64 bits

```cpp
const std::int64_t last = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
if (last < 0 || last >= n) { /* out_of_range naming the far end */ }
```

`count` and `stride` are both `int32` (B8) and their product is not, so the cast
has to sit on an operand, before the multiply, not on the result.

**What this check does and does not buy, corrected.** My first write-up of this
said the check is what stops a wrapped coordinate from being served. That is
wrong, and the reviewer's round found it. Every element of the walk goes through
`line_of`, which validates all four coordinates, and the walk is monotone, so a
burst running off the end throws with or without the far-end check. What the
check actually buys is **which coordinate the message names**:

```
b = { (0,0,0,0), COUT, count = 5, stride = 2^30 }
    elements: 0, 2^30, 2^31, 3*2^30, 2^32

with the far-end check:     "COUT coordinate out of range [0, 512), got 4294967296"
without it, from the walk:  "COUT coordinate out of range [0, 512), got 1073741824"
```

4294967296 is a number only 64-bit arithmetic can produce; 1073741824 is the
second element, which is where a one-at-a-time walk happens to stop. The first
message says the burst's own count and stride are wrong. The second says an
element is wrong, which is true but is not the fault. For a corpus bisect on a
trace header decoded at the wrong offset (the failure V15 exists for), that
difference is the whole diagnostic.

The reviewer found the boundary case that makes this testable rather than
asserted, and it is worth recording because it is subtle: `>= n` and `> n`
disagree on exactly one value and **both refuse it**, since the walk's last
element is then the coordinate `n`, which `line_of` rejects with the same axis
and the same value. The two spellings are indistinguishable on any ordinary
burst. What separates them is which check fires *first*, so the burst that
separates them has to be wrong twice on purpose:

```
b = { (0, 0, 512, 0), COUT, count = 3, stride = 256 }

far end = 0 + 2*256 = 512, exactly on the extent   ->  the check names COUT
anchor's cin = 512, one past the layer             ->  the walk names CIN
```

That was a surviving mutation until that case was written.

---

## 7. What the reviewer's round added

Recorded here because it changes what the suite can catch, not only its counts.

- The A2b stub tripwires are gone, replaced by an "A2d: expand and locate"
  section. They said so themselves in a comment: when A2d lands they fail, and
  they are to be replaced by a suite that says what the members must *do*, not
  deleted.
- `run_all` landed in `test_block_pack.cpp` rather than `test_layout.cpp`. The
  Makefile builds one binary per test file, and `run_all` takes a
  `const AddressMapper&`, so it goes where the mapper is.
- Conformance now runs BlockPackMapper in **seven** configurations: one element
  per line, 4x4, a whole CIN x COUT plane per line, a non-dividing 3x5, blocks
  wider than their extents, a 1x1 (pointwise) layer, and the corpus's own
  `{3,3,256,64}` at `64/128`, which is the one place the 7.7 GB corpus reaches
  the rounding path at all. Beside them, an oracle over 32,000 bursts compares
  `expand` against the slow definition: enumerate the elements, flatten each,
  sort, unique.
- The conformance `Env` gained a **third bucket** rather than a `push_back`, and
  this is the design point worth your attention. The obligation as written said
  "the Env has no zero-count burst and needs one on the illegal side". But the
  illegal side is checked by `c_throw_type_is_out_of_range`, and B38 says a
  zero-count burst throws `invalid_argument`. Pushing it onto `illegal` would
  have made the suite demand the wrong type. So `Env` now has `legal`,
  `illegal` (must throw `out_of_range`) and `malformed` (must throw
  `invalid_argument`), with a contract asserting the type is *not*
  `out_of_range`, which needs saying explicitly, since both derive from
  `logic_error` and a bare `catch` cannot tell them apart. Two new deliberately
  broken fakes prove the new check has teeth.
- 15 new compile-fail cases and 26 new mutations, all killed.

Operational note, worth knowing before you ask for a sweep: a filtered mutation
run now costs about 3.5 minutes of wall clock **per case**, because each case
re-runs all 130 compile-fail cases. The login node's 30-minute cap therefore
allows roughly eight cases per invocation. An unfiltered sweep is out of the
question and always was.

---

## 8. What A2d does not do

- **No `num_sets` validation in `locate`.** `v % num_sets` with `num_sets == 0`
  is undefined behaviour, and it is reachable: the unowned representability
  defect on the board has D1 computing a set count of 0 from a mapper reporting
  a 9.2-exabyte line. I left it alone because that defect is explicitly
  recorded as unowned and not this dispatch's, but the effect is that the number
  of candidate owners is now three, not two: A2b's constructor bound, D1's
  config-load bound, or `locate` itself.
- **No `stride` validation.** See the open questions.
- **`block_len` still has no caller inside the library.** B35 closed U8 partly on
  the grounds that it "gains a real library caller at A2d regardless". It does
  not, and the reason is B25: a burst carries *element* coordinates, so
  `expand`'s range check compares against the shape, exactly as `line_of` does.
  Checking against `block_len` would accept `cin = 100` on a `CIN = 100` layer at
  `cin_block = 32`, because `100 / 32 = 3` is a legal block index. So A2c's
  accepted cost, that `block_len` is only as good as its own direct tests, survives
  A2d rather than expiring at it. The header now says so.
- **No error-message context.** The message names axis, range and value. V15
  wants tile, tick and core too, and B37 assigns that catch-and-re-throw to
  whichever unit owns the per-tick accumulate buffer. `expand` being the engine's
  only entry point means there is exactly one wrap site.
- **No `EXPLAIN.md` claim about performance.** Nothing here has been profiled.

`CPP_NOTES.md` gained **section 22**: the `sort`/`unique`/`erase` shape and why
`Tagged` needs no comparator, the strong exception guarantee by building to the
side, `/` and `%` on a negative left operand, and where the cast goes when an
intermediate would overflow. One thing I did not do, since that file is
append-only: section 17's "what is coming later" table still lists `std::vector`
as first needed by A4, and A2d uses it. That row is the notes keeper's to update.

---

## 9. Open questions

**Q1. Is `stride < 1` legal?** This needs you, and it is the one with a real
trap in it.

`BlockPackMapper` accepts any stride: a negative one walks the axis backwards
and a zero one names the same element `count` times, and in both cases `expand`
returns the correct set of distinct lines because it sorts and uniques. Nothing
in `layout.h` says otherwise. But the reviewer's reference mapper,
`PackedRowMajor` in `test_layout.cpp`, **throws `invalid_argument` on
`stride < 1`**, so the two implementations of the same interface currently
disagree, and a future Env case would have to pick one.

The trap: ruling `stride < 1` illegal would make B31's sort **unreachable** on
this mapper, since a positive stride always walks uphill. The sort would then be
dead code that no test can distinguish from its absence, and you would be paying for
a guarantee you had just made untestable. My recommendation is to keep any stride
legal and to make `PackedRowMajor` match, but it is your call and it is cheap
either way today.

**Q2. When a burst is both malformed and out of range, which tier wins?**
Today `count < 1` is checked first, so a burst with `count = 0` *and* an anchor
outside the tensor reports `invalid_argument`. That is defensible (the malformed
argument is wrong at every layer, so it is the more fundamental complaint) but it
is not written down anywhere, and a caller catching one type and not the other
gets different behaviour depending on an ordering nobody chose deliberately.

**Q3. When two range failures fire at once, which is reported?** Section 6's
double-wrong burst is the case: the far end is out of range on COUT and the
anchor is out of range on CIN. The far-end check runs first, so COUT is named.
I think that is the right answer, since the burst's own count and stride are the
proximate fault, but the same question will be asked again by whoever writes
the V15 re-throw, and it is better decided once.

**Q4. The representability bound, still unowned.** Unchanged from the board, and
now with a third candidate owner (section 8). It is the only path I know of from
a legal-looking config to undefined behaviour in this file.

None of the four blocks A4. Q1 is the one I would like an answer to before the
reviewer writes any more stride cases.
