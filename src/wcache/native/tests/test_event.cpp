// Plan unit B2: `EventQueue`, the min-heap on `(time, class, effective_age,
// core_id, seq)` (N10).
//
// NAMING: the PLAN's Phase B units are B1 (Port), B2 (EventQueue) and B3
// (MshrFile); PROGRESS.md's DECISIONS are also numbered B1-B104. Every "B2" in
// this file is the plan's unit.
//
// This file also closes a harness gap the implementer flagged, and the gap is
// worth naming because it has the same shape as an earlier one: `event.h` was
// included by NO translation unit, so nothing in the tree compiled it. That is
// `cache.h`'s state before A4a, where B59 recorded that an interface created
// but never compiled carries a clean sweep while nothing in it is ever
// exercised. A header-only unit is not tested by the library building.
//
// The exit criterion is plan Part 7 line 1345: "total order; two identical runs
// produce identical event logs". Both halves are here, and the second is the
// substantive one, so it is built as a real scenario (a closed loop where what
// is popped decides what is scheduled next) rather than as a replay of a fixed
// list, which would exercise no ordering decision at all.
//
// The ordering is not cosmetic (D7): under LRU the order two hits to one set are
// serviced IS the recency stack, so one flipped tie leaves a different victim
// and every access after it diverges. A run is either bit-identical or
// arbitrarily different, which is why D11 asks for a TOTAL order rather than a
// stable one.
#include <wcache/event.h>

#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
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
// B2's rejections are all `logic_error`: an event scheduled behind `now` and a
// pop from an empty queue are both an engine that computed something wrong, not
// a config value, which is B27's programmer-error tier. So the probe here
// treats `logic_error` as the correct answer and reports every other type as a
// wrong one, which is the mirror of test_port.cpp's probe rather than a copy of
// it.
template <typename Fn>
std::string logic_thrown_by(Fn fn) {
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

// ===========================================================================
// The independent oracle
// ===========================================================================
//
// 3.6's key, spelled out here from the plan rather than reached for from
// event.h. That independence is the whole value of this function and is the
// reason it is not `key_less` with a different name: if the oracle called
// `key_less`, then every mutation of `key_less` would move the oracle with it
// and the pop-order comparison below would agree with itself while both were
// wrong. Same circularity B102 caught in the probe-is-not-an-access test, in
// its comparator form.
//
// It reads `.get()` and casts the class to an int, so it depends on `EventKey`'s
// field TYPES and on the class's numeric values; those are pinned separately by
// the static_asserts at the bottom of this file, which is what stops this
// function from silently inheriting a mutation of the enum.
bool oracle_earlier(const EventKey& a, const EventKey& b) {
    if (a.time.get() != b.time.get()) return a.time.get() < b.time.get();
    const int ca = static_cast<int>(a.cls);
    const int cb = static_cast<int>(b.cls);
    if (ca != cb) return ca < cb;
    if (a.age.get() != b.age.get()) return a.age.get() < b.age.get();
    if (a.core.get() != b.core.get()) return a.core.get() < b.core.get();
    return a.seq.get() < b.seq.get();
}

EventKey key_of(std::int64_t time, EventClass cls, std::int64_t age, std::int32_t core,
                std::int64_t seq) {
    return EventKey{SimTime{time}, cls, RefusalOrder{age}, CoreId{core}, EventSeq{seq}};
}

// A deterministic 64-bit mixer, so a failure reproduces exactly and no test in
// this file depends on a library RNG's implementation. Group G's seeded
// mt19937 is the tree's precedent for "deterministic, reproducible, written
// down"; this is the same discipline with no state to carry between runs.
std::int64_t mix(std::int64_t x) {
    std::uint64_t v = static_cast<std::uint64_t>(x) + 0x9e3779b97f4a7c15ULL;
    v ^= v >> 30;
    v *= 0xbf58476d1ce4e5b9ULL;
    v ^= v >> 27;
    v *= 0x94d049bb133111ebULL;
    v ^= v >> 31;
    return static_cast<std::int64_t>(v & 0x7fffffffffffffffULL);
}

// ===========================================================================
// class_of, and the class order
// ===========================================================================

void test_class_of_maps_every_kind() {
    check::group("B2: class_of, 3.6's table as code");

    // The six kinds of 3.1 against the four classes of 3.6. Written as six
    // separate checks rather than a loop over a table, because a table would be
    // the mapping written twice and the second copy could be wrong in the same
    // way as the first.
    CHECK_TRUE(class_of(EventKind::L2Fill) == EventClass::Fill);
    CHECK_TRUE(class_of(EventKind::L1Fill) == EventClass::Fill);
    CHECK_TRUE(class_of(EventKind::Barrier) == EventClass::Barrier);
    CHECK_TRUE(class_of(EventKind::L1Probe) == EventClass::Probe);
    CHECK_TRUE(class_of(EventKind::L2Probe) == EventClass::Probe);
    CHECK_TRUE(class_of(EventKind::Issue) == EventClass::Issue);

    // A kind outside the enumerators is REPORTED, not given a fallback class.
    // The fallback is the one wrong answer available here: a kind silently
    // dispatched at class 0 would reorder the run against itself and the result
    // would still look like a result.
    const std::string bad =
        logic_thrown_by([] { return class_of(static_cast<EventKind>(99)); });
    expect_message("an unknown kind is refused", bad, "class_of", {"EventKind"});
}

void test_the_class_order_decides_a_same_cycle_tie() {
    check::group("B2: Fill < Barrier < Probe < Issue at one cycle");

    // Asserted through the KINDS rather than through the class values, so the
    // check survives any renumbering of the enum and fails for a wrong
    // `class_of` either way. Every pair is scheduled at ONE timestamp with the
    // same age and core, so the class is the only field that can decide, and
    // the later-scheduled event is deliberately the one that must come out
    // first: with the class dropped, `seq` would decide and give schedule
    // order, which is the opposite answer.
    struct Case {
        EventKind later_but_first;
        EventKind earlier_but_second;
        const char* why;
    };
    const Case cases[] = {
        {EventKind::L1Fill, EventKind::Barrier,
         "3.6: the barrier observes completed fills, and therefore completed services"},
        {EventKind::Barrier, EventKind::L1Probe, "3.6: a lookup sees this cycle's fills"},
        {EventKind::L1Probe, EventKind::Issue, "3.6: new demand enters last"},
        {EventKind::L2Fill, EventKind::Issue, "class 0 against class 3"},
        {EventKind::L1Fill, EventKind::L2Probe,
         "4.6's worked example: a prefetch fill and a demand probe both land at 111"},
    };

    for (const Case& c : cases) {
        EventQueue<int> q;
        q.schedule(SimTime{111}, c.earlier_but_second, NoRefusal, CoreId{0}, 2);
        q.schedule(SimTime{111}, c.later_but_first, NoRefusal, CoreId{0}, 1);
        CHECK_TRUE(q.pop_min().kind == c.later_but_first);
        CHECK_TRUE(q.pop_min().kind == c.earlier_but_second);
        (void)c.why;
    }

    // The whole chain in one queue, scheduled in exactly reverse order, so
    // nothing but the class can produce the answer.
    EventQueue<int> q;
    q.schedule(SimTime{7}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    q.schedule(SimTime{7}, EventKind::L2Probe, NoRefusal, CoreId{0}, 1);
    q.schedule(SimTime{7}, EventKind::Barrier, NoRefusal, CoreId{0}, 2);
    q.schedule(SimTime{7}, EventKind::L2Fill, NoRefusal, CoreId{0}, 3);
    CHECK_TRUE(q.pop_min().kind == EventKind::L2Fill);
    CHECK_TRUE(q.pop_min().kind == EventKind::Barrier);
    CHECK_TRUE(q.pop_min().kind == EventKind::L2Probe);
    CHECK_TRUE(q.pop_min().kind == EventKind::Issue);
    CHECK_TRUE(q.empty());
}

// ===========================================================================
// The key, field by field
// ===========================================================================

void test_each_field_dominates_the_ones_after_it() {
    check::group("B2: the key's five fields, in priority order");

    // Four cases, one per boundary in the key. In each, the field under test
    // says A < B while EVERY later field says the opposite, so a comparison
    // that dropped this field or reordered it against a later one answers B.
    // That is the shape that catches a reordered chain, which a set of
    // one-field-at-a-time cases cannot.

    // time beats everything after it.
    const EventKey a1 = key_of(1, EventClass::Issue, 9, 9, 9);
    const EventKey b1 = key_of(2, EventClass::Fill, 0, 0, 0);
    CHECK_TRUE(key_less(a1, b1));
    CHECK_TRUE(!key_less(b1, a1));

    // class beats age, core and seq.
    const EventKey a2 = key_of(5, EventClass::Fill, 9, 9, 9);
    const EventKey b2 = key_of(5, EventClass::Issue, 0, 0, 0);
    CHECK_TRUE(key_less(a2, b2));
    CHECK_TRUE(!key_less(b2, a2));

    // age beats core and seq.
    const EventKey a3 = key_of(5, EventClass::Probe, 1, 9, 9);
    const EventKey b3 = key_of(5, EventClass::Probe, 2, 0, 0);
    CHECK_TRUE(key_less(a3, b3));
    CHECK_TRUE(!key_less(b3, a3));

    // core beats seq.
    const EventKey a4 = key_of(5, EventClass::Probe, 3, 1, 9);
    const EventKey b4 = key_of(5, EventClass::Probe, 3, 2, 0);
    CHECK_TRUE(key_less(a4, b4));
    CHECK_TRUE(!key_less(b4, a4));

    // seq is the last discriminator, and the only thing separating these two.
    const EventKey a5 = key_of(5, EventClass::Probe, 3, 3, 1);
    const EventKey b5 = key_of(5, EventClass::Probe, 3, 3, 2);
    CHECK_TRUE(key_less(a5, b5));
    CHECK_TRUE(!key_less(b5, a5));

    // The refusal stamp's own collapse (3.8): NoRefusal is INT64_MAX, so a
    // FRESH event sorts after every refused one under plain `<` and the refused
    // bit is not a second field that could disagree with the counter. This is
    // the one field whose sentinel does real work.
    const EventKey refused = key_of(5, EventClass::Probe, 9223372036854775806LL, 9, 9);
    const EventKey fresh   = EventKey{SimTime{5}, EventClass::Probe, NoRefusal, CoreId{0},
                                      EventSeq{0}};
    CHECK_TRUE(key_less(refused, fresh));
    CHECK_TRUE(!key_less(fresh, refused));
}

void test_key_less_agrees_with_the_plan_written_out() {
    check::group("B2: key_less against the independent oracle");

    // Every ordered pair over a generated key set, compared against the oracle
    // written from 3.6 rather than from the code. The set is built so that
    // every field is a live discriminator somewhere: times and classes repeat
    // heavily so that ties reach the later fields at all, which is the trap
    // 4.3 names in a different context (a test that passes vacuously because
    // the interesting path is never reached).
    std::vector<EventKey> keys;
    std::int64_t seq = 0;
    for (std::int64_t t = 0; t < 3; ++t) {
        for (int c = 0; c < 4; ++c) {
            for (std::int64_t age : {0, 1, 2}) {
                for (std::int32_t core : {0, 1}) {
                    keys.push_back(key_of(t, static_cast<EventClass>(c), age, core, seq++));
                }
            }
        }
    }
    CHECK_EQ(check::ssize(keys), 72);

    int disagreements = 0;
    for (const EventKey& a : keys) {
        for (const EventKey& b : keys) {
            if (key_less(a, b) != oracle_earlier(a, b)) ++disagreements;
        }
    }
    CHECK_EQ(disagreements, 0);
}

void test_no_two_distinct_keys_compare_equal() {
    check::group("B2: the order is TOTAL, not merely consistent");

    // D11 asks for a total order, and this is what that means: for any two
    // keys with different seqs, exactly one of the two comparisons holds. A
    // merely consistent order would leave ties for the container to break, and
    // std::priority_queue's arrangement is unspecified, so a tie is where a
    // re-run stops being byte-identical.
    //
    // The set below is deliberately degenerate: every key shares one time, one
    // class, one age and one core, so `seq` is the ONLY thing left. If seq were
    // dropped from the comparison these are all equivalent and every pair
    // fails.
    std::vector<EventKey> keys;
    for (std::int64_t s = 0; s < 40; ++s) keys.push_back(key_of(5, EventClass::Probe, 7, 3, s));

    int equal_pairs = 0;
    int both_ways   = 0;
    for (std::size_t i = 0; i < keys.size(); ++i) {
        for (std::size_t j = 0; j < keys.size(); ++j) {
            if (i == j) continue;
            const bool ab = key_less(keys[i], keys[j]);
            const bool ba = key_less(keys[j], keys[i]);
            if (!ab && !ba) ++equal_pairs;
            if (ab && ba) ++both_ways;
        }
    }
    CHECK_EQ(equal_pairs, 0);
    CHECK_EQ(both_ways, 0);

    // Irreflexive, which a strict weak ordering owes and which `<=` in any one
    // field would break.
    int reflexive = 0;
    for (const EventKey& k : keys)
        if (key_less(k, k)) ++reflexive;
    CHECK_EQ(reflexive, 0);

    // And transitive, over the mixed set rather than the degenerate one. A
    // comparison chain that compared a later field before an earlier one can be
    // antisymmetric and still not transitive, so this is not implied by the
    // checks above.
    std::vector<EventKey> mixed;
    std::int64_t seq = 0;
    for (std::int64_t t = 0; t < 2; ++t)
        for (int c = 0; c < 3; ++c)
            for (std::int64_t age : {0, 1})
                for (std::int32_t core : {0, 1}) mixed.push_back(
                    key_of(t, static_cast<EventClass>(c), age, core, seq++));

    int intransitive = 0;
    for (const EventKey& a : mixed)
        for (const EventKey& b : mixed)
            for (const EventKey& c : mixed)
                if (key_less(a, b) && key_less(b, c) && !key_less(a, c)) ++intransitive;
    CHECK_EQ(intransitive, 0);
}

// ===========================================================================
// The heap pops in key order
// ===========================================================================

void test_the_heap_pops_in_key_order() {
    check::group("B2: pop order == sorted order, against the oracle");

    // The container's arrangement is unobservable only if what comes out is the
    // key order and nothing else. So: schedule a large deterministic set, sort
    // a copy of the keys with the INDEPENDENT oracle, and require the pop
    // sequence to be that sorted sequence exactly.
    //
    // This is the single strongest check in the file. It subsumes the field
    // priority cases above as a property rather than as five examples, and it
    // is what a reversed comparator, a dropped field, or a max-heap all die on.
    EventQueue<std::int64_t> q;
    std::vector<EventKey> expected;

    const int n = 4000;
    for (int i = 0; i < n; ++i) {
        const std::int64_t r    = mix(i);
        const std::int64_t time = (r >> 3) % 50;         // heavy collision on time
        const EventKind kind    = static_cast<EventKind>((r >> 11) % 6);
        const std::int64_t age  = (r >> 17) % 4;         // and on the refusal stamp
        const std::int32_t core = static_cast<std::int32_t>((r >> 23) % 3);
        q.schedule(SimTime{time}, kind, RefusalOrder{age}, CoreId{core}, static_cast<std::int64_t>(i));
        expected.push_back(key_of(time, class_of(kind), age, core, static_cast<std::int64_t>(i)));
    }
    CHECK_EQ(check::ssize(q), static_cast<std::int64_t>(n));

    std::sort(expected.begin(), expected.end(), oracle_earlier);

    int mismatches = 0;
    std::int64_t previous_time = -1;
    for (int i = 0; i < n; ++i) {
        const Event<std::int64_t> e = q.pop_min();
        const EventKey& w = expected[static_cast<std::size_t>(i)];
        if (!(e.key.time == w.time) || e.key.cls != w.cls || !(e.key.age == w.age) ||
            !(e.key.core == w.core) || !(e.key.seq == w.seq)) {
            ++mismatches;
        }
        // P1: `now` is non-decreasing because this is a min-heap, and the
        // engine has no clock of its own to fall back on.
        if (e.key.time.get() < previous_time) ++mismatches;
        previous_time = e.key.time.get();
    }
    CHECK_EQ(mismatches, 0);
    CHECK_TRUE(q.empty());

    // Every one of the four classes and several distinct times were actually
    // present, so the run above is not passing because the interesting ties
    // never occurred. The vacuity guard 4.3 asks for, applied to this fixture.
    int class_seen[4] = {0, 0, 0, 0};
    for (const EventKey& k : expected) ++class_seen[static_cast<int>(k.cls)];
    for (int c = 0; c < 4; ++c) CHECK_TRUE(class_seen[c] > 0);
}

// ===========================================================================
// Two identical runs produce identical event logs
// ===========================================================================

// One line of the log. Every field of the key plus the kind and the payload,
// because "identical event log" means identical in all of them: a queue that
// ordered correctly but handed back the wrong payload would produce a run that
// is reproducible and wrong.
struct LogLine {
    std::int64_t time;
    int          cls;
    std::int64_t age;
    std::int32_t core;
    std::int64_t seq;
    int          kind;
    std::int64_t payload;
};

bool operator==(const LogLine& a, const LogLine& b) {
    return a.time == b.time && a.cls == b.cls && a.age == b.age && a.core == b.core &&
           a.seq == b.seq && a.kind == b.kind && a.payload == b.payload;
}

// A closed loop: what is popped decides what is scheduled next, so the queue's
// own answers feed back into its input. A replay of a fixed schedule would
// exercise no ordering decision at all and would be reproducible whatever the
// comparator did.
//
// The shape is deliberately the engine's (3.2): pop, take `now` from the event,
// dispatch, and the dispatch schedules more events at `now` or later. Chains
// that stay inside one timestamp are the ORDINARY case at the 2.5b defaults,
// where `l1_latency` and `l2_to_l1_latency` are both 0, so the loop below
// schedules at `now` as well as ahead of it.
std::vector<LogLine> run_scenario(int steps) {
    EventQueue<std::int64_t> q;
    std::vector<LogLine> log;

    for (std::int64_t c = 0; c < 4; ++c) {
        q.schedule(SimTime{c}, EventKind::Issue, NoRefusal, CoreId{static_cast<std::int32_t>(c)}, c);
    }

    int dispatched = 0;
    while (!q.empty() && dispatched < steps) {
        const Event<std::int64_t> e = q.pop_min();
        ++dispatched;
        log.push_back(LogLine{e.key.time.get(), static_cast<int>(e.key.cls), e.key.age.get(),
                              e.key.core.get(), e.key.seq.get(), static_cast<int>(e.kind),
                              e.payload});

        const std::int64_t now = e.key.time.get();
        const std::int64_t r   = mix(e.payload * 7919 + now * 31 + e.key.seq.get());

        // Fan-out of 1 or 2 while the queue is below its cap and 0 above it, so
        // the population settles around a few hundred rather than dying out or
        // growing without bound. Both failure modes cost the fixture its point:
        // a queue that empties stops producing same-timestamp collisions, which
        // are the only place an ordering can be observed, and the depth is what
        // the heap's sift-down path lives in.
        const int fanout = check::ssize(q) > 400 ? 0 : 1 + static_cast<int>(r % 2);
        for (int f = 0; f < fanout; ++f) {
            const std::int64_t s = mix(r + f);
            // Zero-delay legs are legal and must not form a cycle within one
            // timestamp (2.5b), so a same-tick follow-up is scheduled only from
            // a probe and only into a fill, which is exactly the L1-hit chain
            // that terminates.
            const bool same_tick = (e.kind == EventKind::L1Probe || e.kind == EventKind::L2Probe) &&
                                   (s % 4 == 0);
            const std::int64_t delta = same_tick ? 0 : 1 + (s >> 5) % 9;
            const EventKind kind     = same_tick ? EventKind::L1Fill
                                                 : static_cast<EventKind>((s >> 13) % 6);
            // A refusal stamp on some events and none on others, which is what
            // makes the third field of the key a live discriminator here.
            const RefusalOrder age =
                (s >> 21) % 3 == 0 ? NoRefusal : RefusalOrder{(s >> 27) % 6};
            q.schedule(SimTime{now + delta}, kind, age,
                       CoreId{static_cast<std::int32_t>((s >> 33) % 4)}, s % 100000);
        }
    }
    return log;
}

void test_two_identical_runs_produce_identical_logs() {
    check::group("B2: two identical runs, identical event logs");

    const std::vector<LogLine> first  = run_scenario(6000);
    const std::vector<LogLine> second = run_scenario(6000);

    // The scenario must actually have run, or "identical" is a statement about
    // two empty vectors.
    CHECK_EQ(check::ssize(first), 6000);
    CHECK_EQ(check::ssize(second), 6000);

    int differing = 0;
    for (std::size_t i = 0; i < first.size(); ++i)
        if (!(first[i] == second[i])) ++differing;
    CHECK_EQ(differing, 0);

    // And the log is not degenerate: it must contain same-timestamp batches
    // where more than one class is present, since those are the only places the
    // ordering can be observed at all. Without this guard a scenario whose
    // events never collide would report a clean "identical" while proving
    // nothing about the tie-break.
    int ties_across_classes = 0;
    for (std::size_t i = 1; i < first.size(); ++i)
        if (first[i].time == first[i - 1].time && first[i].cls != first[i - 1].cls)
            ++ties_across_classes;
    CHECK_TRUE(ties_across_classes > 100);

    // Every class and every kind actually appeared, so no branch of the key was
    // dead in this fixture.
    int kinds[6] = {0, 0, 0, 0, 0, 0};
    int classes[4] = {0, 0, 0, 0};
    for (const LogLine& l : first) {
        ++kinds[l.kind];
        ++classes[l.cls];
    }
    for (int k = 0; k < 6; ++k) CHECK_TRUE(kinds[k] > 0);
    for (int c = 0; c < 4; ++c) CHECK_TRUE(classes[c] > 0);
}

void test_two_queues_alive_at_once_do_not_share_a_counter() {
    check::group("B2: the seq counter belongs to the queue");

    // The determinism above would still hold with a PROCESS-wide seq counter,
    // because two runs one after another would each start from a different
    // value only if the counter were never reset -- and a global counter is not
    // reset. So it is checked directly instead: a second queue starts its seq
    // at 0, and two queues stepped alternately do not interleave their
    // counters. The engine holds one queue, but a sweep driver (D3) runs many
    // configurations in one process, and a shared counter would make grid point
    // N's event log depend on grid point N-1.
    EventQueue<int> a;
    EventQueue<int> b;
    a.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 1);
    b.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 2);
    a.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 3);
    b.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 4);

    CHECK_EQ(a.pop_min().key.seq, EventSeq{0});
    CHECK_EQ(b.pop_min().key.seq, EventSeq{0});
    CHECK_EQ(a.pop_min().key.seq, EventSeq{1});
    CHECK_EQ(b.pop_min().key.seq, EventSeq{1});
    CHECK_EQ(a.scheduled(), 2);
    CHECK_EQ(b.scheduled(), 2);
}

// ===========================================================================
// schedule and pop_min
// ===========================================================================

void test_schedule_assigns_the_seq_itself() {
    check::group("B2: schedule owns the seq and the class");

    // 3.6's "assigned at SCHEDULE time" made unrepresentable rather than
    // promised: the caller cannot supply a seq, so two events cannot be given
    // the same one and the order cannot stop being total exactly where a tie
    // needs breaking. compile_fail.sh's `tryEvent` cases carry the negative
    // half (no overload takes a seq or a class).
    EventQueue<int> q;
    CHECK_EQ(q.scheduled(), 0);
    for (int i = 0; i < 5; ++i) {
        q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, i);
        CHECK_EQ(q.scheduled(), static_cast<std::int64_t>(i + 1));
    }
    // Within one timestamp, one class, one age and one core, the seq is the
    // only discriminator left, so pop order IS schedule order and the payloads
    // come back 0..4.
    for (int i = 0; i < 5; ++i) {
        const Event<int> e = q.pop_min();
        CHECK_EQ(e.key.seq, EventSeq{i});
        CHECK_EQ(e.payload, i);
    }

    // The counter is never reset, so a seq is unique across the whole run and
    // not merely within one tile. Popping does not give one back.
    EventQueue<int> r;
    r.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    (void)r.pop_min();
    r.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    CHECK_EQ(r.pop_min().key.seq, EventSeq{1});
    CHECK_EQ(r.scheduled(), 2);

    // The class is derived from the kind rather than passed, so a handler
    // cannot schedule a fill under the probe class. That is the mutation which
    // would reverse V23's worked example and report a plausible, wrong,
    // reproducible answer.
    EventQueue<int> s;
    s.schedule(SimTime{3}, EventKind::L2Fill, NoRefusal, CoreId{0}, 0);
    CHECK_TRUE(s.pop_min().key.cls == EventClass::Fill);
}

void test_scheduling_behind_now_is_refused() {
    check::group("B2: P1, nothing is scheduled into the past");

    EventQueue<int> q;
    q.schedule(SimTime{10}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    CHECK_EQ(q.now(), SimTime{0});
    (void)q.pop_min();
    CHECK_EQ(q.now(), SimTime{10});

    // Scheduling AT `now` is legal and ordinary: at the 2.5b defaults whole
    // chains run inside one timestamp, so a rule of `> now` rather than
    // `>= now` would make the default configuration unrunnable.
    q.schedule(SimTime{10}, EventKind::L1Fill, NoRefusal, CoreId{0}, 1);
    CHECK_EQ(check::ssize(q), 1);

    // Behind `now` is P1 violated: a min-heap makes `now` non-decreasing only
    // if nothing is inserted into the past, and such an event would be
    // dispatched immediately and out of order rather than at the time it names.
    const std::string behind = logic_thrown_by(
        [&q] { q.schedule(SimTime{9}, EventKind::L1Fill, NoRefusal, CoreId{0}, 2); });
    expect_message("scheduling behind now", behind, "EventQueue::schedule", {"9", "10"});

    // And it threw before touching the queue, so a caught throw leaves a
    // consistent queue rather than a half-inserted one.
    CHECK_EQ(check::ssize(q), 1);
    CHECK_EQ(q.scheduled(), 2);
}

void test_popping_an_empty_queue_is_refused() {
    check::group("B2: an empty queue is the loop's termination condition");

    EventQueue<int> q;
    CHECK_TRUE(q.empty());
    CHECK_EQ(check::ssize(q), 0);

    // 3.2's loop stops on `empty()`, so reaching this call with nothing in the
    // queue is the loop having been written wrong rather than a run that ended.
    const std::string drained = logic_thrown_by([&q] { return q.pop_min(); });
    expect_message("popping an empty queue", drained, "EventQueue::pop_min", {"empty"});

    q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    CHECK_TRUE(!q.empty());
    (void)q.pop_min();
    CHECK_TRUE(q.empty());
    const std::string again = logic_thrown_by([&q] { return q.pop_min(); });
    expect_message("popping a drained queue", again, "EventQueue::pop_min", {"empty"});
}

void test_the_payload_is_carried_unchanged() {
    check::group("B2: the payload is a parameter and is not inspected");

    // `Payload` is a template parameter because at B2 the hierarchy does not
    // exist: what an event is about is C2's and C3's to define. The ordering,
    // which is all this unit owns, does not depend on the payload at all, so
    // the queue must carry a non-trivial one through untouched.
    struct Thing {
        std::int64_t line;
        bool         demand;
    };
    EventQueue<Thing> q;
    q.schedule(SimTime{4}, EventKind::L1Probe, RefusalOrder{2}, CoreId{1}, Thing{99, false});
    q.schedule(SimTime{4}, EventKind::L1Probe, RefusalOrder{1}, CoreId{1}, Thing{7, true});

    const Event<Thing> first = q.pop_min();
    CHECK_EQ(first.payload.line, 7);          // the older stamp comes out first
    CHECK_TRUE(first.payload.demand);
    const Event<Thing> second = q.pop_min();
    CHECK_EQ(second.payload.line, 99);
    CHECK_TRUE(!second.payload.demand);
}

void test_now_tracks_the_last_pop() {
    check::group("B2: now() is the timestamp of the event being dispatched");

    // P1: the engine has no tick and no current cycle of its own. `now` is held
    // by the queue so the monotonicity rule has something to check against, and
    // it is zero before the first pop, which is tile_origin[0].
    EventQueue<int> q;
    CHECK_EQ(q.now(), SimTime{0});
    for (std::int64_t t : {0, 0, 3, 3, 12, 40}) {
        q.schedule(SimTime{t}, EventKind::Issue, NoRefusal, CoreId{0}, 0);
    }
    std::int64_t previous = -1;
    while (!q.empty()) {
        const Event<int> e = q.pop_min();
        CHECK_EQ(q.now(), e.key.time);
        CHECK_TRUE(q.now().get() >= previous);
        previous = q.now().get();
    }
    CHECK_EQ(q.now(), SimTime{40});
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// 3.6's class order IS the enumerator order, and the numeric values are the
// plan's own. If they are ever renumbered, the oracle in this file (which casts
// to int) and the production comparator (which compares the enum) would both
// move together and agree while both were wrong, so the values are pinned here.
static_assert(static_cast<int>(EventClass::Fill) == 0, "");
static_assert(static_cast<int>(EventClass::Barrier) == 1, "");
static_assert(static_cast<int>(EventClass::Probe) == 2, "");
static_assert(static_cast<int>(EventClass::Issue) == 3, "");
static_assert(EventClass::Fill < EventClass::Barrier, "");
static_assert(EventClass::Barrier < EventClass::Probe, "");
static_assert(EventClass::Probe < EventClass::Issue, "");

// Both enums are scoped and one byte wide: they are vocabulary, not arithmetic,
// and neither decays to an int at a call site.
static_assert(std::is_same<std::underlying_type<EventClass>::type, std::uint8_t>::value, "");
static_assert(std::is_same<std::underlying_type<EventKind>::type, std::uint8_t>::value, "");
static_assert(!std::is_convertible<EventKind, int>::value, "");
static_assert(!std::is_convertible<EventClass, int>::value, "");

// class_of is usable in a constant expression, which is what lets a static
// dispatch table be built from it later without the mapping being written a
// second time.
static_assert(class_of(EventKind::L1Fill) == EventClass::Fill, "");
static_assert(class_of(EventKind::Issue) == EventClass::Issue, "");

// The key's five fields, in the plan's order and with the plan's types. The
// third and the fifth are the pair worth pinning: a RefusalOrder and an
// EventSeq are both monotonic int64 counters sitting in one key, and an
// implementation that compared them in the wrong order would produce a
// plausible, wrong, perfectly reproducible event order.
static_assert(std::is_same<decltype(EventKey::time), SimTime>::value, "");
static_assert(std::is_same<decltype(EventKey::cls), EventClass>::value, "");
static_assert(std::is_same<decltype(EventKey::age), RefusalOrder>::value, "");
static_assert(std::is_same<decltype(EventKey::core), CoreId>::value, "");
static_assert(std::is_same<decltype(EventKey::seq), EventSeq>::value, "");

// The queue's readers are const, so a stats pass can size the queue without
// changing it.
static_assert(std::is_same<decltype(&EventQueue<int>::empty), bool (EventQueue<int>::*)() const>::value, "");
static_assert(std::is_same<decltype(&EventQueue<int>::now), SimTime (EventQueue<int>::*)() const>::value, "");
static_assert(std::is_same<decltype(&EventQueue<int>::scheduled),
                           std::int64_t (EventQueue<int>::*)() const>::value, "");

// And `schedule` takes exactly the five things a caller owns: no seq, no class.
static_assert(std::is_same<decltype(&EventQueue<int>::schedule),
                           void (EventQueue<int>::*)(SimTime, EventKind, RefusalOrder, CoreId,
                                                     int)>::value, "");

}  // namespace

int main() {
    test_class_of_maps_every_kind();
    test_the_class_order_decides_a_same_cycle_tie();
    test_each_field_dominates_the_ones_after_it();
    test_key_less_agrees_with_the_plan_written_out();
    test_no_two_distinct_keys_compare_equal();
    test_the_heap_pops_in_key_order();
    test_two_identical_runs_produce_identical_logs();
    test_two_queues_alive_at_once_do_not_share_a_counter();
    test_schedule_assigns_the_seq_itself();
    test_scheduling_behind_now_is_refused();
    test_popping_an_empty_queue_is_refused();
    test_the_payload_is_carried_unchanged();
    test_now_tracks_the_last_pop();
    return check::summary();
}
