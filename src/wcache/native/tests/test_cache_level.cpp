// Plan unit C1: `CacheLevel` = array + policy + port + MSHR file, and `triage()`
// per level. Exit criterion, Part 7 line 1352: "the 3.4 triage table exercised
// branch by branch".
//
// NAMING: "C1".."C5" here are the PLAN's Phase C units; PROGRESS.md's decisions
// are B1-B126 and are named as decisions when cited.
//
// The 3.4 table has five branches per level and 4.6 adds four drops, so nine
// outcomes exist and each has a test named after it below. The branches are also
// ORDERED -- array, then own-level MSHR, then allocate -- and that order is Part
// 0's surviving verdict, so a state satisfying two branches at once is
// constructed to check which one wins.
//
// What this file does NOT test is anything that crosses a level: `triage` never
// schedules, never touches a core and never reaches the other level, which is
// what makes C1 testable without an engine. The scheduling half of the same
// branches is C2's and lives in test_engine.cpp.
#include <wcache/cache_level.h>

#include <wcache/mshr.h>
#include <wcache/next_use.h>
#include <wcache/types.h>

#include <cstdint>
#include <deque>
#include <functional>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;
using fx::LinearMapper;

namespace {

// Requests must outlive their membership of a wait index (P5, mshr.h), so they
// live in a deque that never moves what it already holds.
class Arena {
public:
    Request& demand(std::int32_t core, std::int64_t line, std::int32_t burst = 0) {
        rs_.push_back(Request{CoreId{core}, LineId{line}, BurstIndex{burst}});
        return rs_.back();
    }
    Request& prefetch(std::int32_t core, std::int64_t line, std::int32_t burst = 0) {
        rs_.push_back(Request{CoreId{core}, LineId{line}, BurstIndex{burst}, false});
        return rs_.back();
    }

private:
    std::deque<Request> rs_;
};

std::string thrown_by(const std::function<void()>& fn) {
    try {
        fn();
    } catch (const std::logic_error& e) {
        return e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong tier] ") + e.what();
    }
    return "[no exception thrown]";
}

// ===========================================================================
// The nine outcomes, branch by branch
// ===========================================================================

void test_hit() {
    check::group("C1: 3.4 branch 1, the array -- HIT");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2), counter);
    Arena arena;
    std::vector<Request*> granted;

    l1.install(LineId{5});
    Request& r = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(r, granted) == TriageOutcome::Hit);
    // Terminal and holding nothing: no entry was allocated, the request did not
    // become a target, and it is not on any index.
    CHECK_EQ(l1.mshrs().live(), 0);
    CHECK_TRUE(!r.on_wait_index);
    CHECK_TRUE(r.mshr1 == nullptr);
    CHECK_TRUE(r.level == Level::L1);
    CHECK_EQ(r.refusal, NoRefusal);

    // 3.4 calls `policy.on_hit` on this branch and 2.2 says `probe` is not an
    // access, so the hit is the ONLY thing that can move recency. Checked
    // behaviourally rather than through a spy: in a 2-way set, a hit on the
    // older line makes the OTHER line the victim of the next fill.
    LinearMapper m2(64);
    RefusalCounter c2;
    CacheLevel one_set(Level::L1, m2, fx::level(1, 2, 4, 2), c2);
    one_set.install(LineId{0});  // oldest
    one_set.install(LineId{1});
    Request& hot = arena.demand(0, 0);
    CHECK_TRUE(one_set.triage(hot, granted) == TriageOutcome::Hit);  // on_hit(line 0)
    const InsertResult res = one_set.install(LineId{2});
    CHECK_TRUE(res.evicted);
    CHECK_EQ(res.evicted_line, LineId{1});  // not 0: the hit moved it
}

void test_merged() {
    check::group("C1: 3.4 branch 2a, a matching entry with room -- MERGED");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2), counter);
    Arena arena;
    std::vector<Request*> granted;

    Request& primary = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(primary, granted) == TriageOutcome::Forwarded);

    Request& second = arena.demand(0, 5, 1);
    CHECK_TRUE(l1.triage(second, granted) == TriageOutcome::Merged);
    // D3: it subscribes and computes nothing, and it costs no downstream
    // traffic, which is the whole reason the MSHR file is consulted before the
    // next level.
    CHECK_EQ(l1.mshrs().live(), 1);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->targets), 2);
    // MERGED holds a committed subentry and is not a waiter: 3.7's first
    // collapse, made unrepresentable rather than merely avoided.
    CHECK_TRUE(!second.on_wait_index);
    CHECK_EQ(second.refusal, NoRefusal);
    CHECK_TRUE(second.mshr1 == nullptr);
}

void test_blocked_targets() {
    check::group("C1: 3.4 branch 2b, targets full -- BLOCKED_TARGETS");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 1), counter);  // tgts = 1
    Arena arena;
    std::vector<Request*> granted;

    Request& primary = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(primary, granted) == TriageOutcome::Forwarded);

    Request& blocked = arena.demand(1, 5);
    CHECK_TRUE(l1.triage(blocked, granted) == TriageOutcome::BlockedTargets);
    // D5: it waits on THIS entry and on nothing else, which is what stops an
    // unrelated retire from waking it into the same refusal forever (3.7's
    // livelock).
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->line_wait), 1);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->targets), 1);
    CHECK_TRUE(blocked.on_wait_index);
    CHECK_EQ(blocked.refusal, RefusalOrder{0});
    CHECK_TRUE(blocked.reason == WaitReason::Line);
    // 3.8: the stamp is write-once, so a second refusal does not re-stamp it.
    // Reached here by re-triaging the same request after clearing the bit the
    // way `retire` does.
    blocked.on_wait_index = false;
    l1.mshrs().find(LineId{5})->line_wait.clear();
    CHECK_TRUE(l1.triage(blocked, granted) == TriageOutcome::BlockedTargets);
    CHECK_EQ(blocked.refusal, RefusalOrder{0});
    CHECK_EQ(counter.issued(), 1);
}

void test_blocked_pool() {
    check::group("C1: 3.4 branch 3, no free entry -- BLOCKED_POOL");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 1, 2), counter);  // mshrs = 1
    Arena arena;
    std::vector<Request*> granted;

    Request& first = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(first, granted) == TriageOutcome::Forwarded);

    Request& blocked = arena.demand(0, 6);
    CHECK_TRUE(l1.triage(blocked, granted) == TriageOutcome::BlockedPool);
    // D2: it registers and predicts nothing. No entry was allocated for it and
    // no completion time was computed anywhere.
    CHECK_EQ(l1.mshrs().live(), 1);
    CHECK_EQ(l1.mshrs().slot_wait_depth(), 1);
    CHECK_TRUE(blocked.on_wait_index);
    CHECK_TRUE(blocked.reason == WaitReason::Slot);
    CHECK_TRUE(blocked.mshr1 == nullptr);
}

void test_forwarded_at_l1_sets_the_re_entry_level() {
    check::group("C1: 3.4 branch 4, a primary miss -- FORWARDED");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2), counter);
    Arena arena;
    std::vector<Request*> granted;

    Request& r = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(r, granted) == TriageOutcome::Forwarded);
    CHECK_EQ(l1.mshrs().live(), 1);
    // 3.5's re-entry rule, written where the request takes the entry. Getting
    // this wrong makes a woken request re-triage at the L1, find its OWN entry,
    // merge into itself and wait for a fill nobody will request.
    CHECK_TRUE(r.level == Level::L2);
    CHECK_TRUE(r.mshr1 == l1.mshrs().find(LineId{5}));
    // The primary occupies the first target slot (4.1's bound is exact because
    // of it), so the fill satisfies it through the same loop as every merge.
    CHECK_EQ(check::ssize(r.mshr1->targets), 1);
    CHECK_TRUE(r.mshr1->targets[0] == &r);
    CHECK_TRUE(r.mshr1->demand);
}

void test_forwarded_at_l2_leaves_the_level_alone() {
    check::group("C1: FORWARDED at the L2 does not re-point mshr1");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2), counter);
    CacheLevel l2(Level::L2, map, fx::level(8, 2, 4, 2), counter);
    Arena arena;
    std::vector<Request*> granted;

    Request& r = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(r, granted) == TriageOutcome::Forwarded);
    Mshr* e1 = r.mshr1;

    CHECK_TRUE(l2.triage(r, granted) == TriageOutcome::Forwarded);
    // The L1 entry is still held, and it is held ACROSS the whole downstream
    // round trip: 4.1's entire argument that the L2's wait sets are views over
    // structures that already exist rather than storage.
    CHECK_TRUE(r.mshr1 == e1);
    CHECK_TRUE(r.level == Level::L2);
    CHECK_EQ(l2.mshrs().live(), 1);
    CHECK_EQ(l1.mshrs().live(), 1);
}

// --- 4.6's four drops -------------------------------------------------------

void test_dropped_array_hit_does_not_touch_recency() {
    check::group("C1: 4.6 drop 1, an array hit -- DroppedArrayHit");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel one_set(Level::L1, map, fx::level(1, 2, 4, 2), counter);
    Arena arena;
    std::vector<Request*> granted;

    one_set.install(LineId{0});
    one_set.install(LineId{1});

    Request& pf = arena.prefetch(0, 0);
    CHECK_TRUE(one_set.triage(pf, granted) == TriageOutcome::DroppedArrayHit);
    CHECK_TRUE(is_dropped(TriageOutcome::DroppedArrayHit));
    CHECK_EQ(one_set.mshrs().live(), 0);

    // "A prefetch is not a use" (4.6, I15). Line 0 is still the older line, so
    // the next fill evicts IT and not line 1. The demand version of this fixture
    // in test_hit() evicts the other way, which is what makes this a check on
    // `on_hit` not firing rather than on the outcome name.
    const InsertResult res = one_set.install(LineId{2});
    CHECK_TRUE(res.evicted);
    CHECK_EQ(res.evicted_line, LineId{0});
}

void test_dropped_entry() {
    check::group("C1: 4.6 drop 2, a matching entry -- DroppedEntry");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 1), counter);  // tgts = 1
    Arena arena;
    std::vector<Request*> granted;

    Request& primary = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(primary, granted) == TriageOutcome::Forwarded);

    // The line is already coming, so nothing is waiting for this copy. Dropped
    // BEFORE the target bound is consulted, which is why DroppedEntry subsumes
    // 4.6's "targets full" row: a prefetch never reaches that bound.
    Request& pf = arena.prefetch(0, 5);
    CHECK_TRUE(l1.triage(pf, granted) == TriageOutcome::DroppedEntry);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->targets), 1);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->line_wait), 0);
    CHECK_TRUE(!pf.on_wait_index);

    // And with room in the target list it is STILL dropped, which is the branch
    // order: a prefetch does not merge either, because nothing is waiting for
    // this copy.
    LinearMapper m2(64);
    RefusalCounter c2;
    CacheLevel roomy(Level::L1, m2, fx::level(4, 2, 4, 4), c2);
    Request& p2 = arena.demand(0, 7);
    CHECK_TRUE(roomy.triage(p2, granted) == TriageOutcome::Forwarded);
    Request& pf2 = arena.prefetch(1, 7);
    CHECK_TRUE(roomy.triage(pf2, granted) == TriageOutcome::DroppedEntry);
    CHECK_EQ(check::ssize(roomy.mshrs().find(LineId{7})->targets), 1);
}

void test_dropped_no_slot_and_dropped_reserve_are_distinguishable() {
    check::group("C1: 4.6 drops 3 and 4 -- DroppedNoSlot vs DroppedReserve");

    Arena arena;
    std::vector<Request*> granted;

    // A file that is completely full: no free entry at all.
    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel full(Level::L1, map, fx::level(8, 2, 1, 2, 0), counter);  // mshrs 1, reserve 0
    Request& d = arena.demand(0, 5);
    CHECK_TRUE(full.triage(d, granted) == TriageOutcome::Forwarded);
    Request& pf = arena.prefetch(0, 6);
    CHECK_TRUE(full.triage(pf, granted) == TriageOutcome::DroppedNoSlot);

    // Free entries remain, but they are the demand reserve a prefetch may never
    // take (4.6, decision B12). Part 8 asks for the drops broken out by reason
    // and this is the only place the two are still distinguishable.
    LinearMapper m2(64);
    RefusalCounter c2;
    CacheLevel reserved(Level::L1, m2, fx::level(8, 2, 2, 2, 1), c2);  // mshrs 2, reserve 1
    Request& held = arena.demand(0, 8);
    CHECK_TRUE(reserved.triage(held, granted) == TriageOutcome::Forwarded);
    CHECK_EQ(reserved.mshrs().live(), 1);  // one free entry left, and it is the reserve
    Request& pf2 = arena.prefetch(0, 9);
    CHECK_TRUE(reserved.triage(pf2, granted) == TriageOutcome::DroppedReserve);
    // A demand request in the same state is admitted: prefetching can delay
    // demand but never starve it, which is what the reserve buys (decision B12).
    Request& d2 = arena.demand(0, 9);
    CHECK_TRUE(reserved.triage(d2, granted) == TriageOutcome::Forwarded);
    // And at reserve == capacity the budget is zero rather than a special case.
    LinearMapper m3(64);
    RefusalCounter c3;
    CacheLevel zero_budget(Level::L1, m3, fx::level(8, 2, 2, 2, 2), c3);
    Request& pf3 = arena.prefetch(0, 11);
    CHECK_TRUE(zero_budget.triage(pf3, granted) == TriageOutcome::DroppedReserve);
}

void test_is_dropped_partitions_the_outcomes() {
    check::group("C1: `is_dropped` names exactly 4.6's four");

    CHECK_TRUE(!is_dropped(TriageOutcome::Hit));
    CHECK_TRUE(!is_dropped(TriageOutcome::Merged));
    CHECK_TRUE(!is_dropped(TriageOutcome::BlockedTargets));
    CHECK_TRUE(!is_dropped(TriageOutcome::BlockedPool));
    CHECK_TRUE(!is_dropped(TriageOutcome::Forwarded));
    CHECK_TRUE(is_dropped(TriageOutcome::DroppedArrayHit));
    CHECK_TRUE(is_dropped(TriageOutcome::DroppedEntry));
    CHECK_TRUE(is_dropped(TriageOutcome::DroppedNoSlot));
    CHECK_TRUE(is_dropped(TriageOutcome::DroppedReserve));
}

// ===========================================================================
// The branch ORDER, which is Part 0's surviving verdict
// ===========================================================================

void test_the_array_is_consulted_before_the_mshr_file() {
    check::group("C1: array before own-level MSHR before allocate");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 4), counter);
    Arena arena;
    std::vector<Request*> granted;

    // A state satisfying two branches at once: an entry for line 5 is live AND
    // line 5 is resident. Only the order decides which branch wins, and 3.4 puts
    // the array first, so this is a HIT and not a MERGED. Reachable in a run
    // through D4's "a queued miss became a hit" (V5).
    Request& primary = arena.demand(0, 5);
    CHECK_TRUE(l1.triage(primary, granted) == TriageOutcome::Forwarded);
    l1.install(LineId{5});

    Request& later = arena.demand(1, 5);
    CHECK_TRUE(l1.triage(later, granted) == TriageOutcome::Hit);
    CHECK_EQ(check::ssize(l1.mshrs().find(LineId{5})->targets), 1);  // it did not merge

    // And the entry is consulted before allocation: with the file at capacity a
    // matching entry still merges, so a secondary miss costs no credit.
    LinearMapper m2(64);
    RefusalCounter c2;
    CacheLevel one(Level::L1, m2, fx::level(4, 2, 1, 4), c2);  // mshrs = 1
    Request& p = arena.demand(0, 8);
    CHECK_TRUE(one.triage(p, granted) == TriageOutcome::Forwarded);
    Request& s = arena.demand(1, 8);
    CHECK_TRUE(one.triage(s, granted) == TriageOutcome::Merged);
    CHECK_EQ(one.mshrs().slot_wait_depth(), 0);
}

// ===========================================================================
// The reservation, and the grant loop re-run (3.8, decision B120)
// ===========================================================================

void test_a_grantee_that_does_not_need_its_slot_releases_it() {
    check::group("C1: a released reservation immediately grants the next waiter");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(8, 2, 1, 4), counter);  // mshrs = 1
    Arena arena;
    std::vector<Request*> granted;

    // One entry live, two requests refused for want of a slot.
    Request& live = arena.demand(0, 1);
    CHECK_TRUE(l1.triage(live, granted) == TriageOutcome::Forwarded);
    Request& w1 = arena.demand(1, 2);
    Request& w2 = arena.demand(2, 3);
    CHECK_TRUE(l1.triage(w1, granted) == TriageOutcome::BlockedPool);
    CHECK_TRUE(l1.triage(w2, granted) == TriageOutcome::BlockedPool);
    CHECK_EQ(w1.refusal, RefusalOrder{0});
    CHECK_EQ(w2.refusal, RefusalOrder{1});

    // The live entry retires: one credit frees, so exactly one grant.
    RetireResult out;
    l1.mshrs().retire(*live.mshr1, out);
    live.mshr1 = nullptr;
    CHECK_EQ(check::ssize(out.wake), 1);
    CHECK_TRUE(out.wake[0] == &w1);  // oldest first
    CHECK_TRUE(w1.reserved);
    CHECK_TRUE(!w1.on_wait_index);
    CHECK_EQ(l1.mshrs().slot_wait_depth(), 1);

    // w1 re-triages and turns out not to need its slot, because the line became
    // resident while it slept (D4, V5). 3.8: the released reservation
    // immediately grants the next waiter, and `granted` is how the engine is
    // told, because injecting reserves a port and a level has no queue.
    l1.install(LineId{2});
    CHECK_TRUE(l1.triage(w1, granted) == TriageOutcome::Hit);
    CHECK_TRUE(!w1.reserved);
    CHECK_EQ(check::ssize(granted), 1);
    CHECK_TRUE(granted[0] == &w2);
    CHECK_TRUE(w2.reserved);
    CHECK_EQ(l1.mshrs().slot_wait_depth(), 0);

    // `granted` is REPLACED and not appended to, so a caller may reuse one
    // buffer across triages. A triage that grants nothing must leave it empty,
    // or the engine reinjects the previous call's grantees a second time. The
    // fresh request is refused here because w2's reservation IS the file's last
    // credit, which is the reservation system working: a grant that has not been
    // spent still counts against the capacity (I4).
    Request& fresh = arena.demand(3, 20);
    CHECK_TRUE(l1.triage(fresh, granted) == TriageOutcome::BlockedPool);
    CHECK_EQ(check::ssize(granted), 0);
}

void test_a_grantee_that_merges_also_releases() {
    check::group("C1: a grantee that re-triages into a MERGE releases too");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(8, 2, 3, 4), counter);  // mshrs = 3
    Arena arena;
    std::vector<Request*> granted;

    // 3.8's counterexample, played forward: a slot waiter outlives the
    // allocation of an entry it later merges onto. `w` is refused for want of
    // any entry while line 2 has none, and by the time it is granted and
    // re-triages, someone else has allocated one.
    Request& a = arena.demand(0, 1);
    Request& b = arena.demand(1, 3);
    Request& c = arena.demand(2, 4);
    CHECK_TRUE(l1.triage(a, granted) == TriageOutcome::Forwarded);
    CHECK_TRUE(l1.triage(b, granted) == TriageOutcome::Forwarded);
    CHECK_TRUE(l1.triage(c, granted) == TriageOutcome::Forwarded);
    Request& w = arena.demand(3, 2);   // wants line 2, file full, no entry for it
    CHECK_TRUE(l1.triage(w, granted) == TriageOutcome::BlockedPool);

    RetireResult out;
    l1.mshrs().retire(*a.mshr1, out);
    a.mshr1 = nullptr;
    CHECK_EQ(check::ssize(out.wake), 1);
    CHECK_TRUE(out.wake[0] == &w);
    CHECK_TRUE(w.reserved);

    // A second retire frees the credit that lets line 2's entry appear, while
    // `w` is still asleep holding its reservation.
    l1.mshrs().retire(*b.mshr1, out);
    b.mshr1 = nullptr;
    CHECK_EQ(check::ssize(out.wake), 0);
    Request& other = arena.demand(4, 2);
    CHECK_TRUE(l1.triage(other, granted) == TriageOutcome::Forwarded);

    // It wakes, finds line 2's entry, and merges: it never needed the credit.
    CHECK_TRUE(l1.triage(w, granted) == TriageOutcome::Merged);
    CHECK_TRUE(!w.reserved);
    CHECK_EQ(l1.mshrs().reserved(), 0);
    CHECK_EQ(check::ssize(granted), 0);  // nobody left to grant it to
}

// ===========================================================================
// I5, refused where the engine can break it
// ===========================================================================

void test_a_request_already_waiting_is_refused() {
    check::group("C1: I5, a request may be on at most one wait index");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(8, 2, 1, 1), counter);
    CacheLevel l2(Level::L2, map, fx::level(8, 2, 1, 1), counter);
    Arena arena;
    std::vector<Request*> granted;

    Request& live = arena.demand(0, 1);
    CHECK_TRUE(l1.triage(live, granted) == TriageOutcome::Forwarded);
    Request& w = arena.demand(1, 2);
    CHECK_TRUE(l1.triage(w, granted) == TriageOutcome::BlockedPool);
    CHECK_TRUE(w.on_wait_index);

    // A second push, at either level, is a caller error. Without the refusal the
    // request is woken by two different releases and the second wake re-probes a
    // request that was already satisfied, decrementing a burst's line count
    // twice at the L1.
    const std::string at_l1 = thrown_by([&] { (void)l1.triage(w, granted); });
    CHECK_TRUE(at_l1.find("already on a wait index") != std::string::npos);
    CHECK_TRUE(at_l1.find("(I5)") != std::string::npos);

    Request& l2live = arena.demand(0, 3);
    CHECK_TRUE(l2.triage(l2live, granted) == TriageOutcome::Forwarded);
    const std::string at_l2 = thrown_by([&] { (void)l2.triage(w, granted); });
    CHECK_TRUE(at_l2.find("already on a wait index") != std::string::npos);

    // The refusal is triage's and NOT MshrFile's, which is decision B3's shipped
    // contract left intact: the file still allows a fixture to build the
    // cross-level state test_mshr.cpp:266-279 needs and a run cannot reach.
    Request& x = arena.demand(4, 40);
    l1.mshrs().push_slot_wait(x);
    Mshr* e = l2.mshrs().find(LineId{3});
    CHECK_TRUE(e != nullptr);
    l2.mshrs().push_line_wait(*e, x);  // must NOT throw: B3's contract is unchanged
    CHECK_TRUE(x.on_wait_index);
    CHECK_EQ(x.refusal, RefusalOrder{1});
}

// ===========================================================================
// install (3.4), and U17
// ===========================================================================

void test_install_prefers_a_free_way_and_reports_the_victim() {
    check::group("C1: install -- free way first, only then the policy (D6)");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(1, 2, 4, 2), counter);

    const InsertResult a = l1.install(LineId{0});
    CHECK_TRUE(!a.evicted);
    const InsertResult b = l1.install(LineId{1});
    CHECK_TRUE(!b.evicted);
    // Both ways were free first, so nothing was evicted while a way sat empty.
    const InsertResult c = l1.install(LineId{2});
    CHECK_TRUE(c.evicted);
    CHECK_EQ(c.evicted_line, LineId{0});
    // The caller needs the victim, because the back-invalidation of 4.4 is the
    // engine's and not a level's.
    CHECK_TRUE(l1.array().probe(LineId{0}) == NoSlot);
    CHECK_TRUE(l1.array().probe(LineId{2}) != NoSlot);
}

void test_install_refuses_a_line_that_is_already_resident() {
    check::group("C1: install refuses a duplicate line (I1)");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel l1(Level::L1, map, fx::level(4, 2, 4, 2), counter);
    l1.install(LineId{3});
    const std::string msg = thrown_by([&] { (void)l1.install(LineId{3}); });
    CHECK_TRUE(msg.find("already resident") != std::string::npos);
    CHECK_TRUE(msg.find("(I1)") != std::string::npos);
}

void test_a_freshly_filled_slot_is_not_the_next_victim() {
    check::group("C1: U17 -- `on_evict` is not called after `on_fill`");

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel one_set(Level::L1, map, fx::level(1, 2, 4, 2), counter);

    // 3.4 line 619 calls `policy.on_evict(slot)` after `on_fill(slot)` on the
    // SAME slot, which for any stamp policy clobbers the stamp the fill just
    // wrote. This is that defect as a behaviour rather than as a comment: with
    // the call made, the slot filled at step 3 would carry the "never stamped"
    // sentinel and would be picked again at step 4, so line 2 would evict
    // ITSELF and line 1 would survive forever.
    one_set.install(LineId{0});
    one_set.install(LineId{1});
    const InsertResult third = one_set.install(LineId{2});  // evicts 0, fills its way
    CHECK_EQ(third.evicted_line, LineId{0});
    const InsertResult fourth = one_set.install(LineId{3});
    CHECK_EQ(fourth.evicted_line, LineId{1});  // NOT 2
    CHECK_TRUE(one_set.array().probe(LineId{2}) != NoSlot);
}

// ===========================================================================
// bank_of (2.3, Q2)
// ===========================================================================

void test_bank_of() {
    check::group("C1: bank_of, low bits by default and high bits as a knob");

    LinearMapper map(64);
    RefusalCounter counter;

    // 2.3's trap, avoided: at `banks = 1` the two settings are indistinguishable
    // by construction, so a fixture asserting bank behaviour sets 2 or more or
    // it passes vacuously.
    LevelParams single = fx::level(8, 1, 4, 2);
    CacheLevel one_bank(Level::L1, map, single, counter);
    CHECK_EQ(one_bank.banks(), 1);
    CHECK_EQ(one_bank.bank_of(LineId{0}), 0);
    CHECK_EQ(one_bank.bank_of(LineId{7}), 0);

    LevelParams low = fx::level(8, 1, 4, 2);
    low.banks       = 4;
    CacheLevel spread(Level::L2, map, low, counter);
    CHECK_EQ(spread.num_sets(), 8);
    // set index == line % 8 under LinearMapper, and the low bits of it are the
    // bank: consecutive lines land in different banks.
    CHECK_EQ(spread.bank_of(LineId{0}), 0);
    CHECK_EQ(spread.bank_of(LineId{1}), 1);
    CHECK_EQ(spread.bank_of(LineId{2}), 2);
    CHECK_EQ(spread.bank_of(LineId{5}), 1);

    LevelParams high     = fx::level(8, 1, 4, 2);
    high.banks           = 4;
    high.bank_high_bits  = true;
    CacheLevel packed(Level::L2, map, high, counter);
    // Two sets per bank, so a contiguous run stays inside one bank: the opposite
    // conflict behaviour, which is why it stayed a knob (Q2).
    CHECK_EQ(packed.bank_of(LineId{0}), 0);
    CHECK_EQ(packed.bank_of(LineId{1}), 0);
    CHECK_EQ(packed.bank_of(LineId{2}), 1);
    CHECK_EQ(packed.bank_of(LineId{7}), 3);
    CHECK_TRUE(spread.bank_of(LineId{1}) != packed.bank_of(LineId{1}));

    // More banks than sets: `sets_per_bank` would be 0, so it is clamped to 1
    // and the bank becomes the set index itself. Every answer is still inside
    // [0, banks), which is what the clamp is for, but note that this is NOT what
    // cache_level.cpp's comment beside the clamp claims ("every set lands in
    // bank 0"): sets 0 and 1 land in banks 0 and 1. Pinned as the behaviour the
    // code has, with the comment reported as wrong rather than the code changed.
    LevelParams many = fx::level(2, 1, 4, 2);
    many.banks       = 8;
    many.bank_high_bits = true;
    CacheLevel clamped(Level::L2, map, many, counter);
    CHECK_EQ(clamped.bank_of(LineId{0}), 0);
    CHECK_EQ(clamped.bank_of(LineId{1}), 1);
    CHECK_TRUE(clamped.bank_of(LineId{1}) < clamped.banks());
}

// ===========================================================================
// The constructor's four refusals
// ===========================================================================

void test_the_constructor_refuses_what_its_parts_refuse() {
    check::group("C1: the constructor's refusals, in the order they run");

    LinearMapper map(64);
    RefusalCounter counter;

    // A geometry that is not a whole number of lines: the array's.
    LevelParams bad_geometry     = fx::level(4, 3, 4, 2);
    bad_geometry.cache_size_bytes = 7;
    CHECK_THROWS(std::invalid_argument,
                 CacheLevel(Level::L1, map, bad_geometry, counter));

    // A negative ii: the port's.
    LevelParams bad_ii = fx::level(4, 2, 4, 2);
    bad_ii.ii          = SimTime{-1};
    CHECK_THROWS(std::invalid_argument, CacheLevel(Level::L1, map, bad_ii, counter));

    // A demand_reserve above the capacity: the MSHR file's.
    LevelParams bad_reserve = fx::level(4, 2, 2, 2, 3);
    CHECK_THROWS(std::invalid_argument, CacheLevel(Level::L1, map, bad_reserve, counter));

    // Random is a placeholder, rejected rather than silently falling back to LRU
    // (A5, Q5, V29).
    LevelParams random = fx::level(4, 2, 4, 2);
    random.policy      = PolicyKind::RANDOM;
    CHECK_THROWS(std::invalid_argument, CacheLevel(Level::L1, map, random, counter));

    // And banks: a level with no port cannot accept anything.
    LevelParams no_banks = fx::level(4, 2, 4, 2);
    no_banks.banks       = 0;
    CHECK_THROWS(std::invalid_argument, CacheLevel(Level::L1, map, no_banks, counter));
}

// ===========================================================================
// Belady's oracle at the level (plan 0831-belady unit W3, extended to the L1)
// ===========================================================================
//
// The three sites in cache_level.cpp that read `next_use_` had no direct test:
// they were covered only through wcache_run's L2 arm. Making the L1 an oracle
// too is what makes them worth pinning here, because the L1 is PRIVATE and the
// property that matters is per-level independence.
//
// Everything below observes the oracle through the VICTIM, which is the only
// thing an attached oracle can change. A spy on the policy would test the spy.

// One set of two ways under BeladyPolicy, so a third fill has to choose between
// the two lines and the choice is the oracle's answer.
LevelParams belady_level() {
    LevelParams p = fx::level(1, 2, 4, 2);
    p.policy      = PolicyKind::BELADY;
    return p;
}

// A demand probe followed by the fill it missed on, which is the pair the
// oracle is read across: the probe consumes the line's occurrence and leaves the
// answer behind, and the fill picks it up.
InsertResult probe_then_install(CacheLevel& lvl, Arena& arena, std::int64_t line) {
    std::vector<Request*> granted;
    Request& r = arena.demand(0, line);
    lvl.triage(r, granted);
    return lvl.install(LineId{line});
}

void test_two_levels_read_their_own_oracles() {
    check::group("W3: each level's victim comes from ITS oracle, not a shared one");

    // Two different futures for the same two lines. Under A, line 10 is
    // referenced again and line 20 never is; under B it is the other way round.
    // MIN evicts the line whose next use is furthest away, so a level that read
    // the wrong oracle evicts the wrong line and nothing else changes.
    NextUseOracle a(std::vector<std::int64_t>{10, 10});
    NextUseOracle b(std::vector<std::int64_t>{20, 20});

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel la(Level::L1, map, belady_level(), counter);
    CacheLevel lb(Level::L1, map, belady_level(), counter);
    la.attach_next_use(&a);
    lb.attach_next_use(&b);

    Arena arena;
    for (CacheLevel* lvl : {&la, &lb}) {
        probe_then_install(*lvl, arena, 10);
        probe_then_install(*lvl, arena, 20);
    }
    const InsertResult ra = probe_then_install(la, arena, 30);
    const InsertResult rb = probe_then_install(lb, arena, 30);

    CHECK_TRUE(ra.evicted);
    CHECK_TRUE(rb.evicted);
    CHECK_EQ(ra.evicted_line, LineId{20});  // A knows only line 10's future
    CHECK_EQ(rb.evicted_line, LineId{10});  // B knows only line 20's

    // This is the per-core L1 property in miniature: one oracle over the merged
    // stream would give both levels the same answer, and the two lines above
    // would come out equal.
}

void test_an_oracle_on_an_lru_level_changes_no_victim() {
    check::group("W3: check B4, an oracle on an LRU level is a no-op for the result");

    // What licenses attaching an oracle to a level without moving a committed
    // result. Stated in cache_level.h; checked here, where it can actually fail.
    NextUseOracle oracle(std::vector<std::int64_t>{10, 10});

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel watched(Level::L1, map, fx::level(1, 2, 4, 2), counter);
    CacheLevel bare(Level::L1, map, fx::level(1, 2, 4, 2), counter);
    watched.attach_next_use(&oracle);

    Arena arena;
    std::vector<Request*> granted;
    const auto drive = [&](CacheLevel& lvl) {
        probe_then_install(lvl, arena, 10);
        probe_then_install(lvl, arena, 20);
        Request& hot = arena.demand(0, 10);          // a hit, which moves LRU order
        CHECK_TRUE(lvl.triage(hot, granted) == TriageOutcome::Hit);
        return lvl.install(LineId{30});
    };
    const InsertResult with_oracle = drive(watched);
    const InsertResult without     = drive(bare);
    CHECK_TRUE(with_oracle.evicted && without.evicted);
    CHECK_EQ(with_oracle.evicted_line, without.evicted_line);
    CHECK_EQ(with_oracle.evicted_line, LineId{20});  // LRU, and the oracle did not vote

    // Not vacuous: the level really did consult the oracle. Line 20 is not in it,
    // so every probe of 20 overran, which is only reachable through `next_use`.
    CHECK_TRUE(oracle.overruns() > 0);
}

void test_a_prefetch_does_not_advance_the_occurrence() {
    check::group("W3: a prefetch probe leaves the demand occurrence alone");

    // The alignment that makes an oracle built from an access log match the run:
    // both probe sites are guarded on `r.demand`, exactly as `l1_accesses` is, so
    // the k-th demand probe of a line reads the k-th record for it.
    //
    // KNOWN LIMITATION, pinned rather than fixed: the FILL site is guarded on the
    // oracle alone, with no `r.demand`, so a prefetch FILL stamps whatever the
    // last demand probe of that line left behind, or kNever. Under the 0907 base
    // both prefetch policies are `none`, so it cannot bite there; the apps warn
    // on stderr when belady meets a prefetcher rather than refusing, because
    // `l2_policy = belady` with an L2 prefetcher is a configuration that runs
    // today and a refusal would break a rerun of it.
    NextUseOracle plain(std::vector<std::int64_t>{10, 10});
    NextUseOracle prefetched(std::vector<std::int64_t>{10, 10});

    LinearMapper map(64);
    RefusalCounter counter;
    CacheLevel quiet(Level::L1, map, belady_level(), counter);
    CacheLevel noisy(Level::L1, map, belady_level(), counter);
    quiet.attach_next_use(&plain);
    noisy.attach_next_use(&prefetched);

    Arena arena;
    std::vector<Request*> granted;
    // The only difference between the two levels: three prefetch probes of line
    // 10 before anything else. If any of them consumed an occurrence, the demand
    // probe below would read occurrence 1 and get kNever, line 10 and line 20
    // would both look dead, and the victim would flip to the lower slot.
    for (int i = 0; i < 3; ++i) {
        Request& pf = arena.prefetch(0, 10, i);
        noisy.triage(pf, granted);
    }
    for (CacheLevel* lvl : {&quiet, &noisy}) {
        probe_then_install(*lvl, arena, 10);
        probe_then_install(*lvl, arena, 20);
    }
    const InsertResult rq = probe_then_install(quiet, arena, 30);
    const InsertResult rn = probe_then_install(noisy, arena, 30);

    CHECK_EQ(rq.evicted_line, LineId{20});
    CHECK_EQ(rn.evicted_line, rq.evicted_line);
    // And the counts agree: the prefetches asked the oracle nothing at all.
    CHECK_EQ(plain.overruns(), prefetched.overruns());
}

void test_the_level_reports_its_own_geometry() {
    check::group("C1: the level's accessors report the array it actually built");

    LinearMapper map(64);
    RefusalCounter counter;
    LevelParams p = fx::level(8, 2, 5, 3, 1);
    p.banks       = 2;
    CacheLevel l2(Level::L2, map, p, counter);

    CHECK_TRUE(l2.level() == Level::L2);
    CHECK_EQ(l2.num_sets(), 8);
    CHECK_EQ(l2.array().num_slots(), 16);
    CHECK_EQ(l2.mshrs().capacity(), 5);
    CHECK_EQ(l2.mshrs().tgts_per_mshr(), 3);
    CHECK_EQ(l2.mshrs().demand_reserve(), 1);
    CHECK_EQ(l2.banks(), 2);
    // The port is real: `ii = 1` means one accept per cycle, per bank.
    CHECK_EQ(l2.port(0).reserve(SimTime{0}), SimTime{0});
    CHECK_EQ(l2.port(0).reserve(SimTime{0}), SimTime{1});
    CHECK_EQ(l2.port(1).reserve(SimTime{0}), SimTime{0});  // banks are independent
}

}  // namespace

int main() {
    test_hit();
    test_merged();
    test_blocked_targets();
    test_blocked_pool();
    test_forwarded_at_l1_sets_the_re_entry_level();
    test_forwarded_at_l2_leaves_the_level_alone();
    test_dropped_array_hit_does_not_touch_recency();
    test_dropped_entry();
    test_dropped_no_slot_and_dropped_reserve_are_distinguishable();
    test_is_dropped_partitions_the_outcomes();
    test_the_array_is_consulted_before_the_mshr_file();
    test_a_grantee_that_does_not_need_its_slot_releases_it();
    test_a_grantee_that_merges_also_releases();
    test_a_request_already_waiting_is_refused();
    test_install_prefers_a_free_way_and_reports_the_victim();
    test_install_refuses_a_line_that_is_already_resident();
    test_a_freshly_filled_slot_is_not_the_next_victim();
    test_bank_of();
    test_the_constructor_refuses_what_its_parts_refuse();
    test_the_level_reports_its_own_geometry();
    test_two_levels_read_their_own_oracles();
    test_an_oracle_on_an_lru_level_changes_no_victim();
    test_a_prefetch_does_not_advance_the_occurrence();
    return check::summary();
}
