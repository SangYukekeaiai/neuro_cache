#include "wcache/cache.h"

#include <cassert>
#include <cstddef>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// std::vector subscripts and sizes with an unsigned size_type, so the signed
// slot ids and counts this class computes have to convert on the way into the
// storage. Every such conversion in this file goes through here, which keeps
// all the arithmetic above it signed. That is the property types.h:10-19
// exists to protect: with the conversion spread across the five subscript
// expressions instead, a negative slot would silently become a huge
// in-range-looking index at each of them, and -Wsign-conversion would be
// answered with five casts rather than one reviewable site. Callers establish
// non-negativity before calling; the assert states that rather than trusting
// it.
std::size_t as_size(std::int64_t v) {
    assert(v >= 0);
    return static_cast<std::size_t>(v);
}

}  // namespace

SetAssociativeArray::SetAssociativeArray(const AddressMapper& mapper,
                                         std::int64_t cache_size_bytes,
                                         std::int64_t associativity)
    : mapper_(mapper), associativity_(associativity) {
    // Everything below throws rather than asserts. cache_size_bytes and
    // associativity are YAML fields (plan 3.5) and line_size_bytes is derived
    // from the layout block of the same file, so all three are config-sourced
    // and the checks have to survive -DNDEBUG in the sweep build. A sweep grid
    // takes a cross product (plan 3.5), so a combination nobody typed by hand
    // reaching this constructor is the expected case, not the exotic one.
    if (cache_size_bytes <= 0) {
        throw std::invalid_argument("SetAssociativeArray: cache_size_bytes must be positive");
    }
    if (associativity <= 0) {
        throw std::invalid_argument("SetAssociativeArray: associativity must be positive");
    }
    const std::int64_t line_bytes = mapper.line_size_bytes();
    if (line_bytes <= 0) {
        throw std::invalid_argument("SetAssociativeArray: line_size_bytes must be positive");
    }

    // Capacity in lines, checked exact. A size that is not a whole number of
    // lines is refused rather than floored because plan 6.1 echoes
    // l1_size_bytes and l2_size_bytes verbatim into every results row: a
    // silently floored geometry would make the whole sweep attribute its hit
    // rates to a capacity the simulator never had.
    if (cache_size_bytes % line_bytes != 0) {
        throw std::invalid_argument(
            "SetAssociativeArray: cache_size_bytes " + std::to_string(cache_size_bytes) +
            " is not a whole number of " + std::to_string(line_bytes) + "-byte lines");
    }
    const std::int64_t total_lines = cache_size_bytes / line_bytes;

    // Checked before the multiply below, which is also what keeps
    // line_bytes * associativity from overflowing: past this point
    // associativity <= total_lines <= cache_size_bytes, so the product is
    // bounded by cache_size_bytes. Refusing here rather than letting num_sets
    // come out zero gives the message that says what is actually wrong, and it
    // is the case an over-associative sweep point lands on first.
    if (associativity > total_lines) {
        throw std::invalid_argument(
            "SetAssociativeArray: associativity " + std::to_string(associativity) +
            " exceeds the whole cache of " + std::to_string(total_lines) + " lines");
    }
    // Exact for the same reason as the byte check above. It is the likelier of
    // the two to be hit: plan 3.5's sweep grid crosses cache_size_bytes with
    // associativity, and a non-power-of-two associativity against a
    // power-of-two size never divides. The two real configurations do:
    // 32768 / (16 * 4) = 512 sets at L1, 524288 / (16 * 32) = 1024 at L2.
    if (total_lines % associativity != 0) {
        throw std::invalid_argument(
            "SetAssociativeArray: " + std::to_string(total_lines) +
            " lines do not divide evenly into sets of " + std::to_string(associativity));
    }

    num_sets_  = total_lines / associativity;
    num_slots_ = total_lines;  // num_sets_ * associativity_, already computed
    // num_sets_ >= 1 follows from the two checks above rather than needing its
    // own: total_lines >= associativity >= 1 and the division is exact.
    assert(num_sets_ >= 1 && num_slots_ == num_sets_ * associativity_);

    // Every slot starts free. An empty cache is the cold start the trace
    // begins from, and kNoLine is what makes "free" indistinguishable from
    // "holds a line that can never be asked for" in the probe loop below.
    slots_.assign(as_size(num_slots_), kNoLine);
}

std::int64_t SetAssociativeArray::set_of(LineId line) const {
    // The tag half of the returned SetIndex is deliberately unused: this array
    // stores whole line ids, so a tag comparison and a line comparison are the
    // same test within a set (see the slots_ comment in cache.h).
    const std::int64_t set_index = mapper_.locate(line, num_sets_).set_index;
    // assert, not throw: a LineId arriving here came from
    // AddressMapper::expand, which already threw on anything the trace got
    // wrong (layout.cpp:101-109), so a bad value at this point could only have
    // come from this simulator's own code. The check is stated here anyway
    // rather than left to BlockPackMapper's internal assert, because it is the
    // AddressMapper contract this class depends on and a future mapper is free
    // to implement locate without asserting. It matters because signed % takes
    // the sign of its dividend, so a negative line yields a negative set index
    // and, one line later, a subscript before the start of slots_.
    assert(set_index >= 0 && set_index < num_sets_);
    return set_index;
}

SlotId SetAssociativeArray::probe(LineId line) const {
    const SlotId base = set_of(line) * associativity_;
    // A linear scan of the ways is what set-associative hardware does in
    // parallel, and associativity is 4 at L1 and 32 at L2 (plan 3.5), so the
    // scan is short and contiguous. Anything cleverer, a per-set hash map say,
    // would cost more per access than it saves at these widths.
    for (std::int64_t way = 0; way < associativity_; ++way) {
        // No validity test in the loop: a free slot holds kNoLine, which is
        // negative, and a real LineId never is, so a free slot cannot match.
        if (slots_[as_size(base + way)] == line) {
            return base + way;
        }
    }
    return kNoSlot;
}

SlotId SetAssociativeArray::free_slot(LineId line) const {
    const SlotId base = set_of(line) * associativity_;
    for (std::int64_t way = 0; way < associativity_; ++way) {
        if (slots_[as_size(base + way)] == kNoLine) {
            // Lowest free way, not an arbitrary one. Cold-start placement is
            // then a property of the trace alone, so two runs of the same
            // sweep point fill the arrays identically even under the Random
            // replacement policy of plan 3.3, which only ever sees full sets.
            return base + way;
        }
    }
    return kNoSlot;
}

void SetAssociativeArray::victim_candidates(LineId line,
                                            std::vector<Candidate>& out) const {
    const SlotId base = set_of(line) * associativity_;
    out.clear();
    // Safe here, unlike the reserve that had to be removed from expand. That
    // one sized a buffer to the exact running total of an accumulation, which
    // left zero slack and reallocated on every later append. This buffer is
    // cleared each call and never exceeds associativity_, so its capacity
    // converges after the first call and it never allocates again.
    out.reserve(as_size(associativity_));
    for (std::int64_t way = 0; way < associativity_; ++way) {
        // Ways in index order, so pick_victim sees a stable ordering. A policy
        // breaking a tie by position (FIFO on equal insert times, Random over
        // an index) then gives the same answer on a re-run.
        out.push_back(Candidate{base + way, slots_[as_size(base + way)]});
    }
}

InsertResult SetAssociativeArray::insert(LineId line, SlotId slot) {
    // All three are asserts: `slot` came from free_slot or from a policy
    // choosing among this array's own candidates, so a bad value could only
    // originate inside the simulator. They are worth stating even so, because
    // each failure mode is silent rather than loud.
    assert(slot >= 0 && slot < num_slots_);
    // A slot belonging to a different set would store the line where probe can
    // never look for it: no crash, no wrong answer that can be pointed at, just
    // a hit rate quietly below the truth for the whole sweep. Recomputing
    // set_of here rather than reusing a local keeps the call out of the release
    // build entirely, since the whole expression disappears with the assert.
    assert(slot / associativity_ == set_of(line));
    // Filling a line already resident would put two copies in one set, after
    // which probe's answer depends on way order and the second copy's eviction
    // is counted as an eviction of a line that is still there. It also means
    // the caller skipped the probe that should have made this a hit.
    assert(probe(line) == kNoSlot);

    LineId& cell = slots_[as_size(slot)];
    InsertResult result;
    // The displaced value is the report. When the slot was free it is already
    // kNoLine, which is exactly what evicted_line documents itself to carry in
    // that case, so the two fields cannot disagree.
    result.evicted      = (cell != kNoLine);
    result.evicted_line = cell;
    cell = line;
    return result;
}

}  // namespace wcache
