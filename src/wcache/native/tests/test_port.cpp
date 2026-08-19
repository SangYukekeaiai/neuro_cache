// Plan unit B1: `Port { ii, latency, next_accept, reserve() }`.
//
// NAMING, stated once because the tree carries a collision that misreads
// easily: the PLAN's Phase B units are B1 (Port), B2 (EventQueue) and B3
// (MshrFile); PROGRESS.md's DECISIONS are also numbered B1-B104. Every "B1" in
// this file is the plan's unit unless a decision number is named as such.
//
// The exit criterion is plan Part 7 line 1344: "occupancy arithmetic; `ii = 0`
// never delays; `ii = latency` serializes; config rejects a negative `ii` and
// warns on `ii = 0` (N13)". The warning half is D1's, not this class's, and
// port.h records why (one line per config against one per port per core), so
// what is testable here is the rejection and the three arithmetic properties.
//
// The whole unit is three lines of production code, so the test's job is not
// coverage but pinning the two distinctions that make those three lines mean
// something:
//
//   1. `reserve` returns the ACCEPT time and not the completion time. A caller
//      that adds the latency itself is 3.4's spelling; a port that folded it in
//      would produce a plausible, wrong, reproducible answer everywhere. The
//      accept sequence is therefore asserted to be a function of `ii` ALONE
//      (`test_the_accept_sequence_does_not_depend_on_the_latency`), which is
//      stronger than checking one return value.
//   2. `ii` and `latency` are separate quantities. `ii = latency` recovers a
//      non-pipelined channel from the same structure, and `ii < latency` leaves
//      `latency / ii` requests in flight, which is 2.4's "completely different
//      machine" made a number.
#include <wcache/port.h>

#include <wcache/types.h>

#include <cstdint>
#include <initializer_list>
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
// One probe pair per test file is the repo convention (test_stamp_policy.cpp
// states why): the probe encodes which exception type is CORRECT for this
// file's subject, and a shared probe would have to be told. Port's two
// rejections are both configuration, so `invalid_argument` is the right answer
// and every other type is reported as a wrong one rather than swallowed.
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

// The message must NOT name the other field, which is what makes the two
// rejections distinguishable rather than one rejection with two spellings.
// L7's reason in TEST_DESIGN_CACHE.md, applied to this constructor.
void expect_absent(const char* name, const std::string& actual, const char* needle) {
    ++check::g_checks;
    if (contains(actual, needle)) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s must not name \"%s\"\n  message  : %s\n",
                        name, needle, actual.c_str());
    }
}

// --- helpers ----------------------------------------------------------------

std::vector<std::int64_t> accepts_of(Port& p, std::initializer_list<std::int64_t> offers) {
    std::vector<std::int64_t> out;
    for (std::int64_t t : offers) out.push_back(p.reserve(SimTime{t}).get());
    return out;
}

// ===========================================================================
// Construction and rejection
// ===========================================================================

void test_the_constructor_takes_the_two_numbers_it_is_given() {
    check::group("B1: construction");

    const Port p(SimTime{2}, SimTime{100});
    CHECK_EQ(p.ii(), SimTime{2});
    CHECK_EQ(p.latency(), SimTime{100});

    // A port that has never been used is free at 0, because the run starts at
    // tile_origin[0] == 0 (Part 5). Without this the first reserve's answer
    // could not be distinguished from a port seeded anywhere below `now`.
    CHECK_EQ(p.next_accept(), SimTime{0});

    // The two numbers do not leak into each other's accessor. Both directions,
    // because a single asymmetric pair would pass if the two were swapped.
    const Port q(SimTime{7}, SimTime{3});
    CHECK_EQ(q.ii(), SimTime{7});
    CHECK_EQ(q.latency(), SimTime{3});
}

void test_zero_is_accepted_for_both_fields() {
    check::group("B1: ii = 0 and latency = 0 are legal");

    // `ii = 0` is N13's modelling escape hatch, meaning infinite throughput,
    // and it is what the unbounded baseline (V1) is built from. `latency = 0`
    // is the DEFAULT for both `l1_latency` and `l2_to_l1_latency` (2.5b). So
    // the constructor's rule is `>= 0` and not `>= 1`, and a suite that only
    // tested the negative rejections would pass with `>= 1` in place, taking
    // the baseline and the default configuration with it.
    const Port zero_ii(SimTime{0}, SimTime{5});
    CHECK_EQ(zero_ii.ii(), SimTime{0});

    const Port zero_latency(SimTime{1}, SimTime{0});
    CHECK_EQ(zero_latency.latency(), SimTime{0});

    const Port both(SimTime{0}, SimTime{0});
    CHECK_EQ(both.ii(), SimTime{0});
    CHECK_EQ(both.latency(), SimTime{0});
}

void test_a_negative_field_is_refused() {
    check::group("B1: a negative ii or latency is refused");

    // invalid_argument and not logic_error: both are config fields (D1, 2.5b),
    // and the sweep build is -DNDEBUG, so a grid point nobody typed by hand
    // reaching this constructor is the expected case rather than the exotic
    // one. B27's tier rule.
    const std::string neg_ii = thrown_by([] { Port p(SimTime{-1}, SimTime{0}); (void)p; });
    expect_message("negative ii", neg_ii, "Port: ", {"ii", ">= 0", "-1"});
    expect_absent("negative ii", neg_ii, "latency");

    const std::string neg_lat = thrown_by([] { Port p(SimTime{1}, SimTime{-4}); (void)p; });
    expect_message("negative latency", neg_lat, "Port: ", {"latency", ">= 0", "-4"});

    // The value is printed, which is what separates "a field nobody set" from
    // "a field decoded wrong" in a log.
    const std::string big = thrown_by([] { Port p(SimTime{-9000}, SimTime{0}); (void)p; });
    expect_message("the offending value is printed", big, "Port: ", {"-9000"});

    // Check ORDER. `ii` is checked first, so a grid point wrong in both fields
    // reports the half N13 rules on and a sweep varies. Stated in port.h and
    // load-bearing there, so it is pinned rather than left to be inferred: the
    // message must name ii and must not name latency.
    const std::string both = thrown_by([] { Port p(SimTime{-1}, SimTime{-1}); (void)p; });
    expect_message("both negative reports ii", both, "Port: ", {"ii"});
    expect_absent("both negative reports ii", both, "latency");
}

// ===========================================================================
// Occupancy arithmetic
// ===========================================================================

void test_the_occupancy_arithmetic() {
    check::group("B1: occupancy arithmetic, hand computed");

    // Hand-computed rather than recomputed from the formula, which would be the
    // implementation written twice. `ii = 3`, offers at 0, 0, 0, 10, 10, 100:
    //
    //   offer  next_accept before  accept  next_accept after
    //     0            0             0            3
    //     0            3             3            6
    //     0            6             6            9
    //    10            9            10           13
    //    10           13            13           16
    //   100           16           100          103
    //
    // The 10 row is the one that matters: the port was free at 9 and the offer
    // is later, so the accept is the OFFER and not the port's stamp. A port
    // that always answered `next_accept` would give 9 there and pass every
    // row above it.
    Port p(SimTime{3}, SimTime{0});
    const std::vector<std::int64_t> got = accepts_of(p, {0, 0, 0, 10, 10, 100});
    const std::vector<std::int64_t> want{0, 3, 6, 10, 13, 100};
    CHECK_EQ(got, want);
    CHECK_EQ(p.next_accept(), SimTime{103});

    // A saturating stream, where every offer is at 0, so the k-th accept is
    // exactly k * ii and the port is the only thing spacing them. This is the
    // form 4.3's back-pressure argument uses: "a k-long wait set drains through
    // k successive reserve() calls on the same bank: k cycles, strictly
    // sequential", and it is what makes `k x ii` a real cost.
    for (std::int64_t ii : {1, 2, 5}) {
        Port sat(SimTime{ii}, SimTime{0});
        for (std::int64_t k = 0; k < 8; ++k) {
            CHECK_EQ(sat.reserve(SimTime{0}), SimTime{k * ii});
        }
        // The window the drain pushed `next_accept` forward by is exactly
        // `k x ii`, which is the quantity 4.3 says delays every unrelated
        // request to the same bank.
        CHECK_EQ(sat.next_accept(), SimTime{8 * ii});
    }

    // An idle port does not accumulate credit. Offers spaced further apart than
    // `ii` each get their own cycle and nothing is banked for later, which is
    // occupancy rather than quota: there is no window to carry a remainder in.
    Port idle(SimTime{2}, SimTime{0});
    for (std::int64_t t = 0; t < 200; t += 50) {
        CHECK_EQ(idle.reserve(SimTime{t}), SimTime{t});
        CHECK_EQ(idle.next_accept(), SimTime{t + 2});
    }
}

void test_reserve_never_answers_before_the_offer() {
    check::group("B1: an accept is never earlier than its offer");

    // The port never hands out a slot in the past, at any `ii`, and never
    // refuses. `reserve` always returns (3.1: "no E_PortFree. A port is a
    // timestamp, not a queue"), which is the property that lets the engine
    // treat the answer as a fact rather than as a request that might fail.
    for (std::int64_t ii : {0, 1, 4}) {
        Port p(SimTime{ii}, SimTime{7});
        std::int64_t previous = 0;
        for (std::int64_t t = 0; t < 60; t += 3) {
            const SimTime accept = p.reserve(SimTime{t});
            CHECK_TRUE(accept >= SimTime{t});
            CHECK_TRUE(accept >= SimTime{previous});
            CHECK_TRUE(p.next_accept() >= accept);
            previous = accept.get();
        }
    }
}

void test_two_ports_do_not_share_state() {
    check::group("B1: one port per resource");

    // `l1_port[c]` is one per core, `l2_bank[b]` one per bank, `dram` one for
    // the channel (3.3). If `next_accept` were shared, per-core L1 acceptance
    // would serialize across the whole machine and the run would still produce
    // numbers.
    Port a(SimTime{4}, SimTime{0});
    Port b(SimTime{4}, SimTime{0});
    CHECK_EQ(a.reserve(SimTime{0}), SimTime{0});
    CHECK_EQ(b.reserve(SimTime{0}), SimTime{0});
    CHECK_EQ(a.reserve(SimTime{0}), SimTime{4});
    CHECK_EQ(b.next_accept(), SimTime{4});
    CHECK_EQ(a.next_accept(), SimTime{8});
}

// ===========================================================================
// The accept / completion distinction
// ===========================================================================

void test_reserve_returns_the_accept_time_not_the_completion_time() {
    check::group("B1: reserve returns the ACCEPT time");

    // 3.4 spells the call as
    //
    //     accept = l2_bank[bank_of(r.line)].reserve(now);
    //     schedule(E_L2Probe(r), accept + l2_latency);
    //
    // so the caller adds the latency. A port that folded it in would make every
    // caller double-charge, and `ii = latency` would become unexpressible since
    // one number would then be both.
    Port p(SimTime{2}, SimTime{100});
    CHECK_EQ(p.reserve(SimTime{0}), SimTime{0});
    CHECK_EQ(p.next_accept(), SimTime{2});
    CHECK_EQ(p.reserve(SimTime{0}), SimTime{2});
    CHECK_EQ(p.next_accept(), SimTime{4});

    // And the caller's own spelling, which is the expression 3.4 writes: the
    // completion time exists, it is just not the port's to compute.
    Port q(SimTime{2}, SimTime{100});
    const SimTime accept = q.reserve(SimTime{5});
    CHECK_EQ(accept, SimTime{5});
    CHECK_EQ(accept + q.latency(), SimTime{105});
}

void test_the_accept_sequence_does_not_depend_on_the_latency() {
    check::group("B1: the accept sequence is a function of ii alone");

    // The strong form of the case above, and the one that kills a `reserve`
    // that leaked the latency into `next_accept` rather than into the return
    // value. Four ports with the same `ii` and wildly different latencies are
    // driven by one offer stream; every accept and every intermediate
    // `next_accept` must agree, cycle for cycle.
    //
    // Written as several ports rather than one before/after comparison for the
    // reason B102 gives about probe: a comparison against a value the same code
    // path produced can agree with itself while both are wrong.
    const std::int64_t offers[] = {0, 0, 1, 1, 1, 9, 9, 40, 41, 41, 41, 100};

    for (std::int64_t ii : {0, 1, 3}) {
        Port free_port(SimTime{ii}, SimTime{0});
        Port small(SimTime{ii}, SimTime{1});
        Port big(SimTime{ii}, SimTime{110});
        Port huge(SimTime{ii}, SimTime{1000000});

        for (std::int64_t t : offers) {
            const SimTime reference = free_port.reserve(SimTime{t});
            CHECK_EQ(small.reserve(SimTime{t}), reference);
            CHECK_EQ(big.reserve(SimTime{t}), reference);
            CHECK_EQ(huge.reserve(SimTime{t}), reference);
            CHECK_EQ(small.next_accept(), free_port.next_accept());
            CHECK_EQ(big.next_accept(), free_port.next_accept());
            CHECK_EQ(huge.next_accept(), free_port.next_accept());
        }
    }
}

// ===========================================================================
// The two named settings
// ===========================================================================

void test_ii_zero_never_delays() {
    check::group("B1: ii = 0 never delays");

    // The unbounded baseline (V1), reached by configuration rather than by a
    // branch, which is what keeps the baseline and the bounded runs on one code
    // path. Every offer in a run of a hundred at ONE timestamp is accepted at
    // that timestamp: there is no serialization at all, which is the "infinite
    // throughput" 4.3 says `ii = 0` means.
    Port p(SimTime{0}, SimTime{12});
    for (int k = 0; k < 100; ++k) {
        CHECK_EQ(p.reserve(SimTime{7}), SimTime{7});
    }
    CHECK_EQ(p.next_accept(), SimTime{7});

    // And across a non-decreasing stream, which is the only shape the engine
    // produces: `now` is the timestamp of the event being dispatched and a
    // min-heap makes it non-decreasing (P1). Every answer is the offer itself.
    Port q(SimTime{0}, SimTime{0});
    for (std::int64_t t : {0, 0, 3, 3, 3, 4, 100, 100, 101}) {
        CHECK_EQ(q.reserve(SimTime{t}), SimTime{t});
        CHECK_EQ(q.next_accept(), SimTime{t});
    }

    // The contrast that gives the case teeth: at `ii = 1` the same stream is
    // spread out. Without this, "returns the offer" would also be satisfied by
    // a port that never advances `next_accept` at any `ii`.
    Port one(SimTime{1}, SimTime{0});
    CHECK_EQ(one.reserve(SimTime{7}), SimTime{7});
    CHECK_EQ(one.reserve(SimTime{7}), SimTime{8});
    CHECK_EQ(one.reserve(SimTime{7}), SimTime{9});
}

void test_ii_equal_to_latency_serializes() {
    check::group("B1: ii = latency serializes, ii < latency pipelines");

    // 2.4's non-pipelined channel recovered from the same structure: a request
    // offered at 0 is accepted at 0 and completes at `latency`, and the NEXT is
    // accepted exactly when the previous one completed. One round trip at a
    // time, asserted as the identity `accept_k + latency == accept_{k+1}`
    // rather than as a table, since that identity is the definition.
    const std::int64_t L = 10;
    Port serial(SimTime{L}, SimTime{L});
    SimTime previous = serial.reserve(SimTime{0});
    CHECK_EQ(previous, SimTime{0});
    for (int k = 1; k < 6; ++k) {
        const SimTime accept = serial.reserve(SimTime{0});
        CHECK_EQ(previous + serial.latency(), accept);
        previous = accept;
    }

    // The other machine, from port.h's own claim: "a channel with 100 cycles of
    // latency and an `ii` of 2 has 50 requests in flight". Counted rather than
    // asserted -- the number of requests accepted before the first one
    // completes is exactly latency / ii.
    for (std::int64_t ii : {1, 2, 5, 10}) {
        Port pipelined(SimTime{ii}, SimTime{100});
        int in_flight = 0;
        for (int k = 0; k < 200; ++k) {
            if (pipelined.reserve(SimTime{0}) < pipelined.latency()) ++in_flight;
        }
        CHECK_EQ(static_cast<std::int64_t>(in_flight), 100 / ii);
    }

    // And the degenerate end of the same axis, which is the row 2.5 translates
    // the old quota model through: at `ii = 0` the count is unbounded, so the
    // in-flight number is however many were offered. That is why 4.3 insists 0
    // and 1 are not adjacent points on a sweep.
    Port unbounded(SimTime{0}, SimTime{100});
    int unbounded_in_flight = 0;
    for (int k = 0; k < 200; ++k) {
        if (unbounded.reserve(SimTime{0}) < unbounded.latency()) ++unbounded_in_flight;
    }
    CHECK_EQ(unbounded_in_flight, 200);
}

// ===========================================================================
// V14's instrument
// ===========================================================================

void test_busy_cycles_are_readable_from_the_port() {
    check::group("B1: next_accept is the busy-cycle instrument (V14)");

    // V14 is "port busy-cycles <= elapsed cycles x port count", which needs the
    // port's own state rather than a count of calls: an implementation that
    // advanced `next_accept` by the wrong amount and then compensated would
    // look identical from a sequence of return values alone. `next_accept` is
    // exposed for exactly this, so the arithmetic is checked through it.
    //
    // n back-to-back reservations from a port free at 0 leave `next_accept` at
    // exactly n * ii, which IS the busy-cycle count over the window.
    for (std::int64_t ii : {1, 2, 3, 8}) {
        Port p(SimTime{ii}, SimTime{0});
        const int n = 25;
        for (int k = 0; k < n; ++k) (void)p.reserve(SimTime{0});
        CHECK_EQ(p.next_accept(), SimTime{n * ii});
        // The V14 inequality itself, over an elapsed window that contains it.
        CHECK_TRUE(p.next_accept() <= SimTime{n * ii});
    }

    // An idle port charges nothing: busy cycles do not grow with wall time.
    Port sparse(SimTime{1}, SimTime{0});
    (void)sparse.reserve(SimTime{0});
    (void)sparse.reserve(SimTime{1000});
    CHECK_EQ(sparse.next_accept(), SimTime{1001});
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// No default construction: a Port with no numbers is a port whose `ii` and
// `latency` nobody chose, and both are config fields.
static_assert(!std::is_default_constructible<Port>::value, "");

// Both parameters are SimTime, so the raw-int and the wrong-time-type spellings
// are gone; compile_fail.sh's `tryPort` cases carry the negative half.
static_assert(std::is_constructible<Port, SimTime, SimTime>::value, "");
static_assert(!std::is_constructible<Port, std::int64_t, std::int64_t>::value, "");
static_assert(!std::is_constructible<Port, SimTime>::value, "");

// `reserve` mutates the port and therefore cannot be const, and it takes and
// returns a SimTime. The whole member-pointer type is pinned rather than the
// return type alone, so a signature that quietly grew a second parameter (a
// latency the caller passes in, say) stops the build here.
static_assert(std::is_same<decltype(&Port::reserve), SimTime (Port::*)(SimTime)>::value, "");

// The three readers are const, which is what lets a stats pass sample a port
// without reserving on it.
static_assert(std::is_same<decltype(&Port::ii), SimTime (Port::*)() const>::value, "");
static_assert(std::is_same<decltype(&Port::latency), SimTime (Port::*)() const>::value, "");
static_assert(std::is_same<decltype(&Port::next_accept), SimTime (Port::*)() const>::value, "");

// A port is copyable as itself: the engine holds one per core over 8 to 256
// cores (2.5b), so a container of them is the ordinary case.
static_assert(std::is_copy_constructible<Port>::value, "");
static_assert(std::is_copy_assignable<Port>::value, "");

}  // namespace

int main() {
    test_the_constructor_takes_the_two_numbers_it_is_given();
    test_zero_is_accepted_for_both_fields();
    test_a_negative_field_is_refused();
    test_the_occupancy_arithmetic();
    test_reserve_never_answers_before_the_offer();
    test_two_ports_do_not_share_state();
    test_reserve_returns_the_accept_time_not_the_completion_time();
    test_the_accept_sequence_does_not_depend_on_the_latency();
    test_ii_zero_never_delays();
    test_ii_equal_to_latency_serializes();
    test_busy_cycles_are_readable_from_the_port();
    return check::summary();
}
