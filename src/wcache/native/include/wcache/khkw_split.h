// KhkwSplitMapper: the block-packed weight layout with the KERNEL POSITION
// digit split, so that the low part of it lands at the bottom of the L1 set
// index and CIN lands directly above it.
//
// A sibling of BlockPackMapper and SplitCinMapper rather than a flag on
// either, for the reason block_pack.h states (B10): a differently NESTED
// layout is a new AddressMapper subclass, because a class deriving from a
// flatten in order to disagree with part of it hides a bug in one override
// behind the correctness of the others.
//
// --- what this layout does ---------------------------------------------------
//
// The kernel position is the pair (kh, kw) read as one digit,
//
//     pos = kh * KW + kw          in [0, KH*KW)
//
// which is 9 values for a 3x3 kernel and therefore does not fit in 3 bits. It
// is split at n_pos_lo = min(8, KH*KW),
//
//     pos_lo = pos % n_pos_lo
//     pos_hi = pos / n_pos_lo
//
// and the four digits nest, outermost first, as
//
//     [pos_hi][cout_blk][cin_blk][pos_lo]
//
// The min is what keeps a 1x1 layer sound. A fixed radix of 8 under KH*KW = 1
// would leave pos_lo pinned at 0, every line a multiple of 8, and seven
// eighths of the L1 sets unreachable; taking the kernel's own extent when it
// is under 8 costs nothing on the 3x3 layers this campaign runs, where the min
// is 8 and the split is exactly the 3 bits asked for.
//
// --- why the digits sit in that order ----------------------------------------
//
// The L1 index is the low bits of the line id, so the digits that reach it are
// pos_lo first and then as much of cin_blk as the set count has room for. Both
// are coordinates every core sweeps fully inside a tile.
//
// cout_blk sits ABOVE cin_blk, which is what fixes the starvation split_cin.h
// documents: a core owns a contiguous slice of COUT and nothing else, so its
// cout_blk is pinned for the whole layer. Pinned digits belong in the tag, not
// in the index. With cout_blk above cin_blk it contributes nothing to an L1
// index of 32 or 64 sets and every core reaches every set.
//
// pos_hi is outermost so that the ninth kernel position aliases onto position
// zero's set and is separated from it by a tag bit. That is the trade the 3-bit
// split makes: a value reached one time in nine does not earn a fourth index
// bit.
//
// --- what this layout does NOT take ------------------------------------------
//
// No split-width argument. n_pos_lo is a property of the KERNEL and the
// constant 8, both of which this mapper already has, so unlike SplitCinMapper's
// n_cin_lo there is nothing for a caller to choose and `cin_lo_blocks` stays at
// its -1 sentinel under this layout.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "wcache/layout.h"
#include "wcache/types.h"

namespace wcache {

// `final` for BlockPackMapper's reason (B10): a class deriving from this one
// would be inheriting a four-digit flatten in order to disagree with part of it.
class KhkwSplitMapper final : public AddressMapper {
public:
    // The four digits of the flatten, in nesting order, outermost first.
    //
    // Nested in the class and not at namespace scope, because SplitCinMapper
    // already owns a five-valued `Digit` there and two enums of the same name
    // meaning different orders is exactly the confusion the tagged scalars in
    // types.h exist to prevent. It is also not Axis: POS_HI and POS_LO are two
    // digits of a pair of axes, and COUT and CIN sit between them.
    enum class Digit : std::uint8_t {
        POS_HI = 0,
        COUT   = 1,
        CIN    = 2,
        POS_LO = 3,
    };

    // The bits the kernel position contributes to the bottom of the index, as
    // a radix. Named rather than spelled 8 in the constructor: it is the one
    // number in this file that is a design choice and not arithmetic.
    static constexpr std::int64_t kPosLoRadix = 8;

    // The arguments and their order match BlockPackMapper exactly, so a call
    // site that swaps one mapper for the other cannot silently reorder them.
    //
    // Throws std::invalid_argument, naming the offending parameter and its
    // value, for a non-positive extent, block or element width, and for a
    // configuration whose line size or line count does not fit in int64.
    KhkwSplitMapper(WeightShape shape,
                    std::int32_t cin_block,
                    std::int32_t cout_block,
                    std::int32_t weight_bytes);

    void expand(const Burst& b, std::vector<LineId>& out) const override;
    Placement locate(LineId line, std::int64_t num_sets) const override;
    std::optional<LineId> neighbour(LineId line, Axis a, std::int32_t delta) const override;

    // The flatten:
    //
    //     line = pos_hi   * digit_stride(POS_HI)
    //          + cout_blk * digit_stride(COUT)
    //          + cin_blk  * digit_stride(CIN)
    //          + pos_lo   * digit_stride(POS_LO)
    //
    // Throws std::out_of_range, NOT std::invalid_argument, for a coordinate
    // outside the layer's shape: layout.h's three-tier vocabulary keeps a bad
    // configuration and a bad coordinate tellable apart at a catch site.
    LineId line_of(const Coord& c) const;

    // Public for the reason BlockPackMapper's equivalents are: without them the
    // constructor's arithmetic is unobservable until line_of exists, and
    // num_lines() is a sum in which two errors can cancel.
    //
    // Both throw std::logic_error for a Digit outside the enumerators.
    std::int64_t digit_stride(Digit d) const;
    std::int64_t digit_radix(Digit d) const;

    // The extent along `a` in whole LINES: the raw extent on KH and KW, the
    // block count on CIN and COUT. Over Axis rather than Digit because "how
    // many cin blocks exist" is a question about the axis.
    std::int64_t block_len(Axis a) const;

    LineId       num_lines()       const override { return LineId{num_lines_}; }
    std::int64_t line_size_bytes() const override { return line_size_bytes_; }
    std::string  line_size_terms(std::int64_t line_bytes) const override;

    const WeightShape& shape()         const { return shape_; }
    std::int32_t       cin_block()     const { return cin_block_; }
    std::int32_t       cout_block()    const { return cout_block_; }
    std::int32_t       weight_bytes()  const { return weight_bytes_; }
    std::int64_t       n_cin_blocks()  const { return n_cin_blocks_; }
    std::int64_t       n_cout_blocks() const { return n_cout_blocks_; }
    std::int64_t       n_pos()         const { return n_pos_; }
    std::int64_t       n_pos_lo()      const { return n_pos_lo_; }
    std::int64_t       n_pos_hi()      const { return n_pos_hi_; }

private:
    WeightShape  shape_;
    std::int32_t cin_block_;
    std::int32_t cout_block_;
    std::int32_t weight_bytes_;

    // int64 for BlockPackMapper's reason: a block count is a factor of a line
    // count and the line count is a LineId, which is int64. Zero-initialised so
    // that a constructor that throws leaves no member indeterminate.
    std::int64_t n_pos_           = 0;
    std::int64_t n_pos_lo_        = 0;
    std::int64_t n_pos_hi_        = 0;
    std::int64_t n_cin_blocks_    = 0;
    std::int64_t n_cout_blocks_   = 0;
    std::int64_t line_size_bytes_ = 0;
    std::int64_t num_lines_       = 0;

    // The four strides, indexed by static_cast<int>(Digit). Putting the order
    // in the array rather than in the expression keeps line_of free of it.
    std::int64_t stride_[4] = {0, 0, 0, 0};
};

}  // namespace wcache
