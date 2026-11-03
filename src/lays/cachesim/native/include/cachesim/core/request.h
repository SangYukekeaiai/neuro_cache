// Request state and the small enums shared by the hierarchy and instruments.
#pragma once

#include <cstdint>

#include "cachesim/types.h"

namespace cachesim {

struct Mshr;

enum class Level : std::uint8_t { L1 = 0, L2 = 1 };
enum class WaitReason : std::uint8_t { None = 0, Slot = 1, Line = 2 };

enum class StallCause : std::uint8_t {
    None    = 0,
    L1Slot  = 1,
    L1Line  = 2,
    L1Port  = 3,
    L2Slot  = 4,
    L2Line  = 5,
    L2Port  = 6,
    Channel = 7,
    Barrier = 8,
};

// One line request travelling the hierarchy (3.3).
//
// The first three fields have no defaults because the tagged scalars have no
// default constructor (B2): a defaulted CoreId would mean core 0 and a
// defaulted BurstIndex would mean the first burst of the tile, both of which
// are valid values a forgotten initialiser would produce silently. The rest
// carry 3.3's own defaults, so `Request{CoreId{c}, LineId{l}, BurstIndex{k}}`
// is a fresh demand request and `Request{CoreId{c}, LineId{l}, BurstIndex{k},
// false}` is a prefetch.
//
// Not built: 3.3's `seq`. Nothing in Part 3 reads it, and 3.8 records that the
// `seq` of the event key is dead for the class where a refusal stamp exists.
// The `seq` that IS load-bearing is assigned at schedule time and belongs to
// the event (3.6), where event.h's EventSeq carries it; a second int64 counter
// of the same name on the request would be the N12 confusion the tagged types
// exist to stop, in the one place a reader is most likely to conflate them.
struct Request {
    CoreId     core;
    LineId     line;
    BurstIndex burst;  // which burst of the core's tile; a prefetch carries a future one

    // False for a prefetch: nobody is waiting on it, it never enters a wait
    // index, and it is DROPPED rather than refused (4.6, B11, N16). That single
    // rule is what keeps the waiting population backed one-for-one by demand
    // credits at any `prefetch_distance`, which is the whole of 4.1's argument.
    bool       demand = true;

    // When the burst this request belongs to was issued: the core's own issue
    // for a demand, the prefetcher's for a prefetch. Copied into `Mshr` at
    // allocate, which is how ruling R8's line anchor reaches the entry without
    // this class ever reading a clock (P2).
    SimTime    issued_at{0};

    // The global refusal COUNTER's value at this request's FIRST refusal, not a
    // tick (3.8). Write-once, which is what makes starvation freedom provable
    // (I10): the set of requests with a smaller stamp is finite and never
    // grows.
    RefusalOrder refusal = NoRefusal;

    // The reason of that first refusal, and write-once with it, exactly as
    // 3.8's `mark_refused` spells it. Note what that means and what it does
    // not: a request first refused for a slot and later re-refused onto a
    // line-wait index still reports Slot here, so this field is the reason it
    // ENTERED the waiting population and not the index that currently holds it.
    // Correctness does not rest on it -- what releases a waiter is which vector
    // holds it -- but Part 8's "reported separately by wait reason" does, and
    // that divergence is recorded rather than designed around.
    WaitReason reason = WaitReason::None;

    // Where to RE-ENTER on wake (3.5), not where it is now.
    Level level = Level::L1;

    // The L1 entry this request holds, once it has been FORWARDED at the L1.
    // I6: `r.level == L2 <=> r.mshr1 != null`. It is still held across the whole
    // downstream round trip, which is what makes the L2's wait sets views over
    // structures that already exist rather than storage (4.1, I6b).
    //
    // Non-owning. The entry lives in an MshrFile's map and outlives this
    // pointer by construction, since the request is satisfied or woken by that
    // entry's own retire.
    Mshr* mshr1 = nullptr;

    // Holds a slot-grant reservation handed out by the grant loop (3.8). Not a
    // second queue: it is what stops a wake producing a thundering herd racing
    // for one freed slot.
    bool reserved = false;

    // On a wait index right now: I5's first half, "a request is on at most one
    // wait index, and holds at most one reservation".
    //
    // Added by plan unit C2, which owns I5, and put on the REQUEST rather than
    // in the engine for the reason the invariant was hard to place at all: a
    // request can sit on an index of the L1 file or of the L2 file, and no one
    // file can see the other's. A bit the request carries is visible to both, so
    // membership is one fact in one place instead of the engine reconstructing
    // the population across two files.
    //
    // It is the wait-index counterpart of `reserved`, which already carried the
    // second half of I5 the same way. Set by `push_line_wait` / `push_slot_wait`
    // and cleared where a request LEAVES an index, which is `retire` for a line
    // waiter and `collect_grants` for a slot waiter -- the only two exits either
    // index has. The REFUSAL is `CacheLevel::triage`'s, one level up: this class
    // holds one file, a request can be refused at either of two, and the caller
    // is what sees both.
    bool on_wait_index = false;

    // Part 8's stall attribution for this line. See `StallCause` for the rule.
    StallCause cause = StallCause::None;

    // Set when `retire` releases this request from a LINE-wait index, which is
    // the one exit that guarantees the line is resident at the moment of the
    // wake: the caller installs before it retires. If the re-probe that follows
    // does not hit, the line was evicted between the wake and the re-triage,
    // which is D4's "a decision made at block time is not valid at service
    // time" and V6's `hits_downgraded_to_miss`. Read and cleared by the engine
    // at the re-probe. A slot waiter carries no such guarantee and is not
    // marked.
    bool line_resident_at_wake = false;
};

}  // namespace cachesim
