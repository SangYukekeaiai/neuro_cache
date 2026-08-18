# Findings and pipeline stalls

> Written by the manager only. The reviewer reports here; the implementer
> reads here when a fix is assigned. Append-only across units, so the defect
> history survives.

**Pipeline state: STALL 2 RESOLVED.** The reviewer found 8 defects in the
signedness / D1 / D2 / tests change set, 4 of them high. All 8 are fixed and
verified. See "STALL 2" at the bottom, which is the current section. Unit 3
(`SetAssociativeArray`) is implemented and waiting behind this stall.

## STALL 1 resolution, verified by the manager

Re-ran the same probes that confirmed the defects, against the fixed code:

```
warnings at -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow:  0
warnings at -O2 -DNDEBUG:                                                      0
F1  1024 appends -> reallocations = 11   (was 1024)
F5  sign-conversion warnings = 0          (was 6)
seven-case regression A-G: all exact, both build modes
unit 2 locate: set reachability still 100% at 512 / 1024 / 4096 sets
```

| Defect | Fix | Verified |
|---|---|---|
| F1 reserve defeats geometric growth | `reserve` deleted, comment explains why and moves the obligation to the caller | reallocations 1024 to 11 |
| F2 32-bit overflow defeats bound check | widened to `std::int64_t` before the multiply, compared in int64 | overflow case now trips the assert instead of passing |
| F3 ordering promise overstated | comment scoped to a single call, sort-and-unique obligation stated for plan 2.4 | reworded |
| F4 missing `<cstddef>` | not needed: F1 removed the only `std::size_t` use | grep confirms zero uses |
| F5 unsigned flatten | flatten done in `std::int64_t`, one cast at the return | 6 warnings to 0 |
| F6 fallback returns 0 | `line_stride`, `block_len`, `WeightShape::extent` now throw `std::logic_error` | compiles clean, unreachable on real input |
| F7 `coord_on` same defect | **found by the implementer, fixed by the manager**, same treatment as F6 | compiles clean |

F7 is the one the reviewer missed. The implementer found it while fixing F6,
correctly refused to widen its own scope, and reported it. It is the worst of
the four: `expand` reads the anchor's coordinate through `coord_on`, so a bad
`Axis` would have expanded the burst from coordinate 0 and emitted a
valid-looking line rather than failing.

Also delivered: `src/wcache/native/Makefile` per plan Part 3.4, with a
fixture build (asserts live) and a `release` build (`-O2 -DNDEBUG`) in
separate object directories, and the warning set pinned rather than
remembered. `compile_flags.txt` now carries the same flags so the IDE agrees.

---

## Carried forward from the fix, still open

**C1. F2 is correct but absent in the sweep build.** The widened bound check
lives inside an `assert`, so `-DNDEBUG` compiles it away and a malformed
trace still walks unchecked. This is D1 below, sharpened by the fix.

**C2. F1 transferred an obligation nothing enforces yet.** Removing the
reserve is right, but the per-tick accumulate loop of plan 2.4 must now hoist
its own `reserve` or pay about log2(N) reallocations per tick (11 measured
for 1024 lines). Unit 3 does not exist yet, so this needs to land in the
engine's spec when drafted.

**C3. `Makefile` uses `CXX ?= g++`, which defers to the environment.** In
this shell `CXX` resolves to `CC`. It built clean and gave identical results,
but on a Delta compute node `CC` is a Cray wrapper with different defaults
than the `g++` line all verification uses. Change `?=` to `:=` if the pinned
warning set should imply a pinned compiler. Left as-is, since overridability
is the usual convention and this is a policy call.

**C4. `types.h` now includes `<stdexcept>`**, and therefore `<string>`, in
every translation unit. Negligible at this size, but it is a real cost added
to the most widely included header, a consequence of putting F6's throw in an
inline function. Moving `extent` out of line into a `.cpp` is the alternative.

---

## How a stall works

1. The manager stalls the pipeline. The implementer does not continue to the
   next function.
2. Findings are written here: file, line, what is wrong, the concrete failure
   scenario, severity.
3. The bug is fixed **first**.
4. `REVIEW.md` is updated with the corrected explanation.
5. Only once the fix is confirmed does the pipeline resume.

---

## STALL 1, opened on unit 1 review

Reviewer verdict: **no correctness defect in the burst arithmetic.** All
seven worked cases A through G reproduce exactly, `num_lines = 147,456` and
the four line strides are correct, ceiling versus floor is right in each
place, half-open is right at both ends, and `line_of({2,2,511,511})` is
exactly `num_lines - 1` with no gap and no overflow.

Five defects sit around that correct core. I re-verified findings 1, 2 and 5
myself with an independent probe rather than accepting the report; output is
quoted under each.

### F1. `expand`'s `reserve` reallocates on every call, in exactly the pattern the interface exists for

**Severity: high (performance).** `src/wcache/native/src/layout.cpp:81`

```cpp
out.reserve(out.size() + static_cast<std::size_t>(last_blk - first_blk + 1));
```

`reserve(n)` sets capacity to exactly `n`, leaving zero slack, so it defeats
`push_back`'s geometric growth. Every subsequent `expand` into the same
buffer reallocates and copies the whole running vector.

Verified, 1024 cores appending into one shared buffer:

```
F1: 1024 appends -> size=1024 cap=1024 reallocations=1024
F1: same, pre-reserved       -> size=1024 cap=4096 reallocations=0
```

1024 reallocations out of 1024 calls. On the `inst1024` sample (1024 cores
times 7,158 ticks) that is roughly 7.3 M malloc/free pairs per file, plus the
quadratic memcpy. The whole stated reason `expand` appends rather than
returns (`layout.h:24-26`, and open decision 1) was to avoid exactly this.
The line reintroduces it.

**Fix:** drop the `reserve`. `push_back`'s amortized growth is correct here,
and the engine can hoist one `reserve` into its per-tick loop where it knows
the total.

### F2. 32-bit overflow at `expand:66` defeats the bound check on the next line

**Severity: high (correctness, latent).** `src/wcache/native/src/layout.cpp:66`

```cpp
const std::int32_t last_coord = coord_on(b.anchor, b.axis) + (b.count - 1) * b.stride;
assert(last_coord < shape_.extent(b.axis));
```

`count` and `stride` are both `int32_t`, so the product is a 32-bit multiply.
This is the **only** arithmetic expression in the three files that is not
widened before multiplying, and it is inconsistent with `:94`, which computes
the same quantity correctly in 64 bits.

Verified:

```
F2: true last_coord=3000000000, as computed in int32=-1294967296, extent=512
F2: bound check 'last_coord < 512' would PASS (defeated)
```

The check exists to catch a run that leaves the tensor, and it fails
precisely on the runs that leave it furthest. Signed overflow is also UB. The
strided loop at `:93-99` is correctly 64-bit, so it then walks to element
3,000,000,000 and emits line ids far past `num_lines()`.

**Fix:** `static_cast<std::int64_t>(b.count - 1) * b.stride`, compared in
`int64_t`.

### F3. The "strictly increasing" promise holds per call, but the documented use is cross-call

**Severity: medium (contract, will mislead the next module).**
`src/wcache/native/include/wcache/layout.h:24-26`

The promise is kept within one call on both paths. It cannot hold across
calls into a shared buffer, which is the accumulate pattern the same comment
recommends. With the real `inst1024` merge ratio of 1.13, duplicates occur
too.

This matters because `REVIEW.md` claimed the ordering promise lets callers
skip a sort and a dedup. For the per-tick distinct-line count that plan Part
2.4 needs, the caller **must** sort and dedup. If the L2 is built believing
otherwise, its distinct-per-tick statistics will be wrong.

**Fix:** say "within a single call" in the comment, and state that a caller
accumulating across cores must sort and unique before counting distinct
lines.

### F4. `std::size_t` used without including `<cstddef>`

**Severity: low.** `src/wcache/native/src/layout.cpp:81`

Arrives transitively through `<vector>`. Compiles on this toolchain, not
guaranteed. Moot if F1 removes the line, but the include belongs there
anyway.

### F5. `line_of` converts everything to unsigned, defeating the stated reason `Coord` is signed

**Severity: medium.** `src/wcache/native/src/layout.cpp:54-55`

Verified: 6 `-Wsign-conversion` warnings, all on these two lines.

`static_cast<LineId>(c.kh)` widens the whole expression to `uint64_t`, so
every later operand converts from signed to unsigned. `types.h:19` justifies
a signed `Coord` on the grounds that unsigned subtraction wraps to a huge
plausible value while signed stays visible. Line 54 converts to unsigned
anyway, at the one place the protection would apply.

Under `-DNDEBUG`, where the asserts are gone, `c.cout = -4` gives
`cout_blk = -1` and lands on `base - 1`: a perfectly valid-looking line.

**Fix:** do the flattening in `std::int64_t`, cast once at the return.

### F6. `line_stride`'s unreachable fallback returns 0, which would break the contract

**Severity: low (defensive).** `src/wcache/native/src/layout.cpp:44`

If that path ever became live, `step = 0` emits N copies of one line id,
silently breaking the strictly-increasing guarantee. The three sibling
switches use three different fallback conventions: `line_stride` returns 0,
`block_len` returns 1, `extent` returns 0.

**Fix:** make the unreachable paths fail loudly rather than return a value
that corrupts results.

---

## Open items raised by the review, needing your decision

### D1. The `assert` versus `throw` split, now sharper than before

Open decision 2 in the old `REVIEW.md` was left to you. The review gives it a
concrete edge, and F2 makes it urgent.

The extent check at `expand:67` guards **trace-sourced** data, which is
external input, but it is an `assert`, so it vanishes in the sweep build.
Fixing F2 makes that check correct, but only in the fixture build.

Reviewer's proposal, which I endorse: keep `assert` on the hot `line_of`
path, and make the single `expand` extent check a `throw`. It runs once per
burst rather than once per element, so it costs about a quarter of what the
blanket argument implies, and it is the one check standing between a
malformed trace and silently wrong line ids.

**Not changed yet. Your call.**

### D2. `line_size_bytes` is documented but not obtainable

`layout.h:42` states `line_size_bytes = cin_block * cout_block * weight_bytes`,
but `weight_bytes` is not a constructor argument and there is no accessor.
`CacheArray` (unit 3) needs it to turn `cache_size_bytes` into a set count,
so as it stands unit 3 must plumb `weight_bytes` separately and recompute the
product.

`weight_bytes` is a v2 trace header field, so the mapper is the natural
owner. **Not changed yet**, because it widens unit 1's scope.

### D3. No `native/Makefile`

Plan Part 3.4 lists one. Today the only build recipe is a hand-typed `g++`
line, and `compile_flags.txt` carries two flags without the warning set.
Worth standing up so the warning flags are pinned rather than remembered,
especially since `-Wsign-conversion` is not currently on and found F5.

---

## Unit status

| Unit | Function | Implemented | Human reviewed | Code reviewed | Tests |
|---|---|---|---|---|---|
| 1 | ctor, `block_len`, `line_stride`, `line_of`, `expand` | yes | accepted | 7 defects, **all fixed** | design pending |
| 2 | `locate` | yes | **awaiting** | not yet | not yet |
| 3 | `SetAssociativeArray` | not started | | | |

## Standing risk

Two units exist and neither has a test, because `TEST_DESIGN.md`'s four
questions are unanswered. Every defect above was found by reading, not by a
test. F1 and F2 are exactly the kind of thing group G's oracle would have
caught mechanically.

**Closed 2026-08-06.** The suite exists and the mutation table below shows it
catches F1-class and F2-class defects mechanically.

---

# Decisions closed 2026-08-06

Approved in one pass, implemented and verified together.

## The signedness class, which is F5's real cause

`LineId` changed from `std::uint64_t` to `std::int64_t`, and `SetIndex::tag`
followed. The F5 fix corrected one expression; the boundary that produced it
remained, with `n_cin_blocks()` returning `int64_t` while `num_lines()`
returned `uint64_t` and both feeding the same arithmetic. Removing the
boundary removes the class.

Ten explicit casts disappeared, across `line_of`, `locate`, `line_stride`,
both `expand` paths and the constructor. Each was a site where a reviewer had
to decide whether a conversion was lossless.

One consequence worth recording: signed `%` follows the sign of the dividend,
so a negative `line` would give a negative `set_index`. `locate`'s assert was
widened to `line >= 0 && line < num_lines_` accordingly. Under the old
unsigned type that half would have been dead code.

Accepted cost: a future hashed or XOR-folded set index wants unsigned shifts
and will need one cast at that one site.

## D1, `assert` becomes `throw` in `expand`

Resolved as proposed. The per-burst extent check throws `std::out_of_range`
and now also checks the lower bound; the per-element checks in `line_of` stay
asserts. This closes **C1**: the widened F2 bound check now runs in the sweep
build, not only the fixture build.

Three test cases exist that could not exist before, because an assert failure
aborts the process:

| Case | Before | Now |
|---|---|---|
| burst runs past the axis extent | fixture aborts, sweep does not check at all | `std::out_of_range` |
| negative anchor coordinate | fixture aborts, sweep emits `base - 1` | `std::out_of_range` |
| F2's overflow case, count 100001 stride 30000 | the 32-bit wrap made the check pass | `std::out_of_range` |

No measurable cost: release build runs the same 64,000 bursts in the same
0.66 s.

## D2, `weight_bytes` and `line_size_bytes()`

Resolved as proposed. `weight_bytes` is a required fourth constructor
argument, `line_size_bytes()` is pure virtual on `AddressMapper`, so
`CacheLevel` can compute `cache_size_bytes / (line_size_bytes *
associativity)` through the interface it already holds. Prevents unit 3 from
plumbing `weight_bytes` separately and recomputing the product.

## C3, the floating compiler

`CXX ?= g++` became `CXX := g++`. Pinning the warning set while leaving the
compiler to resolve to Delta's Cray `CC` pinned nothing.

## C4, `<stdexcept>` in `types.h`

Accepted as-is. Negligible at this size.

## Tests, all four `TEST_DESIGN.md` questions

| Q | Answer |
|---|---|
| 1. C++ in `native/tests/` | yes. `expand` is pure C++; testing it from Python needs a binding plan 3.2 rejected |
| 2. framework | hand-rolled `check.h`. **My stated premise was wrong**: gtest 1.11 *is* installed in conda base. Rechecked and still hand-rolled, because gtest is only a `.so` under `miniconda/lib` and would give the test binary a conda path dependency; its death-test advantage was mostly closed by D1 |
| 3. the assert gap | closed for the externally-sourced check by D1. The four `line_of` asserts remain asserts, accepted |
| 4. 64,000 bursts | kept in the default run. 0.66 s total |

## Verification

```
125 checks, 0 failures    fixture build (-O0 -g)
125 checks, 0 failures    release build (-O2 -DNDEBUG)
0 warnings                -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow
0 warnings                release build, same flags
64,000 bursts, 154,072 lines emitted, 0.66 s, 11 MB peak
```

Mutation testing, to show the suite is not vacuous. Each mutation was applied
to a copy of `layout.cpp` and the unmodified suite re-run:

| Mutation | Result |
|---|---|
| `(count-1)*stride` becomes `count*stride` | caught, throws on a legal burst |
| ceiling division becomes floor in `n_cout_blocks` | 6 failures |
| set index reverts to the sum-of-coordinates rule | **9 failures** |
| `line_stride(CIN)` drops a factor | 7 failures |
| `expand` assigns instead of appending | 5 failures |
| control, unmutated | 0 failures |

The third row is the one to note: the regression that motivated the whole
redesign is now caught mechanically rather than by reading.

## Unit status, current

| Unit | Function | Implemented | Human reviewed | Code reviewed | Tests |
|---|---|---|---|---|---|
| 1 | ctor, `block_len`, `line_stride`, `line_of`, `expand` | yes | accepted | 7 defects, all fixed | **groups A-H, passing** |
| 2 | `locate` | yes | accepted | with the reviewer | **group I, passing** |
| 3 | `SetAssociativeArray` | not started | | | |

## Still open

- **C2.** Removing F1's `reserve` moved a `reserve` obligation onto the
  per-tick accumulate loop of plan 2.4. Nothing enforces it. Must land in
  unit 3's spec.
- The four `assert`s in `line_of` are still untestable in-process. Group G
  never generates a burst that reaches them out of range.
  **Closed by STALL 2 fix F8**: they are throws now, and tested.

---

# STALL 2, opened on the review of the signedness / D1 / D2 / tests change set

Reviewer verdict: **the arithmetic core is correct.** Every finding is about
what the code does not check and what the suite does not see. The reviewer
also independently rebuilt the layout in Python from `layout.h`'s prose alone
and reproduced all 27 hand-computed values across groups A, B, D, E, F and I,
which confirms those are genuine derivations and not transcriptions of the
implementation.

**8 findings, 4 high. All fixed and verified.** I re-verified every high
finding myself with an independent probe before acting; output is quoted.

## The two correctness holes, which are the same hole

### F8. `expand` validated only the burst axis, so 3 of 4 anchor coordinates were unchecked in the sweep build

**Severity: high.** `src/layout.cpp`, `expand` and `line_of`.

D1 made the extent check a `throw` on the grounds that it is "the only thing
standing between a malformed trace and line ids that are wrong but look
fine." It covered one coordinate of four. The other three went to `line_of`,
which only asserted, so under `-DNDEBUG` they were unchecked.

Signed division made it worse rather than better: truncation toward zero
means a small negative coordinate does not go negative at all, it aliases
onto block 0. Verified against the release library, real layer, all with a
legal `axis=COUT, count=4, stride=1` burst:

```
legal   cin=0    -> [65536]   in_range=YES
BAD     cin=-1   -> [65536]   in_range=YES   <- identical to the legal line
BAD     cin=-4   -> [65408]   in_range=YES   <- a real neighbouring line
BAD     cin=512  -> [81920]   in_range=YES   <- one past CIN, lands inside the tensor
BAD     kw=3     -> [98304]   in_range=YES   <- one past KW, lands inside the tensor
BAD     cout=-1  -> THREW                    <- the only one checked
```

Four of six return a plausible line with no diagnostic.

**Fix:** `line_of` validates all four coordinates and throws
`std::out_of_range` with both the coordinate and the shape in the message.
Affordable because `expand` calls `line_of` once per burst, for the anchor,
then walks the run by adding a fixed stride.

This also **falsifies a claim `types.h` was making**, which the reviewer was
right to call out: signedness does not keep a bad coordinate "visibly
negative". Any `cin` in `[-(cin_block-1), -1]` lands on block 0. Only the
range check catches those. The comment now says so.

### F9. `locate` returned a negative `set_index` in the sweep build, which is worse than what the unsigned version did

**Severity: high.** `src/layout.cpp`, `locate`.

`assert(line >= 0 && ...)` was the only guard, and signed `%` follows the
dividend:

```
locate(     -1, 1024) -> set_index = -1
locate(   -128, 1024) -> set_index = -128
locate( -32767, 1024) -> set_index = -1023
```

Under the old `uint64_t` a garbage line still produced an in-range set index:
wrong line, safe index. **This is the one place the signedness migration
traded a defined-but-wrong answer for undefined behaviour**, and I had
recorded the widened assert as the mitigation without noticing that an assert
is exactly what the sweep build does not have.

Reachable end to end, verified:

```
expand(anchor kh=-1) -> line -32767
locate(that, 1024)   -> set_index -1023
a 32-way SetAssociativeArray subscripts slots_ at -1023 * 32 = -32736,
against a vector of 32768 slots. Out of bounds, not a wrong answer.
```

**Fix:** `locate`'s range check is a `throw` now. Two comparisons on the
probe path, which the measurements say is free.

### F10. `count < 0` was silently accepted while `stride <= 0` threw

**Severity: low, same class.** Both are trace-sourced. A corrupt negative
count became a silent no-op, so a tick quietly lost one core's demand, while
a corrupt stride stopped the run. **Fix:** `count < 0` throws;
`count == 0` is still a legitimately empty run.

## The three test-strength holes, each proven by mutation

### F11. No shape anywhere in the suite had `KH != KW`. Four KH/KW confusions passed 125/125

**Severity: high (test strength).** Every valid shape was `{3,3,..}`,
`{1,1,..}`, `{2,2,..}` or `{64,64,..}`, group G's four included, so nothing
could tell the two kernel axes apart. Each mutation applied alone, suite
unmodified:

| Mutation | Before | After |
|---|---|---|
| `line_stride(KH)` reads `shape_.KH` | **125 / 0 failures** | 167 / 4 failures |
| `line_of` flatten uses `shape_.KH` | **125 / 0 failures** | 167 / 5 failures |
| `WeightShape::extent(KH)` returns `KW` | **125 / 0 failures** | caught, aborts |
| `line_of`'s kh bound compares against `KW` | **125 / 0 failures** | 171 / 2 failures |

The first is a real bug with a concrete wrong output: on `{2,5,8,8}` blocks
2x2, a KH burst gives `[0, 32]` while `line_of{1,0,0,0}` gives 80. They
disagree by 48, and line 32 belongs to `kh=0, kw=2`.

**Fix:** new **group J**, on shape `{2,5,8,8}`, plus that shape added to
group G. The fourth mutation needed a specific pair to catch it, since
`KH = 2` and `KW = 5` means `kh = 2` is out of range while `kw = 2` is legal.
Non-square kernels are ordinary: 1x3, 3x1 and 7x1 factorized convolutions.

### F12. The new `throw` was exercised only on the COUT axis

**Severity: high (test strength).** All 64,000 group G bursts are legal by
construction, so none reaches the throw, and every group H case used
`Axis::COUT`. A build enforcing the upper bound **only** when
`axis == COUT` passed the whole suite. That matters directly, because
`types.h` says format v2 carries `burst_dim` precisely so a future arch can
burst along CIN.

**Fix:** group H now loops all four axes, checking the run past the extent,
the negative start, and that the last legal element alone is still accepted.
The mutation now gives 6 failures.

One mutant deliberately left alive: enforcing the **lower** bound only on
COUT still passes, and that is correct. It is an equivalent mutant, because
`start_coord` is just the anchor's coordinate and `line_of` now validates all
four. `layout.cpp` records this so nobody chases it.

### F13. "64,000 bursts" overstated group G by about 20x for the path production actually takes

**Severity: medium (test strength).** The reviewer replayed the generator's
RNG stream:

```
total bursts                     64000
  stride==1 (contiguous path)     6959   (11%)
  count==1 (degenerate)          48699   (76%)
contiguous, count>1, >1 line      2778   (4.3% of the total)
```

Two compounding causes. `stride` was drawn uniformly from `[1,9]` before the
room was known, so 8 of 9 bursts took the strided path. Then deriving the
count from the room left collapsed it to 1 whenever the axis was short, which
on KH and KW is almost always. Per plan Part 1.1 the current trace decodes
`cout_start..cout_end` into `stride = 1`, so **the contiguous path is the only
one production traffic takes**, and it was getting 4.3% of the suite.

**Fix:** stride is 1 half the time; the count is drawn from what the axis can
hold and the anchor is then placed among the positions that fit. Result:

```
80000 bursts, 207467 lines emitted
contiguous 40235 (multi-line 22843), strided multi-line 10478, degenerate 39210
```

Contiguous non-trivial bursts went from **2,778 to 22,843**, an 8.2x
improvement. Three coverage floors are now asserted so a future edit cannot
hollow the group out again silently.

The floors are deliberately uneven, and I set them from structure rather than
by tuning until it passed. A strided run needs an axis long enough to hold
one: of the 20 shape-by-axis combinations, **5 have a kernel extent of 1 or 2
and can never emit a multi-line strided burst**, and 4 more at extent 3
manage it only at stride 2. So ~10,000 is near the structural maximum for
`strided_multi`, and the same cap is most of why `degenerate` sits near half.

The reviewer also checked the two biases I had specifically asked about and
found **both unfounded**: 45,476 bursts ended exactly on a block boundary,
and the strided dedup fired 2,320 times on the CIN axis.

### F14. `make test` ran a stale binary after any change to a header under `tests/`

**Severity: medium.** `$(TEST_BIN)` depended on `$(TEST_SRCS)` and `$(LIB)`
but not on `tests/*.h`, and the test link line carried no `-MMD`. Verified:

```
$ printf '#error THIS FILE IS BROKEN\n' >> tests/check.h
$ make test
125 checks, 0 failures     (exit 0)
```

**This one is about the pipeline itself**, not the simulator: a mutation
applied to a `tests/` header would have reported a clean pass against the
previous binary. The published mutation tables are unaffected, because every
mutation in them was to `layout.cpp` or a header under `include/`, both of
which do trigger a rebuild. **Fix:** `TEST_HDRS` added to the prerequisites.
Verified: `make test` now fails.

### F15. The cross-core buffer contract on a throw was undocumented

**Severity: medium (contract).** **No defect in `expand` itself**, and the
reviewer verified that: every throw site precedes the first `push_back`, so a
throwing call appends nothing, and group H pins it.

The gap is one level up. In the accumulate pattern, a burst that throws part
way through a tick leaves the buffer holding a well-formed but **partial**
tick, the earlier cores only. **Fix:** `layout.h` now states that the engine
must decide whether such a tick is discarded or the run aborts, and must not
silently simulate the partial one. Carried to the engine's spec alongside C2.

## STALL 2 resolution, verified

```
171 checks, 0 failures    fixture build (-O0 -g)
171 checks, 0 failures    release build (-O2 -DNDEBUG)
0 warnings                both modes, full six-flag set
80,000 bursts, 207,467 lines emitted
unit 3 exercise           fixture and release byte-identical, 221,184 accesses
make test with a broken check.h -> now fails
```

Every previously-passing mutation, re-run:

| Mutation | Before | After |
|---|---|---|
| `line_stride(KH)` reads `shape_.KH` | 125 / **0** | 167 / 4 |
| `line_of` flatten uses `shape_.KH` | 125 / **0** | 167 / 5 |
| `WeightShape::extent(KH)` returns `KW` | 125 / **0** | caught |
| `line_of` kh bound against `KW` | 125 / **0** | 171 / 2 |
| `line_of` kw bound against `KH` | 125 / **0** | caught |
| upper bound only on COUT | 125 / **0** | 171 / 6 |
| lower bound only on COUT | 125 / 0 | 171 / 0, **equivalent mutant** |
| `line_of` drops the cin bound check | n/a | 167 / 5 |
| `locate` drops the line range check | n/a | 167 / 3 |
| negative count silently returns | n/a | 167 / 1 |
| expand drops both bound checks | n/a | 171 / 10 |
| the five from STALL 1, as a regression | caught | still caught |
| control | 0 | 0 |

## What this stall says about the process

Both units were reviewed by a human and by me before the reviewer saw them,
and the reviewer still found two ways a malformed trace reaches undefined
behaviour in the build that runs the sweep. The pattern in F8 and F9 is the
same one as F2 in STALL 1: **a check that is correct but lives where the
sweep build cannot see it.** That is now three instances, so it is worth
treating as a standing rule rather than a recurring surprise: any value that
originates outside the simulator gets a `throw`, and `assert` is only for
values this code produced itself.

F11 and F12 say something different and sharper. The suite reported 125
passing checks while six real mutations survived it. Passing tests measured
nothing about those axes, and only mutation testing showed it. That is worth
keeping as standard practice for each unit, not just when something feels
wrong.

---

# Decisions closed 2026-08-11

The six open decisions at the end of the unit 3 review, signed off in one
pass. Only decision 3 carried a code change.

| # | Decision | Outcome |
|---|---|---|
| 1 | four-verb split, `free_slot` + `victim_candidates` | kept as implemented |
| 2 | refuse a non-dividing cache size rather than round | kept, the CSV must not round |
| 3 | `Tick` signedness | **changed**, `std::uint64_t` -> `std::int64_t` |
| 4 | `locate` re-validates `num_sets > 0` per call | left as-is, revisit only if it profiles |
| 5 | no `invalidate` verb yet | agreed, deferred to `CacheLevel` |
| 6 | C2 still open | confirmed, belongs to the engine |

## Decision 3, `Tick` signed

`types.h:30`. Free to do now: `Tick` was declared and referenced nowhere, so
the change touched one typedef and no call site. The engine will subtract
ticks for stall time and for `max(tick_base + tick, core_ready_time)`, and an
unsigned subtraction that goes negative wraps to a large plausible value
instead of a visibly wrong one. That is the same failure `LineId` was made
signed to avoid, which makes this the third instance of the signedness class.

`CoreId` stays `std::uint32_t`. The review made it conditional on meeting a
signed count, and it meets nothing yet; changing it now would be speculative.
It becomes a real decision when the engine decodes `core_id` against a signed
core count.

Verified: 171 checks, 0 failures; fixture and release both build with the
full six-flag warning set and no output.

## What unit 4 inherits

The engine spec has to answer three things this unit deliberately did not:

- **C2**, the per-tick `reserve` obligation that F1 moved out of `expand` and
  nothing currently holds. Costs about log2(N) reallocations per tick, 11
  measured at 1024 lines, and no test will report it.
- **`invalidate`**, once plan 2.3's inclusion fix makes an L2 eviction
  back-invalidate the L1 copy.
- **`CoreId` signedness**, per decision 3 above.

## Unit status, current

| Unit | Function | Implemented | Human reviewed | Code reviewed | Tests |
|---|---|---|---|---|---|
| 1 | ctor, `block_len`, `line_stride`, `line_of`, `expand` | yes | accepted | 7 defects, all fixed | groups A-J, passing |
| 2 | `locate` | yes | accepted | with the reviewer | group I, passing |
| 3 | `SetAssociativeArray` | yes | accepted | 0 defects | **none, next** |
| 4 | engine / `CacheLevel` | not started | | | |

Unit 3 is the gap: implemented and reviewed clean, but the only evidence it
runs correctly is the implementer's 221,184-access exercise. STALL 2 showed a
125-check suite hiding six live mutations, so a unit with no suite at all is
the weakest point in the pipeline.
