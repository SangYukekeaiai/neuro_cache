// Phase 3 line-oriented prefetch policy and cross-level coverage.
#include <cachesim/core/engine.h>
#include <cachesim/layout/block_pack.h>
#include <cachesim/prefetch/neighbour.h>
#include <cachesim/prefetch/next_burst.h>

#include <cstdint>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace cachesim;
using fx::FakeTrace;

namespace {

void test_neighbour_preserves_line_order_and_direction() {
    check::group("C5: neighbour emits closest up/down lines in order");

    BlockPackMapper mapper(WeightShape{1, 1, 1, 8}, 1, 1, 1);
    FakeTrace trace(1);
    const std::int32_t tile = trace.add_tile();
    trace.add_burst(tile, 0, 0, 3);
    NeighbourPrefetcher pf(Axis::COUT, 2, true, true);
    std::vector<PrefetchTarget> out;
    const PrefetchContext ctx{Level::L1, CoreId{0}, tile, BurstIndex{0}, LineId{3}, SimTime{0},
                              mapper, trace};

    pf.on_demand(ctx, out);
    CHECK_EQ(check::ssize(out), 4);
    CHECK_EQ(out[0].line, LineId{4});
    CHECK_EQ(out[1].line, LineId{2});
    CHECK_EQ(out[2].line, LineId{5});
    CHECK_EQ(out[3].line, LineId{1});
    CHECK_EQ(out[3].burst, BurstIndex{0});
}

void test_each_policy_runs_at_the_other_level() {
    check::group("C5: each pluggable policy is legal at the other cache level");

    FakeTrace trace(1);
    const std::int32_t tile = trace.add_tile();
    trace.add_burst(tile, 0, 0, 3);
    trace.add_burst(tile, 0, 20, 4);
    trace.add_burst(tile, 0, 40, 5);

    // Neighbour at L1: it emits spatial targets into the private array and
    // still uses the ordinary L1 budget/port path.
    {
        BlockPackMapper mapper(WeightShape{1, 1, 1, 16}, 1, 1, 1);
        EngineParams p;
        p.l1 = fx::level(16, 2, 8, 4);
        p.l2 = fx::level(32, 2, 8, 4);
        p.l1.prefetch_kind = PrefetchKind::Neighbour;
        p.l1.prefetch_params = PrefetchParams{1, Axis::COUT, true, true};
        p.l2_miss_latency = SimTime{1};
        Engine engine(mapper, trace, p);
        engine.run();
        CHECK_TRUE(engine.stats().pf_issued > 0);
        CHECK_EQ(engine.l1(CoreId{0}).mshrs().live(), 0);
        CHECK_EQ(engine.l2().mshrs().live(), 0);
        CHECK_EQ(engine.stats().pf_outstanding.at(0), 0);
    }

    // NextBurst at L2: the same cursor policy is driven by the L2 demand
    // trigger, while target issue uses the bank port and L2 triage drops.
    {
        BlockPackMapper mapper(WeightShape{1, 1, 1, 16}, 1, 1, 1);
        EngineParams p;
        p.l1 = fx::level(16, 2, 8, 4);
        p.l2 = fx::level(32, 2, 8, 4);
        p.l2.prefetch_kind = PrefetchKind::NextBurst;
        p.l2.prefetch_params = PrefetchParams{1, Axis::COUT, true, true};
        p.l2_miss_latency = SimTime{1};
        Engine engine(mapper, trace, p);
        engine.run();
        CHECK_TRUE(engine.stats().l2_pf_issued > 0);
        CHECK_EQ(engine.stats().l2_pf_issued_up + engine.stats().l2_pf_issued_down,
                 engine.stats().l2_pf_issued);
        CHECK_EQ(engine.l2().mshrs().live(), 0);
        CHECK_EQ(engine.stats().pf_outstanding.at(0), 0);
    }
}

}  // namespace

int main() {
    test_neighbour_preserves_line_order_and_direction();
    test_each_policy_runs_at_the_other_level();
    return check::summary();
}
