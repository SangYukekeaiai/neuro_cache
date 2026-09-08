#include "wcache/stats.h"

#include <algorithm>
#include <cstdio>
#include <numeric>
#include <stdexcept>

namespace wcache {

namespace {

// The spellings config.cpp's parser accepts, written back out. Kept beside the
// emitter rather than exported from the parser because these are the CSV's
// vocabulary: a round trip through parse_config is what pairs them, and
// test_config already pins the reading half.
const char* name_of(PolicyKind k) {
    switch (k) {
        case PolicyKind::LRU:    return "lru";
        case PolicyKind::FIFO:   return "fifo";
        case PolicyKind::RANDOM: return "random";
        case PolicyKind::BELADY: return "belady";
        case PolicyKind::RRIP:   return "rrip";
        case PolicyKind::LFU:    return "lfu";
    }
    throw std::logic_error("RunStats: unknown PolicyKind");
}

const char* name_of(LayoutKind l) {
    switch (l) {
        case LayoutKind::BlockPack: return "block_pack";
        case LayoutKind::SplitCin:  return "split_cin";
        case LayoutKind::KhkwSplit: return "khkw_split";
    }
    throw std::logic_error("RunStats: unknown LayoutKind");
}

const char* name_of(Inclusion i) {
    switch (i) {
        case Inclusion::NonInclusive: return "non_inclusive";
        case Inclusion::Inclusive:    return "inclusive";
    }
    throw std::logic_error("RunStats: unknown Inclusion");
}

const char* name_of(PrefetchKind p) {
    switch (p) {
        case PrefetchKind::None:      return "none";
        case PrefetchKind::NextBurst: return "next_burst";
    }
    throw std::logic_error("RunStats: unknown PrefetchKind");
}

std::int64_t total(const std::vector<std::int64_t>& v) {
    return std::accumulate(v.begin(), v.end(), std::int64_t{0});
}

// Nearest rank: the sorted sample at index min(n - 1, floor(q * n)). Stated
// once and used for both the MSHR occupancy columns and, through hist.h, for
// the G14 summary, so the two percentiles in one row mean the same thing.
std::int32_t quantile(std::vector<std::int32_t> s, double q) {
    std::sort(s.begin(), s.end());
    std::size_t i = static_cast<std::size_t>(q * static_cast<double>(s.size()));
    if (i >= s.size()) i = s.size() - 1;
    return s[i];
}

// Builds the cells in csv_columns() order, checking each against the name the
// schema has at that position. The check is the point of the class: a cell
// appended out of order, or one appended twice, is what silently shifts every
// later column of every row of a sweep.
class Row {
public:
    void str(const char* column, const std::string& v) {
        expect(column);
        if (v.find_first_of(",\"\n\r") != std::string::npos) {
            throw std::invalid_argument(
                std::string("RunStats: the column '") + column + "' would hold \"" + v +
                "\", which contains a comma, a quote or a newline. Such a value is "
                "refused rather than quoted per RFC 4180: every identity in this "
                "campaign is a filesystem-safe name, and a writer that quotes is a "
                "writer that must also escape quotes.");
        }
        cells_.push_back(v);
    }

    void i64(const char* column, std::int64_t v) {
        expect(column);
        cells_.push_back(std::to_string(v));
    }

    void f64(const char* column, double v) {
        expect(column);
        char buf[32];
        std::snprintf(buf, sizeof buf, "%.6f", v);
        cells_.emplace_back(buf);
    }

    // A ratio with a zero denominator is UNDEFINED, not zero and not a NaN, so
    // it is the empty cell: NaN and inf are not portable across CSV readers and
    // a 0 would be read as a measurement.
    void ratio(const char* column, double num, double den) {
        if (den == 0.0) {
            blank(column);
            return;
        }
        f64(column, num / den);
    }

    void blank(const char* column) {
        expect(column);
        cells_.emplace_back();
    }

    // Every column still unwritten, left empty. The oracle arm's tail.
    void blank_rest() {
        const std::vector<std::string>& cols = csv_columns();
        while (cells_.size() < cols.size()) cells_.emplace_back();
    }

    std::vector<std::string> take() {
        const std::vector<std::string>& cols = csv_columns();
        if (cells_.size() != cols.size()) {
            throw std::logic_error("RunStats: built " + std::to_string(cells_.size()) +
                                   " cells but the schema has " + std::to_string(cols.size()));
        }
        return std::move(cells_);
    }

private:
    void expect(const char* column) {
        const std::vector<std::string>& cols = csv_columns();
        if (cells_.size() >= cols.size() || cols[cells_.size()] != column) {
            throw std::logic_error(
                std::string("RunStats: emitted '") + column + "' at position " +
                std::to_string(cells_.size()) + ", where the schema has '" +
                (cells_.size() < cols.size() ? cols[cells_.size()] : std::string("(past the end)")) +
                "'");
        }
    }

    std::vector<std::string> cells_;
};

void emit_identity(Row& r, const RowIdentity& id, const stream::StreamHeader& hdr) {
    r.str("run_id", id.run_id);
    r.str("git_commit", id.git_commit);
    r.str("arm", id.arm);
    r.str("tier", id.tier);
    r.str("arch", hdr.arch);
    r.i64("n_cores", hdr.n_cores);
    r.str("workload", hdr.workload);
    r.str("layer", hdr.layer);
    r.i64("sample_idx", hdr.sample_idx);
}

void emit_config(Row& r, const RunConfig& cfg) {
    r.i64("l1_size_bytes", cfg.l1_size_bytes);
    r.i64("l1_assoc", cfg.l1_assoc);
    r.i64("l1_num_lines", cfg.l1_num_lines());
    r.i64("l1_num_sets", cfg.l1_num_sets());
    r.i64("l2_size_bytes", cfg.l2_size_bytes);
    r.i64("l2_assoc", cfg.l2_assoc);
    r.i64("l2_num_lines", cfg.l2_num_lines());
    r.i64("l2_num_sets", cfg.l2_num_sets());
    r.i64("line_size_bytes", cfg.line_size_bytes());
    r.i64("cin_block", cfg.cin_block);
    r.i64("cout_block", cfg.cout_block);
    r.i64("weight_bytes", cfg.weight_bytes);
    r.str("layout", name_of(cfg.layout));
    // -1 under block_pack, which has no split. The cell says so itself rather
    // than repeating l1_num_sets and implying a width the run did not use.
    r.i64("cin_lo_blocks", cfg.cin_lo_blocks);
    r.i64("l1_mshrs", cfg.l1_mshrs);
    r.i64("l1_tgts_per_mshr", cfg.l1_tgts_per_mshr);
    r.i64("l2_mshrs", cfg.l2_mshrs);
    r.i64("l2_tgts_per_mshr", cfg.l2_tgts_per_mshr);
    r.i64("l1_demand_reserve", cfg.l1_demand_reserve);
    // `l2_demand_reserve` is deliberately absent: ruling Q8 removed the knob and
    // Task 10 rejects it at config load (G11).
    r.str("prefetch_policy", name_of(cfg.prefetch_policy));
    r.i64("prefetch_distance", cfg.prefetch_distance);
    r.i64("l1_latency", cfg.l1_latency);
    r.i64("l1_ii", cfg.l1_ii);
    r.i64("l2_latency", cfg.l2_latency);
    r.i64("l2_to_l1_latency", cfg.l2_to_l1_latency);
    r.i64("l2_miss_latency", cfg.l2_miss_latency);
    r.i64("l2_banks", cfg.l2_banks);
    r.i64("l2_ii", cfg.l2_ii);
    r.i64("dram_ii", cfg.dram_ii);
    r.i64("core_accept_ii", cfg.core_accept_ii);
    r.str("inclusion", name_of(cfg.inclusion));
    r.str("policy", name_of(cfg.policy));
}

void emit_headline(Row& r, std::int64_t total_cycles, std::int64_t tick_base_total) {
    r.i64("total_cycles", total_cycles);
    r.i64("tick_base_total", tick_base_total);
    r.i64("stretch_cycles", total_cycles - tick_base_total);
}

}  // namespace

const std::vector<std::string>& csv_columns() {
    static const std::vector<std::string> cols = {
        "run_id", "git_commit", "arm", "tier",
        "arch", "n_cores", "workload", "layer", "sample_idx",
        "l1_size_bytes", "l1_assoc", "l1_num_lines", "l1_num_sets",
        "l2_size_bytes", "l2_assoc", "l2_num_lines", "l2_num_sets",
        "line_size_bytes", "cin_block", "cout_block", "weight_bytes",
        "layout", "cin_lo_blocks",
        "l1_mshrs", "l1_tgts_per_mshr", "l2_mshrs", "l2_tgts_per_mshr", "l1_demand_reserve",
        "prefetch_policy", "prefetch_distance",
        "l1_latency", "l1_ii", "l2_latency", "l2_to_l1_latency", "l2_miss_latency",
        "l2_banks", "l2_ii", "dram_ii", "core_accept_ii", "inclusion", "policy",
        "total_cycles", "tick_base_total", "stretch_cycles",
        "l1_hits", "l1_accesses", "l1_hit_rate", "l2_hits", "l2_accesses", "l2_hit_rate",
        "dram_accesses", "dram_bytes",
        "stall_l1_slot", "stall_l1_line", "stall_l1_port",
        "stall_l2_slot", "stall_l2_line", "stall_l2_port",
        "stall_channel", "stall_barrier", "stall_total",
        "core_stall_sum", "fetch_latency_sum", "hidden_latency", "hidden_fraction",
        "pf_issued", "pf_timely", "pf_late", "pf_wasted",
        "pf_dropped_array_hit", "pf_dropped_matching", "pf_dropped_no_slot",
        "pf_dropped_targets_full", "pf_dropped_reserve",
        "pf_coverage", "pf_coverage_ceiling", "pf_budget_exhausted", "pf_pollution_evictions",
        "l2_prefetch_policy", "l2_prefetch_axis", "l2_prefetch_distance",
        "l2_prefetch_up", "l2_prefetch_down", "l2_demand_reserve",
        "l2_pf_issued", "l2_pf_issued_up", "l2_pf_issued_down",
        "l2_pf_timely", "l2_pf_late", "l2_pf_wasted", "l2_pf_retriggers",
        "l2_pf_dropped_array_hit", "l2_pf_dropped_entry", "l2_pf_dropped_no_slot",
        "l2_pf_dropped_reserve", "l2_pf_coverage",
        "padding_fraction", "port_bound_threshold",
        "l1_mshr_occ_p50", "l1_mshr_occ_p95", "l1_mshr_occ_max",
        "l2_mshr_occ_p50", "l2_mshr_occ_p95", "l2_mshr_occ_max",
        "max_wait_depth", "hits_downgraded_to_miss", "events", "events_per_cycle",
        "sim_wall_seconds",
        "distinct_addr_per_core_tile_p50", "distinct_addr_per_core_tile_max"};
    return cols;
}

std::string csv_header() {
    std::string s;
    for (const std::string& c : csv_columns()) {
        if (!s.empty()) s.push_back(',');
        s += c;
    }
    return s;
}

RunStats::RunStats(const RowIdentity& id, const RunConfig& cfg,
                   const stream::StreamHeader& hdr, const EngineStats& es,
                   std::int64_t total_cycles, std::int64_t tick_base_total,
                   double padding_fraction, double sim_wall_seconds,
                   std::int32_t distinct_p50, std::int32_t distinct_max) {
    const std::int64_t core_stall_sum    = total(es.core_stall);
    const std::int64_t fetch_latency_sum = total(es.fetch_latency);
    const std::int64_t stall_total       = total(es.stall_total);
    const std::int64_t causes =
        total(es.stall_l1_slot) + total(es.stall_l1_line) + total(es.stall_l1_port) +
        total(es.stall_l2_slot) + total(es.stall_l2_line) + total(es.stall_l2_port) +
        total(es.stall_channel) + total(es.stall_barrier);
    const std::int64_t pf_accounted = es.pf_timely + es.pf_late + es.pf_wasted +
                                      es.pf_dropped_array_hit + es.pf_dropped_entry +
                                      es.pf_dropped_no_slot + es.pf_dropped_targets_full +
                                      es.pf_dropped_reserve;

    stall_causes_   = causes;
    stall_total_    = stall_total;
    hidden_latency_ = fetch_latency_sum - core_stall_sum;
    pf_issued_      = es.pf_issued;
    pf_accounted_   = pf_accounted;

    Row r;
    emit_identity(r, id, hdr);
    emit_config(r, cfg);
    emit_headline(r, total_cycles, tick_base_total);

    r.i64("l1_hits", es.l1_hits);
    r.i64("l1_accesses", es.l1_accesses);
    r.ratio("l1_hit_rate", static_cast<double>(es.l1_hits), static_cast<double>(es.l1_accesses));
    r.i64("l2_hits", es.l2_hits);
    r.i64("l2_accesses", es.l2_accesses);
    r.ratio("l2_hit_rate", static_cast<double>(es.l2_hits), static_cast<double>(es.l2_accesses));
    r.i64("dram_accesses", es.dram_accesses);
    r.i64("dram_bytes", es.dram_accesses * cfg.line_size_bytes());

    // `stall_l1_line` is unreachable through a mapper that expands a burst to
    // one line per burst, which LinearMapper does and which the corpus's own
    // layout does at cout_block == burst_span. It is pinned at whatever the
    // engine reports, which is 0 there, and it is a column because §9.2 names
    // it: a missing column and a zero column are different answers.
    r.i64("stall_l1_slot", total(es.stall_l1_slot));
    r.i64("stall_l1_line", total(es.stall_l1_line));
    r.i64("stall_l1_port", total(es.stall_l1_port));
    r.i64("stall_l2_slot", total(es.stall_l2_slot));
    r.i64("stall_l2_line", total(es.stall_l2_line));
    r.i64("stall_l2_port", total(es.stall_l2_port));
    r.i64("stall_channel", total(es.stall_channel));
    r.i64("stall_barrier", total(es.stall_barrier));
    r.i64("stall_total", stall_total);

    r.i64("core_stall_sum", core_stall_sum);
    r.i64("fetch_latency_sum", fetch_latency_sum);
    r.i64("hidden_latency", hidden_latency_);
    r.ratio("hidden_fraction", static_cast<double>(hidden_latency_),
            static_cast<double>(fetch_latency_sum));

    r.i64("pf_issued", es.pf_issued);
    r.i64("pf_timely", es.pf_timely);
    r.i64("pf_late", es.pf_late);
    r.i64("pf_wasted", es.pf_wasted);
    r.i64("pf_dropped_array_hit", es.pf_dropped_array_hit);
    r.i64("pf_dropped_matching", es.pf_dropped_entry);
    r.i64("pf_dropped_no_slot", es.pf_dropped_no_slot);
    // Structurally 0: a prefetch meeting a matching entry is dropped before the
    // target-list bound is ever consulted, so `pf_dropped_matching` subsumes
    // this reason (4.6). Reported because §9.2 names it and because 0 is the
    // answer the schema needs.
    r.i64("pf_dropped_targets_full", es.pf_dropped_targets_full);
    r.i64("pf_dropped_reserve", es.pf_dropped_reserve);


    // Part 8: "coverage is timely plus late over all bursts, and its ceiling is
    // the fraction of bursts that are not first-in-tile". The numerator counts
    // prefetched LINES; the two units coincide when a burst expands to one line,
    // which is this corpus at cout_block == burst_span.
    r.ratio("pf_coverage", static_cast<double>(es.pf_timely + es.pf_late),
            static_cast<double>(es.demand_bursts));
    r.ratio("pf_coverage_ceiling", static_cast<double>(es.pf_bursts_eligible),
            static_cast<double>(es.demand_bursts));
    r.i64("pf_budget_exhausted", es.pf_budget_exhausted);
    r.i64("pf_pollution_evictions", es.pf_pollution_evictions);
    // The L2 policy (plan 0831-l2-cin-neighbour). Config first so a row is
    // self-describing, then the outcomes, which sum to `l2_pf_issued`.
    r.str("l2_prefetch_policy", cfg.l2_prefetch_policy == L2PrefetchKind::None ? "none" : "neighbour");
    r.str("l2_prefetch_axis", axis_name(cfg.l2_prefetch_axis));
    r.i64("l2_prefetch_distance", cfg.l2_prefetch_distance);
    r.i64("l2_prefetch_up", cfg.l2_prefetch_up ? 1 : 0);
    r.i64("l2_prefetch_down", cfg.l2_prefetch_down ? 1 : 0);
    r.i64("l2_demand_reserve", cfg.l2_demand_reserve);
    r.i64("l2_pf_issued", es.l2_pf_issued);
    r.i64("l2_pf_issued_up", es.l2_pf_issued_up);
    r.i64("l2_pf_issued_down", es.l2_pf_issued_down);
    r.i64("l2_pf_timely", es.l2_pf_timely);
    r.i64("l2_pf_late", es.l2_pf_late);
    r.i64("l2_pf_wasted", es.l2_pf_wasted);
    r.i64("l2_pf_retriggers", es.l2_pf_retriggers);
    r.i64("l2_pf_dropped_array_hit", es.l2_pf_dropped_array_hit);
    r.i64("l2_pf_dropped_entry", es.l2_pf_dropped_entry);
    r.i64("l2_pf_dropped_no_slot", es.l2_pf_dropped_no_slot);
    r.i64("l2_pf_dropped_reserve", es.l2_pf_dropped_reserve);
    // What fraction of the demand references this policy turned into hits.
    r.ratio("l2_pf_coverage", static_cast<double>(es.l2_pf_timely),
            static_cast<double>(es.l2_accesses));

    r.f64("padding_fraction", padding_fraction);
    // Q14's port-bound threshold, miss_fraction * l2_miss_latency * l2_banks /
    // l2_ii: the `l2_mshrs` value above which the L2 port cannot deliver
    // accesses fast enough to keep further entries occupied, so a knee there is
    // a port effect rather than an MSHR result. Undefined, and therefore empty,
    // when no demand access was made.
    if (es.l1_accesses == 0 || cfg.l2_ii == 0) {
        r.blank("port_bound_threshold");
    } else {
        const double miss_fraction =
            static_cast<double>(es.l1_accesses - es.l1_hits) / static_cast<double>(es.l1_accesses);
        r.f64("port_bound_threshold", miss_fraction * static_cast<double>(cfg.l2_miss_latency) *
                                          static_cast<double>(cfg.l2_banks) /
                                          static_cast<double>(cfg.l2_ii));
    }

    const char* occ_cols[2][3] = {{"l1_mshr_occ_p50", "l1_mshr_occ_p95", "l1_mshr_occ_max"},
                                  {"l2_mshr_occ_p50", "l2_mshr_occ_p95", "l2_mshr_occ_max"}};
    const std::vector<std::int32_t>* occ[2] = {&es.l1_mshr_occupancy, &es.l2_mshr_occupancy};
    for (int lvl = 0; lvl < 2; ++lvl) {
        const std::vector<std::int32_t>& s = *occ[lvl];
        if (s.empty()) {
            for (int j = 0; j < 3; ++j) r.blank(occ_cols[lvl][j]);
        } else {
            r.i64(occ_cols[lvl][0], quantile(s, 0.50));
            r.i64(occ_cols[lvl][1], quantile(s, 0.95));
            r.i64(occ_cols[lvl][2], *std::max_element(s.begin(), s.end()));
        }
    }

    r.i64("max_wait_depth", es.max_wait_depth);
    r.i64("hits_downgraded_to_miss", es.hits_downgraded_to_miss);
    r.i64("events", es.events);
    r.ratio("events_per_cycle", static_cast<double>(es.events), static_cast<double>(total_cycles));
    r.f64("sim_wall_seconds", sim_wall_seconds);
    r.i64("distinct_addr_per_core_tile_p50", distinct_p50);
    r.i64("distinct_addr_per_core_tile_max", distinct_max);

    cells_ = r.take();
}

std::string RunStats::csv_row() const {
    std::string s;
    for (const std::string& c : cells_) {
        if (!s.empty()) s.push_back(',');
        s += c;
    }
    return s;
}

void RunStats::check_invariants() const {
    // V21, and an equality at EVERY l1_latency rather than only at 0.
    //
    // The old precondition existed for one feeder: an L1 hit nothing refused
    // waited on none of the seven causes, so its l1_latency, and its wait on a
    // port with a nonzero l1_ii, had nowhere to go. Both are `stall_l1_port`
    // now, so there is no legal remainder left to allow for; `stall_total` is
    // written at two sites and every cycle either site charges lands in one of
    // the eight (see `StallCause`).
    if (stall_causes_ != stall_total_) {
        throw std::logic_error(
            "RunStats: V21 violated: the eight stall causes sum to " +
            std::to_string(stall_causes_) + " but stall_total is " +
            std::to_string(stall_total_));
    }

    // Ruling R8: the line anchor makes this structural, so a negative value
    // means the anchor moved the wrong way rather than that the policy hid
    // nothing.
    if (hidden_latency_ < 0) {
        throw std::logic_error("RunStats: R8 violated: hidden_latency is " +
                               std::to_string(hidden_latency_) +
                               ", but fetch_latency_sum - core_stall_sum can never be negative");
    }

    // 4.6: every prefetch issued ends in exactly one of the four outcomes or one
    // of the five drop reasons.
    if (pf_accounted_ != pf_issued_) {
        throw std::logic_error(
            "RunStats: the prefetch outcomes and drops sum to " + std::to_string(pf_accounted_) +
            " but pf_issued is " + std::to_string(pf_issued_));
    }
}

std::string oracle_row(const RowIdentity& id, const RunConfig& cfg,
                       const stream::StreamHeader& hdr, std::int64_t tick_base_total) {
    Row r;
    emit_identity(r, id, hdr);
    emit_config(r, cfg);
    // The arm's whole definition: the scratchpad's makespan IS the trace's own
    // timeline, so there is nothing to simulate and the stretch is zero.
    emit_headline(r, tick_base_total, tick_base_total);
    r.blank_rest();

    std::string s;
    for (const std::string& c : r.take()) {
        if (!s.empty()) s.push_back(',');
        s += c;
    }
    return s;
}

}  // namespace wcache
