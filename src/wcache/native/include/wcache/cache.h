// CacheArray: which storage locations may hold a line, and what holds one now.
//
// Plan v3 Part 2.2, the "L1 tag + data array" row: `CacheArray { probe,
// free_slot, victim_candidates, insert, invalidate }`. The same row for the L2
// (2.3) names the same interface, so one abstraction covers both levels and
// the levels differ only in the geometry they are constructed with.
//
// The array/policy split named in 2.2 is a hard constraint on this file rather
// than a description of it: "the array knows geometry and holds no recency,
// timestamps, or insertion order; the policy holds all of those and knows
// nothing about sets or ways". So nothing a ReplacementPolicy would own may
// appear here. What is here is the map from a LineId to the locations that may
// hold it, plus one LineId per location.
//
// The handle that crosses the split is SlotId, and that is what makes the
// split implementable at all: it is dense in [0, num_slots()) so a policy
// indexes a flat vector with it and never computes a set index, and it is
// stable while a line stays resident so a stamp a policy wrote on a fill still
// names the same location on the next access.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/types.h"

namespace wcache {

// One entry of the set competing for replacement, as handed to
// ReplacementPolicy::pick_victim (A5).
//
// The line travels beside the slot rather than being looked up afterwards. A
// policy that has to exclude a line (the one with an outstanding MSHR, say)
// would otherwise need a reference back to the array and a slot-to-line
// accessor, which puts the array inside the module the split exists to keep
// out of it. Pairing them costs nothing: the array is already reading exactly
// these cells to enumerate the set.
struct Candidate {
    SlotId slot;
    LineId line;  // NoLine when the slot is free
};

// What an insert displaced.
//
// Both fields, because the caller needs both: the level counts evictions, and
// under `inclusion = inclusive` it has to know WHICH line left the L2 in order
// to back-invalidate it out of the L1s (plan 4.4, N8). Reporting only a bool
// would force the caller to read the slot before inserting, which is the same
// read done twice and a rule that is easy to forget once and then undercount
// for the whole sweep.
struct InsertResult {
    bool   evicted;       // the slot held a line, which this insert displaced
    LineId evicted_line;  // that line, or NoLine when `evicted` is false
};

// Geometry and storage. The implementation is SetAssociativeArray; a fully
// associative array is the other one this interface is shaped to admit, which
// is why nothing below mentions a set or a way.
//
// On the verb count. Plan 2.2 lists five, and two of them are one idea split:
// with replacement in another module this one cannot choose a victim, so all
// it can offer is the candidate set, while the case that needs no policy at
// all -- a set with a free way -- still has to be answered by the module that
// knows which ways are free. Folding the free case into the candidate list
// would oblige every policy to re-implement "prefer an empty way", and a
// policy that got it wrong would evict a live line while a way sat empty:
// silent, and visible only as a hit rate slightly below the truth.
class CacheArray {
public:
    virtual ~CacheArray() = default;

    // The slot holding `line`, or NoSlot if it is not resident.
    //
    // const, and free of side effects, which plan 2.2 states outright: "probe
    // is const and is NOT an access. The engine calls policy.on_hit
    // explicitly." Two things rest on it. A speculative lookup would otherwise
    // perturb the recency stack, and the prefetcher of 4.6 tests residency on
    // a path that must not touch replacement state at all (B11, I15).
    virtual SlotId probe(LineId line) const = 0;

    // A free slot among those that may hold `line`, or NoSlot when they are
    // all occupied. Call it before victim_candidates: a free slot costs no
    // eviction, so no policy is consulted and none can get it wrong.
    virtual SlotId free_slot(LineId line) const = 0;

    // Replaces the contents of `out` with the slots competing to hold `line`,
    // for ReplacementPolicy::pick_victim.
    //
    // Replaces rather than appends, which is the opposite of
    // AddressMapper::expand and deliberately so. expand appends because its
    // documented use accumulates a whole tick across cores into one buffer; a
    // candidate list is one set's worth, consumed immediately by one
    // pick_victim call. An appending version would let a caller that forgot to
    // clear pick a victim from a previous fill in a DIFFERENT set, and the
    // line would then be stored where probe can never look for it: no crash,
    // just a hit rate quietly below the truth for the whole run. Buffer reuse
    // is unaffected, since clearing keeps the capacity.
    //
    // The candidate set is handed over whole, and A5's obligation is that no
    // policy may depend on its order. That is what keeps this interface open
    // for a policy that does not pick by age.
    virtual void victim_candidates(LineId line, std::vector<Candidate>& out) const = 0;

    // Stores `line` in `slot`, which must be one of the slots that may hold
    // `line`, obtained from free_slot or from pick_victim over
    // victim_candidates.
    virtual InsertResult insert(LineId line, SlotId slot) = 0;

    // Drops whatever `slot` holds, leaving it free.
    //
    // On the interface from the start (N8) rather than added when C4 builds
    // inclusion, because a level that cannot invalidate cannot implement the
    // inclusive branch at all, and an interface that gains a verb later gets
    // one implementation of it rather than every implementation.
    //
    // The caller is expected to have located `slot` with probe, so the slot
    // holds a line; invalidating a free slot is a no-op rather than an error
    // only in the sense that it leaves it free. The policy's on_invalidate is
    // the caller's to make, exactly as on_hit is after a probe: this module
    // does not name a policy.
    virtual void invalidate(SlotId slot) = 0;

    // Number of storage locations, so slot ids are exactly [0, num_slots()).
    // Present so a policy can size its per-slot state from this interface
    // alone; handing it num_sets and associativity instead would put the
    // geometry back into the module the split keeps free of it.
    //
    // int32, matching SlotId's representation rather than the int64 the
    // geometry is computed in. A slot count a SlotId cannot name is a geometry
    // whose upper slots are unreachable, so an implementation refuses it at
    // construction instead of reporting it here.
    virtual std::int32_t num_slots() const = 0;

protected:
    // Copy and move are protected rather than public, which is the standard
    // treatment of a polymorphic base and is here for a measured reason rather
    // than a stylistic one.
    //
    // What was reachable before, and it is assignment rather than copying:
    //
    //     CacheArray& r1 = a1;  CacheArray& r2 = a2;
    //     r1 = r2;              // compiles; assigns the base subobject only
    //
    // Run rather than argued: a1's derived state was unchanged afterwards, so
    // the assignment was a silent partial write. For an array that is a
    // half-assigned cache, and it reports a hit rate for a geometry no level
    // ever had. Copying by value was never reachable, because this class is
    // abstract and no object of it can exist, so the reject cases that pass one
    // by value are proving abstractness rather than this.
    //
    // Protected rather than deleted, which is the half worth stating: deleting
    // would take the operations away from derived classes as well, and the
    // engine holds one L1 per core over a range of 8 to 256 cores, so a
    // container of concrete arrays is the ordinary case rather than a
    // hypothetical one. Protected leaves a derived class copyable AS ITSELF,
    // where a copy is whole, and leaves the base unusable as the source or
    // target of one, where it would not be.
    //
    // The default constructor has to be declared alongside them: declaring any
    // constructor suppresses the implicit default one, and without this line
    // every array in the tree would stop constructing.
    CacheArray()                             = default;
    CacheArray(const CacheArray&)            = default;
    CacheArray(CacheArray&&)                 = default;
    CacheArray& operator=(const CacheArray&) = default;
    CacheArray& operator=(CacheArray&&)      = default;
};

}  // namespace wcache
