// Unit A5: ReplacementPolicy, and the two implementations of it.
//
// Its own file rather than more of test_set_associative.cpp, for the reason
// B21 gives and one specific to this unit. The general reason is that a test
// file mirrors the module under test, and plan 2.2 says outright that the
// policy is "a **separate module** from the array". The specific one is that
// test_set_associative.cpp is evidence about the ARRAY: everything in it is
// reachable with no policy in the tree at all, and folding A5 in would retire
// that.
//
// This file does include set_associative.h, and deliberately. The one thing
// only an integration can say is that LRU and FIFO, driving the SAME array
// through the same accesses, evict different lines: that is the whole content
// of the difference between them, and it cannot be stated about a policy in
// isolation. The property that the policy interface needs NOTHING but SlotId
// and Candidate is not weakened by that, because it is not carried here: it is
// carried by compile_fail.sh's `tryR` cases, which compile against policy.h
// alone and fail if it ever acquires a dependency on an array or a layout.
//
// Group letters: TEST_DESIGN_CACHE.md stops at S and predates this unit, so
// the groups below are named rather than lettered.
#include <cachesim/replacement/lfu.h>

#include <cachesim/layout/block_pack.h>
#include <cachesim/index/cache_array.h>
#include <cachesim/layout/mapper.h>
#include <cachesim/replacement/policy.h>
#include <cachesim/index/set_associative.h>
#include <cachesim/types.h>

#include <algorithm>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "check.h"

using namespace cachesim;

namespace {

// ===========================================================================
// Probes and fixtures
// ===========================================================================
//
// The two message probes are test_set_associative.cpp's, kept in that shape
// rather than shared through a header: the repo convention is one probe pair
// per test file, because the pair encodes which exception type is CORRECT for
// the file's subject, and a shared probe would have to be told, which is the
// thing being tested.

template <typename Fn>
std::string thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::out_of_range& e) {
        return std::string("[out_of_range, not invalid_argument] ") + e.what();
    } catch (const std::invalid_argument& e) {
        return e.what();
    } catch (const std::logic_error& e) {
        return std::string("[logic_error, not invalid_argument] ") + e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong exception type] ") + e.what();
    } catch (...) {
        return "[non-std exception]";
    }
    return "[no exception thrown]";
}

template <typename Fn>
std::string range_thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::out_of_range& e) {
        return e.what();
    } catch (const std::invalid_argument& e) {
        return std::string("[invalid_argument, not out_of_range] ") + e.what();
    } catch (const std::logic_error& e) {
        return std::string("[logic_error, not out_of_range] ") + e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong exception type] ") + e.what();
    } catch (...) {
        return "[non-std exception]";
    }
    return "[no exception thrown]";
}

bool contains(const std::string& hay, const char* needle) {
    return hay.find(needle) != std::string::npos;
}

void expect_message(const char* name,
                    const std::string& actual,
                    const char* prefix,
                    std::initializer_list<const char*> needles) {
    ++check::g_checks;
    std::string missing;
    if (actual.rfind(prefix, 0) != 0) {
        missing += " prefix \"";
        missing += prefix;
        missing += "\"";
    }
    for (const char* n : needles) {
        if (!contains(actual, n)) {
            missing += " \"";
            missing += n;
            missing += "\"";
        }
    }
    if (!missing.empty()) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s missing:%s\n  message  : %s\n",
                        name, missing.c_str(), actual.c_str());
    }
}

// --- the candidate set --------------------------------------------------------

// A candidate set over the given slots. The line each one carries is filled in
// with something distinguishable and is never what pick_victim answers on:
// StampPolicy orders by its own stamps, so a policy that read the line would
// have to be reaching for state the array owns.
std::vector<Candidate> candidates_over(std::initializer_list<std::int32_t> slots) {
    std::vector<Candidate> out;
    for (std::int32_t s : slots) out.push_back(Candidate{SlotId{s}, LineId{1000 + s}});
    return out;
}

// pick_victim over EVERY permutation of the candidate set, reporting whether
// all of them agreed and what the agreed answer was.
//
// The plan's A5 exit criterion is that no implementation may depend on the
// order of the candidate set, and this is that criterion tested as what it
// says: an invariance, rather than one expected answer compared against one
// arrangement. A policy that quietly kept "the first one seen" on a tie would
// pass any single-order check and fail here on the first swap.
SlotId pick_over_every_permutation(ReplacementPolicy& p,
                                   std::vector<Candidate> ordered,
                                   bool& agreed,
                                   long& permutations) {
    std::sort(ordered.begin(), ordered.end(),
              [](const Candidate& a, const Candidate& b) { return a.slot < b.slot; });

    std::vector<std::size_t> order(ordered.size());
    for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;

    std::vector<Candidate> shuffled;
    SlotId first = NoSlot;
    agreed       = true;
    permutations = 0;

    do {
        shuffled.clear();
        for (std::size_t i : order) shuffled.push_back(ordered[i]);
        const SlotId got = p.pick_victim(shuffled);
        if (permutations == 0) {
            first = got;
        } else if (got != first) {
            agreed = false;
        }
        ++permutations;
    } while (std::next_permutation(order.begin(), order.end()));

    return first;
}

void expect_invariant(const char* name, ReplacementPolicy& p,
                      const std::vector<Candidate>& set, SlotId expected) {
    bool agreed        = false;
    long permutations  = 0;
    const SlotId got   = pick_over_every_permutation(p, set, agreed, permutations);

    ++check::g_checks;
    if (!agreed) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s the answer depends on candidate order\n", name);
    }
    // The invariance is the criterion; the value is checked too, because an
    // implementation that always answered the same slot whatever its state
    // would be perfectly invariant and useless.
    CHECK_EQ(got, expected);
    CHECK_TRUE(permutations > 1);
}
}  // namespace

// The reference count of `slot`. Requires a slot id above 0, which is the probe.
//
// LFU's victim is the smallest count with the smallest slot id as the
// tie-break, so a probe at slot 0 wins the pair until its own count passes the
// probed slot's. Counting the hits that takes reads the count back exactly.
int lfu_count_of(LfuPolicy p, std::int32_t slot) {
    p.on_fill(SlotId{0});
    for (int hits = 0; hits <= 1000; ++hits) {
        if (p.pick_victim(candidates_over({0, slot})) == SlotId{slot}) return hits - 1;
        p.on_hit(SlotId{0});
    }
    throw std::logic_error("lfu_count_of: reference count exceeded 1000");
}

// pick_victim over every permutation of a candidate set, each permutation
// against a FRESH policy from `setup`, checking that the victim AND the state
// the call leaves behind are the same every time.
//
// The state half is what this adds to expect_invariant above, and RRIP is why:
// its pick_victim AGES its candidates, so a run whose answers agreed while its
// aging did not would still be order-dependent, and the divergence would
// surface on some later call instead of here. `read` reports one slot's state
// through the readers above.
template <typename Setup, typename Read>
void expect_state_invariant(const char* name, Setup setup, Read read,
                            const std::vector<std::int32_t>& slots, SlotId expected) {
    std::vector<std::int32_t> fixed = slots;
    std::sort(fixed.begin(), fixed.end());
    std::vector<std::int32_t> order = fixed;

    std::vector<std::int64_t> first_state;
    SlotId first_victim  = NoSlot;
    long   permutations  = 0;
    bool   agreed        = true;
    bool   state_agreed  = true;

    do {
        auto p = setup();

        std::vector<Candidate> set;
        for (std::int32_t s : order) set.push_back(Candidate{SlotId{s}, LineId{1000 + s}});
        const SlotId got = p.pick_victim(set);

        std::vector<std::int64_t> state;
        for (std::int32_t s : fixed) state.push_back(read(p, s));

        if (permutations == 0) {
            first_victim = got;
            first_state  = state;
        } else {
            if (got != first_victim) agreed = false;
            if (state != first_state) state_agreed = false;
        }
        ++permutations;
    } while (std::next_permutation(order.begin(), order.end()));

    ++check::g_checks;
    if (!agreed) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s the answer depends on candidate order\n", name);
    }
    ++check::g_checks;
    if (!state_agreed) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s the state left behind depends on candidate order\n", name);
    }
    CHECK_EQ(first_victim, expected);
    CHECK_TRUE(permutations > 1);
}

void test_lfu_counts_references_per_line() {
    check::group("P4: LFU -- a fill resets the count, a hit raises it, an invalidate clears it");

    // Slots 1 to 4, because slot 0 is lfu_count_of's probe.
    LfuPolicy p(32);
    for (std::int32_t s : {1, 2, 3, 4}) p.on_fill(SlotId{s});

    // Every count is 0 after the fills, so the victim is the tie-break alone.
    // A fill that INHERITED the slot's previous count would let an evicted
    // line's history protect its replacement, which is what this pins.
    CHECK_EQ(lfu_count_of(p, 2), 0);
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3, 4})), SlotId{1});

    for (int i = 0; i < 3; ++i) p.on_hit(SlotId{1});
    p.on_hit(SlotId{2});
    CHECK_EQ(lfu_count_of(p, 1), 3);
    CHECK_EQ(lfu_count_of(p, 2), 1);
    CHECK_EQ(lfu_count_of(p, 4), 0);
    // 3 and 4 are still at 0 and tie, so the smallest of those two answers.
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3, 4})), SlotId{3});

    // The fill is a reset and not a no-op: slot 1 was the most used and becomes
    // the least used by being refilled.
    p.on_fill(SlotId{1});
    CHECK_EQ(lfu_count_of(p, 1), 0);
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3, 4})), SlotId{1});

    // With every count at 1 but slot 1's at 2, the answer is the smallest of
    // the three that tie, and an invalidate then moves it: the count belongs to
    // the line, and slot 4 now holds none.
    p.on_hit(SlotId{1});
    p.on_hit(SlotId{1});
    for (std::int32_t s : {3, 4}) p.on_hit(SlotId{s});
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3, 4})), SlotId{2});
    p.on_invalidate(SlotId{4});
    CHECK_EQ(lfu_count_of(p, 4), 0);
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3, 4})), SlotId{4});

    // Pure LFU never ages, and that ceiling is recorded rather than asserted as
    // right: slot 1 was hammered once and holds its way against slots used once
    // each from then on, however long that is.
    LfuPolicy old(32);
    for (std::int32_t s : {1, 2, 3, 4}) old.on_fill(SlotId{s});
    for (int i = 0; i < 50; ++i) old.on_hit(SlotId{1});
    for (int round = 0; round < 20; ++round) {
        for (std::int32_t s : {2, 3, 4}) old.on_hit(SlotId{s});
        CHECK_TRUE(old.pick_victim(candidates_over({1, 2, 3, 4})) != SlotId{1});
    }
}

void test_lfu_ties_go_to_the_smallest_slot_id() {
    check::group("P4: LFU -- ties go to the smallest slot id, not to the first one offered");

    // Stated as a value rather than as the invariance below, for the reason
    // test_the_tie_break_is_the_smallest_slot_id gives: invariant and correct
    // are independent properties.
    LfuPolicy p(32);
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({5, 9, 2})), SlotId{2});

    // And the tie-break decides only ties: one hit on the smallest slot moves
    // the answer to the smallest of those still tied at zero.
    p.on_hit(SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{5});
    CHECK_EQ(p.pick_victim(candidates_over({5, 2, 9})), SlotId{5});
    p.on_hit(SlotId{5});
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{9});
}

int main() {
    test_lfu_counts_references_per_line();
    test_lfu_ties_go_to_the_smallest_slot_id();
    return check::summary();
}
