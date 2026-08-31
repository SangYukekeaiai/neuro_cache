#include "wcache/split_cin.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace wcache {
namespace {

// The four axes in declaration order, for the range-check loop. Same list as
// block_pack.cpp's, written out again rather than shared: see the note on the
// duplicated helpers below.
constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

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

// --- helpers duplicated from block_pack.cpp ----------------------------------
//
// Five of the six below differ from their counterparts in exactly one way that
// cannot be shared: the message prefix names the class, and a message that
// says "BlockPackMapper" out of a SplitCinMapper constructor sends a reader to
// the wrong file. reject, reject_range, positive_or_reject and checked_mul are
// therefore genuinely per-class, and only blocks_covering and block_size_on
// are true duplicates, at three lines each.
//
// Extracting the two pure ones into a shared internal header would mean
// editing block_pack.cpp, which this unit has no other reason to touch and
// whose tests are the ones that currently hold the flatten down. That is a
// refactor to do once both mappers are settled and both suites are green, not
// while adding the second one. Recorded here so the duplication is a decision
// with a date rather than an oversight.

[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("SplitCinMapper: " + what);
}

[[noreturn]] void reject_range(const std::string& what) {
    throw std::out_of_range("SplitCinMapper: " + what);
}

// The value is always printed, because the interesting cases are a 0 from a
// field the config loader forgot to set and a negative from a header decoded
// at the wrong offset, and those two look nothing alike in a log.
void positive_or_reject(const char* name, std::int64_t v) {
    if (v < 1) reject(std::string(name) + " must be >= 1, got " + std::to_string(v));
}

// Signed overflow is undefined behaviour, not wraparound, so an unchecked
// product here is not "a wrong number under -DNDEBUG" but "the optimiser is
// entitled to assume it did not happen". Both arguments are known positive at
// every call site, which is why the a != 0 guard the general form needs is not
// written.
std::int64_t checked_mul(std::int64_t a, std::int64_t b, const char* what) {
    if (b > INT64_MAX / a) {
        reject(std::string(what) + " overflows a signed 64-bit value: " +
               std::to_string(a) + " * " + std::to_string(b));
    }
    return a * b;
}

// Blocks needed to cover `extent`, rounding up. Ceiling, not floor, and not a
// divisibility requirement: a short final block still occupies a whole line.
std::int64_t blocks_covering(std::int32_t extent, std::int32_t block) {
    return (static_cast<std::int64_t>(extent) + block - 1) / block;
}

// The same ceiling, over two int64 operands, for the split. n_cin_blocks_ is
// already int64 by the time this is called, so it cannot reuse the int32 form
// above, and the addition is done on values the constructor has already
// checked positive.
std::int64_t ceil_div(std::int64_t a, std::int64_t b) {
    return (a + b - 1) / b;
}

// The block size along `a`: the divisor that turns a coordinate into a block
// index. KH and KW are not blocked, and the honest way to say that is that
// their block size is 1, rather than giving line_of a branch that treats two
// axes as special.
std::int32_t block_size_on(Axis a, std::int32_t cin_block, std::int32_t cout_block) {
    switch (a) {
        case Axis::KH:
        case Axis::KW:   return 1;
        case Axis::CIN:  return cin_block;
        case Axis::COUT: return cout_block;
    }
    // Refusing rather than defaulting to 1: a fallback would make an unknown
    // axis flatten as if it were unblocked, which is a plausible wrong line id
    // rather than a visible failure.
    throw std::logic_error("SplitCinMapper: unknown Axis in block_size_on");
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
    // Every extent, not only the two that are blocked. KH and KW are radices
    // in the flatten just as much as the block counts are, so a KW of 0
    // collapses the KH stride to zero and makes two different (kh, kw) pairs
    // name the same line, which is a silently wrong hit rate rather than a
    // crash.
    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(shape, a);
        if (n < 1) {
            reject(std::string(axis_name(a)) + " extent must be >= 1, got " +
                   std::to_string(n));
        }
    }

    // A block of 0 would divide by zero in the flatten; a negative one would
    // make the block index follow the sign of the coordinate, and integer
    // division truncating toward zero means the damage is a plausible
    // neighbouring line rather than an obviously wrong one.
    positive_or_reject("cin_block", cin_block);
    positive_or_reject("cout_block", cout_block);
    positive_or_reject("weight_bytes", weight_bytes);

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
    positive_or_reject("n_cin_lo", n_cin_lo);
    n_cin_lo_ = n_cin_lo;

    n_cin_blocks_  = blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = blocks_covering(shape.COUT, cout_block);

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
    line_size_bytes_ = checked_mul(checked_mul(cin_block, cout_block, "line_size_bytes"),
                                   weight_bytes, "line_size_bytes");

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
    const std::int64_t radix_product = checked_mul(
        checked_mul(
            checked_mul(checked_mul(shape.KH, shape.KW, "num_lines"), n_cin_hi_, "num_lines"),
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
        checked_mul(n_cout_blocks_, n_cin_lo_, "CIN_HI line stride");
    stride_[static_cast<int>(Digit::KW)] =
        checked_mul(n_cin_hi_, stride_[static_cast<int>(Digit::CIN_HI)], "KW line stride");
    stride_[static_cast<int>(Digit::KH)] =
        checked_mul(shape.KW, stride_[static_cast<int>(Digit::KW)], "KH line stride");

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
        reject("num_lines " + std::to_string(num_lines_) +
               " is outside (0, radix product " + std::to_string(radix_product) + "]");
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
    // The range check is a loop over the four AXES and the accumulation below
    // is over the five DIGITS. They are deliberately two passes rather than
    // one fused loop: the check is a property of the coordinate and the
    // accumulation is a property of the layout, and fusing them would need an
    // array indexed by one enum and read by the other, where Axis::CIN and
    // Digit::CIN_HI are both 2 with nothing to tell them apart.
    for (Axis a : kAxes) {
        const std::int32_t v = coord_on(c, a);

        // Checked against the layer's SHAPE, not against block_len.
        //
        // The coordinate is an element coordinate, so the shape is the range
        // it actually has to lie in, and that check is strictly the stronger of
        // the two. Under CIN = 100 with cin_block = 32 there are 4 blocks: a
        // cin of 100 divides to block 3 and would pass a block_len check while
        // naming an element the layer does not contain, and a cin of -1 divides
        // to block 0 and would pass it too. Integer division truncates toward
        // zero, so every cin in [-(cin_block - 1), -1] lands on block 0 and no
        // amount of signedness makes it visible; only this check does.
        const std::int32_t n = extent_on(shape_, a);
        if (v < 0 || v >= n) {
            reject_range(std::string(axis_name(a)) + " coordinate out of range [0, " +
                         std::to_string(n) + "), got " + std::to_string(v));
        }
    }

    // Every coordinate is now known to be in [0, extent), so each division is
    // of two non-negative values and cannot be the truncation trap above. The
    // quotient is widened before the multiply, so every product is formed in
    // int64.
    const auto blk_of = [&](Axis a) -> std::int64_t {
        return static_cast<std::int64_t>(coord_on(c, a)) /
               block_size_on(a, cin_block_, cout_block_);
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

// The elements of a burst are anchor, anchor + stride, ... along b.axis, and
// the lines it touches are their flattens with the duplicates removed, since a
// packed line holds several elements of a walked axis whenever that axis is
// blocked. Four things the contract asks for that are not free:
//
//  - Every range check before the first append. The lines are built in a local
//    vector and appended to `out` only at the end, so a call that throws part
//    way leaves `out` untouched by construction rather than by a rollback that
//    has to be got right. The cost is one allocation per call.
//
//  - Strictly increasing ids, which layout.h makes an obligation on the
//    IMPLEMENTATION rather than a property a layout is free to have, so this
//    sorts unconditionally instead of arguing that it need not.
//
//    Under this layout the walk is in fact already non-decreasing for a
//    positive stride, and saying why is worth the lines because the split is
//    exactly the part that could have broken it. On KH, KW and COUT the block
//    index is non-decreasing in the coordinate and the stride is positive, so
//    the argument is BlockPackMapper's unchanged. On CIN it is not, because cin
//    now feeds TWO digits with different strides and the low one WRAPS. Raising
//    cin_blk by one either
//
//        raises cin_lo by 1                          -> line + 1
//        wraps cin_lo to 0 and raises cin_hi by 1    -> line + n_cin_lo *
//                                                       (n_cout_blocks - 1) + 1
//
//    and the second is positive for every legal n_cout_blocks, including 1,
//    where it degenerates to +1. So line_of is strictly increasing in cin_blk
//    and the sort is over an already sorted range.
//
//    The sort is kept anyway. It is what makes the obligation structural rather
//    than something re-argued per layout, and unique() removes only ADJACENT
//    equals, so without it the de-duplication would rest on that same
//    monotonicity argument too.
//
//  - A burst with count < 1, or with stride < 1, is std::invalid_argument and
//    not out_of_range: a request for no elements, and a run that stands still
//    or walks backwards, are malformed whatever layer they are applied to.
//
//  - The far end of the walk computed in int64. `count` and `stride` are both
//    int32 and their product is not, so a wild count would wrap into a
//    valid-looking coordinate: with an anchor of 0 and stride 2^30, element 4
//    is at 2^32, which truncates to a perfectly legal 0. Checking both ends
//    also covers every element between them, since the walk is affine in the
//    element index.
void SplitCinMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    if (b.count < 1) {
        reject("burst count must be >= 1, got " + std::to_string(b.count));
    }
    // The constructor's spelling of the same rule, reused so the two messages
    // cannot drift apart.
    positive_or_reject("burst stride", b.stride);

    const std::int32_t n     = extent_on(shape_, b.axis);
    const std::int64_t start = coord_on(b.anchor, b.axis);
    const std::int64_t last  = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
    if (last < 0 || last >= n) {
        reject_range(std::string(axis_name(b.axis)) + " coordinate out of range [0, " +
                     std::to_string(n) + "), got " + std::to_string(last));
    }

    // Not reserved to b.count: the count is untrusted, and reserving it would
    // turn a burst with a wild count into a bad_alloc before the walk could
    // name the coordinate that was wrong.
    std::vector<LineId> lines;
    for (std::int32_t i = 0; i < b.count; ++i) {
        const std::int64_t v = start + static_cast<std::int64_t>(i) * b.stride;
        // line_of checks all four coordinates against the shape, so the
        // anchor's other three are validated by the first element rather than
        // by a pass of their own, and the walked one is re-checked at no cost.
        lines.push_back(line_of(with_coord_on(b.anchor, b.axis, static_cast<std::int32_t>(v))));
    }

    std::sort(lines.begin(), lines.end());
    lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
    out.insert(out.end(), lines.begin(), lines.end());
}

// Identical to BlockPackMapper::locate, and that is the point of the whole
// design rather than an accident: this layout moves which line an element
// lands on, and leaves the cache's indexing alone. Nothing in CacheLevel,
// SetAssociativeArray or the policies changes to support it.
//
// The range check is the whole of this function's difficulty, and it runs
// BEFORE the division. LineId is signed, so a negative id would come back out
// of `line % num_sets` as a negative set index, and the postcondition
// 0 <= set_index < num_sets would be an assumption rather than a fact.
// num_lines_ is an exact bound because the constructor computed it as one past
// the largest line this flatten can produce, not as the radix product.
Placement SplitCinMapper::locate(LineId line, std::int64_t num_sets) const {
    const std::int64_t v = line.get();
    if (v < 0 || v >= num_lines_) {
        reject_range("line id out of range [0, " + std::to_string(num_lines_) + "), got " +
                     std::to_string(v));
    }
    // `line == tag * num_sets + set_index` is the definition of the pair, and
    // both operands are non-negative here, so these are the ordinary division
    // and remainder rather than the truncate-toward-zero trap.
    //
    // When the caller passes the num_sets this mapper's n_cin_lo was built for,
    // the set index it returns is cin_lo and nothing else. That equality is
    // the layout's whole purpose and it is pinned in the tests rather than
    // asserted here, because locate must stay correct for any num_sets: L2
    // calls it with a different one through the same mapper.
    return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};
}

// --- the line size, decomposed -----------------------------------------------

// The three factors of line_size_bytes_, in the order the constructor
// multiplies them, so that a reader who sees "96-byte lines" in
// SetAssociativeArray's refusal can reach the config fields that produced the
// 96. The product itself is not repeated: the caller has already printed it,
// and a second copy is a second thing that can disagree with the first. That is
// also why the line size the caller passes is unused here.
//
// n_cin_lo is NOT among the terms, and its absence is the point: it changes
// where a line goes, never how big a line is.
// The separator is " x " and the parameter is unnamed, both matching
// BlockPackMapper::line_size_terms exactly. The two mappers produce the same
// three factors and a reader should not be able to tell from the message which
// one they are looking at, since the answer is the same either way.
std::string SplitCinMapper::line_size_terms(std::int64_t) const {
    return "cin_block " + std::to_string(cin_block_) + " x cout_block " +
           std::to_string(cout_block_) + " x weight_bytes " +
           std::to_string(weight_bytes_);
}

}  // namespace wcache
