#include "cachesim/split_cin.h"

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "layout_common.h"

namespace cachesim {
namespace {

constexpr const char* kName = "SplitCinMapper";

// The nesting order this layout flattens in, made mechanical the way
// block_pack.cpp does it for its four. Swap any two enumerators in Digit and
// the build stops here, at the file that would otherwise have been silently
// wrong. This matters more here than it does there: the whole point of this
// layout is WHICH digit is innermost, so a reorder is not a wrong number in a
// corner case, it is the bug this class was written to fix, reintroduced.
static_assert(static_cast<int>(Digit::KH)     == 0, "Digit order feeds the flatten");
static_assert(static_cast<int>(Digit::KW)     == 1, "Digit order feeds the flatten");
static_assert(static_cast<int>(Digit::CIN_HI) == 2, "Digit order feeds the flatten");
static_assert(static_cast<int>(Digit::COUT)   == 3, "Digit order feeds the flatten");
static_assert(static_cast<int>(Digit::CIN_LO) == 4, "Digit order feeds the flatten");

// The ceiling of detail::blocks_covering, over two int64 operands, for the
// split. n_cin_blocks_ is already int64 by the time this is called, so it
// cannot reuse the int32 form, and the addition is done on values the
// constructor has already checked positive.
std::int64_t ceil_div(std::int64_t a, std::int64_t b) {
    return (a + b - 1) / b;
}

}  // namespace

SplitCinMapper::SplitCinMapper(WeightShape shape,
                               std::int32_t cin_block,
                               std::int32_t cout_block,
                               std::int32_t weight_bytes,
                               std::int64_t n_cin_lo)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    detail::check_shape_and_blocking(kName, shape, cin_block, cout_block, weight_bytes);

    // n_cin_lo is the innermost radix, so a 0 divides by zero in line_of and a
    // negative one makes cin_lo follow the sign of cin_blk. It is checked with
    // the same helper as the block sizes because it fails the same way.
    //
    // Deliberately NOT checked: n_cin_lo > n_cin_blocks_, and n_cin_lo not
    // dividing n_cin_blocks_. The first leaves part of the set index
    // unreachable and the second leaves holes in the id space; both cost
    // placement quality rather than correctness, and both follow
    // BlockPackMapper's precedent that padding is a statistic rather than a
    // configuration error. The quality warning belongs in config.cpp beside
    // the others.
    detail::positive_or_reject(kName, "n_cin_lo", n_cin_lo);
    n_cin_lo_ = n_cin_lo;

    n_cin_blocks_  = detail::blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = detail::blocks_covering(shape.COUT, cout_block);

    // How many values the high digit takes. Ceiling for the same reason
    // blocks_covering is: a short final group still needs a digit value, and
    // flooring here would make the top cin blocks flatten onto the same line
    // as the ones n_cin_lo below them.
    n_cin_hi_ = ceil_div(n_cin_blocks_, n_cin_lo_);

    // A function of the three layout parameters ONLY, never of the shape and
    // never of n_cin_lo. That is what makes it safe for the caller to turn
    // cache_size_bytes into a set count with it, and it is why the split
    // cannot change the line size: splitting a digit rearranges which line an
    // element lands in, not how many elements a line holds.
    line_size_bytes_ = detail::line_size_bytes(kName, cin_block, cout_block, weight_bytes);

    // The product of the FIVE radices, in nesting order, folded left so the
    // partial products are ones a reader can name: KH * KW is the kernel
    // window, times n_cin_hi is one line plane per (kernel position, cin
    // group), times n_cout_blocks is one line row per cout block, times
    // n_cin_lo is the whole tensor in lines.
    //
    // This is NOT num_lines_. It is the overflow guard and the upper bound for
    // it: layout.h defines num_lines() as "one past the LARGEST LineId this
    // mapper can produce", and the conformance suite checks that the bound is
    // REACHED, not merely respected. When n_cin_lo does not divide
    // n_cin_blocks_ the top of the cin_hi digit is only partly used, so the
    // radix product overruns the largest line this flatten can actually emit.
    // Measured on the ragged case CIN 10, n_cin_lo 4, COUT 4: the product is
    // 48 and the largest real line is 45, so a num_lines_ of 48 would be a
    // bound that is too loose, which deflates every coverage figure computed
    // by dividing through it.
    //
    // Computing it here anyway, with the same checked_mul chain, is what makes
    // the sum below provably overflow-free: every term of that sum is one
    // digit's maximum times its stride, so the sum is at most this product
    // minus one.
    const std::int64_t radix_product = detail::checked_mul(kName,
        detail::checked_mul(kName,
            detail::checked_mul(kName,
                detail::checked_mul(kName, shape.KH, shape.KW, "num_lines"), n_cin_hi_,
                "num_lines"),
            n_cout_blocks_, "num_lines"),
        n_cin_lo_, "num_lines");

    // The five radices, and the only place in the tree that knows this
    // flatten's order. Filled innermost first, because each stride is the next
    // one times that digit's radix, so reading downward is reading the nesting
    // from the inside out:
    //
    //   CIN_LO is innermost, which is the whole point: `line % n_cin_lo`
    //          is cin_lo, so a caller that sets n_cin_lo to the L1 set count
    //          gets a set index that depends only on cin
    //   COUT   steps over one whole run of cin_lo values, so it keeps as many
    //          of its own bits as a larger set count can still see
    //   CIN_HI steps over one whole (cout block, cin_lo) plane
    //   KW     steps over one whole cin_hi run of those planes
    //   KH     steps over one whole kw row
    //
    // AFTER num_lines_, deliberately, for BlockPackMapper's reason: num_lines_
    // is KH * stride_[KH] and KH is already known to be at least 1, so every
    // stride here is bounded above by num_lines_ and none of these products
    // can overflow once that one has been checked. The checked_mul calls stay
    // because that bound is an argument about the code's order rather than
    // something the code states.
    stride_[static_cast<int>(Digit::CIN_LO)] = 1;
    stride_[static_cast<int>(Digit::COUT)]   = n_cin_lo_;
    stride_[static_cast<int>(Digit::CIN_HI)] =
        detail::checked_mul(kName, n_cout_blocks_, n_cin_lo_, "CIN_HI line stride");
    stride_[static_cast<int>(Digit::KW)] =
        detail::checked_mul(kName, n_cin_hi_, stride_[static_cast<int>(Digit::CIN_HI)],
                            "KW line stride");
    stride_[static_cast<int>(Digit::KH)] =
        detail::checked_mul(kName, shape.KW, stride_[static_cast<int>(Digit::KW)],
                            "KH line stride");

    // One past the largest line this flatten can produce, which is what
    // layout.h asks for and what the radix product above is not.
    //
    // Each digit contributes its own maximum times its own stride, and the
    // digits are independent EXCEPT for the two halves of cin, which are two
    // views of one number. So cin contributes at its own largest block index,
    // n_cin_blocks_ - 1, split the same way line_of splits it, rather than at
    // (n_cin_hi_ - 1, n_cin_lo_ - 1), which is a pair the coordinate space may
    // not contain.
    //
    // That this really is the maximum rests on line_of being strictly
    // increasing in cin_blk: raising cin_blk by one either raises cin_lo by
    // one, for +1, or wraps cin_lo to zero and raises cin_hi, for
    // +n_cin_lo_ * (n_cout_blocks_ - 1) + 1, which is positive for every legal
    // n_cout_blocks_ including 1. The other three digits appear linearly with
    // positive strides, so their maxima are their own extents.
    const std::int64_t cin_blk_max = n_cin_blocks_ - 1;
    num_lines_ = 1
        + (shape.KH - 1)          * stride_[static_cast<int>(Digit::KH)]
        + (shape.KW - 1)          * stride_[static_cast<int>(Digit::KW)]
        + (cin_blk_max / n_cin_lo_) * stride_[static_cast<int>(Digit::CIN_HI)]
        + (n_cout_blocks_ - 1)    * stride_[static_cast<int>(Digit::COUT)]
        + (cin_blk_max % n_cin_lo_) * stride_[static_cast<int>(Digit::CIN_LO)];

    // The sum is a mixed-radix number with every digit at or below its radix
    // minus one, so it cannot exceed radix_product - 1 and the + 1 cannot
    // exceed radix_product. checked_mul already refused anything that would
    // make radix_product itself overflow, so this assertion is about the
    // argument above rather than about arithmetic the compiler can see.
    if (num_lines_ < 1 || num_lines_ > radix_product) {
        detail::reject(kName, "num_lines " + std::to_string(num_lines_) +
                                  " is outside (0, radix product " +
                                  std::to_string(radix_product) + "]");
    }
}

// --- the radices, read back --------------------------------------------------

// The out-of-enumerator arm follows types.h's precedent: a switch over every
// enumerator, and a throw after it that the compiler proves unreachable for any
// legal Digit. -Wswitch makes a new enumerator a build failure here rather than
// a silent fall through. std::logic_error and not out_of_range: a Digit that is
// not one of the five is a bug in the caller's program.
std::int64_t SplitCinMapper::digit_stride(Digit d) const {
    switch (d) {
        case Digit::KH:
        case Digit::KW:
        case Digit::CIN_HI:
        case Digit::COUT:
        case Digit::CIN_LO:
            return stride_[static_cast<int>(d)];
    }
    throw std::logic_error("SplitCinMapper::digit_stride: unknown Digit");
}

std::int64_t SplitCinMapper::digit_radix(Digit d) const {
    switch (d) {
        case Digit::KH:     return static_cast<std::int64_t>(shape_.KH);
        case Digit::KW:     return static_cast<std::int64_t>(shape_.KW);
        case Digit::CIN_HI: return n_cin_hi_;
        case Digit::COUT:   return n_cout_blocks_;
        case Digit::CIN_LO: return n_cin_lo_;
    }
    throw std::logic_error("SplitCinMapper::digit_radix: unknown Digit");
}

// The extent along `a` counted in whole lines. KH and KW are not blocked, so
// their line extent is the raw extent; CIN and COUT report block counts. CIN
// reports the whole block count and not either half of the split, because the
// question "how many cin blocks does this layer have" has one answer and the
// split does not change it: n_cin_blocks() is what n_cin_hi() and n_cin_lo()
// cover between them.
std::int64_t SplitCinMapper::block_len(Axis a) const {
    switch (a) {
        case Axis::KH:   return static_cast<std::int64_t>(shape_.KH);
        case Axis::KW:   return static_cast<std::int64_t>(shape_.KW);
        case Axis::CIN:  return n_cin_blocks_;
        case Axis::COUT: return n_cout_blocks_;
    }
    throw std::logic_error("SplitCinMapper::block_len: unknown Axis");
}

// --- the flatten -------------------------------------------------------------

LineId SplitCinMapper::line_of(const Coord& c) const {
    // The range check is over the four AXES and the accumulation below is
    // over the five DIGITS, two passes rather than one fused loop: Axis::CIN
    // and Digit::CIN_HI are both 2 with nothing to tell them apart.
    detail::check_in_shape(kName, shape_, c);

    // Every coordinate is now known to be in [0, extent), so each division is
    // of two non-negative values and cannot truncate toward zero. The
    // quotient is widened before the multiply, so every product is formed in
    // int64.
    const auto blk_of = [&](Axis a) -> std::int64_t {
        return static_cast<std::int64_t>(coord_on(c, a)) /
               detail::block_size_on(kName, a, cin_block_, cout_block_);
    };

    const std::int64_t cin_blk = blk_of(Axis::CIN);

    // The split itself, and the only two lines in the tree that perform it.
    // Both operands are non-negative, so these are the ordinary quotient and
    // remainder rather than the truncate-toward-zero pair.
    const std::int64_t cin_hi = cin_blk / n_cin_lo_;
    const std::int64_t cin_lo = cin_blk % n_cin_lo_;

    std::int64_t line = 0;
    line += blk_of(Axis::KH)   * digit_stride(Digit::KH);
    line += blk_of(Axis::KW)   * digit_stride(Digit::KW);
    line += cin_hi             * digit_stride(Digit::CIN_HI);
    line += blk_of(Axis::COUT) * digit_stride(Digit::COUT);
    line += cin_lo             * digit_stride(Digit::CIN_LO);

    // The LineId is constructed once, at the end, out of arithmetic done in
    // plain int64. Tagged has no arithmetic on purpose, so this is the only
    // shape the flatten can take: compute the sum, then name it.
    return LineId{line};
}

// --- the burst walk and the placement ----------------------------------------

// detail::expand_burst sorts unconditionally, but under this layout the walk
// is in fact already non-decreasing for a positive stride, and saying why is
// worth the lines because the split is exactly the part that could have broken
// it. On KH, KW and COUT the block index is non-decreasing in the coordinate
// and the stride is positive, so the argument is BlockPackMapper's unchanged.
// On CIN it is not, because cin now feeds TWO digits with different strides
// and the low one WRAPS. Raising cin_blk by one either
//
//     raises cin_lo by 1                          -> line + 1
//     wraps cin_lo to 0 and raises cin_hi by 1    -> line + n_cin_lo *
//                                                    (n_cout_blocks - 1) + 1
//
// and the second is positive for every legal n_cout_blocks, including 1, where
// it degenerates to +1. So line_of is strictly increasing in cin_blk and the
// sort is over an already sorted range.
void SplitCinMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    detail::expand_burst(kName, *this, b, out);
}

// When the caller passes the num_sets this mapper's n_cin_lo was built for,
// the set index locate returns is cin_lo and nothing else. That equality is
// the layout's whole purpose and it is pinned in the tests rather than
// asserted here, because locate must stay correct for any num_sets: L2 calls
// it with a different one through the same mapper. num_lines_ is an exact
// bound because the constructor computed it as one past the largest line this
// flatten can produce, not as the radix product.
Placement SplitCinMapper::locate(LineId line, std::int64_t num_sets) const {
    return detail::locate_line(kName, num_lines_, line, num_sets);
}

// --- the line size, decomposed -----------------------------------------------

// n_cin_lo is NOT among the terms, and its absence is the point: it changes
// where a line goes, never how big a line is.
std::string SplitCinMapper::line_size_terms(std::int64_t) const {
    return detail::line_size_terms(cin_block_, cout_block_, weight_bytes_);
}



std::optional<LineId> SplitCinMapper::neighbour(LineId line, Axis a,
                                                std::int32_t delta) const {
    if (line.get() < 0 || line.get() >= num_lines_) {
        detail::reject_range(kName, "SplitCinMapper::neighbour: line " +
                                        std::to_string(line.get()) + " outside [0, " +
                                        std::to_string(num_lines_) + ")");
    }
    // KH, KW and COUT are one digit each. CIN is SPLIT across cin_hi and
    // cin_lo, so a step of one cin block can carry between two digits, which is
    // exactly the case a prefetcher must not be asked to know about.
    if (a != Axis::CIN) {
        Digit d = Digit::KH;
        if (a == Axis::KW)       d = Digit::KW;
        else if (a == Axis::COUT) d = Digit::COUT;
        else if (a != Axis::KH)   throw std::logic_error("SplitCinMapper::neighbour: unknown Axis");
        const std::int64_t stride = digit_stride(d);
        const std::int64_t radix  = digit_radix(d);
        const std::int64_t blk    = (line.get() / stride) % radix;
        const std::int64_t want   = blk + delta;
        if (want < 0 || want >= radix) return std::nullopt;
        return LineId{line.get() + static_cast<std::int64_t>(delta) * stride};
    }
    const std::int64_t lo  = (line.get() / digit_stride(Digit::CIN_LO)) % n_cin_lo_;
    const std::int64_t hi  = (line.get() / digit_stride(Digit::CIN_HI)) % n_cin_hi_;
    const std::int64_t blk = hi * n_cin_lo_ + lo;
    const std::int64_t want = blk + delta;
    if (want < 0 || want >= n_cin_blocks_) return std::nullopt;
    const std::int64_t base = line.get() - hi * digit_stride(Digit::CIN_HI)
                                         - lo * digit_stride(Digit::CIN_LO);
    return LineId{base + (want / n_cin_lo_) * digit_stride(Digit::CIN_HI)
                       + (want % n_cin_lo_) * digit_stride(Digit::CIN_LO)};
}

}  // namespace cachesim
