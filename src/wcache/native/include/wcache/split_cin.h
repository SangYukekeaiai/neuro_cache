// SplitCinMapper: the block-packed weight layout, with the CIN block index
// split into two digits so that the low one lands in the L1 set index.
//
// Why this exists rather than a flag on BlockPackMapper: block_pack.h states
// the rule (B10) that a differently NESTED memory layout is a new
// AddressMapper subclass, because a class deriving from a flatten in order to
// disagree with part of it is exactly the shape that makes a bug in one
// override invisible in the others. This layout disagrees with BlockPackMapper
// about the nesting, so it is a sibling and shares no code with it.
//
// --- the problem this layout is for ------------------------------------------
//
// BlockPackMapper nests [KH][KW][cin_blk][cout_blk] with cout_blk innermost.
// A core owns a contiguous slice of COUT and nothing else, so its cout_blk is
// pinned for the whole layer while it sweeps cin. Consecutive lines it asks
// for therefore differ by n_cout_blocks, a power of two, and `line % num_sets`
// keeps only
//
//     num_sets / gcd(n_cout_blocks, num_sets)
//
// distinct sets per block it owns. Measured on vgg16 layer_08_features_27 at
// 16 KB / 8-way / 16-byte lines: one core reaches 8 of 128 sets, 1152 distinct
// tags contend for each of them against 8 ways, and the L1 hit rate is exactly
// 0.000. Pooling all 16 cores reaches all 128 sets, so the flatten is a sound
// bijection and the starvation is per core: a private L1 sees one sixteenth of
// the id space, and that sixteenth is an arithmetic progression rather than a
// dense range.
//
// --- what this layout does instead -------------------------------------------
//
// The CIN block index is split at n_cin_lo,
//
//     cin_lo = cin_blk % n_cin_lo
//     cin_hi = cin_blk / n_cin_lo
//
// and the five digits nest, outermost first, as
//
//     [KH][KW][cin_hi][cout_blk][cin_lo]
//
// so that cin_lo is innermost and `line % n_cin_lo == cin_lo`. The caller sets
// n_cin_lo to the L1 set count, which makes the L1 index a pure function of
// cin, the one coordinate a core sweeps fully inside every tile.
//
// --- why cout_blk sits directly above cin_lo, and not higher ------------------
//
// A line-id relabel is global: L2 reads the same ids. Both orders that put
// cin_lo innermost were measured on the same trace, as the fraction of each
// tile's working set that could be simultaneously resident:
//
//     digit order (outermost first)        L1        L2
//     [KH][KW][cin][cout_blk]  (current)   2.5%     72.1%
//     [KH][KW][cout_blk][cin_hi][cin_lo]  69.5%     55.7%
//     [KH][KW][cin_hi][cout_blk][cin_lo]  69.5%     69.5%
//
// The middle row is the obvious reading and it costs L2 sixteen points,
// because with cout_blk that far out only 2 of its 5 bits survive into L2's
// 2048-set index. Keeping cout_blk directly above cin_lo leaves 4 of them
// there. L2 still gives up 2.6 points against the current layout; that is the
// price of the 67 points at L1, and it is paid against a level that sees far
// less traffic once L1 stops missing everything.
//
// --- what n_cin_lo couples to ------------------------------------------------
//
// n_cin_lo is a constructor argument and not derived, even though the caller
// will always pass an L1 set count. The coupling is real: change
// l1_size_bytes or l1_assoc and the optimal DRAM layout changes with it. An
// argument makes that visible at every construction site and lets a test pin a
// value the config would never produce. Deriving it would hide a dependency of
// the memory layout on the cache geometry inside a constructor.
//
// Nothing here requires n_cin_lo to divide, or even to be reached by, the
// block count. n_cin_lo > n_cin_blocks leaves part of the index unreachable
// and n_cin_lo not dividing n_cin_blocks leaves holes in the id space; both
// cost placement quality rather than correctness, and both follow
// BlockPackMapper's precedent that padding is a statistic rather than a
// configuration error. The warning belongs in config.cpp, beside the other
// quality warnings, not in this constructor.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "wcache/layout.h"
#include "wcache/types.h"

namespace wcache {

// The five digits of the flatten, in nesting order, outermost first.
//
// A separate enum from Axis, and not an extension of it, because these are not
// axes: CIN_HI and CIN_LO are two digits of one axis, and COUT sits between
// them. Reusing Axis would give this file two different meanings for the value
// 2 (Axis::CIN and Digit::CIN_HI) with no diagnostic between them, which is
// the class of confusion the tagged scalars in types.h exist to prevent.
enum class Digit : std::uint8_t {
    KH     = 0,
    KW     = 1,
    CIN_HI = 2,
    COUT   = 3,
    CIN_LO = 4,
};

// `final` for BlockPackMapper's reason (B10), stated in full at the top of its
// header: a class deriving from this one would be inheriting a five-digit
// flatten in order to disagree with part of it.
class SplitCinMapper final : public AddressMapper {
public:
    // The first four arguments and their order match BlockPackMapper exactly,
    // so a call site that swaps one mapper for the other cannot silently
    // reorder them. n_cin_lo is appended rather than inserted for the same
    // reason.
    //
    // n_cin_lo is int64 and not int32 because it is a SET COUNT: the caller
    // reads it from RunConfig::l1_num_sets(), which returns int64, and
    // narrowing it here would put the conversion at the call site where
    // -Wconversion cannot see what it is for.
    //
    // Throws std::invalid_argument, naming the offending parameter and its
    // value, for a non-positive extent, block, element width, or n_cin_lo, and
    // for a configuration whose line size or line count does not fit in int64.
    SplitCinMapper(WeightShape shape,
                   std::int32_t cin_block,
                   std::int32_t cout_block,
                   std::int32_t weight_bytes,
                   std::int64_t n_cin_lo);

    // --- the two interface entry points ---------------------------------------
    //
    // Both are unit W2. They throw std::logic_error until then, which is the
    // tier layout.h reserves for programmer error, and calling a function that
    // has not been written is exactly that. A stub returning a plausible value
    // would be the failure mode this whole file exists to argue against.
    void expand(const Burst& b, std::vector<LineId>& out) const override;
    Placement locate(LineId line, std::int64_t num_sets) const override;
    std::optional<LineId> neighbour(LineId line, Axis a, std::int32_t delta) const override;

    // --- the flatten ----------------------------------------------------------
    //
    //     line = kh       * digit_stride(KH)
    //          + kw       * digit_stride(KW)
    //          + cin_hi   * digit_stride(CIN_HI)
    //          + cout_blk * digit_stride(COUT)
    //          + cin_lo   * digit_stride(CIN_LO)
    //
    // Throws std::out_of_range, NOT std::invalid_argument, for a coordinate
    // outside the layer's shape. The two must stay distinguishable: a bad
    // configuration and a bad coordinate are found at different times by
    // different callers. layout.h states the three-tier vocabulary.
    LineId line_of(const Coord& c) const;

    // Public for the reason BlockPackMapper's equivalents are: without them
    // the constructor's arithmetic is unobservable until line_of exists, and
    // num_lines() is a product in which two errors can cancel.
    //
    // digit_stride and digit_radix are over Digit and not over Axis, because a
    // split axis has two strides and two radices and a `line_stride(Axis::CIN)`
    // would have to return one of them. Returning either would be a plausible
    // wrong answer of exactly the kind block_pack.cpp's comments warn against,
    // so the accessor is over the thing that actually has one stride each.
    //
    // Both throw std::logic_error for a Digit outside the enumerators, which is
    // the convention types.h sets: refuse rather than invent an answer.
    std::int64_t digit_stride(Digit d) const;
    std::int64_t digit_radix(Digit d) const;

    // The extent along `a` measured in whole LINES: the raw extent on KH and
    // KW, the block count on CIN and COUT. Over Axis rather than Digit because
    // "how many cin blocks exist" is a question about the axis and is the same
    // number whatever the split does with it. It is deliberately NOT what a
    // range check compares against; line_of checks the shape, which is the
    // strictly stronger bound.
    std::int64_t block_len(Axis a) const;

    // --- fixed at construction ------------------------------------------------
    LineId       num_lines()       const override { return LineId{num_lines_}; }
    std::int64_t line_size_bytes() const override { return line_size_bytes_; }

    // The three factors line_size_bytes_ is the product of, named and with
    // their values, for SetAssociativeArray's exactness message. The line size
    // the caller read is ignored: this override names the factors it
    // multiplies its own members out of.
    std::string line_size_terms(std::int64_t line_bytes) const override;

    // --- the derived state, exposed -------------------------------------------
    const WeightShape& shape()          const { return shape_; }
    std::int32_t       cin_block()      const { return cin_block_; }
    std::int32_t       cout_block()     const { return cout_block_; }
    std::int32_t       weight_bytes()   const { return weight_bytes_; }
    std::int64_t       n_cin_blocks()   const { return n_cin_blocks_; }
    std::int64_t       n_cout_blocks()  const { return n_cout_blocks_; }
    std::int64_t       n_cin_lo()       const { return n_cin_lo_; }
    std::int64_t       n_cin_hi()       const { return n_cin_hi_; }

private:
    WeightShape  shape_;
    std::int32_t cin_block_;
    std::int32_t cout_block_;
    std::int32_t weight_bytes_;

    // int64 for BlockPackMapper's reason: a block count is a factor of a line
    // count and the line count is a LineId, which is int64. Keeping a factor
    // narrower than its product is the boundary the v1 signedness class lived
    // on. Zero-initialised so that a constructor that throws leaves no member
    // indeterminate.
    std::int64_t n_cin_lo_        = 0;
    std::int64_t n_cin_hi_        = 0;
    std::int64_t n_cin_blocks_    = 0;
    std::int64_t n_cout_blocks_   = 0;
    std::int64_t line_size_bytes_ = 0;
    std::int64_t num_lines_       = 0;

    // The five radices, indexed by static_cast<int>(Digit). Five and not four
    // is the entire difference between this layout and BlockPackMapper's, and
    // putting the order in the array rather than in the expression is what
    // keeps line_of free of it.
    std::int64_t stride_[5] = {0, 0, 0, 0, 0};
};

}  // namespace wcache
