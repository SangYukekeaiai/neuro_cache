// Unit A4a: the CacheArray interface, plus Candidate and InsertResult.
//
// A4a is an interface and two aggregates, so most of its exit criterion is
// about SHAPE and lives in tests/compile_fail.sh: the five verbs of plan 2.2
// are all present, invalidate is among them from the start (N8), probe is
// const, and no signature can quietly change. A test that must not compile
// cannot live in a file that must.
//
// What is left for this file is the part a compiler cannot answer, and it is
// not nothing. Following A2a's precedent (B33: the testable content of an
// interface is its contracts, exercised through conforming and deliberately
// non-conforming fakes), the questions here are whether the interface actually
// dispatches, whether it can be owned polymorphically without leaking, and
// whether the two aggregates carry what the header says they carry.
//
// SetAssociativeArray is A4b. Nothing here anticipates it: these fakes are the
// smallest things that satisfy the interface, not a cache.
#include <wcache/cache.h>

#include <cstdint>
#include <type_traits>
#include <vector>

#include "check.h"

using namespace wcache;

namespace {

// A conforming array that records what it was asked, so a check can tell a verb
// that dispatched from one that silently did nothing. It stores one line in one
// slot, which is the least state that lets insert, probe and invalidate
// disagree with each other if the dispatch is wrong.
struct RecordingArray : CacheArray {
    mutable int  probes         = 0;
    mutable int  free_slots     = 0;
    mutable int  candidate_asks = 0;
    int          inserts        = 0;
    int          invalidates    = 0;
    LineId       held           = NoLine;

    SlotId probe(LineId line) const override {
        ++probes;
        return (held != NoLine && line == held) ? SlotId{0} : NoSlot;
    }
    SlotId free_slot(LineId) const override {
        ++free_slots;
        return held == NoLine ? SlotId{0} : NoSlot;
    }
    void victim_candidates(LineId, std::vector<Candidate>& out) const override {
        ++candidate_asks;
        out.clear();
        out.push_back(Candidate{SlotId{0}, held});
    }
    InsertResult insert(LineId line, SlotId) override {
        ++inserts;
        const LineId prev = held;
        held = line;
        return InsertResult{prev != NoLine, prev};
    }
    void invalidate(SlotId) override {
        ++invalidates;
        held = NoLine;
    }
    std::int32_t num_slots() const override { return 1; }
};

// --- the interface dispatches ----------------------------------------------

void test_every_verb_dispatches() {
    check::group("A4a: every verb dispatches through the base");

    RecordingArray a;
    CacheArray& r = a;

    // Each verb is called exactly once through the base and the derived
    // override is what runs. A pure virtual that was accidentally given a body
    // on the base, or a verb reached on the wrong object, shows up as a count
    // that stayed at zero.
    std::vector<Candidate> out;
    (void)r.probe(LineId{1});
    (void)r.free_slot(LineId{1});
    r.victim_candidates(LineId{1}, out);
    (void)r.insert(LineId{1}, SlotId{0});
    r.invalidate(SlotId{0});

    CHECK_EQ(a.probes, 1);
    CHECK_EQ(a.free_slots, 1);
    CHECK_EQ(a.candidate_asks, 1);
    CHECK_EQ(a.inserts, 1);
    CHECK_EQ(a.invalidates, 1);
    CHECK_EQ((int)r.num_slots(), 1);
}

// --- the aggregates ---------------------------------------------------------

void test_candidate_carries_a_line_beside_a_slot() {
    check::group("A4a: Candidate");

    // cache.h:32-37: the line travels beside the slot rather than being looked
    // up afterwards, so a policy that has to exclude a line needs no reference
    // back to the array. Both fields, in that order.
    const Candidate occupied{SlotId{3}, LineId{99}};
    CHECK_EQ(occupied.slot.get(), std::int32_t{3});
    CHECK_EQ(occupied.line.get(), std::int64_t{99});

    // A free way reports NoLine, which is the whole reason the sentinel exists
    // rather than a second valid bit per slot.
    const Candidate free{SlotId{4}, NoLine};
    CHECK_TRUE(free.line == NoLine);
    CHECK_TRUE(free.slot != NoSlot);
}

void test_insert_result_never_self_contradicts() {
    check::group("A4a: InsertResult");

    // cache.h:44-50 argues the struct cannot self-contradict: `evicted` and
    // `evicted_line != NoLine` are the same fact. Pinned here on the interface
    // so A4b inherits the invariant rather than inventing it.
    const InsertResult none{false, NoLine};
    CHECK_TRUE(!none.evicted);
    CHECK_TRUE(none.evicted_line == NoLine);
    CHECK_EQ(none.evicted, none.evicted_line != NoLine);

    const InsertResult displaced{true, LineId{7}};
    CHECK_TRUE(displaced.evicted);
    CHECK_EQ(displaced.evicted, displaced.evicted_line != NoLine);

    // Driven through a real insert, both branches, so the invariant is checked
    // against behaviour and not only against two literals.
    RecordingArray a;
    const InsertResult first = a.insert(LineId{5}, SlotId{0});
    CHECK_TRUE(!first.evicted);
    CHECK_EQ(first.evicted, first.evicted_line != NoLine);

    const InsertResult second = a.insert(LineId{6}, SlotId{0});
    CHECK_TRUE(second.evicted);
    CHECK_TRUE(second.evicted_line == LineId{5});
    CHECK_EQ(second.evicted, second.evicted_line != NoLine);
}

// --- polymorphic ownership --------------------------------------------------

int destructor_runs = 0;

// No `override` on the destructor, and that omission is deliberate rather than
// sloppy. Writing `~CountsItsDestructor() override` would make this fake fail
// to COMPILE the moment the base destructor lost its `virtual`, which sounds
// stronger and is actually weaker: it would move the kill into this test file's
// own spelling, and the run-time check below would never run at all. The
// property that matters is not "the fake said override", it is "the derived
// destructor actually ran", and A4b's real array will be deleted through a
// CacheArray* with no `override` standing guard over the call site.
//
// Verified by meta-verification rather than reasoned about: with `override`
// here, weakening the check below to a tautology still killed the paired
// mutation, which is the definition of a check that is not load-bearing.
struct CountsItsDestructor : RecordingArray {
    ~CountsItsDestructor() { ++destructor_runs; }
};

void test_destruction_through_the_base() {
    check::group("A4a: the base destructor is virtual");

    // The engine owns levels through CacheArray, so an array is deleted through
    // a base pointer. Without `virtual ~CacheArray()` that is undefined
    // behaviour and, in practice, a derived destructor that never runs: every
    // array's storage leaks for the whole sweep and nothing says so.
    //
    // This is the one property of A4a that no compile_fail.sh case can reach:
    // dropping `virtual` still compiles, and g++ reduces it to a
    // -Wdelete-non-virtual-dtor warning, which this build does not turn into an
    // error.
    //
    // Covered twice on purpose, and the redundancy is measured rather than
    // assumed. `static_assert(has_virtual_destructor)` below is the cheaper
    // check and catches it at compile time; this one catches the thing that
    // actually matters, which is the derived destructor running. Meta-verified:
    // with BOTH disabled the paired mutation SURVIVES, and restoring this check
    // alone kills it, so this check is load-bearing on its own rather than
    // riding on the static_assert.
    destructor_runs = 0;
    {
        CacheArray* p = new CountsItsDestructor();
        delete p;
    }
    CHECK_EQ(destructor_runs, 1);
}

// --- a deliberately non-conforming fake -------------------------------------
//
// A2a's thirteen fakes exist so the suite can be shown to catch a mapper that
// does not conform. The same idea, at the size A4a warrants: one fake that
// breaks the one behavioural contract this interface states outright.

// cache.h:88-97: victim_candidates REPLACES the contents of `out`, it does not
// append. An appending array lets a caller that forgot to clear pick a victim
// from a previous fill in a DIFFERENT set, and the line is then stored where
// probe can never look for it: no crash, a hit rate quietly below the truth for
// the whole run. This fake is what proves the check below can see it.
struct AppendsItsCandidates : RecordingArray {
    void victim_candidates(LineId, std::vector<Candidate>& out) const override {
        out.push_back(Candidate{SlotId{0}, held});
    }
};

// The contract, written over the abstract base so A4b's real array inherits it
// by being passed here rather than by copying the check.
bool candidates_replace_rather_than_append(const CacheArray& r) {
    std::vector<Candidate> out;
    r.victim_candidates(LineId{1}, out);
    const std::size_t first = out.size();

    // Called again on the same buffer without clearing, which is exactly the
    // caller mistake the contract exists to survive.
    r.victim_candidates(LineId{1}, out);
    if (out.size() != first) return false;

    // And with junk already in it, which is the stronger half: a `clear()` that
    // was dropped is invisible when the buffer starts empty.
    out.assign(7, Candidate{NoSlot, NoLine});
    r.victim_candidates(LineId{1}, out);
    return out.size() == first;
}

void test_the_replace_contract_and_that_we_can_catch_it() {
    check::group("A4a: victim_candidates replaces, and the check can catch a fake");

    const RecordingArray good;
    CHECK_TRUE(candidates_replace_rather_than_append(good));

    // The negative half. If this ever reports true, the check above is
    // decoration and A4b would inherit a contract nothing enforces.
    const AppendsItsCandidates bad;
    CHECK_TRUE(!candidates_replace_rather_than_append(bad));
}

// --- compile-time shape -----------------------------------------------------

// The interface is abstract and stays abstract. A concrete CacheArray would
// mean a level could be built with no storage behind it.
static_assert(std::is_abstract<CacheArray>::value, "");
static_assert(std::has_virtual_destructor<CacheArray>::value, "");
static_assert(!std::is_abstract<RecordingArray>::value, "");

// The two aggregates stay aggregates: they are returned and copied per access,
// and a constructor on either would make them something to build rather than
// something to read.
static_assert(std::is_aggregate<Candidate>::value, "");
static_assert(std::is_aggregate<InsertResult>::value, "");
static_assert(std::is_trivially_copyable<Candidate>::value, "");
static_assert(std::is_trivially_copyable<InsertResult>::value, "");

// Candidate is a slot and a line, in that order, and no bigger than the two.
static_assert(std::is_same<decltype(Candidate::slot), SlotId>::value, "");
static_assert(std::is_same<decltype(Candidate::line), LineId>::value, "");
static_assert(std::is_same<decltype(InsertResult::evicted_line), LineId>::value, "");

// num_slots is int32, matching SlotId's representation: a slot count a SlotId
// cannot name is a geometry whose upper slots are unreachable.
static_assert(std::is_same<decltype(std::declval<const CacheArray&>().num_slots()),
                           std::int32_t>::value, "");
// probe answers with a slot, not a line, and is const.
static_assert(std::is_same<decltype(std::declval<const CacheArray&>().probe(NoLine)),
                           SlotId>::value, "");

}  // namespace

int main() {
    test_every_verb_dispatches();
    test_candidate_carries_a_line_beside_a_slot();
    test_insert_result_never_self_contradicts();
    test_destruction_through_the_base();
    test_the_replace_contract_and_that_we_can_catch_it();
    return check::summary();
}
