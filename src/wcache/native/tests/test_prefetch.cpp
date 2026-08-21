// Plan unit C5: the `Prefetcher` interface, `none`, `next_burst(d)`, the
// `demand = false` triage rules and the drop rule (4.6, N15, N16).
//
// Exit criterion, Part 7 line 1356: "`none` reproduces C3's event log
// byte-identically; no prefetch ever appears on a wait index; V22 through V25".
//
// NAMING: "C1".."C5" are the PLAN's Phase C units; PROGRESS.md's decisions are
// B1-B126.
//
// ORACLE vs SELF, decision B121 again and it matters most here, because C5's
// stated criterion is literally a self-comparison. "`none` reproduces C3's event
// log byte-identically" compares a run against another run of the same code, so
// it detects a prefetcher that fires when it should not and can never detect a
// wrong timeline: a `none` run that is wrong in the same way on both sides
// passes it. Every self-comparison below is therefore paired with an oracle that
// computes the expected answer from 4.5, 4.6 and 2.5b without running the engine:
//
//   inertness    SELF (two runs) + ORACLE (`NoPrefetcher` makes ZERO calls into
//                the issuer, checked directly on the class) + ORACLE (the `none`
//                run's timeline equals `fx::oracle_tile_origin`)
//   V22          SELF (every `d` agrees) + ORACLE (all of them equal the trace's
//                own timeline, which is what "nothing left to hide" means)
//   V23          ORACLE only: the plan states the three cycle numbers
//   the d sweep  ORACLE at both ends: the serialized-miss recurrence at d = 0 and
//                the all-hit timeline plus one miss at d = 2
#include <wcache/prefetcher.h>

#include <wcache/cache_level.h>
#include <wcache/engine.h>
#include <wcache/mshr.h>
#include <wcache/types.h>

#include <cstdint>
#include <cstdio>
#include <deque>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;
using fx::EventLog;
using fx::FakeTrace;
using fx::InvariantProbe;
using fx::LinearMapper;

namespace {

constexpr std::int64_t kL1Sets = 16;
constexpr std::int64_t kL2Sets = 32;

// ===========================================================================
// The policy classes on their own (4.6's pseudocode, line for line)
// ===========================================================================

// What the memory system looks like to a prefetcher, recorded. It is the whole
// interface: how long the tile is, and a request to fetch a burst that answers
// with the BUDGET rather than with a refusal (N16).
class RecordingIssuer final : public PrefetchIssuer {
public:
    std::int32_t bursts_in_tile = 5;
    std::int32_t budget         = 1000;
    std::vector<std::pair<std::int32_t, std::int32_t>> calls;  // (core, burst)

    std::int32_t n_bursts_in_tile(CoreId) const override { return bursts_in_tile; }

    bool issue_prefetch(CoreId core, BurstIndex k, SimTime) override {
        if (static_cast<std::int32_t>(calls.size()) >= budget) return false;
        calls.push_back({core.get(), k.get()});
        return true;
    }
};

void test_none_asks_the_memory_system_for_nothing() {
    check::group("C5: ORACLE -- `none` makes zero calls, which is what inertness IS");

    NoPrefetcher pf;
    RecordingIssuer mem;
    for (std::int32_t k = 0; k < 5; ++k) {
        pf.on_demand_issue(mem, CoreId{0}, BurstIndex{k}, SimTime{k});
    }
    pf.on_tile_start(CoreId{0});
    // The strongest form of C5's "genuinely inert when off": not "the two logs
    // agree" but "the call cannot have had an effect, because it made none".
    CHECK_EQ(check::ssize(mem.calls), 0);
}

void test_next_burst_walks_ahead_by_exactly_the_distance() {
    check::group("C5: 4.6's next_burst(d), line for line");

    RecordingIssuer mem;
    NextBurstPrefetcher pf(1, 2);
    CHECK_EQ(pf.distance(), 1);
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{0});

    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{0}, SimTime{0});
    CHECK_EQ(check::ssize(mem.calls), 1);
    CHECK_EQ(mem.calls[0].second, 1);
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{2});   // one past what it fetched

    // "Never behind the core": a demand issue of burst k means every burst up to
    // k is already the core's business, so the cursor is pulled forward rather
    // than walking from where it stopped.
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{1}, SimTime{1});
    CHECK_EQ(check::ssize(mem.calls), 2);
    CHECK_EQ(mem.calls[1].second, 2);

    // Two cores keep separate cursors, which is what makes `PrefetchState` per
    // L1 (3.3) rather than global.
    pf.on_demand_issue(mem, CoreId{1}, BurstIndex{0}, SimTime{2});
    CHECK_EQ(mem.calls[2].first, 1);
    CHECK_EQ(mem.calls[2].second, 1);

    RecordingIssuer m2;
    NextBurstPrefetcher deep(3, 1);
    deep.on_demand_issue(m2, CoreId{0}, BurstIndex{0}, SimTime{0});
    CHECK_EQ(check::ssize(m2.calls), 3);
    CHECK_EQ(m2.calls[0].second, 1);
    CHECK_EQ(m2.calls[2].second, 3);
    // I14's first half: `pf_cursor - cursor <= 1 + d`.
    CHECK_EQ(deep.pf_cursor(CoreId{0}), BurstIndex{4});
}

void test_next_burst_stops_at_the_tile_boundary() {
    check::group("C5: 4.6 -- the policy never crosses a tile boundary");

    RecordingIssuer mem;
    mem.bursts_in_tile = 3;
    NextBurstPrefetcher pf(5, 1);
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{1}, SimTime{0});
    // Only burst 2 exists ahead of burst 1 in a three-burst tile, and the next
    // tile's activations do not exist until the barrier resolves.
    CHECK_EQ(check::ssize(mem.calls), 1);
    CHECK_EQ(mem.calls[0].second, 2);
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{3});
}

void test_next_burst_stops_on_the_budget_and_retries_later() {
    check::group("C5: ORACLE -- N16, the budget and not a refusal is what stops it");

    RecordingIssuer mem;
    mem.budget = 2;
    NextBurstPrefetcher pf(4, 1);
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{0}, SimTime{0});
    CHECK_EQ(check::ssize(mem.calls), 2);          // bursts 1 and 2, then the budget
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{3});
    // The cursor is NOT advanced past the burst the budget refused, so the same
    // burst is tried again at the next demand issue, by which time its own fills
    // have returned credits.
    mem.budget = 4;
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{0}, SimTime{1});
    CHECK_EQ(check::ssize(mem.calls), 4);
    CHECK_EQ(mem.calls[2].second, 3);
    CHECK_EQ(mem.calls[3].second, 4);
}

void test_on_tile_start_is_needed_and_not_convenient() {
    check::group("C5: the unnamed hook -- without the reset a tile loses bursts");

    // The plan states the BEHAVIOUR ("the first burst of every tile is never
    // prefetched") and never names a hook. This is the check that the hook is
    // load-bearing: with the cursor carried across the seam, the next tile's
    // burst 1 is below the stale cursor and is never fetched at all.
    RecordingIssuer mem;
    NextBurstPrefetcher pf(1, 1);
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{0}, SimTime{0});
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{1}, SimTime{1});
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{3});

    // A new tile begins. Without the reset the cursor is still 3 and a demand
    // issue of burst 0 fetches nothing, because 3 > 0 + 1.
    pf.on_tile_start(CoreId{0});
    CHECK_EQ(pf.pf_cursor(CoreId{0}), BurstIndex{0});
    const std::int64_t before = check::ssize(mem.calls);
    pf.on_demand_issue(mem, CoreId{0}, BurstIndex{0}, SimTime{100});
    CHECK_EQ(check::ssize(mem.calls) - before, 1);
    CHECK_EQ(mem.calls.back().second, 1);
}

void test_make_prefetcher_refuses_a_configuration_that_claims_to_be_on() {
    check::group("C5: make_prefetcher, and what it refuses");

    CHECK_THROWS(std::invalid_argument, make_prefetcher(PrefetchKind::NextBurst, 0, 1));
    CHECK_THROWS(std::invalid_argument, make_prefetcher(PrefetchKind::NextBurst, -1, 1));
    CHECK_THROWS(std::invalid_argument, make_prefetcher(PrefetchKind::NextBurst, 1, 0));
    CHECK_THROWS(std::invalid_argument, make_prefetcher(PrefetchKind::None, -1, 1));
    // 2.5b pairs `none` with distance 0 and a sweep grid crosses the two axes,
    // so a distance is accepted and ignored here; D1's row owns the cross-field
    // rule that `next_burst` with distance 0 is a configuration error.
    CHECK_TRUE(make_prefetcher(PrefetchKind::None, 3, 1) != nullptr);
    CHECK_TRUE(make_prefetcher(PrefetchKind::NextBurst, 2, 4) != nullptr);
}

// ===========================================================================
// V22: inertness when off, and nothing left to hide on the unbounded baseline
// ===========================================================================

FakeTrace sweep_trace(std::int64_t gap, std::int32_t n_bursts) {
    FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(1);
    for (std::int32_t k = 0; k < n_bursts; ++k) {
        tr.add_burst(t0, 0, gap * k, k);
    }
    return tr;
}

EngineParams miss_params() {
    // 4.6's worked example, at the 2.5b defaults: single-line bursts,
    // l1_latency 0, l1_ii 1, l2_latency 10, l2_miss_latency 100, so a full miss
    // costs 110 cycles.
    EngineParams p     = fx::unbounded_params(kL1Sets, 4);
    p.l1               = fx::level(kL1Sets, 4, 8, 4, 1);
    p.l2               = fx::level(kL2Sets, 4, 8, 4, 1);
    p.l1.ii            = SimTime{1};
    p.l1.latency       = SimTime{0};
    p.l2.ii            = SimTime{1};
    p.l2.latency       = SimTime{10};
    p.l2_to_l1_latency = SimTime{0};
    p.l2_miss_latency  = SimTime{100};
    p.dram_ii          = SimTime{1};
    return p;
}

void test_none_reproduces_the_no_prefetch_timeline() {
    check::group("C5: SELF + ORACLE -- `none` is inert");

    FakeTrace tr = sweep_trace(60, 4);
    LinearMapper m1(64);
    EventLog log1;
    m1.set_recorder(&log1);
    Engine a(m1, tr, miss_params());
    a.run();

    LinearMapper m2(64);
    EventLog log2;
    m2.set_recorder(&log2);
    EngineParams p    = miss_params();
    p.prefetch_policy = PrefetchKind::None;
    p.prefetch_distance = 0;
    Engine b(m2, tr, p);
    b.run();

    // SELF, and it is C5's stated criterion in the only form the tree can build
    // it: there is no pre-C5 engine to compare against, so "reproduces C3's
    // event log byte-identically" becomes "the default configuration and an
    // explicit `none` produce the same log". It is the weak half.
    CHECK_TRUE(log1.lines == log2.lines);
    CHECK_TRUE(log1.lines.size() > 20);

    // ORACLE, and it is the half that can fail for a reason other than
    // nondeterminism: with `none` every burst is a full miss and the timeline is
    // the serialized-miss recurrence, computed here from 4.5 and the three
    // latencies rather than from the engine.
    std::int64_t served = 0;
    for (std::int32_t k = 0; k < 4; ++k) {
        const std::int64_t issue = (k == 0) ? 0 : served + 60;
        served                   = issue + 110;
    }
    CHECK_EQ(a.tile_origin(1), SimTime{served + 1});
    CHECK_EQ(a.tile_origin(1), SimTime{621});
    CHECK_EQ(a.stats().pf_budget_exhausted, 0);
    CHECK_EQ(a.stats().pf_dropped_array_hit + a.stats().pf_dropped_entry +
                 a.stats().pf_dropped_no_slot + a.stats().pf_dropped_reserve,
             0);
}

void test_on_the_unbounded_baseline_every_distance_agrees() {
    check::group("C5: SELF + ORACLE -- V22, nothing left to hide when access is free");

    FakeTrace tr(3);
    const std::int32_t t0 = tr.add_tile(2);
    for (std::int32_t c = 0; c < 3; ++c) {
        for (std::int32_t k = 0; k < 5; ++k) tr.add_burst(t0, c, c + 3 * k, (c * 5 + k) % 16);
    }
    const std::int32_t t1 = tr.add_tile(1);
    for (std::int32_t c = 0; c < 3; ++c) {
        for (std::int32_t k = 0; k < 3; ++k) tr.add_burst(t1, c, 2 * k, (c + k) % 16);
    }

    const std::vector<std::int64_t> want = fx::oracle_tile_origin(tr);

    std::vector<std::int64_t> ends;
    for (std::int32_t d : {0, 1, 2, 4}) {
        LinearMapper map(16);
        EngineParams p      = fx::unbounded_params(kL1Sets, 4);
        p.l1                = fx::level(kL1Sets, 4, 8, 4, 1);
        p.l1.ii             = SimTime{0};
        p.l2                = fx::level(kL2Sets, 4, 8, 4, 1);
        p.l2.ii             = SimTime{0};
        p.prefetch_policy   = d == 0 ? PrefetchKind::None : PrefetchKind::NextBurst;
        p.prefetch_distance = d == 0 ? 0 : d;

        InvariantProbe probe(16, 1);
        map.set_recorder(&probe);
        Engine eng(map, tr, p);
        probe.attach(&eng);
        eng.run();

        // ORACLE: with every access free, `served(c, k) = issue(c, k)` and there
        // is nothing left for a prefetcher to hide, so EVERY distance must
        // reproduce the trace's own timeline (Part 5, V22).
        CHECK_EQ(eng.tile_origin(1), SimTime{want[1]});
        CHECK_EQ(eng.tile_origin(2), SimTime{want[2]});
        ends.push_back(eng.tile_origin(2).get());
        CHECK_EQ(check::ssize(probe.failures), 0);
        for (const std::string& f : probe.failures) std::printf("  invariant: %s\n", f.c_str());
        // I15 at the L1, which is where the plan's drop rule applies and where
        // it holds: no prefetch ever waits there.
        CHECK_EQ(probe.l1_prefetch_waiters, 0);
    }
    // SELF: the four agree with each other, which is V22's own wording. It is
    // the weaker statement and it is here because V22 asks for it.
    for (std::size_t i = 1; i < ends.size(); ++i) CHECK_EQ(ends[i], ends[0]);
}

// ===========================================================================
// V23: the 4.6 worked example, all three columns
// ===========================================================================

void test_the_worked_example_of_4_6() {
    check::group("C5: ORACLE -- V23, served(b2) is 221, 111 and 221");

    // One core, two single-line bursts one tick apart, and burst 1 misses in
    // every column. `tile_origin[1]` is the last service plus a tail of 1, so
    // served(b2) is observable as `tile_origin[1] - 1`.
    FakeTrace tr = sweep_trace(1, 2);

    // --- column 1: none -----------------------------------------------------
    {
        LinearMapper map(64);
        Engine eng(map, tr, miss_params());
        eng.run();
        CHECK_EQ(eng.tile_origin(1), SimTime{222});   // served(b2) = 221
    }

    // --- column 2: next_burst(1), timely ------------------------------------
    {
        LinearMapper map(64);
        EngineParams p      = miss_params();
        p.prefetch_policy   = PrefetchKind::NextBurst;
        p.prefetch_distance = 1;
        InvariantProbe probe(64, 1);
        map.set_recorder(&probe);
        Engine eng(map, tr, p);
        probe.attach(&eng);
        eng.run();

        // 110 cycles saved, and the number is a class-order test as well: the
        // prefetch fill and the demand probe both land at 111, and only the
        // "class 0 before class 2" rule of 3.6 makes that a hit rather than a
        // second fetch. Reverse the two classes and this run reports 221.
        CHECK_EQ(eng.tile_origin(1), SimTime{112});   // served(b2) = 111
        CHECK_EQ(check::ssize(probe.failures), 0);
        // 4.5's floor doing its work without being a mechanism: the line became
        // resident at 111 and the core was served at 111 rather than earlier,
        // because it could not ask before 111. A line resident since cycle 0
        // would still be served at 111.
        CHECK_EQ(eng.stats().core_stall.at(0), 110);
    }

    // --- column 3: next_burst(1), evicted before use ------------------------
    {
        // A one-set, one-way L1 and L2, and burst 2's line already in the L2 so
        // the prefetch lands early. Burst 1's fill at 110 then evicts it from
        // BOTH arrays, and the core's own access at 111 is a full miss again.
        // "Prefetching can lose here, and that is the honest cost of leaving the
        // data in the cache."
        LinearMapper map(64);
        EngineParams p      = miss_params();
        p.l1                = fx::level(1, 1, 8, 4, 1);
        p.l2                = fx::level(1, 1, 8, 4, 1);
        p.l1.ii             = SimTime{1};
        p.l2.ii             = SimTime{1};
        p.l2.latency        = SimTime{10};
        p.prefetch_policy   = PrefetchKind::NextBurst;
        p.prefetch_distance = 1;
        Engine eng(map, tr, p);
        eng.l2().install(LineId{1});
        eng.run();
        CHECK_EQ(eng.tile_origin(1), SimTime{222});   // served(b2) = 221, and a wasted fetch
    }
}

// ===========================================================================
// The distance sweep: the implementer's smoke claim, re-derived
// ===========================================================================

void test_deeper_prefetching_shortens_the_run() {
    check::group("C5: ORACLE -- the end cycle falls as the distance grows");

    FakeTrace tr = sweep_trace(60, 4);
    std::vector<std::int64_t> ends;
    for (std::int32_t d : {0, 1, 2}) {
        LinearMapper map(64);
        EngineParams p      = miss_params();
        p.prefetch_policy   = d == 0 ? PrefetchKind::None : PrefetchKind::NextBurst;
        p.prefetch_distance = d;
        InvariantProbe probe(64, 1);
        map.set_recorder(&probe);
        Engine eng(map, tr, p);
        probe.attach(&eng);
        eng.run();
        ends.push_back(eng.tile_origin(1).get());
        CHECK_EQ(check::ssize(probe.failures), 0);
    }
    std::printf("  end cycle at d = 0, 1, 2: %lld, %lld, %lld\n",
                static_cast<long long>(ends[0]), static_cast<long long>(ends[1]),
                static_cast<long long>(ends[2]));

    // ORACLE at d = 0: four serialized full misses, `served(k) = served(k-1) +
    // gap + 110`, plus a tail of 1.
    CHECK_EQ(ends[0], 621);

    // ORACLE at d = 2: the fetch-ahead is deep enough that every burst after the
    // first is resident before the core asks, so the timeline is the trace's own
    // shifted by the one miss that cannot be hidden -- the first burst of a tile
    // is never prefetched (4.6), which is also the reported ceiling on how much
    // this can win.
    const std::int64_t all_hit = fx::oracle_tile_origin(tr)[1];
    CHECK_EQ(all_hit, 181);
    CHECK_EQ(ends[2], all_hit + 110);

    // And the claim itself: strictly monotone, which is the shape of the
    // implementer's smoke number. The absolute figures are this fixture's; the
    // implementer's own fixture was not left in the tree, so the numbers it
    // reported cannot be reproduced, only the property they were reporting.
    CHECK_TRUE(ends[0] > ends[1]);
    CHECK_TRUE(ends[1] > ends[2]);
}

void test_prefetching_restarts_at_every_tile() {
    check::group("C5: ORACLE -- the fetch-ahead cursor restarts, so every tile wins");

    // Two tiles of four bursts each. The first burst of a tile is never
    // prefetched (4.6), so each tile costs one full miss and nothing else, and
    // the second tile must win exactly as much as the first. Without the cursor
    // reset at the seam the second tile's bursts 1 to 3 sit below a stale cursor
    // and are never fetched at all, which is the whole reason the hook exists.
    FakeTrace tr(1);
    for (std::int32_t t = 0; t < 2; ++t) {
        const std::int32_t tile = tr.add_tile(1);
        for (std::int32_t k = 0; k < 4; ++k) tr.add_burst(tile, 0, 60 * k, 4 * t + k);
    }

    LinearMapper map(64);
    EngineParams p      = miss_params();
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 2;
    Engine eng(map, tr, p);
    eng.run();

    // ORACLE: one unavoidable miss per tile on top of the trace's own timeline,
    // which is 181 cycles per tile, so each tile costs 291 and the run ends at
    // 582. A carried-over cursor makes the second tile behave like d = 0 and
    // ends the run at 291 + 621.
    CHECK_EQ(eng.tile_origin(1), SimTime{291});
    CHECK_EQ(eng.tile_origin(2), SimTime{582});
}

// ===========================================================================
// V25: the promotion path
// ===========================================================================

void test_a_demand_request_promotes_an_outstanding_prefetch_entry() {
    check::group("C5: ORACLE -- V25, the late prefetch merges and promotes");

    // A gap short enough that the core's demand access arrives while its own
    // prefetch is still outstanding: the fetch started early but not early
    // enough, so the core saves the part of the latency that had elapsed.
    FakeTrace tr = sweep_trace(40, 3);

    LinearMapper map(64);
    EngineParams p      = miss_params();
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 1;
    InvariantProbe probe(64, 1);
    map.set_recorder(&probe);
    Engine eng(map, tr, p);
    probe.attach(&eng);
    eng.run();

    // The promotion happened, and it was watched rather than assumed: an entry
    // seen with `demand == false` and later with `demand == true` is exactly
    // 4.6's late-prefetch case, and it is why `Mshr::demand` is mutable.
    CHECK_TRUE(probe.promotions > 0);
    CHECK_EQ(check::ssize(probe.failures), 0);

    // ORACLE: burst 1's prefetch is issued at cycle 0 and its fill lands at 111;
    // the core asks for burst 1 at 150 (served(b0) = 110 plus a gap of 40), so
    // that one is timely. Burst 2's prefetch is issued at 150 and lands at 261,
    // while the core asks at 190, so it MERGES and is served at 261 rather than
    // at 190 + 110 = 300. The tile ends one cycle later.
    CHECK_EQ(eng.tile_origin(1), SimTime{262});
}

// ===========================================================================
// V28 and I15: where a prefetch may and may not wait
// ===========================================================================

void test_a_prefetch_never_waits_at_the_l1() {
    check::group("C5: ORACLE -- I15 at the L1, where 4.6's drop rule applies");

    // Heavy contention with a small L1 MSHR file, so prefetches are refused
    // often. Every refusal must be a DROP, counted by reason, and no prefetch
    // may ever appear on an L1 wait index.
    FakeTrace tr(4);
    const std::int32_t t0 = tr.add_tile(1);
    for (std::int32_t c = 0; c < 4; ++c) {
        for (std::int32_t k = 0; k < 6; ++k) tr.add_burst(t0, c, 2 * k, (c + k) % 8, 2);
    }

    LinearMapper map(16);
    EngineParams p      = miss_params();
    p.l1                = fx::level(4, 2, 4, 2, 2);   // 4 entries, 2 reserved for demand
    p.l2                = fx::level(8, 2, 4, 2, 2);
    p.l1.ii             = SimTime{1};
    p.l2.ii             = SimTime{1};
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 2;
    InvariantProbe probe(16, 2);
    map.set_recorder(&probe);
    Engine eng(map, tr, p);
    probe.attach(&eng);
    eng.run();

    CHECK_EQ(check::ssize(probe.failures), 0);
    for (const std::string& f : probe.failures) std::printf("  invariant: %s\n", f.c_str());
    CHECK_EQ(probe.l1_prefetch_waiters, 0);

    // Not vacuous: the fixture really did refuse prefetches, and it refused them
    // for more than one reason, which is what Part 8 asks to be broken out.
    const EngineStats& s = eng.stats();
    const std::int64_t drops = s.pf_dropped_array_hit + s.pf_dropped_entry +
                               s.pf_dropped_no_slot + s.pf_dropped_reserve;
    CHECK_TRUE(drops > 0);
    std::printf("  drops: hit %lld, entry %lld, no slot %lld, reserve %lld; budget out %lld\n",
                static_cast<long long>(s.pf_dropped_array_hit),
                static_cast<long long>(s.pf_dropped_entry),
                static_cast<long long>(s.pf_dropped_no_slot),
                static_cast<long long>(s.pf_dropped_reserve),
                static_cast<long long>(s.pf_budget_exhausted));
    // I14's second half held at every sample, and the budget really did bind, so
    // "the budget and not a refusal is what stops it" is a measured statement.
    CHECK_TRUE(s.pf_budget_exhausted > 0);
    CHECK_TRUE(probe.max_pf_outstanding <= p.l1.mshrs - p.l1.demand_reserve);
    // Every prefetch credit came back: nothing is in flight at the end.
    for (std::int32_t c = 0; c < 4; ++c) CHECK_EQ(s.pf_outstanding.at(static_cast<std::size_t>(c)), 0);
}

void test_a_prefetch_DOES_wait_at_the_l2_which_I15_forbids() {
    check::group("C5: FINDING -- a prefetch reaches an L2 wait index (I15, V28, P1)");

    // Two cores and one shared line. Core 0's DEMAND request takes the L2 entry;
    // the L2 target list holds one, so core 1's PREFETCH for the same line finds
    // the entry with its targets full and is pushed onto the L2 line-wait index
    // carrying `demand == false`.
    //
    // That is reachable, it terminates, and it is what the implementer's P1
    // resolution requires: `is_prefetch_at_issue` is false at the L2, so the
    // drop rules do not apply there and the request waits like a demand request.
    // It also contradicts I15 and V28 as literally written ("a request with
    // demand == false is NEVER on a wait index"), so the invariant and the V-row
    // need amending rather than the code.
    FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(1);
    tr.add_burst(t0, 0, 0, 5);    // core 0 demands line 5 first
    tr.add_burst(t0, 0, 8, 6);
    tr.add_burst(t0, 1, 0, 7);    // core 1's burst 0, whose prefetch is burst 1
    tr.add_burst(t0, 1, 4, 5);    // core 1's burst 1 IS line 5, so it is prefetched

    LinearMapper map(16);
    EngineParams p      = miss_params();
    p.l1                = fx::level(4, 2, 4, 2, 1);
    p.l2                = fx::level(8, 2, 4, 1, 1);   // l2_tgts_per_mshr = 1
    p.l1.ii             = SimTime{1};
    p.l2.ii             = SimTime{1};
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 1;
    InvariantProbe probe(16, 1);
    map.set_recorder(&probe);
    Engine eng(map, tr, p);
    probe.attach(&eng);
    eng.run();

    // The finding, as a number: prefetch requests were seen on an L2 line-wait
    // index, and never on an L1 one.
    CHECK_TRUE(probe.l2_prefetch_waiters > 0);
    CHECK_EQ(probe.l1_prefetch_waiters, 0);
    std::printf("  prefetch requests observed on an L2 wait index: %lld samples\n",
                static_cast<long long>(probe.l2_prefetch_waiters));

    // And it terminates: the waiter is woken by the entry's retire, re-enters at
    // the L2 (3.5), hits, and fills the L1 entry it has been holding all along.
    // No invariant other than I15's letter is broken.
    CHECK_EQ(check::ssize(probe.failures), 0);
    CHECK_EQ(eng.l2().mshrs().live(), 0);
    for (std::int32_t c = 0; c < 2; ++c) {
        CHECK_EQ(eng.l1(CoreId{c}).mshrs().live(), 0);
        CHECK_EQ(eng.stats().pf_outstanding.at(static_cast<std::size_t>(c)), 0);
    }
}

void test_dropping_a_prefetch_at_the_l2_would_strand_its_l1_entry() {
    check::group("C5: FINDING -- P1's deadlock, demonstrated at the level below");

    // P1's claim: a prefetch refused at the L2 has no defined outcome, and the
    // obvious one (drop it, as 4.6 says) deadlocks. Demonstrated here without
    // an engine, because the engine refuses to reach the state at all.
    //
    // Step 1: a prefetch is forwarded at the L1, which allocates an L1 entry it
    // now holds across the whole downstream round trip (4.1, 4.2).
    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2, 0), counter);
    CacheLevel l2(Level::L2, map, fx::level(8, 2, 1, 1, 0), counter);
    std::deque<Request> arena;
    std::vector<Request*> granted;

    arena.push_back(Request{CoreId{0}, LineId{9}, BurstIndex{1}, false});
    Request& pf = arena.back();
    CHECK_TRUE(l1.triage(pf, granted) == TriageOutcome::Forwarded);
    CHECK_EQ(l1.mshrs().live(), 1);
    CHECK_TRUE(pf.mshr1 != nullptr);
    CHECK_TRUE(pf.level == Level::L2);

    // Step 2: at the L2 it is no longer "at issue", so the drop rules do not
    // apply and it is treated exactly like a demand request. That is the
    // implementer's resolution, and `is_prefetch_at_issue` is the one spelling
    // of it that `has_slot`, both wait pushes and `triage` all read.
    CHECK_TRUE(!is_prefetch_at_issue(pf));
    arena.push_back(Request{CoreId{1}, LineId{10}, BurstIndex{0}});
    Request& other = arena.back();
    CHECK_TRUE(l2.triage(other, granted) == TriageOutcome::Forwarded);   // l2_mshrs = 1, now full
    CHECK_TRUE(l2.triage(pf, granted) == TriageOutcome::BlockedPool);    // waits, holding its L1 entry
    CHECK_TRUE(pf.on_wait_index);

    // Step 3: what the plan asks for instead. A request that IS at issue and is
    // refused for want of a slot is dropped, and the four reasons are the L1's.
    // Applying that rule at the L2 means this request goes away while its L1
    // entry stays live, and the ONLY thing that retires an L1 entry is an
    // `E_L1Fill`, which only an L2 hit or an L2 fill for that line can schedule.
    // With the request dropped, neither will ever happen, so the entry is
    // unfillable, its core's burst never completes, and the run ends at D12's
    // deadlock check. I15 forbids the other outcome, waiting, which is why the
    // plan leaves no third option.
    CHECK_EQ(l1.mshrs().live(), 1);
    CHECK_TRUE(l1.mshrs().find(LineId{9}) != nullptr);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{9})->targets), 1);

    // And the engine refuses to be put in that state rather than producing it:
    // a request reaching the L2 without an L1 entry is caught by I6's check, and
    // a drop at the L2 is caught by name.
    arena.push_back(Request{CoreId{0}, LineId{11}, BurstIndex{0}, false});
    Request& loose = arena.back();
    CHECK_TRUE(is_prefetch_at_issue(loose));
    CHECK_TRUE(l2.triage(loose, granted) == TriageOutcome::DroppedNoSlot);
}

// ===========================================================================
// P2, with the prefetcher on
// ===========================================================================

void test_r8_makes_the_hidden_latency_measurable() {
    check::group("C5: R8 -- the hidden latency is zero at d = 0 and positive above it");

    // Part 8: "with prefetching on, their DIFFERENCE is the latency the policy
    // hid, and it is the single number the policy should be judged on."
    //
    // Under the pre-R8 definition `fetch_latency = served - issued_at` that
    // difference was identically zero at EVERY distance, because `E_Issue` is
    // scheduled at exactly the `want` that `serve` recomputes, so
    // `issued_at == want` for every burst. U19 measured it and G7 recorded that
    // the prefetch study therefore had no metric.
    //
    // R8 anchors the fetch on the LINE's first request instead. This is the
    // measurement U19 made, re-run: equal at `d = 0`, where nothing is
    // prefetched and nothing can be hidden, and strictly greater at every
    // distance above it.
    FakeTrace tr = sweep_trace(60, 4);
    std::int64_t hidden_at_1 = 0;
    for (std::int32_t d : {0, 1, 2, 4, 8}) {
        LinearMapper map(64);
        EngineParams p      = miss_params();
        p.prefetch_policy   = d == 0 ? PrefetchKind::None : PrefetchKind::NextBurst;
        p.prefetch_distance = d;
        Engine eng(map, tr, p);
        eng.run();
        const std::int64_t stall  = eng.stats().core_stall.at(0);
        const std::int64_t fetch  = eng.stats().fetch_latency.at(0);
        const std::int64_t hidden = fetch - stall;
        CHECK_TRUE(stall > 0);
        if (d == 0) {
            CHECK_EQ(fetch, stall);
        } else {
            CHECK_TRUE(hidden > 0);
        }
        if (d == 1) hidden_at_1 = hidden;
        std::printf("  d = %d: core_stall %lld, fetch_latency %lld, hidden %lld\n", d,
                    static_cast<long long>(stall), static_cast<long long>(fetch),
                    static_cast<long long>(hidden));
    }
    // Not vacuous: the metric is large where the pre-R8 one was zero.
    CHECK_TRUE(hidden_at_1 > 100);
}

}  // namespace

int main() {
    test_none_asks_the_memory_system_for_nothing();
    test_next_burst_walks_ahead_by_exactly_the_distance();
    test_next_burst_stops_at_the_tile_boundary();
    test_next_burst_stops_on_the_budget_and_retries_later();
    test_on_tile_start_is_needed_and_not_convenient();
    test_make_prefetcher_refuses_a_configuration_that_claims_to_be_on();
    test_none_reproduces_the_no_prefetch_timeline();
    test_on_the_unbounded_baseline_every_distance_agrees();
    test_the_worked_example_of_4_6();
    test_deeper_prefetching_shortens_the_run();
    test_prefetching_restarts_at_every_tile();
    test_a_demand_request_promotes_an_outstanding_prefetch_entry();
    test_a_prefetch_never_waits_at_the_l1();
    test_a_prefetch_DOES_wait_at_the_l2_which_I15_forbids();
    test_dropping_a_prefetch_at_the_l2_would_strand_its_l1_entry();
    test_r8_makes_the_hidden_latency_measurable();
    return check::summary();
}
