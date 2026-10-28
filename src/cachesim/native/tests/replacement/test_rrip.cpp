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
#include <cachesim/replacement/rrip.h>
#include <cachesim/replacement/policy.h>
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

// Neither policy exposes an accessor for its per-slot state, deliberately and
// for StampPolicy's stated reason, so the two readers below read it the way the
// engine would: by asking pick_victim about a candidate set whose answer the
// wanted value decides. Each takes its policy BY VALUE, so the probing runs on
// a copy and the caller's policy is untouched; that is what policy.h's
// protected-and-defaulted copy constructor exists for.
//
// Both readers are needed by the order-independence cases below, which have to
// compare the state a pick_victim call LEAVES BEHIND and not only the slot it
// answered.

// Probe slots for rrpv_of, above every slot id the cases below name. Their ids
// have to be LARGER than the probed slot, since the tie at the maximum RRPV
// goes to the smallest id and the probes read the answer as "was it the probed
// slot".
constexpr std::int32_t kRripProbeA = 30;
constexpr std::int32_t kRripProbeB = 31;

// The RRPV of `slot`, in [0, 3]. Requires a policy of at least 32 slots and a
// slot id below kRripProbeA.
//
// Two facts make the probes exact. pick_victim raises every candidate by the
// single delta (3 - the largest RRPV among them), so a probe already at 3
// freezes the set and a probe at 3-d ages it by exactly d; and the answer is
// the smallest slot id among those at 3 after that raise.
int rrpv_of(RripPolicy p, std::int32_t slot) {
    // A probe at the maximum, so the raise is 0 and nothing moves: the answer
    // is the probed slot exactly when it is already at the maximum.
    p.on_invalidate(SlotId{kRripProbeA});
    if (p.pick_victim(candidates_over({slot, kRripProbeA})) == SlotId{slot}) return 3;

    // A probe at the insertion value ages the pair by 1, so the probed slot
    // reaches the maximum exactly when it stood one below it.
    p.on_fill(SlotId{kRripProbeB});
    if (p.pick_victim(candidates_over({slot, kRripProbeB})) == SlotId{slot}) return 2;

    // And once more, which is two rounds of aging in total.
    p.on_fill(SlotId{kRripProbeA});
    if (p.pick_victim(candidates_over({slot, kRripProbeA})) == SlotId{slot}) return 1;

    return 0;
}

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

void test_rrip_inserts_below_the_maximum_and_ages_to_it() {
    check::group("P4: RRIP -- insertion at 2, a hit at 0, and the aging loop between them");

    // A slot that has never been filled sits at the maximum, so it is the
    // victim before any line, which is the same preference LRU states with its
    // never-stamped sentinel.
    RripPolicy p(32);
    CHECK_EQ(rrpv_of(p, 0), 3);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});
    // Fill lands at insertion value 2 (below the maximum); the exact value is pinned
    // by aging rounds further down, not by these checks.
    CHECK_EQ(rrpv_of(p, 0), 2);
    CHECK_EQ(rrpv_of(p, 3), 2);

    p.on_hit(SlotId{0});
    CHECK_EQ(rrpv_of(p, 0), 0);

    // Round 1. The largest RRPV present is 2, so every candidate rises by 1:
    // three of them land on the maximum and the hit line lands on 1, which is
    // the reprieve the hit bought it.
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    CHECK_EQ(p.pick_victim(set), SlotId{1});
    CHECK_EQ(rrpv_of(p, 0), 1);
    CHECK_EQ(rrpv_of(p, 1), 3);
    CHECK_EQ(rrpv_of(p, 2), 3);
    CHECK_EQ(rrpv_of(p, 3), 3);

    // Rounds 2 and 3. Refilling the victim puts it back at 2, and the other
    // candidates still at the maximum make the raise 0, so the hit line is not
    // aged at all while there is a slot at the maximum to take.
    p.on_fill(SlotId{1});
    CHECK_EQ(p.pick_victim(set), SlotId{2});
    CHECK_EQ(rrpv_of(p, 0), 1);
    p.on_fill(SlotId{2});
    CHECK_EQ(p.pick_victim(set), SlotId{3});
    CHECK_EQ(rrpv_of(p, 0), 1);
    p.on_fill(SlotId{3});

    // Round 4. Nothing is at the maximum any more, so the raise is 1 again and
    // the hit line finally reaches 2. It survived three evictions on one hit,
    // which is the whole of what SRRIP's insertion value buys.
    CHECK_EQ(p.pick_victim(set), SlotId{1});
    CHECK_EQ(rrpv_of(p, 0), 2);
    CHECK_EQ(rrpv_of(p, 1), 3);

    // A second hit puts it back to 0 from wherever it had aged to, so the reset
    // is to a value and not a decrement.
    p.on_hit(SlotId{0});
    CHECK_EQ(rrpv_of(p, 0), 0);
}

void test_rrip_invalidate_pins_a_slot_at_the_maximum() {
    check::group("P4: RRIP -- an invalidated way is taken without aging the live lines");

    RripPolicy p(32);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});

    // Slot 2 is neither the smallest id nor the oldest fill, so nothing but the
    // invalidate can make it the answer.
    p.on_invalidate(SlotId{2});
    CHECK_EQ(rrpv_of(p, 2), 3);
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2, 3})), SlotId{2});

    // And the live lines did not move, which is the point of pinning at the
    // maximum rather than merely high: a set holding an empty way answers it
    // immediately and spends none of the other lines' remaining life doing so.
    CHECK_EQ(rrpv_of(p, 0), 2);
    CHECK_EQ(rrpv_of(p, 1), 2);
    CHECK_EQ(rrpv_of(p, 3), 2);

    // Refilling it puts it back to the insertion value, so the pin is a state
    // the slot leaves again rather than one it stays in.
    p.on_fill(SlotId{2});
    CHECK_EQ(rrpv_of(p, 2), 2);
    CHECK_EQ(p.pick_victim(candidates_over({0, 1, 2, 3})), SlotId{0});
}

void test_rrip_ties_go_to_the_smallest_slot_id() {
    check::group("P4: RRIP -- ties at the maximum go to the smallest slot id");

    // Every slot starts at the maximum, so all three tie and the raise is 0.
    RripPolicy p(32);
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({5, 9, 2})), SlotId{2});

    // Filling the smallest moves the answer to the smallest of those still at
    // the maximum, so the tie-break decides only ties.
    p.on_fill(SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{5});
    p.on_fill(SlotId{5});
    CHECK_EQ(p.pick_victim(candidates_over({5, 2, 9})), SlotId{9});

    // With all three at the insertion value the raise is 1, every candidate
    // reaches the maximum together, and the tie-break is the whole answer.
    RripPolicy all(32);
    for (std::int32_t s : {9, 2, 5}) all.on_fill(SlotId{s});
    CHECK_EQ(all.pick_victim(candidates_over({9, 5, 2})), SlotId{2});
}

void test_lfu_and_rrip_are_order_independent() {
    check::group("P4: policy.h's contract applied to LFU and RRIP, over every permutation");

    const std::vector<std::int32_t> slots{1, 3, 4, 6, 7};
    auto read_count = [](const LfuPolicy& p, std::int32_t s) {
        return static_cast<std::int64_t>(lfu_count_of(p, s));
    };
    auto read_rrpv = [](const RripPolicy& p, std::int32_t s) {
        return static_cast<std::int64_t>(rrpv_of(p, s));
    };

    // LFU, all counts tied at zero. This is the case the tie-break exists for
    // and the one a naive minimum fails.
    expect_state_invariant("lfu, all counts tied", [] { return LfuPolicy(32); },
                           read_count, slots, SlotId{1});

    // LFU, every count distinct, so the tie-break never runs and the answer is
    // the least used line.
    expect_state_invariant(
        "lfu, distinct counts",
        [] {
            LfuPolicy p(32);
            const std::int32_t hits[5][2] = {{1, 3}, {3, 1}, {4, 2}, {6, 5}, {7, 4}};
            for (const auto& h : hits) {
                p.on_fill(SlotId{h[0]});
                for (std::int32_t i = 0; i < h[1]; ++i) p.on_hit(SlotId{h[0]});
            }
            return p;
        },
        read_count, slots, SlotId{3});

    // LFU, a partial tie: two candidates at the minimum and three above it.
    expect_state_invariant(
        "lfu, partial tie",
        [] {
            LfuPolicy p(32);
            for (std::int32_t s : {1, 3, 4, 6, 7}) p.on_fill(SlotId{s});
            for (std::int32_t s : {1, 1, 3, 7, 7}) p.on_hit(SlotId{s});
            return p;
        },
        read_count, slots, SlotId{4});

    // RRIP with every candidate at the insertion value, which is the case that
    // AGES: the raise is 1 and every candidate ends at the maximum. A
    // mutate-and-rescan aging loop answers this one correctly and leaves
    // different RRPVs behind depending on the order, which is what the state
    // half of the check catches.
    expect_state_invariant(
        "rrip, all at the insertion value",
        [] {
            RripPolicy p(32);
            for (std::int32_t s : {1, 3, 4, 6, 7}) p.on_fill(SlotId{s});
            return p;
        },
        read_rrpv, slots, SlotId{1});

    // RRIP with one candidate already at the maximum, so the raise is 0 and no
    // live line may move.
    expect_state_invariant(
        "rrip, one already at the maximum",
        [] {
            RripPolicy p(32);
            for (std::int32_t s : {1, 3, 4, 6, 7}) p.on_fill(SlotId{s});
            p.on_invalidate(SlotId{6});
            return p;
        },
        read_rrpv, slots, SlotId{6});

    // RRIP with a hit line among the candidates: the raise is 1, four
    // candidates tie at the maximum, and the hit line lands on 1.
    expect_state_invariant(
        "rrip, one hit line",
        [] {
            RripPolicy p(32);
            for (std::int32_t s : {1, 3, 4, 6, 7}) p.on_fill(SlotId{s});
            p.on_hit(SlotId{3});
            return p;
        },
        read_rrpv, slots, SlotId{1});
}

// --- the RRPV width (plan 0907-linesize) -------------------------------------
//
// M is a constructor argument now, so two facts need pinning: the default is
// still 2, so no committed result moves, and a wider M really does give a
// deeper order rather than being accepted and ignored.
//
// The probe is aging itself. pick_victim raises every candidate by
// (max - the largest RRPV among them), so a slot at the insertion value is one
// raise from the maximum at ANY width. What the width changes is how many
// raises a slot that was just hit needs to walk from 0 back to the maximum, and
// that count is what separates M = 2 from M = 5 here.
void test_rrip_bits_widens_the_rrpv() {
    check::group("P5: RRIP -- a wider M gives a deeper priority order");

    for (std::int32_t bits : {2, 3, 5}) {
        const int max_rrpv = (1 << bits) - 1;
        RripPolicy p(32, bits);
        p.on_fill(SlotId{0});
        p.on_fill(SlotId{1});
        p.on_hit(SlotId{0});          // slot 0 -> 0, slot 1 -> max - 1

        // One raise puts slot 1 at the maximum, so it goes first at every width.
        CHECK_EQ(p.pick_victim(candidates_over({0, 1})), SlotId{1});

        // Slot 0 was raised to 1 by that call and now needs max_rrpv - 1 more
        // raises to reach the maximum. Each single-candidate pick_victim is one
        // raise, and the slot is trivially the victim throughout; the fact being
        // pinned is that the walk takes exactly this many steps, which IS the
        // depth the width buys.
        for (int i = 1; i < max_rrpv; ++i) {
            CHECK_EQ(p.pick_victim(candidates_over({0})), SlotId{0});
        }

        // A second slot freshly hit is now strictly younger than slot 0, and at
        // M = 2 there is no room left to express that: slot 0 is already at the
        // maximum either way. At M = 5 there is.
        RripPolicy q(32, bits);
        q.on_fill(SlotId{0});
        q.on_fill(SlotId{1});
        q.on_hit(SlotId{1});
        CHECK_EQ(q.pick_victim(candidates_over({0, 1})), SlotId{0});
    }
}

void test_rrip_refuses_a_width_outside_the_store() {
    check::group("P5: RRIP -- a width outside [1, 8] is refused");
    CHECK_THROWS(std::invalid_argument, RripPolicy(32, 0));
    CHECK_THROWS(std::invalid_argument, RripPolicy(32, 9));
    CHECK_THROWS(std::invalid_argument, RripPolicy(0, 2));
}

// The default reaches through make_policy unchanged, which is what keeps every
// row taken before the knob existed reproducible.
void test_make_policy_passes_rrip_bits_through() {
    check::group("P5: make_policy -- rrip_bits defaults to 2 and is passed through");
    CHECK_TRUE(make_policy(PolicyKind::RRIP, 32) != nullptr);
    CHECK_TRUE(make_policy(PolicyKind::RRIP, 32, 5) != nullptr);
    // Inert on every other kind rather than refused: a call site that does not
    // build RRIP has nothing to say about the width.
    CHECK_TRUE(make_policy(PolicyKind::LRU, 32, 5) != nullptr);
}

int main() {
    test_rrip_inserts_below_the_maximum_and_ages_to_it();
    test_rrip_invalidate_pins_a_slot_at_the_maximum();
    test_rrip_ties_go_to_the_smallest_slot_id();
    test_lfu_and_rrip_are_order_independent();
    test_rrip_bits_widens_the_rrpv();
    test_rrip_refuses_a_width_outside_the_store();
    test_make_policy_passes_rrip_bits_through();
    return check::summary();
}
