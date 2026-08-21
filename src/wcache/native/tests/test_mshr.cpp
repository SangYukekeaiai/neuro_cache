// Plan unit B3: `MshrFile`, its entries, `targets`, `line_wait`, `slot_wait`,
// the refusal counter, `find` / `allocate` / `retire`, and the grant loop.
//
// NAMING: the PLAN's Phase B units are B1 (Port), B2 (EventQueue) and B3
// (MshrFile); PROGRESS.md's DECISIONS are also numbered B1-B104. Every "B3" in
// this file is the plan's unit unless a decision is named as one.
//
// The exit criterion is plan Part 7 line 1346: "grant loop terminates with a
// free slot; the line-wait set resolves atomically on retire; the 3.8
// out-of-order-insert counterexample sorts correctly; a non-demand allocation
// is refused once fewer than `demand_reserve` entries remain, and promotion of
// an entry to demand is idempotent". Each has a test named after it below.
//
// What this unit does NOT do bounds what can be tested here: it never reserves
// a port, never schedules an event, and never knows which level it is. So the
// L1 and the L2 are the SAME class with different numbers, and the two fixtures
// that say "L2" below differ from the L1 ones only in their capacities and in
// what the bound being checked is named after (I11).
//
// Invariants reachable at Phase B and asserted here: I1 (one live Mshr per line
// per level), I3 (|targets| <= tgts_per_mshr), I4 (|entries| + reserved <=
// capacity), I6b's storage form, I7 (the grant loop terminates), I11 (the
// line-wait bound), I15 (a prefetch is never on a wait index). I2's write-once
// half is here too; its "unique across the run" half is V18 and belongs to a
// run. I7b needs a port and is C2's.
#include <wcache/mshr.h>

#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <deque>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "check.h"

using namespace wcache;

namespace {

// ===========================================================================
// Probes
// ===========================================================================
//
// TWO probes here rather than the usual one, because MshrFile is the first
// class in the tree that uses both of B27's tiers on purpose and the split is
// part of its contract. The constructor's four rejections are CONFIG
// (`invalid_argument`, since the sweep build is -DNDEBUG and a grid is a cross
// product); `allocate`, `retire` and the two pushes refuse CALLER errors
// (`logic_error`, since 3.4 checks `find` and `has_slot` first and a refused
// prefetch is a rule the engine broke). A single probe would let one tier pass
// as the other, which is exactly the distinction being pinned.
template <typename Fn>
std::string config_thrown_by(Fn fn) {
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
std::string caller_thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::invalid_argument& e) {
        return std::string("[invalid_argument, not logic_error] ") + e.what();
    } catch (const std::out_of_range& e) {
        return std::string("[out_of_range, not logic_error] ") + e.what();
    } catch (const std::logic_error& e) {
        return e.what();
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

void expect_message(const char* name, const std::string& actual, const char* prefix,
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

void expect_absent(const char* name, const std::string& actual, const char* needle) {
    ++check::g_checks;
    if (contains(actual, needle)) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s must not name \"%s\"\n  message  : %s\n",
                        name, needle, actual.c_str());
    }
}

// ===========================================================================
// Fixtures
// ===========================================================================

// The requests a fixture holds. A deque and not a vector, and the reason is
// P5 rather than container taste: the wait indices store POINTERS because they
// are selection sets over structures the engine already owns, so the requests
// must outlive their membership and must not move while they are pointed at. A
// vector reallocating mid-fixture would leave every index dangling and the test
// would be measuring undefined behaviour instead of the file. std::deque never
// invalidates references to existing elements on push_back.
class Arena {
public:
    Request& demand(std::int32_t core, std::int64_t line, std::int32_t burst = 0) {
        r_.push_back(Request{CoreId{core}, LineId{line}, BurstIndex{burst}});
        return r_.back();
    }
    Request& prefetch(std::int32_t core, std::int64_t line, std::int32_t burst = 0) {
        r_.push_back(Request{CoreId{core}, LineId{line}, BurstIndex{burst}, false});
        return r_.back();
    }

private:
    std::deque<Request> r_;
};

std::vector<std::int64_t> stamps_of(const std::vector<Request*>& v) {
    std::vector<std::int64_t> out;
    for (const Request* r : v) out.push_back(r->refusal.get());
    return out;
}

// I4 and I3, checkable from outside at any moment. Called after every step of
// the soak and at the end of several hand-built fixtures, because both are
// invariants rather than outcomes: a file that satisfied them only at the end
// of a fixture would have been over-full in the middle.
void expect_i4(const MshrFile& f) {
    CHECK_TRUE(f.live() + f.reserved() <= f.capacity());
    CHECK_TRUE(f.live() >= 0);
    CHECK_TRUE(f.reserved() >= 0);
}

// ===========================================================================
// Construction
// ===========================================================================

void test_the_constructor_validates_in_the_stated_order() {
    check::group("B3: the constructor's four checks, in order");

    RefusalCounter counter;

    // The order is load-bearing and mshr.h states it rather than leaving it to
    // be inferred, so it is pinned here in B62's shape: each case is wrong in
    // TWO fields and must report the earlier one, which is the only way an
    // order can be measured at all.
    const std::string cap =
        config_thrown_by([&counter] { MshrFile f(0, 4, 0, counter); (void)f; });
    expect_message("capacity 0", cap, "MshrFile: ", {"capacity", ">= 1", "0"});

    const std::string cap_and_tgts =
        config_thrown_by([&counter] { MshrFile f(0, 0, 0, counter); (void)f; });
    expect_message("capacity before tgts", cap_and_tgts, "MshrFile: ", {"capacity"});
    expect_absent("capacity before tgts", cap_and_tgts, "tgts_per_mshr");

    // tgts_per_mshr >= 1 because the primary occupies a target slot, so a zero
    // here is an entry that cannot record its own allocator.
    const std::string tgts =
        config_thrown_by([&counter] { MshrFile f(4, 0, 0, counter); (void)f; });
    expect_message("tgts_per_mshr 0", tgts, "MshrFile: ", {"tgts_per_mshr", ">= 1"});

    const std::string tgts_and_reserve =
        config_thrown_by([&counter] { MshrFile f(4, 0, -1, counter); (void)f; });
    expect_message("tgts before demand_reserve", tgts_and_reserve, "MshrFile: ",
                   {"tgts_per_mshr"});
    expect_absent("tgts before demand_reserve", tgts_and_reserve, "demand_reserve");

    const std::string reserve =
        config_thrown_by([&counter] { MshrFile f(4, 2, -1, counter); (void)f; });
    expect_message("demand_reserve -1", reserve, "MshrFile: ", {"demand_reserve", ">= 0", "-1"});

    // The fourth check is a RELATION between two fields and only means anything
    // once both have been accepted, which is why it is last. Its message names
    // both numbers, since "5 exceeds 4" is actionable and "bad demand_reserve"
    // is not.
    const std::string too_big =
        config_thrown_by([&counter] { MshrFile f(4, 2, 5, counter); (void)f; });
    expect_message("demand_reserve over capacity", too_big, "MshrFile: ",
                   {"demand_reserve", "5", "4"});

    // The two boundaries that are ACCEPTED, and the second of them is the
    // DEFAULT configuration rather than an edge case: `l1_demand_reserve`
    // defaults to `lines_per_burst`, so at `l1_mshrs == lines_per_burst` the
    // prefetch budget is exactly zero and prefetching is off however
    // `prefetch_distance` is set (4.2). A constructor that rejected equality
    // would reject the shipped defaults.
    const MshrFile smallest(1, 1, 0, counter);
    CHECK_EQ(smallest.capacity(), 1);
    CHECK_EQ(smallest.tgts_per_mshr(), 1);
    CHECK_EQ(smallest.demand_reserve(), 0);

    const MshrFile all_reserved(4, 2, 4, counter);
    CHECK_EQ(all_reserved.demand_reserve(), 4);
    CHECK_EQ(all_reserved.live(), 0);
    CHECK_EQ(all_reserved.reserved(), 0);
    CHECK_EQ(all_reserved.slot_wait_depth(), 0);
}

// ===========================================================================
// The refusal counter and the write-once stamp
// ===========================================================================

void test_the_refusal_counter_is_global_and_write_once() {
    check::group("B3: 3.8's stamp, write-once at the FIRST refusal");

    RefusalCounter counter;
    CHECK_EQ(counter.issued(), 0);
    CHECK_EQ(counter.next(), RefusalOrder{0});
    CHECK_EQ(counter.next(), RefusalOrder{1});
    CHECK_EQ(counter.issued(), 2);

    // The ABSOLUTE values matter, not only the order: V18 asserts every
    // waiter's stamp is written exactly once and is unique across the run, and
    // `issued()` is the count that check compares against. A counter that
    // started at 1 would order identically and break that comparison.
    Arena arena;
    RefusalCounter c2;
    MshrFile l1(4, 2, 0, c2);
    MshrFile l2(4, 2, 0, c2);   // ONE counter, shared: a request refused at the
                                // L1 and again at the L2 keeps its original
                                // stamp, so it carries L2 seniority reflecting
                                // how long it has genuinely waited (3.8).

    Request& a = arena.demand(0, 100);
    Request& b = arena.demand(1, 200);
    l1.push_slot_wait(a);
    l2.push_slot_wait(b);
    CHECK_EQ(a.refusal, RefusalOrder{0});
    CHECK_EQ(b.refusal, RefusalOrder{1});
    CHECK_EQ(c2.issued(), 2);

    // Write-once. `a` is re-refused, at the other level and on the other index,
    // and keeps stamp 0. If the stamp were reset on a wake, an aged request
    // would lose to every fresh arrival at high load, forever, and I10's
    // starvation-freedom argument (the set of smaller stamps is finite and
    // never grows) would not hold.
    Request& primary = arena.demand(2, 300);
    Mshr& e = l2.allocate(LineId{300}, primary);
    l2.push_line_wait(e, a);
    CHECK_EQ(a.refusal, RefusalOrder{0});
    CHECK_EQ(c2.issued(), 2);

    // And the REASON is write-once with it, exactly as `mark_refused` spells
    // it. mshr.h records the consequence rather than designing around it: `a`
    // was first refused for a slot and now sits on a line-wait index, and still
    // reports Slot. What releases a waiter is which vector holds it; this field
    // is Part 8's reporting of how it ENTERED the population.
    CHECK_TRUE(a.reason == WaitReason::Slot);
    CHECK_EQ(check::ssize(e.line_wait), 1);

    // A fresh request carries NoRefusal, which is INT64_MAX, so it sorts after
    // every refused one under plain `<` (3.8's collapsed key).
    Request& fresh = arena.demand(3, 400);
    CHECK_EQ(fresh.refusal, NoRefusal);
    CHECK_TRUE(fresh.reason == WaitReason::None);
    CHECK_TRUE(key_less(a, fresh));
    CHECK_TRUE(!key_less(fresh, a));
    CHECK_TRUE(key_less(a, b));
}

// ===========================================================================
// find, allocate, and I1
// ===========================================================================

void test_find_and_allocate() {
    check::group("B3: find / allocate, and I1");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(3, 2, 0, counter);

    CHECK_TRUE(f.find(LineId{10}) == nullptr);
    CHECK_EQ(f.live(), 0);

    // 3.3's defaults on a fresh request, checked once and here because nothing
    // else in this file reads them and each is a field a wrong default would
    // make silently true of every request in the run: `level` says where to
    // RE-ENTER on wake (3.5) and a fresh request has not reached the L2 yet;
    // `mshr1` is I6's other half (`r.level == L2 <=> r.mshr1 != null`); and a
    // request that started out holding a reservation would be admitted by
    // `has_slot` unconditionally, forever.
    Request& p = arena.demand(1, 10, 5);
    CHECK_TRUE(p.level == Level::L1);
    CHECK_TRUE(p.mshr1 == nullptr);
    CHECK_TRUE(!p.reserved);
    CHECK_TRUE(p.demand);
    CHECK_EQ(p.burst, BurstIndex{5});

    Mshr& e = f.allocate(LineId{10}, p);
    CHECK_EQ(f.live(), 1);
    CHECK_EQ(e.line, LineId{10});
    CHECK_EQ(e.core, CoreId{1});
    CHECK_TRUE(e.demand);

    // find hands back THE entry, not a copy, and hands back the same one every
    // time. The engine holds `Request::mshr1` across the whole downstream round
    // trip (I6), so a file that reseated its entries would leave every held
    // pointer naming something else.
    CHECK_TRUE(f.find(LineId{10}) == &e);
    CHECK_TRUE(f.find(LineId{10}) == &e);
    CHECK_TRUE(f.find(LineId{11}) == nullptr);

    // The primary occupies targets[0]. That is what makes 4.1's per-entry bound
    // `n_cores - tgts_per_mshr` rather than one less, and it is what puts the
    // primary through the same retire loop as every later merge, so there is no
    // second path that could satisfy it differently.
    CHECK_EQ(check::ssize(e.targets), 1);
    CHECK_TRUE(e.targets[0] == &p);
    CHECK_EQ(check::ssize(e.line_wait), 0);

    // I1: at most one live Mshr per line per level. A second entry for one line
    // double-fetches it, so this is a throw and not an assert.
    Request& q = arena.demand(2, 10, 6);
    const std::string dup = caller_thrown_by([&f, &q] { return &f.allocate(LineId{10}, q); });
    expect_message("a second entry for one line", dup, "MshrFile::allocate", {"10", "already"});
    CHECK_EQ(f.live(), 1);

    // Allocating past the capacity is the caller's error too: 3.4 checks
    // `has_slot` first. A silently over-full file reports an occupancy the
    // sweep is measuring.
    Request& r2 = arena.demand(0, 20);
    Request& r3 = arena.demand(0, 30);
    (void)f.allocate(LineId{20}, r2);
    (void)f.allocate(LineId{30}, r3);
    CHECK_EQ(f.live(), 3);
    Request& r4 = arena.demand(0, 40);
    const std::string full = caller_thrown_by([&f, &r4] { return &f.allocate(LineId{40}, r4); });
    expect_message("allocate past the capacity", full, "MshrFile::allocate",
                   {"no free entry", "3", "live"});
    expect_absent("a demand refusal does not mention prefetch", full, "prefetch");
    expect_i4(f);
}

// ===========================================================================
// has_slot and the demand reserve
// ===========================================================================

void test_a_non_demand_allocation_is_refused_at_the_reserve() {
    check::group("B3: the demand reserve, and the prefetch budget");

    Arena arena;
    RefusalCounter counter;

    // capacity 4, reserve 2, so the prefetch BUDGET is capacity - reserve = 2
    // (4.2). Exactly two prefetch entries may ever be live at once, and the
    // third is refused while two entries are still free, which is the rule
    // 4.6's table states: a prefetch may never take the last `demand_reserve`
    // entries, so a demand burst can always allocate.
    MshrFile f(4, 2, 2, counter);

    Request& pf0 = arena.prefetch(0, 100);
    Request& pf1 = arena.prefetch(0, 101);
    Request& pf2 = arena.prefetch(0, 102);
    Request& dm0 = arena.demand(0, 200);
    Request& dm1 = arena.demand(0, 201);

    CHECK_TRUE(f.has_slot(pf0));
    (void)f.allocate(LineId{100}, pf0);
    CHECK_TRUE(f.has_slot(pf1));
    (void)f.allocate(LineId{101}, pf1);

    // Budget spent. Two entries are still free and a DEMAND request takes one
    // happily, which is the whole point of the reserve: prefetching can delay
    // demand but never starve it.
    CHECK_EQ(f.live(), 2);
    CHECK_TRUE(!f.has_slot(pf2));
    CHECK_TRUE(f.has_slot(dm0));

    const std::string refused =
        caller_thrown_by([&f, &pf2] { return &f.allocate(LineId{102}, pf2); });
    expect_message("a prefetch at the reserve", refused, "MshrFile::allocate",
                   {"prefetch", "may not take the last", "2"});

    (void)f.allocate(LineId{200}, dm0);
    (void)f.allocate(LineId{201}, dm1);
    CHECK_EQ(f.live(), 4);
    CHECK_TRUE(!f.has_slot(arena.demand(0, 202)));
    expect_i4(f);

    // The boundary walked one entry at a time, so an off-by-one in either
    // direction shows up as the wrong crossing point rather than as a pass.
    // capacity 5, reserve 2: a prefetch is admitted while `free > 2`, so at
    // live 0,1,2 yes and at live 3,4,5 no.
    const bool expected_prefetch[6] = {true, true, true, false, false, false};
    for (std::int32_t live = 0; live < 6; ++live) {
        RefusalCounter c3;
        MshrFile h(5, 2, 2, c3);
        Arena a3;
        for (std::int32_t i = 0; i < live; ++i) {
            Request& d = a3.demand(0, 1000 + i);
            (void)h.allocate(LineId{1000 + i}, d);
        }
        Request& probe_pf = a3.prefetch(0, 9999);
        Request& probe_dm = a3.demand(0, 9998);
        CHECK_EQ(h.has_slot(probe_pf), expected_prefetch[live]);
        CHECK_EQ(h.has_slot(probe_dm), live < 5);
    }

    // demand_reserve == capacity is the demand-only default (4.2): the budget
    // is exactly zero, so no prefetch may ever allocate, even into an empty
    // file. That is the budget being zero rather than a special case.
    RefusalCounter c4;
    MshrFile demand_only(4, 2, 4, c4);
    Arena a4;
    CHECK_TRUE(!demand_only.has_slot(a4.prefetch(0, 1)));
    CHECK_TRUE(demand_only.has_slot(a4.demand(0, 1)));

    // demand_reserve == 0 is the other end: a prefetch is admitted on exactly
    // the same terms as a demand request.
    RefusalCounter c5;
    MshrFile no_reserve(2, 2, 0, c5);
    Arena a5;
    Request& only = a5.prefetch(0, 1);
    CHECK_TRUE(no_reserve.has_slot(only));
    (void)no_reserve.allocate(LineId{1}, only);
    Request& second = a5.prefetch(0, 2);
    CHECK_TRUE(no_reserve.has_slot(second));
    (void)no_reserve.allocate(LineId{2}, second);
    CHECK_TRUE(!no_reserve.has_slot(a5.prefetch(0, 3)));
    CHECK_TRUE(!no_reserve.has_slot(a5.demand(0, 3)));
}

void test_a_grantee_is_admitted_by_its_own_reservation() {
    check::group("B3: a reservation is a credit already counted");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(1, 2, 0, counter);

    // Fill the one entry, park a waiter, then retire so the waiter is granted.
    Request& p = arena.demand(0, 1);
    Mshr& e = f.allocate(LineId{1}, p);
    Request& w = arena.demand(1, 2);
    f.push_slot_wait(w);
    CHECK_TRUE(!f.has_slot(w));            // no credit yet

    RetireResult out;
    f.retire(e, out);
    CHECK_EQ(check::ssize(out.wake), 1);
    CHECK_TRUE(w.reserved);
    CHECK_EQ(f.reserved(), 1);
    CHECK_EQ(f.live(), 0);
    expect_i4(f);

    // The grantee is admitted UNCONDITIONALLY, because the credit it is about
    // to spend is the one `collect_grants` set aside for it and is already
    // counted in `reserved`. Without that case a grantee would be refused by
    // its own reservation and the freed slot would never be consumed.
    CHECK_TRUE(f.has_slot(w));

    // Spending it trades the reservation for the entry, one for one, so I4
    // holds across the transition rather than only at its ends.
    (void)f.allocate(LineId{2}, w);
    CHECK_TRUE(!w.reserved);
    CHECK_EQ(f.reserved(), 0);
    CHECK_EQ(f.live(), 1);
    expect_i4(f);

    // A leaked reservation is a credit the file never hands back, so the grant
    // loop would stop one waiter short for the rest of the run and the symptom
    // would be a stall attributed to the MSHR bound. That is why `allocate`
    // spends it rather than leaving a `consume_reservation` call for a caller
    // to forget.
    Request& later = arena.demand(2, 3);
    CHECK_TRUE(!f.has_slot(later));
}

void test_release_reservation() {
    check::group("B3: a grantee that turns out not to need its slot");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(2, 2, 0, counter);

    Request& p = arena.demand(0, 1);
    Mshr& e = f.allocate(LineId{1}, p);
    Request& w = arena.demand(1, 2);
    Request& x = arena.demand(2, 3);
    f.push_slot_wait(w);
    f.push_slot_wait(x);

    RetireResult out;
    f.retire(e, out);
    CHECK_EQ(f.reserved(), 2);   // capacity 2, nothing live, both granted
    CHECK_EQ(check::ssize(out.wake), 2);

    // 3.4 calls `release_reservation` on every hit and merge whether or not one
    // was held, so a request holding none is not an error: it answers false and
    // the caller knows not to re-run the grant loop.
    CHECK_TRUE(f.release_reservation(w));
    CHECK_TRUE(!w.reserved);
    CHECK_EQ(f.reserved(), 1);
    CHECK_TRUE(!f.release_reservation(w));      // idempotent, and says so
    CHECK_EQ(f.reserved(), 1);
    CHECK_TRUE(!f.release_reservation(arena.demand(9, 9)));
    CHECK_EQ(f.reserved(), 1);
    expect_i4(f);

    // And the released credit is really back: a fresh demand request is now
    // admitted where it was not a moment ago.
    Request& fresh = arena.demand(3, 4);
    CHECK_TRUE(f.has_slot(fresh));
    CHECK_TRUE(f.release_reservation(x));
    CHECK_EQ(f.reserved(), 0);
}

// ===========================================================================
// add_target: I3 and 4.6's promotion
// ===========================================================================

void test_add_target_bounds_the_list_and_promotes_idempotently() {
    check::group("B3: add_target owns I3 and 4.6's promotion");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(4, 3, 0, counter);          // three targets per entry

    Request& p = arena.demand(0, 50);
    Mshr& e = f.allocate(LineId{50}, p);
    CHECK_EQ(check::ssize(e.targets), 1);   // the primary is one of the three

    Request& t1 = arena.demand(1, 50);
    Request& t2 = arena.demand(2, 50);
    CHECK_TRUE(f.add_target(e, t1));
    CHECK_TRUE(f.add_target(e, t2));
    CHECK_EQ(check::ssize(e.targets), 3);

    // I3, and the bound lives inside `add_target` so it cannot be violated by a
    // caller that checked it and then pushed anyway. At the bound the call
    // returns false and changes NOTHING, which is the caller's signal to
    // line-wait instead (3.4's BLOCKED_TARGETS).
    Request& t3 = arena.demand(3, 50);
    CHECK_TRUE(!f.add_target(e, t3));
    CHECK_EQ(check::ssize(e.targets), 3);
    CHECK_TRUE(e.targets[0] == &p);
    CHECK_TRUE(e.targets[1] == &t1);
    CHECK_TRUE(e.targets[2] == &t2);

    // Refusing at the bound is not the same as refusing always: a second entry
    // in the same file still accepts targets.
    Request& p2 = arena.demand(0, 60);
    Mshr& e2 = f.allocate(LineId{60}, p2);
    CHECK_TRUE(f.add_target(e2, t3));

    // 4.6's promotion, in all four combinations, which is the only way to say
    // "idempotent" rather than "happens to work here". `e.demand = e.demand ||
    // r.demand`: a demand request merging onto a prefetch entry makes it a
    // demand entry (the LATE PREFETCH case, where the fetch started early but
    // not early enough), and every other combination leaves it as it was.
    struct Combo {
        bool entry_starts_demand;
        bool target_is_demand;
        bool entry_ends_demand;
    };
    const Combo combos[] = {
        {false, false, false},   // prefetch onto prefetch: still nobody waiting
        {false, true,  true},    // 4.6's promotion
        {true,  false, true},    // a prefetch merging onto a demand entry must
                                 // NOT demote it: a core IS waiting on this line
        {true,  true,  true},
    };
    std::int64_t line = 1000;
    for (const Combo& c : combos) {
        RefusalCounter fc;
        MshrFile g(2, 4, 0, fc);
        Arena a;
        Request& primary = c.entry_starts_demand ? a.demand(0, line) : a.prefetch(0, line);
        Mshr& entry = g.allocate(LineId{line}, primary);
        CHECK_EQ(entry.demand, c.entry_starts_demand);

        Request& merging = c.target_is_demand ? a.demand(1, line) : a.prefetch(1, line);
        CHECK_TRUE(g.add_target(entry, merging));
        CHECK_EQ(entry.demand, c.entry_ends_demand);

        // Idempotent by construction rather than by discipline: merging the
        // SAME kind again, and then the other kind, never moves it back.
        Request& again = c.target_is_demand ? a.demand(2, line) : a.prefetch(2, line);
        CHECK_TRUE(g.add_target(entry, again));
        CHECK_EQ(entry.demand, c.entry_ends_demand);
        Request& other = c.target_is_demand ? a.prefetch(3, line) : a.demand(3, line);
        CHECK_TRUE(g.add_target(entry, other));
        CHECK_TRUE(entry.demand);       // once demand, always demand
        ++line;
    }

    // The entry's `demand` is seeded from the PRIMARY, not defaulted, which is
    // what makes a prefetch-allocated entry a prefetch entry at all.
    RefusalCounter c6;
    MshrFile h(2, 2, 0, c6);
    Arena a6;
    Request& pf = a6.prefetch(0, 77);
    CHECK_TRUE(!h.allocate(LineId{77}, pf).demand);
}

// ===========================================================================
// The drop rule: I15 and N16
// ===========================================================================

void test_a_prefetch_is_dropped_and_never_queued() {
    check::group("B3: N16, a refused prefetch is dropped");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(2, 1, 0, counter);

    Request& p = arena.demand(0, 5);
    Mshr& e = f.allocate(LineId{5}, p);

    // Both pushes refuse a `demand == false` request. Making it unrepresentable
    // here is cheaper than looking for it in a sweep (I15), and it is the ONE
    // rule that keeps the waiting population backed one-for-one by demand
    // credits, which is the whole of 4.1's argument: a prefetch permitted to
    // wait would occupy a selection set with no L1 MSHR entry behind it.
    Request& pf = arena.prefetch(1, 5);
    const std::string line_wait =
        caller_thrown_by([&f, &e, &pf] { f.push_line_wait(e, pf); });
    expect_message("a prefetch on a line-wait index", line_wait, "MshrFile::push_line_wait",
                   {"prefetch", "dropped", "N16"});

    const std::string slot_wait = caller_thrown_by([&f, &pf] { f.push_slot_wait(pf); });
    expect_message("a prefetch on the slot-wait index", slot_wait, "MshrFile::push_slot_wait",
                   {"prefetch", "dropped", "N16"});

    // It threw BEFORE touching anything, so a caught throw leaves no half-state
    // and, in particular, does not stamp the prefetch with a refusal it will
    // then carry forever.
    CHECK_EQ(check::ssize(e.line_wait), 0);
    CHECK_EQ(f.slot_wait_depth(), 0);
    CHECK_EQ(pf.refusal, NoRefusal);
    CHECK_TRUE(pf.reason == WaitReason::None);
    CHECK_EQ(counter.issued(), 0);

    // A demand request on the same call sites goes through and IS stamped, so
    // the refusal above is about the demand bit and not about the file being
    // in some state that refuses everyone.
    Request& dm = arena.demand(2, 5);
    f.push_line_wait(e, dm);
    CHECK_EQ(check::ssize(e.line_wait), 1);
    CHECK_EQ(dm.refusal, RefusalOrder{0});
    CHECK_TRUE(dm.reason == WaitReason::Line);

    Request& dm2 = arena.demand(3, 6);
    f.push_slot_wait(dm2);
    CHECK_EQ(f.slot_wait_depth(), 1);
    CHECK_EQ(dm2.refusal, RefusalOrder{1});
    CHECK_TRUE(dm2.reason == WaitReason::Slot);
}

// ===========================================================================
// retire
// ===========================================================================

void test_the_line_wait_set_resolves_atomically() {
    check::group("B3: the whole line-wait set resolves at once");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(4, 2, 0, counter);

    Request& p = arena.demand(0, 70);
    Mshr& e = f.allocate(LineId{70}, p);
    Request& t = arena.demand(1, 70);
    CHECK_TRUE(f.add_target(e, t));      // targets now full at 2

    // Five more arrive after the target list filled. Because targets in a
    // read-only cache are satisfied only by the fill, a target list NEVER
    // drains incrementally, so nothing is promoted from line_wait into targets
    // and the whole set resolves at once, at retire, as hits (3.7). A model
    // that promoted on a free target slot would be modelling a drain that
    // cannot happen.
    for (std::int32_t c = 2; c < 7; ++c) f.push_line_wait(e, arena.demand(c, 70));
    CHECK_EQ(check::ssize(e.line_wait), 5);
    CHECK_EQ(check::ssize(e.targets), 2);

    RetireResult out;
    f.retire(e, out);

    // The two groups are reported separately, and acting on them alike is D5's
    // livelock in the other direction: a target is satisfied DIRECTLY by the
    // fill and never re-triages, while a woken waiter goes back through its
    // level's port and re-probes.
    CHECK_EQ(check::ssize(out.targets), 2);
    CHECK_TRUE(out.targets[0] == &p);
    CHECK_TRUE(out.targets[1] == &t);

    // ALL of them, in one dispatch. Not some, not one per retire.
    CHECK_EQ(check::ssize(out.wake), 5);
    CHECK_EQ(stamps_of(out.wake), (std::vector<std::int64_t>{0, 1, 2, 3, 4}));

    // The entry is gone, so a second retire has nothing to resolve and there is
    // no residue for a later retire to wake a second time.
    CHECK_TRUE(f.find(LineId{70}) == nullptr);
    CHECK_EQ(f.live(), 0);
    expect_i4(f);
}

void test_the_grant_loop_terminates_with_a_free_slot() {
    check::group("B3: I7, collect_grants terminates and leaves a free slot");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(3, 1, 0, counter);

    // Three entries live, capacity three, and ten waiters. Retiring ONE entry
    // frees exactly one credit, so exactly one waiter is granted: the loop
    // terminates because every iteration strictly increases `reserved` while
    // its bound is fixed, and it terminates WITH a free slot in the sense that
    // matters -- the grantee can allocate.
    Request& p0 = arena.demand(0, 1);
    Request& p1 = arena.demand(0, 2);
    Request& p2 = arena.demand(0, 3);
    Mshr& e0 = f.allocate(LineId{1}, p0);
    (void)f.allocate(LineId{2}, p1);
    (void)f.allocate(LineId{3}, p2);

    std::vector<Request*> waiters;
    for (std::int32_t c = 1; c <= 10; ++c) {
        Request& w = arena.demand(c, 100 + c);
        f.push_slot_wait(w);
        waiters.push_back(&w);
    }
    CHECK_EQ(f.slot_wait_depth(), 10);

    RetireResult out;
    f.retire(e0, out);
    CHECK_EQ(check::ssize(out.wake), 1);
    CHECK_EQ(f.slot_wait_depth(), 9);
    CHECK_EQ(f.reserved(), 1);
    CHECK_EQ(f.live(), 2);
    expect_i4(f);

    // Oldest first: the grant went to the request with the smallest stamp,
    // which is the one that has genuinely waited longest.
    CHECK_TRUE(out.wake[0] == waiters[0]);
    CHECK_TRUE(out.wake[0]->reserved);

    // And the grantee really can allocate, which is what "terminates with a
    // free slot" means operationally.
    CHECK_TRUE(f.has_slot(*out.wake[0]));
    (void)f.allocate(out.wake[0]->line, *out.wake[0]);
    CHECK_EQ(f.live(), 3);
    CHECK_EQ(f.reserved(), 0);
    expect_i4(f);

    // An empty file with many waiters grants exactly `capacity` of them and
    // stops: the loop is bounded by credits, not by the index's length, so a
    // wake never produces a thundering herd racing for one slot (3.8).
    RefusalCounter c2;
    MshrFile g(4, 1, 0, c2);
    Arena a2;
    Request& only = a2.demand(0, 1);
    Mshr& ge = g.allocate(LineId{1}, only);
    for (std::int32_t c = 1; c <= 20; ++c) g.push_slot_wait(a2.demand(c, 200 + c));
    RetireResult gout;
    g.retire(ge, gout);
    CHECK_EQ(check::ssize(gout.wake), 4);
    CHECK_EQ(g.reserved(), 4);
    CHECK_EQ(g.slot_wait_depth(), 16);
    expect_i4(g);
}

void test_the_credit_this_retire_freed_is_the_one_it_hands_out() {
    check::group("B3: retire ERASES before it grants");

    // The ordering claim in 3.4 and in mshr.h, stated as its own test because
    // it is invisible in any fixture with spare capacity. Capacity ONE, one
    // entry live, one waiter: the only credit in the file is the one this
    // retire is freeing. Collect first and the loop sees a full file and grants
    // nobody; erase first and the waiter is granted. Every retire in a
    // capacity-bound run differs by one waiter, which is a stall the sweep
    // would attribute to the MSHR depth.
    Arena arena;
    RefusalCounter counter;
    MshrFile f(1, 1, 0, counter);

    Request& p = arena.demand(0, 1);
    Mshr& e = f.allocate(LineId{1}, p);
    Request& w = arena.demand(1, 2);
    f.push_slot_wait(w);
    CHECK_EQ(f.live(), 1);
    CHECK_EQ(f.slot_wait_depth(), 1);

    RetireResult out;
    f.retire(e, out);
    CHECK_EQ(check::ssize(out.wake), 1);
    CHECK_TRUE(out.wake[0] == &w);
    CHECK_EQ(f.slot_wait_depth(), 0);
    CHECK_EQ(f.reserved(), 1);
    CHECK_EQ(f.live(), 0);
    expect_i4(f);

    // The same shape at a larger capacity, so the case is not a property of
    // capacity one: three live of three, four waiting, retire one, exactly one
    // granted. Off by one in the other direction would grant two.
    RefusalCounter c2;
    MshrFile g(3, 1, 0, c2);
    Arena a2;
    Request& g0 = a2.demand(0, 10);
    Mshr& ge = g.allocate(LineId{10}, g0);
    (void)g.allocate(LineId{11}, a2.demand(0, 11));
    (void)g.allocate(LineId{12}, a2.demand(0, 12));
    for (std::int32_t c = 1; c <= 4; ++c) g.push_slot_wait(a2.demand(c, 20 + c));
    RetireResult gout;
    g.retire(ge, gout);
    CHECK_EQ(check::ssize(gout.wake), 1);
    CHECK_EQ(g.reserved(), 1);
    CHECK_EQ(g.live(), 2);
}

void test_the_3_8_counterexample() {
    check::group("B3: 3.8's out-of-order insert, replayed (V17)");

    // The counterexample verbatim from plan 3.8:
    //
    //   t=5   r1 wants Y. No entry for Y, pool full  -> slot_wait, stamp 5
    //   t=6   some core allocates B(Y)                  (r1 is asleep)
    //   t=8   r2 wants Y. Matches B, targets full    -> B.line_wait, stamp 8
    //   t=10  an entry retires, a slot frees. collect_grants pops r1 (oldest),
    //         reinjects. r1 re-triages, now finds B(Y) with full targets
    //                                                -> B.line_wait.push(r1),
    //                                                   stamp still 5
    //         B.line_wait = [r2(8), r1(5)]           <- out of age order
    //
    // The stamps here are counter values rather than ticks (3.8 is explicit
    // that the stamp is a COUNTER, not a tick), so r1 gets 0 and r2 gets 1; the
    // structure is identical and the ORDER is what the case is about.
    const std::int64_t Y = 777;

    Arena arena;
    RefusalCounter counter;
    MshrFile f(1, 1, 0, counter);          // capacity 1, one target per entry

    // The pool is full with an unrelated line X.
    Request& px = arena.demand(0, 900);
    Mshr& X = f.allocate(LineId{900}, px);

    // t=5: r1 wants Y, no entry, pool full -> slot_wait. FIRST refusal.
    Request& r1 = arena.demand(1, Y);
    CHECK_TRUE(f.find(LineId{Y}) == nullptr);
    CHECK_TRUE(!f.has_slot(r1));
    f.push_slot_wait(r1);
    CHECK_EQ(r1.refusal, RefusalOrder{0});

    // t=6: X retires, and a core allocates B(Y) with its own primary. r1 is
    // asleep on the slot index and does not notice; it is granted by this
    // retire, so the fixture spends the grant on the allocating request the way
    // the engine would, then re-refuses r1 below.
    RetireResult first;
    f.retire(X, first);
    CHECK_EQ(check::ssize(first.wake), 1);
    CHECK_TRUE(first.wake[0] == &r1);      // r1 was granted the freed credit
    CHECK_TRUE(r1.reserved);

    Request& pb = arena.demand(2, Y);
    // r1's grant is released because r1's own re-triage will find B(Y) and need
    // no slot after all, which is 3.4's `release_reservation` on the merge
    // path. Released FIRST, so the credit is available to B's primary.
    CHECK_TRUE(f.release_reservation(r1));
    Mshr& B = f.allocate(LineId{Y}, pb);
    CHECK_EQ(check::ssize(B.targets), 1);   // full at tgts_per_mshr == 1

    // t=8: r2 wants Y, matches B, targets full -> B.line_wait, stamp 1.
    Request& r2 = arena.demand(3, Y);
    CHECK_TRUE(!f.add_target(B, r2));
    f.push_line_wait(B, r2);
    CHECK_EQ(r2.refusal, RefusalOrder{1});

    // t=10: r1 re-triages, finds B with full targets, and joins the line-wait
    // index carrying its ORIGINAL stamp. `reinject` never touches the stamp, so
    // a request enters the waiting population exactly once.
    CHECK_TRUE(!f.add_target(B, r1));
    f.push_line_wait(B, r1);
    CHECK_EQ(r1.refusal, RefusalOrder{0});   // still 0, not re-stamped

    // The wait set is now OUT OF AGE ORDER on insert. This is the observation
    // the whole case exists for: building a wait set as a literal FIFO gives
    // the wrong order in exactly this situation.
    CHECK_EQ(stamps_of(B.line_wait), (std::vector<std::int64_t>{1, 0}));
    CHECK_TRUE(B.line_wait[0] == &r2);
    CHECK_TRUE(B.line_wait[1] == &r1);

    // And the retire sorts it. Insert order [r2, r1] wakes as [r1, r2], which
    // is the "[1,0] waking as [0,1]" the implementation reports. Service order
    // is r1 before r2 even though r1 was inserted second, which is V17.
    RetireResult out;
    f.retire(B, out);
    CHECK_EQ(check::ssize(out.wake), 2);
    CHECK_TRUE(out.wake[0] == &r1);
    CHECK_TRUE(out.wake[1] == &r2);
    CHECK_EQ(stamps_of(out.wake), (std::vector<std::int64_t>{0, 1}));

    // The sort is therefore NOT redundant, and this is the fixture that says
    // so: without it the wake order is the insert order, which is [1, 0].
}

void test_the_wake_list_is_one_key_ordered_population() {
    check::group("B3: the merge of the two indices is by age, not by index");

    // 3.7's ruling: there is deliberately NO rule ranking line waiters above
    // slot waiters, or either above fresh arrivals. One key orders everything,
    // and 3.4 merges and re-sorts the two indexes at every retire. So the
    // stamps are interleaved ACROSS the two indices on purpose: line waiters
    // take 0 and 3, slot waiters 1 and 2, and a wake list grouped by index
    // would come out [0,3,1,2] while the correct answer is [0,1,2,3].
    //
    // The merge is mandatory rather than tidy: reinjection reserves a port, so
    // iterating the two indexes separately staggers the wake by loop order
    // instead of by age, which is what I7b forbids.
    Arena arena;
    RefusalCounter counter;
    MshrFile f(4, 1, 0, counter);

    Request& p = arena.demand(0, 500);
    Mshr& e = f.allocate(LineId{500}, p);
    (void)f.allocate(LineId{501}, arena.demand(0, 501));
    (void)f.allocate(LineId{502}, arena.demand(0, 502));
    (void)f.allocate(LineId{503}, arena.demand(0, 503));

    Request& line_a = arena.demand(1, 500);
    Request& slot_a = arena.demand(2, 600);
    Request& slot_b = arena.demand(3, 601);
    Request& line_b = arena.demand(4, 500);

    f.push_line_wait(e, line_a);   // stamp 0
    f.push_slot_wait(slot_a);      // stamp 1
    f.push_slot_wait(slot_b);      // stamp 2
    f.push_line_wait(e, line_b);   // stamp 3

    RetireResult out;
    f.retire(e, out);

    // One credit freed, so exactly one slot waiter is granted, and it is the
    // older of the two. Both line waiters wake regardless: they need no slot
    // and will all hit, since the line is resident by the time they re-probe.
    CHECK_EQ(check::ssize(out.wake), 3);
    CHECK_EQ(stamps_of(out.wake), (std::vector<std::int64_t>{0, 1, 3}));
    CHECK_TRUE(out.wake[0] == &line_a);
    CHECK_TRUE(out.wake[1] == &slot_a);      // interleaved BETWEEN two line waiters
    CHECK_TRUE(out.wake[2] == &line_b);
    CHECK_TRUE(slot_a.reserved);
    CHECK_TRUE(!slot_b.reserved);
    CHECK_TRUE(!line_a.reserved);            // a LINE waiter holds nothing
    CHECK_TRUE(!line_b.reserved);
    CHECK_EQ(f.slot_wait_depth(), 1);
    expect_i4(f);

    // A LINE waiter woken by an unrelated retire would livelock the grant loop
    // (3.7): it re-blocks on the same condition, is popped again, and the freed
    // slot is never consumed. So the two indices must stay distinguishable by
    // WHAT RELEASES THEM, and this is that fact from the other side -- retiring
    // a DIFFERENT entry wakes the slot waiter and leaves the other entry's line
    // waiters exactly where they are.
    Mshr* other = f.find(LineId{501});
    CHECK_TRUE(other != nullptr);
    Request& other_line = arena.demand(5, 501);
    f.push_line_wait(*other, other_line);

    Mshr* third = f.find(LineId{502});
    RetireResult out2;
    f.retire(*third, out2);
    CHECK_EQ(check::ssize(out2.wake), 1);
    CHECK_TRUE(out2.wake[0] == &slot_b);           // the slot waiter, released by ANY retire
    CHECK_EQ(check::ssize(other->line_wait), 1);   // the other entry's line waiter, untouched
    CHECK_TRUE(other->line_wait[0] == &other_line);
}

// D4/V6's first half: a LINE waiter is woken onto a resident line and a SLOT
// waiter is not, and the two are told apart by a bit `retire` writes.
//
// It matters because the engine reads that bit at the re-probe and counts
// `hits_downgraded_to_miss` when the re-probe misses anyway. Marking the slot
// waiters too would count every ordinary grant-then-allocate as a downgrade,
// which is the whole population rather than the exception.
void test_retire_marks_line_waiters_as_woken_onto_a_resident_line() {
    check::group("B3: D4, retire marks the LINE waiters and not the slot waiters");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(1, 1, 0, counter);

    Request& p = arena.demand(0, 7);
    Mshr& e    = f.allocate(LineId{7}, p);

    // The target list is full at one, so a second request for the same line
    // waits on THIS entry and is released by its fill.
    Request& liner = arena.demand(1, 7);
    f.push_line_wait(e, liner);

    // A request for another line has no entry to wait on and no free slot, so it
    // waits for any entry and is released by ANY retire, with no promise at all
    // about its own line.
    Request& slotter = arena.demand(2, 9);
    f.push_slot_wait(slotter);

    CHECK_TRUE(!liner.line_resident_at_wake);
    CHECK_TRUE(!slotter.line_resident_at_wake);

    RetireResult out;
    f.retire(e, out);
    CHECK_EQ(check::ssize(out.wake), 2);
    CHECK_TRUE(liner.line_resident_at_wake);
    CHECK_TRUE(!slotter.line_resident_at_wake);
}

void test_retire_replaces_its_output_and_refuses_a_foreign_entry() {
    check::group("B3: retire's out parameter, and a foreign entry");

    Arena arena;
    RefusalCounter counter;
    MshrFile f(4, 2, 0, counter);

    // `out` is REPLACED, not appended to, so a caller may reuse one buffer
    // across retires. An appending version makes a later retire hand the engine
    // an earlier one's targets a second time, which double-serves a core.
    RetireResult out;
    out.targets.assign(7, nullptr);
    out.wake.assign(5, nullptr);

    Request& p = arena.demand(0, 1);
    Mshr& e = f.allocate(LineId{1}, p);
    f.retire(e, out);
    CHECK_EQ(check::ssize(out.targets), 1);
    CHECK_EQ(check::ssize(out.wake), 0);

    // Reused across a second retire, which is the pattern the contract exists
    // for.
    Request& p2 = arena.demand(0, 2);
    Mshr& e2 = f.allocate(LineId{2}, p2);
    Request& t2 = arena.demand(1, 2);
    CHECK_TRUE(f.add_target(e2, t2));
    f.retire(e2, out);
    CHECK_EQ(check::ssize(out.targets), 2);
    CHECK_EQ(check::ssize(out.wake), 0);

    // An entry that is not this file's is a caller error. Two shapes: a live
    // entry of ANOTHER file, and a stale copy whose line no longer has an entry
    // here. The second is the one that would otherwise erase whatever entry now
    // happens to hold that line.
    RefusalCounter c2;
    MshrFile g(2, 2, 0, c2);
    Arena a2;
    Request& gp = a2.demand(0, 3);
    Mshr& ge = g.allocate(LineId{3}, gp);
    RetireResult ignored;
    const std::string foreign =
        caller_thrown_by([&f, &ge, &ignored] { f.retire(ge, ignored); });
    expect_message("an entry of another file", foreign, "MshrFile::retire",
                   {"3", "not a live entry"});

    Mshr stale{LineId{2}, CoreId{0}, true, false, SimTime{0}, {}, {}};
    const std::string gone =
        caller_thrown_by([&f, &stale, &ignored] { f.retire(stale, ignored); });
    expect_message("an already-retired entry", gone, "MshrFile::retire",
                   {"2", "not a live entry"});
    CHECK_EQ(g.live(), 1);

    // The third shape, and the only one that measures the IDENTITY half of the
    // check rather than the lookup half: a line that IS live in this file,
    // presented as a different Mshr object. A `retire` that only asked whether
    // the line has an entry would erase the real one and report someone else's
    // targets as satisfied, which double-serves a core and drops a fill.
    Request& live_p = arena.demand(0, 42);
    (void)f.allocate(LineId{42}, live_p);
    Mshr impostor{LineId{42}, CoreId{9}, true, false, SimTime{0}, {}, {}};
    const std::string other_object =
        caller_thrown_by([&f, &impostor, &ignored] { f.retire(impostor, ignored); });
    expect_message("a different object for a live line", other_object, "MshrFile::retire",
                   {"42", "not a live entry"});
    CHECK_EQ(f.live(), 1);
    CHECK_TRUE(f.find(LineId{42}) != nullptr);
}

void test_the_line_wait_bound_i11() {
    check::group("B3: I11, the per-entry line-wait bound");

    // I11 at the L2: `|e.line_wait| <= n_cores - l2_tgts_per_mshr`. The bound
    // holds with EQUALITY in the worst case, and that is what makes it a real
    // number rather than an inequality nobody can reach: at most one request
    // per core arrives at the L2 for any given line (I6b, because a core's L1
    // absorbs every later same-line request), so n_cores requests for one line
    // fill the target list first and the rest line-wait.
    //
    // The corollary is I12 and it is a real design lever: if
    // `l2_tgts_per_mshr >= n_cores`, the L2 line-wait sets are provably always
    // empty.
    for (std::int32_t n_cores : {4, 8, 16}) {
        for (std::int32_t tgts : {1, 2, 4, 8, 16}) {
            RefusalCounter counter;
            MshrFile l2(2, tgts, 0, counter);
            Arena arena;
            const std::int64_t line = 4242;

            Request& primary = arena.demand(0, line);
            Mshr& e = l2.allocate(LineId{line}, primary);
            for (std::int32_t c = 1; c < n_cores; ++c) {
                Request& r = arena.demand(c, line);
                if (!l2.add_target(e, r)) l2.push_line_wait(e, r);
            }

            const std::int32_t merged  = static_cast<std::int32_t>(e.targets.size());
            const std::int32_t waiting = static_cast<std::int32_t>(e.line_wait.size());
            CHECK_EQ(merged, tgts < n_cores ? tgts : n_cores);
            CHECK_EQ(waiting, tgts < n_cores ? n_cores - tgts : 0);
            CHECK_TRUE(waiting <= n_cores - (tgts < n_cores ? tgts : n_cores));
            CHECK_TRUE(merged <= l2.tgts_per_mshr());          // I3
            // I12: at or above n_cores targets, the set is provably empty.
            if (tgts >= n_cores) CHECK_EQ(waiting, 0);
        }
    }
}

// ===========================================================================
// The randomized soak, against an independent model
// ===========================================================================

// The model. It stores the same relationships the file does, but it computes
// `retire`'s two answers ITSELF, from 3.4's four steps written out: copy the
// targets, take all the line waiters, erase, THEN grant, then sort by 3.8's
// key. That last ordering is the whole reason the model exists rather than a
// set of spot checks: a file that granted before erasing agrees with a model
// that also granted before erasing, so the model spells the plan's order rather
// than the code's.
//
// It deliberately does NOT re-implement `has_slot`. The soak drives the file
// through the production predicate the way the engine does and asserts I4 after
// every step, so an over-permissive predicate is caught by the invariant rather
// than by a second copy of the formula that could be wrong in the same way.
struct ModelEntry {
    std::vector<Request*> targets;
    std::vector<Request*> line_wait;
    bool demand;
};

void test_a_soak_against_the_model() {
    check::group("B3: randomized soak against an independent model");

    // A small file on purpose. TEST_DESIGN_CACHE.md's group R records the
    // lesson: a large case count can still leave the interesting path nearly
    // untouched, and here the interesting paths are "the file is full" and "the
    // target list is full", both of which a roomy file almost never reaches.
    const std::int32_t capacity = 4;
    const std::int32_t tgts     = 2;
    const std::int32_t reserve  = 1;
    const std::int64_t n_lines  = 6;

    Arena arena;
    RefusalCounter counter;
    MshrFile f(capacity, tgts, reserve, counter);

    std::map<std::int64_t, ModelEntry> model;
    std::vector<Request*> model_slot_wait;
    std::int32_t model_reserved = 0;
    std::int64_t next_stamp     = 0;

    RetireResult out;

    // A deterministic LCG, held in an UNSIGNED accumulator on purpose. Signed
    // overflow is undefined behaviour, and the first version of this line kept
    // the state in an int64: the fixture then behaved differently under -O2,
    // where the optimiser is entitled to assume the overflow cannot happen, and
    // the stream collapsed to an allocate/retire alternation that reached none
    // of the paths this soak exists to reach. It still reported zero
    // mismatches, which is the shape of the failure worth recording: the model
    // agreed with the file about a stream that tested nothing, and only the
    // coverage floors below caught it. Unsigned wrap is defined, so the two
    // builds now drive the same stream.
    std::uint64_t rng = 12345;
    auto next         = [&rng]() {
        rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
        return static_cast<std::int64_t>((rng >> 17) & 0x7fffffffULL);
    };

    int allocations = 0, merges = 0, line_waits = 0, slot_waits = 0, retires = 0, drops = 0;
    int grants = 0, releases = 0;
    int mismatches = 0;

    // 3.4's triage, minus the array probe (there is no array at Phase B) and
    // minus the port (there is no clock here either). One lambda rather than
    // two copies, because it is called both when a request first arrives and
    // when `retire` wakes it: a woken request re-enters triage and its outcome
    // is unknown (3.7), which is the whole difference between a SLOT waiter and
    // a MERGED subentry, and a soak that never re-triaged its wake list would
    // leave every reservation outstanding and the file permanently full.
    //
    // The model bookkeeping here MIRRORS the file rather than predicting it.
    // The independent computation is retire's two answers, below; this is
    // plumbing that keeps the two structures beside each other.
    auto triage = [&](Request& r) {
        Mshr* e = f.find(r.line);
        const bool model_has = model.count(r.line.get()) != 0;
        if ((e != nullptr) != model_has) ++mismatches;

        if (e != nullptr) {
            // 3.4: a request that matches an entry needs no slot after all, so
            // it gives any grant back before merging.
            if (r.reserved) {
                if (!f.release_reservation(r)) ++mismatches;
                --model_reserved;
                ++releases;
            }
            if (f.add_target(*e, r)) {
                ModelEntry& m = model[r.line.get()];
                m.targets.push_back(&r);
                m.demand = m.demand || r.demand;
                ++merges;
            } else if (r.demand) {
                const bool fresh = (r.refusal == NoRefusal);
                f.push_line_wait(*e, r);
                model[r.line.get()].line_wait.push_back(&r);
                if (fresh) ++next_stamp;
                if (r.refusal == NoRefusal) ++mismatches;
                ++line_waits;
            } else {
                ++drops;    // 4.6: a prefetch is dropped, never queued
            }
            return;
        }

        if (f.has_slot(r)) {
            const bool held = r.reserved;
            Mshr& fresh_entry = f.allocate(r.line, r);
            ModelEntry m;
            m.targets.push_back(&r);
            m.demand = r.demand;
            model[r.line.get()] = m;
            if (fresh_entry.demand != m.demand) ++mismatches;
            if (r.reserved) ++mismatches;          // the reservation was spent
            if (held) --model_reserved;
            ++allocations;
            return;
        }

        if (r.demand) {
            const bool fresh = (r.refusal == NoRefusal);
            f.push_slot_wait(r);
            model_slot_wait.push_back(&r);
            if (fresh) ++next_stamp;
            ++slot_waits;
        } else {
            ++drops;
        }
    };

    for (int step = 0; step < 20000; ++step) {
        const std::int64_t roll = next() % 10;

        if (roll < 6 || model.empty()) {
            const std::int64_t line = next() % n_lines;
            const bool is_demand    = (next() % 4) != 0;
            triage(is_demand ? arena.demand(static_cast<std::int32_t>(next() % 8), line)
                             : arena.prefetch(static_cast<std::int32_t>(next() % 8), line));
        } else {
            // Retire a live entry, chosen by position in the MODEL's ordered map
            // so the choice never depends on the file's unordered_map order,
            // which is unspecified and must not reach the run.
            auto it = model.begin();
            std::advance(it, static_cast<std::ptrdiff_t>(
                                 next() % static_cast<std::int64_t>(model.size())));
            const std::int64_t line = it->first;

            // The model's own answer, from 3.4's four steps written out: copy
            // the targets, take ALL the line waiters, ERASE, then grant, then
            // sort by 3.8's key. The erase-before-grant order is the whole
            // reason this is a model rather than a set of spot checks.
            std::vector<Request*> want_targets = it->second.targets;
            std::vector<Request*> want_wake    = it->second.line_wait;
            model.erase(it);
            while (static_cast<std::int32_t>(model.size()) + model_reserved < capacity &&
                   !model_slot_wait.empty()) {
                auto oldest = std::min_element(
                    model_slot_wait.begin(), model_slot_wait.end(),
                    [](const Request* a, const Request* b) { return a->refusal < b->refusal; });
                Request* granted = *oldest;
                model_slot_wait.erase(oldest);
                granted->reserved = true;
                ++model_reserved;
                want_wake.push_back(granted);
                ++grants;
            }
            std::stable_sort(want_wake.begin(), want_wake.end(),
                             [](const Request* a, const Request* b) {
                                 return a->refusal < b->refusal;
                             });

            Mshr* e = f.find(LineId{line});
            if (e == nullptr) {
                ++mismatches;
            } else {
                f.retire(*e, out);
                if (out.targets != want_targets) ++mismatches;
                if (out.wake != want_wake) ++mismatches;
                ++retires;
                // Every woken request re-enters triage, in the order the file
                // handed them back, which is what the engine's `reinject` loop
                // does. Copied out first: `out` is reused by nothing here, but
                // triage can retire nothing, so this is only about reading a
                // buffer the loop below does not own.
                const std::vector<Request*> woken = out.wake;
                for (Request* w : woken) triage(*w);
            }
        }

        // The invariants, after EVERY step rather than at the end.
        if (f.live() != static_cast<std::int32_t>(model.size())) ++mismatches;
        if (f.reserved() != model_reserved) ++mismatches;
        if (f.slot_wait_depth() != static_cast<std::int32_t>(model_slot_wait.size()))
            ++mismatches;
        if (f.live() + f.reserved() > capacity) ++mismatches;              // I4
        for (const auto& kv : model) {
            const Mshr* e = f.find(LineId{kv.first});
            if (e == nullptr) { ++mismatches; continue; }
            if (static_cast<std::int32_t>(e->targets.size()) > tgts) ++mismatches;   // I3
            if (e->targets != kv.second.targets) ++mismatches;
            if (e->line_wait != kv.second.line_wait) ++mismatches;
            if (e->demand != kv.second.demand) ++mismatches;
            for (const Request* t : e->line_wait)
                if (!t->demand) ++mismatches;                                        // I15
        }
        for (const Request* w : model_slot_wait)
            if (!w->demand) ++mismatches;                                            // I15
    }
    CHECK_EQ(mismatches, 0);
    CHECK_EQ(counter.issued(), next_stamp);

    // The fixture must have reached every path it claims to cover, or the zero
    // above is a statement about a stream that never got interesting. F13's
    // lesson, in the form group R states it.
    CHECK_TRUE(allocations > 500);
    CHECK_TRUE(merges > 500);
    CHECK_TRUE(line_waits > 200);
    CHECK_TRUE(slot_waits > 200);
    CHECK_TRUE(retires > 500);
    CHECK_TRUE(drops > 100);
    CHECK_TRUE(grants > 200);
    CHECK_TRUE(releases > 50);
    std::printf("  soak: %d allocations, %d merges, %d line-waits, %d slot-waits, "
                "%d retires, %d grants, %d released grants, %d prefetch drops, %lld stamps\n",
                allocations, merges, line_waits, slot_waits, retires, grants, releases, drops,
                static_cast<long long>(counter.issued()));
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// The three tagged scalars a Request carries are DIFFERENT types, which is the
// whole reason BurstIndex exists: a CoreId and a BurstIndex are both int32 and
// both small counts sitting side by side, so `Request{...}` with two arguments
// swapped is a spelling the struct invites and that neither `explicit` nor the
// non-narrowing constructor can see. compile_fail.sh's `tryMshr` cases carry
// the swap itself.
static_assert(std::is_same<decltype(Request::core), CoreId>::value, "");
static_assert(std::is_same<decltype(Request::line), LineId>::value, "");
static_assert(std::is_same<decltype(Request::burst), BurstIndex>::value, "");
static_assert(!std::is_same<CoreId, BurstIndex>::value, "");

// The first three fields have no defaults, so a forgotten initialiser cannot
// silently mean core 0 / line 0 / the first burst of the tile.
static_assert(!std::is_default_constructible<Request>::value, "");

// `demand` is a plain bool defaulting to true, so `Request{c, l, k}` is a fresh
// DEMAND request and the prefetch spelling is explicit.
static_assert(std::is_same<decltype(Request::demand), bool>::value, "");

// `Mshr::demand` is a mutable field rather than a constructor argument, which
// is 4.6's promotion path made possible at all.
static_assert(std::is_same<decltype(Mshr::demand), bool>::value, "");
static_assert(!std::is_const<decltype(Mshr::demand)>::value, "");

// Both wait indices hold POINTERS, which is P5: a wait list stores nothing, it
// selects. A vector of Requests here would have invented hardware, and 4.1's
// bound would become an argument about simulator memory rather than about
// credits.
static_assert(std::is_same<decltype(Mshr::targets), std::vector<Request*>>::value, "");
static_assert(std::is_same<decltype(Mshr::line_wait), std::vector<Request*>>::value, "");
static_assert(std::is_same<decltype(RetireResult::targets), std::vector<Request*>>::value, "");
static_assert(std::is_same<decltype(RetireResult::wake), std::vector<Request*>>::value, "");

// The two enums are scoped and one byte wide, and neither decays to an int.
static_assert(std::is_same<std::underlying_type<Level>::type, std::uint8_t>::value, "");
static_assert(std::is_same<std::underlying_type<WaitReason>::type, std::uint8_t>::value, "");
static_assert(!std::is_convertible<Level, int>::value, "");
static_assert(!std::is_convertible<WaitReason, int>::value, "");

// The four readers are const, so a stats pass can sample MSHR occupancy (Part
// 8's headline instrument) without changing the file.
static_assert(std::is_same<decltype(&MshrFile::live), std::int32_t (MshrFile::*)() const>::value, "");
static_assert(std::is_same<decltype(&MshrFile::reserved), std::int32_t (MshrFile::*)() const>::value, "");
static_assert(std::is_same<decltype(&MshrFile::slot_wait_depth),
                           std::int32_t (MshrFile::*)() const>::value, "");
static_assert(std::is_same<decltype(&MshrFile::has_slot),
                           bool (MshrFile::*)(const Request&) const>::value, "");

// `find` is NOT const and returns a mutable entry: the caller merges onto it.
static_assert(std::is_same<decltype(&MshrFile::find), Mshr* (MshrFile::*)(LineId)>::value, "");

// `allocate` takes the primary by non-const reference, because it spends the
// primary's reservation, and hands back a reference to the entry the file owns.
static_assert(std::is_same<decltype(&MshrFile::allocate),
                           Mshr& (MshrFile::*)(LineId, Request&)>::value, "");

// `mark_refused` is a free function, not a method: it belongs to neither the
// counter nor the file, it is the rule joining them.
static_assert(std::is_same<decltype(&mark_refused),
                           void (*)(Request&, WaitReason, RefusalCounter&)>::value, "");

// A file holds its counter by reference, so it cannot be copied into a second
// file with a private counter and quietly start a second stamp sequence.
static_assert(!std::is_copy_assignable<MshrFile>::value, "");
static_assert(!std::is_default_constructible<MshrFile>::value, "");

}  // namespace

int main() {
    test_the_constructor_validates_in_the_stated_order();
    test_the_refusal_counter_is_global_and_write_once();
    test_find_and_allocate();
    test_a_non_demand_allocation_is_refused_at_the_reserve();
    test_a_grantee_is_admitted_by_its_own_reservation();
    test_release_reservation();
    test_add_target_bounds_the_list_and_promotes_idempotently();
    test_a_prefetch_is_dropped_and_never_queued();
    test_the_line_wait_set_resolves_atomically();
    test_the_grant_loop_terminates_with_a_free_slot();
    test_the_credit_this_retire_freed_is_the_one_it_hands_out();
    test_the_3_8_counterexample();
    test_the_wake_list_is_one_key_ordered_population();
    test_retire_marks_line_waiters_as_woken_onto_a_resident_line();
    test_retire_replaces_its_output_and_refuses_a_foreign_entry();
    test_the_line_wait_bound_i11();
    test_a_soak_against_the_model();
    return check::summary();
}
