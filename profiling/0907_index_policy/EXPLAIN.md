# P1: LfuPolicy

Erasable. Covers increments P1 and P2 of PLAN.md section 5 only.

## What was added

`LfuPolicy`, a `ReplacementPolicy` with one `int64` reference count per slot in a
flat vector indexed by `SlotId`, the same shape `StampPolicy` and `BeladyPolicy`
use.

* `include/wcache/stamp_policy.h`: class `LfuPolicy`, declared after
  `BeladyPolicy` and before the `PolicyKind` enum.
* `src/stamp_policy.cpp`: `LfuPolicy::LfuPolicy`, `index_or_reject`, `on_hit`,
  `on_fill`, `on_invalidate`, `pick_victim`, placed before `make_policy`.

Behaviour: `on_fill` resets the slot's count to 0, `on_hit` increments it,
`on_invalidate` sets it to 0, and `pick_victim` returns the smallest count with
the smallest slot id as the tie-break, which is what satisfies the
order-independence contract in `policy.h:88-101`. No aging.

Nothing else moved: no `PolicyKind::LFU`, no `make_policy` arm, no `config.cpp`,
no `stats.cpp`, no test file. `LfuPolicy` is therefore compiled but not yet
reachable from a config.

## Verification

Run from `src/wcache/native`:

* `make` compiled clean under the pinned warning set (`-Wall -Wextra -Wpedantic
  -Wsign-conversion -Wconversion -Wshadow`), no warnings, both apps linked.
* `make test` exited 0. Every test binary reported `0 failures`, including the
  316-case compile-fail driver.

# P2: RripPolicy

## What was added

`RripPolicy`, SRRIP with a 2-bit RRPV, one `uint8` per slot in a flat vector
indexed by `SlotId`, the same shape `LfuPolicy` uses.

* `include/wcache/stamp_policy.h`: class `RripPolicy`, declared after
  `LfuPolicy` and before the `PolicyKind` enum.
* `src/stamp_policy.cpp`: constants `kRripMaxRrpv` (3) and `kRripInsertRrpv`
  (2) in a second anonymous-namespace block, then `RripPolicy::RripPolicy`,
  `index_or_reject`, `on_hit`, `on_fill`, `on_invalidate`, `pick_victim`,
  placed after the LFU section and before `make_policy`.

Behaviour: `on_fill` sets the RRPV to 2, `on_hit` to 0, `on_invalidate` to 3.
`pick_victim` ages in two passes: the first finds the largest RRPV among the
candidates, the second raises every candidate by the single delta `3 - that`,
so at least one lands on 3 and none exceeds it, and returns the smallest slot id
among those now at 3. Both the aging and the pick are functions of the candidate
SET rather than its order, which is what satisfies `policy.h:88-101`. M and the
insertion value stay compile-time constants.

Nothing else moved: no `PolicyKind::RRIP`, no `make_policy` arm, no
`config.cpp`, no `stats.cpp`, no test file. `RripPolicy` is compiled but not yet
reachable from a config.

## Verification

Same two commands from `src/wcache/native`:

* `make` compiled clean under the pinned warning set, no warnings, both apps
  linked.
* `make test` exited 0: 22 test binaries at `0 failures` plus the 316-case
  compile-fail driver at `0 failures`.

P3 (wiring: `PolicyKind::RRIP` and `LFU`, `make_policy`, `config.cpp`,
`stats.cpp`) is next.

# P3: wiring

Covers increment P3 of PLAN.md section 5 only. `LfuPolicy` and `RripPolicy` are
unchanged; this makes them reachable from a config.

## What was wired

Four sites, each following the arm `BELADY` already occupies:

* `include/wcache/stamp_policy.h:257-264`: `PolicyKind` gains `RRIP = 4` and
  `LFU = 5`. The enum is now one enumerator per line, since six no longer fit on
  one.
* `src/stamp_policy.cpp:303-304`: two `make_policy` arms constructing
  `RripPolicy` and `LfuPolicy`.
* `src/config.cpp:231-234`: two arms in the shared `policy` / `l2_policy`
  parser, so the names `rrip` and `lfu` resolve for both keys from one place.
* `src/stats.cpp:22-23`: the CSV spellings `rrip` and `lfu`, so a results row
  records the policy it ran.

No other file moved. No config knob was added for RRIP's M or its insertion
value, which stay compile-time constants, and no test file was written.

The section 5 invariant holds: `make_policy` still throws on
`PolicyKind::RANDOM`, and `rrip` and `lfu` parse to their own enumerators
without touching the RANDOM sentinel that means "`l2_policy` is unset, follow
`policy`".

## Verification

From `src/wcache/native`:

* `make` compiled clean under the pinned warning set, no warnings, both apps
  linked.
* `make test` exited 0: 22 test binaries at `0 failures` plus the 316-case
  compile-fail driver at `0 failures`. No existing test enumerates `PolicyKind`
  exhaustively in a way two new enumerators break.
* End to end on a minimal two-tile, two-core WCTS stream, `wcache_run` with
  `"policy": "rrip"` and again with `"policy": "lfu"` each exited 0 and wrote a
  CSV row whose `policy` column read `rrip` and `lfu` respectively. A config
  naming `bogus` is still refused with `unknown policy "bogus"`, and one naming
  `random` is still refused as a placeholder.

P4 (`test_stamp_policy.cpp`: hit, fill and invalidate for both, the RRPV aging
loop, and the permuted-candidate order-independence check) is next.

# P4: tests

Covers increment P4 of PLAN.md section 5 only. `tests/test_stamp_policy.cpp` is
the one file that moved; no implementation or wiring file was touched.

## What was added

Two state readers, then six cases, all appended after the Belady section.

The readers exist because neither policy exposes its per-slot state, which is
StampPolicy's rule and is kept: each takes its policy BY VALUE and reads the
state back through `pick_victim` answers on a copy, so the caller's policy is
untouched.

* `rrpv_of(RripPolicy, slot)` returns 0 to 3. `pick_victim` raises every
  candidate by the single delta `3 - the largest RRPV present`, so a probe slot
  already at 3 freezes the set and a probe at `3 - d` ages it by exactly `d`;
  the answer is then the smallest slot id at 3, so probing against a probe with
  a LARGER id reads "did the probed slot reach 3".
* `lfu_count_of(LfuPolicy, slot)` returns the reference count, by counting the
  hits a probe at slot 0 needs before it stops winning the pair.

The cases:

* `test_lfu_counts_references_per_line`: a fill resets the count to 0 (checked
  as a reset of the MOST used slot, so a no-op fails), a hit raises it, an
  invalidate clears it, and the victim is the minimum count. Also records the
  known ceiling that pure LFU never ages.
* `test_lfu_ties_go_to_the_smallest_slot_id`: the tie-break as a value, over
  three orderings, plus the check that it decides only ties.
* `test_rrip_inserts_below_the_maximum_and_ages_to_it`: the full aging loop. A
  never-filled slot is at 3, a fill is at 2, a hit is at 0; then four rounds of
  pick-and-refill, asserting the exact RRPV after each, showing the raise is 1
  when nothing is at the maximum and 0 when something is, and that one hit buys
  a line three evictions before it ages back to 2.
* `test_rrip_invalidate_pins_a_slot_at_the_maximum`: an invalidated slot is at
  3 and is taken while the live lines' RRPVs are asserted unchanged, and a
  refill returns it to 2.
* `test_rrip_ties_go_to_the_smallest_slot_id`: the tie-break as a value, in the
  raise-0 and raise-1 cases.
* `test_lfu_and_rrip_are_order_independent`: `expect_state_invariant`, which
  runs EVERY permutation of a five-candidate set against a FRESH policy each
  time and compares the victim AND the state the call left behind. The state
  half is what the existing `expect_invariant` does not carry and is what RRIP
  needs, since its `pick_victim` ages its candidates as a side effect. Three
  LFU states (all tied, all distinct, partial tie) and three RRIP states (all
  at 2 so the raise is 1, one at 3 so the raise is 0, and one hit line).

`make_policy` for the two new enumerators is deliberately not tested here: that
is P3 wiring, and P4's scope in PLAN.md section 5 is the two policies'
behaviour.

## The duplicate-candidate note, not pinned as a test

The P2 review noted that `RripPolicy::pick_victim` is not idempotent if the SAME
slot appears twice in one candidate vector: the raise would be applied twice and
the RRPV could pass 3. `LfuPolicy` is unaffected, since its `pick_victim` writes
nothing. It is left as this note rather than as a case, because `policy.h`
specifies a candidate SET, so a duplicate is caller error and the behaviour is
unspecified; asserting anything about it would pin an accident. No
implementation change was made for it.

## Verification

From `src/wcache/native`:

* `make` compiled clean under the pinned warning set, no warnings.
* `make test` exited 0: every binary and the 316-case compile-fail driver at
  `0 failures`.
* `test_stamp_policy` went from **150 checks** to **241 checks**, both at 0
  failures, so the new cases ran rather than merely compiled.
* Two deliberate breaks, each reverted and the file's checksum confirmed
  restored. Changing `kRripInsertRrpv` from 2 to 1 turned the binary red with 8
  failures. Making the aging skip the FIRST candidate turned it red with 17,
  including both halves of the new invariance check reporting by name: "the
  answer depends on candidate order" and "the state left behind depends on
  candidate order".

P1 to P4 are complete. The sweep (PLAN.md section 6,
`profiling/0907_index_policy/run_sweep.py`) is the remaining work.
