// D1 fixtures: RunConfig parse, defaults, and validation.
//
// The rejection cases each stand alone rather than sharing one function,
// because a single function that throws on its first check would report the
// remaining rules as covered when they were never reached.
#include <wcache/config.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"

using namespace wcache;

namespace {

bool has_warning(const std::vector<Warning>& w, const std::string& code) {
    for (const Warning& x : w) {
        if (x.code == code) return true;
    }
    return false;
}

// --- Task 9: parse and defaults ------------------------------------------

void test_an_empty_object_gives_the_documented_defaults() {
    check::group("Task 9: {} is the campaign default configuration");
    const RunConfig c = parse_config("{}");
    CHECK_EQ(c.cin_block, 1);
    CHECK_EQ(c.cout_block, 16);
    CHECK_EQ(c.weight_bytes, 1);
    CHECK_EQ(c.l1_size_bytes, std::int64_t{8 * 1024});
    CHECK_EQ(c.l1_assoc, 8);
    CHECK_EQ(c.l2_size_bytes, std::int64_t{512 * 1024});
    CHECK_EQ(c.l2_assoc, 16);
    CHECK_EQ(c.l1_mshrs, 16);
    CHECK_EQ(c.l1_tgts_per_mshr, 20);
    CHECK_EQ(c.l2_mshrs, 20);
    CHECK_EQ(c.l2_tgts_per_mshr, 12);
    CHECK_EQ(c.l1_latency, std::int64_t{0});
    CHECK_EQ(c.l1_ii, std::int64_t{1});
    CHECK_EQ(c.l2_latency, std::int64_t{10});
    CHECK_EQ(c.l2_to_l1_latency, std::int64_t{0});
    CHECK_EQ(c.l2_miss_latency, std::int64_t{100});
    CHECK_EQ(c.l2_banks, 1);
    CHECK_EQ(c.l2_ii, std::int64_t{1});
    CHECK_EQ(c.dram_ii, std::int64_t{1});
    CHECK_EQ(c.core_accept_ii, std::int64_t{1});
    CHECK_EQ(c.prefetch_distance, 0);
    CHECK_TRUE(c.policy == PolicyKind::LRU);
    CHECK_TRUE(c.inclusion == Inclusion::NonInclusive);
    CHECK_TRUE(c.prefetch_policy == PrefetchKind::None);
    CHECK_EQ(c.l1_demand_reserve, -1);   // the "resolve me from the burst span" sentinel
}

void test_every_default_is_overridden_when_the_key_is_present() {
    check::group("Task 9: a present key overrides the default it stands for");
    const RunConfig c = parse_config(
        R"({"cin_block": 2, "cout_block": 32, "weight_bytes": 2,
            "l1_size_bytes": 4096, "l1_assoc": 4,
            "l2_size_bytes": 262144, "l2_assoc": 8,
            "l1_mshrs": 9, "l1_tgts_per_mshr": 7,
            "l2_mshrs": 11, "l2_tgts_per_mshr": 13,
            "l1_demand_reserve": 3,
            "l1_latency": 5, "l1_ii": 2, "l2_latency": 21,
            "l2_to_l1_latency": 3, "l2_miss_latency": 200,
            "l2_banks": 4, "l2_ii": 6, "dram_ii": 8, "core_accept_ii": 2,
            "policy": "fifo", "inclusion": "inclusive",
            "prefetch_policy": "next_burst", "prefetch_distance": 4})");
    CHECK_EQ(c.cin_block, 2);
    CHECK_EQ(c.cout_block, 32);
    CHECK_EQ(c.weight_bytes, 2);
    CHECK_EQ(c.l1_size_bytes, std::int64_t{4096});
    CHECK_EQ(c.l1_assoc, 4);
    CHECK_EQ(c.l2_size_bytes, std::int64_t{262144});
    CHECK_EQ(c.l2_assoc, 8);
    CHECK_EQ(c.l1_mshrs, 9);
    CHECK_EQ(c.l1_tgts_per_mshr, 7);
    CHECK_EQ(c.l2_mshrs, 11);
    CHECK_EQ(c.l2_tgts_per_mshr, 13);
    CHECK_EQ(c.l1_demand_reserve, 3);
    CHECK_EQ(c.l1_latency, std::int64_t{5});
    CHECK_EQ(c.l1_ii, std::int64_t{2});
    CHECK_EQ(c.l2_latency, std::int64_t{21});
    CHECK_EQ(c.l2_to_l1_latency, std::int64_t{3});
    CHECK_EQ(c.l2_miss_latency, std::int64_t{200});
    CHECK_EQ(c.l2_banks, 4);
    CHECK_EQ(c.l2_ii, std::int64_t{6});
    CHECK_EQ(c.dram_ii, std::int64_t{8});
    CHECK_EQ(c.core_accept_ii, std::int64_t{2});
    CHECK_TRUE(c.policy == PolicyKind::FIFO);
    CHECK_TRUE(c.inclusion == Inclusion::Inclusive);
    CHECK_TRUE(c.prefetch_policy == PrefetchKind::NextBurst);
    CHECK_EQ(c.prefetch_distance, 4);
}

void test_line_size_and_geometry_are_derived_not_declared() {
    check::group("Task 9: line_size_bytes = cin_block * cout_block * weight_bytes");
    const RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "weight_bytes": 1,
            "l1_size_bytes": 2048, "l1_assoc": 8})");
    CHECK_EQ(c.line_size_bytes(), std::int64_t{64});
    CHECK_EQ(c.l1_num_lines(), std::int64_t{32});
    CHECK_EQ(c.l1_num_sets(), std::int64_t{4});
    CHECK_EQ(c.l2_num_lines(), std::int64_t{8192});
    CHECK_EQ(c.l2_num_sets(), std::int64_t{512});
}

void test_an_unknown_key_is_rejected() {
    check::group("Task 9: an unknown key throws rather than loading silently");
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_sz": 2048})"));
}

void test_every_enum_spelling_round_trips() {
    check::group("Task 9: the string spellings the grids use all parse");
    CHECK_TRUE(parse_config(R"({"policy": "lru"})").policy == PolicyKind::LRU);
    CHECK_TRUE(parse_config(R"({"policy": "fifo"})").policy == PolicyKind::FIFO);
    CHECK_TRUE(parse_config(R"({"policy": "random"})").policy == PolicyKind::RANDOM);
    CHECK_TRUE(parse_config(R"({"inclusion": "non_inclusive"})").inclusion
               == Inclusion::NonInclusive);
    CHECK_TRUE(parse_config(R"({"inclusion": "inclusive"})").inclusion
               == Inclusion::Inclusive);
    CHECK_TRUE(parse_config(R"({"prefetch_policy": "none"})").prefetch_policy
               == PrefetchKind::None);
    CHECK_TRUE(parse_config(R"({"prefetch_policy": "next_burst",
                                "prefetch_distance": 4})").prefetch_policy
               == PrefetchKind::NextBurst);
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"policy": "clock"})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"prefetch_policy": "stride"})"));
}

void test_inclusion_exclusive_is_refused_at_load() {
    check::group("Task 9/10: inclusion = exclusive is refused, not downgraded");
    // There is no Inclusion::Exclusive to hold, so the refusal is at parse.
    bool named = false;
    try {
        parse_config(R"({"inclusion": "exclusive"})");
    } catch (const std::invalid_argument& e) {
        named = std::string(e.what()).find("exclusive") != std::string::npos;
    }
    CHECK_TRUE(named);
}

void test_malformed_json_is_refused() {
    check::group("Task 9: the reader is strict about the subset it accepts");
    CHECK_THROWS(std::invalid_argument, parse_config(""));
    CHECK_THROWS(std::invalid_argument, parse_config("[]"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": 8,})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc" 8})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": 8)"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({l1_assoc: 8})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": 8.5})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": true})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": [8]})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"policy": 3})"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": 8} trailing)"));
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_assoc": 8, "l1_assoc": 4})"));
}

// --- Task 10: rejections, one case each -----------------------------------

void test_l2_demand_reserve_is_rejected_by_name() {
    check::group("Task 10: l2_demand_reserve is REJECTED at load (ruling Q8, G11)");
    // Not merely unknown: it must be rejected with its own message, so a sweeper
    // who tries it learns the knob is dead rather than that they mistyped.
    std::string what;
    try {
        parse_config(R"({"l2_demand_reserve": 4})");
    } catch (const std::invalid_argument& e) {
        what = e.what();
    }
    CHECK_TRUE(what.find("l2_demand_reserve") != std::string::npos);
    CHECK_TRUE(what.find("removed knob") != std::string::npos);
}

void test_fewer_than_one_set_is_rejected_at_l1() {
    check::group("Task 10: l1_size < l1_assoc * line_size is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 256, "l1_assoc": 8})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));   // 8*64 = 512 > 256
}

void test_fewer_than_one_set_is_rejected_at_l2() {
    check::group("Task 10: l2_size < l2_assoc * line_size is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l2_size_bytes": 512, "l2_assoc": 16})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));   // 16*64 = 1024 > 512
}

void test_a_partial_line_is_rejected_at_l1() {
    check::group("Task 10: l1_size_bytes % line_size_bytes != 0 is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 2000, "l1_assoc": 8})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_a_partial_line_is_rejected_at_l2() {
    check::group("Task 10: l2_size_bytes % line_size_bytes != 0 is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l2_size_bytes": 262100})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_a_partial_set_is_rejected_at_l1() {
    check::group("Task 10: l1_num_lines % l1_assoc != 0 is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 2560, "l1_assoc": 8})");
    std::vector<Warning> w;   // 40 lines, 40 % 8 == 0, so push it off by one line
    c.l1_size_bytes = 2624;   // 41 lines
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_a_partial_set_is_rejected_at_l2() {
    check::group("Task 10: l2_num_lines % l2_assoc != 0 is rejected");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l2_size_bytes": 262208})");
    std::vector<Warning> w;   // 4097 lines, 4097 % 16 != 0
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_policy_random_is_rejected() {
    check::group("Task 10: policy = random is a placeholder and is rejected");
    RunConfig c = parse_config(R"({"policy": "random"})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_a_burst_wider_than_the_l1_mshr_file_is_rejected() {
    check::group("Task 10: lines_per_burst > l1_mshrs is rejected");
    RunConfig c = parse_config(R"({"l1_mshrs": 2})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_core_accept_ii_below_one_is_rejected() {
    check::group("Task 10: core_accept_ii < 1 is rejected");
    RunConfig c = parse_config(R"({"core_accept_ii": 0})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
}

void test_a_negative_prefetch_distance_is_rejected() {
    check::group("Task 10: prefetch_distance < 0 is rejected");
    RunConfig c = parse_config(R"({"prefetch_distance": -1})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
}

void test_next_burst_with_zero_distance_is_rejected() {
    check::group("Task 10: prefetch_policy = next_burst with distance 0 is rejected");
    RunConfig c = parse_config(R"({"prefetch_policy": "next_burst"})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
}

void test_a_demand_reserve_at_or_above_the_mshr_count_is_rejected() {
    check::group("Task 10: l1_demand_reserve >= l1_mshrs is rejected");
    RunConfig c = parse_config(R"({"l1_mshrs": 4, "l1_demand_reserve": 4})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));
}

void test_every_count_below_one_is_rejected() {
    check::group("Task 10: a count below 1 is arithmetic nonsense and is rejected");
    const char* const cases[] = {
        R"({"l1_assoc": 0})",         R"({"l2_assoc": 0})",
        R"({"l1_mshrs": 0})",         R"({"l1_tgts_per_mshr": 0})",
        R"({"l2_mshrs": 0})",         R"({"l2_tgts_per_mshr": 0})",
        R"({"l2_banks": 0})",         R"({"cin_block": 0})",
        R"({"cout_block": 0})",       R"({"weight_bytes": 0})",
    };
    for (const char* text : cases) {
        RunConfig c = parse_config(text);
        std::vector<Warning> w;
        CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
    }
}

void test_every_negative_time_is_rejected() {
    check::group("Task 10: a negative initiation interval or latency is rejected");
    const char* const cases[] = {
        R"({"l1_ii": -1})",           R"({"l2_ii": -1})",
        R"({"dram_ii": -1})",         R"({"l1_latency": -1})",
        R"({"l2_latency": -1})",      R"({"l2_to_l1_latency": -1})",
        R"({"l2_miss_latency": -1})",
    };
    for (const char* text : cases) {
        RunConfig c = parse_config(text);
        std::vector<Warning> w;
        CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
    }
}

// --- Task 10: warnings, one case each --------------------------------------

void test_the_mshr_versus_lines_warning_fires() {
    check::group("Task 10: W_MSHR_VS_LINES at l1_mshrs >= l1_num_lines / 2");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 2048, "l1_assoc": 8,
            "l1_mshrs": 16})");
    std::vector<Warning> w;
    validate(c, 4, w);                       // must NOT throw: the corner is kept
    CHECK_EQ(c.l1_num_lines(), std::int64_t{32});
    CHECK_TRUE(has_warning(w, "W_MSHR_VS_LINES"));   // 16 >= 32/2
}

void test_the_few_sets_warning_fires() {
    check::group("Task 10: W_FEW_SETS at l1_num_sets < 8");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 2048, "l1_assoc": 8,
            "l1_mshrs": 16})");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_EQ(c.l1_num_sets(), std::int64_t{4});
    CHECK_TRUE(has_warning(w, "W_FEW_SETS"));        // 4 < 8
}

void test_the_prefetch_budget_warning_fires() {
    check::group("Task 10: W_PREFETCH_BUDGET when the free pool is under a burst");
    RunConfig c = parse_config(R"({"l1_mshrs": 5, "l1_demand_reserve": 4})");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_TRUE(has_warning(w, "W_PREFETCH_BUDGET"));  // budget 1 < lines_per_burst 4
}

void test_the_zero_ii_warning_fires() {
    check::group("Task 10: W_ZERO_II when a port is given an unbounded rate");
    RunConfig c = parse_config(R"({"l1_ii": 0})");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_TRUE(has_warning(w, "W_ZERO_II"));
    RunConfig d = parse_config(R"({"l2_ii": 0})");
    std::vector<Warning> v;
    validate(d, 4, v);
    CHECK_TRUE(has_warning(v, "W_ZERO_II"));
}

void test_the_default_configuration_validates_without_a_warning() {
    check::group("Task 10: the shipped defaults are clean at a 4-line burst");
    RunConfig c = parse_config("{}");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_EQ(check::ssize(w), std::int64_t{0});
}

// --- Task 10: resolution and handoff ---------------------------------------

void test_demand_reserve_defaults_to_lines_per_burst() {
    check::group("Task 10: the -1 sentinel resolves to lines_per_burst");
    RunConfig c = parse_config("{}");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_EQ(c.l1_demand_reserve, 4);
}

void test_a_declared_demand_reserve_of_zero_survives_validation() {
    check::group("Task 10: a declared 0 is not the same config as an omitted key");
    RunConfig c = parse_config(R"({"l1_demand_reserve": 0})");
    std::vector<Warning> w;
    validate(c, 4, w);
    CHECK_EQ(c.l1_demand_reserve, 0);
}

void test_to_engine_params_requires_validation_first() {
    check::group("Task 10: to_engine_params on an unvalidated config throws");
    const RunConfig c = parse_config("{}");
    CHECK_THROWS(std::invalid_argument, to_engine_params(c));   // reserve still -1
}

void test_to_engine_params_carries_every_knob() {
    check::group("Task 10: every RunConfig knob reaches EngineParams");
    RunConfig c = parse_config(
        R"({"l1_size_bytes": 4096, "l1_assoc": 8, "l2_size_bytes": 262144,
            "l2_assoc": 16, "l1_latency": 0, "l1_ii": 2, "l2_latency": 10,
            "l2_to_l1_latency": 3, "l2_miss_latency": 100, "l2_banks": 1,
            "l2_ii": 1, "dram_ii": 1, "core_accept_ii": 1, "l1_mshrs": 16,
            "l1_tgts_per_mshr": 20, "l2_mshrs": 20, "l2_tgts_per_mshr": 12,
            "policy": "fifo", "inclusion": "inclusive",
            "prefetch_policy": "next_burst", "prefetch_distance": 4})");
    std::vector<Warning> w;
    validate(c, 1, w);
    const EngineParams p = to_engine_params(c);
    CHECK_EQ(p.l1.cache_size_bytes, std::int64_t{4096});
    CHECK_EQ(p.l1.associativity, 8);
    CHECK_EQ(p.l1.mshrs, 16);
    CHECK_EQ(p.l1.tgts_per_mshr, 20);
    CHECK_EQ(p.l1.demand_reserve, 1);
    CHECK_EQ(p.l1.latency, SimTime{0});
    CHECK_EQ(p.l1.ii, SimTime{2});
    CHECK_EQ(p.l1.banks, 1);
    CHECK_TRUE(p.l1.policy == PolicyKind::FIFO);
    CHECK_EQ(p.l2.cache_size_bytes, std::int64_t{262144});
    CHECK_EQ(p.l2.associativity, 16);
    CHECK_EQ(p.l2.mshrs, 20);
    CHECK_EQ(p.l2.tgts_per_mshr, 12);
    CHECK_EQ(p.l2.demand_reserve, 0);   // L2 reserve is DEAD: always 0 (G11)
    CHECK_EQ(p.l2.latency, SimTime{10});
    CHECK_EQ(p.l2.ii, SimTime{1});
    CHECK_EQ(p.l2.banks, 1);
    CHECK_TRUE(p.l2.policy == PolicyKind::FIFO);
    CHECK_EQ(p.l2_to_l1_latency, SimTime{3});
    CHECK_EQ(p.l2_miss_latency, SimTime{100});
    CHECK_EQ(p.dram_ii, SimTime{1});
    CHECK_EQ(p.core_accept_ii, SimTime{1});
    CHECK_TRUE(p.inclusion == Inclusion::Inclusive);
    CHECK_EQ(p.prefetch_distance, 4);
    CHECK_TRUE(p.prefetch_policy == PrefetchKind::NextBurst);
}

// --- Task 18: the sweep grid ---------------------------------------------
//
// The grid document is read by the SAME reader and assigned through the same
// key table as a single configuration, so a knob is declared in exactly one
// place and a typo is refused identically in both documents.

void test_a_grid_array_is_used_verbatim_and_in_order() {
    check::group("Task 18: an array grid keeps its declared order");
    const std::vector<RunConfig> g =
        parse_config_grid(R"([{"l1_size_bytes": 2048}, {"l1_size_bytes": 4096}])");
    CHECK_EQ(check::ssize(g), std::int64_t{2});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});
    CHECK_EQ(g[1].l1_size_bytes, std::int64_t{4096});
    // Everything the array did not state is still RunConfig's default.
    CHECK_EQ(g[0].cout_block, 16);
}

void test_axes_expand_first_axis_slowest() {
    check::group("Task 18: the first declared axis varies slowest");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"cout_block": 16},
            "axes": {"l1_size_bytes": [2048, 4096],
                     "prefetch_distance": [0, 2]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{4});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});  CHECK_EQ(g[0].prefetch_distance, 0);
    CHECK_EQ(g[1].l1_size_bytes, std::int64_t{2048});  CHECK_EQ(g[1].prefetch_distance, 2);
    CHECK_EQ(g[2].l1_size_bytes, std::int64_t{4096});  CHECK_EQ(g[2].prefetch_distance, 0);
    CHECK_EQ(g[3].l1_size_bytes, std::int64_t{4096});  CHECK_EQ(g[3].prefetch_distance, 2);
    for (const RunConfig& c : g) CHECK_EQ(c.cout_block, 16);
}

void test_an_axis_takes_a_quoted_spelling_too() {
    check::group("Task 18: an axis carries whatever a config value can be");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"prefetch_distance": 2},
            "axes": {"prefetch_policy": ["none", "next_burst"]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{2});
    CHECK_TRUE(g[0].prefetch_policy == PrefetchKind::None);
    CHECK_TRUE(g[1].prefetch_policy == PrefetchKind::NextBurst);
}

void test_an_axis_overrides_the_same_key_in_base() {
    check::group("Task 18: an axis wins over base, which is what makes it an axis");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"l1_size_bytes": 1024}, "axes": {"l1_size_bytes": [2048]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{1});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});
}

void test_the_campaign_grid_expands_to_exactly_180() {
    check::group("Task 18: the campaign grid is 5 x 3 x 3 x 4 = 180");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"cout_block": 16, "weight_bytes": 1, "l1_assoc": 8,
                     "l2_assoc": 16, "l1_mshrs": 16, "l2_mshrs": 20},
            "axes": {"l1_size_bytes": [2048, 4096, 8192, 16384, 32768],
                     "cin_block": [1, 2, 4],
                     "l2_size_bytes": [262144, 524288, 1048576],
                     "prefetch_distance": [0, 2, 4, 8]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{180});
    // The line size axis is the cin packing at a fixed cout_block of 16, so the
    // three cin_block values are 16, 32 and 64 byte lines.
    CHECK_EQ(g[0].line_size_bytes(), std::int64_t{16});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});
    CHECK_EQ(g[0].prefetch_distance, 0);
    CHECK_EQ(g[179].line_size_bytes(), std::int64_t{64});
    CHECK_EQ(g[179].l1_size_bytes, std::int64_t{32768});
    CHECK_EQ(g[179].l2_size_bytes, std::int64_t{1048576});
    CHECK_EQ(g[179].prefetch_distance, 8);
    // The first axis varies slowest, so the last axis turns over every point.
    CHECK_EQ(g[1].prefetch_distance, 2);
    CHECK_EQ(g[4].l2_size_bytes, std::int64_t{524288});
    CHECK_EQ(g[12].cin_block, 2);
    CHECK_EQ(g[36].l1_size_bytes, std::int64_t{4096});
}

void test_a_grid_with_no_axes_is_one_point() {
    check::group("Task 18: no axes is a cross product of nothing, which is one point");
    const std::vector<RunConfig> g = parse_config_grid(R"({"base": {"l1_assoc": 4}})");
    CHECK_EQ(check::ssize(g), std::int64_t{1});
    CHECK_EQ(g[0].l1_assoc, 4);
}

void test_an_empty_axis_is_an_empty_grid() {
    check::group("Task 18: an axis with no values leaves nothing to run");
    const std::vector<RunConfig> g = parse_config_grid(R"({"axes": {"l1_assoc": []}})");
    CHECK_EQ(check::ssize(g), std::int64_t{0});
}

void test_a_bad_grid_is_refused_the_way_a_bad_config_is() {
    check::group("Task 18: the grid reader refuses what the config reader refuses");
    // An unknown knob, in base and on an axis alike.
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"({"base": {"l1_sixe": 1}})"));
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"({"axes": {"l1_sixe": [1]}})"));
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"([{"l1_sixe": 1}])"));
    // The removed knob keeps its own message wherever it appears.
    CHECK_THROWS(std::invalid_argument,
                 parse_config_grid(R"({"axes": {"l2_demand_reserve": [4]}})"));
    // A key that is neither base nor axes.
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"({"l1_size_bytes": 2048})"));
    // A duplicate axis, a duplicate top-level key, and a nested axis value.
    CHECK_THROWS(std::invalid_argument,
                 parse_config_grid(R"({"axes": {"l1_assoc": [2], "l1_assoc": [4]}})"));
    CHECK_THROWS(std::invalid_argument,
                 parse_config_grid(R"({"base": {}, "base": {}})"));
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"({"axes": {"l1_assoc": [[2]]}})"));
    // Trailing text, and a document that is neither of the two forms.
    CHECK_THROWS(std::invalid_argument, parse_config_grid(R"([{"l1_assoc": 2}] junk)"));
    CHECK_THROWS(std::invalid_argument, parse_config_grid("7"));
}

}  // namespace

int main() {
    test_an_empty_object_gives_the_documented_defaults();
    test_every_default_is_overridden_when_the_key_is_present();
    test_line_size_and_geometry_are_derived_not_declared();
    test_an_unknown_key_is_rejected();
    test_every_enum_spelling_round_trips();
    test_inclusion_exclusive_is_refused_at_load();
    test_malformed_json_is_refused();

    test_l2_demand_reserve_is_rejected_by_name();
    test_fewer_than_one_set_is_rejected_at_l1();
    test_fewer_than_one_set_is_rejected_at_l2();
    test_a_partial_line_is_rejected_at_l1();
    test_a_partial_line_is_rejected_at_l2();
    test_a_partial_set_is_rejected_at_l1();
    test_a_partial_set_is_rejected_at_l2();
    test_policy_random_is_rejected();
    test_a_burst_wider_than_the_l1_mshr_file_is_rejected();
    test_core_accept_ii_below_one_is_rejected();
    test_a_negative_prefetch_distance_is_rejected();
    test_next_burst_with_zero_distance_is_rejected();
    test_a_demand_reserve_at_or_above_the_mshr_count_is_rejected();
    test_every_count_below_one_is_rejected();
    test_every_negative_time_is_rejected();

    test_the_mshr_versus_lines_warning_fires();
    test_the_few_sets_warning_fires();
    test_the_prefetch_budget_warning_fires();
    test_the_zero_ii_warning_fires();
    test_the_default_configuration_validates_without_a_warning();

    test_demand_reserve_defaults_to_lines_per_burst();
    test_a_declared_demand_reserve_of_zero_survives_validation();
    test_to_engine_params_requires_validation_first();
    test_to_engine_params_carries_every_knob();

    test_a_grid_array_is_used_verbatim_and_in_order();
    test_axes_expand_first_axis_slowest();
    test_an_axis_takes_a_quoted_spelling_too();
    test_an_axis_overrides_the_same_key_in_base();
    test_the_campaign_grid_expands_to_exactly_180();
    test_a_grid_with_no_axes_is_one_point();
    test_an_empty_axis_is_an_empty_grid();
    test_a_bad_grid_is_refused_the_way_a_bad_config_is();
    return check::summary();
}
