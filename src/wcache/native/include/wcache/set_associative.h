// SetAssociativeArray: the set-associative CacheArray.
//
// Plan v3 Part 2.2, the "L1 tag + data array" row: "Set-associative SRAM; a
// line may sit in any way of one set", shaped by `l1_size_bytes` and
// `l1_assoc`. Part 2.3 names the same structure for the L2 with `l2_size_bytes`
// and `l2_assoc`, so one class covers both levels and they differ only in the
// geometry they are constructed with.
//
// This is also the direct-mapped implementation, at associativity 1: every set
// has one way, `free_slot` answers the cold case, and the candidate list has a
// single entry that every policy must return. A third class would be this code
// with the loops unrolled to one iteration.
//
// Its own header rather than a second class in cache.h, mirroring the split A2
// already makes between layout.h (the abstract AddressMapper) and block_pack.h
// (the concrete BlockPackMapper). The reason is specific rather than
// symmetry: this class holds an AddressMapper, so putting it in cache.h would
// make cache.h include layout.h, and tests/compile_fail.sh's `tryC` preamble
// exists to fail if the array interface ever acquires that dependency. Keeping
// the concrete array here leaves that check meaning what it says.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/cache.h"
#include "wcache/layout.h"
#include "wcache/types.h"

namespace wcache {

// `final` for BlockPackMapper's reason (B10): a class deriving from this one
// would be inheriting the set-associative geometry in order to disagree with
// part of it, which is the shape that makes a bug in one override invisible in
// the others. A fully associative array is a sibling implementation of
// CacheArray, not a subclass of this.
//
// Holds the mapper by reference rather than taking `num_sets` as a number, for
// two reasons. It needs the mapper regardless: `locate(line, num_sets)` is the
// only thing that turns a LineId into a set, it is virtual so a future hashed
// layout states its own rule, and copying the current rule in here would be a
// second place that can disagree about where a line lives. And given the
// mapper, `num_sets` is derivable from the two config fields, so deriving it
// once inside the array is one place that can be wrong instead of one per
// construction site. The mapper must outlive the array; one mapper instance
// serves the whole hierarchy (layout.h), so its lifetime already exceeds every
// level's.
class SetAssociativeArray final : public CacheArray {
public:
    // `cache_size_bytes` and `associativity` are config fields (D1), so every
    // rejection below is a `throw` rather than an `assert`: they have to
    // survive the sweep build's -DNDEBUG. A sweep grid takes a cross product,
    // so a combination nobody typed by hand reaching this constructor is the
    // expected case rather than the exotic one.
    //
    // num_sets is `cache_size_bytes / (line_size_bytes * associativity)` and
    // the constructor refuses a combination where that division is not exact,
    // which is unit A4's exit criterion. See set_associative.cpp for the order
    // the checks run in and why refusing beats rounding.
    //
    // `associativity` is int32 rather than int64: it is a way count, it
    // multiplies into a slot count that is int32 because SlotId is (cache.h's
    // num_slots), and a way index is the same quantity class as a slot id.
    // `cache_size_bytes` is int64 because it is divided by line_size_bytes(),
    // which is int64.
    //
    // Throws std::invalid_argument, naming the offending value, for a
    // non-positive size, associativity or line size; for a size that is not a
    // whole number of lines; for an associativity larger than the whole cache;
    // for a line count that does not divide into sets; and for a geometry with
    // more slots than a SlotId can name.
    SetAssociativeArray(const AddressMapper& mapper,
                        std::int64_t cache_size_bytes,
                        std::int32_t associativity);

    // --- the five verbs (A4c) ------------------------------------------------
    //
    // The contracts are CacheArray's and are not restated here; what this class
    // adds to them is one fact, and it is the whole of the implementation: the
    // slots that may hold a line are the `associativity()` consecutive ids
    // starting at `set_index * associativity()`. Every verb below is that
    // arithmetic plus a scan of at most `associativity()` cells.
    //
    // Three of the five throw only what `locate` throws, which is
    // std::out_of_range for a line outside [0, num_lines()); they add no
    // rejection of their own. The two that take a SlotId range-check it, for
    // the reason given on `insert` in the .cpp.
    SlotId probe(LineId line) const override;
    SlotId free_slot(LineId line) const override;
    void victim_candidates(LineId line, std::vector<Candidate>& out) const override;
    InsertResult insert(LineId line, SlotId slot) override;
    void invalidate(SlotId slot) override;

    // --- fixed at construction -----------------------------------------------
    //
    // num_slots is on CacheArray so a policy can size its per-slot state from
    // that interface alone. The other two are deliberately NOT: a fully
    // associative array has no meaningful set count, and putting them on the
    // interface would invite a policy to read them, which is the array/policy
    // split (2.2) leaking.
    //
    // They are public here for B20's reason rather than for the config echo:
    // without them the constructor's arithmetic is unobservable. num_slots
    // alone is the same number under a swapped division, so an implementation
    // that reported `num_sets` where the associativity belongs, or that floored
    // where it should refuse, would look identical from outside until A4c.
    std::int32_t num_slots() const override { return num_slots_; }
    std::int64_t num_sets() const { return num_sets_; }
    std::int32_t associativity() const { return associativity_; }

private:
    // The lowest slot id of the set `line` competes in, so the set's slots are
    // exactly [base_slot(line), base_slot(line) + associativity()). This is
    // B65's `set_of`, which A4b left unwritten because it reads `Placement` and
    // U16 was open; U16 has since typed the fields, so it is written here in
    // the form its three callers actually need. The set index alone is never
    // used by anything: probe, free_slot and victim_candidates each want the
    // base, so returning a SetIndex and multiplying at three call sites would
    // be the same expression written three times.
    //
    // It reads `set_index` and never `tag`. That is worth stating because the
    // identity `line == tag * num_sets + set_index` (layout.h) makes the tag
    // look like the natural thing to compare on, and forming `tag * num_sets`
    // is signed overflow for a large enough tag, which `Placement` has no
    // precondition against. Nothing in this class forms that product: the slot
    // array stores whole line ids (see slots_ below), so a way scan compares
    // line ids directly and the tag half of locate's answer is never touched.
    //
    // Throws std::out_of_range, from locate, for a line outside
    // [0, mapper.num_lines()).
    std::int32_t base_slot(LineId line) const;

    // The shared bound check of `insert` and `invalidate`. Returns the slot's
    // representation, so a caller that has checked it does not unwrap it a
    // second time; throws std::out_of_range naming `verb` otherwise.
    std::int32_t slot_or_reject(const char* verb, SlotId slot) const;

    const AddressMapper& mapper_;

    // Zero-initialised so a constructor that throws leaves no member
    // indeterminate, and derived rather than stored where the constructor can
    // check first: the validation lives in the body, which runs after the
    // initialiser list, so anything computed from a checked value is assigned
    // in the body. That is block_pack.h's "check, then derive" order.
    std::int32_t associativity_ = 0;
    std::int64_t num_sets_      = 0;
    std::int32_t num_slots_     = 0;

    // One LineId per slot, NoLine when free, indexed by SlotId. Stores the full
    // line id rather than the tag half of locate's answer: within one set the
    // set index is constant, so comparing line ids is exactly comparing tags
    // and is equally free of aliasing, and it lets insert report the evicted
    // line without reconstructing it from `tag * num_sets + set_index`. It
    // costs nothing, since a tag is an int64 here too.
    //
    // A vector rather than a fixed array because the geometry is a config
    // field. LineId has no default constructor (B2), which is why this is
    // filled with an explicit NoLine rather than sized and left to
    // value-initialise.
    std::vector<LineId> slots_;
};

}  // namespace wcache
