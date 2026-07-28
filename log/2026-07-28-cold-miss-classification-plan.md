# 2026-07-28 Cold-Miss Classification Plan

Status: DRAFT, awaiting review. Nothing in this document has been
implemented. This is a separate plan from
`log/2026-07-28-debug-pipeline-plan.md` (the pipeline rebuild plan,
unchanged) and depends on that plan's Part 1b (the per-burst hit-rate
fix) landing first.

## Goal

For every recorded MISS in the cache-replay simulation, determine
whether it is:

- a **cold / compulsory miss**: the first time this cache line's tag has
  ever been touched in the sample, so no replacement policy could have
  prevented it, or
- a **non-cold miss**: the line was previously resident and got evicted
  (by LRU) before this access, i.e. a capacity/conflict miss in the
  classic 3C sense.

This refines the per-burst hit-rate work into the standard compulsory /
capacity / conflict miss taxonomy, at the same per-burst-event
granularity already decided in the pipeline plan.

## Part A: Audit of the per-burst dedup decision

Before building on top of it, two review passes read the current
`profiling/0726/native/cache_sweep.cpp` implementation and the
`src/cachesim` reference against the plan doc's worked example. Findings:

1. **The granularity is "one distinct line per burst," not "one access
   per burst."** `cache_sweep.cpp:270-277` collapses consecutive
   same-tag elements, so a burst spanning a line boundary still yields
   two accesses. The header comment at `cache_sweep.cpp:17-25` overstates
   this as "exactly one hit/miss decision" per burst; fix the comment.

2. **The fix is a no-op for 3 of 4 swept `inner_dim` values.** Every
   arch's burst ranges over `cout` with `(kh,kw,cin)` fixed
   (`src/archmodels/*/address.py`), and `tag_for_element` only
   floor-divides `inner_dim` (`layout.py:95-97`). So for
   `inner_dim` in `{kh, kw, cin}`, every element is already a distinct
   line and dedup changes nothing; **only the `inner_dim=cout` rows of
   the existing 288-config grid actually moved.** This is not documented
   anywhere yet, and without it a reader will assume the whole grid
   moved. Consequence: `mean_hit_rate` is no longer comparable across
   the `inner_dim` axis of a single CSV, since the denominator now
   differs by roughly the burst width between rows.

3. **Consecutive-only dedup is correct today, by an invariant that isn't
   written down anywhere.** `read_sample` emits strictly ascending
   `cout` and `tag = value / line_size` is monotone, so same-tag
   elements inside one event are always contiguous. A future arch with a
   non-monotone burst expansion would silently break this. Worth an
   assertion, not just a comment.

4. **Feeding the deduped stream to the cache is provably harmless under
   LRU, but not under other policies.** Repeated immediate touches leave
   a line at MRU exactly where one touch does, so the miss set is
   identical before/after dedup, and
   `old_hits = new_hits + (n_elements - n_accesses)` exactly (confirmed
   by the worked example: 38 = 2 + (48-12)). That identity is a cheap
   regression test worth adding. But `config.py:31` declares fifo, lfu,
   random, and `input_activity` policies, and `input_activity` is
   described as this project's actual point (`policy.py:14-21`). Under
   LFU or random, dropping repeats changes frequency counts or victim
   draws. Decide now, before a second policy lands: the policy should
   see the deduped stream, not the raw one.

5. **Set indexing aliases distinct index tuples together.**
   `sum(tag_components) % num_sets` (`cache.py:49-60`,
   `cache_sweep.cpp:295`) means `(kh=2,kw=0)` and `(kh=0,kw=2)` map to
   the same set. Since associativity is swept across all 288 configs,
   every associativity conclusion drawn from the current results
   reflects this hashing artifact rather than the true weight layout.
   Recommend fixing this before trusting associativity comparisons: flatten
   the tuple into one linear element index, then index sets on
   `(addr / line_size) % num_sets`.

6. **`native_bridge.py` never passes `policy` to the native binary**;
   native hardcodes LRU (`main.cpp:51`) while the Python side raises on
   non-LRU policies. A silent Python/C++ mismatch waiting to happen once
   a second policy is wired up.

7. **`line_size_bytes` is an element count, not bytes** (`layout.py:96`,
   `config.py:76`). Was cosmetic when counting per element; now it alone
   decides whether a burst collapses to 1 access or several, so getting
   it wrong directly moves the headline hit rate.

8. **The Part 1b port, as scoped in the pipeline plan, is missing
   several things:**
   - The native file is `src/cachesim/native/main.cpp`, not
     `cache_replay.cpp` (the Makefile just names the built binary
     `cache_replay`). The pipeline plan names the wrong file.
   - `main.cpp:92` prints `hits total hit_rate` positionally, parsed by
     `native_bridge.py:63`; after the fix `total` changes meaning, and
     nothing currently flags that at the call site.
   - The fix can't live in `sweep.py` alone: `sweep.py:28-30` flattens
     all tiles' events before expansion, which destroys the event
     boundaries the dedup needs. `layout.py` needs to change too and
     isn't listed as a touched file.
   - `tag_histogram` (`layout.py:105-110`) stays per-element, so it will
     disagree with the deduped hit rate about what an access is, unless
     it's deduped too or the split is documented.
   - No tests exist anywhere in the repo (no `tests/`, no `test_*.py`),
     so the two diff scripts in Stage 1 are currently the only safety
     net.

9. **Reproducibility hazard**: `cache_sweep.py:122-124` skips any unit
   whose CSV already exists, and `merge_results` blindly concatenates.
   Re-running into an existing results dir after a semantics change
   silently merges pre-fix and post-fix rows into one CSV. Any results
   dir touched by this change needs to be deleted, not reused.

10. **Empty samples bias the mean**: `cache_sweep.cpp:234` skips empty
    samples with `continue`, but the aggregation still divides by
    `n_samples` at `:319`, so an empty sample contributes a hit rate of
    0.0 to the average. This needs a decision (drop from denominator, or
    exclude the unit) before any new identity checks are added on top,
    since they'd otherwise fail for the wrong reason.

None of these block the cold-miss work directly, but items 2, 5, 6, 9,
and 10 affect how much the existing `results_cout_test*` CSVs (and any
associativity conclusions drawn from them) can currently be trusted.

## Part B: Cold vs non-cold miss classification

### B0. The key simplification

With demand fetch, an empty cache at the start of each sample, and no
prefetch anywhere in the code:

    cold_misses(sample) == number of DISTINCT line tags in that
                            sample's deduped access stream

independent of cache type, associativity, size, or policy, since the
first touch of any tag is always a miss no matter what's already in the
cache. So `noncold_misses = total_misses - cold_misses`. This means the
feature needs **zero changes** to `cache.py`, `policy.py`, `cache.h`, or
`policy.h`; it's computed entirely in the replay driver, next to the
existing dedup loop.

### B1. Where it lands

Recommend fusing this with the still-open per-burst port (pipeline
plan's Part 1b), rather than doing it as a separate pass later, so the
same ~8 lines aren't touched twice. `cache_sweep.cpp` and
`src/cachesim/native/` currently share no headers and reimplement tag
formation, LRU, and set indexing independently, so this is also a
prompt to resolve which one is canonical (see the pipeline plan's
Part 1, and the scope question in B6 below) before adding a second
feature on top of the duplication.

### B2. Data structure

Both C++ paths already compress a tag to a dense int64 via a mixed-radix
pack over observed per-dim maxima (`layout.h:77-86`,
`cache_sweep.cpp:258`). Reuse that as a dense index into a bitmap:
`std::vector<uint64_t> seen(space/64 + 1)`, one shift and mask per test.
Measured against the actual traces, worst case is about 288 KiB per
sample (loas layer_19), versus the roughly 1-3 GB already allocated per
layer by the existing per-element tag arrays, so this is negligible
compared to what the sweep already does. An `unordered_set` would cost
more in both memory and hashing time; skip it. Python reference: a plain
`set` of the tag tuple, correctness over speed.

**Scope / lifetime**: "ever touched" means within one sample, matching
the cache's own lifetime (`sweep.py:22-24` already documents that a real
cache starts empty every sample). Reset the bitmap once per sample,
alongside allocating the fresh cache. A cross-sample "warm weights"
number would be a different metric with a different name; out of scope
here.

Update unconditionally on every deduped access via test-and-set (a hit
implies the bit is already set, so the write is a no-op on hits).

### B3. Interaction with the per-burst dedup

Classify at the granularity of the **deduped access**, not the original
expanded element, to stay consistent with how hits/misses are already
counted (Part A's decision). Example, one event
`(kh=1, kw=1, cin=0, cout 0..4)`:

- `line_size=4`: all 4 elements collapse to one tag, dedup keeps 1: this
  event contributes exactly 1 cold miss, not 4.
- `line_size=2`: collapses to 2 tags (`cout 0-1`, `cout 2-3`), dedup
  keeps 2: this event contributes 2 cold misses if both are first
  touches.

A tag reappearing later within the same event (e.g. A, B, A) cannot
occur today given the monotone `cout` scan noted in Part A item 3;
should be asserted, not just assumed, in the Python reference.

### B4. Output format

Append four columns to the existing sweep CSV schema
(`arch,workload,layer,cache_type,associativity,size_bytes,inner_dim,line_size,mean_hit_rate,n_samples`)
without changing any existing column:

- `mean_accesses`: mean deduped accesses per sample. Needed to recover
  raw counts from any of the rates below.
- `mean_cold_miss_rate`: mean of `cold / accesses`.
- `mean_noncold_miss_rate`: mean of `(misses - cold) / accesses`.
- `mean_cold_frac_of_misses`: mean of `cold / misses`, guarded to `0.0`
  when `misses == 0`. This is the number that actually answers "what
  fraction of misses could no replacement policy have prevented."

Per-row identity, exact up to float rounding:
`mean_hit_rate + mean_cold_miss_rate + mean_noncold_miss_rate == 1.0`.
(`mean_cold_frac_of_misses` does not compose linearly with the others;
don't check it against this identity.)

Compatibility notes: `plot_cout_hit_rate.py` reads by column name, so
appended columns won't break it, but `merge_results` blindly
concatenates, so a fresh `--results-dir` is needed for the first run
to avoid a ragged CSV mixing old and new schemas. `native_bridge.py:63`
parses `cache_replay`'s stdout positionally; append the new fields after
the existing three and switch to indexed/named parsing in the same
change.

### B5. Staged verification

Following the same tiny-trace-first philosophy as the pipeline plan's
Stage 0-3:

**Stage C0, hand-checked tiny trace.** Same config as the pipeline
plan's worked example (4-way fully-associative, `line_size=4`, 12
per-burst accesses). Classifying all 12:

| # | tag | result | class |
|---|---|---|---|
| 1-5 | A,B,C,D,E | MISS | cold |
| 6 | B | HIT | - |
| 7 | F | MISS (evict C) | cold |
| 8 | A | MISS (evict D) | non-cold |
| 9 | G | MISS (evict E) | cold |
| 10 | H | MISS (evict B) | cold |
| 11 | D | MISS (evict F) | non-cold |
| 12 | A | HIT | - |

Pass criterion, exact: `accesses=12, hits=2, misses=10, cold=8,
noncold=2`; rates `0.166667 / 0.666667 / 0.166667`;
`cold_frac_of_misses = 0.8`.

**Stage C0b, line-crossing case.** The example above can't distinguish
"cold counted per deduped access" from "cold counted per raw element,"
since `line_size=4` already collapses every event to one tag. Add the
same trace at `line_size=2` (8 lines instead of 4) and check only:
`accesses == 24`, `cold == 16`, `hits + 16 + noncold == 24`. This is the
check that would catch a per-element rather than per-deduped-access
implementation, which would report `accesses = 48`.

**Stage C1, one real layer, invariants only.** `loas / resnet19_T4_all /
layer_01`, one sample, across all swept configs:

- `cold_misses` must be identical across every config that shares the
  same `(line_size, inner_dim)`, regardless of cache size or
  associativity, since cold-ness doesn't depend on cache state (B0).
  This is the sharpest available check: a failure means cache state is
  leaking into the classification, or the bitmap isn't resetting per
  sample.
- `cold_misses` must equal an independently computed distinct-tag count
  from the raw JSON (Python, off the production path).
- `hits + cold + noncold == accesses` and `1 <= cold <= accesses` per
  row.

**Stage C2, Python/C++ parity.** Extend `debug/05_diff_hit_rate.py` to
diff the triple `(hits, cold, noncold)`, not just the rate. Exact
integer equality required. A mismatch on `cold` with matching `hits`
points at the dedup being applied on one side and not the other.

**Stage C3, full sweep**, into a fresh results directory. Assert the
sum-to-1.0 identity within `1e-6`, and that `cold_rate * accesses` is
constant across the swept sizes/associativities within each
`(arch, workload, layer, inner_dim, line_size)` group. Do not assert
monotonicity of `cold_frac_of_misses` in cache size; it's plausible but
not guaranteed given the set-indexing caveat in Part A item 5. Report
it, don't assert it.

## B6. Open decisions, needed before implementation starts

1. How to resolve the empty-sample bias (Part A item 10): drop empty
   samples from the denominator, or exclude the affected unit entirely.
   Needs settling first, or the Stage C3 identity check can fail for the
   wrong reason.
2. Whether to fold the pipeline plan's Part 1 scope (currently: archive
   `profiling/0726` to `dump/`) into promoting `cache_sweep.cpp`'s
   288-config-in-one-pass engine into `src/cachesim/` instead, since
   nothing else currently reimplements its speed trick, and this work
   would otherwise touch a file about to be archived.
3. Confirm "ever touched" is scoped per sample (matching cache
   lifetime), not across samples.
4. Confirm `cache_replay`'s stdout stays append-only and
   `native_bridge.py:63` is updated in the same change that changes the
   output format.
5. Whether `noncold_miss_rate` should carry an explicit caveat that it
   inherits the sum-tag set-indexing issue (Part A item 5): cold counts
   are immune to that issue (B0), but any conflict-vs-capacity
   conclusion drawn from non-cold misses is not.
6. This design gives a 2-way split (cold vs non-cold), not the full
   3-way compulsory/capacity/conflict model. Separating capacity from
   conflict needs a parallel fully-associative shadow cache of the same
   capacity, roughly doubling replay cost. Confirm 2-way is sufficient
   for now, or scope the shadow cache as a follow-on.

## Files this would touch (once approved)

`src/cachesim/native/layout.h`, `src/cachesim/native/main.cpp` (near
lines 81-92), `src/cachesim/sweep.py` (near lines 20-34, 48-56),
`src/cachesim/native_bridge.py` (near line 63), plus wherever
`cache_sweep.cpp`/`cache_sweep.py` end up per decision 2 above. No
changes needed to `cache.py`, `policy.py`, `cache.h`, `policy.h`, or
`config.py`.
