#include "wcache/port.h"

#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// One spelling of the prefix, so every message this file produces is findable by
// grepping for the class name and no two of them disagree about the
// punctuation. block_pack.cpp sets the convention.
[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("Port: " + what);
}

// One spelling of the non-negativity rule, for the same reason: the two cases
// below differ only in which quantity they name. The value is always printed,
// because a 0 from a config field nobody set and a negative from one decoded
// wrong look nothing alike in a log.
//
// `>= 0` and not `>= 1`: a zero `ii` is N13's escape hatch and a zero `latency`
// is the default for both `l1_latency` and `l2_to_l1_latency` (2.5b), so the
// only thing either field can be wrong by is sign.
void non_negative_or_reject(const char* name, SimTime v) {
    if (v.get() < 0) {
        reject(std::string(name) + " must be >= 0, got " + std::to_string(v.get()));
    }
}

}  // namespace

Port::Port(SimTime ii, SimTime latency) : ii_(ii), latency_(latency) {
    non_negative_or_reject("ii", ii);
    non_negative_or_reject("latency", latency);
}

// The whole of occupancy, in three lines.
//
// At `ii = 0` the port never delays: `next_accept` is assigned the accept time
// unchanged, so every later offer at the same or a later cycle is accepted at
// its own `now`. That is the unbounded baseline, and it is reached by
// configuration rather than by a branch, which is what keeps the baseline and
// the bounded runs on one code path (D8's lesson).
//
// At `ii = latency` the port serializes: a request offered at 0 is accepted at
// 0 and completes at `latency`, and the next is accepted at `latency` and
// completes at `2 * latency`. One round trip at a time, which is 2.4's
// non-pipelined channel recovered from the same structure.
//
// Written as a compare rather than as a max() so the two directions read
// separately: a port that is already free hands back `now`, and a busy one
// hands back its own next-free stamp. Nothing here predicts anything (P2): the
// answer is a fact about a timestamp this port already holds.
SimTime Port::reserve(SimTime now) {
    const SimTime accept = (now < next_accept_) ? next_accept_ : now;
    next_accept_ = accept + ii_;
    return accept;
}

}  // namespace wcache
