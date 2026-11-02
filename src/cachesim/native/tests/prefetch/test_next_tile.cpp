#include <cachesim/core/engine.h>
#include <cachesim/layout/khkw_split.h>
#include <cachesim/prefetch/next_tile.h>

#include <stdexcept>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace cachesim;

namespace {

void test_exact_targets_and_boundaries() {
    check::group("next_tile: forward COUT blocks preserve the burst tag and other coordinates");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    const PrefetchContext ctx{Level::L2, CoreId{0}, tile, BurstIndex{7},
                              mapper.line_of(Coord{1, 1, 16, 4}), SimTime{0}, mapper, trace};
    CHECK_EQ(ctx.line, LineId{28});
    CHECK_EQ(mapper.digit_stride(KhkwSplitMapper::Digit::COUT), 16);

    // Neither a CIN axis nor disabled directions changes this fixed policy.
    auto pf = make_prefetcher(PrefetchKind::NextTile,
                              PrefetchParams{1, Axis::CIN, false, false}, 16);
    std::vector<PrefetchTarget> out;
    pf->on_demand(ctx, out);
    CHECK_EQ(check::ssize(out), 1);
    if (out.size() == 1) {
        CHECK_EQ(out[0].line, LineId{44});
        CHECK_EQ(out[0].burst, ctx.k);
    }

    NextTilePrefetcher two(2);
    out.clear();
    two.on_demand(ctx, out);
    CHECK_EQ(check::ssize(out), 2);
    if (out.size() == 2) {
        CHECK_EQ(out[0].line, LineId{44});
        CHECK_EQ(out[1].line, LineId{60});
        CHECK_EQ(out[0].burst, ctx.k);
        CHECK_EQ(out[1].burst, ctx.k);
    }

    auto edge = ctx;
    edge.line = mapper.line_of(Coord{1, 1, 16, 12});
    out.clear();
    two.on_demand(edge, out);
    CHECK_EQ(check::ssize(out), 0);

    edge.line = mapper.line_of(Coord{1, 1, 16, 8});
    two.on_demand(edge, out);
    CHECK_EQ(check::ssize(out), 1);
    if (out.size() == 1) CHECK_EQ(out[0].line, LineId{60});

    // Callbacks carry no cursor; repeating the demand appends the same target.
    pf->on_issued(CoreId{0}, ctx.k);
    pf->on_tile_start(CoreId{0});
    pf->on_demand(ctx, out);
    CHECK_EQ(check::ssize(out), 2);
    if (out.size() == 2) CHECK_EQ(out[1].line, LineId{44});
}

void test_nonpositive_distance_is_refused() {
    check::group("next_tile: a nonpositive distance is refused");
    CHECK_THROWS(std::invalid_argument, NextTilePrefetcher(0));
    CHECK_THROWS(std::invalid_argument, NextTilePrefetcher(-1));
}

// A context for line (1,1,16,4) of `tile`, whose distance-1 target is line 44.
PrefetchContext filter_ctx(const KhkwSplitMapper& mapper, const fx::FakeTrace& trace, int tile,
                           bool retrigger = false) {
    return PrefetchContext{Level::L2,  CoreId{0}, tile,  BurstIndex{7},
                           mapper.line_of(Coord{1, 1, 16, 4}), SimTime{0}, mapper, trace,
                           retrigger};
}

void test_min_touches_zero_is_the_current_policy() {
    check::group("next_tile filter: min_touches 0 is the current policy, with zero touches");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    NextTilePrefetcher pf(1, 0);
    std::vector<PrefetchTarget> out;
    pf.on_demand(filter_ctx(mapper, trace, tile), out);
    CHECK_EQ(check::ssize(out), 1);
    if (out.size() == 1) CHECK_EQ(out[0].line, LineId{44});
    CHECK_EQ(pf.filtered_triggers(), 0);
}

void test_filter_opens_at_min_touches_inclusive() {
    check::group("next_tile filter: emission opens at count >= min_touches");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    const PrefetchContext ctx = filter_ctx(mapper, trace, tile);
    NextTilePrefetcher pf(1, 3);
    std::vector<PrefetchTarget> out;

    for (int touch = 1; touch <= 2; ++touch) {
        pf.on_access(ctx.line, tile);
        pf.on_demand(ctx, out);
        CHECK_EQ(check::ssize(out), 0);
        CHECK_EQ(pf.filtered_triggers(), touch);
    }
    pf.on_access(ctx.line, tile);  // third touch: >= 3 opens the filter
    pf.on_demand(ctx, out);
    CHECK_EQ(check::ssize(out), 1);
    if (out.size() == 1) CHECK_EQ(out[0].line, LineId{44});
    CHECK_EQ(pf.filtered_triggers(), 2);
}

void test_counts_are_per_line() {
    check::group("next_tile filter: counts are per line");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    const PrefetchContext hot = filter_ctx(mapper, trace, tile);
    PrefetchContext cold      = hot;
    cold.line                 = mapper.line_of(Coord{0, 0, 0, 0});
    NextTilePrefetcher pf(1, 3);
    for (int touch = 0; touch < 3; ++touch) pf.on_access(hot.line, tile);
    pf.on_access(cold.line, tile);

    std::vector<PrefetchTarget> out;
    pf.on_demand(hot.line == cold.line ? cold : hot, out);
    CHECK_EQ(check::ssize(out), 1);
    out.clear();
    pf.on_demand(cold, out);
    CHECK_EQ(check::ssize(out), 0);
}

void test_counts_reset_at_the_tile_boundary() {
    check::group("next_tile filter: a new tile starts the line's count over");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile0 = trace.add_tile();
    const auto tile1 = trace.add_tile();
    NextTilePrefetcher pf(1, 3);
    const PrefetchContext in0 = filter_ctx(mapper, trace, tile0);
    for (int touch = 0; touch < 3; ++touch) pf.on_access(in0.line, tile0);

    std::vector<PrefetchTarget> out;
    PrefetchContext in1 = filter_ctx(mapper, trace, tile1);
    pf.on_access(in1.line, tile1);  // first touch of tile1 resets, then counts 1
    pf.on_demand(in1, out);
    CHECK_EQ(check::ssize(out), 0);
    pf.on_access(in1.line, tile1);
    pf.on_access(in1.line, tile1);
    pf.on_demand(in1, out);
    CHECK_EQ(check::ssize(out), 1);
}

void test_retrigger_is_exempt() {
    check::group("next_tile filter: a retrigger bypasses the filter at any count");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    NextTilePrefetcher pf(1, 3);
    std::vector<PrefetchTarget> out;
    pf.on_demand(filter_ctx(mapper, trace, tile, /*retrigger=*/true), out);
    CHECK_EQ(check::ssize(out), 1);
    CHECK_EQ(pf.filtered_triggers(), 0);
}

void test_negative_min_touches_is_refused() {
    check::group("next_tile filter: a negative min_touches is refused");
    CHECK_THROWS(std::invalid_argument, NextTilePrefetcher(1, -1));
}

void test_l2_engine_issues_forward_and_drains() {
    check::group("next_tile: L2 issues forward targets and drains all MSHRs");
    KhkwSplitMapper mapper(WeightShape{3, 3, 32, 16}, 16, 4, 1);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    trace.add_burst(tile, 0, 0, 0);
    trace.add_burst(tile, 0, 20, 4);
    trace.add_burst(tile, 0, 40, 8);

    EngineParams p;
    p.l1 = fx::level(16, 2, 8, 4);
    p.l2 = fx::level(32, 2, 8, 4);
    p.l1.cache_size_bytes *= mapper.line_size_bytes();
    p.l2.cache_size_bytes *= mapper.line_size_bytes();
    p.l2.prefetch_kind = PrefetchKind::NextTile;
    p.l2.prefetch_params = PrefetchParams{1, Axis::CIN, false, false};
    p.l2_miss_latency = SimTime{1};
    Engine engine(mapper, trace, p);
    engine.run();
    CHECK_TRUE(engine.stats().l2_pf_issued > 0);
    CHECK_EQ(engine.stats().l2_pf_issued_up, engine.stats().l2_pf_issued);
    CHECK_EQ(engine.stats().l2_pf_issued_down, 0);
    CHECK_EQ(engine.l1(CoreId{0}).mshrs().live(), 0);
    CHECK_EQ(engine.l2().mshrs().live(), 0);
    CHECK_EQ(engine.stats().pf_outstanding.at(0), 0);
}

}  // namespace

int main() {
    test_exact_targets_and_boundaries();
    test_nonpositive_distance_is_refused();
    test_min_touches_zero_is_the_current_policy();
    test_filter_opens_at_min_touches_inclusive();
    test_counts_are_per_line();
    test_counts_reset_at_the_tile_boundary();
    test_retrigger_is_exempt();
    test_negative_min_touches_is_refused();
    test_l2_engine_issues_forward_and_drains();
    return check::summary();
}
