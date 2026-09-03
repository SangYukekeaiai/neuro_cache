// BlockPackMapper: the block-packed weight layout.
//
// Plan v3 Part 2.1, the address-generator row: the concrete AddressMapper
// shaped by `cin_block`, `cout_block`, `weight_bytes`. It packs a
// cin_block x cout_block sub-block of the [KH][KW][CIN][COUT] weight tensor
// into one line, so a line is named by
//
//     (kh, kw, cin / cin_block, cout / cout_block)
//
// flattened row-major in that order, which is Axis declaration order with CIN
// and COUT replaced by their block indices (A1b's carried obligation to A2:
// reordering Axis without reordering the flatten gives plausible, wrong line
// ids, and nothing else announces it). The flatten itself is increment A2c;
// what this increment fixes is the radix vector it will use, which is the same
// decision made one step earlier.
//
// This is the first header in the tree with a matching .cpp. The class is not
// header-only because its constructor is the only place the layout's
// invariants are established, and a body in the header would let a caller with
// a different -D or a different include order compile a different constructor
// into their translation unit than the library was built with. See
// CPP_NOTES.md section 20.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "wcache/layout.h"
#include "wcache/types.h"

namespace wcache {

// `final` because there is nothing here to specialise. B10 settled that a
// differently NESTED memory layout is a new AddressMapper subclass rather than
// a variant of this one, so a class deriving from BlockPackMapper would be
// inheriting the block-packed flatten in order to disagree with part of it,
// which is exactly the shape that makes a bug in one override invisible in the
// others. Deriving from AddressMapper instead costs four functions and is
// honest about sharing nothing.
class BlockPackMapper final : public AddressMapper {
public:
    // Argument order is pinned by tests/test_layout.cpp, which already carries
    // the call A2d will uncomment:
    //
    //     BlockPackMapper(shape, cin_block, cout_block, weight_bytes)
    //
    // The three block and width parameters are int32, matching WeightShape's
    // extents and Burst's count and stride (B8): one width across the whole
    // coordinate and block arithmetic, so the mixed-signedness, mixed-width
    // expression that produced the v1 line_of bug has nowhere to form.
    //
    // weight_bytes is a constructor argument rather than something the caller
    // carries separately because it is a format v2 header field arriving with
    // the same trace as the shape, and because the alternative is CacheLevel
    // plumbing it separately and recomputing cin_block * cout_block *
    // weight_bytes, giving two places that can disagree about the size of a
    // line. That was v1 finding D2.
    //
    // Throws std::invalid_argument, naming the offending parameter and its
    // value, for a non-positive extent, block or element width, and for a
    // configuration whose line size or line count does not fit in int64.
    BlockPackMapper(WeightShape shape,
                    std::int32_t cin_block,
                    std::int32_t cout_block,
                    std::int32_t weight_bytes);

    // --- the two entry points (A2d) -------------------------------------------
    //
    // Both are built out of the three public pieces below, and both hold to
    // layout.h's contracts rather than to anything specific to this layout.
    //
    // `expand` walks `b.axis` from the anchor by `b.stride`, flattens each
    // element with `line_of`, and appends the distinct lines in strictly
    // increasing order. A burst with `count < 1` throws std::invalid_argument,
    // a burst that leaves the layer's shape throws std::out_of_range, and
    // either way nothing is appended.
    //
    // `locate` range-checks `line` against `num_lines()` before it divides, and
    // throws std::out_of_range outside it.
    void expand(const Burst& b, std::vector<LineId>& out) const override;
    Placement locate(LineId line, std::int64_t num_sets) const override;
    std::optional<LineId> neighbour(LineId line, Axis a, std::int32_t delta) const override;

    // --- the flatten (A2c) ---------------------------------------------------
    //
    // Public for the same reason the derived-state accessors below are: without
    // them the flatten is observable only through `expand`, which does not
    // exist yet, so A2c could not be tested on its own terms. They are also the
    // three pieces `expand` and `locate` are built out of at A2d, so exposing
    // them costs nothing that A2d does not expose anyway.
    //
    // `line_stride` returns std::int64_t and NOT LineId. A stride is a delta,
    // not an address, and LineId is a Tagged with no arithmetic (A1a), so a
    // stride typed as LineId could not be multiplied by a coordinate without
    // stripping the tag at every use. v1 returned LineId here; A1's typing is
    // what makes that no longer possible. The board carries this as the A2b to
    // A2c obligation.
    //
    // `block_len` is the extent along `a` measured in whole LINES, so KH and KW
    // report the raw extent and CIN and COUT report their block counts. It is
    // the "how many distinct block indices exist on this axis" number. It is
    // deliberately NOT what a range check compares against: a burst carries
    // element coordinates, so `expand` and `line_of` both check the shape,
    // which is the strictly stronger bound (a cin of 100 under CIN = 100 with
    // cin_block = 32 divides to a legal block 3 while naming an element the
    // layer does not have).
    //
    // Both throw std::logic_error for an Axis outside the enumerators, which is
    // the convention extent_on and coord_on already set in types.h: refuse
    // rather than invent an answer.
    std::int64_t line_stride(Axis a) const;
    std::int64_t block_len(Axis a) const;

    // The flatten itself, B17's order made arithmetic:
    //
    //     line = sum over the four axes of block_index(c, a) * line_stride(a)
    //
    // where block_index is the raw coordinate on KH and KW and the coordinate
    // divided by the block size on CIN and COUT.
    //
    // Throws std::out_of_range, NOT the constructor's std::invalid_argument,
    // for a coordinate outside the layer's shape (N11, V15). The two must stay
    // distinguishable: a bad configuration and a bad coordinate are found at
    // different times by different callers. layout.h states the three-tier
    // vocabulary both follow.
    LineId line_of(const Coord& c) const;

    // --- fixed at construction ----------------------------------------------
    //
    // Both are pure derivation from the constructor arguments, so they are
    // one-liners over members the constructor already checked. Neither reads
    // the shape at call time and neither can fail.
    LineId       num_lines()       const override { return LineId{num_lines_}; }
    std::int64_t line_size_bytes() const override { return line_size_bytes_; }

    // The three constructor arguments line_size_bytes_ is the product of, named
    // and with their values, for SetAssociativeArray's exactness message (A4b).
    // Out of line rather than beside the two above because it builds a string,
    // which is the constructor's file's business rather than the header's.
    //
    // The line size the caller read is ignored here: this override names the
    // factors it multiplies its own members out of, so it needs nothing from
    // the caller. The parameter exists for the interface's default (layout.h).
    std::string line_size_terms(std::int64_t line_bytes) const override;

    // --- the derived state, exposed ------------------------------------------
    //
    // Not decoration and not for the engine, which only ever sees the four
    // AddressMapper members above. These exist because without them the
    // constructor's arithmetic is unobservable: num_lines() is the product
    // KH * KW * n_cin_blocks * n_cout_blocks, so swapping n_cin_blocks_ and
    // n_cout_blocks_, or taking a floor where the layout takes a ceiling in
    // one of them and compensating in the other, leaves num_lines() unchanged
    // and would first show up at A2c as a wrong line stride. Reporting the two
    // block counts separately is what lets this increment be tested on its own
    // terms rather than through code that does not exist yet.
    const WeightShape& shape()          const { return shape_; }
    std::int32_t       cin_block()      const { return cin_block_; }
    std::int32_t       cout_block()     const { return cout_block_; }
    std::int32_t       weight_bytes()   const { return weight_bytes_; }
    std::int64_t       n_cin_blocks()   const { return n_cin_blocks_; }
    std::int64_t       n_cout_blocks()  const { return n_cout_blocks_; }

private:
    WeightShape  shape_;
    std::int32_t cin_block_;
    std::int32_t cout_block_;
    std::int32_t weight_bytes_;

    // Derived, and int64 rather than int32 or LineId.
    //
    // int64 because a block count is a factor of a line count and the line
    // count is a LineId, which is int64; keeping the factors narrower than the
    // product is the boundary the v1 signedness class lived on (n_cin_blocks()
    // returned int64 while num_lines() returned uint64 and both fed the same
    // expression).
    //
    // num_lines_ is a plain int64 and not a LineId because Tagged has no
    // default constructor (B2), so a LineId member would have to be given its
    // value in the constructor's initialiser list, which runs BEFORE the body
    // where the validation lives. Storing the int64 and wrapping it in
    // num_lines() keeps the order "check, then derive" rather than "derive,
    // then check". Zero-initialised here so that a constructor that throws
    // leaves no member indeterminate.
    std::int64_t n_cin_blocks_   = 0;
    std::int64_t n_cout_blocks_  = 0;
    std::int64_t line_size_bytes_ = 0;
    std::int64_t num_lines_      = 0;

    // The four line strides, indexed by static_cast<int>(Axis), not four
    // separately named members. Board obligation B24 to A2c: with the radices
    // in an array, a future permutation parameter is an edit to the one
    // function that fills the array, and `line_of`, `expand` and `locate` read
    // it without knowing the order. Four named members would put the order
    // into every reader instead. The four static_asserts at
    // block_pack.cpp:32-35 pin the enumerator values and exist to make this
    // indexing safe.
    //
    // int64 for the same reason the block counts are: a stride is a factor of
    // a line count, and keeping a factor narrower than its product is the
    // boundary the v1 signedness bug lived on. Zero-initialised so a
    // constructor that throws before filling them leaves nothing
    // indeterminate.
    std::int64_t stride_[4]      = {0, 0, 0, 0};
};

}  // namespace wcache
