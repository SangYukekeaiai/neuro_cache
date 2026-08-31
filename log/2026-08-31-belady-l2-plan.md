# 2026-08-31: Belady on the L2, against LRU and against nocsim

Authority for the Belady measurement. Implementation lives in
`profiling/0831_reuse_distance/` alongside the reuse-distance work it extends;
the live board is that folder's `PROGRESS.md`, unit series W.

Follows `log/2026-08-31-reuse-distance-plan.md`, whose finding this tests.

## 1. The question worth asking

Belady's MIN cannot beat the cold-forced ceiling. V8's L2 sees 77,824 references
over 36,864 distinct lines, so 47.37% of them are compulsory and **52.63% is the
hit rate no replacement policy can exceed**. Fully-associative LRU already reaches
it. So "what is Belady's best hit rate" has a known answer at any capacity where
the cache can hold the reuse window: 52.63%, and measuring it is a check rather
than a discovery.

The live question is the one yesterday's finding raises:

> **At 16-way, where LRU returns 0.00%, what does a perfect policy return?**

Two outcomes, and they prescribe different hardware:

- **Belady reaches 52.63% at 16-way.** The set index is fine and LRU is simply
  the wrong policy for this access pattern. The fix is a better replacement
  policy, which is cheap.
- **Belady stays far below 52.63% at 16-way.** More lines are live in a set than
  the set has ways, so no policy can hold them. The fix is ways or a different
  set index, and the replacement policy is irrelevant.

Belady is the instrument that separates those, and nothing else does.

## 2. Belady fits the policy interface without breaking it

Plan v3 Part 2.2 is explicit that a policy "knows nothing about sets or ways" and
that "nothing about sets, ways, associativity or line addresses may appear in
what a policy is TOLD". Belady needs to know the future, which sounds like it
needs the line. It does not.

LRU keeps one stamp per slot, the time of its LAST use, and evicts the MINIMUM.
Belady keeps one stamp per slot, the time of its NEXT use, and evicts the
MAXIMUM. Same shape, opposite sign, and the policy still holds nothing but a
number per slot.

The only new thing is that LRU derives its stamp from a counter it owns, and
Belady's has to be supplied. That is one optional virtual:

    // Optional. The engine's hint about when this slot's occupant is next
    // referenced. A time, not a line, so 2.2's rule holds. Default no-op, so
    // every existing policy is unchanged.
    virtual void note_next_use(SlotId, std::int64_t) {}

A line never referenced again gets `INT64_MAX` and is evicted first, which is
what MIN prescribes.

`pick_victim` must not depend on candidate order (A5's exit criterion). Two slots
tie only when both hold lines never used again, so the tie-break is the smallest
`SlotId` among the maxima: a function of the candidates, not of their positions.

## 3. The oracle, and why it converges

The oracle answers: for the k-th L2 reference to line X, where is the (k+1)-th?
It is built from an access log, which `--access-log` already emits, and is keyed
by **(line, occurrence index)** rather than by absolute time, so it survives a
change in how the sixteen cores interleave.

The stream it is built from is the stream a Belady run will see, for a reason
that is already established rather than assumed:

- The per-core L1 reference sequence is config-independent (V4, proved on all
  four layers).
- `inclusion = non_inclusive`, so the L2 never back-invalidates an L1.
- Therefore each core's L1 hit/miss pattern depends only on its own sequence and
  the L1 geometry, and its L2 reference sequence is invariant to the L2's
  replacement policy.

What is NOT invariant is the merge order across the sixteen cores, because L2
hits change timing. So the run is iterated: build the oracle from run N's log,
run N+1 with it, and compare the two L2 streams. **Identical streams mean the
oracle was exact and the run is true Belady.** This is measured and reported per
layer, never assumed. B3 below is the check.

## 4. Config

`policy` currently feeds both levels from one knob (`config.cpp:602,612`). Belady
on the L2 alone needs `l2_policy`, defaulting to `policy` so every existing
config and every committed result is unchanged.

## 5. The measurement matrix

Per layer, five samples, everything else at the best config from
`_khkw_grid/khkw_64b.json[0]`:

| Arm | L2 geometry | L2 policy | What it answers |
|---|---|---|---|
| A | 512 KB, 16-way | LRU | the swept point, 0.00% |
| B | 512 KB, 16-way | **Belady** | **can a perfect policy fix the conflict** |
| C | 512 KB, 64-way | LRU | yesterday's fix |
| D | 512 KB, 64-way | Belady | headroom left above C |
| E | 512 KB, fully assoc. | Belady | the ceiling, must be 52.63% |

The latency comparison is arms A, B, C and the nocsim baseline, which is
`stage3_total_cycles` in
`profiling/0823_stagewise_verify/stage4_wcache/outputs/khkw_vs_stage3.csv`,
already on disk: V8 302,253, V9 310,191, R9 77,142, R16 151,485.

## 6. Units

| Unit | Increment |
|---|---|
| W1 | `note_next_use` on `ReplacementPolicy`, `BeladyPolicy` in `stamp_policy.h`, tests |
| W2 | `NextUseOracle`: build from an access log, answer per (line, occurrence) |
| W3 | `l2_policy` in config, and the engine pushing the stamp at L2 fill and hit |
| W4 | `run_belady.py`: the five arms, the fixpoint iteration, the convergence check |
| W5 | Analysis and the artifact update |

## 7. Verification

- **B1** Belady is never worse than LRU at the same geometry, on every layer and
  sample. A property of MIN; a violation means the oracle is wrong.
- **B2** Belady fully-associative equals the cold-forced ceiling exactly, which
  is 52.63% on V8, V9 and R16 and 0.00% on R9.
- **B3** The oracle converges: run N and run N+1 produce byte-identical L2 access
  logs. Reported per layer.
- **B4** With the oracle attached but `l2_policy = lru`, every column of the
  results row is identical to today's committed run. The oracle must be inert
  unless it is selected.
- **B5** `note_next_use` is a no-op on LRU and FIFO, so all 21 existing engine
  suites stay green and `test_stamp_policy`'s 120-permutation order-invariance
  check extends to Belady.

## 8. Out of scope

Belady on the L1 (its 8-way array already beats fully-associative LRU, so the
interesting question there is the set index, not the policy). Belady as a
shippable policy: it is an upper bound and is measured as one. Re-cutting the
set index, which is the follow-on this result will inform.
