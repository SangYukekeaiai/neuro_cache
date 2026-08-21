// Task 13 (D2c): the results CSV schema, RunStats, check_invariants and the
// oracle row.
//
// The failure mode this file exists to catch is a schema that drifts from its
// own header: a row whose cells stop lining up with csv_columns() joins
// silently and wrongly downstream. So the column list is pinned by name and by
// count, and every row built here is checked against the header's arity.
#include <wcache/config.h>
#include <wcache/engine.h>
#include <wcache/stats.h>
#include <wcache/stream_format.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <sstream>
#include <stdexcept>
#include <string>
#include <typeinfo>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;

namespace {

// EXACT type, not "or anything derived from it". CHECK_THROWS catches a derived
// type and reports a pass, which is how a sibling unit lost a real bug: a
// std::out_of_range escaping where a std::logic_error was expected satisfies
// CHECK_THROWS(std::logic_error, ...) because out_of_range derives from it.
// Returns the message on an exact match, a marker otherwise, so the caller
// asserts on both the type and what the message names.
template <typename Exc, typename Fn>
std::string exactly_thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::exception& caught) {
        if (typeid(caught) == typeid(Exc)) return caught.what();
        return std::string("<wrong type: ") + typeid(caught).name() + ": " + caught.what() + ">";
    } catch (...) {
        return "<non-std exception>";
    }
    return "<no exception>";
}

bool mentions(const std::string& haystack, const char* needle) {
    return haystack.find(needle) != std::string::npos;
}

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> out;
    std::string cell;
    std::istringstream in(line);
    while (std::getline(in, cell, ',')) out.push_back(cell);
    // getline drops a trailing empty field, and the last column may legitimately
    // be empty (an oracle row ends in two empty cells), so restore it by
    // counting separators instead of trusting the split.
    const std::size_t seps = static_cast<std::size_t>(
        std::count(line.begin(), line.end(), ','));
    while (out.size() < seps + 1) out.push_back(std::string());
    return out;
}

std::string cell_of(const std::string& row, const char* column) {
    const std::vector<std::string> head = split_csv(csv_header());
    const std::vector<std::string> cells = split_csv(row);
    for (std::size_t i = 0; i < head.size(); ++i) {
        if (head[i] == column && i < cells.size()) return cells[i];
    }
    return "<no such column>";
}

RunConfig default_config() {
    RunConfig cfg = parse_config("{}");
    std::vector<Warning> w;
    validate(cfg, 1, w);
    return cfg;
}

stream::StreamHeader header_for(std::int32_t n_tiles, std::int32_t n_cores) {
    stream::StreamHeader hdr;
    hdr.n_tiles    = n_tiles;
    hdr.n_cores    = n_cores;
    hdr.arch       = "loas";
    hdr.workload   = "vgg16_T4_all";
    hdr.layer      = "layer_01_features_3";
    hdr.sample_idx = 0;
    return hdr;
}

// A real two-tile, two-core run, so no row in this file is hand made. Built as
// a function because Engine takes the trace by reference at construction and
// the trace must be fully populated first.
void build_trace(fx::FakeTrace& tr) {
    const std::int32_t t0 = tr.add_tile(4);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 1, 1);
    tr.add_burst(t0, 1, 0, 2);
    const std::int32_t t1 = tr.add_tile(4);
    tr.add_burst(t1, 0, 0, 3);
    tr.add_burst(t1, 1, 1, 0);
}

void test_the_column_list_is_pinned() {
    check::group("Task 13: the CSV schema is exactly kCsvColumnCount columns, in order");
    const std::vector<std::string>& cols = csv_columns();
    // 90 until `stall_l1_port` was added, which is the column V21's partition
    // was missing. The plan's ordered list is the normative artifact and now
    // has 91 entries; the 91 the plan's PROSE used to say was an unrelated
    // arithmetic error against a 90-entry list.
    CHECK_EQ(check::ssize(cols), std::int64_t{91});
    CHECK_TRUE(cols.front() == "run_id");
    CHECK_TRUE(cols.back() == "distinct_addr_per_core_tile_max");
    bool has_total = false, has_pad = false, has_hidden = false, has_sets = false;
    for (const std::string& c : cols) {
        if (c == "total_cycles")     has_total  = true;
        if (c == "padding_fraction") has_pad    = true;
        if (c == "hidden_latency")   has_hidden = true;
        if (c == "l1_num_sets")      has_sets   = true;
    }
    CHECK_TRUE(has_total);
    CHECK_TRUE(has_pad);
    CHECK_TRUE(has_hidden);
    CHECK_TRUE(has_sets);
}

void test_no_column_is_named_twice() {
    check::group("Task 13: no column name repeats");
    std::vector<std::string> sorted = csv_columns();
    std::sort(sorted.begin(), sorted.end());
    CHECK_EQ(check::ssize(sorted),
             static_cast<std::int64_t>(std::unique(sorted.begin(), sorted.end()) - sorted.begin()));
}

void test_the_header_is_the_column_list_joined() {
    check::group("Task 13: the header row IS csv_columns(), in order");
    const std::vector<std::string> head = split_csv(csv_header());
    const std::vector<std::string>& cols = csv_columns();
    CHECK_EQ(check::ssize(head), check::ssize(cols));
    bool same = head.size() == cols.size();
    for (std::size_t i = 0; same && i < cols.size(); ++i) same = head[i] == cols[i];
    CHECK_TRUE(same);
}

void test_l2_demand_reserve_is_not_a_column() {
    check::group("Task 13: l2_demand_reserve is NOT a column (G11, ruling Q8)");
    for (const std::string& c : csv_columns()) CHECK_TRUE(c != "l2_demand_reserve");
}

void test_the_header_and_a_row_have_the_same_field_count() {
    check::group("Task 13: header and row agree on arity");
    fx::FakeTrace tr(2);
    build_trace(tr);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();

    const RunConfig cfg = default_config();
    const stream::StreamHeader hdr = header_for(tr.n_tiles(), tr.n_cores());
    const RowIdentity id{"run-0", "deadbeef", "cache", "tier0"};
    const RunStats st(id, cfg, hdr, e.stats(), e.tile_origin(tr.n_tiles()).get(),
                      tr.tick_base(tr.n_tiles()), 0.0, 0.001, 1, 1);
    const std::string row = st.csv_row();
    CHECK_EQ(check::ssize(split_csv(row)), check::ssize(split_csv(csv_header())));
    st.check_invariants();  // must not throw

    // The identity and the headline land in the columns that name them.
    CHECK_TRUE(cell_of(row, "run_id") == "run-0");
    CHECK_TRUE(cell_of(row, "arm") == "cache");
    CHECK_TRUE(cell_of(row, "arch") == "loas");
    CHECK_TRUE(cell_of(row, "total_cycles") ==
               std::to_string(e.tile_origin(tr.n_tiles()).get()));
    CHECK_TRUE(cell_of(row, "tick_base_total") ==
               std::to_string(tr.tick_base(tr.n_tiles())));
    // V1: unbounded, so the makespan IS the trace's own timeline and the stretch
    // is zero. An ORACLE, not a self-comparison: tick_base comes from the trace.
    CHECK_TRUE(cell_of(row, "stretch_cycles") == "0");
    // Derived cells, each against a value computed outside RunStats.
    CHECK_TRUE(cell_of(row, "line_size_bytes") == std::to_string(cfg.line_size_bytes()));
    CHECK_TRUE(cell_of(row, "l1_num_sets") == std::to_string(cfg.l1_num_sets()));
    CHECK_TRUE(cell_of(row, "dram_bytes") ==
               std::to_string(e.stats().dram_accesses * cfg.line_size_bytes()));
    // Part 8's coverage ceiling, "the fraction of bursts that are not
    // first-in-tile", computed from the TRACE rather than read back out of the
    // engine: 5 bursts, of which 4 open a (core, tile), leaves 1 eligible.
    std::int64_t bursts = 0, eligible = 0;
    for (std::int32_t t = 0; t < tr.n_tiles(); ++t) {
        for (std::int32_t c = 0; c < tr.n_cores(); ++c) {
            const std::int32_t n = tr.n_bursts(CoreId{c}, t);
            bursts += n;
            if (n > 0) eligible += n - 1;
        }
    }
    CHECK_EQ(bursts, std::int64_t{5});
    CHECK_EQ(eligible, std::int64_t{1});
    char want[32];
    std::snprintf(want, sizeof want, "%.6f",
                  static_cast<double>(eligible) / static_cast<double>(bursts));
    CHECK_TRUE(cell_of(row, "pf_coverage_ceiling") == want);
    CHECK_TRUE(cell_of(row, "pf_coverage") == "0.000000");  // no prefetcher is on

    CHECK_TRUE(cell_of(row, "policy") == "lru");
    CHECK_TRUE(cell_of(row, "inclusion") == "non_inclusive");
    CHECK_TRUE(cell_of(row, "prefetch_policy") == "none");

    std::printf("  sample row:\n%s\n", row.c_str());
}

void test_a_known_zero_column_is_present_and_zero() {
    check::group("Task 13: the two structurally-zero columns exist and read 0");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), e.stats(), e.tile_origin(1).get(),
                      tr.tick_base(1), 0.0, 0.0, 0, 0);
    const std::string row = st.csv_row();
    // stall_l1_line is unreachable under a 1:1 mapper and pf_dropped_targets_full
    // is structurally unreachable in this engine. Both are columns because §9.2
    // names them, and 0 is the answer the schema needs.
    CHECK_TRUE(cell_of(row, "stall_l1_line") == "0");
    CHECK_TRUE(cell_of(row, "pf_dropped_targets_full") == "0");
}

void test_an_undefined_ratio_is_empty_not_a_nan() {
    check::group("Task 13: a zero denominator gives an empty cell, never nan or inf");
    fx::FakeTrace tr(1);
    tr.add_tile(1);  // one tile, no bursts at all: every denominator is 0
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), e.stats(), e.tile_origin(1).get(),
                      tr.tick_base(1), 0.0, 0.0, 0, 0);
    const std::string row = st.csv_row();
    CHECK_TRUE(!mentions(row, "nan"));
    CHECK_TRUE(!mentions(row, "inf"));
    CHECK_TRUE(cell_of(row, "l1_hit_rate").empty());
    CHECK_TRUE(cell_of(row, "hidden_fraction").empty());
    CHECK_TRUE(cell_of(row, "port_bound_threshold").empty());
    CHECK_EQ(check::ssize(split_csv(row)), check::ssize(split_csv(csv_header())));
}

void test_an_identity_carrying_a_comma_is_rejected() {
    check::group("Task 13: a cell that would break the CSV is refused, not quoted");
    stream::StreamHeader hdr = header_for(1, 1);
    hdr.layer = "layer,with,commas";
    const std::string msg = exactly_thrown_by<std::invalid_argument>(
        [&] { (void)oracle_row(RowIdentity{"r", "", "spad_oracle", ""}, default_config(), hdr, 0); });
    CHECK_TRUE(mentions(msg, "layer,with,commas"));

    stream::StreamHeader nl = header_for(1, 1);
    nl.workload = "has\nnewline";
    CHECK_TRUE(mentions(exactly_thrown_by<std::invalid_argument>(
                            [&] { (void)oracle_row(RowIdentity{"r", "", "cache", ""},
                                                   default_config(), nl, 0); }),
                        "newline"));

    RowIdentity quoted{"r\"q", "", "cache", ""};
    CHECK_TRUE(mentions(exactly_thrown_by<std::invalid_argument>(
                            [&] { (void)oracle_row(quoted, default_config(),
                                                   header_for(1, 1), 0); }),
                        "run_id"));
}

void test_check_invariants_catches_a_broken_stall_sum() {
    check::group("Task 13: a stall breakdown that does not sum throws (V21)");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    EngineStats broken = e.stats();
    broken.stall_total[0] += 7;  // the eight causes no longer sum to the total
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), broken, 2, 2, 0.0, 0.0, 0, 0);
    const std::string msg = exactly_thrown_by<std::logic_error>([&] { st.check_invariants(); });
    CHECK_TRUE(mentions(msg, "V21"));
    CHECK_TRUE(mentions(msg, "stall_total"));
    // Both sides are named, with the numbers the caller can act on. Computed
    // here from the engine's own vectors, not read back out of the message.
    std::int64_t causes = 0, tot = 0;
    for (std::size_t c = 0; c < broken.stall_total.size(); ++c) {
        causes += broken.stall_l1_slot[c] + broken.stall_l1_line[c] + broken.stall_l1_port[c] +
                  broken.stall_l2_slot[c] + broken.stall_l2_line[c] + broken.stall_l2_port[c] +
                  broken.stall_channel[c] + broken.stall_barrier[c];
        tot += broken.stall_total[c];
    }
    CHECK_EQ(tot, causes + 7);
    CHECK_TRUE(mentions(msg, std::to_string(causes).c_str()));
    CHECK_TRUE(mentions(msg, std::to_string(tot).c_str()));
}

void test_v21_is_an_equality_at_every_l1_latency() {
    check::group("Task 13: V21 is an equality at every l1_latency");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();

    // An L1 hit's own access time used to be the legal remainder above
    // l1_latency 0. It is `stall_l1_port` now, so a remainder is a bug at every
    // latency and the check no longer has a lenient branch to fall into.
    RunConfig hot   = default_config();
    hot.l1_latency  = 1;
    EngineStats unbucketed = e.stats();
    unbucketed.stall_total[0] += 7;
    const RunStats short_by_seven(RowIdentity{"r", "", "cache", ""}, hot, header_for(1, 1),
                                  unbucketed, 2, 2, 0.0, 0.0, 0, 0);
    CHECK_TRUE(mentions(exactly_thrown_by<std::logic_error>(
                            [&] { short_by_seven.check_invariants(); }), "V21"));

    // And in the other direction: causes summing ABOVE the total is double
    // counting, at any l1_latency.
    EngineStats over = e.stats();
    over.stall_barrier[0] += 3;
    const RunStats st(RowIdentity{"r", "", "cache", ""}, hot, header_for(1, 1), over,
                      2, 2, 0.0, 0.0, 0, 0);
    CHECK_TRUE(mentions(exactly_thrown_by<std::logic_error>([&] { st.check_invariants(); }),
                        "V21"));

    // The unmodified run passes at a nonzero l1_latency, so the two throws
    // above are the tampering and not the latency.
    const RunStats clean(RowIdentity{"r", "", "cache", ""}, hot, header_for(1, 1), e.stats(),
                         2, 2, 0.0, 0.0, 0, 0);
    clean.check_invariants();
}

void test_check_invariants_catches_a_negative_hidden_latency() {
    check::group("Task 13: hidden_latency below zero throws (ruling R8)");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    EngineStats broken = e.stats();
    broken.core_stall[0] += 5;  // stall above fetch latency: R8 says impossible
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), broken, 2, 2, 0.0, 0.0, 0, 0);
    const std::string msg = exactly_thrown_by<std::logic_error>([&] { st.check_invariants(); });
    CHECK_TRUE(mentions(msg, "hidden_latency"));
    CHECK_TRUE(mentions(msg, "-5"));
}

void test_check_invariants_catches_a_broken_prefetch_sum() {
    check::group("Task 13: the four prefetch outcomes plus the drops must sum to pf_issued");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    EngineStats broken = e.stats();
    broken.pf_issued += 2;
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), broken, 2, 2, 0.0, 0.0, 0, 0);
    CHECK_TRUE(mentions(exactly_thrown_by<std::logic_error>([&] { st.check_invariants(); }),
                        "pf_issued"));
}

void test_percentiles_read_the_occupancy_samples() {
    check::group("Task 13: p50/p95/max reduce the MSHR occupancy samples");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper(64);
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    EngineStats s = e.stats();
    // A hand-made sample set with a known answer, so the reduction is checked
    // against arithmetic and not against itself. Deliberately unsorted.
    s.l1_mshr_occupancy = {3, 1, 4, 1, 5, 9, 2, 6, 5, 3};  // sorted: 1 1 2 3 3 4 5 5 6 9
    s.l2_mshr_occupancy.clear();
    const RunStats st(RowIdentity{"r", "", "cache", ""}, default_config(),
                      header_for(1, 1), s, 2, 2, 0.0, 0.0, 0, 0);
    const std::string row = st.csv_row();
    // Nearest-rank, index min(n-1, floor(q*n)): p50 -> index 5, p95 -> index 9.
    CHECK_TRUE(cell_of(row, "l1_mshr_occ_p50") == "4");
    CHECK_TRUE(cell_of(row, "l1_mshr_occ_p95") == "9");
    CHECK_TRUE(cell_of(row, "l1_mshr_occ_max") == "9");
    CHECK_TRUE(cell_of(row, "l2_mshr_occ_p50").empty());
    CHECK_TRUE(cell_of(row, "l2_mshr_occ_max").empty());
}

void test_the_oracle_row_needs_no_engine() {
    check::group("Task 13: the spad_oracle arm is a row with no simulation");
    const stream::StreamHeader hdr = header_for(32, 8);
    const RowIdentity id{"run-0", "", "spad_oracle", "tier1"};
    const std::string row = oracle_row(id, default_config(), hdr, 4096);
    CHECK_EQ(check::ssize(split_csv(row)), check::ssize(split_csv(csv_header())));
    CHECK_TRUE(cell_of(row, "arm") == "spad_oracle");
    CHECK_TRUE(cell_of(row, "total_cycles") == "4096");
    CHECK_TRUE(cell_of(row, "tick_base_total") == "4096");
    CHECK_TRUE(cell_of(row, "stretch_cycles") == "0");
    CHECK_TRUE(cell_of(row, "n_cores") == "8");
    // The configuration is still reported: an oracle row must join to its
    // cache rows on the same keys.
    CHECK_TRUE(cell_of(row, "l1_size_bytes") == std::to_string(default_config().l1_size_bytes));
    // Every simulated column is empty rather than a misleading zero.
    CHECK_TRUE(cell_of(row, "l1_hits").empty());
    CHECK_TRUE(cell_of(row, "stall_total").empty());
    CHECK_TRUE(cell_of(row, "events").empty());
    CHECK_TRUE(cell_of(row, "hidden_latency").empty());
    CHECK_TRUE(!mentions(row, "nan"));
    std::printf("  oracle row:\n%s\n", row.c_str());
}

}  // namespace

int main() {
    test_the_column_list_is_pinned();
    test_no_column_is_named_twice();
    test_the_header_is_the_column_list_joined();
    test_l2_demand_reserve_is_not_a_column();
    test_the_header_and_a_row_have_the_same_field_count();
    test_a_known_zero_column_is_present_and_zero();
    test_an_undefined_ratio_is_empty_not_a_nan();
    test_an_identity_carrying_a_comma_is_rejected();
    test_check_invariants_catches_a_broken_stall_sum();
    test_v21_is_an_equality_at_every_l1_latency();
    test_check_invariants_catches_a_negative_hidden_latency();
    test_check_invariants_catches_a_broken_prefetch_sum();
    test_percentiles_read_the_occupancy_samples();
    test_the_oracle_row_needs_no_engine();
    return check::summary();
}
