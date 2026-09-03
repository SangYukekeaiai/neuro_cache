# 0831 reuse distance: progress board

Authority: `log/2026-08-31-reuse-distance-plan.md`. Unit names and exit criteria
come from its Part 7, the V-list is its Part 8.

Pipeline: implementer builds one class at a time, stops, overwrites
`EXPLAIN.md`. User reviews and says "next". Only then does the reviewer test the
completed unit and the implementer start the following one.

`EXPLAIN.md` is erasable and is never the record of anything. This board is the
record.

## Board

| Unit | Increment | Implemented | Explained | Reviewed | Tested |
|---|---|---|---|---|---|
| U1 | `StackDistance`, `ReuseHistogram`, naive oracle, self-checks | done | done | done | done: 850 checks, 0 failures, 10 mutations with 9 killed and 1 recorded `allow` |
| U2 | `AccessLog` dumper, hooked at the two access-count sites, `--access-log` on `wcache_run` | done | done | done | done: row identical with and without the log on every one of the 93 columns bar `sim_wall_seconds`; 21 engine suites still green |
| U3 | `reuse_tool`: read an access log, write the histogram CSV | done | done | done | done: 2.68M records in 0.19 s, V1 exact on every run |
| U4 | `run_reuse_hist.py`, 20 best-config runs plus 4 for V4 | done | done | done | done: 24 runs in 12 s, V1 and V4 pass on all |
| U5 | `analyze_reuse.py`: CDF, hit-rate curve, V2, V3, the finding | done | done | done | done: V2 and V3 pass, agreement better than 0.005% |
| U6 | The published artifact | done | done | done | https://claude.ai/code/artifact/38f8e8d6-02fb-486a-af96-b9b9b03d3983 |

**All units complete 2026-08-31.**

## Board, W series (Belady on the L2)

Authority: `log/2026-08-31-belady-l2-plan.md`.

| Unit | Increment | Implemented | Explained | Reviewed | Tested |
|---|---|---|---|---|---|
| W1 | `note_next_use` on `ReplacementPolicy`, `BeladyPolicy` | done | done | done | done: `test_stamp_policy` 150 checks, 5 mutations all killed |
| W2 | `NextUseOracle`, keyed by (line, occurrence), plus an engine-free `optimal_hit_rate` | done | done | done | done: exercised through B2 and B3 |
| W3 | `l2_policy` in config, `--l2-oracle` on `wcache_run`, the occurrence counter in `CacheLevel` | done | done | done | done: B4 inert on all 93 columns, four refusals fire, 21 suites green |
| W4 | `run_belady.py`: six arms, the fixpoint iteration, B1 B2 B3 | done | done | done | done: 120 runs, B1 B2 B3 all pass |
| W5 | Analysis and the artifact update | done | done | done | published |

**W series complete 2026-08-31.**

**D7, 2026-08-31. B1 caught a real bug, which is the reason it exists.** The first
full run had Belady returning 6.58% where LRU returned 52.63% at the same
geometry, which is impossible for an optimal policy. Cause: `CacheLevel` advanced
the per-line occurrence counter only inside the array-HIT branch of `triage`. At
16-way the L2 hit rate is exactly 0.00%, so the counter never moved and every
fill consulted occurrence 0 for the whole run. It passed B2 throughout, because
at fully-associative the cache is large enough that the eviction choice barely
matters. Fixed by consuming the occurrence before the array probe, under the same
`r.demand` guard that `engine.cpp` counts `l2_accesses` with, so the counter and
the access log advance together by construction.

## The Belady findings

**The 16-way conflict has two independent components.** LRU returns 0.00% where
Belady's MIN returns 26.32%, so LRU is pathological rather than merely
suboptimal. But 26.32% is exactly half of the 52.63% ceiling, so even perfect
knowledge of the future leaves half the reuse on the floor: more lines are live
in a set than the set has ways. Neither component alone explains the zero.

**At 64-way, Belady and LRU are identical to the cycle.** Once the ways are
there LRU is already optimal, so there is no policy headroom to chase. That is
the cleanest available statement that associativity is the lever.

**The result that outranks the hit rate: a lock-step barrier makes total hit rate
the wrong objective.** Belady at 16-way wins 26.32% of L2 accesses and buys
essentially NO makespan.

**D10, 2026-08-31. "Belady is slower than LRU" was reported without isolating
its cause, and the cause is not the policy.** The whole excess is L2 PORT
serialisation. Measured on V8 s0 at l2_miss_latency 24:

    l2_ii = 1   LRU 290,136   Belady 293,888   +3,752
    l2_ii = 0   LRU 290,136   Belady 289,856     -280

With the port limit removed the excess vanishes and the sign flips. `l2_ii = 1`
admits one L2 request per cycle; under LRU every access misses and returns in 26
cycles, while under Belady 26% return in 2, so the served cores come back to the
port about thirteen times sooner and collide with the starved core that sets the
tile's time. The user raised this: Belady's floor should be LRU, and it is. What
was reported as the policy being worse is a resource effect a replacement policy
has no model of.

The -280 residual is the real policy effect, and it is small for the 88-of-88
starvation reason below, which stands unchanged.

**D8, 2026-08-31. The first explanation for this was wrong and is withdrawn.**
It said Belady helped non-critical cores while leaving the critical one alone.
Per-core accounting refutes that outright: all sixteen cores have exactly 4,864
L2 references and exactly 1,280 MIN hits, so there is no imbalance for the
barrier to expose. It was withdrawn after its own falsification test failed:
if the gain were real but barrier-absorbed for that reason, raising the DRAM
latency should let it break through, and instead Belady stayed marginally slower
at every latency from 8 to 2000 with the gap narrowing toward zero.

What IS established:

- The hit rates are correct. An offline Python simulation over the engine's own
  L2 reference sequence and its own line-to-set mapping (read from
  `--cache-state`) reproduces LRU 0.00%, MIN 26.32%, and 52.63% from 32 ways up,
  exactly. The engine's Belady is Belady.
- The accounting is exact. At `l2_miss_latency = 2000`, Belady saves 42,540,344
  cycles of channel stall and gains 42,405,704 cycles of barrier stall, agreeing
  to 0.3%. `stall_total` is 155,826,816 under LRU and 155,828,864 under Belady:
  the composition changes completely and the total does not move.
- The per-core-chain model holds for both LRU arms and fails only for Belady:
  LRU 16-way 4,864 misses/core gives 4,946 x latency, LRU 64-way 2,304 gives
  2,398 x, and Belady 16-way 3,536 gives 4,946 x, a 40% excess.

So Belady's misses are uniform in TOTAL per core and not uniform across the
BARRIER INTERVALS. The makespan is the sum over tiles of the slowest core while
MIN optimises the sum over the layer, and MIN is free to prefer a line needed in
tile 900 over one needed in tile 5. Associativity works because it removes misses
from every tile at once: 282,854 to 241,430, a 14.6% cut Belady cannot buy at any
hit rate.

**D9, 2026-08-31. D8's mechanism is now MEASURED, and it is sharper than the
inference.** No engine change was needed: under LRU 16-way every L2 access
misses, so the k-th L2 `fill` row in `--cache-state` is the k-th reference's
tile (77,824 against 77,824, exact). Joining that with the access log's core
gives the per-(core, tile) grid, and the offline `sum_t max_c` reproduces every
measured engine slope to the integer: 4,864 / 4,864 / 2,304 / 2,304. The
reconstruction also recovers 20,480 Belady hits, which is the engine's own
number, so the model is faithful.

Across the 88 tiles carrying L2 traffic:

    tiles where Belady lands ZERO hits on any core:             24 of 88
    tiles where Belady helps EVERY core (so the max must fall):   0 of 88
    tiles whose per-tile MAXIMUM is unchanged:                   88 of 88

The per-tile structure is BIMODAL rather than partial. In tile 7 some cores go
from 32 misses to zero, completely served, while others stay at 32, completely
starved; the spread is 32 and never an intermediate value. MIN keeps the 16
lines with the nearest next use in each set, and because the cores are
structurally symmetric while their lines sit at different points in the global
next-use ordering, "nearest 16" resolves to WHOLE CORES. The starved cores keep
exactly LRU's count, so `max_c` is exactly LRU's in all 88 tiles and the makespan
cannot move by one cycle.

Associativity works for the same reason MIN fails: 64 ways gives every core room
at once, all sixteen fall to 2,304 together, the ratio stays 1.000, and
`sum_t max_c` drops by the full factor.

**The general lesson, and it outranks the hit-rate result.** `sum of hits` and
`sum over tiles of max over cores of misses` are different objective functions,
and optimising the first can be worth exactly zero on the second. A replacement
policy for this machine must be scoped to a TILE and FAIR ACROSS CORES, which is
the opposite of a global optimiser.

Caveat on the high-latency arms: `l2_miss_latency = 2000` ran one iteration, not
to a fixpoint, and its hit count (21,248) differs from the converged run at
latency 24 (20,480) because the timing reordered the merge. B3 was verified at
the operating point only. The direction is unaffected; the exact high-latency
figures are softer.

**Against nocsim**, best cache arm versus `stage3_total_cycles`: V8 1.25x, V9
0.81x, R9 0.91x, R16 0.93x. Against Friday's 1.07 / 0.71 / 0.91 / 0.80,
associativity moves every layer and turns V8 into a clear win, but the cache is
still behind the NoC on three of four.

## Decisions the plan did not make

**D1, 2026-08-31. The reuse-distance logic lives here, and the engine gets a
dumper only.** The plan as first presented put a `ReuseHistogram` in
`include/wcache/` alongside `CacheStateLog` and `LineTrace`. The user asked for
today's implementation to sit in today's profiling folder, and the restructure
that makes that work is better on its own terms: the engine's diff shrinks to a
thin access-log writer with no Fenwick, no per-core histogram state and no CSV
schema of its own, and U1 becomes buildable and provable with zero engine
coupling. The cost is one intermediate file per run, at most 40 MB, which the
driver deletes after consuming it.

**D2, 2026-08-31. Each stack carries its own timestamp axis.** Sixteen private
L1s and one shared L2 are seventeen independent stacks. A shared axis would lay
down squares that a given core's markers can never occupy, so its prefix sums
would count other cores' references as distinct lines. The per-stack axis is
also what keeps each Fenwick small: about 312K squares at the widest core.

**D3, 2026-08-31. Growth is doubling with a full rebuild, not an in-place
append.** A Fenwick slot's coverage depends only on its index, so slots that
already exist stay correct across a resize, but a slot born at an index above
the old bound covers squares BELOW it and would be created holding zero where it
owes a sum. The O(n) rebuild cannot get that wrong and runs about log2(n) times
over a whole run. Measured cost at real scale: 5M references in 551 ms, so the
full 54.7M corpus is roughly 6 seconds.

**D4, 2026-08-31. The growth policy is checked structurally, by counting
rebuilds.** Growing by a constant instead of doubling leaves every answer
correct and turns the class into O(n^2), which at 55M references is not a slow
test but an unusable class. The mutation survived the first sweep for exactly
that reason. `StackDistance::rebuilds()` exists so the test can assert
`<= 16` for 5000 references, which kills it deterministically where a wall-clock
assertion would have been flaky.

## Mutation record, U1

Ten seds over `reuse_distance.h`, nine killed. The one survivor:

| Sed | Verdict |
|---|---|
| `prefix(t - 1)` to `prefix(t)` in the query | **allow**, semantically equivalent |

Position `t` has not yet had its marker placed when the query runs, and its cell
has never been written, so `prefix(t) == prefix(t - 1)` at that instant by
construction. The mutation changes no answer. `t - 1` stays in the source
because it states the window the definition asks for, rather than one that
happens to coincide with it.

**D5, 2026-08-31. The three questions U1 left open were answered by the implementer**, under
the user's instruction to run to completion without review stops. Access-log format: the
8-byte binary record, as recommended. Per-core L2 breakdown: left out under YAGNI, and the
mechanism question it would have answered is now recorded as the open item below. `hit_rate_at`
keeps cold references in the denominator, which is what makes V2 a comparison against a measured
hit rate rather than against a warm-cache idealisation.

**D6, 2026-08-31. V3 was rewritten after it failed, and the failure was the point.** As first
written, V3 compared a fully-associative PREDICTION against Friday's measured 16-way L2 and
called the disagreement a failure. Stack distance predicts a fully-associative LRU cache and
nothing else, so that comparison could never have passed and was the wrong check. V3 now
validates against fully-associative RUNS, where it agrees to better than 0.005%, and the
prediction-versus-swept-geometry comparison is reported as a FINDING rather than as a check.

## The finding

The 2026-08-28 artifact read the L2's flat 0.00% hit rate as a capacity cliff and prescribed a
4 MB L2. The measured distances refute that: the largest L2 reuse distance in the whole corpus is
3,071 lines, and the 512 KB L2 already held 8,192.

Holding capacity at 512 KB and varying only associativity settles it. 16-way gives 0.00%; 64-way
gives the full 52.63% ceiling and cuts 14.5% (V8), 12.7% (V9) and 13.4% (R16) off total cycles.
512 KB at 64-way and 4 MB at 16-way produce identical hit rates and identical cycle counts. R9 is
the control and moves not at all, correctly, since it has no L2 reuse to recover.

The L1 result runs the other way and is the same result: its 8-way array BEATS fully-associative
LRU by up to 5.36 points, because `khkw_split` spreads a reuse window across the L1's 32 sets well
enough that per-set LRU retains what global LRU would evict. The identical index, extended to the
L2's 512 sets, concentrates a window instead. The layout is correct at the level it was tuned
against and unexamined at the level below.

## D11, 2026-08-31: the four-layer sample was not representative

A scan of all 31 layers of both networks (12 vgg16 + 19 resnet19, `run_assoc31.py`,
`outputs/assoc31.csv`) at l2_assoc 16 vs 32, everything else pinned:

- **5 of 31 layers have any L2 reuse.** The L2 reuse ratio takes exactly two
  values across the corpus: 1.00 on 26 layers and 2.11 on 5. Nothing between.
- Where reuse exists the prediction from set-local distance 31 holds perfectly:
  0.00% -> 52.63% on all five, no exceptions, no partial cases.
- **End-to-end gain is 2.58%**, not the 12.7 to 14.5% the four-layer sample
  implied. Per layer the wins are 14 to 17%; they land on five layers holding a
  small share of total cycles.
- vgg16 1.0533x over 12 layers (2 benefit); resnet19 1.0192x over 19 (3 benefit).

Cross-checks: `layer_08_features_27` reproduces stage 4's V8 at 290,136 cycles
and `layer_09_layer2_0_conv2` reproduces R9 at 93,992, both to the cycle, so the
surviving `_n5` input traces are equivalent to the `_all` ones the 0823 study
used. 31 gurobi solves in 50 s, none infeasible; the scan itself 681 s.

**Why the sample was biased:** the 0823 study picked its four layers by where
their weight footprint sat against the L2 axis, i.e. selected for L2 pressure.
Three of the four have reuse 2.11.

Artifact: https://claude.ai/code/artifact/c399d99e-66cc-465e-9ece-1f1f574f6461

## D12, 2026-08-31: per-layer hit rates, reuse distance, reuse counts

`analyze31.py` -> `outputs/perlayer31.csv`, all 31 layers, same config at 16-way.

**The 2.11 ratio was two populations, not one.** The reuse-count distribution is
bimodal, and the average hid it:

    features_27, features_30, layer3_1_conv1, layer3_1_conv2
        28,672 lines touched 1x   (78%)
         8,192 lines touched 6x   (22%)   <- all the reuse
    layer3_0_conv2
        14,336 lines 1x,  4,096 lines 6x

28,672 + 8,192*6 = 77,824 refs over 36,864 lines = 2.11. The hot set is 8,192
lines, which is 512 KB, which is EXACTLY the L2 capacity; on layer3_0_conv2 it is
4,096 lines, exactly half. Whether that is a design coupling or a coincidence is
not something this measurement can say, and it is worth chasing.

**Reuse distance is identical in shape on all five layers.** Global: 47.37% at
d=1023 and 5.26% at d=3071. Set-local: a single spike at d=31 against 16 ways.
The set-local-31 result is now confirmed on all five, including the two never
previously measured.

**Footprint does not predict reuse.** Five vgg16 layers have identical 36,864-line
L2 footprints and split cleanly:

    features_34  L1 92.53%  reuse 1.00    <- worst L1 in the corpus, zero L2 help
    features_37  L1 94.55%  reuse 1.00
    features_40  L1 94.76%  reuse 1.00
    features_27  L1 97.00%  reuse 2.11
    features_30  L1 98.44%  reuse 2.11

Reuse follows the SCHEDULE, not layer size. And the three worst L1 hit rates in
the corpus belong to exactly the three layers the L2 cannot help, so the memory
system is weakest where neither level contributes anything.

L1 hit rate across the corpus: 92.53% to 99.97%.

## Open questions

0. **CLOSED by D9: the per-tile mechanism is measured, not inferred.** No
   `AccessRecord` change was needed after all.
0a. **REFINED by D12: why is the hot set always exactly 6 touches, and why is it
   exactly 8,192 lines = 512 KB = the L2 capacity?** The question is no longer
   about the 2.11 average, which is derived. It is about the 6 and the 8,192.
0a-2. **Why do features_34/37/40 have zero reuse while features_27/30 have six-fold
   reuse at an identical 36,864-line footprint?** The answer is in the schedule
   and would say which layers a shared L2 is for.
0b. **NEW: does the 512 KB L2 earn its area?** 26 of 31 layers would behave
   identically with no L2 at all. Nothing has been measured for this.
0c. **A tile-scoped, core-fair replacement policy is the open design
   question.** MIN shows the ceiling for a global optimiser is zero makespan
   gain; a policy that equalises misses ACROSS CORES WITHIN A TILE has headroom
   that MIN does not, because it attacks `max_c` directly. Nothing has been
   built or measured for this.
0c. **CLOSED by the W series: replacement is not the lever, in the usual sense.** Belady reaches half
   the ceiling at 16-way and ties LRU exactly at 64-way, so no policy work is
   worth doing at either geometry.
1. **The mechanism is a hypothesis, not a measurement.** That the reuse window lands in too few
   distinct L2 sets is what the data most obviously supports, and Friday's own capacity sweep
   backs it (1 MB and 2 MB at 16-way stay at 0.00%, so doubling the set count twice changes
   nothing, while quartering it via ways fixes everything). Confirming it means counting the
   distinct L2 sets touched inside one reuse window. The access log already holds what that needs.
2. **Re-cutting the L2 set index** may recover the win at 16-way and cost nothing, which is the
   result actually worth having.
3. **The prefetch verdict deserves a re-run.** Friday measured prefetching as a 37 to 90% penalty
   at 64-byte lines against an L2 returning 0.00%. With the L2 hitting, that arithmetic changes.
