#include "wcache/set_associative.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// One spelling of the prefix, so every message this file produces is findable
// by grepping for the class name and no two of them disagree about the
// punctuation. block_pack.cpp sets the convention.
[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("SetAssociativeArray: " + what);
}

// One spelling of the positivity rule, for the same reason: the three
// non-positive cases below differ only in which quantity they name, and three
// hand-written messages are three chances for them to drift apart. The value is
// always printed, because 0 from a config field nobody set and a negative from
// one decoded wrong look nothing alike in a log.
void positive_or_reject(const char* name, std::int64_t v) {
    if (v < 1) reject(std::string(name) + " must be >= 1, got " + std::to_string(v));
}

// std::vector sizes with an unsigned size_type, so the signed slot count this
// class computes has to convert on the way into the storage. The one such
// conversion in this file goes through here, which keeps the arithmetic above
// it signed: with the cast spread across subscript expressions instead, a
// negative count would silently become a huge in-range-looking size at each of
// them and -Wsign-conversion would be answered with several casts rather than
// one reviewable site. The caller establishes non-negativity first.
std::size_t as_size(std::int32_t v) {
    return static_cast<std::size_t>(v);
}

}  // namespace

// The two verbs that take a SlotId share one bound check, so the two cannot
// disagree about whether the top of the range is open or closed. Named for the
// verb rather than for the class, because a caller with a stray slot id needs
// to know which call it reached.
std::int32_t SetAssociativeArray::slot_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || s >= num_slots_) {
        throw std::out_of_range("SetAssociativeArray::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(num_slots_) + ")");
    }
    return s;
}

// The order the checks run in is load-bearing and is therefore stated rather
// than left to be inferred from the sequence:
//
//   1. the three positivity checks, because every check after them divides by
//      one of the three values. A line size of 0 is a division by zero at
//      step 2 rather than a diagnosable refusal.
//   2. byte exactness, before the line count is derived, because the line count
//      means nothing if the division that produced it was not exact.
//   3. the slot-count bound, which is a fact about the size and the line size
//      alone, so a cache too large for a SlotId to index is reported as that
//      whatever the associativity is set to.
//   4. associativity against the whole cache, BEFORE the divides-into-sets
//      check. The two are both "bad associativity" and an over-associative
//      point fails the divisibility check too, but with a message that reads as
//      a rounding problem rather than as a cache too small to hold one set.
//   5. the divides-into-sets check.
//
// The plan's exit criterion is one division, "non-exact size / (line x assoc)
// throws", and steps 2 and 5 are that division split in two. They are exactly
// equivalent: writing size = q * (L * A) + r, `size % L != 0` implies
// `size % (L * A) != 0` because L divides L * A, and when `size % L == 0` the
// remainder `size % (L * A)` is `L * (total_lines % A)`. So the conjunction of
// the two checks holds exactly when the single division is exact.
//
// Splitting it buys two things. The messages say which of the two config fields
// is wrong, which one division cannot. And the product `line_size_bytes *
// associativity` is never formed, which matters because line_size_bytes() is
// only bounded by int64: the mapper `BlockPackMapper(WeightShape{1,1,1,1},
// INT32_MAX, INT32_MAX, 2)` reports 9223372028264841218 bytes per line, and
// multiplying that by any associativity above 1 is signed overflow, which is
// undefined behaviour rather than a wrong number. The split form only ever
// divides by it, and that mapper is refused at step 2 instead.
SetAssociativeArray::SetAssociativeArray(const AddressMapper& mapper,
                                         std::int64_t cache_size_bytes,
                                         std::int32_t associativity)
    : mapper_(mapper) {
    positive_or_reject("cache_size_bytes", cache_size_bytes);
    positive_or_reject("associativity", associativity);

    // Read once. It is a virtual call whose answer the rest of this
    // constructor divides by, and a mapper free to compute it per call is a
    // mapper free to answer differently at step 2 than at step 5.
    const std::int64_t line_bytes = mapper.line_size_bytes();
    positive_or_reject("mapper line_size_bytes", line_bytes);

    // Refused rather than floored. D2 echoes cache_size_bytes verbatim into
    // every results row, so a silently floored geometry would make the whole
    // sweep attribute its hit rates to a capacity the simulator never had.
    //
    // The message names the FACTORS of the line size and not only the product,
    // which is the A2b carried obligation to this unit. A non-power-of-two line
    // size is deliberately legal (B16), so "65536 is not a whole number of
    // 96-byte lines" is only actionable if the 96 can be traced back to
    // cin_block 12 x cout_block 8 x weight_bytes 1. line_size_terms() is what
    // supplies that, and its default on AddressMapper returns the bare product,
    // so a mapper that does not decompose its line size still produces a
    // well-formed message.
    //
    // It is handed `line_bytes`, the value read above, so the whole message is
    // built from one read: the default would otherwise call line_size_bytes()
    // again and a mapper answering differently the second time would print a
    // message whose two halves contradict each other.
    if (cache_size_bytes % line_bytes != 0) {
        reject("cache_size_bytes " + std::to_string(cache_size_bytes) +
               " is not a whole number of " + std::to_string(line_bytes) + "-byte lines (" +
               mapper.line_size_terms(line_bytes) + ")");
    }
    const std::int64_t total_lines = cache_size_bytes / line_bytes;

    // Slot ids are exactly [0, num_slots) and SlotId's representation is int32
    // (cache.h's num_slots), so a geometry with more lines than that has upper
    // slots no SlotId can name: storage the sweep paid for and never used,
    // showing up only as a hit rate a few points below the truth. Refused here
    // rather than reported by num_slots(), which is the decision A4a took when
    // it made num_slots() int32.
    //
    // The bound is INT32_MAX rather than INT32_MAX - 1, and that is exact
    // rather than approximate: at total_lines == INT32_MAX the largest slot id
    // is INT32_MAX - 1, one short of NoSlot, so no valid slot can be mistaken
    // for the sentinel.
    if (total_lines > INT32_MAX) {
        reject(std::to_string(total_lines) + " lines exceeds the " +
               std::to_string(INT32_MAX) + " slots a SlotId can name");
    }

    // Reachable only as a better message: an associativity larger than the
    // whole cache also fails the divisibility check below, since
    // `total_lines % associativity` is total_lines itself and total_lines is at
    // least 1 here. It is the case an over-associative sweep point lands on
    // first, and "3 lines do not divide evenly into sets of 512" describes the
    // wrong problem.
    if (associativity > total_lines) {
        reject("associativity " + std::to_string(associativity) +
               " exceeds the whole cache of " + std::to_string(total_lines) + " lines");
    }

    // Exact for the same reason as the byte check. It is the likelier of the
    // two to be hit, since a sweep grid crosses cache_size_bytes with
    // associativity and a non-power-of-two associativity against a
    // power-of-two size never divides.
    if (total_lines % associativity != 0) {
        reject(std::to_string(total_lines) + " lines do not divide evenly into sets of " +
               std::to_string(associativity));
    }

    associativity_ = associativity;
    num_sets_      = total_lines / associativity;
    // total_lines, which the check above bounded at INT32_MAX. Also
    // num_sets_ * associativity_, already computed.
    num_slots_     = static_cast<std::int32_t>(total_lines);

    // num_sets_ >= 1 follows from the checks rather than needing one of its
    // own: total_lines >= 1 because cache_size_bytes >= 1 divided exactly by
    // line_bytes, associativity <= total_lines, and the division is exact. That
    // is what makes `locate(line, num_sets_)` safe from A2d's unvalidated
    // division by num_sets, for calls through THIS array. It does not answer
    // the open question of who owns that guard in general (U14), and locate's
    // contract is unchanged.

    // Every slot starts free. An empty cache is the cold start the trace begins
    // from, and NoLine is what makes "free" and "holds a line" one comparison
    // in A4c's way scan rather than a second valid bit per slot.
    slots_.assign(as_size(num_slots_), NoLine);
}

// --- A4c: the five verbs -----------------------------------------------------

// The one piece of geometry the verbs share. `locate` range-checks the line and
// bounds the set index at [0, num_sets_), so the product below is at most
// (num_sets_ - 1) * associativity_, which is num_slots_ - associativity_: the
// multiplication is done in int64 and the result is known to fit an int32
// before the cast, since the constructor bounded num_slots_ at INT32_MAX.
//
// num_sets_ >= 1 is guaranteed by the constructor, which is what makes this
// call safe from the unvalidated division U14 records. That is a fact about
// calls through THIS array and not an answer to U14, which stays open.
std::int32_t SetAssociativeArray::base_slot(LineId line) const {
    const std::int64_t set_index = mapper_.locate(line, num_sets_).set_index.get();
    return static_cast<std::int32_t>(set_index * associativity_);
}

// Reads and returns. It touches no member, and the class has no mutable state
// for it to touch: plan 2.2 requires that "probe is const and is NOT an
// access", so a probe that recorded having been called -- a counter, a
// last-touched slot, anything a later verb could read back -- would perturb the
// recency stack through the back door the array/policy split exists to close.
// The engine calls policy.on_hit itself, and 4.6's prefetcher probes on a path
// that must not touch replacement state at all (I15).
//
// Compares whole line ids rather than tags. Within one set the set index is
// constant, so comparing line ids is exactly comparing tags and is equally free
// of aliasing; it also means no expression in this file forms `tag * num_sets`.
// NoLine cannot be mistaken for a resident line here: it is INT64_MAX, one past
// what any mapper can produce, and `locate` has already refused any line
// outside [0, num_lines()).
SlotId SetAssociativeArray::probe(LineId line) const {
    const std::int32_t base = base_slot(line);
    for (std::int32_t w = 0; w < associativity_; ++w) {
        if (slots_[as_size(base + w)] == line) return SlotId{base + w};
    }
    return NoSlot;
}

// The lowest free way, not an arbitrary one. The order is what makes the answer
// a function of the array's state alone, so two arrays given the same insert
// sequence agree slot for slot; an implementation free to return any free way
// would still be correct and would make every fixture below it unwritable.
SlotId SetAssociativeArray::free_slot(LineId line) const {
    const std::int32_t base = base_slot(line);
    for (std::int32_t w = 0; w < associativity_; ++w) {
        if (slots_[as_size(base + w)] == NoLine) return SlotId{base + w};
    }
    return NoSlot;
}

// Replaces the contents of `out` (cache.h), so the clear is the contract rather
// than tidiness. It runs AFTER base_slot, which is the other half of the same
// rule: base_slot is the only thing here that can throw, and a call that throws
// must leave `out` exactly as it was rather than emptied. That is expand's
// "every range check runs before the first append" applied to a verb that
// assigns instead of appending.
//
// The free ways are reported as candidates carrying NoLine rather than omitted.
// A caller reaching this verb has already had NoSlot from free_slot, so in the
// engine there are none; reporting them keeps the list one whole set, which is
// what makes "every slot appears under exactly one set" checkable from outside.
void SetAssociativeArray::victim_candidates(LineId line, std::vector<Candidate>& out) const {
    const std::int32_t base = base_slot(line);
    out.clear();
    for (std::int32_t w = 0; w < associativity_; ++w) {
        out.push_back(Candidate{SlotId{base + w}, slots_[as_size(base + w)]});
    }
}

// The slot is range-checked and the line is not, which is a deliberate asymmetry
// rather than an omission. An out-of-range slot is an out-of-bounds write into
// slots_: undefined behaviour, and reachable by one plausible mistake, since
// `insert(line, free_slot(line))` without checking for NoSlot passes INT32_MAX
// here. A line outside the mapper's range is a stored value, and every path
// that reads it back goes through `locate` and is refused there, so it is wrong
// but not silent and not memory-unsafe.
//
// std::out_of_range, not invalid_argument: layout.h's vocabulary gives
// out_of_range to an argument that is well formed but names something outside
// THIS layer, and a slot id outside [0, num_slots()) is exactly that.
//
// What is NOT checked, and is a caller precondition cache.h states: that `slot`
// is one of the slots that may hold `line`. Checking it costs a `locate` on
// every fill, and the callers that can get it wrong are pick_victim
// implementations, which A5 owns.
InsertResult SetAssociativeArray::insert(LineId line, SlotId slot) {
    const std::int32_t s = slot_or_reject("insert", slot);
    const LineId previous = slots_[as_size(s)];
    slots_[as_size(s)] = line;
    if (previous == NoLine) return InsertResult{false, NoLine};
    return InsertResult{true, previous};
}

// Invalidating a slot that is already free leaves it free, which is cache.h's
// stated behaviour and needs no branch: the write is the same either way.
void SetAssociativeArray::invalidate(SlotId slot) {
    slots_[as_size(slot_or_reject("invalidate", slot))] = NoLine;
}

}  // namespace wcache
