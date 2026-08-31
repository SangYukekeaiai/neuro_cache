// U1's checks: the Fenwick stack distance against a naive back-scan oracle.
//
// The oracle is the DEFINITION, transcribed as directly as it can be written:
// walk backwards to the previous reference of this line and count the distinct
// lines passed. It is O(n * gap) and unusable on the corpus, which is exactly
// why it is trustworthy here. Every check below states an answer twice, once
// through the oracle and once through the tree.
//
// Built and run standalone:
//     g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
//         -Wshadow test_reuse_distance.cpp -o test_reuse_distance
//     ./test_reuse_distance
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <set>
#include <string>
#include <vector>

#include "reuse_distance.h"

namespace {

int checks  = 0;
int failures = 0;

void check(bool ok, const std::string& what) {
    ++checks;
    if (ok) return;
    ++failures;
    std::printf("  FAIL: %s\n", what.c_str());
}

void check_eq(std::int64_t got, std::int64_t want, const std::string& what) {
    check(got == want, what + ": got " + std::to_string(got) + ", want " + std::to_string(want));
}

void group(const char* name) { std::printf("== %s\n", name); }

// The definition, walked backwards. -1 for a first reference.
std::vector<std::int64_t> naive(const std::vector<std::int64_t>& seq) {
    std::vector<std::int64_t> out;
    out.reserve(seq.size());
    for (std::size_t i = 0; i < seq.size(); ++i) {
        std::size_t p    = 0;
        bool        seen = false;
        for (std::size_t j = i; j-- > 0;) {
            if (seq[j] == seq[i]) {
                p = j;
                seen = true;
                break;
            }
        }
        if (!seen) {
            out.push_back(-1);
            continue;
        }
        std::set<std::int64_t> between;
        for (std::size_t j = p + 1; j < i; ++j) between.insert(seq[j]);
        out.push_back(static_cast<std::int64_t>(between.size()));
    }
    return out;
}

std::vector<std::int64_t> fenwick(const std::vector<std::int64_t>& seq) {
    reuse::StackDistance sd;
    std::vector<std::int64_t> out;
    out.reserve(seq.size());
    for (const std::int64_t x : seq) out.push_back(sd.observe(x));
    return out;
}

// "ABCABDA" as line ids, the sequence the plan walks by hand.
const std::vector<std::int64_t> kWorked = {0, 1, 2, 0, 1, 3, 0};

void test_the_worked_example_matches_what_the_plan_claims() {
    group("U1: the worked example, hand-checked in the plan");
    const std::vector<std::int64_t> want = {-1, -1, -1, 2, 2, -1, 2};
    const std::vector<std::int64_t> got  = fenwick(kWorked);
    check_eq(static_cast<std::int64_t>(got.size()), 7, "seven references");
    for (std::size_t i = 0; i < want.size(); ++i) {
        check_eq(got[i], want[i], "distance at t=" + std::to_string(i + 1));
    }
    // Stated twice: the oracle has to agree with the hand-written answer too,
    // or the oracle is what is wrong.
    check(naive(kWorked) == want, "the oracle reproduces the hand-written answer");
}

void test_the_oracle_and_the_tree_agree_on_random_sequences() {
    group("U1: 2000 random sequences, oracle against tree");
    std::mt19937_64 rng(20260831);
    int disagreements = 0;
    for (int trial = 0; trial < 2000; ++trial) {
        const std::size_t n = 1 + rng() % 120;
        const std::int64_t m = 1 + static_cast<std::int64_t>(rng() % 12);
        std::vector<std::int64_t> seq(n);
        for (std::size_t i = 0; i < n; ++i) seq[i] = static_cast<std::int64_t>(rng() % static_cast<std::uint64_t>(m));
        if (naive(seq) != fenwick(seq)) ++disagreements;
    }
    check_eq(disagreements, 0, "disagreements over 2000 sequences");
}

// The growth path is the one place the tree can silently be wrong, because a
// slot born above the old bound covers squares below it. A sequence long enough
// to cross several doublings, checked against the oracle, is what catches it.
void test_the_tree_survives_its_own_doublings() {
    group("U1: growth across doublings");
    std::mt19937_64 rng(7);
    std::vector<std::int64_t> seq(5000);
    for (std::size_t i = 0; i < seq.size(); ++i) seq[i] = static_cast<std::int64_t>(rng() % 400);
    check(naive(seq) == fenwick(seq), "5000 references across ~12 doublings");

    // The growth POLICY, checked structurally. Doubling rebuilds about log2(n)
    // times; growing by a constant rebuilds n times and turns the class into
    // O(n^2) while leaving every answer correct. Counting rebuilds catches that
    // deterministically, which a wall-clock assertion would not.
    reuse::StackDistance sd;
    for (const std::int64_t x : seq) sd.observe(x);
    check_eq(sd.references(), 5000, "all 5000 observed");
    check(sd.rebuilds() <= 16, "5000 references rebuild ~log2(n) times, got " +
                                   std::to_string(sd.rebuilds()));

    // And at the exact boundaries, where an off-by-one in `ensure` would live.
    for (std::size_t n : {1u, 2u, 3u, 4u, 7u, 8u, 9u, 15u, 16u, 17u, 31u, 32u, 33u}) {
        std::vector<std::int64_t> s(n);
        for (std::size_t i = 0; i < n; ++i) s[i] = static_cast<std::int64_t>(i % 5);
        check(naive(s) == fenwick(s), "length " + std::to_string(n));
    }
}

// The access pattern the layers actually have. The artifact called it "LRU
// meeting a cyclic sweep", and it is the shape V3 will be checked against.
void test_a_cyclic_sweep_gives_one_spike_at_the_working_set() {
    group("U1: ORACLE -- a cyclic sweep is a single spike");
    const std::int64_t W = 300, passes = 40;
    std::vector<std::int64_t> seq;
    seq.reserve(static_cast<std::size_t>(W * passes));
    for (std::int64_t p = 0; p < passes; ++p) {
        for (std::int64_t i = 0; i < W; ++i) seq.push_back(i);
    }
    check(naive(seq) == fenwick(seq), "oracle agrees on the sweep");

    reuse::ReuseHistogram h;
    for (const std::int64_t x : seq) h.observe(x);

    check_eq(h.references(), W * passes, "every reference counted");
    check_eq(h.cold(), W, "one cold reference per distinct line");

    // Every non-cold reference sits at exactly W-1, and nowhere else.
    const std::vector<std::int64_t>& c = h.counts();
    check_eq(static_cast<std::int64_t>(c.size()), W, "the histogram reaches exactly W-1");
    check_eq(c[static_cast<std::size_t>(W - 1)], W * (passes - 1), "the whole spike sits at W-1");
    std::int64_t elsewhere = 0;
    for (std::size_t d = 0; d + 1 < c.size(); ++d) elsewhere += c[d];
    check_eq(elsewhere, 0, "nothing anywhere below the spike");

    // Which makes the hit-rate curve a step, and pins its two levels. This is
    // V3's shape in miniature: nothing below the working set, the cold-forced
    // ceiling at and above it.
    check(h.hit_rate_at(W - 1) == 0.0, "a cache one line short of W hits nothing");
    const double ceiling = static_cast<double>(W * (passes - 1)) / static_cast<double>(W * passes);
    check(h.hit_rate_at(W) == ceiling, "at W the rate jumps straight to its ceiling");
    check(h.hit_rate_at(W * 10) == ceiling, "and a far larger cache adds nothing");
}

void test_the_histogram_accounts_for_every_reference() {
    group("U1: V1 in miniature -- the tally is closed");
    std::mt19937_64 rng(99);
    std::vector<std::int64_t> seq(4000);
    for (std::size_t i = 0; i < seq.size(); ++i) seq[i] = static_cast<std::int64_t>(rng() % 250);

    reuse::ReuseHistogram h;
    for (const std::int64_t x : seq) h.observe(x);

    std::int64_t summed = h.cold();
    for (const std::int64_t c : h.counts()) summed += c;
    // V1's shape: the histogram's own total must equal the reference count it
    // was fed, with no reference falling into no bucket at all.
    check_eq(summed, static_cast<std::int64_t>(seq.size()), "cold + every bucket == references");
    check_eq(h.references(), static_cast<std::int64_t>(seq.size()), "the stack counted the same");

    // The cold count is the distinct-line count, by the invariant.
    std::set<std::int64_t> distinct(seq.begin(), seq.end());
    check_eq(h.cold(), static_cast<std::int64_t>(distinct.size()), "cold == distinct lines");
}

void test_the_hit_rate_curve_is_monotone_and_bounded() {
    group("U1: the curve is a CDF, so it only ever climbs");
    std::mt19937_64 rng(2026);
    std::vector<std::int64_t> seq(6000);
    for (std::size_t i = 0; i < seq.size(); ++i) seq[i] = static_cast<std::int64_t>(rng() % 180);

    reuse::ReuseHistogram h;
    for (const std::int64_t x : seq) h.observe(x);

    double prev = -1.0;
    for (std::int64_t n = 0; n <= 400; ++n) {
        const double r = h.hit_rate_at(n);
        check(r >= prev, "monotone at n=" + std::to_string(n));
        check(r >= 0.0 && r <= 1.0, "in [0,1] at n=" + std::to_string(n));
        prev = r;
    }
    check(h.hit_rate_at(0) == 0.0, "a cache of zero lines hits nothing");

    // The ceiling is forced by the cold count and cannot be exceeded however
    // large the cache gets. This is the arithmetic V3 leans on.
    const double ceiling = 1.0 - static_cast<double>(h.cold()) / static_cast<double>(h.references());
    check(h.hit_rate_at(1000000) == ceiling, "the ceiling is 1 - cold fraction");
}

void test_degenerate_sequences() {
    group("U1: the edges");
    check(fenwick({}).empty(), "an empty sequence yields nothing");
    check(fenwick({5}) == std::vector<std::int64_t>{-1}, "one reference is cold");
    // The same line over and over: nothing distinct ever comes between.
    const std::vector<std::int64_t> same(50, 3);
    const std::vector<std::int64_t> got = fenwick(same);
    check_eq(got[0], -1, "first is cold");
    std::int64_t nonzero = 0;
    for (std::size_t i = 1; i < got.size(); ++i) nonzero += (got[i] != 0);
    check_eq(nonzero, 0, "every repeat is at distance 0");
    check(naive(same) == got, "the oracle agrees");

    // All distinct: every reference is cold and the histogram is empty.
    std::vector<std::int64_t> all(50);
    for (std::size_t i = 0; i < all.size(); ++i) all[i] = static_cast<std::int64_t>(i);
    reuse::ReuseHistogram h;
    for (const std::int64_t x : all) h.observe(x);
    check_eq(h.cold(), 50, "fifty cold references");
    check(h.counts().empty(), "no finite distance anywhere");
    check(h.hit_rate_at(1000) == 0.0, "no cache size helps a stream with no reuse");
}

}  // namespace

int main() {
    test_the_worked_example_matches_what_the_plan_claims();
    test_the_oracle_and_the_tree_agree_on_random_sequences();
    test_the_tree_survives_its_own_doublings();
    test_a_cyclic_sweep_gives_one_spike_at_the_working_set();
    test_the_histogram_accounts_for_every_reference();
    test_the_hit_rate_curve_is_monotone_and_bounded();
    test_degenerate_sequences();
    std::printf("%d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
