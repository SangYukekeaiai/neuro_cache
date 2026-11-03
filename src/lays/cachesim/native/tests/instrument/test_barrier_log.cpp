// BarrierLog (T22): one row per (tile, core) at every barrier, and inertness.
//
// Two properties, each the reason the instrument is usable as evidence:
//
//   1. The rows restate the engine's own accounting exactly: summed over a
//      core's rows, `tile_end - arrival` IS `stall_barrier[c]`, and the last
//      row's cumulative columns ARE the engine's final per-core counters.
//      ORACLE in B121's sense: the expected side is the engine's results-row
//      counters, which the log is forbidden to feed.
//
//   2. Attaching the log changes nothing the engine computes (SELF, and kept
//      because the property IS "these two runs agree"): a run with the log and
//      a run without produce identical stats.
#include <cachesim/instrument/barrier_log.h>

#include <cachesim/core/engine.h>
#include <cachesim/types.h>

#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace cachesim;
using fx::FakeTrace;
using fx::LinearMapper;

namespace {

// Three cores, two tiles, with real L2 traffic: a tiny L1 so bursts miss into
// the L2 and the l2_demand column has something to count.
FakeTrace small_trace() {
    FakeTrace tr(3);
    const std::int32_t t0 = tr.add_tile(3);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 2, 1);
    tr.add_burst(t0, 1, 1, 3);
    tr.add_burst(t0, 2, 0, 5);
    tr.add_burst(t0, 2, 4, 6);
    const std::int32_t t1 = tr.add_tile(1);
    tr.add_burst(t1, 0, 2, 9);
    tr.add_burst(t1, 1, 0, 11);
    // Core 2 contributes nothing to tile 1 and still gets a row.
    return tr;
}

std::vector<std::vector<std::int64_t>> data_rows(const std::string& text) {
    std::vector<std::vector<std::int64_t>> rows;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#' || line[0] == 't') continue;  // header row
        std::vector<std::int64_t> row;
        std::istringstream cells(line);
        std::string cell;
        while (std::getline(cells, cell, ',')) row.push_back(std::stoll(cell));
        rows.push_back(row);
    }
    return rows;
}

void test_one_row_per_tile_core_and_the_rows_restate_the_stats() {
    check::group("BarrierLog: ORACLE -- rows restate stall_barrier and the per-core counters");

    FakeTrace tr = small_trace();
    LinearMapper map(64);
    EngineParams p = fx::unbounded_params(4, 2);  // 8-line L1: tile 2 traffic misses
    p.l2_miss_latency = SimTime{4};

    Engine eng(map, tr, p);
    std::ostringstream out;
    BarrierLog log(out, tr.n_cores());
    log.write_header();
    eng.set_barrier_log(&log);
    eng.run();

    const auto rows = data_rows(out.str());
    CHECK_EQ(check::ssize(rows), std::int64_t{tr.n_tiles() * tr.n_cores()});
    CHECK_EQ(log.written(), std::int64_t{tr.n_tiles() * tr.n_cores()});

    // Columns: tile,core,arrival,tile_end,core_stall,fetch_latency,6 stalls,
    // channel,l2_demand,l2_demand_hits,l2_l1pf,l2_l1pf_hits.
    std::vector<std::int64_t> slack_sum(3, 0);
    for (const auto& r : rows) {
        CHECK_EQ(check::ssize(r), std::int64_t{17});
        CHECK_TRUE(r[3] >= r[2]);  // tile_end >= arrival
        slack_sum.at(static_cast<std::size_t>(r[1])) += r[3] - r[2];
        // tile_end is the barrier's own instant, which is tile_origin[N+1].
        CHECK_EQ(r[3], eng.tile_origin(static_cast<std::int32_t>(r[0]) + 1).get());
    }
    std::int64_t l2_demand_last = 0, l2_demand_hits_last = 0;
    for (std::int32_t c = 0; c < 3; ++c) {
        const std::size_t i = static_cast<std::size_t>(c);
        CHECK_EQ(slack_sum[i], eng.stats().stall_barrier[i]);
        const auto& last = rows.at(static_cast<std::size_t>(tr.n_tiles() - 1) * 3 + i);
        CHECK_EQ(last[4], eng.stats().core_stall[i]);
        CHECK_EQ(last[5], eng.stats().fetch_latency[i]);
        CHECK_EQ(last[10], eng.stats().stall_l2_line[i]);
        CHECK_EQ(last[12], eng.stats().stall_channel[i]);
        l2_demand_last += last[13];
        l2_demand_hits_last += last[14];
    }
    // The per-core L2 probe counts sum to the engine's own totals. Exact
    // because nothing here is ever refused (unbounded ports): no re-probes.
    CHECK_EQ(l2_demand_last, eng.stats().l2_accesses);
    CHECK_EQ(l2_demand_hits_last, eng.stats().l2_hits);
    CHECK_TRUE(eng.stats().l2_accesses > 0);
}

void test_attaching_the_log_changes_nothing() {
    check::group("BarrierLog: SELF -- a logged run and a bare run agree");

    FakeTrace tr = small_trace();
    LinearMapper map(64);
    EngineParams p = fx::unbounded_params(4, 2);
    p.l2_miss_latency = SimTime{4};

    Engine bare(map, tr, p);
    bare.run();

    Engine logged(map, tr, p);
    std::ostringstream out;
    BarrierLog log(out, tr.n_cores());
    logged.set_barrier_log(&log);
    logged.run();

    CHECK_EQ(logged.tile_origin(tr.n_tiles()), bare.tile_origin(tr.n_tiles()));
    CHECK_EQ(logged.stats().l2_accesses, bare.stats().l2_accesses);
    CHECK_EQ(logged.stats().events, bare.stats().events);
    for (std::size_t c = 0; c < 3; ++c) {
        CHECK_EQ(logged.stats().stall_barrier[c], bare.stats().stall_barrier[c]);
        CHECK_EQ(logged.stats().core_stall[c], bare.stats().core_stall[c]);
    }
}

}  // namespace

int main() {
    test_one_row_per_tile_core_and_the_rows_restate_the_stats();
    test_attaching_the_log_changes_nothing();
    return check::summary();
}
