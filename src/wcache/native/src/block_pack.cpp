#include "wcache/block_pack.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// The four axes in declaration order. Written out once so the validation loop
// below is written once, and so the order this file depends on is stated
// rather than inlined into a loop body.
constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

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

// One spelling of the prefix, so every message this file produces is findable
// by grepping for the class name and no two of them disagree about the
// punctuation.
[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("BlockPackMapper: " + what);
}

// The same prefix, a different type. A configuration the caller built wrong is
// std::invalid_argument and is found once, at construction; a coordinate
// outside the layer's shape is std::out_of_range and is found per call, while
// the trace is being replayed. Keeping them distinguishable is what lets a
// caller catch one and not the other, and what lets a test say which it
// expected rather than only that something was thrown.
//
// The choice of std::out_of_range is layout.h's, stated there as one of three
// tiers: invalid_argument for an argument malformed at every layer,
// out_of_range for one that is well formed but outside this layer, and
// logic_error for programmer error.
[[noreturn]] void reject_range(const std::string& what) {
    throw std::out_of_range("BlockPackMapper: " + what);
}

// N11 asks that a range failure be diagnosable, and a message that only
// asserts the rule ("block sizes must be positive", which is what v1 said) does
// not say WHICH block or what it was. The value is always printed, because the
// interesting cases are 0 from a field the config loader forgot to set and a
// negative from a header decoded at the wrong offset, and those two look
// nothing alike in a log.
void positive_or_reject(const char* name, std::int32_t v) {
    if (v < 1) reject(std::string(name) + " must be >= 1, got " + std::to_string(v));
}

// Signed overflow is undefined behaviour, not wraparound, so an unchecked
// product here is not "a wrong number under -DNDEBUG" but "the optimiser is
// entitled to assume it did not happen". Both products this constructor forms
// are folds of small positive factors, so the check is one division per
// multiply, once per mapper, and it buys the guarantee that num_lines_ is a
// real bound: everything downstream that compares against it (the engine's tag
// check, locate's own range check at A2d, D2's coverage division) is only
// meaningful if it is.
//
// Both arguments are known positive at every call site, which is why the
// a != 0 guard the general form needs is not written: the caller has already
// run positive_or_reject or a ceiling division of positive operands.
std::int64_t checked_mul(std::int64_t a, std::int64_t b, const char* what) {
    if (b > INT64_MAX / a) {
        reject(std::string(what) + " overflows a signed 64-bit value: " +
               std::to_string(a) + " * " + std::to_string(b));
    }
    return a * b;
}

// Blocks needed to cover `extent`, rounding up.
//
// Ceiling, not floor, and not a divisibility requirement: a short final block
// still occupies a whole line. See EXPLAIN.md for why rounding up rather than
// rejecting a non-dividing block, and why block > extent is a legal degenerate
// case rather than an error. The short version is that the corpus makes the
// rounding path unreachable at every power-of-two block up to 64 (every layer
// has CIN and COUT in {64, 128, 256, 512}) while the tiny verification trace
// has CIN = 1 and COUT = 4, so rejecting would cost the fixture and buy
// nothing on the corpus.
//
// The widening cast puts the whole expression in int64 before the + block - 1,
// so a large extent cannot wrap into a small block count. `extent` and `block`
// are both int32 and both already checked positive, so this cannot divide by
// zero and cannot go negative.
std::int64_t blocks_covering(std::int32_t extent, std::int32_t block) {
    return (static_cast<std::int64_t>(extent) + block - 1) / block;
}

// The block size along `a`: the divisor that turns a coordinate into a block
// index. KH and KW are not blocked, and the honest way to say that is that
// their block size is 1, rather than giving line_of a branch that treats two
// axes as special. With this, the flatten is one loop over the four axes with
// no per-axis code in it.
//
// The two block sizes are passed in rather than read from a member because
// this is a file-local free function, which is where types.h puts its own
// per-axis switches (extent_on, coord_on, axis_name) and keeps the four-way
// switch out of the class.
std::int32_t block_size_on(Axis a, std::int32_t cin_block, std::int32_t cout_block) {
    switch (a) {
        case Axis::KH:
        case Axis::KW:   return 1;
        case Axis::CIN:  return cin_block;
        case Axis::COUT: return cout_block;
    }
    // Unreachable, and refusing rather than defaulting to 1: a fallback of 1
    // would make an unknown axis flatten as if it were unblocked, which is a
    // plausible wrong line id rather than a visible failure. Same reasoning as
    // types.h's coord_on.
    throw std::logic_error("BlockPackMapper: unknown Axis in block_size_on");
}

}  // namespace

BlockPackMapper::BlockPackMapper(WeightShape shape,
                                 std::int32_t cin_block,
                                 std::int32_t cout_block,
                                 std::int32_t weight_bytes)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    // Every extent, not only the two that are blocked. KH and KW are radices
    // in the flatten just as much as the block counts are, so a KW of 0
    // collapses the KH stride to zero and makes two different (kh, kw) pairs
    // name the same line, which is a silently wrong hit rate rather than a
    // crash. Looping over kAxes rather than writing four `if`s means the
    // message names the axis without four copies of the message.
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
    // neighbouring line rather than an obviously wrong one. That is the same
    // trap v1 recorded on line_of: signedness alone does not keep a bad value
    // visible, only a check does.
    positive_or_reject("cin_block", cin_block);
    positive_or_reject("cout_block", cout_block);
    // Not a layout radix at all: weight_bytes only scales line_size_bytes. It
    // is checked here anyway because a zero would make line_size_bytes zero,
    // and D1 divides cache_size_bytes by it to get a set count.
    positive_or_reject("weight_bytes", weight_bytes);

    // Deliberately NOT checked: cin_block > CIN, cout_block > COUT, and a
    // block that does not divide its extent. Both are legal and both mean the
    // same thing, one short block. The cost is padding, not incorrectness, and
    // padding is a statistic (D2) rather than a configuration error.
    n_cin_blocks_  = blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = blocks_covering(shape.COUT, cout_block);

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
    line_size_bytes_ = checked_mul(checked_mul(cin_block, cout_block, "line_size_bytes"),
                                   weight_bytes, "line_size_bytes");

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
    num_lines_ = checked_mul(
        checked_mul(checked_mul(shape.KH, shape.KW, "num_lines"), n_cin_blocks_, "num_lines"),
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
        checked_mul(n_cin_blocks_, n_cout_blocks_, "KW line stride");
    stride_[static_cast<int>(Axis::KH)]   =
        checked_mul(shape.KW, stride_[static_cast<int>(Axis::KW)], "KH line stride");
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
    std::int64_t line = 0;

    // One loop over kAxes rather than the nested-Horner spelling in the comment
    // at the top of this file. They compute the same number, and this one reads
    // the order out of stride_ instead of building it into the expression,
    // which is what B24 asks for: the order lives in the constructor and
    // nowhere else.
    for (Axis a : kAxes) {
        const std::int32_t v = coord_on(c, a);

        // Checked against the layer's SHAPE, not against block_len.
        //
        // The coordinate is an element coordinate, so the shape is the range it
        // actually has to lie in, and that check is strictly the stronger of the
        // two. Under CIN = 100 with cin_block = 32 there are 4 blocks: a cin of
        // 100 divides to block 3 and would pass a block_len check while naming
        // an element the layer does not contain, and a cin of -1 divides to
        // block 0 and would pass it too. Integer division truncates toward
        // zero, so every cin in [-(cin_block - 1), -1] lands on block 0 and no
        // amount of signedness makes it visible; only this check does. That is
        // the v1 lesson the archive preserved, and checking the quotient rather
        // than the coordinate would throw it away.
        //
        // The cost of not routing through block_len is that block_len has no
        // second caller yet and so is only as good as its own tests. That is
        // the reviewer's to cover, and it is the better trade: sharing the path
        // would also share a failure mode across the range check and the
        // flatten.
        const std::int32_t n = extent_on(shape_, a);
        if (v < 0 || v >= n) {
            reject_range(std::string(axis_name(a)) + " coordinate out of range [0, " +
                         std::to_string(n) + "), got " + std::to_string(v));
        }

        // v and the block size are both non-negative int32 here, so the
        // division cannot be the truncation trap above and cannot overflow.
        // The quotient is widened before the multiply, so the product is formed
        // in int64 and not in int32.
        const std::int32_t block = block_size_on(a, cin_block_, cout_block_);
        line += static_cast<std::int64_t>(v / block) * line_stride(a);
    }

    // The LineId is constructed once, at the end, out of arithmetic that was
    // done in plain int64. A1's Tagged has no arithmetic on purpose, so this is
    // the only shape the flatten can take: compute the delta sum, then name it.
    return LineId{line};
}

// --- A2d: the burst walk and the placement -----------------------------------

// The elements of a burst are anchor, anchor + stride, ... along b.axis, and
// the lines it touches are their flattens with the duplicates removed, since a
// block-packed line holds several elements of a walked axis whenever that axis
// is blocked. Four things the contract asks for that are not free:
//
//  - Every range check before the first append. The lines are built in a local
//    vector and appended to `out` only at the end, so a call that throws part
//    way leaves `out` untouched by construction rather than by a rollback that
//    has to be got right. The cost is one allocation per call.
//
//  - Strictly increasing ids, which layout.h makes an obligation on the
//    implementation rather than a property of the layout, so this sorts
//    unconditionally instead of arguing that it need not. Under this layout the
//    walk is already increasing for a positive stride, because a block index is
//    non-decreasing in its coordinate and every line stride is positive, so the
//    sort is over an already sorted range and the unconditional call costs a
//    comparison pass. A burst walking backwards is what it is there for.
//
//  - A burst with count < 1 is std::invalid_argument, not out_of_range: a
//    request for no elements is malformed whatever layer it is applied to.
//
//  - The far end of the walk computed in int64. `count` and `stride` are both
//    int32 (B8) and their product is not, so a wild count would wrap into a
//    valid-looking coordinate: with an anchor of 0 and stride 2^30, element 4
//    is at 2^32, which truncates to a perfectly legal 0. Checking both ends
//    also covers every element between them, since the walk is affine in the
//    element index, and it is what makes the narrowing to int32 below a
//    conversion of a value already known to fit.
void BlockPackMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    if (b.count < 1) {
        reject("burst count must be >= 1, got " + std::to_string(b.count));
    }

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
        // line_of checks all four coordinates against the shape, so the anchor's
        // other three are validated by the first element rather than by a pass
        // of their own, and the walked one is re-checked at no cost.
        lines.push_back(line_of(with_coord_on(b.anchor, b.axis, static_cast<std::int32_t>(v))));
    }

    std::sort(lines.begin(), lines.end());
    lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
    out.insert(out.end(), lines.begin(), lines.end());
}

// The range check is the whole of this function's difficulty, and it runs
// BEFORE the division. LineId is signed (B5), so a negative id would come back
// out of `line % num_sets` as a negative set index, and the postcondition
// 0 <= set_index < num_sets would be an assumption rather than a fact.
// num_lines_ is an exact bound because the constructor's checked products made
// it one.
Placement BlockPackMapper::locate(LineId line, std::int64_t num_sets) const {
    const std::int64_t v = line.get();
    if (v < 0 || v >= num_lines_) {
        reject_range("line id out of range [0, " + std::to_string(num_lines_) + "), got " +
                     std::to_string(v));
    }
    // `line == tag * num_sets + set_index` is the definition of the pair, and
    // both operands are non-negative here, so these are the ordinary division
    // and remainder rather than the truncate-toward-zero trap the constructor's
    // negative-block check exists for.
    return Placement{v % num_sets, v / num_sets};
}

}  // namespace wcache
