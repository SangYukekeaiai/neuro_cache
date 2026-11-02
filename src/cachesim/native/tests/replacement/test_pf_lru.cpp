// T18: PfLruPolicy, two-class LRU behind the note_protected hook.
//
// Its own file for the reason every policy suite has one: a test file mirrors
// the module under test. What is specific to this unit is the hook: the six
// cases below are the T18 list from docs/plans/2026-11-02-l2-pf-lru-replacement.md,
// (a) through (f), and (f) is carried twice -- here, by driving the existing
// stamp policies through a base reference whose note_protected is the default
// no-op, and by every pre-existing suite staying green with the hook in
// policy.h.
#include <cachesim/replacement/pf_lru.h>

#include <cachesim/replacement/policy.h>
#include <cachesim/replacement/stamp.h>
#include <cachesim/types.h>

#include <algorithm>
#include <cstdint>
#include <initializer_list>
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
// The message probe is test_stamp.cpp's, kept in that shape rather than shared
// through a header: the repo convention is one probe pair per test file,
// because the pair encodes which exception type is CORRECT for the file's
// subject.

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

std::vector<Candidate> candidates_over(std::initializer_list<std::int32_t> slots) {
    std::vector<Candidate> out;
    for (std::int32_t s : slots) out.push_back(Candidate{SlotId{s}, LineId{1000 + s}});
    return out;
}

// pick_victim over EVERY permutation of the candidate set, test_stamp.cpp's
// helper: the A5 order-independence criterion tested as the invariance it is.
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
    CHECK_EQ(got, expected);
    CHECK_TRUE(permutations > 1);
}

// ===========================================================================
// (a) the protected class is passed over
// ===========================================================================

void test_an_older_protected_line_survives() {
    check::group("T18a: the LRU unprotected line goes, however old the protected one is");

    // Slot 0 is the oldest fill AND protected, so plain LRU's answer and this
    // policy's differ, which is the whole content of the class split.
    PfLruPolicy p(8);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    CHECK_EQ(p.pick_victim(set), SlotId{0});  // before the mark: plain LRU
    p.note_protected(SlotId{0}, true);
    CHECK_EQ(p.pick_victim(set), SlotId{1});  // oldest UNPROTECTED

    // A hit on an unprotected line moves the answer within the normal class
    // only: the stamps are still LRU underneath.
    p.on_hit(SlotId{1});
    CHECK_EQ(p.pick_victim(set), SlotId{2});

    // Protecting a second line narrows the normal class further.
    p.note_protected(SlotId{2}, true);
    CHECK_EQ(p.pick_victim(set), SlotId{3});
}

// ===========================================================================
// (b) all candidates protected: plain LRU wins
// ===========================================================================

void test_an_all_protected_set_falls_back_to_plain_lru() {
    check::group("T18b: a set whose ways are all protected victimizes by LRU over all");

    PfLruPolicy p(8);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});
    for (std::int32_t s : {0, 1, 2, 3}) p.note_protected(SlotId{s}, true);
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    CHECK_EQ(p.pick_victim(set), SlotId{0});  // the oldest fill, exactly as LRU

    // And a hit still refreshes a protected line's stamp, so the fallback
    // order is LRU and not fill order.
    p.on_hit(SlotId{0});
    CHECK_EQ(p.pick_victim(set), SlotId{1});
}

// ===========================================================================
// (c) unprotecting returns a line to the normal class
// ===========================================================================

void test_note_protected_false_returns_the_line_to_the_normal_class() {
    check::group("T18c: protection ends when the engine says so, and the line is evictable");

    PfLruPolicy p(8);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});
    p.note_protected(SlotId{0}, true);
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    CHECK_EQ(p.pick_victim(set), SlotId{1});

    // Consumption: the engine clears the bit, and slot 0 is the oldest stamp
    // overall, so it is victimized next.
    p.note_protected(SlotId{0}, false);
    CHECK_EQ(p.pick_victim(set), SlotId{0});

    // Clearing an already-clear bit is a no-op, which is what lets the engine
    // call it unconditionally on every L2 hit.
    p.note_protected(SlotId{0}, false);
    CHECK_EQ(p.pick_victim(set), SlotId{0});
}

// ===========================================================================
// (d) on_fill and on_invalidate reset the bit
// ===========================================================================

void test_a_refill_and_an_invalidate_reset_the_protected_bit() {
    check::group("T18d: the bit describes the slot's CURRENT occupant");

    // Evict a protected line (all-protected fallback picks slot 0), refill the
    // slot: the new occupant starts normal, so it is the victim even though
    // its stamp is now the newest-but-protected set's companion.
    PfLruPolicy p(8);
    for (std::int32_t s : {0, 1, 2, 3}) p.on_fill(SlotId{s});
    for (std::int32_t s : {0, 1, 2, 3}) p.note_protected(SlotId{s}, true);
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    const SlotId victim = p.pick_victim(set);
    CHECK_EQ(victim, SlotId{0});
    p.on_fill(victim);  // the evicting insert's fill
    CHECK_EQ(p.pick_victim(set), SlotId{0});  // newest stamp, but the only normal line

    // on_invalidate clears the bit too: a back-invalidated slot holds nothing,
    // so it must not sit in the protected class on the strength of a line that
    // is gone.
    PfLruPolicy q(8);
    for (std::int32_t s : {0, 1, 2, 3}) q.on_fill(SlotId{s});
    q.note_protected(SlotId{3}, true);
    q.on_invalidate(SlotId{3});
    // Slot 3 is back to never-stamped AND unprotected: the preferred victim.
    CHECK_EQ(q.pick_victim(candidates_over({0, 1, 2, 3})), SlotId{3});
}

// ===========================================================================
// (e) order independence
// ===========================================================================

void test_pick_victim_is_invariant_under_permutation() {
    check::group("T18e: permuting the candidate set cannot change the answer");

    // The three states the class split adds to StampPolicy's own invariance
    // suite: a mixed set, an all-protected set, and a set whose normal class
    // ties on never-stamped slots.

    PfLruPolicy mixed(8);
    for (std::int32_t s : {6, 3, 7, 1, 4}) mixed.on_fill(SlotId{s});
    mixed.note_protected(SlotId{6}, true);  // the oldest fill is protected
    expect_invariant("mixed classes", mixed, candidates_over({1, 3, 4, 6, 7}), SlotId{3});

    PfLruPolicy shielded(8);
    for (std::int32_t s : {6, 3, 7, 1, 4}) shielded.on_fill(SlotId{s});
    for (std::int32_t s : {1, 3, 4, 6, 7}) shielded.note_protected(SlotId{s}, true);
    expect_invariant("all protected", shielded, candidates_over({1, 3, 4, 6, 7}), SlotId{6});

    // Never-stamped normal slots tie, and the tie-break is StampPolicy's:
    // the smallest slot id among them.
    PfLruPolicy ties(8);
    for (std::int32_t s : {6, 3}) ties.on_fill(SlotId{s});
    ties.note_protected(SlotId{3}, true);
    expect_invariant("ties in the normal class", ties, candidates_over({1, 3, 4, 6, 7}),
                     SlotId{1});
}

// ===========================================================================
// (f) the default hook is a no-op on every existing policy
// ===========================================================================

void test_existing_policies_ignore_note_protected() {
    check::group("T18f: note_protected on a policy without classes changes nothing");

    // Driven through the interface, exactly as the engine will call it: the
    // same calls that split PfLruPolicy's answer leave LRU's and FIFO's where
    // they were.
    LruPolicy lru(8);
    FifoPolicy fifo(8);
    for (std::int32_t s : {0, 1, 2, 3}) {
        lru.on_fill(SlotId{s});
        fifo.on_fill(SlotId{s});
    }
    ReplacementPolicy& l = lru;
    ReplacementPolicy& f = fifo;
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    l.note_protected(SlotId{0}, true);
    f.note_protected(SlotId{0}, true);
    CHECK_EQ(l.pick_victim(set), SlotId{0});
    CHECK_EQ(f.pick_victim(set), SlotId{0});
}

// ===========================================================================
// Bound checks, StampPolicy's pattern on the bit vector
// ===========================================================================

void test_every_new_verb_bound_checks_its_slot() {
    check::group("T18: a slot id from a differently sized array is refused, not written");

    PfLruPolicy p(8);
    expect_message("note_protected past the end",
                   range_thrown_by([&] { p.note_protected(SlotId{8}, true); }),
                   "PfLruPolicy::note_protected", {"slot 8", "outside [0, 8)"});
    expect_message("note_protected negative",
                   range_thrown_by([&] { p.note_protected(SlotId{-1}, true); }),
                   "PfLruPolicy::note_protected", {"slot -1", "outside [0, 8)"});
    expect_message("pick_victim over a foreign slot",
                   range_thrown_by([&] { (void)p.pick_victim(candidates_over({0, 8})); }),
                   "PfLruPolicy::pick_victim", {"slot 8", "outside [0, 8)"});
    expect_message("on_fill past the end",
                   range_thrown_by([&] { p.on_fill(SlotId{8}); }),
                   "PfLruPolicy::on_fill", {"slot 8"});
    expect_message("on_invalidate past the end",
                   range_thrown_by([&] { p.on_invalidate(SlotId{8}); }),
                   "PfLruPolicy::on_invalidate", {"slot 8"});

    // The constructor's refusal is StampPolicy's, reached through the base.
    CHECK_THROWS(std::invalid_argument, PfLruPolicy(0));

    // The boundary: the last slot is accepted.
    p.note_protected(SlotId{7}, true);
    p.on_fill(SlotId{7});
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// `final` for B10's reason, and built on StampPolicy: the stamps ARE plain
// LRU's, so the two classes cannot drift apart in how they age.
static_assert(std::is_final<PfLruPolicy>::value, "");
static_assert(!std::is_abstract<PfLruPolicy>::value, "");
static_assert(std::is_base_of<StampPolicy, PfLruPolicy>::value, "");

// note_protected crosses the split as a SlotId and a bit, nothing more: no
// line, no address, no set index.
static_assert(std::is_same<decltype(&ReplacementPolicy::note_protected),
                           void (ReplacementPolicy::*)(SlotId, bool)>::value, "");

// The constructor is explicit, as every policy's is.
static_assert(std::is_constructible<PfLruPolicy, std::int32_t>::value, "");
static_assert(!std::is_convertible<std::int32_t, PfLruPolicy>::value, "");

}  // namespace

int main() {
    test_an_older_protected_line_survives();
    test_an_all_protected_set_falls_back_to_plain_lru();
    test_note_protected_false_returns_the_line_to_the_normal_class();
    test_a_refill_and_an_invalidate_reset_the_protected_bit();
    test_pick_victim_is_invariant_under_permutation();
    test_existing_policies_ignore_note_protected();
    test_every_new_verb_bound_checks_its_slot();
    return check::summary();
}
