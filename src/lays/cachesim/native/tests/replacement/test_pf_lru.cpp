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
// T24: the random fallback (Fallback::Rand), cases (a) through (d)
// ===========================================================================
//
// The rand mode differs from the default in EXACTLY one situation: every
// candidate is protected. The four cases below pin (a) that the forced victim
// is no longer a fixed slot, (b) that it is nevertheless deterministic,
// (c) that each draw is still a function of the candidate SET, and (d) that
// whenever an unprotected candidate exists the two modes are the same policy.

std::vector<Candidate> sixteen_candidates() {
    return candidates_over({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15});
}

void fill_and_protect_all(PfLruPolicy& p, std::int32_t n) {
    for (std::int32_t s = 0; s < n; ++s) p.on_fill(SlotId{s});
    for (std::int32_t s = 0; s < n; ++s) p.note_protected(SlotId{s}, true);
}

void test_rand_fallback_spreads_across_slots() {
    check::group("T24a: all-protected draws spread across slots, no fixed victim");

    // T23's failure mode was the fallback victimizing the SAME slot in every
    // set; the rand mode exists to break that. The policy state is held fixed
    // across draws, so only the draw counter moves, and the victims must
    // still spread: at least 4 distinct slots out of 16 over 64 draws (a
    // uniform draw would give ~15.7 distinct).
    PfLruPolicy p(16, PfLruPolicy::Fallback::Rand);
    fill_and_protect_all(p, 16);
    const std::vector<Candidate> set = sixteen_candidates();

    std::vector<int> hits(16, 0);
    int distinct = 0;
    for (int d = 0; d < 64; ++d) {
        const SlotId v = p.pick_victim(set);
        const std::int32_t s = v.get();
        CHECK_TRUE(s >= 0 && s < 16);
        if (hits[static_cast<std::size_t>(s)]++ == 0) ++distinct;
    }
    CHECK_TRUE(distinct >= 4);
}

void test_rand_fallback_is_deterministic() {
    check::group("T24b: two identical call sequences give identical victims");

    // No global RNG and no platform entropy: the draw is a pure function of
    // (candidate set, fixed seed, draw counter), so two policies driven
    // identically agree draw for draw.
    PfLruPolicy a(16, PfLruPolicy::Fallback::Rand);
    PfLruPolicy b(16, PfLruPolicy::Fallback::Rand);
    fill_and_protect_all(a, 16);
    fill_and_protect_all(b, 16);
    const std::vector<Candidate> set = sixteen_candidates();
    for (int d = 0; d < 32; ++d) CHECK_EQ(a.pick_victim(set), b.pick_victim(set));
}

void test_rand_fallback_is_invariant_under_permutation() {
    check::group("T24c: permuting the candidate set cannot change any single draw");

    // pick_over_every_permutation cannot serve here: each pick_victim call is
    // its own draw, so the SAME draw index must be compared across orders.
    // One fresh, identically driven policy per permutation, checked against
    // the sorted order's victims draw for draw.
    const auto drive = [](PfLruPolicy& p) { fill_and_protect_all(p, 8); };
    const std::vector<Candidate> ordered = candidates_over({1, 3, 4, 6});
    constexpr int kDraws = 4;

    std::vector<SlotId> reference;
    {
        PfLruPolicy p(8, PfLruPolicy::Fallback::Rand);
        drive(p);
        for (int d = 0; d < kDraws; ++d) reference.push_back(p.pick_victim(ordered));
    }

    std::vector<std::size_t> order = {0, 1, 2, 3};
    long permutations = 0;
    do {
        PfLruPolicy p(8, PfLruPolicy::Fallback::Rand);
        drive(p);
        std::vector<Candidate> shuffled;
        for (std::size_t i : order) shuffled.push_back(ordered[i]);
        for (int d = 0; d < kDraws; ++d)
            CHECK_EQ(p.pick_victim(shuffled), reference[static_cast<std::size_t>(d)]);
        ++permutations;
    } while (std::next_permutation(order.begin(), order.end()));
    CHECK_TRUE(permutations == 24);
}

void test_rand_mode_matches_lru_fallback_mode_outside_the_fallback() {
    check::group("T24d: with any unprotected candidate the two modes are one policy");

    // A scripted interleaved protect/unprotect/fill/hit sequence driven
    // through both modes in lockstep. pick_victim mutates no stamps and no
    // bits (only the rand draw counter), so the two policies' states stay
    // identical throughout, and every pick taken while an unprotected
    // candidate exists must agree. The op stream is a fixed LCG, weighted
    // toward protect so the all-protected fallback is actually reached.
    PfLruPolicy lru_fb(4);
    PfLruPolicy rnd_fb(4, PfLruPolicy::Fallback::Rand);
    bool prot[4] = {false, false, false, false};
    for (std::int32_t s = 0; s < 4; ++s) {
        lru_fb.on_fill(SlotId{s});
        rnd_fb.on_fill(SlotId{s});
    }
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});

    std::uint32_t x = 12345u;
    const auto next = [&x] {
        x = x * 1664525u + 1013904223u;
        return x >> 16;
    };

    int compared = 0;
    int skipped  = 0;
    for (int i = 0; i < 300; ++i) {
        const std::uint32_t op = next() % 8u;
        const SlotId s{static_cast<std::int32_t>(next() % 4u)};
        if (op == 0) {
            lru_fb.on_fill(s);
            rnd_fb.on_fill(s);
            prot[s.get()] = false;
        } else if (op == 1) {
            lru_fb.on_hit(s);
            rnd_fb.on_hit(s);
        } else if (op <= 5) {
            lru_fb.note_protected(s, true);
            rnd_fb.note_protected(s, true);
            prot[s.get()] = true;
        } else {
            lru_fb.note_protected(s, false);
            rnd_fb.note_protected(s, false);
            prot[s.get()] = false;
        }
        const bool any_unprotected = !prot[0] || !prot[1] || !prot[2] || !prot[3];
        const SlotId a = lru_fb.pick_victim(set);
        const SlotId b = rnd_fb.pick_victim(set);
        if (any_unprotected) {
            CHECK_EQ(a, b);
            ++compared;
        } else {
            ++skipped;
        }
    }
    // Both regimes were actually exercised, or the test proved nothing.
    CHECK_TRUE(compared > 0);
    CHECK_TRUE(skipped > 0);
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
    test_rand_fallback_spreads_across_slots();
    test_rand_fallback_is_deterministic();
    test_rand_fallback_is_invariant_under_permutation();
    test_rand_mode_matches_lru_fallback_mode_outside_the_fallback();
    test_every_new_verb_bound_checks_its_slot();
    return check::summary();
}
