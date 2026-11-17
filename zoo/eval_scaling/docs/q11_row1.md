# Q11, factual half: does nocsim expose a weight-only makespan? - REVIEWED, R1 ADOPTED

**Decision, 2026-11-16: R1, the ablation re-run, is ADOPTED.** The user
delegated the call to boss, who chose R1; implementation is dispatched as T72
with this file as the spec. The recommendation section below is the adopted
plan, not a proposal, and `plan.md` Q11 is closed accordingly. Everything
above that section is the finding that the decision rests on and is unchanged
by it.

**Question.** `plan.md` Q11 proposes putting all three series of row 1 on the
weight path, because the cache series is a weight-path-only measurement
(`docs/plans/2026-11-11-fig12-edp-plan.md:17-18`) while nocsim's
`total_cycles` is the whole node. The plan records that it could not determine
whether nocsim exposes a weight-only makespan. This file determines it.

**Answer: no, it does not, and no counter in the current output can be
combined into one.** A weight-only makespan is obtainable, but only by
re-running eventsim with the non-weight transfers suppressed, which needs
about thirty lines of instrumentation. The alternative is the fallback, whose
cost is stated at the end.

**Path convention.** Repo-relative from the `neuro_cache` root. Short forms:
`sim.py`, `combine.py`, `step_cycles.py` are `src/lays/nocsim/`;
`generator.py`, `transaction.py` are `src/lays/nocsim/core/`; `dram.py`,
`weight.py` are `src/lays/nocsim/transactions/`; `EventSim.h`,
`Transaction.h`, `main.cpp` are `src/lays/nocsim/eventsim/`; `run_case.py` is
`zoo/eval_scaling/`.

---

## (a) What exists

**Five cycle scalars, and they are categorized by operation, not by
variable.** eventsim accumulates per-transaction durations into four buckets
and takes the makespan separately (`EventSim.h:178-183`):

> `if (tc.op == 2) res.count_cycles += duration;`
> `else if (is_dram) res.dram_cycles += duration;`
> `else if (tc.op == 0) res.unicast_cycles += duration;`
> `else res.multicast_cycles += duration;`
> `res.total_cycles = std::max(res.total_cycles, finish);`

`main.cpp:68-73` prints exactly these five and nothing else. Two properties
matter here:

- **The four buckets are busy-cycle sums, not spans.** Transactions on
  different actors and links overlap in time, so the four do not sum to
  `total_cycles` and no arithmetic over them yields a span. Only
  `total_cycles` is a makespan, and it is a `max` over finish times.
- **`is_dram` is an endpoint test, not a stream test.** `dram_cycles` holds
  weight, psum and vmem DRAM legs together; `unicast_cycles` holds every
  on-chip point-to-point send of all three variables plus the K- and T-chain
  hops. Neither can be narrowed to the weight stream after the fact.

**Four per-variable counters, and they are analytic traffic rather than
simulated time** (`generator.py:68-71`): `unicast_hops`, `multicast_hops`,
`dram_cost`, `dram_bytes`, each a dict keyed by `weight`/`psum`/`vmem`,
printed one line per variable at `sim.py:370-376`. The chain already parses
all of `dram_cost_*` and `dram_bytes_*` (`run_case.py:264-281`).

`dram_cost` is the closest thing in the tree to a weight-only time, and it is
worth being precise about what it is not. At `generator.py:121`:

> `self.dram_cost[var_name] += math.ceil(num_packets * self.dram_latency)`

That is **DRAM port occupancy in cycles, summed analytically over every
weight leg**, independent of contention, dependencies and overlap. It is a
good diagnostic and a good sanity column. It is not a makespan, it is not what
eventsim measures, and it would not be comparable to cachesim's
`total_cycles`, which is a simulated span (`tick_base_total` plus
`stretch_cycles`).

**The variable identity does reach the transaction list, and then stops.**
`TC` carries `var_name` (`transaction.py:74`), but `format_csv` writes only
`tc_id, actor_id, op, size, src, dest, dep` (`transaction.py:111-127`, the
column list at `:118-125`), and
eventsim's parser skips the comment line that carries the annotation
(`Transaction.h:58`). So the simulator **never learns which stream a
transaction belongs to**. The identity is recoverable from the comment line
by naming convention - DRAM legs are labelled `dram_<i>__load_<var>` and
`dram_<i>__store_<var>` (`dram.py:74`, `:109`), NoC-level weight sends carry
the prefix `weight_<step>` (`combine.py:393`, built into the label at
`weight.py:105`), compute carries `mac_<step>` and `lif_<step>`
(`combine.py:447`, `:531`) - but that is a convention in label strings, not a
field, and a plan should not build a headline metric on it.

**Per-transaction finish times exist and are discarded.** `finish_time[i]` is
written for every transaction (`EventSim.h:173-174`) and never emitted. This
is what makes the instrumentation in (c) small: the simulator already knows
everything needed; it only lacks the stream label and an output.

## (b) The formula, if one wanted it from today's output

There is none. The two candidate constructions both fail, and they fail for
different reasons worth recording so neither is retried:

1. **`total_cycles - (psum and vmem contributions)`.** Not available: no
   counter isolates psum/vmem contributions, and even if one did, subtracting
   a busy-cycle sum from a makespan is not an operation.
2. **`count_cycles / nodes + dram_cost_weight`**, i.e. compute plus weight
   port occupancy as a cachesim analogue. This is the construction to reach
   for, since `dram_cost` is per-variable and the chain already collects it,
   so both grounds for rejecting it are given as lines rather than as a
   reading. **It ignores overlap by construction**: `generator.py:121`
   accumulates while the transaction list is built, with no reference to
   start times, link occupancy or dependencies, so it is an upper bound whose
   slack nothing in the tree measures. **And it omits the on-chip
   GB-to-node weight sends entirely**, because that accumulation sits inside
   the guard at `generator.py:120` -
   `if src == self.noc.dram_port or dest == self.noc.dram_port:` - so a send
   whose endpoints are both on-chip never reaches the counter. It would be a
   third quantity, not a weight-only makespan, and plotting it beside a
   simulated span would be the same category error Q11 exists to avoid.

## (c) Minimal instrumentation, and what it buys

**An ablation re-run is the only construction that gives a weight-only
makespan comparable in kind to cachesim's.** cachesim's `total_cycles` is the
weight path with the compute ticks as its baseline - `tick_base_total` plus
the stall cycles the memory system adds. The nocsim analogue is therefore a
run in which weight transfers and compute counts are kept and psum/vmem
transfers are free:

1. **Carry the stream into the CSV**: append `var_name` as an eighth column in
   `format_csv` (`transaction.py:118-127`). It is appended, so every existing
   reader keeps its column positions.
2. **Parse it**: one `std::string var` field in `Transaction`
   (`Transaction.h:16-25`) and one more field read in `parse_csv`.
3. **One flag**, `--weight-only`: when set, a transaction whose `var` is
   `psum` or `vmem` gets `duration = 0` while still enforcing its
   dependencies. **The dependency structure and the loop order are unchanged;
   only the durations of psum and vmem transfers become zero, so the weight
   path is re-timed against a machine where those transfers are free.** That
   re-timing is the mechanism: a zero-duration psum transfer frees its actor
   and its links at `start` rather than at `start + duration`
   (`EventSim.h:185-186`), so weight transactions behind it begin earlier and
   the makespan falls. `op == 2` (compute) and `var == "weight"` are
   untouched.
4. **Run eventsim twice per case** over the same already-written `tc.csv` -
   once normally, once with the flag. The transaction list is generated once;
   eventsim re-reads a file (`Transaction.h:50`), so the second run costs one
   extra invocation and no regeneration.

Then, counter-exact and in the plan's form:

> `weight_makespan(point, l) = total_cycles` of the `--weight-only` run
> `row1_spad(point) = 1 / sum_l weight_makespan(point, l)`
> `row1_cache(point) = 1 / sum_l total_cycles_cachesim(point, l)`
> `y_row1 = row1(point) / row1(single_x1)`

**The honest caveat, which belongs in the caption.** An ablation makespan is
a counterfactual machine - one whose psum and vmem traffic is free - not a
decomposition of the real makespan. Nothing is being attributed; a second
machine is being measured. That is exactly the right comparison here, because
**the cache series is also a weight-only machine**: both sides become "the
weight path, with compute, everything else free". But it means row 1 no longer
plots the same quantity as the scratchpad arms' own `total_cycles`, which the
caption and the CSV must both say. The real whole-node `total_cycles` stays in
the CSV for every point, so nothing is lost.

**Two gates it needs.**

- `weight_makespan <= total_cycles` for every row. Finish times are monotone
  in durations - `finish = start + duration` feeds `actor_free_time`,
  `link_free_time` and every dependent's start (`EventSim.h:173-176`) - so
  zeroing a duration cannot make any transaction finish later and the `max`
  cannot rise. **This gate therefore cannot fail on a correct
  implementation, which makes it an implementation check and not a statement
  about the machine**; a pass is evidence that the flag was wired correctly
  and nothing more.
- `weight_makespan >= count_cycles / nodes`, the same floor
  `run_case.py:282-285` and `run_case.py:467-470` assert it on the full and
  weight-only runs. It carries over unchanged because `count_cycles` accumulates only `tc.op == 2`
  (`EventSim.h:188`) and the flag leaves op-2 durations untouched.

## Recommendation, and the decision taken

**R1 - ADOPTED 2026-11-16**, the call delegated by the user to boss, and
dispatched to impl as T72 with this file as the spec: the four
instrumentation steps above, **both** gates, the extension of `plan.md`
section 4's step-5 assertion to cover **both** eventsim runs, and the S2
pilot timing the second invocation rather than assuming it free. R2 and R3
below are kept as the record of what was weighed, not as live options.

**Do the ablation (R1).** It is about thirty lines across one Python file and
two C++ headers, it needs no change to the scheduler, the generator, the trace
format or the harness's case list, and it keeps all three series on row 1 -
which is the half of the figure's claim the cache arm exists to carry.

**The fallback (R2), not adopted, with the cost that decided against it.** Row 1 carries the two
scratchpad series only; the cache series appears on row 2 alone. The figure
then shows that the cache organization avoids DRAM traffic and says nothing
about whether that converts into performance - and "converts capacity into
performance" is the sentence the figure is for. The paper would have to
promise traffic for the cache arm and performance for the scratchpad arms in
the same breath, which invites the reviewer question of whether the
performance number was omitted because it was unfavourable. R2 is workable and
honest; it is simply a weaker figure than the user asked for.

**Rejected (R3), plotting cachesim `total_cycles` directly against nocsim
`total_cycles`.** The two are not measurements of one quantity, and the ratio
has no name. This is the thing Q11 was raised to prevent.

## What this file could not determine

- **Whether the ablation's weight critical path is stable across capacities**
  the way the full run's is. The dedup argument of `plan.md` section 4 covers
  the full run; a `--weight-only` run is a different traversal of the same TC
  list, so the dedup still holds by the same argument (same schedule, same
  trace, same list), but nothing has been measured. The step-5 assertion
  should cover both runs.
- **The per-case cost of the second eventsim invocation.** eventsim is cheap
  relative to trace generation, but no eval_scaling S4 run has completed, so
  the S2 pilot should time both runs rather than assume the second is free.
