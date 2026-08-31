// ReplacementPolicy: which resident line leaves when a set is full.
//
// Plan v3 Part 2.2, the "L1 replacement state" row: `ReplacementPolicy {
// on_hit, on_fill, on_invalidate, pick_victim }`, and the row says outright
// that it is "a **separate module** from the array". Part 2.3's L2 row names
// the same interface, so one abstraction covers both levels.
//
// The split named in 2.2 is a hard constraint on this file, and it is the
// mirror of the one cache.h carries: "the array knows geometry and holds no
// recency, timestamps, or insertion order; the policy holds all of those and
// knows nothing about sets or ways". So nothing about sets, ways, associativity
// or line addresses may appear in what a policy is TOLD; what it holds is the
// ordering state the array refuses to.
//
// The handle that crosses the split is SlotId, dense in [0, num_slots()) and
// stable while a line stays resident, so a policy indexes a flat vector with it
// and never computes a set index. That is what lets one array serve LRU, FIFO
// and Random unchanged.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/cache.h"
#include "wcache/types.h"

namespace wcache {

// The four verbs, in the order 2.2 lists them.
//
// Three of them are notifications and one is a question. That asymmetry is the
// design: the array reports what happened to a slot, and the policy is asked
// only at the point where the array genuinely cannot answer. Nothing here
// returns state, because a policy's state is its own and no other module reads
// it; D2's victim-age instrument is a statistic computed at the eviction site,
// not a getter on this interface.
class ReplacementPolicy {
public:
    virtual ~ReplacementPolicy() = default;

    // `slot` was hit by an access.
    //
    // Called by the engine explicitly, never by the array, and that is plan
    // 2.2's rule rather than a convention: "probe is const and is NOT an
    // access. The engine calls policy.on_hit explicitly. Without this, a
    // speculative lookup would perturb the recency stack." The prefetcher of
    // 4.6 is the case that makes it bite: a prefetch that finds the line
    // resident drops it and must not touch replacement state (I15), and it can
    // only do that if probing and recording a use are two separate calls.
    virtual void on_hit(SlotId slot) = 0;

    // `slot` now holds a newly installed line.
    //
    // One verb for the fill, whether or not the insert evicted. What was
    // displaced is gone, and a policy's state for a slot describes its CURRENT
    // occupant, so an eviction leaves nothing for the policy to remember about
    // the line that left.
    virtual void on_fill(SlotId slot) = 0;

    // `slot` no longer holds a line: the array's `invalidate` was called on it,
    // which under `inclusion = inclusive` is the back-invalidation path (N8,
    // 4.4). The caller makes this call, exactly as it makes on_hit after a
    // probe; the array does not name a policy.
    virtual void on_invalidate(SlotId slot) = 0;

    // OPTIONAL. When the line now in `slot` is next referenced, as a position in
    // the level's own reference stream, or INT64_MAX for a line never referenced
    // again. Called by the engine immediately before `on_fill` or `on_hit`, and
    // only where a next-use oracle is attached.
    //
    // A TIME, not a line and not an address, so 2.2's rule stands unchanged: the
    // policy is still told nothing about sets, ways, associativity or line
    // addresses. That is what lets Belady's MIN live behind this interface at
    // all. LRU keeps the time of a slot's LAST use and evicts the minimum;
    // Belady keeps the time of its NEXT use and evicts the maximum. Same shape,
    // opposite sign, and the only difference is that LRU derives its stamp from
    // a counter it owns while Belady's has to be supplied from outside.
    //
    // A default no-op rather than a pure virtual, so every policy that does not
    // want the future is unchanged and no existing call site moves.
    virtual void note_next_use(SlotId /*slot*/, std::int64_t /*next_use*/) {}

    // Which of `candidates` to evict, as a slot drawn from that set.
    //
    // Given a candidate SET, and no implementation may depend on its order.
    // That is the plan's A5 exit criterion and it is load-bearing rather than
    // stylistic: with only LRU and FIFO built, both pick "oldest by a stamp",
    // so an implementation that quietly relied on, say, the list being in slot
    // order would compile, pass every fixture, and fail only when a policy that
    // does not pick by age is added. Nothing else announces that regression, so
    // the obligation is stated on the interface where an implementer reads it.
    //
    // What order-independence means concretely: permuting `candidates` may not
    // change the answer. A policy whose natural rule can tie therefore needs a
    // tie-break that is a function of the candidates themselves and not of
    // where they sit in the vector.
    //
    // Not const, and that is the openness the criterion is protecting: a Random
    // policy draws from an RNG, which is state it must advance. Random is a
    // placeholder today (Q5) and is not implemented, but a const signature here
    // would be exactly the interface change adding it would force.
    //
    // `candidates` is the whole of one set, including any free ways, which
    // carry NoLine (cache.h). The engine reaches this verb only after free_slot
    // has answered NoSlot, so in the engine there are none.
    virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;

protected:
    // Protected and defaulted, for the reason B67 settled for CacheArray rather
    // than re-derived here: through two base references `p1 = p2` would compile
    // and assign the base subobject only, leaving the derived recency state
    // untouched. For a policy that is a half-assigned eviction order, which
    // reports a plausible hit rate for a history it never had. Protected rather
    // than deleted keeps a derived policy copyable AS ITSELF, which matters
    // because the engine holds one L1 policy per core over 8 to 256 cores.
    //
    // The default constructor is declared alongside them because declaring any
    // constructor suppresses the implicit one.
    ReplacementPolicy()                                    = default;
    ReplacementPolicy(const ReplacementPolicy&)            = default;
    ReplacementPolicy(ReplacementPolicy&&)                 = default;
    ReplacementPolicy& operator=(const ReplacementPolicy&) = default;
    ReplacementPolicy& operator=(ReplacementPolicy&&)      = default;
};

}  // namespace wcache
