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
#include <cachesim/replacement/belady.h>
#include <cachesim/replacement/policy.h>
#include <cachesim/replacement/stamp.h>

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

void test_belady_evicts_the_furthest_next_use() {
    check::group("W1: MIN evicts the line whose next use is furthest away");
    BeladyPolicy p(4);
    p.note_next_use(SlotId{0}, 100);
    p.note_next_use(SlotId{1}, 7);
    p.note_next_use(SlotId{2}, 55);
    p.note_next_use(SlotId{3}, 900);
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2, 3})).get(), 3);

    // The sign really is flipped. Stated as a contrast so a later edit cannot
    // quietly turn MIN back into an LRU-shaped minimum and still pass.
    p.note_next_use(SlotId{3}, 1);
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2, 3})).get(), 0);

    // Only the candidates offered are considered, never every slot the policy
    // has: slot 0 is the global maximum and is absent from this set.
    CHECK_EQ(p.pick_victim(candidates_over({1, 2, 3})).get(), 2);
}

void test_belady_evicts_a_line_never_used_again_first() {
    check::group("W1: a line with no next use leaves before any line with one");
    BeladyPolicy p(3);
    p.note_next_use(SlotId{0}, 5);
    p.note_next_use(SlotId{1}, 999999);
    // Slot 2 was never told a next use, so it carries the never value. This is
    // where most of MIN's advantage over LRU comes from: a dead line goes first
    // however recently it was touched.
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2})).get(), 2);

    p.note_next_use(SlotId{2}, 1);
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2})).get(), 1);
    // An invalidated slot returns to never and becomes the victim again.
    p.on_invalidate(SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2})).get(), 2);
}

void test_belady_is_order_independent() {
    check::group("W1: A5's contract applied to MIN, over every permutation");
    // Distinct futures: the answer is the maximum, not the tie-break.
    BeladyPolicy p(4);
    p.note_next_use(SlotId{0}, 10);
    p.note_next_use(SlotId{1}, 40);
    p.note_next_use(SlotId{2}, 20);
    p.note_next_use(SlotId{3}, 30);
    expect_invariant("belady, distinct futures", p, candidates_over({0, 1, 2, 3}), SlotId{1});

    // Every slot never-used, so all four tie at the never value. This is the
    // case the tie-break exists for, and the one a naive maximum fails.
    BeladyPolicy tied(4);
    expect_invariant("belady, all never-used", tied, candidates_over({0, 1, 2, 3}), SlotId{0});

    // A partial tie: two at the never value, two with futures.
    BeladyPolicy part(4);
    part.note_next_use(SlotId{1}, 9);
    part.note_next_use(SlotId{3}, 4);
    expect_invariant("belady, partial tie", part, candidates_over({0, 1, 2, 3}), SlotId{0});
}

void test_belady_ignores_the_past() {
    check::group("W1: hits and fills tell MIN nothing");
    BeladyPolicy p(2);
    p.note_next_use(SlotId{0}, 900);
    p.note_next_use(SlotId{1}, 5);
    // Hammer slot 0 with exactly the events LRU and FIFO order themselves by.
    for (int i = 0; i < 50; ++i) {
        p.on_hit(SlotId{0});
        p.on_fill(SlotId{0});
    }
    CHECK_EQ(p.pick_victim(candidates_over({0, 1})).get(), 0);
}

void test_belady_refuses_what_the_other_policies_refuse() {
    check::group("W1: the same refusals StampPolicy makes");
    CHECK_THROWS(std::invalid_argument, BeladyPolicy(0));
    CHECK_THROWS(std::invalid_argument, BeladyPolicy(-1));
    BeladyPolicy p(2);
    CHECK_THROWS(std::invalid_argument, p.pick_victim(std::vector<Candidate>{}));
    CHECK_THROWS(std::out_of_range, p.note_next_use(SlotId{2}, 1));
    CHECK_THROWS(std::out_of_range, p.note_next_use(SlotId{-1}, 1));
    CHECK_THROWS(std::out_of_range, p.on_hit(SlotId{2}));
    CHECK_THROWS(std::out_of_range, p.on_fill(SlotId{2}));
    CHECK_THROWS(std::out_of_range, p.on_invalidate(SlotId{2}));
    CHECK_THROWS(std::out_of_range, p.pick_victim(candidates_over({0, 2})));
}

void test_note_next_use_is_inert_on_lru_and_fifo() {
    check::group("W1: B5 -- the new verb changes nothing for the existing policies");
    // If note_next_use were wired into StampPolicy by accident, both of these
    // would move. It is the check that the default no-op really is one.
    LruPolicy lru(3);
    lru.on_fill(SlotId{0});
    lru.on_fill(SlotId{1});
    lru.on_fill(SlotId{2});
    lru.note_next_use(SlotId{0}, 1);
    lru.note_next_use(SlotId{2}, 999999);
    CHECK_EQ(lru.pick_victim(candidates_over({0, 1, 2})).get(), 0);
    lru.on_hit(SlotId{0});
    CHECK_EQ(lru.pick_victim(candidates_over({0, 1, 2})).get(), 1);

    FifoPolicy fifo(3);
    fifo.on_fill(SlotId{0});
    fifo.on_fill(SlotId{1});
    fifo.on_fill(SlotId{2});
    fifo.note_next_use(SlotId{0}, 999999);
    fifo.on_hit(SlotId{0});
    CHECK_EQ(fifo.pick_victim(candidates_over({0, 1, 2})).get(), 0);
}

void test_make_policy_builds_belady() {
    check::group("W1: the factory knows the name");
    std::unique_ptr<ReplacementPolicy> p = make_policy(PolicyKind::BELADY, 4);
    CHECK_TRUE(p != nullptr);
    p->note_next_use(SlotId{0}, 1);
    p->note_next_use(SlotId{1}, 2);
    // Reached through the ABSTRACT interface, which is what the engine holds.
    CHECK_EQ(p->pick_victim(candidates_over({0, 1})).get(), 1);
}

// ===========================================================================

int main() {
    test_belady_evicts_the_furthest_next_use();
    test_belady_evicts_a_line_never_used_again_first();
    test_belady_is_order_independent();
    test_belady_ignores_the_past();
    test_belady_refuses_what_the_other_policies_refuse();
    test_note_next_use_is_inert_on_lru_and_fifo();
    test_make_policy_builds_belady();
    return check::summary();
}
