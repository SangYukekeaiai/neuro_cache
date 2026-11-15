#include <cachesim/config.h>
#include <cachesim/core/engine.h>
#include <cachesim/enum_names.h>
#include <cachesim/layout/block_pack.h>
#include <cachesim/prefetch/next_line.h>
#include <cachesim/sweep.h>
#include <cachesim/trace/byte_source.h>
#include <cachesim/trace/stream_trace.h>

#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"
#include "stream_builder.h"

using namespace cachesim;

namespace {

void test_candidates() {
    check::group("next_line: ordered physical lines, append, default degree and extent");
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    // No future bursts: a trace-lookahead implementation cannot produce these targets.
    trace.add_burst(tile, 0, 0, 3);
    // LinearMapper::neighbour returns nullopt, so this also detects neighbour lookup.
    fx::LinearMapper mapper(8);
    for (const auto level : {Level::L1, Level::L2}) {
        const PrefetchContext ctx{level, CoreId{0}, tile, BurstIndex{0}, LineId{3},
                                  SimTime{0}, mapper, trace};
        std::vector<PrefetchTarget> out{{LineId{7}, BurstIndex{9}}};
        NextLinePrefetcher one;
        one.on_demand(ctx, out);
        CHECK_EQ(check::ssize(out), 2);
        CHECK_EQ(out.front().line, LineId{7});
        CHECK_EQ(out.front().burst, BurstIndex{9});
        CHECK_EQ(out.back().line, LineId{4});
        CHECK_EQ(out.back().burst, ctx.k);

        NextLinePrefetcher deep(3);
        out.clear();
        deep.on_demand(ctx, out);
        CHECK_EQ(check::ssize(out), 3);
        for (std::size_t i = 0; i < out.size(); ++i) {
            CHECK_EQ(out[i].line, LineId{4 + static_cast<std::int64_t>(i)});
            CHECK_EQ(out[i].burst, ctx.k);
        }
        auto factory = make_prefetcher(PrefetchKind::NextLine, PrefetchParams{3}, 1);
        out.clear();
        factory->on_demand(ctx, out);
        CHECK_EQ(check::ssize(out), 3);
        CHECK_EQ(out.back().line, LineId{6});

        for (std::int64_t line : {6, 7}) {
            const PrefetchContext edge{level, CoreId{0}, tile, BurstIndex{0}, LineId{line},
                                       SimTime{0}, mapper, trace};
            out.clear();
            deep.on_demand(edge, out);
            CHECK_EQ(check::ssize(out), 7 - line);
            if (!out.empty()) CHECK_EQ(out.front().line, LineId{7});
        }
    }
    for (std::int64_t line : {-1, 8}) {
        const PrefetchContext invalid{Level::L1, CoreId{0}, tile, BurstIndex{0}, LineId{line},
                                      SimTime{0}, mapper, trace};
        std::vector<PrefetchTarget> untouched{{LineId{2}, BurstIndex{5}}};
        NextLinePrefetcher one;
        CHECK_THROWS(std::out_of_range, one.on_demand(invalid, untouched));
        CHECK_EQ(check::ssize(untouched), 1);
        CHECK_EQ(untouched.front().line, LineId{2});
        CHECK_EQ(untouched.front().burst, BurstIndex{5});
    }
    // The addition must be bounded before it can overflow a physical line id.
    const auto end = std::numeric_limits<std::int64_t>::max();
    fx::LinearMapper huge(end);
    const PrefetchContext edge{Level::L1, CoreId{0}, tile, BurstIndex{0}, LineId{end - 2},
                               SimTime{0}, huge, trace};
    std::vector<PrefetchTarget> out;
    NextLinePrefetcher deep(3);
    deep.on_demand(edge, out);
    CHECK_EQ(check::ssize(out), 1);
    CHECK_EQ(out.front().line, LineId{end - 1});
    CHECK_THROWS(std::invalid_argument, NextLinePrefetcher(0));
    CHECK_THROWS(std::invalid_argument, NextLinePrefetcher(-1));
    CHECK_THROWS(std::invalid_argument,
                 make_prefetcher(PrefetchKind::NextLine, PrefetchParams{0}, 1));
}

RunConfig validated(const std::string& json) {
    auto cfg = parse_config(json);
    std::vector<Warning> warnings;
    validate(cfg, 1, warnings);
    return cfg;
}

void test_config() {
    check::group("next_line: both levels, omitted degree, explicit zero and aliases");
    CHECK_TRUE(std::string(name_of(PrefetchKind::NextLine)) == "next_line");
    for (const std::string policy : {"l1_prefetch_policy", "prefetch_policy"}) {
        const auto cfg = validated("{\"" + policy +
            "\":\"next_line\",\"l2_prefetch_policy\":\"next_line\"}");
        CHECK_TRUE(cfg.l1_prefetch_policy == PrefetchKind::NextLine);
        CHECK_TRUE(cfg.l2_prefetch_policy == PrefetchKind::NextLine);
        CHECK_EQ(cfg.l1_prefetch_distance, 1);
        CHECK_EQ(cfg.prefetch_distance, 1);
        CHECK_EQ(cfg.l2_prefetch_distance, 1);
        CHECK_TRUE(cfg.l2_prefetch_trigger == L2Trigger::Miss);
        const auto params = to_engine_params(cfg);
        CHECK_TRUE(params.l1.prefetch_kind == PrefetchKind::NextLine);
        CHECK_TRUE(params.l2.prefetch_kind == PrefetchKind::NextLine);
        CHECK_EQ(params.l1.prefetch_params.distance, 1);
        CHECK_EQ(params.l2.prefetch_params.distance, 1);
        for (const std::string distance : {"l1_prefetch_distance", "prefetch_distance"}) {
            const std::string prefix = "{\"" + policy + "\":\"next_line\",\"" + distance + "\":";
            CHECK_THROWS(std::invalid_argument, validated(prefix + "0}"));
            CHECK_THROWS(std::invalid_argument, validated(prefix + "-1}"));
            const auto explicit_degree = validated(prefix + "3}");
            CHECK_EQ(explicit_degree.l1_prefetch_distance, 3);
            CHECK_EQ(to_engine_params(explicit_degree).l1.prefetch_params.distance, 3);
        }
    }
    CHECK_THROWS(std::invalid_argument, validated(
        R"({"l2_prefetch_policy":"next_line","l2_prefetch_distance":0})"));
    CHECK_THROWS(std::invalid_argument, validated(
        R"({"l2_prefetch_policy":"next_line","l2_prefetch_distance":-1})"));
    CHECK_EQ(validated(R"({"l2_prefetch_policy":"next_line","l2_prefetch_distance":3})")
                 .l2_prefetch_distance, 3);
    CHECK_EQ(validated("{}").l1_prefetch_distance, 0);
    CHECK_THROWS(std::invalid_argument, validated(R"({"l1_prefetch_policy":"next_access"})"));
}

EngineParams engine_params(Level level, int degree) {
    EngineParams p;
    p.l1 = fx::level(16, 2, 8, 8, 1);
    p.l2 = fx::level(32, 2, 8, 8, 1);
    p.l2_miss_latency = SimTime{20};
    auto& selected = level == Level::L1 ? p.l1 : p.l2;
    selected.prefetch_kind = PrefetchKind::NextLine;
    selected.prefetch_params.distance = degree;
    return p;
}

void drained(Engine& engine) {
    CHECK_EQ(engine.l1(CoreId{0}).mshrs().live(), 0);
    CHECK_EQ(engine.l2().mshrs().live(), 0);
    CHECK_EQ(engine.stats().pf_outstanding.at(0), 0);
}

void test_engine_drops() {
    check::group("next_line: engine residency and existing MSHR drops at both levels");
    for (const auto level : {Level::L1, Level::L2}) {
        check::group(level == Level::L1 ? "next_line: L1 residency / pending entry"
                                       : "next_line: L2 residency / pending entry");
        fx::LinearMapper mapper(16);
        fx::FakeTrace resident(1);
        auto tile = resident.add_tile();
        resident.add_burst(tile, 0, 0, 1);
        resident.add_burst(tile, 0, 100, 0);
        Engine hit(mapper, resident, engine_params(level, 1));
        hit.run();
        CHECK_EQ(level == Level::L1 ? hit.stats().pf_dropped_array_hit
                                    : hit.stats().l2_pf_dropped_array_hit, 1);
        CHECK_EQ(hit.stats().dram_accesses, 3);
        drained(hit);

        fx::FakeTrace pending(level == Level::L1 ? 1 : 2);
        tile = pending.add_tile();
        if (level == Level::L1) {
            // Both demand lines trigger L1 candidates before the fills return.
            pending.add_burst(tile, 0, 0, 0, 2);
        } else {
            // Descending demands on independent cores both miss. Ascending demands
            // would merge into the first prefetch and would not trigger L2 again.
            // Demand 1 launches 2,3; demand 0 then proposes in-flight 1,2.
            pending.add_burst(tile, 0, 0, 1);
            pending.add_burst(tile, 1, 1, 0);
        }
        Engine entry(mapper, pending, engine_params(level, 2));
        entry.run();
        CHECK_TRUE((level == Level::L1 ? entry.stats().pf_dropped_entry
                                       : entry.stats().l2_pf_dropped_entry) > 0);
        CHECK_EQ(entry.stats().dram_accesses, 4);
        drained(entry);
        if (level == Level::L2) {
            CHECK_EQ(entry.stats().l2_pf_dropped_entry, 2);
            CHECK_EQ(entry.stats().l2_pf_issued, 4);
            CHECK_EQ(entry.l1(CoreId{1}).mshrs().live(), 0);
            CHECK_EQ(entry.stats().pf_outstanding.at(1), 0);
        }
    }

    check::group("next_line: L1 budget and L2 MSHR capacity/reserve refuse optional work");
    fx::LinearMapper mapper(16);
    fx::FakeTrace trace(1);
    const auto tile = trace.add_tile();
    trace.add_burst(tile, 0, 0, 0);
    auto p = engine_params(Level::L1, 3);
    p.l1.mshrs = 2;
    p.l1.demand_reserve = 1;
    Engine budget(mapper, trace, p);
    budget.run();
    CHECK_EQ(budget.stats().pf_budget_exhausted, 1);
    CHECK_EQ(budget.stats().pf_issued, 1);
    // One candidate gets an issue credit; triage then sees the demand occupying
    // one of two MSHRs and protects the remaining reserve. Only demand reaches DDR.
    CHECK_EQ(budget.stats().pf_dropped_reserve, 1);
    CHECK_EQ(budget.stats().pf_dropped_no_slot, 0);
    CHECK_EQ(budget.stats().dram_accesses, 1);
    drained(budget);
    for (int reserve : {0, 1}) {
        p = engine_params(Level::L2, 3);
        p.l2.mshrs = 2;
        p.l2.demand_reserve = reserve;
        Engine limited(mapper, trace, p);
        limited.run();
        CHECK_EQ(limited.stats().l2_pf_issued, 3);
        CHECK_EQ(limited.stats().l2_pf_dropped_no_slot, reserve == 0 ? 2 : 0);
        CHECK_EQ(limited.stats().l2_pf_dropped_reserve, reserve == 1 ? 3 : 0);
        CHECK_EQ(limited.stats().dram_accesses, reserve == 0 ? 2 : 1);
        drained(limited);
    }
}

void test_grid_sweep() {
    check::group("next_line: grid cross product reaches both policies in BroadcastSweep");
    auto configs = parse_config_grid(R"({"base":{},"axes":{
        "l1_prefetch_policy":["none","next_line"],
        "l2_prefetch_policy":["none","next_line"]}})");
    CHECK_EQ(check::ssize(configs), 4);
    for (auto& cfg : configs) {
        std::vector<Warning> warnings;
        validate(cfg, 1, warnings);
    }
    fx::StreamBuilder builder(1, 1);
    builder.begin_tile(0, 1);
    builder.begin_core(0);
    builder.add_burst(0, 0, 0, 0, 0, 16);
    builder.end_tile();
    const auto bytes = builder.finish();
    MemByteSource source(bytes);
    StreamingTileTrace trace(source);
    BlockPackMapper mapper(shape_of(trace.header()), 1, 16, 1);
    BroadcastSweep sweep(trace, mapper, configs, 4);
    sweep.run();
    for (std::size_t i = 0; i < configs.size(); ++i) {
        auto& engine = sweep.engine(i);
        CHECK_EQ(engine.stats().pf_issued, i >= 2 ? 1 : 0);
        CHECK_EQ(engine.stats().l2_pf_issued, i % 2 == 1 ? 1 : 0);
        drained(engine);
    }
}

void test_production_config(const char* path) {
    check::group("next_line: supplied production B config reaches both cache levels");
    std::ifstream input(path);
    CHECK_TRUE(input.is_open());
    if (!input.is_open()) return;
    const std::string json((std::istreambuf_iterator<char>(input)),
                           std::istreambuf_iterator<char>());
    const auto cfg = validated(json);
    CHECK_TRUE(cfg.l1_prefetch_policy == PrefetchKind::NextLine);
    CHECK_TRUE(cfg.l2_prefetch_policy == PrefetchKind::NextLine);
    const auto params = to_engine_params(cfg);
    CHECK_TRUE(params.l1.prefetch_kind == PrefetchKind::NextLine);
    CHECK_TRUE(params.l2.prefetch_kind == PrefetchKind::NextLine);
    CHECK_EQ(params.l1.prefetch_params.distance, cfg.l1_prefetch_distance);
    CHECK_EQ(params.l2.prefetch_params.distance, cfg.l2_prefetch_distance);
}

}  // namespace

int main(int argc, char** argv) {
    test_candidates();
    test_config();
    test_engine_drops();
    test_grid_sweep();
    CHECK_TRUE(argc <= 2);
    if (argc == 2) test_production_config(argv[1]);
    return check::summary();
}
