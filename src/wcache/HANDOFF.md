# wcache rebuild: handoff

Written 2026-08-18. Read this, then `PROGRESS.md`, then the plan. Everything
needed to resume is in files; no conversation transcript is required.

## What this is

A from-scratch discrete-event cache model for an SNN weight cache, replacing
the archived v1 tree in `native_v1_archive/`. It replays weight traces through
a configurable L1/L2 hierarchy so that cache geometry, block layout, MSHR
depth, and prefetch policy become swept parameters rather than assumptions.

**The single authority is `log/2026-08-17-wcache-event-driven-plan-v3.md`.**
It supersedes five earlier plans in `log/` which are kept only as history. If
this document and the v3 plan disagree, the plan wins.

## The three files that carry state

| File | Role | Durability |
|---|---|---|
| `PROGRESS.md` | unit status, decisions B1-B38 with reasons, carried obligations | durable, never delete |
| `EXPLAIN.md` | explanation of the increment just built | **erasable**, overwritten each increment |
| `CPP_NOTES.md` | durable C++ lessons learned during the build | durable, append only |

`PROGRESS.md` is the record. Its carried-obligations table is the important
part: each row names a unit that must discharge something a later unit
depends on. Do not start a unit without reading the rows that name it.

## Current state

Branch `wcache-rebuild-phase-a`, commit `aff9b42`.

| Unit | Increment | Status |
|---|---|---|
| A1a | `Tagged` + six scalar types | done, reviewed, tested |
| A1b | `Axis`, `Coord`, `Burst`, `WeightShape` | done, reviewed, tested |
| A2a | `Placement`, `AddressMapper` interface | done, reviewed, tested |
| A2b | `BlockPackMapper` construction and validation | done, reviewed, tested |
| A2c | `line_of`, `block_len`, `line_stride`, `stride_[4]` | done, **review incomplete** |
| A2d | `expand`, `locate` | not started, currently `logic_error` stubs |

Critical path from the plan: `A1 -> A2 -> A4 -> A5 -> (Phase A gate) -> B3 -> C1 -> C2 -> C3`.

### Gate as committed

```
cd src/wcache/native && make clean && make test
92 compile cases, 0 failures
test_block_pack   413 checks, 0 failures
test_layout      9270 checks, 0 failures
test_types        263 checks, 0 failures
exit 0, warning-clean under -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow
```

### The one loose end

The A2c review was interrupted partway. The tree is green and the tests it
did write are committed, but it had not finished. Specifically **not** done:

- `compile_fail.sh` cases for A2c (it was starting these when stopped)
- `mutation_check.sh` cases for A2c
- the meta-verification step (deliberately weaken a check, confirm the
  matching mutation then survives, restore)

So A2c's tests exist but their negative half is unverified. Finish that before
or alongside A2d.

## How the work is done

A three-role pipeline, and the discipline matters more than it looks:

- **Implementer** builds **one function, class, or struct**, then **stops** and
  overwrites `EXPLAIN.md` with a rich worked-example explanation plus its open
  questions. It does not batch several units to save a round trip.
- **Reviewer** writes and runs tests **one unit behind** the implementer. It
  owns `tests/` and the build harness. It does not touch production code.
- **PM** owns `PROGRESS.md` only. It records decisions the plan did not make.

The handshake: implementer stops, the human reads `EXPLAIN.md` and may ask
questions, the human says "next", and only then does the next increment begin.

**Serialize the reviewer and implementer.** The `Makefile` globs both
`tests/*.cpp` and `src/*.cpp`, so a reviewer running `make test` while an
implementer writes `src/block_pack.cpp` produces failures belonging to neither.
The PM can run in parallel with either, since it touches only Markdown.

## Testing philosophy, which is unusual and deliberate

Contract-based, not example-based. `tests/mapper_conformance.h` holds nine
checks parameterised over the abstract `const AddressMapper&`, so a new layout
inherits all nine by adding one `run_all(...)` line. Thirteen deliberately
non-conforming fakes in `test_layout.cpp` exist so the suite can be shown to
catch them; `expect_caught` fails if a check passed **or ran zero checks**.

The negative halves of the exit criteria:

- `tests/compile_fail.sh`: reject cases (this must not compile) **and** accept
  cases (this does compile, and we are recording that it does). The accept
  cases are how the known `Tagged` narrowing gap is measured rather than
  assumed.
- `tests/mutation_check.sh`: mutate a source line, confirm the suite goes red.
  Takes an optional filter argument by file path or case name, because a full
  run is roughly 35 minutes on a login node. A surviving mutation is a gap in
  the tests; fix the test, never weaken the mutation.

## Decisions a newcomer must not silently re-litigate

All are in `PROGRESS.md` with full reasoning. The ones most likely to look
wrong at first glance:

- **B27, exception vocabulary.** `invalid_argument` = malformed regardless of
  layer. `out_of_range` = well formed but outside *this* layer. `logic_error` =
  programmer error, including unimplemented stubs. Five other decisions rest on
  this.
- **B25, `line_of` validates against `extent_on(shape_, a)`, never against
  `block_len`.** The shape check is strictly stronger. At `CIN=100,
  cin_block=32`, a `cin` of 100 divides to block 3 and would pass a `block_len`
  check while naming an element the layer does not have; `cin = -1` divides to
  block 0 and would pass it too, because integer division truncates toward
  zero. Signedness alone does not make a bad coordinate visible. Accepted cost:
  `block_len` has no library caller until A2d, so it needs direct tests.
- **B17 and B22, the flatten order is KH -> KW -> cin_block -> cout_block** with
  radices `(KW*n_cin*n_cout, n_cin*n_cout, n_cout, 1)`. Order is a bijection,
  so it changes neither line contents nor `num_lines`. It changes only which
  axis owns the low bits of `line`, hence `set_index = line % num_sets`.
  COUT at radix 1 makes a COUT-walking burst a contiguous run, alias-free at
  every set count. Every corpus trace bursts along COUT.
- **B24, flatten order is not a swept parameter**, and the radices live in
  `stride_[4]` indexed by `static_cast<int>(Axis)` so a future permutation is a
  one-function edit.
- **B34.** `line_of` **is** surjective onto `[0, num_lines())` even for a
  non-dividing layer, because `(extent-1)/block == ceil(extent/block)-1`
  always. Padding is intra-line and non-uniform, not extra-line. Verified by
  exhaustive enumeration on shape 3x5x100x50 at blocks 32/8: 420 lines, all
  reached, fan-in histogram 270 at 256 / 45 at 64 / 90 at 32 / 15 at 8.
- **B38.** A burst with `count < 1` throws `invalid_argument`. v1 allowed it.

B27 through B38 were **resolved by delegation**, meaning the user asked for a
recommendation rather than deciding each individually. That is a weaker warrant
than an explicit answer. If one of them looks wrong later, it is fair game to
reopen; the rows are marked so you can tell which.

## What A2d must do

`expand` and `locate`, the two remaining `AddressMapper` methods.

Obligations already recorded against A2d, from `PROGRESS.md`:

1. `locate` range-checks `0 <= line < num_lines()` before dividing, throwing
   `out_of_range`. This also discharges the question of what `locate` promises
   for a negative `LineId`.
2. `count < 1` throws `invalid_argument` (B38), and `layout.h` states it.
3. One `layout.h` edit covering five things: the `out_of_range` contract, the
   `locate` precondition, "strictly increasing" as an obligation on
   implementations rather than a property of the layout, `count < 1`, and two
   stale citations (a retired "merge ratio 1.13 at 1024 cores" figure, and a
   "Plan v2 Part 2.1" reference that should point at v3).
4. `expand` must emit strictly increasing ids whatever the layout, sorting if
   its walk order does not produce them. Zero cost today, since COUT sits at
   radix 1.
5. The conformance `Env` has no zero-count burst and needs one on the illegal
   side.

## Known latent defects, unowned

- **Representability versus plausibility.** `BlockPackMapper(WeightShape{1,1,1,1},
  INT32_MAX, INT32_MAX, 2)` is accepted and reports `line_size_bytes() ==
  9223372028264841218`, about 9.2 exabytes. D1 computes a set count as
  `cache_size_bytes / line_size_bytes`, which is 0 for any such mapper, and a
  zero set count is a division by zero in `locate`. Whether A2b or D1 owns a
  plausibility bound is **not decided**. The `at_bound` case in
  `test_block_pack.cpp` is where a bound would surface.
- **`Tagged` narrows silently.** `SlotId s{p.tag}` compiles and truncates 64
  bits to 32. Policy is decided (a `Tagged` constructor must not narrow),
  mechanism is scheduled for A4, and three `compile_fail.sh` cases currently
  recorded as `accept` must flip to `reject` then.
- **Error messages lack context.** `line_of` throws naming axis, range, and
  value, but the plan's V15 requires naming tile, tick, and core too.
  `BlockPackMapper` is context-free by construction and cannot supply them.
  Resolution is to catch and re-throw at the engine boundary, keeping the
  `out_of_range` type; there is exactly one wrap site because `expand` is the
  only entry point the engine uses. Ownership goes to whichever unit owns the
  per-tick accumulate buffer, because that same catch must also decide the fate
  of a partially accumulated tick (`layout.h:67-72`).

## Corpus facts that constrain design

- 155 layer directories under `outputs/weight_traces`, 7.7 GB total.
- **Every** layer is KH=KW=3 with CIN and COUT in {64, 128, 256, 512}.
- So every radix is a power of two, which is why a strided walk aliases
  perfectly against a power-of-two set count rather than degrading gracefully.
- Non-divisible extents are unreachable for any power-of-two block up to 64,
  and first bite at `cout_block = 128` on the COUT = 64 layers. Ceiling
  division was chosen over rejecting so that different sweep grid cells cover
  the same 155 layers, rather than silently comparing a 155-layer mean against
  a 140-layer mean.
- Core range settled at 8 to 256. The "1024 cores" and "merge ratio 1.13"
  figures in older text are retired.

## Running it

```bash
cd src/wcache/native
make clean && make test          # full gate
./tests/mutation_check.sh                 # all mutations, slow
./tests/mutation_check.sh block_pack      # filtered
./tests/compile_fail.sh                   # accept and reject cases
```

NCSA Delta login nodes have a 30-minute CPU cap, so run the full mutation
sweep filtered or on a compute node.
