// Port: a shared resource that accepts one request every `ii` cycles.
//
// Plan v3 Part 3.3: `Port { ii, latency, next_accept }`, instantiated as
// `l1_port[c]`, `l2_bank[b]` and `dram`. One class covers all three; they
// differ only in the two numbers they are constructed with (2.2, 2.3, 2.4).
//
// This is P3 made literal: "contention is occupancy, not quota. A shared
// resource is a next-free timestamp, not a per-window counter." A quota port
// would need a window, a window needs a periodic reset, and a periodic reset is
// the tick loop D1 exists to remove. There is no window here, so there is no
// window artifact: sixteen requests at `ii = 2` land at t, t+2, ... t+30 rather
// than all at one stamp with a cliff at the window edge.
//
// It is also why 3.1 has no `E_PortFree` event. A port never refuses and never
// schedules a wake-up: `reserve` always returns, immediately, with the time this
// port can take the request. Nothing registers on a port and nothing waits on
// one, which is what keeps P2's "subscribe, never predict" a statement about
// MSHRs alone.
//
// Two quantities, deliberately separate (2.4). `ii` is the initiation interval,
// the reciprocal of throughput; `latency` is the delay a single request sees.
// A channel with 100 cycles of latency and an `ii` of 2 has 50 requests in
// flight and is a completely different machine from one that serializes 100
// cycle round trips, and `ii = latency` recovers the second from the first.
#pragma once

#include "wcache/types.h"

namespace wcache {

// Reservations are non-preemptive and are never released (4.3): a request that
// has been given an accept time keeps it, so `reserve` order is service order
// and is never revisited. That is what makes I7b ("port reservation order ==
// key order at every retire") a property the merge-and-sort of 3.4 can be held
// to, and it is also why it is only testable at `ii >= 1` (N13): at `ii = 0`
// every reservation returns `now` and the ordering has nothing to express.
class Port {
public:
    // `ii` and `latency` are config fields (D1, plan 2.5b), so both rejections
    // are a `throw` rather than an `assert`: the sweep build is -DNDEBUG, and a
    // sweep grid is a cross product, so a combination nobody typed by hand
    // reaching this constructor is the expected case rather than the exotic one.
    //
    // `ii = 0` is ACCEPTED, and that is N13 rather than an oversight: it is the
    // modelling escape hatch meaning infinite throughput, which is what the
    // unbounded baseline (V1) is built from. It is not a setting a real port can
    // have, and a sweep over `ii` in {0, 1, 2} reads as three adjacent points
    // when 0 and 1 differ by unbounded parallelism, so N13 asks for a warning on
    // it. That warning is D1's and not this constructor's: it is one line per
    // config, while this constructor runs once per port per core and would emit
    // it up to `n_cores + l2_banks + 1` times for one typed value.
    //
    // Throws std::invalid_argument, naming the offending value, for a negative
    // `ii` or a negative `latency`. `ii` is checked first: it is the field N13
    // rules on and the one a sweep varies, so a grid point that is wrong in both
    // reports the interesting half.
    Port(SimTime ii, SimTime latency);

    // The cycle this port can accept a request offered at `now`, which is `now`
    // itself when the port is free and `next_accept` when it is not. Advances
    // `next_accept` by `ii`.
    //
    // Returns the ACCEPT time and not the completion time, so the caller adds
    // the latency itself, exactly as 3.4 spells it:
    //
    //     accept = l2_bank[bank_of(r.line)].reserve(now);
    //     schedule(E_L2Probe(r), accept + l2_latency);
    //
    // The two halves are separated because they cross different boundaries: the
    // accept time is when this port takes the request, and the latency is how
    // long the structure behind it takes to answer, which P4 makes a separate
    // event rather than a return value. Folding the latency in here would also
    // make `ii = latency` unexpressible, since one number would then be both.
    SimTime reserve(SimTime now);

    SimTime ii() const { return ii_; }

    // Read by every caller of `reserve`, which adds it to the accept time. It
    // lives on the port rather than beside each call site because it is the
    // same config field the port was built from, and two spellings of one
    // latency is one place for them to disagree.
    SimTime latency() const { return latency_; }

    // The next cycle this port is free. Exposed for V14, "port busy-cycles <=
    // elapsed cycles x port count", which needs the port's own state rather
    // than a count of calls, and for B20's reason besides: without it the
    // occupancy arithmetic is observable only through a sequence of `reserve`
    // calls, so an implementation that advanced `next_accept` by the wrong
    // amount and then compensated would look identical from outside.
    SimTime next_accept() const { return next_accept_; }

private:
    SimTime ii_;
    SimTime latency_;

    // The run starts at tile_origin[0] == 0 (Part 5), so a port that has never
    // been used is free at 0 and `reserve(SimTime{0})` accepts at 0. SimTime has
    // no default constructor (B2), which is why this is written out.
    SimTime next_accept_{0};
};

}  // namespace wcache
