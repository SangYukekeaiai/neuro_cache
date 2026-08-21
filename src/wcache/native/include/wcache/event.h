// EventQueue: the min-heap the engine loop pops, and the total order it pops in.
//
// Plan v3 Part 7, unit B2: "`EventQueue`: min-heap on `(time, class,
// effective_age, core_id, seq)` (N10)", whose exit criterion is a total order
// and two identical runs producing identical event logs.
//
// This is the whole of P1: "time is carried by events, never by a loop". The
// engine has no tick and no current cycle of its own; `now` is the timestamp of
// the event being dispatched, and it is monotonically non-decreasing because
// this is a min-heap. 3.2's loop is
//
//     while (!queue.empty()) { e = queue.pop_min(); now = e.time; dispatch(e); }
//
// and there is nothing else: no horizon, no scan over cores, and no condition
// re-evaluated on a schedule.
//
// The ordering is not cosmetic. Under LRU the order in which two hits to one set
// are serviced IS the recency stack (D7), so a single flipped tie leaves a
// different victim, a later fill evicts a different line, and every access after
// it diverges. A run is therefore either bit-identical or arbitrarily different,
// which is why D11 asks for a TOTAL order rather than a stable one.
#pragma once

#include <cstddef>
#include <cstdint>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>

#include "wcache/types.h"

namespace wcache {

// 3.6's four classes, which break ties between event kinds at one cycle. The
// values are the plan's own and the order of the enumerators is the order of
// the key, so `<` on this enum is the comparison the key needs.
//
// Zero-latency legs make this the ordinary case rather than a corner: at the
// 2.5b defaults both `l1_latency` and `l2_to_l1_latency` are 0, so an L1 hit
// issues, probes and serves the core all at one tick and `E_L2Probe` schedules
// `E_L1Fill` at its own timestamp.
enum class EventClass : std::uint8_t {
    // State changes land before anything looks at state. A core is served
    // inside its last demand fill (3.4b), so services inherit this class and
    // land ahead of the barrier.
    Fill = 0,

    // The barrier observes completed fills, and therefore completed services.
    // One class later than Fill so a core's last service of a tile is counted
    // before `tile_origin[N+1]` is set from it (V26).
    Barrier = 1,

    // Lookups see this cycle's fills, which is what closes D4's "a queued miss
    // became a hit". It is also the live test of 4.6's worked example: a
    // prefetch fill and a demand probe both land at cycle 111, and only Fill
    // before Probe makes that a hit rather than a second fetch (V23).
    Probe = 2,

    // New demand enters last.
    Issue = 3,
};

// 3.1's alphabet. Six kinds, unchanged in number by v3: a prefetched burst
// travels the same chain as any other request carrying `demand = false`, and
// service is a call inside `E_L1Fill` rather than an event of its own, which is
// what gives it class 0 automatically.
enum class EventKind : std::uint8_t {
    Issue    = 0,  // burst k becomes due at the core (4.5)
    L1Probe  = 1,  // the L1 port accepted this request, l1_latency later
    L2Probe  = 2,  // the L2 bank port accepted it, l2_latency later
    L2Fill   = 3,  // the memory channel returns data
    L1Fill   = 4,  // data reaches the L1
    Barrier  = 5,  // the last core clears a tile
};

// 3.6's table, as code. It lives here rather than at the seven scheduling sites
// so that the mapping from a boundary crossing to its tie-break class is
// written once: a handler that scheduled a fill under the probe class would
// reverse V23's worked example and report a plausible, wrong, reproducible
// answer.
constexpr EventClass class_of(EventKind kind) {
    switch (kind) {
        case EventKind::L2Fill:
        case EventKind::L1Fill:  return EventClass::Fill;
        case EventKind::Barrier: return EventClass::Barrier;
        case EventKind::L1Probe:
        case EventKind::L2Probe: return EventClass::Probe;
        case EventKind::Issue:   return EventClass::Issue;
    }
    // Unreachable: the switch covers every enumerator. Reported rather than
    // given a fallback class, which is the one wrong answer here: a kind
    // silently dispatched at class 0 would reorder the run against itself and
    // the result would still look like a result. types.h's Axis accessors
    // refuse the same way for the same reason.
    throw std::logic_error("class_of: unknown EventKind");
}

// N10's key. Five fields, in the plan's order.
//
// `age` is the subject's refusal stamp, or NoRefusal when it has never been
// refused. That single field is the whole of 3.8's `(refused_bit, refusal)`
// key, because NoRefusal is INT64_MAX (B3): a fresh request sorts after every
// refused one under plain `<`, so the refused bit is not carried as a second
// field that could disagree with the counter.
//
// For class 2 the last three fields collapse (3.8): no two waiters can tie on
// the counter, so `core` and `seq` are dead there. They are kept because the
// other three classes have no refusal stamp at all, and something has to make
// the order total.
struct EventKey {
    SimTime      time;
    EventClass   cls;
    RefusalOrder age;
    CoreId       core;
    EventSeq     seq;
};

// Strictly earlier in the total order. Field by field, in the key's order.
//
// It is a total order and not merely a consistent one, and that is the property
// D11 asks for: `seq` is unique across the run, so no two keys compare equal
// and no tie is ever left to the container. That is what makes the heap's
// internal arrangement unobservable and a re-run byte-identical.
constexpr bool key_less(const EventKey& a, const EventKey& b) {
    if (!(a.time == b.time)) return a.time < b.time;
    if (a.cls != b.cls)      return a.cls < b.cls;
    if (!(a.age == b.age))   return a.age < b.age;
    if (!(a.core == b.core)) return a.core < b.core;
    return a.seq < b.seq;
}

// One scheduled event: its key, what it is, and what it is about.
//
// `Payload` is a parameter because at B2 the hierarchy does not exist: what an
// event is about is a Request, an Mshr entry, a core or a tile, and every one
// of those is C2's or C3's to define. Naming a concrete payload here would be
// this unit deciding a later one's storage, and an opaque integer handle would
// be the same decision wearing a disguise. The ordering, which is all this unit
// owns, does not depend on the payload at all.
template <typename Payload>
struct Event {
    EventKey  key;
    EventKind kind;
    Payload   payload;
};

// The min-heap of 3.2.
//
// std::priority_queue is a max-heap, so the comparator below is deliberately
// reversed rather than the key being: `key_less` stays the plain "earlier
// than" every other reader of this file expects, and the one inversion lives at
// the single point where the container demands it.
template <typename Payload>
class EventQueue {
public:
    // Schedules an event at `time`, assigning its `seq` from this queue's own
    // counter.
    //
    // The caller cannot supply a `seq`, which is 3.6's "assigned at SCHEDULE
    // time" made unrepresentable rather than promised: two events could
    // otherwise be given the same one, and the order would stop being total
    // exactly where a tie needs breaking. For the same reason the class is
    // derived from the kind through class_of rather than passed.
    //
    // Throws std::logic_error when `time` is earlier than the last popped
    // event's, because that is P1 violated: a min-heap makes `now`
    // non-decreasing only if nothing is inserted into the past, and an event
    // scheduled behind `now` would be dispatched immediately and out of order
    // rather than at the time it names. Scheduling AT `now` is legal and
    // ordinary, since 2.5b's defaults make whole chains run inside one
    // timestamp. logic_error rather than invalid_argument because no config
    // value produces it: it is an engine that computed a time, which B27 puts
    // in the programmer-error tier. A throw and not an assert, because the
    // sweep build is -DNDEBUG and a silently reordered run still produces
    // numbers.
    void schedule(SimTime time, EventKind kind, RefusalOrder age, CoreId core, Payload payload) {
        if (time < now_) {
            throw std::logic_error("EventQueue::schedule: time " + std::to_string(time.get()) +
                                   " is behind now " + std::to_string(now_.get()));
        }
        q_.push(Event<Payload>{EventKey{time, class_of(kind), age, core, EventSeq{next_seq_}},
                               kind, payload});
        ++next_seq_;
    }

    // The earliest event in the total order, removed from the queue, and the
    // event whose timestamp becomes `now`.
    //
    // Throws std::logic_error on an empty queue. An empty queue is the engine
    // loop's termination condition (3.2), so reaching this call with nothing in
    // it is the loop having been written wrong rather than a run that ended.
    Event<Payload> pop_min() {
        if (q_.empty()) throw std::logic_error("EventQueue::pop_min: the queue is empty");
        Event<Payload> e = q_.top();
        q_.pop();
        now_ = e.key.time;
        return e;
    }

    // The same event `pop_min` would return, left in the queue and without
    // moving `now`.
    //
    // This is what lets a driver decide whether to dispatch the next event
    // before it has committed to dispatching it, which is how a run is paused at
    // a chosen kind of event rather than at a chosen time. `now` deliberately
    // stays put: a peeked event has not happened.
    //
    // Throws std::logic_error on an empty queue, for pop_min's reason.
    const Event<Payload>& peek_min() const {
        if (q_.empty()) throw std::logic_error("EventQueue::peek_min: the queue is empty");
        return q_.top();
    }

    bool empty() const { return q_.empty(); }
    std::size_t size() const { return q_.size(); }

    // The timestamp of the last popped event: P1's `now`, held here rather than
    // in a variable of the engine loop so that the monotonicity rule above has
    // something to check against. Zero before the first pop, which is
    // tile_origin[0] and therefore the earliest time anything can be scheduled
    // at anyway.
    SimTime now() const { return now_; }

    // How many events this queue has ever been given. Part 8 reports the event
    // count and events per simulated cycle, which is the measured form of the
    // cost win over the tick model rather than the claimed one. It is the seq
    // counter, which already exists, so reporting it costs nothing.
    std::int64_t scheduled() const { return next_seq_; }

private:
    struct Later {
        bool operator()(const Event<Payload>& a, const Event<Payload>& b) const {
            return key_less(b.key, a.key);
        }
    };

    std::priority_queue<Event<Payload>, std::vector<Event<Payload>>, Later> q_;

    // Never reset, so a seq is unique across the whole run and not merely
    // within one tile. int64 for the refusal counter's reason (Q8): a full
    // trace at 256 cores schedules more than 2^31 events, and a wrapped
    // counter would silently reorder the queue.
    std::int64_t next_seq_ = 0;

    SimTime now_{0};
};

}  // namespace wcache
