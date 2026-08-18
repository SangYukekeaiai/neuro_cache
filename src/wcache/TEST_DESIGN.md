# Unit test design: unit 1, `BlockPackMapper`

> **Implemented and passing as of 2026-08-06.** All four questions at the
> bottom are answered in `FINDINGS.md`. Live code is
> `native/tests/test_layout.cpp` and `native/tests/check.h`; run it with
> `make -C src/wcache/native test`. Result: 125 checks, 0 failures in both
> build modes, 64,000 bursts against the oracle in 0.66 s.
>
> Two things below are now out of date and are left in place so the reasoning
> is auditable. Both are corrected inline where they appear:
>
> - Section 2's claim that gtest is not installed. It is.
> - Section 4 group G's rejection-sampling scheme, replaced by deriving the
>   count from the room left on the axis.
>
> The design also grew a group I for unit 2's `locate`, which section 5
> deferred.

Covers plan Part 5 structural item 1, "burst expansion under
`BlockPackMapper` for several `(cin_block, cout_block)` values".

---

## 1. Where the tests live, and why not in `debug/`

Plan Part 5 says fixtures continue the `debug/NN_verify_*.py` numbering from
17. Plan Part 3.4 says C++ fixture tests live in `native/tests/`, one file
per interface. Both are in the plan, so this needs a decision.

**Proposal: this unit's tests are C++, at
`src/wcache/native/tests/test_layout.cpp`.**

Reason: `expand` is a pure C++ function with no file I/O. Testing it from
Python would mean building a binding first, which the plan explicitly
rejected in favour of a process boundary (3.2), or shelling out to a
throwaway tool. Either adds a layer that can itself be wrong.

`debug/18_verify_*.py` still gets written, but later and for a different
job: cross-checking the native result against real trace files once
`TraceReader` exists. That script needs a reader, so it cannot be written
now. Flagged so it does not get forgotten.

## 2. Test harness

> **Correction.** "Neither gtest nor Catch2 is installed" is wrong: gtest
> 1.11 is present in the conda base environment, at
> `/u/yyu9/miniconda3/include/gtest` and `lib/libgtest.so.1.11.0`. The
> conclusion held on rechecking, but for a different reason: gtest ships
> there only as a shared object, so linking it would give the test binary a
> conda path dependency for macros `check.h` provides in thirty lines. Its
> one real advantage was death tests for the assert-only preconditions, and
> making `expand`'s range check a `throw` (D1) closed most of that gap.

No framework. Neither gtest nor Catch2 is installed, and adding a dependency
for one file is not worth it. Proposal is a 30-line header,
`native/tests/check.h`, giving:

```cpp
CHECK_EQ(actual, expected)        // prints both values and the line on failure
CHECK_LINES(mapper, burst, {...}) // expands and compares the whole vector
CHECK_THROWS(expr)                // expects std::invalid_argument
```

Every failure prints file, line, expected and actual, then the run continues
so one invocation reports every failure rather than the first. Exit code is
the failure count.

Build: a `test` target in `native/Makefile`, compiled **without** `-DNDEBUG`
so the `assert` preconditions are live.

```
make -C src/wcache/native test && ./src/wcache/native/build/test_layout
```

## 3. The oracle, which is the core of the design

Groups A through F below are hand-computed expected values, which is the
repo convention. But hand-computed values only test the cases someone
thought of.

So group G adds an independent **brute-force oracle**:

```
expected(burst) = sorted(unique( line_of(e) for e in elements(burst) ))
```

where `elements(burst)` enumerates the run one element at a time from
`anchor`, `axis`, `count`, `stride`. This is deliberately the slow, obvious
definition of what `expand` means, computed a completely different way from
the block-range arithmetic under test. `expand` short-circuits the whole
contiguous range in the unit-stride path; the oracle never does.

`line_of` is shared between the two, so the oracle does not validate
`line_of` itself. Group D tests `line_of` standing alone, and group B tests
it against `line_stride` independently, which closes that gap.

---

## 4. Test groups

### Group A, constructor and derived quantities

| # | Case | Expected |
|---|---|---|
| A1 | `{3,3,512,512}`, blocks 4,4 | `n_cin_blocks = 128`, `n_cout_blocks = 128` |
| A2 | `CIN = 10`, `cin_block = 4` | `n_cin_blocks = 3`, ceiling not floor |
| A3 | `{3,3,512,512}`, blocks 4,4 | `num_lines = 3*3*128*128 = 147,456` |
| A4 | same | `num_lines * 16 bytes = 2,359,296` equals `3*3*512*512*1`, so no padding when dims divide |
| A5 | `CIN = 10, COUT = 10`, blocks 4,4 | `num_lines = 3*3*3*3 = 81`, padded above the true 900 elements, confirming open decision 5 |
| A6 | `KH = 0` and each other dim zero or negative | throws `std::invalid_argument` |
| A7 | `cin_block = 0`, `cout_block = 0`, and negatives | throws `std::invalid_argument` |
| A8 | `{64,64,4096,4096}`, blocks 1,1 | `num_lines = 6.87e10`, exceeds 32 bits, catches a missing widening cast |

A8 is the one that fails loudly if someone drops a `static_cast<LineId>` in
the constructor.

### Group B, `line_stride`

| # | Case | Expected |
|---|---|---|
| B1 | `{3,3,512,512}`, blocks 4,4 | `COUT = 1`, `CIN = 128`, `KW = 16,384`, `KH = 49,152` |
| B2 | blocks 1,1 on the same shape | `COUT = 1`, `CIN = 512`, `KW = 262,144`, `KH = 786,432` |
| B3 | cross-check against `line_of`, all four axes | `line_of(c stepped one block along a) - line_of(c) == line_stride(a)` |

B3 is what makes B1's table more than a transcription of the code. It
derives the stride from `line_of`, which is the other side of the same
arithmetic.

### Group C, `block_len`

| # | Case | Expected |
|---|---|---|
| C1 | blocks 4,4 | `KH = 1`, `KW = 1`, `CIN = 4`, `COUT = 4` |
| C2 | blocks 2,8 | `KH = 1`, `KW = 1`, `CIN = 2`, `COUT = 8` |

The `KH = KW = 1` result is the substantive one: this layout never packs
across the kernel axes. That is open decision 4.

### Group D, `line_of`

| # | Case | Expected |
|---|---|---|
| D1 | `{0,0,0,0}` | `0` |
| D2 | `{2,2,511,511}` on the real shape | `147,455`, which is `num_lines - 1` |
| D3 | all 16 elements of one tile, `cin` 0..3 by `cout` 0..3 | all map to the same line |
| D4 | `{1,1,0,0}` | `65,536`, matching REVIEW.md case A |
| D5 | small shape `{2,2,8,8}` blocks 2,2, enumerate all 256 elements | the set of line ids is exactly `[0, 64)`, so `line_of` is onto and no line is unreachable |

D5 is the set-index reachability idea from plan Part 5 item 2, applied at
the line level. The set-level version belongs to the next unit, `locate`.

### Group E, `expand` at unit stride

Real shape `{3,3,512,512}`. E1 through E3 are the cases already worked in
REVIEW.md Part 4, so they double as a regression on that document.

| # | Burst | Blocks | Expected |
|---|---|---|---|
| E1 | `{1,1,0,0}` COUT count 4 | 4,4 | `[65536]`, one line, the whole corpus's case |
| E2 | `{1,1,0,2}` COUT count 4 | 4,4 | `[65536, 65537]`, straddles a tile |
| E3 | `{1,1,0,0}` COUT count 16 | 4,4 | `[65536..65539]` |
| E4 | `{1,1,0,0}` COUT count 4 | 4,**1** | 4 lines, the narrowing case of plan 2.5 |
| E5 | `{1,1,0,0}` COUT count 4 | 4,**8** | 1 line |
| E6 | `{1,1,0,3}` COUT count 4 | 4,4 | 2 lines, boundary at the very last element of a tile |
| E7 | `{1,1,0,0}` COUT count 1 | 4,4 | 1 line |
| E8 | `{1,1,0,0}` COUT count 512 | 4,4 | 128 lines, the whole `cout` row |
| E9 | `{1,1,6,0}` **CIN** count 4 | 4,4 | `[65664, 65792]`, spacing 128, REVIEW.md case E |
| E10 | `{0,0,0,0}` **KH** count 3 | 4,4 | 3 lines spaced 49,152, since `block_len(KH) = 1` |
| E11 | `{0,0,0,0}` **KW** count 3 | 4,4 | 3 lines spaced 16,384 |

E6 is the off-by-one trap: `cout` 3 to 7 must give 2 lines. If `last_coord`
were computed as `start + count*stride`, E1 would give 2 instead of 1, and
E6 would still give 2, so **E1 and E6 must both be present** for that bug to
be caught in either direction.

### Group F, `expand` at non-unit stride

| # | Burst | Expected | What it catches |
|---|---|---|---|
| F1 | COUT count 4 stride 8, blk 4 | `[65536, 65538, 65540, 65542]` | gaps: blocks 1,3,5 untouched |
| F2 | COUT count 4 stride 2, blk 4 | `[65536, 65537]` | dedup fires |
| F3 | COUT count 4 stride 4, blk 4 | 4 lines, no dedup | exact-block-size stride |
| F4 | COUT count 5 stride 3, blk 4 | elements 0,3,6,9,12 to blocks 0,0,1,2,3 so 4 lines | irregular dedup, not a clean pattern |
| F5 | CIN count 3 stride 5, blk 4 | elements 0,5,10 to blocks 0,1,2, spacing 128 | strided path on a non-COUT axis |

F5 matters because the strided path and the axis generality are two separate
mechanisms and F1 to F4 only exercise them one at a time.

### Group G, contract invariants against the brute-force oracle

For every burst in a generated set, assert all six:

| # | Invariant |
|---|---|
| G1 | output is strictly increasing |
| G2 | output has no duplicates (implied by G1, asserted separately so a failure names the right cause) |
| G3 | every emitted line is `< num_lines()` |
| G4 | output equals the oracle exactly, as a sequence |
| G5 | for every element the burst denotes, `line_of(element)` appears in the output |
| G6 | `expand` **appends**: pre-fill `out` with a sentinel, confirm the sentinel survives and the new lines follow it |

G6 is worth its own line because appending is open decision 1, and if that
decision is ever reversed this test is what fails.

**Burst set.** Deterministic, seeded `std::mt19937` with a fixed seed so a
failure reproduces exactly. Cross product of:

- shapes: `{3,3,512,512}` real, `{1,1,7,13}` odd primes, `{3,3,10,10}` non-dividing, `{2,2,8,8}` tiny
- `cin_block`: 1, 2, 4, 8
- `cout_block`: 1, 2, 4, 8, 16
- axis: all four
- 200 random `(anchor, count, stride)` per combination, with `count` in 1..32 and `stride` in 1..9, rejected and redrawn if the run leaves the tensor

> **Correction.** Rejection sampling was replaced by deriving the count from
> the room left on the axis: `count` is drawn from
> `1 .. min(32, (extent - 1 - anchor) / stride + 1)`. Rejection loses draws
> on axes of extent 1, such as `KH` and `KW` on the `{1,1,7,13}` shape, which
> would make the per-combination counts uneven and the total short of 64,000.
> The suite now asserts the total is exactly 64,000 so a future edit cannot
> quietly shrink it.

That is 4 shapes times 4 times 5 blocks times 4 axes times 200, so 64,000
bursts. Each is checked against the oracle. This is the test that actually
establishes correctness; A through F establish that the specific numbers in
REVIEW.md are right.

The odd shape `{1,1,7,13}` is deliberate: 7 and 13 are coprime with every
block size in the sweep, so every partial trailing block is exercised.

### Group H, edge and error cases

| # | Case | Expected |
|---|---|---|
| H1 | `count = 0` | appends nothing, `out` unchanged |
| H2 | `count = -1` | appends nothing |
| H3 | `stride = 0` | throws `std::invalid_argument` |
| H4 | `stride = -1` | throws `std::invalid_argument` |

> **Resolved by D1, option 2.** The `expand` extent check is now a `throw`,
> so H5 (runs past the extent), H6 (negative anchor) and the F2 overflow case
> are all tested. It costs one branch per **burst**, not per element, which
> is roughly a quarter of what the argument below assumes. The four `line_of`
> asserts stayed asserts, so option 1 applies to those.

**Not tested, and this is a real gap.** The range preconditions in `line_of`
(`layout.cpp:48-51`) and the extent check in `expand` (`:67`) are `assert`,
so violating them aborts the process. There is no portable way to test an
abort in-process. Options, and I would take the first:

1. Accept the gap. The asserts document intent and fire during development,
   and group G never generates an out-of-range burst.
2. Convert them to `throw`, making them testable at the cost of a branch per
   event on the hottest path. This is open decision 2 from REVIEW.md.
3. Fork a child process per case and assert on the abort signal. Testable,
   but heavy machinery for four cases.

---

## 5. What this design deliberately does not cover

| Not covered | Why | Where it lands |
|---|---|---|
| ~~`locate` to `{set_index, tag}`~~ | now written | **group I, done** |
| ~~set-index reachability~~ | now written | **group I, done**, plan Part 5 item 2 |
| real trace files | needs `TraceReader` | `debug/18_verify_*.py`, after M1 |
| `LinearMapper` | not written yet | later, same test file |
| performance | not a correctness question | the sweep itself |

## 6. Size and cost

Roughly 340 lines in `test_layout.cpp` plus 30 in `check.h`. The 64,000-burst
group G runs in well under a second, so it stays in the default `make test`
rather than behind a flag.

---

## Questions I need answered before writing this

1. **C++ tests in `native/tests/`, agreed?** Section 1 picks it over
   `debug/NN_verify_*.py`, but the plan names both and you own that call.
2. **The hand-rolled `check.h`, or would you rather I pull in a framework?**
   If gtest is available somewhere in your environment I would use it.
3. **The `assert` gap in section 4 group H.** Accept it, or convert the
   range checks to `throw` so they are testable?
4. **Is 64,000 random bursts the right size** for the default test run, or
   would you rather the randomized group be opt-in and the committed test be
   the hand-computed cases only?
