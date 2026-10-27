#pragma once

// What the three layout mappers (BlockPackMapper, SplitCinMapper,
// KhkwSplitMapper) share: argument checks, the coordinate range check, the
// burst walk, the placement and the line-size message. Each mapper keeps its
// own flatten (line_of, num_lines, strides) and its own neighbour.
//
// Every refusal names the mapper class through `cls`, prefixed as
// "<cls>: <what>", so a message out of one mapper never sends a reader to
// another mapper's file. A configuration the caller built wrong is
// std::invalid_argument and is found once, at construction; a coordinate or
// line id outside the layer is std::out_of_range and is found per call. That
// is layout.h's three tiers, with std::logic_error for programmer error.

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "cachesim/layout.h"
#include "cachesim/types.h"

namespace cachesim {
namespace detail {

// The four axes in declaration order.
constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

[[noreturn]] void reject(const char* cls, const std::string& what);
[[noreturn]] void reject_range(const char* cls, const std::string& what);

// The value is always printed, because the interesting cases are 0 from a
// field the config loader forgot to set and a negative from a header decoded
// at the wrong offset, and those two look nothing alike in a log.
inline void positive_or_reject(const char* cls, const char* name, std::int64_t v) {
    if (v < 1) reject(cls, std::string(name) + " must be >= 1, got " + std::to_string(v));
}

// a * b, refused rather than overflowed: signed overflow is undefined
// behaviour, not wraparound. Both arguments are known positive at every call
// site, which is why the a != 0 guard the general form needs is not written.
std::int64_t checked_mul(const char* cls, std::int64_t a, std::int64_t b, const char* what);

// Blocks needed to cover `extent`, rounding up: a short final block still
// occupies a whole line. The widening cast puts the sum in int64, so a large
// extent cannot wrap into a small block count.
inline std::int64_t blocks_covering(std::int32_t extent, std::int32_t block) {
    return (static_cast<std::int64_t>(extent) + block - 1) / block;
}

// The divisor that turns a coordinate on `a` into a block index. KH and KW
// are not blocked, so their block size is 1. An unknown axis is refused
// rather than defaulted to 1, which would flatten it as if unblocked: a
// plausible wrong line id rather than a visible failure.
inline std::int32_t block_size_on(const char* cls, Axis a, std::int32_t cin_block,
                                  std::int32_t cout_block) {
    switch (a) {
        case Axis::KH:
        case Axis::KW:   return 1;
        case Axis::CIN:  return cin_block;
        case Axis::COUT: return cout_block;
    }
    throw std::logic_error(std::string(cls) + ": unknown Axis in block_size_on");
}

// The constructor checks every mapper makes first, in this order: every
// extent >= 1 (KH and KW are radices of the flatten as much as the block
// counts are), then cin_block, cout_block and weight_bytes >= 1. A block that
// exceeds or does not divide its extent is legal: one short block, which
// costs padding, not correctness.
void check_shape_and_blocking(const char* cls, const WeightShape& shape,
                              std::int32_t cin_block, std::int32_t cout_block,
                              std::int32_t weight_bytes);

// cin_block * cout_block * weight_bytes. A line holds the whole block,
// padding included, and the size depends on these three parameters only,
// never on the shape, so a cache size turns into the same set count on every
// layer.
std::int64_t line_size_bytes(const char* cls, std::int32_t cin_block, std::int32_t cout_block,
                             std::int32_t weight_bytes);

// line_of's range check, against the layer's SHAPE and not against the block
// counts. Integer division truncates toward zero, so a cin in
// [-(cin_block - 1), -1] divides to block 0 and a cin of CIN can divide to the
// last block; only a check on the element coordinate itself catches both.
inline void check_in_shape(const char* cls, const WeightShape& shape, const Coord& c) {
    for (Axis a : kAxes) {
        const std::int32_t v = coord_on(c, a);
        const std::int32_t n = extent_on(shape, a);
        if (v < 0 || v >= n) {
            reject_range(cls, std::string(axis_name(a)) + " coordinate out of range [0, " +
                                  std::to_string(n) + "), got " + std::to_string(v));
        }
    }
}

// AddressMapper::expand for any mapper with line_of and shape(). The elements
// of a burst are anchor, anchor + stride, ... along b.axis, and the lines it
// touches are their flattens with the duplicates removed. What layout.h's
// contract asks for that is not free:
//
//  - Every check before the first append. The lines are built in a local
//    vector and appended to `out` only at the end, so a call that throws part
//    way leaves `out` untouched by construction.
//
//  - Strictly increasing ids, an obligation on the implementation rather than
//    a property of the layout, so this sorts unconditionally. unique() removes
//    only ADJACENT equals, so the de-duplication rests on the sort too.
//
//  - count < 1 or stride < 1 is std::invalid_argument, checked in that order
//    and before the coordinate range check: a request for no elements, and a
//    run that stands still or walks backwards, are malformed on every layer.
//
//  - The far end of the walk computed in int64. count and stride are both
//    int32 and their product is not, so a wild count would otherwise wrap into
//    a valid-looking coordinate. Checking both ends covers every element
//    between them, since the walk is affine in the element index.
template <typename Mapper>
void expand_burst(const char* cls, const Mapper& m, const Burst& b, std::vector<LineId>& out) {
    if (b.count < 1) {
        reject(cls, "burst count must be >= 1, got " + std::to_string(b.count));
    }
    positive_or_reject(cls, "burst stride", b.stride);

    const std::int32_t n     = extent_on(m.shape(), b.axis);
    const std::int64_t start = coord_on(b.anchor, b.axis);
    const std::int64_t last  = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
    if (last < 0 || last >= n) {
        reject_range(cls, std::string(axis_name(b.axis)) + " coordinate out of range [0, " +
                              std::to_string(n) + "), got " + std::to_string(last));
    }

    // Not reserved to b.count: the count is untrusted, and reserving it would
    // turn a burst with a wild count into a bad_alloc before the walk could
    // name the coordinate that was wrong.
    std::vector<LineId> lines;
    for (std::int32_t i = 0; i < b.count; ++i) {
        const std::int64_t v = start + static_cast<std::int64_t>(i) * b.stride;
        // line_of checks all four coordinates against the shape, so the
        // anchor's other three are validated by the first element.
        lines.push_back(m.line_of(with_coord_on(b.anchor, b.axis, static_cast<std::int32_t>(v))));
    }

    std::sort(lines.begin(), lines.end());
    lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
    out.insert(out.end(), lines.begin(), lines.end());
}

// AddressMapper::locate, the same for every layout: a layout moves which line
// an element lands on and leaves the cache's indexing alone. The range check
// runs BEFORE the division, because LineId is signed and a negative id would
// come back out of `line % num_sets` as a negative set index.
inline Placement locate_line(const char* cls, std::int64_t num_lines, LineId line,
                             std::int64_t num_sets) {
    const std::int64_t v = line.get();
    if (v < 0 || v >= num_lines) {
        reject_range(cls, "line id out of range [0, " + std::to_string(num_lines) + "), got " +
                              std::to_string(v));
    }
    // `line == tag * num_sets + set_index` is the definition of the pair.
    return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};
}

// AddressMapper::line_size_terms: the three factors of line_size_bytes, in
// the order they are multiplied, so a reader who sees "96-byte lines" in a
// refusal can reach the config fields that produced the 96. The same text for
// every layout, since they all build the line size the same way.
std::string line_size_terms(std::int32_t cin_block, std::int32_t cout_block,
                            std::int32_t weight_bytes);

}  // namespace detail
}  // namespace cachesim
