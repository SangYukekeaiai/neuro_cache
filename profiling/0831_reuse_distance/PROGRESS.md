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

## Open questions

1. **The mechanism is a hypothesis, not a measurement.** That the reuse window lands in too few
   distinct L2 sets is what the data most obviously supports, and Friday's own capacity sweep
   backs it (1 MB and 2 MB at 16-way stay at 0.00%, so doubling the set count twice changes
   nothing, while quartering it via ways fixes everything). Confirming it means counting the
   distinct L2 sets touched inside one reuse window. The access log already holds what that needs.
2. **Re-cutting the L2 set index** may recover the win at 16-way and cost nothing, which is the
   result actually worth having.
3. **The prefetch verdict deserves a re-run.** Friday measured prefetching as a 37 to 90% penalty
   at 64-byte lines against an L2 returning 0.00%. With the L2 hitting, that arithmetic changes.
