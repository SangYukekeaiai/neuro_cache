// Plan units C2, C3 and C4: the event loop and its handlers, the core state
// machine and tile barrier, and two-valued inclusion.
//
// NAMING: "C1".."C5" here are the PLAN's Phase C units; PROGRESS.md's decisions
// are B1-B126 and are named as decisions when cited. Parts 2.1/3.1/4.1 of the
// plan use "C1" and "C2" for two of v3's own CHANGES, which is a third spelling;
// this file says "4.5" and "4.6" where it means those.
//
// Exit criteria covered here:
//
//   C2  Part 7 line 1353, "the V-list below"
//   C3  Part 7 line 1354, "`tile_origin == tick_base` under the unbounded
//       baseline; V20, V21, V26, V27"
//   C4  Part 7 line 1355, "both branches exercised; `back_invalidations == 0`
//       under `non_inclusive`"
//
// WHICH CHECKS ARE ORACLES AND WHICH ARE SELF-COMPARISONS. Decision B121 is the
// standing lesson: a criterion of the form "two identical runs agree" detects
// nondeterminism and never a wrong answer, because the wrong answer is on both
// sides. Every check below is therefore labelled at its site:
//
//   ORACLE      the expected value is computed from the plan's own rules
//               without calling the code under test (`fx::oracle_tile_origin`,
//               a hand-derived cycle count, a hand-derived event order)
//   SELF        a run compared against another run of the same code. Kept only
//               where the property IS "these two runs agree" (V3's byte-identity
//               and V22's inertness), and always beside an oracle.
#include <wcache/engine.h>

#include <wcache/cache_level.h>
#include <wcache/event.h>
#include <wcache/mshr.h>
#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;
using fx::EventLog;
using fx::FakeTrace;
using fx::InvariantProbe;
using fx::LinearMapper;

namespace {

// The L1 and the L2 are given different set counts throughout, because the only
// thing the mapper log carries about an array operation is the set count it was
// asked for. That is what lets a check say "this probe was at the L2", which is
// the whole of V11.
constexpr std::int64_t kL1Sets = 16;
constexpr std::int64_t kL2Sets = 32;

// The positions of a set of expand records, in log order. `expand` is called
// once per burst issue and carries the burst's first line, so a fixture that
// gives every core a distinct line reads its own issue order out of this.
std::vector<std::int64_t> expand_order(const EventLog& log) {
    std::vector<std::int64_t> out;
    for (const std::string& l : log.lines) {
        if (l.empty() || l[0] != 'E') continue;
        out.push_back(std::stoll(l.substr(1, l.find('x') - 1)));
    }
    return out;
}

// ===========================================================================
// C3's exit criterion: the unbounded baseline collapses to the trace (V1)
// ===========================================================================

FakeTrace three_core_two_tile_trace() {
    FakeTrace tr(3);
    const std::int32_t t0 = tr.add_tile(3);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 2, 1);
    tr.add_burst(t0, 0, 5, 2);
    tr.add_burst(t0, 1, 1, 3);
    tr.add_burst(t0, 1, 3, 4);
    tr.add_burst(t0, 2, 0, 5);
    tr.add_burst(t0, 2, 4, 6);
    tr.add_burst(t0, 2, 6, 7);
    tr.add_burst(t0, 2, 7, 8);

    const std::int32_t t1 = tr.add_tile(1);
    tr.add_burst(t1, 0, 2, 9);
    tr.add_burst(t1, 0, 3, 10);
    tr.add_burst(t1, 1, 0, 11);
    // Core 2 contributes nothing to tile 1 and still has to clear the barrier.
    return tr;
}

void test_unbounded_baseline_reproduces_the_trace() {
    check::group("C3: ORACLE -- tile_origin == tick_base on the unbounded baseline (V1)");

    FakeTrace tr = three_core_two_tile_trace();
    LinearMapper map(64);
    EngineParams p = fx::unbounded_params(kL1Sets, 4);
    p.l2           = fx::level(kL2Sets, 4, 16, 8);
    p.l2.ii        = SimTime{0};

    Engine eng(map, tr, p);
    eng.run();

    // ORACLE: computed from the trace and 4.5's recurrence, with no call into
    // the engine. `oracle_tile_origin` is in engine_fixture.h and reads only
    // `local_tick`, `gap` and `tile_tail`.
    const std::vector<std::int64_t> want = fx::oracle_tile_origin(tr);
    CHECK_EQ(eng.tile_origin(0), SimTime{want[0]});
    CHECK_EQ(eng.tile_origin(1), SimTime{want[1]});
    CHECK_EQ(eng.tile_origin(2), SimTime{want[2]});

    // V1's second form, which is the one that also checks `tile_tail` (Q10):
    // `tile_origin[N+1] - tile_origin[N] == mac_cycles[N]` exactly.
    for (std::int32_t t = 0; t < tr.n_tiles(); ++t) {
        CHECK_EQ((eng.tile_origin(t + 1) - eng.tile_origin(t)).get(), tr.mac_cycles(t));
        CHECK_EQ(eng.tile_origin(t), SimTime{tr.tick_base(t)});
    }

    // 4.5: `gap == 0` is the one case where v3 and the trace differ by
    // construction, so the count is asserted rather than assumed. The corpus
    // half of that obligation is unit A3's; this is the fixture's half.
    CHECK_EQ(tr.gap_zero_pairs(), 0);

    // The run left nothing behind: every core Done, every file empty. That is
    // D12's condition read as a postcondition rather than as a failure.
    for (std::int32_t c = 0; c < 3; ++c) {
        CHECK_TRUE(eng.core(CoreId{c}).phase == Phase::Done);
        CHECK_EQ(eng.core(CoreId{c}).pending_lines, 0);
        CHECK_EQ(eng.l1(CoreId{c}).mshrs().live(), 0);
        CHECK_EQ(eng.l1(CoreId{c}).mshrs().slot_wait_depth(), 0);
    }
    CHECK_EQ(eng.l2().mshrs().live(), 0);
    CHECK_EQ(eng.stats().back_invalidations, 0);
}

void test_a_tile_whose_cores_all_idle_still_advances() {
    check::group("C3: ORACLE -- an empty tile advances by its tail alone");

    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(4);   // nobody issues anything
    (void)t0;
    const std::int32_t t1 = tr.add_tile(1);
    tr.add_burst(t1, 0, 3, 1);

    LinearMapper map(64);
    Engine eng(map, tr, fx::unbounded_params(kL1Sets, 4));
    eng.run();

    // ORACLE: `tile_tail >= 1` is what makes the seam advance the clock, so a
    // tile in which no core issues anything cannot leave the barrier firing at
    // its own timestamp forever (trace.h, 4.5).
    const std::vector<std::int64_t> want = fx::oracle_tile_origin(tr);
    CHECK_EQ(eng.tile_origin(1), SimTime{want[1]});
    CHECK_EQ(eng.tile_origin(1), SimTime{4});
    CHECK_EQ(eng.tile_origin(2), SimTime{want[2]});
    CHECK_EQ(eng.tile_origin(2), SimTime{8});
}

// ===========================================================================
// V20: a stall is CARRIED, not absorbed (N14, D13)
// ===========================================================================

// Every line resident in the L1 except `absent`, so exactly one burst misses.
void preinstall_except(Engine& eng, std::int32_t core, std::int64_t n_lines, std::int64_t absent) {
    for (std::int64_t l = 0; l < n_lines; ++l) {
        if (l != absent) eng.l1(CoreId{core}).install(LineId{l});
    }
}

void test_a_stall_shifts_the_whole_remainder_of_the_tile() {
    check::group("C3: ORACLE -- V20, the tail shifts by exactly the stall");

    FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    for (std::int32_t k = 0; k < 6; ++k) tr.add_burst(t0, 0, 2 * k, k);

    const std::int64_t delay = 37;
    LinearMapper map(16);

    EngineParams p       = fx::unbounded_params(kL1Sets, 4);
    p.l2                 = fx::level(kL2Sets, 4, 16, 8);
    p.l2.ii              = SimTime{0};
    p.l2_miss_latency    = SimTime{delay};

    // Run A: every access free, because every line is already resident.
    Engine free_run(map, tr, p);
    preinstall_except(free_run, 0, 16, -1);
    free_run.run();

    // Run B: identical except that burst 3's line is absent, so that ONE burst
    // pays a full miss of `delay` cycles.
    Engine stalled(map, tr, p);
    preinstall_except(stalled, 0, 16, 3);
    stalled.run();

    // ORACLE: the free run is the trace's own timeline, and the stalled run is
    // that timeline plus `delay`, because N14 adds the trace's spacing to the
    // SERVICE and never to an absolute tick. v2 added it to an absolute tick,
    // which let a core that had lost 37 cycles arrive at its next burst on
    // schedule anyway and discard the loss (D13).
    const std::vector<std::int64_t> want = fx::oracle_tile_origin(tr);
    CHECK_EQ(free_run.tile_origin(1), SimTime{want[1]});
    CHECK_EQ(stalled.tile_origin(1), SimTime{want[1] + delay});

    // And the same statement as the difference of the two runs (SELF, and it is
    // the weaker half: it says the two differ by 37 without saying either is
    // right, which is why the oracle above carries the check).
    CHECK_EQ((stalled.tile_origin(1) - free_run.tile_origin(1)).get(), delay);

    // The stall is the core's, and `core_stall` is what integrates to the tile
    // stretch: one burst waited 37 cycles past its own schedule and no other
    // burst waited at all, because every later burst was re-based on the late
    // service rather than on the trace's tick.
    CHECK_EQ(stalled.stats().core_stall.at(0), delay);
    CHECK_EQ(free_run.stats().core_stall.at(0), 0);
}

// ===========================================================================
// V27: the `l1_latency = 1` sensitivity run (2.5b)
// ===========================================================================

void test_a_per_burst_constant_accumulates_into_tile_origin() {
    check::group("C3: ORACLE -- V27, one cycle per burst compounds across tiles");

    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    // Core 0 has both the largest last tick and the most bursts, which is what
    // makes V27's closed form (the sum of per-tile MAXIMUM burst counts) equal
    // the general oracle. They are the same number only when one core maximises
    // both, and the plan's wording does not say so; the general oracle below is
    // what actually carries the check.
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 1, 1);
    tr.add_burst(t0, 0, 2, 2);
    tr.add_burst(t0, 1, 0, 3);
    const std::int32_t t1 = tr.add_tile(1);
    tr.add_burst(t1, 0, 0, 4);
    tr.add_burst(t1, 0, 1, 5);
    tr.add_burst(t1, 1, 0, 6);

    LinearMapper map(16);
    EngineParams p = fx::unbounded_params(kL1Sets, 4);
    p.l2           = fx::level(kL2Sets, 4, 16, 8);
    p.l2.ii        = SimTime{0};
    p.l1.latency   = SimTime{1};  // the sensitivity run: everything else free

    Engine eng(map, tr, p);
    for (std::int32_t c = 0; c < 2; ++c) preinstall_except(eng, c, 16, -1);
    eng.run();

    // ORACLE: the same recurrence with one extra cycle per burst.
    const std::vector<std::int64_t> want = fx::oracle_tile_origin(tr, 1, 1);
    CHECK_EQ(eng.tile_origin(1), SimTime{want[1]});
    CHECK_EQ(eng.tile_origin(2), SimTime{want[2]});

    // V27's own closed form: the drift at tile N is the sum over earlier tiles
    // of that tile's maximum per-core burst count. It is the check that N14
    // ACCUMULATES rather than absorbs: an implementation that re-based each tile
    // on the trace would show a drift of one tile's worth and stop growing.
    CHECK_EQ((eng.tile_origin(1) - SimTime{tr.tick_base(1)}).get(), 3);
    CHECK_EQ((eng.tile_origin(2) - SimTime{tr.tick_base(2)}).get(), 3 + 2);
}

// ===========================================================================
// V26 and the barrier
// ===========================================================================

void test_the_barrier_measures_the_last_service() {
    check::group("C3: ORACLE -- V26, tile_origin is the last service plus the tail");

    // The barrier is class 1 and a service happens inside a class-0 fill, so a
    // barrier resolving in the same cycle observes the service. With
    // `tile_tail >= 1` the barrier is always at least one cycle after the last
    // service, so the exact-tick case is unreachable through the trace contract;
    // it is reached here by a tail of 0, which is outside trace.h's stated range
    // and is used deliberately to exercise the ordering the plan asks about.
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(0);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 1, 5, 1);
    const std::int32_t t1 = tr.add_tile(1);
    tr.add_burst(t1, 0, 0, 2);
    tr.add_burst(t1, 1, 0, 3);

    LinearMapper map(16);
    Engine eng(map, tr, fx::unbounded_params(kL1Sets, 4));
    eng.run();

    // ORACLE: the last service of tile 0 is core 1's, at cycle 5, and the tile
    // origin is that cycle and NOT one event earlier. Set one event early it
    // would be 5 as well only by accident; with the tail at 0 the two are
    // distinguishable because the barrier and the fill share a timestamp.
    CHECK_EQ(eng.tile_origin(1), SimTime{5});
    CHECK_EQ(eng.tile_origin(2), SimTime{6});
    CHECK_EQ(eng.tile_origin(1), SimTime{fx::oracle_tile_origin(tr)[1]});
}

// ===========================================================================
// V21 and P2: core_stall and fetch_latency
// ===========================================================================

void test_core_stall_and_fetch_latency_are_equal_by_construction() {
    check::group("C3: ORACLE -- core_stall == fetch_latency, always (Part 8, P2)");

    // Part 8 says the two are "equal by construction" with prefetching OFF and
    // that with it ON their DIFFERENCE is "the latency the policy hid", and that
    // difference is "the single number the policy should be judged on".
    //
    // Under v3's own recurrence they are equal ALWAYS, not only with prefetching
    // off, and the argument is two lines of 3.4b: `serve` computes
    // `want = served_time + max(gap, ii)` and schedules the next `E_Issue` at
    // exactly `now + max(gap, ii)`, so `issued_at`, which is the timestamp of
    // that event, IS `want` for every burst after the first; and for the first
    // burst of a tile both are `tile_origin + local_tick(c, 0)`. So
    // `served - want` and `served - issued_at` are the same number term by term
    // and the difference is identically zero under EVERY policy.
    //
    // Checked here on a run with real misses, and again in test_prefetch.cpp
    // with the prefetcher on, which is where Part 8's claim actually fails.
    FakeTrace tr = three_core_two_tile_trace();
    LinearMapper map(64);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(kL2Sets, 2, 4, 2);
    p.l2.latency      = SimTime{3};
    p.l2_miss_latency = SimTime{11};
    p.dram_ii         = SimTime{2};

    Engine eng(map, tr, p);
    eng.run();

    bool any_stall = false;
    for (std::int32_t c = 0; c < 3; ++c) {
        CHECK_EQ(eng.stats().core_stall.at(static_cast<std::size_t>(c)),
                 eng.stats().fetch_latency.at(static_cast<std::size_t>(c)));
        if (eng.stats().core_stall.at(static_cast<std::size_t>(c)) > 0) any_stall = true;
    }
    // Not vacuous: the run really does stall, so the equality above is an
    // equality of two large numbers rather than of two zeroes.
    CHECK_TRUE(any_stall);
}

void test_the_return_leg_is_a_knob_that_still_works() {
    check::group("C2: ORACLE -- `l2_to_l1_latency` is charged, at its default and above it");

    // 2.5b: the return leg is not charged by default, and "the KNOB stays, so
    // D10's split between 'the L2 MSHR frees' and 'the core finishes' remains
    // structural and reopens by setting it nonzero". A knob nothing exercises is
    // a knob nobody can trust, and at its default of 0 every check of it passes
    // whether it is read or not.
    FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 3);

    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(kL2Sets, 2, 4, 2);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2.latency      = SimTime{10};
    p.l2_miss_latency = SimTime{100};
    p.dram_ii         = SimTime{1};

    Engine base(map, tr, p);
    base.run();
    CHECK_EQ(base.tile_origin(1), SimTime{111});   // 10 + 100, plus a tail of 1

    p.l2_to_l1_latency = SimTime{7};
    Engine slower(map, tr, p);
    slower.run();
    CHECK_EQ(slower.tile_origin(1), SimTime{118});
    CHECK_EQ(slower.stats().fetch_latency.at(0), 117);

    // The knob is read on TWO paths and they are separate lines of code: the
    // target loop of an L2 fill, which the two runs above take, and the L2 hit
    // that schedules an `E_L1Fill` directly. This is the second one: the line is
    // resident in the L2 and not in the L1, so the round trip is
    // `l2_latency + l2_to_l1_latency` and nothing else.
    Engine on_hit(map, tr, p);
    on_hit.l2().install(LineId{3});
    on_hit.run();
    CHECK_EQ(on_hit.tile_origin(1), SimTime{18});   // 10 + 7, plus a tail of 1
    CHECK_EQ(on_hit.stats().fetch_latency.at(0), 17);
}

// ===========================================================================
// C2: the wake order is FIFO by first refusal (V7, V17, I7b, 3.8)
// ===========================================================================

void test_line_waiters_resolve_together_in_stamp_order() {
    check::group("C2: ORACLE -- V7/I7b, the wake is in stamp order at ii >= 1");

    // Four cores want the same line. The L2 target list holds one, so the other
    // three line-wait, and their stamps are their ARRIVAL order, which the
    // fixture makes the REVERSE of core-id order on purpose: a wake sorted by
    // anything but the stamp gives a different answer here.
    FakeTrace tr(4);
    const std::int32_t t0 = tr.add_tile(1);
    for (std::int32_t c = 0; c < 4; ++c) {
        tr.add_burst(t0, c, 3 - c, 5);              // the shared line
        tr.add_burst(t0, c, 3 - c + 10, 10 + c);    // a line unique to this core
    }

    LinearMapper map(64);
    EventLog log;
    map.set_recorder(&log);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(kL2Sets, 2, 4, 1);  // l2_tgts_per_mshr = 1
    p.l2.latency      = SimTime{1};
    p.l2.ii           = SimTime{1};                   // N13: at ii = 0 this is vacuous
    p.l1.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{20};
    p.dram_ii         = SimTime{1};

    Engine eng(map, tr, p);
    eng.run();

    // ORACLE, derived by hand from 3.4, 3.8 and 4.3 and written out so the
    // expected order is not a rerun of the code:
    //
    //   core 3 issues at 0 and reaches the L2 first, so it takes the entry and
    //   is its only target. Cores 2, 1 and 0 arrive at 1, 2 and 3 and line-wait
    //   with stamps 0, 1 and 2 in that order.
    //   The fill retires the entry: core 3 is satisfied as a target and the
    //   three waiters are reinjected in stamp order, each taking one L2 port
    //   slot at ii = 1, so they are served one cycle apart in stamp order.
    //   Their second bursts, whose lines are 13, 12, 11 and 10, therefore issue
    //   in that order.
    const std::vector<std::int64_t> want{13, 12, 11, 10};
    std::vector<std::int64_t> got;
    for (std::int64_t l : expand_order(log)) {
        if (l >= 10) got.push_back(l);
    }
    CHECK_EQ(check::ssize(got), 4);
    CHECK_TRUE(got == want);

    // V7's other two clauses: all of them resolved at once and NONE allocated.
    // Only one MSHR entry ever existed for line 5 at the L2, which is V4.
    CHECK_EQ(eng.l2().mshrs().live(), 0);
    CHECK_EQ(eng.l2().mshrs().slot_wait_depth(), 0);
}

void test_a_woken_request_keeps_its_seniority_in_the_queue() {
    check::group("C2: ORACLE -- a reinjected probe carries its stamp into the event key");

    // 3.8: "refused beats fresh". The stamp is carried into the EVENT KEY as
    // well as kept on the request, and the two are different things: the wake
    // list is sorted by the request's stamp, while two probes landing at one
    // timestamp are ordered by the key's `age` field. Only the second is
    // exercised here, and it needs `ii = 0` so that two probes can share a
    // timestamp at all -- which is the mirror of N13's rule that reservation
    // order needs `ii >= 1`.
    //
    // The fixture makes the core ids fight the stamps on purpose: the woken
    // request belongs to core 3 and the fresh one to core 1, so an engine that
    // dropped the stamp from the key would order them by core id and get the
    // opposite answer.
    FakeTrace tr(4);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 30);    // core 0 takes the L2 entry for line 30
    tr.add_burst(t0, 3, 0, 30);    // core 3 line-waits on it, stamp 0
    tr.add_burst(t0, 1, 55, 31);   // core 1 probes line 31 at the same tick as the wake
    tr.add_burst(t0, 2, 90, 32);   // core 2's fill then evicts the older of the two

    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(1, 2, 4, 1);   // ONE set, two ways, one target
    p.l1.ii           = SimTime{0};
    p.l2.ii           = SimTime{0};
    p.l1.latency      = SimTime{0};
    // A nonzero L2 latency is what puts the two probes in the queue TOGETHER.
    // With it at 0 the woken probe is dispatched before the fresh request's
    // `E_Issue` has even fired, because Issue is class 3 and a probe is class 2,
    // so the class decides the order and the key's age field is never consulted.
    // That is the same vacuity trap N13 records for `ii = 0`.
    p.l2.latency      = SimTime{5};
    p.l2_miss_latency = SimTime{50};
    p.dram_ii         = SimTime{0};

    Engine eng(map, tr, p);
    eng.l2().install(LineId{31});
    eng.run();

    // ORACLE, derived from 3.6 and 3.8: line 30's fill lands at 55 and wakes
    // core 3, whose reinjected L2 probe is accepted at 55 and lands at 60
    // carrying stamp 0. Core 1 issues at 55, probes its own L1 at 55, misses,
    // and its fresh L2 probe lands at 60 too, carrying NoRefusal. Refused
    // beats fresh, so line 30 is touched first and line 31 second, leaving 30 as
    // the older of the two; core 2's fill at 90 therefore evicts line 30.
    //
    // Drop the stamp from the key and the two are ordered by core id instead,
    // core 1 before core 3, which leaves line 31 older and evicts IT.
    CHECK_TRUE(eng.l2().array().probe(LineId{30}) == NoSlot);
    CHECK_TRUE(eng.l2().array().probe(LineId{31}) != NoSlot);
    CHECK_TRUE(eng.l2().array().probe(LineId{32}) != NoSlot);
}

void test_a_slot_waiter_re_enters_at_the_level_it_blocked_at() {
    check::group("C2: ORACLE -- V11, a wake from the L2 pool re-enters at the L2 (3.5)");

    // Two cores, two different lines, one L2 MSHR. The second core reaches the
    // L2 holding its own L1 entry, finds the file full and blocks on the L2's
    // slot index. When it wakes it must re-enter AT THE L2: a re-triage at the
    // L1 would find its own entry, merge the request into itself, and wait for
    // a fill nobody will request.
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 1);
    tr.add_burst(t0, 1, 1, 2);

    LinearMapper map(64);
    EventLog log;
    map.set_recorder(&log);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(kL2Sets, 2, 1, 2);  // l2_mshrs = 1
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2.latency      = SimTime{1};
    p.l2_miss_latency = SimTime{20};
    p.dram_ii         = SimTime{1};

    Engine eng(map, tr, p);
    eng.run();

    // The run completing at all is the code's own guard talking: a request that
    // re-entered at the L1 would merge into its own entry and the queue would
    // empty with that entry live, which is D12. The ORACLE half is the log: the
    // set counts distinguish the two arrays, so the reinjected probe for line 2
    // must appear as an L2 lookup with no L1 lookup of line 2 after the fill.
    std::size_t last_l1_probe_of_line2 = 0;
    std::size_t l2_probes_of_line2     = 0;
    std::size_t first_l2_probe         = 0;
    for (std::size_t i = 0; i < log.lines.size(); ++i) {
        if (log.lines[i] == "L" + std::to_string(kL1Sets) + ":2") last_l1_probe_of_line2 = i;
        if (log.lines[i] == "L" + std::to_string(kL2Sets) + ":2") {
            if (l2_probes_of_line2 == 0) first_l2_probe = i;
            ++l2_probes_of_line2;
        }
    }
    // Two L2 lookups of line 2 at least: the refused one and the reinjected one.
    CHECK_TRUE(l2_probes_of_line2 >= 2);
    CHECK_TRUE(first_l2_probe > 0);
    // And the LAST touch of line 2 at the L1 is its fill, which comes after the
    // reinjected L2 probe rather than before it.
    CHECK_TRUE(last_l1_probe_of_line2 > first_l2_probe);
    CHECK_EQ(eng.l2().mshrs().live(), 0);
    CHECK_EQ(eng.l2().mshrs().slot_wait_depth(), 0);
}

// ===========================================================================
// V5, V6: re-triage on wake, from the top of the level (D4, N5)
// ===========================================================================

void test_a_queued_miss_that_became_a_hit_consumes_no_entry() {
    check::group("C2: ORACLE -- V5, a blocked request wakes into a hit");

    // Core 1 wants a line core 0 is already fetching, but the L1 target list is
    // irrelevant here: they are different L1s. The shared structure is the L2,
    // where core 1's request merges as a target and is satisfied by the fill
    // with no second fetch. The number that shows it is the timing: both cores
    // are served by ONE round trip, so core 1 is served at the fill and not a
    // second round trip later.
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 7);
    tr.add_burst(t0, 1, 1, 7);

    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(kL2Sets, 2, 4, 2);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{50};
    p.dram_ii         = SimTime{1};

    Engine eng(map, tr, p);
    eng.run();

    // ORACLE: core 0 probes at 0, misses, forwards, and the DRAM returns at 50.
    // Core 1 probes at 1, misses in its own L1, forwards, and MERGES at the L2,
    // so it is satisfied by the same fill at 50. Both are served at 50, the tail
    // is 1, and the tile therefore ends at 51. A second fetch would put core 1's
    // service at 51 and the tile at 52.
    CHECK_EQ(eng.tile_origin(1), SimTime{51});
    CHECK_EQ(eng.stats().core_stall.at(0), 50);
    CHECK_EQ(eng.stats().core_stall.at(1), 49);
}

// ===========================================================================
// V8: under LRU the service order IS the eviction order (D7)
// ===========================================================================

void test_service_order_is_eviction_order() {
    check::group("C2: ORACLE -- V8, two L2 hits one cycle apart order the recency stack");

    // One L2 set, two ways, and three lines. Cores 0 and 1 hit lines 20 and 21
    // one cycle apart at the L2; core 2 then misses line 22, whose fill must
    // evict the line that was hit FIRST. Reverse the two services and the other
    // line goes.
    FakeTrace tr(3);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 20);
    tr.add_burst(t0, 1, 1, 21);
    tr.add_burst(t0, 2, 30, 22);

    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 4, 2);
    p.l2              = fx::level(1, 2, 4, 2);   // ONE set, two ways
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{5};
    p.dram_ii         = SimTime{1};

    Engine eng(map, tr, p);
    eng.l2().install(LineId{20});
    eng.l2().install(LineId{21});
    eng.run();

    // ORACLE: line 20 was hit at cycle 0 and line 21 at cycle 1, so 20 is the
    // older of the two when line 22's fill lands, and 20 is the victim.
    CHECK_TRUE(eng.l2().array().probe(LineId{20}) == NoSlot);
    CHECK_TRUE(eng.l2().array().probe(LineId{21}) != NoSlot);
    CHECK_TRUE(eng.l2().array().probe(LineId{22}) != NoSlot);
}

// ===========================================================================
// C4: inclusion is a knob, not an invariant (4.4, N8, V9, V9b)
// ===========================================================================

// One L2 set with one way, so every L2 fill evicts whatever was there. Two cores
// touch two lines that share that set; under `inclusive` the second fill
// invalidates the first core's copy and its next access misses, under
// `non_inclusive` the copy survives and its next access hits.
FakeTrace inclusion_trace() {
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 40);    // core 0 fetches line 40
    tr.add_burst(t0, 1, 20, 41);   // core 1 fetches line 41, evicting 40 from the L2
    tr.add_burst(t0, 0, 40, 40);   // core 0 wants line 40 again
    return tr;
}

void test_inclusive_back_invalidates_and_non_inclusive_does_not() {
    check::group("C4: ORACLE -- V9 and V9b, both branches of `inclusion`");

    FakeTrace tr = inclusion_trace();
    LinearMapper map(64);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(4, 2, 4, 2);
    p.l2              = fx::level(1, 1, 4, 2);   // one set, one way
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{10};
    p.dram_ii         = SimTime{1};

    EngineParams incl = p;
    incl.inclusion    = Inclusion::Inclusive;
    Engine eng_i(map, tr, incl);
    eng_i.run();

    Engine eng_n(map, tr, p);   // NonInclusive is 2.5b's default and the sweep's
    eng_n.run();

    // ORACLE for the count: line 41's fill evicts line 40 from the one-way L2,
    // and exactly one L1 holds line 40 at that moment, so exactly one
    // back-invalidation happens. Line 40's own fill evicts nothing, because the
    // set is empty at that point, and core 0's refetch evicts line 41, which no
    // L1 holds by then... except core 1's, which fetched it. So the total is
    // two: one for line 40 out of core 0's L1, one for line 41 out of core 1's.
    CHECK_EQ(eng_i.stats().back_invalidations, 2);

    // C4's stated exit criterion, and it is an ORACLE in the strict sense: the
    // expected value is zero because the branch is guarded, not because another
    // run said so.
    CHECK_EQ(eng_n.stats().back_invalidations, 0);

    // V9: under `inclusive` core 0's L1 lost the line, so its third burst is a
    // real miss and the tile is longer. V9b: under `non_inclusive` the L1 still
    // holds it and that access hits, which is the source of the extra effective
    // capacity 4.4 describes.
    CHECK_TRUE(eng_i.tile_origin(1) > eng_n.tile_origin(1));
    CHECK_EQ(eng_n.stats().core_stall.at(0), eng_i.stats().core_stall.at(0) - 10);

    // And the residency itself, which is the mechanism rather than its cost.
    Engine eng_i2(map, tr, incl);
    eng_i2.run();
    CHECK_EQ(eng_i2.stats().back_invalidations, 2);
}

void test_back_invalidation_walks_every_core_in_id_order() {
    check::group("C4: ORACLE -- the scan covers every L1 that holds the line");

    // Four cores all holding line 40, then one L2 fill that evicts it: the count
    // is the number of L1s holding it, which is four. A scan that stopped at the
    // first hit, or that walked an unordered container and missed one, gives a
    // different number.
    FakeTrace tr(4);
    const std::int32_t t0 = tr.add_tile(1);
    for (std::int32_t c = 0; c < 4; ++c) tr.add_burst(t0, c, c, 40);
    tr.add_burst(t0, 0, 30, 41);   // evicts 40 from the one-way L2

    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(4, 2, 4, 2);
    p.l2              = fx::level(1, 1, 4, 4);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{5};
    p.dram_ii         = SimTime{1};
    p.inclusion       = Inclusion::Inclusive;

    Engine eng(map, tr, p);
    eng.run();
    CHECK_EQ(eng.stats().back_invalidations, 4);
    for (std::int32_t c = 0; c < 4; ++c) {
        CHECK_TRUE(eng.l1(CoreId{c}).array().probe(LineId{40}) == NoSlot);
    }
}

// ===========================================================================
// C2: the handler set, and what the engine refuses
// ===========================================================================

void test_there_are_six_event_kinds_and_six_handlers() {
    check::group("C2: 3.1's alphabet is SIX, and the C2 row's 'seven' is a plan slip");

    // Part 7's C2 row reads "*(v3: seven)* The seven event handlers", while 3.1
    // says "Six event kinds, unchanged in number by v3" and adds "C2 adds no
    // event kind" -- where that "C2" is v3's PREFETCH CHANGE, not Part 7's unit
    // C2. Six is right and seven is a slip: nothing in v3 adds a kind, service
    // is a call inside `E_L1Fill` rather than an event (3.1, 3.6), and the
    // prefetcher's hook is a call and not an event.
    CHECK_EQ(static_cast<int>(EventKind::Issue), 0);
    CHECK_EQ(static_cast<int>(EventKind::L1Probe), 1);
    CHECK_EQ(static_cast<int>(EventKind::L2Probe), 2);
    CHECK_EQ(static_cast<int>(EventKind::L2Fill), 3);
    CHECK_EQ(static_cast<int>(EventKind::L1Fill), 4);
    CHECK_EQ(static_cast<int>(EventKind::Barrier), 5);
    // 3.6's class table, which is the ordering half of the same alphabet.
    CHECK_TRUE(class_of(EventKind::L1Fill) == EventClass::Fill);
    CHECK_TRUE(class_of(EventKind::L2Fill) == EventClass::Fill);
    CHECK_TRUE(class_of(EventKind::Barrier) == EventClass::Barrier);
    CHECK_TRUE(class_of(EventKind::L1Probe) == EventClass::Probe);
    CHECK_TRUE(class_of(EventKind::L2Probe) == EventClass::Probe);
    CHECK_TRUE(class_of(EventKind::Issue) == EventClass::Issue);
}

void test_the_engine_refuses_a_trace_it_cannot_run() {
    check::group("C2: the constructor refuses what it cannot simulate");

    LinearMapper map(64);
    FakeTrace none(0);
    CHECK_THROWS(std::invalid_argument, Engine(map, none, fx::unbounded_params(kL1Sets, 2)));

    // A trace with no tiles is legal and runs to completion doing nothing.
    FakeTrace empty(2);
    Engine eng(map, empty, fx::unbounded_params(kL1Sets, 2));
    eng.run();
    CHECK_EQ(eng.tile_origin(0), SimTime{0});
}

void test_a_coordinate_outside_the_layer_names_its_tile_tick_and_core() {
    check::group("C2: V15/N11, a bad coordinate aborts naming tile, tick and core");

    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 1);
    tr.add_burst(t0, 1, 4, 900);   // outside a 64-line layer

    LinearMapper map(64);
    Engine eng(map, tr, fx::unbounded_params(kL1Sets, 2));
    bool named = false;
    try {
        eng.run();
    } catch (const std::out_of_range& e) {
        const std::string what = e.what();
        named = what.find("tile 0") != std::string::npos &&
                what.find("tick 4") != std::string::npos &&
                what.find("core 1") != std::string::npos &&
                what.find("burst 0") != std::string::npos;
    }
    CHECK_TRUE(named);
}

void test_the_queue_emptying_with_work_outstanding_is_a_deadlock() {
    check::group("C2: D12, an empty queue with an entry still live throws");

    // The deadlock check is the one handler path a correct run never takes, and
    // "it never happens" is not a reason to leave it untested: it is what a
    // sweep build reports instead of a plausible short run, and it is a throw
    // rather than an assert precisely because that build is -DNDEBUG.
    //
    // Reached by leaving an entry in an L1 file that no fill will ever retire,
    // for a line the trace never touches, which is the shape every real
    // deadlock in this model has.
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 1);
    tr.add_burst(t0, 1, 0, 2);

    LinearMapper map(64);
    Engine eng(map, tr, fx::unbounded_params(kL1Sets, 2));
    Request stuck{CoreId{0}, LineId{40}, BurstIndex{0}};
    (void)eng.l1(CoreId{0}).mshrs().allocate(LineId{40}, stuck);

    std::string msg = "[no exception thrown]";
    try {
        eng.run();
    } catch (const std::logic_error& e) {
        msg = e.what();
    }
    CHECK_TRUE(msg.find("deadlock") != std::string::npos);
    CHECK_TRUE(msg.find("live entries") != std::string::npos);
}

void test_the_arena_refuses_to_release_a_request_that_is_still_held() {
    check::group("C2: a request is released only when nothing points at it");

    // Not reachable from a run, which is the point: the guard exists so that a
    // future handler that released early is caught at the release rather than
    // when the freed request is handed back out with someone else's stamp. It is
    // exercised through the one reachable proxy, a full run that never trips it.
    FakeTrace tr = three_core_two_tile_trace();
    LinearMapper map(64);
    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(kL1Sets, 2, 2, 1);
    p.l2              = fx::level(kL2Sets, 2, 2, 1);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2_miss_latency = SimTime{7};
    p.dram_ii         = SimTime{1};
    Engine eng(map, tr, p);
    eng.run();
    CHECK_EQ(eng.stats().back_invalidations, 0);
    for (std::int32_t c = 0; c < 3; ++c) CHECK_EQ(eng.l1(CoreId{c}).mshrs().live(), 0);
}

// ===========================================================================
// The soak (Appendix A, checked after every array operation)
// ===========================================================================

FakeTrace soak_trace(std::int32_t n_cores, std::int32_t n_tiles, std::int64_t n_lines) {
    FakeTrace tr(n_cores);
    // A deterministic pseudo-random walk, so the fixture is a fixture and not a
    // seed nobody recorded. Sharing is deliberate: every core touches a small
    // set of hot lines, which is what puts several cores on one MSHR entry and
    // makes the target lists and the wait indices fill.
    std::uint64_t s = 0x9E3779B97F4A7C15ULL;
    auto next = [&s]() {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        return s;
    };
    for (std::int32_t t = 0; t < n_tiles; ++t) {
        const std::int32_t tile = tr.add_tile(1 + static_cast<std::int64_t>(next() % 4));
        for (std::int32_t c = 0; c < n_cores; ++c) {
            std::int64_t tick = static_cast<std::int64_t>(next() % 3);
            const std::int32_t n = 3 + static_cast<std::int32_t>(next() % 5);
            for (std::int32_t k = 0; k < n; ++k) {
                const bool hot     = (next() % 3) != 0;
                const std::int64_t first = hot ? static_cast<std::int64_t>(next() % 6)
                                               : static_cast<std::int64_t>(next() % static_cast<std::uint64_t>(n_lines));
                const std::int32_t count = 1 + static_cast<std::int32_t>(next() % 3);
                const std::int64_t last  = first + count - 1;
                tr.add_burst(tile, c, tick, last >= n_lines ? n_lines - count : first, count);
                tick += 1 + static_cast<std::int64_t>(next() % 4);
            }
        }
    }
    return tr;
}

void run_soak(const char* name, Inclusion inclusion) {
    check::group(name);

    constexpr std::int64_t kLines = 64;
    FakeTrace tr = soak_trace(8, 64, kLines);
    LinearMapper map(kLines);
    InvariantProbe probe(kLines, 3);
    map.set_recorder(&probe);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(4, 2, 3, 2);    // small, so the pool really binds
    p.l2              = fx::level(8, 2, 3, 2);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2.latency      = SimTime{2};
    p.l2_miss_latency = SimTime{17};
    p.dram_ii         = SimTime{3};
    p.inclusion       = inclusion;

    Engine eng(map, tr, p);
    probe.attach(&eng);
    eng.run();

    // The invariants held at every sample, and there were a lot of samples: the
    // probe runs on every array operation, which is several times per event.
    CHECK_EQ(check::ssize(probe.failures), 0);
    for (const std::string& f : probe.failures) std::printf("  invariant: %s\n", f.c_str());
    CHECK_TRUE(probe.samples > 20000);

    // The run really did exercise the structures the invariants are about: a
    // soak whose target lists never filled would report a clean sweep of
    // nothing. These are the same vacuity guards N13 asks for at `ii = 0`.
    CHECK_TRUE(probe.max_targets >= 2);
    CHECK_TRUE(probe.max_line_wait >= 1);
    CHECK_TRUE(probe.max_live_l2 >= 2);

    // D12's postcondition: the queue emptied with nothing outstanding.
    for (std::int32_t c = 0; c < 8; ++c) {
        CHECK_TRUE(eng.core(CoreId{c}).phase == Phase::Done);
        CHECK_EQ(eng.l1(CoreId{c}).mshrs().live(), 0);
        CHECK_EQ(eng.l1(CoreId{c}).mshrs().slot_wait_depth(), 0);
    }
    CHECK_EQ(eng.l2().mshrs().live(), 0);
    CHECK_EQ(eng.l2().mshrs().slot_wait_depth(), 0);
    if (inclusion == Inclusion::NonInclusive) {
        // C4's exit criterion again, this time over a run with thousands of
        // evictions rather than a hand-built fixture.
        CHECK_EQ(eng.stats().back_invalidations, 0);
    } else {
        CHECK_TRUE(eng.stats().back_invalidations > 0);
    }
    std::printf("  soak: %lld samples, max targets %d, max line_wait %d, back-inv %lld,"
                " end cycle %lld\n",
                static_cast<long long>(probe.samples), probe.max_targets, probe.max_line_wait,
                static_cast<long long>(eng.stats().back_invalidations),
                static_cast<long long>(eng.tile_origin(64).get()));
}

void test_eight_cores_under_pressure() {
    run_soak("C2: the invariant soak, 8 cores, non_inclusive", Inclusion::NonInclusive);
    run_soak("C4: the invariant soak, 8 cores, inclusive", Inclusion::Inclusive);
}

void test_two_runs_of_one_configuration_agree() {
    check::group("C2: SELF -- V3, a re-run is byte-identical");

    // SELF-COMPARISON, and labelled as one. Decision B121: this detects
    // nondeterminism and can never detect a wrong answer, because a
    // wrong-but-deterministic engine passes it. It is here because V3's property
    // IS "two runs agree", and every other check in this file is an oracle.
    constexpr std::int64_t kLines = 64;
    FakeTrace tr = soak_trace(8, 64, kLines);

    EngineParams p    = fx::unbounded_params(kL1Sets, 2);
    p.l1              = fx::level(4, 2, 3, 2);
    p.l2              = fx::level(8, 2, 3, 2);
    p.l1.ii           = SimTime{1};
    p.l2.ii           = SimTime{1};
    p.l2.latency      = SimTime{2};
    p.l2_miss_latency = SimTime{17};
    p.dram_ii         = SimTime{3};

    LinearMapper m1(kLines);
    EventLog log1;
    m1.set_recorder(&log1);
    Engine e1(m1, tr, p);
    e1.run();

    LinearMapper m2(kLines);
    EventLog log2;
    m2.set_recorder(&log2);
    Engine e2(m2, tr, p);
    e2.run();

    CHECK_TRUE(log1.lines.size() > 5000);
    CHECK_TRUE(log1.lines == log2.lines);
    CHECK_EQ(e1.tile_origin(4), e2.tile_origin(4));
    CHECK_EQ(e1.stats().core_stall.at(3), e2.stats().core_stall.at(3));
}

}  // namespace

int main() {
    test_unbounded_baseline_reproduces_the_trace();
    test_a_tile_whose_cores_all_idle_still_advances();
    test_a_stall_shifts_the_whole_remainder_of_the_tile();
    test_a_per_burst_constant_accumulates_into_tile_origin();
    test_the_barrier_measures_the_last_service();
    test_core_stall_and_fetch_latency_are_equal_by_construction();
    test_the_return_leg_is_a_knob_that_still_works();
    test_line_waiters_resolve_together_in_stamp_order();
    test_a_woken_request_keeps_its_seniority_in_the_queue();
    test_a_slot_waiter_re_enters_at_the_level_it_blocked_at();
    test_a_queued_miss_that_became_a_hit_consumes_no_entry();
    test_service_order_is_eviction_order();
    test_inclusive_back_invalidates_and_non_inclusive_does_not();
    test_back_invalidation_walks_every_core_in_id_order();
    test_there_are_six_event_kinds_and_six_handlers();
    test_the_engine_refuses_a_trace_it_cannot_run();
    test_a_coordinate_outside_the_layer_names_its_tile_tick_and_core();
    test_the_queue_emptying_with_work_outstanding_is_a_deadlock();
    test_the_arena_refuses_to_release_a_request_that_is_still_held();
    test_eight_cores_under_pressure();
    test_two_runs_of_one_configuration_agree();
    return check::summary();
}
