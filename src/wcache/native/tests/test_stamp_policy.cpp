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
#include <wcache/stamp_policy.h>

#include <wcache/block_pack.h>
#include <wcache/cache.h>
#include <wcache/layout.h>
#include <wcache/policy.h>
#include <wcache/set_associative.h>
#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "check.h"

using namespace wcache;

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

// A policy that counts its own destruction, held and destroyed through the
// interface exactly as the engine holds one. It implements the four verbs
// trivially: what it is for is the destructor.
int g_destroyed = 0;

struct CountingPolicy final : ReplacementPolicy {
    void on_hit(SlotId) override {}
    void on_fill(SlotId) override {}
    void on_invalidate(SlotId) override {}
    SlotId pick_victim(const std::vector<Candidate>&) override { return NoSlot; }
    ~CountingPolicy() override { ++g_destroyed; }
};

// --- the array driver ---------------------------------------------------------

// The geometry the divergence cases run on: 4096 bytes of 256-byte lines is 16
// lines, 4 ways deep is 4 sets. Small on purpose, because a set that never
// fills never asks a policy anything.
constexpr WeightShape kShape{3, 3, 512, 512};
constexpr std::int64_t kBytes = 4096;
constexpr std::int32_t kWays  = 4;
constexpr std::int64_t kSets  = 4;

// One access, driven the way the engine will drive it (plan 3.4, minus the
// timing): probe, take a free way if there is one, otherwise ask the policy
// over the whole candidate set, insert, and tell the policy about the fill.
//
// The engine makes every policy call here, and the array makes none: probe is
// not an access, so `on_hit` is this loop's business rather than the array's.
// That is 2.2's rule and it is what makes the two policies' difference
// observable at all.
//
// Returns the lines that were evicted, in order, which is what the two
// policies disagree about.
std::vector<std::int64_t> drive(ReplacementPolicy& p, SetAssociativeArray& a,
                                const std::vector<std::int64_t>& stream, long& hits) {
    std::vector<std::int64_t> evicted;
    std::vector<Candidate> out;
    for (std::int64_t l : stream) {
        const LineId line{l};
        const SlotId found = a.probe(line);
        if (found != NoSlot) {
            ++hits;
            p.on_hit(found);
            continue;
        }
        SlotId target = a.free_slot(line);
        if (target == NoSlot) {
            a.victim_candidates(line, out);
            target = p.pick_victim(out);
        }
        const InsertResult r = a.insert(line, target);
        if (r.evicted) evicted.push_back(r.evicted_line.get());
        p.on_fill(target);
    }
    return evicted;
}

// The same stream under a named policy, on a fresh array each time, so the two
// runs differ in the policy and in nothing else.
std::vector<std::int64_t> run(const AddressMapper& m, PolicyKind kind,
                              const std::vector<std::int64_t>& stream, long& hits) {
    SetAssociativeArray a(m, kBytes, kWays);
    std::unique_ptr<ReplacementPolicy> p = make_policy(kind, a.num_slots());
    return drive(*p, a, stream, hits);
}

// ===========================================================================
// Construction and the bound checks
// ===========================================================================

void test_the_constructor_refuses_a_non_positive_slot_count() {
    check::group("A5: num_slots must be >= 1, refused as a config value");

    // A throw rather than an assert, for SetAssociativeArray's reason: the slot
    // count is derived from config fields, so it has to be refused under
    // -DNDEBUG, which is the build the sweep runs in. A zero-slot array is a
    // cache that can hold nothing.
    expect_message("zero slots", thrown_by([] { LruPolicy p(0); }),
                   "StampPolicy: ", {"num_slots", "must be >= 1", "got 0"});
    expect_message("negative slots", thrown_by([] { FifoPolicy p(-4); }),
                   "StampPolicy: ", {"num_slots", "must be >= 1", "got -4"});

    // The boundary is >= 1 rather than > 0 spelled differently: one slot is a
    // legal direct-mapped cache of one line, and it constructs.
    LruPolicy one(1);
    one.on_fill(SlotId{0});
    CHECK_EQ(one.pick_victim(candidates_over({0})), SlotId{0});

    // Both refusals are invalid_argument, which is the tier B27 gives a
    // malformed argument, and the catch site has to tell that from a bad
    // access.
    CHECK_THROWS(std::invalid_argument, LruPolicy(0));
    CHECK_THROWS(std::invalid_argument, FifoPolicy(0));
}

void test_every_verb_bound_checks_its_slot() {
    check::group("A5: a slot id from a differently sized array is refused, not written");

    // What the check prevents is an out-of-bounds write into the stamp vector:
    // a policy handed the slot ids of a bigger array would otherwise corrupt
    // memory silently rather than say so. out_of_range and not
    // invalid_argument, which is the same tier and the same reason
    // SetAssociativeArray::insert applies to the same quantity.
    LruPolicy p(8);

    expect_message("on_fill past the end", range_thrown_by([&] { p.on_fill(SlotId{8}); }),
                   "StampPolicy::stamp", {"slot 8", "outside [0, 8)"});
    expect_message("on_fill negative", range_thrown_by([&] { p.on_fill(SlotId{-1}); }),
                   "StampPolicy::stamp", {"slot -1", "outside [0, 8)"});
    expect_message("on_hit past the end", range_thrown_by([&] { p.on_hit(SlotId{8}); }),
                   "StampPolicy::stamp", {"slot 8"});
    expect_message("on_invalidate past the end",
                   range_thrown_by([&] { p.on_invalidate(SlotId{8}); }),
                   "StampPolicy::on_invalidate", {"slot 8", "outside [0, 8)"});
    expect_message("pick_victim over a foreign slot",
                   range_thrown_by([&] { (void)p.pick_victim(candidates_over({0, 8})); }),
                   "StampPolicy::pick_victim", {"slot 8", "outside [0, 8)"});
    // The first candidate is bound-checked too, which is worth its own case
    // because it is read outside the loop that checks the rest.
    expect_message("pick_victim's first candidate",
                   range_thrown_by([&] { (void)p.pick_victim(candidates_over({9, 0})); }),
                   "StampPolicy::pick_victim", {"slot 9"});
    expect_message("on_hit at NoSlot", range_thrown_by([&] { p.on_hit(NoSlot); }),
                   "StampPolicy::stamp", {"2147483647"});

    // The boundary: the last slot is accepted.
    p.on_fill(SlotId{7});
    CHECK_EQ(p.pick_victim(candidates_over({7})), SlotId{7});

    // FIFO's on_hit does NOT bound-check, and that is recorded here rather
    // than asserted as right: its body is empty by design, so there is nothing
    // to check the slot for. The asymmetry is real -- a policy handed a foreign
    // slot id is caught under LRU and not under FIFO -- and it is a fact about
    // the code rather than a rule anybody wrote, so this check pins what the
    // code does and the finding is reported rather than designed around.
    FifoPolicy f(8);
    f.on_hit(SlotId{8});
    f.on_hit(NoSlot);
    CHECK_EQ(f.pick_victim(candidates_over({0, 1})), SlotId{0});
}

void test_pick_victim_refuses_an_empty_candidate_set() {
    check::group("A5: the minimum of nothing has no answer");

    // Not defensive padding: the alternative to refusing is returning a slot
    // id that names no candidate, which the caller then installs a line into.
    LruPolicy p(8);
    const std::vector<Candidate> none;
    expect_message("empty", thrown_by([&] { (void)p.pick_victim(none); }),
                   "StampPolicy::pick_victim: ", {"candidate set is empty"});
    CHECK_THROWS(std::invalid_argument, p.pick_victim(none));

    // A single candidate is the direct-mapped case and is answered, not
    // refused: at associativity 1 the candidate list has one entry and every
    // policy must return it.
    CHECK_EQ(p.pick_victim(candidates_over({5})), SlotId{5});
}

// ===========================================================================
// The victim rule
// ===========================================================================

void test_pick_victim_is_invariant_under_permutation() {
    check::group("A5: permuting the candidate set cannot change the answer");

    // Four states, chosen because each one is a different way for the rule to
    // become order-dependent. All four are checked over every permutation of a
    // five-way set, which is 120 arrangements apiece.

    // 1. Nothing has ever been filled, so every stamp ties. This is the state
    //    the tie-break exists for: without it the answer would be whichever of
    //    them the vector happened to hold first.
    LruPolicy fresh(8);
    expect_invariant("all never stamped", fresh, candidates_over({1, 3, 4, 6, 7}), SlotId{1});

    // 2. Every candidate filled, in an order that is not slot order. The
    //    stamps are then all distinct, so the tie-break never runs and the
    //    answer is the oldest fill.
    LruPolicy filled(8);
    for (std::int32_t s : {6, 3, 7, 1, 4}) filled.on_fill(SlotId{s});
    expect_invariant("all filled, oldest wins", filled, candidates_over({1, 3, 4, 6, 7}),
                     SlotId{6});

    // 3. Mixed, which is the case a full set never reaches and a partly filled
    //    one does: the never-stamped slots tie among themselves and beat every
    //    filled one, so the answer is the smallest never-stamped slot.
    LruPolicy mixed(8);
    for (std::int32_t s : {1, 6, 3}) mixed.on_fill(SlotId{s});
    expect_invariant("mixed, an empty way wins", mixed, candidates_over({1, 3, 4, 6, 7}),
                     SlotId{4});

    // 4. After an invalidate, which puts a filled slot back to never-stamped.
    //    Slot 6 was the oldest fill and is now the smallest never-stamped slot,
    //    so it stays the answer for a different reason, and 4 and 7 tie with it.
    LruPolicy invalidated(8);
    for (std::int32_t s : {1, 3, 4, 6, 7}) invalidated.on_fill(SlotId{s});
    invalidated.on_invalidate(SlotId{6});
    expect_invariant("after an invalidate", invalidated, candidates_over({1, 3, 4, 6, 7}),
                     SlotId{6});

    // FIFO answers the same way, since the rule is StampPolicy's and the two
    // subclasses differ only in what a hit does.
    FifoPolicy fifo(8);
    for (std::int32_t s : {6, 3, 7, 1, 4}) fifo.on_fill(SlotId{s});
    expect_invariant("FIFO obeys the same rule", fifo, candidates_over({1, 3, 4, 6, 7}),
                     SlotId{6});
}

void test_the_tie_break_is_the_smallest_slot_id() {
    check::group("A5: ties go to the smallest slot id, not to the first one offered");

    // The half of the invariance that is a value rather than a property. It is
    // checked directly as well, because "invariant" and "correct" are
    // independent: a policy that always answered candidates.back() would be
    // invariant under nothing and one that always answered SlotId{0} would be
    // invariant under everything.
    LruPolicy p(16);
    CHECK_EQ(p.pick_victim(candidates_over({9, 2, 5})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({5, 9, 2})), SlotId{2});

    // And a never-filled slot beats a filled one however recently the filled
    // one was touched, which is the right preference rather than an accident of
    // the sentinel: an empty way costs nothing to evict, so a policy that
    // preferred a live line would evict one while a way sat empty.
    p.on_fill(SlotId{2});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{5});
    p.on_fill(SlotId{5});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{9});
    p.on_fill(SlotId{9});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{2});  // the oldest fill

    // on_invalidate is observable rather than a formality: it puts the slot
    // back to never-stamped, so it is taken first. Leaving the previous
    // occupant's stamp would make an invalidated slot compete on the age of a
    // line that is gone.
    p.on_invalidate(SlotId{9});
    CHECK_EQ(p.pick_victim(candidates_over({2, 5, 9})), SlotId{9});
}

// The preference stated as itself, for each policy separately, rather than as a
// consequence of the tie-break or of the sentinel's value.
//
// Both halves are asserted through a FifoPolicy as well as an LruPolicy, and
// that is not duplication of a shared rule. pick_victim, on_fill and
// on_invalidate are StampPolicy's, but nothing else in this suite says FIFO
// inherits them unchanged: FifoPolicy already overrides one of the four verbs,
// so "it overrides no others" is a fact about the class that has to be checked
// on the class. Before this case every runtime invalidate in the file ran
// through an LruPolicy, so a FifoPolicy that ignored the verb was invisible.
void test_a_never_filled_way_is_the_preferred_victim() {
    check::group("A5: an empty way is taken before any live line, under both policies");

    // Fresh array, some ways filled and some never touched. The never-filled
    // ways must win however recently the filled ones were used, because such a
    // way holds no line and evicting it costs nothing. A policy that got this
    // backwards would evict a live line while a way sat unused, which is not a
    // crash and shows up only as a hit rate that is quietly wrong.
    LruPolicy lru(8);
    FifoPolicy fifo(8);
    for (std::int32_t s : {0, 1, 2}) {
        lru.on_fill(SlotId{s});
        fifo.on_fill(SlotId{s});
    }
    const std::vector<Candidate> set = candidates_over({0, 1, 2, 5, 6});
    CHECK_EQ(lru.pick_victim(set), SlotId{5});
    CHECK_EQ(fifo.pick_victim(set), SlotId{5});

    // A hit does not buy a filled way a reprieve it did not need: the empty way
    // is still the answer, under the policy that refreshes on a hit and under
    // the one that does not.
    lru.on_hit(SlotId{0});
    fifo.on_hit(SlotId{0});
    CHECK_EQ(lru.pick_victim(set), SlotId{5});
    CHECK_EQ(fifo.pick_victim(set), SlotId{5});

    // And with every way filled, the answer moves to the oldest, which is what
    // says the two checks above are about emptiness rather than about slot 5.
    LruPolicy full_lru(8);
    FifoPolicy full_fifo(8);
    for (std::int32_t s : {0, 1, 2, 5, 6}) {
        full_lru.on_fill(SlotId{s});
        full_fifo.on_fill(SlotId{s});
    }
    CHECK_EQ(full_lru.pick_victim(set), SlotId{0});
    CHECK_EQ(full_fifo.pick_victim(set), SlotId{0});

    // The post-invalidate half, which is the whole point of on_invalidate
    // resetting the stamp: a way whose line was back-invalidated holds nothing,
    // so it returns to preferred-victim status rather than competing on the age
    // of a line that is gone. Slot 6 was the NEWEST fill, so nothing but the
    // reset can make it the answer.
    full_lru.on_invalidate(SlotId{6});
    full_fifo.on_invalidate(SlotId{6});
    CHECK_EQ(full_lru.pick_victim(set), SlotId{6});
    CHECK_EQ(full_fifo.pick_victim(set), SlotId{6});

    // Refilling it puts it back at the newest end, so the reset is a state the
    // slot leaves again and not a slot that is preferred from then on.
    full_lru.on_fill(SlotId{6});
    full_fifo.on_fill(SlotId{6});
    CHECK_EQ(full_lru.pick_victim(set), SlotId{0});
    CHECK_EQ(full_fifo.pick_victim(set), SlotId{0});

    // Two invalidated ways tie with each other and with a never-filled one, and
    // the tie goes to the smallest slot id: an invalidated way and a way that
    // was never filled are the same state, not two ranks of the same state.
    LruPolicy mixed(8);
    for (std::int32_t s : {0, 1, 2, 6}) mixed.on_fill(SlotId{s});
    mixed.on_invalidate(SlotId{6});
    CHECK_EQ(mixed.pick_victim(candidates_over({0, 1, 2, 5, 6})), SlotId{5});
    CHECK_EQ(mixed.pick_victim(candidates_over({0, 1, 2, 6})), SlotId{6});
}

void test_the_stamp_counter_only_increases() {
    check::group("A5: no two occupied slots ever share a stamp");

    // The property the tie-break's argument rests on. Tested as its
    // consequence: fill every slot of a large policy in some order, then evict
    // and refill repeatedly, and the answer must always be the single oldest
    // rather than a tie decided by slot id. A counter that reset, or that
    // stopped advancing, shows up as the answer collapsing to the smallest
    // slot in the set.
    LruPolicy p(64);
    for (std::int32_t s = 0; s < 64; ++s) p.on_fill(SlotId{s});

    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    for (int round = 0; round < 40; ++round) {
        const SlotId victim = p.pick_victim(set);
        // The oldest of the four is what round-robins: 0, 1, 2, 3, 0, ...
        CHECK_EQ(victim, SlotId{round % 4});
        p.on_fill(victim);
    }
}

// ===========================================================================
// LRU against FIFO
// ===========================================================================

void test_a_hit_refreshes_an_lru_stamp_and_not_a_fifo_one() {
    check::group("A5: on_hit is the whole of the difference between the two");

    // Same fills, same hit, same candidate set. The only thing that differs is
    // which class the policy is, and the answers differ, which is what makes
    // FifoPolicy::on_hit an empty body rather than a stub.
    LruPolicy lru(8);
    FifoPolicy fifo(8);
    for (std::int32_t s : {0, 1, 2, 3}) {
        lru.on_fill(SlotId{s});
        fifo.on_fill(SlotId{s});
    }

    const std::vector<Candidate> set = candidates_over({0, 1, 2, 3});
    CHECK_EQ(lru.pick_victim(set), SlotId{0});
    CHECK_EQ(fifo.pick_victim(set), SlotId{0});

    lru.on_hit(SlotId{0});
    fifo.on_hit(SlotId{0});

    CHECK_EQ(lru.pick_victim(set), SlotId{1});   // 0 was just used
    CHECK_EQ(fifo.pick_victim(set), SlotId{0});  // 0 is still the oldest install

    // However heavily it is used, FIFO's answer does not move.
    for (int i = 0; i < 20; ++i) fifo.on_hit(SlotId{0});
    CHECK_EQ(fifo.pick_victim(set), SlotId{0});

    // And LRU's does, every time.
    lru.on_hit(SlotId{1});
    CHECK_EQ(lru.pick_victim(set), SlotId{2});
}

void test_lru_and_fifo_diverge_driving_the_same_array() {
    check::group("A5: one array, one stream, two policies, different evictions");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // Set 0 of a 4-set, 4-way array is lines 0, 4, 8, 12, 16, ... Fill the four
    // ways, hit the oldest, then force one eviction. FIFO evicts the oldest
    // INSTALL and LRU evicts the oldest USE, and the hit is what separates them.
    const std::vector<std::int64_t> stream{0, 4, 8, 12, 0, 16};

    long lru_hits = 0, fifo_hits = 0;
    const std::vector<std::int64_t> lru_evicted  = run(m, PolicyKind::LRU, stream, lru_hits);
    const std::vector<std::int64_t> fifo_evicted = run(m, PolicyKind::FIFO, stream, fifo_hits);

    // The hit is common to both: the two policies do not change what is
    // resident, only what leaves.
    CHECK_EQ(lru_hits, 1L);
    CHECK_EQ(fifo_hits, 1L);

    CHECK_EQ(check::ssize(lru_evicted), std::int64_t{1});
    CHECK_EQ(check::ssize(fifo_evicted), std::int64_t{1});
    CHECK_EQ(lru_evicted[0], std::int64_t{4});   // 0 was just used, so 4 is oldest by use
    CHECK_EQ(fifo_evicted[0], std::int64_t{0});  // 0 was installed first

    // With no hit in the stream the two agree, which is what says the
    // divergence above is caused by the hit and not by anything else about the
    // two classes.
    const std::vector<std::int64_t> no_hits{0, 4, 8, 12, 16};
    long a_hits = 0, b_hits = 0;
    const std::vector<std::int64_t> lru_cold  = run(m, PolicyKind::LRU, no_hits, a_hits);
    const std::vector<std::int64_t> fifo_cold = run(m, PolicyKind::FIFO, no_hits, b_hits);
    CHECK_EQ(a_hits, 0L);
    CHECK_EQ(b_hits, 0L);
    CHECK_TRUE(lru_cold == fifo_cold);

    // And over a longer stream, where the two diverge repeatedly rather than
    // once. The check is that they DIFFER: which is better is a research
    // question the sweep answers, not a fact this suite should pin.
    std::vector<std::int64_t> loop;
    for (int pass = 0; pass < 30; ++pass)
        for (std::int64_t l : {0, 4, 8, 12, 0, 0, 16, 20, 0}) loop.push_back(l);

    long loop_lru = 0, loop_fifo = 0;
    const std::vector<std::int64_t> lru_long  = run(m, PolicyKind::LRU, loop, loop_lru);
    const std::vector<std::int64_t> fifo_long = run(m, PolicyKind::FIFO, loop, loop_fifo);
    CHECK_TRUE(!lru_long.empty());
    CHECK_TRUE(lru_long != fifo_long);

    // The one place the difference has a direction worth pinning: line 0 is
    // re-referenced on every pass, so LRU keeps it and FIFO does not. LRU
    // therefore takes strictly more hits on this stream.
    CHECK_TRUE(loop_lru > loop_fifo);

    // Neither policy ever names a slot that is not a candidate, which is the
    // one way a legal-looking policy silently corrupts an array: the insert
    // would land in another set and probe would never look there.
    SetAssociativeArray a(m, kBytes, kWays);
    std::unique_ptr<ReplacementPolicy> p = make_policy(PolicyKind::LRU, a.num_slots());
    std::vector<Candidate> out;
    bool in_set = true;
    for (std::int64_t l = 0; l < 40; ++l) {
        const LineId line{l % 16};
        if (a.probe(line) != NoSlot) { p->on_hit(a.probe(line)); continue; }
        SlotId target = a.free_slot(line);
        if (target == NoSlot) {
            a.victim_candidates(line, out);
            const SlotId chosen = p->pick_victim(out);
            bool found = false;
            for (const Candidate& c : out) found = found || c.slot == chosen;
            in_set = in_set && found;
            target = chosen;
        }
        (void)a.insert(line, target);
        p->on_fill(target);
    }
    CHECK_TRUE(in_set);
}

// ===========================================================================
// make_policy
// ===========================================================================

void test_make_policy() {
    check::group("A5: the config vocabulary, and the placeholder that is refused");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // The enumerators that are built produce policies that behave as their
    // names say. Checked by behaviour rather than by a dynamic_cast: what a
    // config file selects is a replacement rule, and the type is how that is
    // implemented.
    const std::vector<std::int64_t> stream{0, 4, 8, 12, 0, 16};
    long hits = 0;
    CHECK_EQ(run(m, PolicyKind::LRU, stream, hits)[0], std::int64_t{4});
    hits = 0;
    CHECK_EQ(run(m, PolicyKind::FIFO, stream, hits)[0], std::int64_t{0});

    // A5's exit criterion. Random stays in the enum and is refused here, which
    // is the plan's wording made literal: dropping it from the enum would make
    // `policy = random` an unknown NAME rather than a known and unbuilt one,
    // and the run would report a typo where it should report a missing feature.
    expect_message("random", thrown_by([] { (void)make_policy(PolicyKind::RANDOM, 8); }),
                   "make_policy: ",
                   {"random", "placeholder", "not implemented", "lru", "fifo"});

    // invalid_argument rather than logic_error: it is a config value refused,
    // not a function called before it was written, so it has to survive
    // -DNDEBUG and be caught where a bad configuration is caught.
    CHECK_THROWS(std::invalid_argument, make_policy(PolicyKind::RANDOM, 8));

    // There is no silent fallback. A config naming a policy this build does not
    // have must not run to completion under one nobody selected, which would
    // attribute a whole sweep's hit rates to the wrong rule.
    bool fell_back = false;
    try {
        std::unique_ptr<ReplacementPolicy> p = make_policy(PolicyKind::RANDOM, 8);
        fell_back = p != nullptr;
    } catch (const std::invalid_argument&) {
    }
    CHECK_TRUE(!fell_back);

    // The slot count is forwarded, so a policy built this way refuses a foreign
    // slot id exactly as a hand-built one does.
    std::unique_ptr<ReplacementPolicy> made = make_policy(PolicyKind::LRU, 8);
    expect_message("the count reaches the policy",
                   range_thrown_by([&] { made->on_fill(SlotId{8}); }),
                   "StampPolicy::stamp", {"outside [0, 8)"});
    expect_message("and a bad count is refused",
                   thrown_by([] { (void)make_policy(PolicyKind::FIFO, 0); }),
                   "StampPolicy: ", {"num_slots", "got 0"});
}

void test_a_policy_is_destroyed_through_the_interface() {
    check::group("A5: the base destructor is virtual, so the engine's policy is whole-destroyed");

    // make_policy hands back a unique_ptr to the INTERFACE, so every policy in
    // the run is destroyed through a ReplacementPolicy pointer. With a
    // non-virtual base destructor that destroys the base subobject only and
    // leaks the per-slot stamp vector, once per policy, over 8 to 256 cores.
    // The compiler warns and does not refuse, so this counter is what catches
    // it.
    g_destroyed = 0;
    {
        std::unique_ptr<ReplacementPolicy> p(new CountingPolicy);
        p->on_fill(SlotId{0});
        CHECK_EQ(g_destroyed, 0);
    }
    CHECK_EQ(g_destroyed, 1);

    // And the real policies arrive the same way, so the destructor that runs is
    // reached through the same pointer type.
    std::unique_ptr<ReplacementPolicy> made = make_policy(PolicyKind::FIFO, 4);
    made.reset();
    CHECK_TRUE(made == nullptr);
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// The interface is abstract and stays abstract: a ReplacementPolicy with a
// default answer for any of the four verbs is a policy that can be half
// implemented, and the half that was forgotten is silent.
static_assert(std::is_abstract<ReplacementPolicy>::value, "");
static_assert(std::is_abstract<StampPolicy>::value, "");
static_assert(std::is_base_of<ReplacementPolicy, StampPolicy>::value, "");

// `final` for B10's reason: a class deriving from LruPolicy would be
// inheriting the stamp rule in order to disagree with part of it.
static_assert(std::is_final<LruPolicy>::value, "");
static_assert(std::is_final<FifoPolicy>::value, "");
static_assert(!std::is_abstract<LruPolicy>::value, "");
static_assert(!std::is_abstract<FifoPolicy>::value, "");
static_assert(std::is_base_of<StampPolicy, LruPolicy>::value, "");
static_assert(std::is_base_of<StampPolicy, FifoPolicy>::value, "");

// pick_victim is NOT const, and the whole member-pointer type is pinned rather
// than the return type alone. That is the openness the order-independence
// criterion protects: a Random policy draws from an RNG, which is state it must
// advance, and a const signature here is exactly the interface change adding it
// would force.
static_assert(std::is_same<decltype(&ReplacementPolicy::pick_victim),
                           SlotId (ReplacementPolicy::*)(const std::vector<Candidate>&)>::value,
              "");

// The three notifications take a SlotId and return nothing. SlotId is the whole
// of what crosses the array/policy split, so a verb that grew a LineId or a set
// index would be the split leaking.
static_assert(std::is_same<decltype(&ReplacementPolicy::on_hit),
                           void (ReplacementPolicy::*)(SlotId)>::value, "");
static_assert(std::is_same<decltype(&ReplacementPolicy::on_fill),
                           void (ReplacementPolicy::*)(SlotId)>::value, "");
static_assert(std::is_same<decltype(&ReplacementPolicy::on_invalidate),
                           void (ReplacementPolicy::*)(SlotId)>::value, "");

// The constructor is explicit, so a bare int cannot become a policy at a call
// site, and it takes int32 because that is what CacheArray::num_slots reports.
static_assert(std::is_constructible<LruPolicy, std::int32_t>::value, "");
static_assert(!std::is_convertible<std::int32_t, LruPolicy>::value, "");

// The enum's width is part of the config vocabulary rather than incidental.
static_assert(std::is_same<std::underlying_type<PolicyKind>::type, std::uint8_t>::value, "");

// make_policy hands back the INTERFACE, not a concrete policy: the engine holds
// one per core and must not know which rule it got.
static_assert(std::is_same<decltype(make_policy(PolicyKind::LRU, 1)),
                           std::unique_ptr<ReplacementPolicy>>::value, "");

}  // namespace


// ===========================================================================
// Belady's MIN (plan log/2026-08-31-belady-l2-plan.md, unit W1)
// ===========================================================================

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
// LFU and RRIP (plan profiling/0907_index_policy/PLAN.md, increments P1-P4)
// ===========================================================================

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

int main() {
    test_the_constructor_refuses_a_non_positive_slot_count();
    test_every_verb_bound_checks_its_slot();
    test_pick_victim_refuses_an_empty_candidate_set();
    test_pick_victim_is_invariant_under_permutation();
    test_the_tie_break_is_the_smallest_slot_id();
    test_a_never_filled_way_is_the_preferred_victim();
    test_the_stamp_counter_only_increases();
    test_a_hit_refreshes_an_lru_stamp_and_not_a_fifo_one();
    test_lru_and_fifo_diverge_driving_the_same_array();
    test_make_policy();
    test_a_policy_is_destroyed_through_the_interface();
    test_belady_evicts_the_furthest_next_use();
    test_belady_evicts_a_line_never_used_again_first();
    test_belady_is_order_independent();
    test_belady_ignores_the_past();
    test_belady_refuses_what_the_other_policies_refuse();
    test_note_next_use_is_inert_on_lru_and_fifo();
    test_make_policy_builds_belady();
    test_lfu_counts_references_per_line();
    test_lfu_ties_go_to_the_smallest_slot_id();
    test_rrip_inserts_below_the_maximum_and_ages_to_it();
    test_rrip_invalidate_pins_a_slot_at_the_maximum();
    test_rrip_ties_go_to_the_smallest_slot_id();
    test_lfu_and_rrip_are_order_independent();
    return check::summary();
}
