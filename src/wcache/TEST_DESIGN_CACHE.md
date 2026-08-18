# Unit test design: unit 3, `SetAssociativeArray`

Companion to `TEST_DESIGN.md`, which covers units 1 and 2 (`BlockPackMapper`,
`locate`) and owns groups A-J. This file owns groups K onward, so a group
letter identifies its unit across both documents and both test binaries.

Unit 3 is implemented (`cache.h`, `cache.cpp`) and reviewed with no defects
found. It has no suite. The only evidence it runs correctly is the
implementer's 221,184-access exercise, which was byte-identical between the
fixture and release builds but is not committed and checks no stated
expectation. STALL 2 established that a 125-check suite can hide six live
mutations, so "reviewed clean, untested" is the weakest state a unit can be
in.

---

## 1. Where the tests live, and the one build change it forces

`src/wcache/native/tests/test_cache.cpp`, a second file beside
`test_layout.cpp`.

One file per interface is plan Part 3.4, and the Makefile already globs
`tests/*.cpp` into `TEST_SRCS` and lists `tests/*.h` in `TEST_HDRS`, so a new
file is picked up and correctly re-linked with no Makefile change. Both files
link into the one `wcache_tests` binary and the check counts add, which is why
the group letters have to stay unique across the two.

**But they cannot both define `main`.** `test_layout.cpp:662` has it today,
calling `group_a()` through `group_j()`, all of them `static`. Linking a second
file with its own `main` fails, and the fix has to be chosen before either file
is written, not after:

| Option | Cost |
|---|---|
| A. `main` stays in `test_layout.cpp` and also calls the cache groups | the layout file drives a suite it has nothing to do with, and every later unit edits it again |
| B. `main` moves to `tests/main.cpp`; each suite exposes one entry, declared in `tests/suites.h` | touches `test_layout.cpp` once, to drop `main` and un-`static` a single entry function |
| C. two binaries, `wcache_tests_layout` and `wcache_tests_cache` | a real Makefile change, two commands to run, two check counts to read |

**Proposal: B.** It is the only one that stays flat as units 4 and 5 arrive, and
the edit to `test_layout.cpp` is two lines: delete `int main()`, replace it with
`void run_layout_tests()` calling the same ten groups, and let `main.cpp` call
`run_layout_tests()` then `run_cache_tests()` then `check::summary()`. The
group functions themselves stay `static` and untouched.

`tests/suites.h` is two declarations. `TEST_HDRS` globs `tests/*.h`, so F14's
stale-binary fix already covers it.

This is the only change this design makes to existing code. Flagging it because
it edits a file that is passing 171 checks, and the edit has to preserve them
exactly: verification is the same 171 checks, 0 failures before the cache
groups are added at all.

## 2. Harness

`check.h` unchanged, reused as-is. `CHECK_EQ`, `CHECK_TRUE` and
`CHECK_THROWS(ExcType, expr)` cover everything below; the constructor cases
need the exception type named, which `CHECK_THROWS` already takes.

One addition is needed and it is small: `to_str` has an overload for
`std::vector<std::int64_t>` but not for `Candidate` or
`std::vector<Candidate>`, so a failing candidate-list comparison would not
print. Proposal is to compare candidate lists field-wise with `CHECK_EQ` on
`slot` and `line` rather than adding an overload for a type from the code
under test into the generic harness. It keeps `check.h` free of wcache types,
which is the property that lets it stay a thirty-line file.

**Both builds must run this suite.** The constructor's six rejections are
`throw`, not `assert`, precisely so they survive `-DNDEBUG`, and F8/F9 were
two cases of a check that was correct but invisible in the build that runs the
sweep. So verification is:

```
make -C src/wcache/native test                 # asserts live
make -C src/wcache/native MODE=release test    # asserts compiled out
```

The Makefile prints a warning on the second, which is correct for
`test_layout.cpp` and worth ignoring here: the release run is the point for
groups L and Q.

## 3. The oracle

Groups K through Q are hand-computed, the repo convention. Group R adds an
independent model, and the interesting design decision is what the model is
allowed to know.

**The model must not assume the slot numbering.** `cache.h:34-37` states that
`set_index * associativity + way` is private to the file and that
`FullyAssociativeArray` will number slots differently while the same policies
keep working. A shadow model that recomputed slot ids that way would test the
formula twice and the contract not at all, and it would have to be rewritten
for the next array.

So the model is a `std::vector<std::vector<LineId>>` indexed `[set][way]`,
driven through the four verbs, and it compares only what the interface
promises:

| Observable | Compared as |
|---|---|
| residency | `probe(line) != kNoSlot` against the model's membership |
| stability | `probe(line)` returns the *same* slot on every call while resident |
| set partition | slots reachable for line X and line Y are disjoint unless X and Y share a set, identical when they do |
| candidate count | `victim_candidates` size equals `associativity()` |
| eviction | `InsertResult` against the line the model displaces |
| exhaustion | `free_slot` is `kNoSlot` exactly when the model's set is full |

`locate` is shared between model and code, so group R does not re-validate the
line-to-set map; group I already tests `locate` standing alone. What group R
tests is everything the array builds on top of it.

The concrete numbering still gets pinned, but as a white-box property of this
class rather than of `CacheArray`, in group S, and labelled as such so that
adding `FullyAssociativeArray` does not look like it broke a contract test.

---

## 4. Test groups

Two geometries recur, both from the real configurations in `cache.cpp:76`:
**L1** = 32768 bytes, 16-byte lines, assoc 4, so 512 sets, 2048 slots. **L2** =
524288 bytes, assoc 32, so 1024 sets, 32768 slots.

### Group K, constructor and derived quantities

| # | Case | Expected |
|---|---|---|
| K1 | L1 geometry | `num_sets = 512`, `associativity = 4`, `num_slots = 2048` |
| K2 | L2 geometry | `num_sets = 1024`, `associativity = 32`, `num_slots = 32768` |
| K3 | assoc 1, 4096 bytes | `num_sets = 256`, `num_slots = 256`, the direct-mapped case of `cache.h:142-146` |
| K4 | assoc equal to total lines, 4096 bytes assoc 256 | `num_sets = 1`, fully associative degenerate case |
| K5 | every slot free at construction | `probe(line) == kNoSlot` for all lines mapping to a sampled set |
| K6 | `num_slots` equals `num_sets * associativity` | across K1-K4 |

### Group L, constructor rejections

Each throws `std::invalid_argument`. **Every case runs in both builds**, since
these are the checks that exist to survive `-DNDEBUG`.

| # | Case | Which check |
|---|---|---|
| L1 | `cache_size_bytes = 0`, and negative | `cache.cpp:38` |
| L2 | `associativity = 0`, and negative | `cache.cpp:41` |
| L3 | mapper reporting `line_size_bytes <= 0` | `cache.cpp:45`, needs a stub mapper, see section 6 |
| L4 | 4095 bytes against 16-byte lines | `cache.cpp:54`, not a whole number of lines |
| L5 | 4096 bytes, assoc 512 against 256 lines | `cache.cpp:67`, assoc exceeds the cache |
| L6 | 4096 bytes, assoc 3 against 256 lines | `cache.cpp:77`, lines do not divide into sets |
| L7 | L5 and L6 are distinguishable | the two messages differ; assert on `what()` containing "exceeds" vs "divide" |

L7 exists because L5 and L6 are both "bad associativity" and an implementation
that dropped one check would still throw on the other case. Without it the two
checks are one check as far as the suite can see.

### Group M, `probe`

| # | Case | Expected |
|---|---|---|
| M1 | probe on a fresh array | `kNoSlot`, for lines across many sets |
| M2 | insert then probe | returns the slot that was inserted into |
| M3 | probe is repeatable | same slot on 10 consecutive calls, no drift |
| M4 | probe of a line in the same set as a resident one | `kNoSlot`, not the neighbour's slot |
| M5 | probe of a line in a *different* set from a resident one | `kNoSlot` |
| M6 | probe leaves no trace | full-array residency snapshot identical before and after |

M4 is the one that catches a probe comparing against something other than the
line id, and M5 catches a probe that forgot to scope itself to the set.

### Group N, `free_slot`

| # | Case | Expected |
|---|---|---|
| N1 | fresh array | returns a slot, not `kNoSlot` |
| N2 | lowest free way | fill ways in order, each `free_slot` returns the next one up, per `cache.cpp:133-137` |
| N3 | after filling all `associativity` ways of one set | `kNoSlot` |
| N4 | a full set does not starve a different set | `free_slot` still answers for a line in another set |
| N5 | freed by eviction, then reused | after an `insert` over an occupied slot the set stays full |
| N6 | determinism | two arrays given the same insert sequence return identical slots throughout |

N2 is load-bearing beyond tidiness: `cache.cpp:133-137` justifies lowest-way
selection as what makes a cold-start fill reproducible under the Random policy
of plan 3.3. If that ordering silently changed, only a re-run of a whole sweep
would show it.

### Group O, `victim_candidates`

| # | Case | Expected |
|---|---|---|
| O1 | size | exactly `associativity()` entries, at every fill level |
| O2 | **replaces, does not append** | pre-fill `out` with 7 junk entries, call, size is still `associativity()` |
| O3 | called twice in a row | second call's contents equal the first's |
| O4 | free ways carry `kNoLine` | a partly filled set reports `kNoLine` in the free entries |
| O5 | occupied ways carry the resident line | matches what was inserted, per slot |
| O6 | all candidates are in one set | every returned slot answers `probe` for the line it holds |
| O7 | ways in index order | slots strictly increasing across the list, per `cache.cpp:153-156` |
| O8 | buffer capacity converges | `out.capacity()` unchanged across calls 2..10 |
| O9 | leaves the array unchanged | residency snapshot identical before and after |

O2 is the single most valuable case in this group. `cache.h:119-125` spells out
the failure it prevents: an appending implementation makes a caller that
forgets to clear pick a victim from a previous fill in a *different set*, and
the line is then stored where `probe` can never find it. That is a silent hit
rate error, not a crash.

O8 checks the property that made this `reserve` acceptable where F1's was not.
It is the local, testable half of C2; the per-tick half stays open and belongs
to unit 4.

### Group P, `insert`

| # | Case | Expected |
|---|---|---|
| P1 | into a free slot | `evicted = false`, `evicted_line = kNoLine` |
| P2 | into an occupied slot | `evicted = true`, `evicted_line` is the previous occupant |
| P3 | the two fields never disagree | `evicted == (evicted_line != kNoLine)` over the whole of group R |
| P4 | after insert | `probe(line)` returns that slot |
| P5 | after eviction | `probe(old_line)` returns `kNoSlot` |
| P6 | insert does not disturb other ways | the set's other occupants still probe to their own slots |
| P7 | insert does not disturb other sets | residency snapshot of a sampled other set is unchanged |

P3 is stated as an invariant checked inside the randomized group rather than as
a case, because it is the property `cache.h:78-81` uses to argue the struct
cannot self-contradict.

### Group Q, capacity and conflict behaviour

| # | Case | Expected |
|---|---|---|
| Q1 | `associativity + 1` distinct lines into one set | exactly one eviction |
| Q2 | working set smaller than one set, replayed | one miss per line, then all hits |
| Q3 | direct-mapped conflict, assoc 1 | two lines `num_sets` apart evict each other every time |
| Q4 | slot reachability | the union of candidate slots over lines `[0, num_lines)` is exactly `[0, num_slots)` |
| Q5 | no slot serves two sets | that union is a partition, no slot appears under two set indices |

Q4 and Q5 are the array-level counterpart of group I's set-index reachability
check and cover plan 5.2. A geometry where some slot is unreachable is storage
the sweep paid for and never used, which would show up only as a hit rate a few
points below the truth.

Q3 is worth its own case because assoc 1 is a real configuration
(`cache.h:142-146`), and it is the width at which an off-by-one in the way loop
stops being visible.

### Group R, randomized replay against the model

Drive both the array and the section 3 model with the same stream and compare
after every operation.

- **Stream**: an access is a `LineId` drawn from a mixture, roughly a third
  uniform over `[0, num_lines)`, a third from a small hot working set, a third
  a repeat of a recent line. The mixture matters: uniform-only access on 512
  sets almost never fills a set, so eviction would barely be exercised, which
  is F13's lesson, that a large case count can still leave the interesting path
  nearly untouched.
- **Per access**: `probe`; on a miss, `free_slot`, and if that is `kNoSlot`,
  `victim_candidates` and pick the lowest-numbered slot as a stand-in policy
  (unit 3 has no policy yet, and the choice only has to be legal, not smart).
  Then `insert`.
- **Compared each step**: residency, returned slot stability, `InsertResult`
  against the model, `free_slot` exhaustion agreeing with the model.
- **Size**: 200,000 accesses at the L1 geometry, plus a small-geometry run
  (32 sets, assoc 4) where sets fill constantly. The small geometry is the one
  that actually stresses eviction; the L1 one confirms nothing breaks at scale.

Reported like group G: accesses, hits, misses, evictions, and the fraction of
misses that needed a victim. If the eviction fraction is near zero the stream
is wrong and the group is not testing what it claims, which is the check F13
would have wanted.

### Group S, white-box, `SetAssociativeArray` numbering only

Explicitly not a `CacheArray` contract test. If `FullyAssociativeArray` fails
these, that is correct behaviour, not a regression.

| # | Case | Expected |
|---|---|---|
| S1 | slot ids of a set | `victim_candidates` for a line in set `s` returns `s*assoc .. s*assoc+assoc-1` |
| S2 | `probe` and `free_slot` agree with that base | both return slots in that range |
| S3 | slot ids are dense | `[0, num_slots)` with no gaps, across K1-K4 |

---

## 5. Mutation testing

Standing practice since STALL 2, where the suite reported 125 passing checks
while six real mutations survived. A mutation that no group catches means the
group that should have caught it does not test what its name says.

| # | Mutation | Should be caught by |
|---|---|---|
| 1 | `probe` returns `base` unconditionally | M1, M4 |
| 2 | `probe` compares against `kNoLine` instead of `line` | M2 |
| 3 | `probe` drops the `* associativity_` on `base` | M5, S2 |
| 4 | `free_slot` scans ways downward | N2 |
| 5 | `free_slot` returns the first way without testing `kNoLine` | N3, P6 |
| 6 | `victim_candidates` drops the `clear()` | **O2** |
| 7 | `victim_candidates` loops to `associativity_ - 1` | O1 |
| 8 | `victim_candidates` emits `kNoLine` for every entry | O5 |
| 9 | `insert` sets `evicted = true` unconditionally | P1, P3 |
| 10 | `insert` reports `evicted_line = line` | P2 |
| 11 | `insert` writes to `slots_[0]` | P4, P7 |
| 12 | ctor sets `num_slots_ = num_sets_` | K1, K6 |
| 13 | ctor drops the exactness check on bytes | L4 |
| 14 | ctor drops the `associativity > total_lines` check | L5 |
| 15 | ctor drops the divides-into-sets check | L6 |
| 16 | control, no mutation | nothing |

Mutations 13-15 are run in the **release** build as well, since that is where
the equivalent unit 1 checks turned out to be invisible.

Any mutation that survives gets a new case, and the surviving mutation is
recorded in `FINDINGS.md` the way F11's five were.

---

## 6. What this design deliberately does not cover

| Not covered | Why | Where it lands |
|---|---|---|
| the three `assert`s in `insert` | an assert failure aborts the process, so it cannot be checked in-process | open question 1 below |
| `as_size`'s negativity assert | same, and it is unreachable without one of the above already failing | same |
| `ReplacementPolicy` | not written | unit 4's suite |
| the per-tick `reserve`, C2 | belongs to the engine's accumulate loop, not this array | unit 4's spec |
| `invalidate` | not on the interface yet, decision 5 deferred it | `CacheLevel` |
| `FullyAssociativeArray` | not written | later, same file, groups K-R reused |
| performance | not a correctness question | the sweep |

The stub mapper L3 needs is worth flagging as real work rather than a detail:
`AddressMapper` has to be implemented far enough to return a bad
`line_size_bytes` while `locate` still answers, so it is a small test-local
subclass, maybe 15 lines. It is the only new scaffolding this design requires.

## 7. Size and cost

Roughly 550 lines in `test_cache.cpp`. Group R's 200,000 accesses at the L1
geometry is about the size of the exercise the implementer already ran in
0.01 s, so the whole suite stays in the default `make test` with no flag.

---

## Questions I need answered before writing this

1. **The three `assert`s in `insert` (`cache.cpp:166-177`).** By the standing
   rule from STALL 2, `assert` is right: `slot` comes from `free_slot` or from
   a policy, so a bad value originates inside the simulator, not in a trace.
   But the review's own note is that each of the three failure modes is silent,
   and a wrong-set slot stores a line where `probe` can never find it, which
   costs a whole sweep's hit rates and points at nothing. Three ways to go:
   leave them as asserts and accept that the suite cannot reach them; convert
   to `throw` as D1 did for `expand`, which makes them testable and live in the
   sweep; or keep asserts and add fork-based death tests. My recommendation is
   **leave as asserts for now and revisit at unit 4**, when a real policy exists
   and it is clear whether a policy can produce a wrong-set slot at all. Yours.

2. **Group R size and shape.** 200,000 accesses at L1 plus a small-geometry run.
   Is the small geometry worth it, or would you rather one stream? I think it is
   the more valuable of the two, since it is where sets actually fill.

3. **Option B for the `main` split** (section 1), which is the one item here
   that edits existing code. A is less disruptive today and worse at unit 4;
   C is the clean separation if you would rather read two check counts.

4. **Should `make test` run both build modes?** Right now it runs one, and the
   release run is a separate command that prints a warning. Groups L and Q want
   release. I can add a `make test-all` that runs both and reports both counts,
   or leave it as two commands in the verification notes.
