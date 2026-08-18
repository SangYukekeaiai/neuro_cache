// CacheArray: which storage locations may hold a line, and what holds it now.
// Plan Part 3.3, where the stated reason this is its own module is "geometry
// independent of policy".
//
// That sentence is a hard constraint on this file, not a description of it.
// `ReplacementPolicy` is a separate module with on_hit, on_fill and
// pick_victim(candidates), so nothing a policy would own may appear here: no
// recency stack, no counters, no timestamps, no insertion order. What is here
// is the map from a LineId to the set that may hold it, plus one LineId per
// storage location. The array cannot name a policy and the policy cannot see
// the geometry, which is what lets LRU, FIFO and Random share one array and
// lets PinnedDecorator wrap any of them.
//
// The seam between the two modules is `SlotId`. See its comment below: it is
// the whole reason this split is implementable.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/layout.h"
#include "wcache/types.h"

namespace wcache {

// A storage location, stable for as long as the line in it stays resident.
//
// This is the type that carries the geometry/policy split. A policy has to be
// able to say "evict that one" and to remember something per location across
// accesses, and it has to do both without knowing what a set or a way is.
// SlotId is that handle: it is dense in [0, num_slots), so a policy indexes its
// own per-location state with a flat vector and never computes a set index; and
// it is stable, so a counter a policy wrote on a fill still describes the same
// physical location on the next access to it. A set-associative array numbers
// slots `set_index * associativity + way`, but nothing outside this file may
// rely on that: FullyAssociativeArray (a later unit) will number them
// differently and the same policies must work unchanged.
//
// Signed, like LineId and SetIndex, so that a sentinel stays visibly negative
// instead of wrapping to a large plausible index. types.h:10-19 records the
// defect that motivates keeping one signedness across the tree.
using SlotId = std::int64_t;

// Returned by probe and free_slot when no location qualifies, and returned by
// ReplacementPolicy::pick_victim when every candidate is ineligible, which is
// reachable once PinnedDecorator excludes lines with an outstanding MSHR
// (plan 2.3). -1 rather than a large value so that a caller that forgets to
// check it indexes out of bounds loudly instead of at a real slot.
inline constexpr SlotId kNoSlot = -1;

// The LineId stored in a slot that holds nothing. A real LineId is a dense
// index into [0, num_lines) and therefore never negative, so this cannot
// collide with a resident line and an empty slot can never satisfy a probe.
inline constexpr LineId kNoLine = -1;

// One entry of the set that competes for replacement, as handed to
// ReplacementPolicy::pick_victim.
//
// The line travels with the slot rather than being looked up afterwards
// because of PinnedDecorator: excluding a line that has an outstanding MSHR
// means testing candidates against a pool keyed by LineId (plan 2.3), and if
// the candidate were a bare SlotId then that decorator would have to hold a
// reference back to the array and call a slot-to-line accessor. Pairing them
// here costs nothing, since the array is already reading exactly these cells to
// enumerate the set, and it keeps every policy free of any array reference.
struct Candidate {
    SlotId slot;
    LineId line;  // kNoLine if the slot is free
};

// What an insert displaced.
//
// The caller needs both fields: CacheLevel counts evictions, and an inclusive
// hierarchy has to know *which* line left the L2 to act on it. Returning only
// a bool would force the caller to read the slot before inserting, which is
// the same read done twice and a rule that is easy to forget once and then
// undercount forever.
struct InsertResult {
    bool   evicted;       // the slot held a valid line, which this insert displaced
    LineId evicted_line;  // that line, or kNoLine when evicted is false
};

// Geometry and storage. Implementations: SetAssociativeArray below, and
// FullyAssociativeArray in a later unit.
//
// On the verb count. Plan 3.3 lists three verbs, `probe`, `insert`, `victim`.
// The one written as `victim` is split in two here, and the split is forced:
// with replacement in another module, this module cannot choose a victim, so
// the only thing it can offer is the candidate set. Meanwhile the one case
// that needs no policy at all, a set with a free way, still has to be answered
// by the module that knows which ways are free. Folding that case into the
// candidate list instead would oblige every policy to re-implement "prefer an
// empty way", and a policy that got it wrong would evict a live line while a
// way sat empty, silently and only visible as a slightly worse hit rate.
// Hence: `free_slot` for the no-policy case, `victim_candidates` for the
// policy case.
class CacheArray {
public:
    virtual ~CacheArray() = default;

    // The slot holding `line`, or kNoSlot if it is not resident.
    //
    // const, and free of side effects, on purpose. In a design where the array
    // owned recency, a lookup would have to be split into a "peek" and a real
    // access, because plan 2.9.4 drops a prefetch whose target is already
    // resident and that test must not itself count as a use. With recency in
    // the policy there is one lookup: the caller decides whether to follow it
    // with ReplacementPolicy::on_hit, and only that call makes it an access.
    virtual SlotId probe(LineId line) const = 0;

    // A free slot in the set `line` maps to, or kNoSlot if the set is full.
    // Call this before victim_candidates: a free slot costs no eviction, so no
    // policy is consulted and none can get it wrong.
    virtual SlotId free_slot(LineId line) const = 0;

    // Replaces the contents of `out` with the slots competing to hold `line`,
    // for ReplacementPolicy::pick_victim.
    //
    // Replaces rather than appends, unlike AddressMapper::expand. expand
    // appends because its documented use accumulates a whole tick across cores
    // into one buffer; a candidate list is one set's worth, consumed
    // immediately by one pick_victim call. Appending would make a caller that
    // forgets to clear pick a victim from a previous fill, in a different set,
    // and the line would then be stored where probe can never find it again.
    // Buffer reuse is unaffected: clear() keeps the capacity.
    virtual void victim_candidates(LineId line, std::vector<Candidate>& out) const = 0;

    // Stores `line` in `slot`, which must be a slot of the set `line` maps to,
    // obtained from free_slot or from pick_victim over victim_candidates.
    virtual InsertResult insert(LineId line, SlotId slot) = 0;

    // Number of storage locations, so slot ids are exactly [0, num_slots).
    // Present so a policy can size its per-slot state from the interface alone.
    // The alternative, handing the policy num_sets and associativity, would put
    // the geometry back into the module this split exists to keep free of it.
    virtual std::int64_t num_slots() const = 0;
};

// Set-associative storage: a line may sit in any of `associativity` ways of
// the one set AddressMapper::locate assigns it.
//
// This is also the direct-mapped implementation. YAML `cache_type:
// direct_mapped` (plan 3.5) is this class at associativity 1, where every set
// has one way, free_slot answers the cold case and the candidate list has a
// single entry that every policy must return. A third class would be the same
// code with the loops unrolled to one iteration.
//
// Holds the mapper by reference rather than taking num_sets and associativity
// as plain numbers, for two reasons. First, it needs the mapper regardless:
// locate(line, num_sets) is the only thing that turns a LineId into a set, it
// is virtual so a future hashed layout can state its own rule, and copying the
// current rule in here would be the sum-of-coordinates regression waiting to
// happen a second time. Second, given the mapper, num_sets is derivable here
// from the two YAML fields, and deriving it once inside the array is one place
// that can be wrong instead of one per construction site. The mapper must
// outlive the array; one mapper instance serves the whole hierarchy
// (layout.h:40-43), so its lifetime already exceeds every level's.
class SetAssociativeArray final : public CacheArray {
public:
    // `cache_size_bytes` and `associativity` are the YAML fields of plan 3.5,
    // so both are validated with throw rather than assert: the checks have to
    // survive the sweep build's -DNDEBUG. num_sets is
    // cache_size_bytes / (line_size_bytes * associativity), and the constructor
    // refuses a combination where that division is not exact. See cache.cpp for
    // why refusing beats rounding.
    SetAssociativeArray(const AddressMapper& mapper,
                        std::int64_t cache_size_bytes,
                        std::int64_t associativity);

    SlotId probe(LineId line) const override;
    SlotId free_slot(LineId line) const override;
    void victim_candidates(LineId line, std::vector<Candidate>& out) const override;
    InsertResult insert(LineId line, SlotId slot) override;
    std::int64_t num_slots() const override { return num_slots_; }

    // Geometry, for the config echo of plan 6.1 (`l1_assoc`, `l2_assoc`) and
    // for the set-reachability check of plan 5.2. Deliberately not on
    // CacheArray: a fully associative array has no meaningful set count, and
    // putting these on the interface would invite a policy to read them.
    std::int64_t num_sets() const { return num_sets_; }
    std::int64_t associativity() const { return associativity_; }

private:
    // Set index of `line`, with the bound the rest of this class indexes on.
    std::int64_t set_of(LineId line) const;

    const AddressMapper& mapper_;
    std::int64_t associativity_;
    std::int64_t num_sets_;
    std::int64_t num_slots_;

    // One LineId per slot, kNoLine when free, indexed by SlotId. Stores the
    // full line id rather than SetIndex::tag: within one set the set index is
    // constant, so comparing line ids is exactly comparing tags and is equally
    // free of aliasing (layout.cpp:172-179 establishes that (set, tag) and line
    // are in bijection). It also lets insert report the evicted line without
    // reconstructing it from tag * num_sets + set_index, and costs nothing,
    // since a tag is an int64 here too.
    std::vector<LineId> slots_;
};

}  // namespace wcache
