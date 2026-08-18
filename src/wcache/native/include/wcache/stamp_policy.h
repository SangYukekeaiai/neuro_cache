// LruPolicy and FifoPolicy: the two ReplacementPolicy implementations A5 builds.
//
// Plan v3 Part 7, unit A5: "`ReplacementPolicy` + LRU and FIFO. Random is a
// placeholder: it stays in the enum, is rejected at config load, and is not
// implemented (Q5)."
//
// Its own header rather than two more classes in policy.h, mirroring the split
// layout.h / block_pack.h and cache.h / set_associative.h already make, and for
// the same specific reason rather than for symmetry: a case compiled against
// policy.h proves the interface needs nothing but a SlotId and a Candidate, and
// folding the implementations in would make that unprovable.
//
// Both policies are the same machine under one different wire, which is why
// they share a base rather than being written twice: each slot carries a stamp,
// the victim is the smallest stamp in the candidate set, and the two differ
// only in whether a hit refreshes the stamp. Writing them separately would be
// two copies of pick_victim, and a rule that "no policy may depend on candidate
// order" is worth stating once and testing once rather than per policy.
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

#include "wcache/cache.h"
#include "wcache/policy.h"
#include "wcache/types.h"

namespace wcache {

// One stamp per slot, and a victim rule over stamps. Abstract, because a stamp
// policy with no rule for what a hit does is not a policy; the subclasses below
// supply exactly that.
class StampPolicy : public ReplacementPolicy {
public:
    // `num_slots` is CacheArray::num_slots(), which is the only thing a policy
    // is told about the array it serves (2.2). Throws std::invalid_argument for
    // a non-positive count: it is a config-derived geometry, so it has to be
    // refused under -DNDEBUG the same way SetAssociativeArray's is, and a
    // zero-slot array is a cache that can hold nothing.
    explicit StampPolicy(std::int32_t num_slots);

    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;

    // The smallest stamp among `candidates`, ties broken by the smallest slot
    // id. Both halves are needed for the order-independence policy.h requires:
    // the stamps of two occupied slots are never equal, since each is a
    // distinct value of a counter that only increases, but a slot that has
    // never been filled carries the "never stamped" value and several of those
    // can tie. Without the tie-break the answer would then be whichever of them
    // the vector happened to hold first, which is the dependency on order the
    // criterion forbids. With it, permuting `candidates` cannot change the
    // answer at all.
    //
    // Throws std::invalid_argument for an empty candidate set, and
    // std::out_of_range for a candidate naming a slot this policy does not
    // have. The first is not defensive padding: the minimum of nothing has no
    // answer, so the alternative to refusing is returning a slot id that names
    // no candidate, which the caller then installs a line into.
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

    // There is deliberately no `num_slots()` accessor. B20's argument for
    // BlockPackMapper's accessors does not apply: the constructor's sizing is
    // already observable, since the bound check below refuses the first slot id
    // past the end and names the count in the message. An accessor would be a
    // second way to read a fact the interface already reports.

protected:
    // Records `slot` as the most recently touched. The subclasses' on_hit is
    // this call or nothing, which is the whole of the difference between LRU
    // and FIFO.
    void stamp(SlotId slot);

private:
    // Bound check shared by every verb, so no two of them can disagree about
    // the range. Returns the slot's representation as an index.
    std::size_t index_or_reject(const char* verb, SlotId slot) const;

    // One stamp per slot, indexed by SlotId, carrying the "never stamped"
    // value for a slot that has never been filled (stamp_policy.cpp names it).
    // A flat vector is what the dense, stable SlotId of
    // 2.2 buys: the policy never computes a set index to reach its own state.
    std::vector<std::int64_t> stamp_;

    // The next stamp to hand out, strictly increasing, so no two stamps written
    // to occupied slots are ever equal. int64 for the same reason the refusal
    // counter is (Q8): it advances once per hit or fill over a whole sweep, and
    // 32 bits is reachable at the corpus size while 64 is not.
    std::int64_t next_stamp_;
};

// Least recently used: a hit refreshes the stamp, so the victim is the slot
// whose last USE is oldest.
class LruPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;

    void on_hit(SlotId slot) override;
};

// First in, first out: a hit does not refresh the stamp, so the victim is the
// slot whose INSTALL is oldest, however heavily it has been used since.
class FifoPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;

    // Deliberately empty, and it is not a stub. FIFO orders by insertion, and
    // insertion is what on_fill records; a hit is exactly the event this policy
    // is defined to ignore, which is the whole of its difference from LRU.
    void on_hit(SlotId slot) override;
};

// The config vocabulary, per plan 2.2's `l1_policy` and `l2_policy` fields.
//
// `random` is an enumerator with no class behind it, which is the plan's
// wording made literal: "Random is a placeholder: it stays in the enum, is
// rejected at config load, and is not implemented (Q5)". Dropping it from the
// enum would make `policy = random` an unknown name rather than a known and
// unbuilt one, and the run would then report a typo where it should report a
// missing feature (V29).
enum class PolicyKind : std::uint8_t { LRU = 0, FIFO = 1, RANDOM = 2 };

// The policy `kind` names, sized for an array of `num_slots` slots.
//
// Throws std::invalid_argument for PolicyKind::RANDOM, with a message saying
// Random is a placeholder and is not implemented. That is A5's exit criterion,
// and invalid_argument rather than logic_error because it is a config value
// refused, not a function called before it was written: the run must refuse it
// under -DNDEBUG, and D1's config load reaches this call with a value a human
// typed. This is the one place the refusal lives, so no config path can pick a
// policy the enum admits and silently fall back to LRU.
std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots);

}  // namespace wcache
