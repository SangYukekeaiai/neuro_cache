#include "cachesim/layout/block_pack.h"

#include <cstdint>
#include <stdexcept>
#include <string>

#include "layout_common.h"

namespace cachesim {
namespace {

using detail::kAxes;

constexpr const char* kName = "BlockPackMapper";

// A1b's carried obligation to A2, made mechanical.
//
// The nesting order this layout flattens in is KH, then KW, then the CIN block
// index, then the COUT block index, outermost first. That IS Axis declaration
// order, and A2c's line_of will read
//
//     line = ((kh * KW + kw) * n_cin_blocks + cin / cin_block) * n_cout_blocks
//            + cout / cout_block
//
// with line strides KH: KW * n_cin_blocks * n_cout_blocks, KW: n_cin_blocks *
// n_cout_blocks, CIN: n_cout_blocks, COUT: 1, strictly decreasing along the
// enumerator order. The obligation says reordering Axis without reordering
// that expression yields plausible, wrong line ids; the expression is not
// written yet, but the radices it multiplies are computed in this file, so the
// dependency exists here already. This is what stops a silent reorder: swap
// any two enumerators and the build stops, at the file that would have been
// wrong.
static_assert(static_cast<int>(Axis::KH) == 0, "Axis order feeds the flatten");
static_assert(static_cast<int>(Axis::KW) == 1, "Axis order feeds the flatten");
static_assert(static_cast<int>(Axis::CIN) == 2, "Axis order feeds the flatten");
static_assert(static_cast<int>(Axis::COUT) == 3, "Axis order feeds the flatten");

}  // namespace

BlockPackMapper::BlockPackMapper(WeightShape shape,
                                 std::int32_t cin_block,
                                 std::int32_t cout_block,
                                 std::int32_t weight_bytes)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    // Every extent, not only the two that are blocked: a KW of 0 collapses
    // the KH stride to zero and makes two different (kh, kw) pairs name the
    // same line, which is a silently wrong hit rate rather than a crash. A
    // block of 0 would divide by zero in the flatten; a negative one would
    // make the block index follow the sign of the coordinate, and integer
    // division truncating toward zero means the damage is a plausible
    // neighbouring line rather than an obviously wrong one. weight_bytes is
    // not a layout radix, but a zero would make line_size_bytes zero, and D1
    // divides cache_size_bytes by it to get a set count.
    detail::check_shape_and_blocking(kName, shape, cin_block, cout_block, weight_bytes);

    // Deliberately NOT checked: cin_block > CIN, cout_block > COUT, and a
    // block that does not divide its extent. Both are legal and both mean the
    // same thing, one short block. The cost is padding, not incorrectness, and
    // padding is a statistic (D2) rather than a configuration error.
    n_cin_blocks_  = detail::blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = detail::blocks_covering(shape.COUT, cout_block);

    // A line holds the whole cin_block x cout_block tile, padding included, so
    // this is the block's area and not the count of real elements in it. A
    // partial trailing block therefore costs a full line of capacity, which is
    // what the hardware being modelled does too: a DMA of a tile into a
    // line-sized buffer occupies the line whether or not the tile filled it.
    //
    // A function of the three layout parameters ONLY, never of the shape. That
    // is what makes it safe for D1 to turn cache_size_bytes into a set count
    // with it: a line size that varied per layer would make L1 and L2 a
    // different cache for every layer and would make the size axis of the
    // sweep incomparable across layers.
    line_size_bytes_ = detail::line_size_bytes(kName, cin_block, cout_block, weight_bytes);

    // The product of the four radices, in nesting order, folded left so the
    // partial products are the ones a reader can name: KH * KW is the kernel
    // window, times n_cin_blocks is one line row per kernel position, times
    // n_cout_blocks is the whole tensor in lines.
    //
    // Reachable overflow, not a formality. The corpus tops out at
    // 3 * 3 * 512 * 512 = 2359296 lines at cin_block = cout_block = 1, which
    // is 22 bits, but WeightShape carries four independent int32 extents that
    // arrive from a trace header, and three of them near INT32_MAX already
    // exceed int64. A header decoded at the wrong offset is exactly how that
    // happens, and it is the case where a wrong num_lines_ is worst: it is the
    // bound every later range check is written against.
    num_lines_ = detail::checked_mul(kName,
        detail::checked_mul(kName, detail::checked_mul(kName, shape.KH, shape.KW, "num_lines"),
                            n_cin_blocks_, "num_lines"),
        n_cout_blocks_, "num_lines");

    // The four radices of B17/B22, and the only place in the tree that knows
    // the flatten order. Filled innermost first, because each stride is the
    // next one times that axis's extent in lines, so reading downward is
    // reading the nesting from the inside out:
    //
    //   COUT is innermost, so consecutive cout blocks are consecutive lines
    //   CIN  steps over one whole run of cout blocks
    //   KW   steps over one whole (cin block, cout block) plane
    //   KH   steps over one whole kw row of those planes
    //
    // Indexed by static_cast<int>(Axis) rather than by four named members, per
    // board obligation B24, and the static_asserts at the top of this file are
    // what make the indexing safe.
    //
    // AFTER num_lines_, deliberately. num_lines_ is KH * stride_[KH], and KH is
    // already known to be at least 1, so every stride here is bounded above by
    // num_lines_ and none of these products can overflow once that one has been
    // checked. The checked_mul calls stay because the bound is an argument
    // about the code's order rather than something the code states: move this
    // block above num_lines_, or let a later edit relax the KH check, and the
    // guard is the difference between a diagnosed refusal and undefined
    // behaviour. The cost is two divisions, once per mapper.
    stride_[static_cast<int>(Axis::COUT)] = 1;
    stride_[static_cast<int>(Axis::CIN)]  = n_cout_blocks_;
    stride_[static_cast<int>(Axis::KW)]   =
        detail::checked_mul(kName, n_cin_blocks_, n_cout_blocks_, "KW line stride");
    stride_[static_cast<int>(Axis::KH)]   =
        detail::checked_mul(kName, shape.KW, stride_[static_cast<int>(Axis::KW)],
                            "KH line stride");
}

// --- A2c: the flatten --------------------------------------------------------

// The out-of-enumerator arm follows types.h's precedent exactly: a switch over
// every enumerator, and a throw after it that the compiler proves unreachable
// for any legal Axis. -Wswitch makes a new enumerator a build failure here
// rather than a silent fall through to the throw, which is the half that keeps
// this cheap. std::logic_error and not out_of_range: an Axis that is not one of
// the four is a bug in the caller's program, not a value outside a legal range,
// and that is the same distinction layout.h's three tiers draw.
std::int64_t BlockPackMapper::line_stride(Axis a) const {
    switch (a) {
        case Axis::KH:
        case Axis::KW:
        case Axis::CIN:
        case Axis::COUT:
            return stride_[static_cast<int>(a)];
    }
    throw std::logic_error("BlockPackMapper::line_stride: unknown Axis");
}

// The extent along `a` counted in whole lines. KH and KW are not blocked, so
// their line extent is the raw extent; CIN and COUT report block counts, which
// is why this is not extent_on with a cast. The int32 to int64 widenings are
// written out because -Wconversion is on and because the widening is the point:
// a block index is a factor of a line id.
std::int64_t BlockPackMapper::block_len(Axis a) const {
    switch (a) {
        case Axis::KH:   return static_cast<std::int64_t>(shape_.KH);
        case Axis::KW:   return static_cast<std::int64_t>(shape_.KW);
        case Axis::CIN:  return n_cin_blocks_;
        case Axis::COUT: return n_cout_blocks_;
    }
    throw std::logic_error("BlockPackMapper::block_len: unknown Axis");
}

LineId BlockPackMapper::line_of(const Coord& c) const {
    // Checked against the layer's SHAPE, not against block_len. Under CIN =
    // 100 with cin_block = 32 there are 4 blocks: a cin of 100 divides to
    // block 3 and would pass a block_len check while naming an element the
    // layer does not contain, and a cin of -1 divides to block 0 and would
    // pass it too. That is the v1 lesson the archive preserved, and checking
    // the quotient rather than the coordinate would throw it away.
    detail::check_in_shape(kName, shape_, c);

    // One loop over kAxes rather than the nested-Horner spelling in the comment
    // at the top of this file. They compute the same number, and this one reads
    // the order out of stride_ instead of building it into the expression,
    // which is what B24 asks for: the order lives in the constructor and
    // nowhere else.
    std::int64_t line = 0;
    for (Axis a : kAxes) {
        // v and the block size are both non-negative int32 here, so the
        // division cannot be the truncation trap above and cannot overflow.
        // The quotient is widened before the multiply, so the product is formed
        // in int64 and not in int32.
        const std::int32_t v     = coord_on(c, a);
        const std::int32_t block = detail::block_size_on(kName, a, cin_block_, cout_block_);
        line += static_cast<std::int64_t>(v / block) * line_stride(a);
    }

    // The LineId is constructed once, at the end, out of arithmetic that was
    // done in plain int64. A1's Tagged has no arithmetic on purpose, so this is
    // the only shape the flatten can take: compute the delta sum, then name it.
    return LineId{line};
}

// --- A2d: the burst walk and the placement -----------------------------------

// detail::expand_burst sorts unconditionally. Under this layout the walk is
// already increasing for a positive stride, because a block index is
// non-decreasing in its coordinate and every line stride is positive, so the
// sort is over an already sorted range, and that stays true under a permuted
// flatten order because every radix is positive whatever the permutation.
void BlockPackMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    detail::expand_burst(kName, *this, b, out);
}

// num_lines_ is an exact bound because the constructor's checked products made
// it one.
Placement BlockPackMapper::locate(LineId line, std::int64_t num_sets) const {
    return detail::locate_line(kName, num_lines_, line, num_sets);
}

// --- A4b: the line size, decomposed ------------------------------------------

std::string BlockPackMapper::line_size_terms(std::int64_t) const {
    return detail::line_size_terms(cin_block_, cout_block_, weight_bytes_);
}



// The flatten is one digit per axis (B17), so a neighbour is one stride away
// and the only question is whether the digit stays inside its radix.
std::optional<LineId> BlockPackMapper::neighbour(LineId line, Axis a,
                                                 std::int32_t delta) const {
    if (line.get() < 0 || line.get() >= num_lines_) {
        detail::reject_range(kName, "BlockPackMapper::neighbour: line " +
                                        std::to_string(line.get()) + " outside [0, " +
                                        std::to_string(num_lines_) + ")");
    }
    const std::int64_t stride = line_stride(a);   // throws on a bad Axis
    const std::int64_t radix  = block_len(a);
    const std::int64_t blk    = (line.get() / stride) % radix;
    const std::int64_t want   = blk + delta;
    if (want < 0 || want >= radix) return std::nullopt;
    return LineId{line.get() + static_cast<std::int64_t>(delta) * stride};
}

}  // namespace cachesim
