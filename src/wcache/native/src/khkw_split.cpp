#include "wcache/khkw_split.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace wcache {
namespace {

constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("KhkwSplitMapper: " + what);
}

[[noreturn]] void reject_range(const std::string& what) {
    throw std::out_of_range("KhkwSplitMapper: " + what);
}

void positive_or_reject(const char* name, std::int64_t v) {
    if (v < 1) reject(std::string(name) + " must be >= 1, got " + std::to_string(v));
}

std::int64_t checked_mul(std::int64_t a, std::int64_t b, const char* what) {
    if (b > INT64_MAX / a) {
        reject(std::string(what) + " overflows a signed 64-bit value: " +
               std::to_string(a) + " * " + std::to_string(b));
    }
    return a * b;
}

std::int64_t blocks_covering(std::int32_t extent, std::int32_t block) {
    return (static_cast<std::int64_t>(extent) + block - 1) / block;
}

std::int32_t block_size_on(Axis a, std::int32_t cin_block, std::int32_t cout_block) {
    switch (a) {
        case Axis::KH:
        case Axis::KW:   return 1;
        case Axis::CIN:  return cin_block;
        case Axis::COUT: return cout_block;
    }
    throw std::logic_error("KhkwSplitMapper: unknown Axis in block_size_on");
}

}  // namespace

KhkwSplitMapper::KhkwSplitMapper(WeightShape shape,
                                 std::int32_t cin_block,
                                 std::int32_t cout_block,
                                 std::int32_t weight_bytes)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(shape, a);
        if (n < 1) {
            reject(std::string(axis_name(a)) + " extent must be >= 1, got " +
                   std::to_string(n));
        }
    }
    positive_or_reject("cin_block", cin_block);
    positive_or_reject("cout_block", cout_block);
    positive_or_reject("weight_bytes", weight_bytes);

    n_cin_blocks_  = blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = blocks_covering(shape.COUT, cout_block);

    // The kernel position, and the split. Both extents are int32 and already
    // checked positive, so the product cannot overflow int64.
    n_pos_    = static_cast<std::int64_t>(shape.KH) * shape.KW;
    n_pos_lo_ = std::min<std::int64_t>(kPosLoRadix, n_pos_);
    n_pos_hi_ = (n_pos_ + n_pos_lo_ - 1) / n_pos_lo_;

    line_size_bytes_ = checked_mul(checked_mul(cin_block, cout_block, "line_size_bytes"),
                                   weight_bytes, "line_size_bytes");

    stride_[static_cast<int>(Digit::POS_LO)] = 1;
    stride_[static_cast<int>(Digit::CIN)]    = n_pos_lo_;
    stride_[static_cast<int>(Digit::COUT)]   =
        checked_mul(n_cin_blocks_, n_pos_lo_, "COUT line stride");
    stride_[static_cast<int>(Digit::POS_HI)] =
        checked_mul(n_cout_blocks_, stride_[static_cast<int>(Digit::COUT)],
                    "POS_HI line stride");

    // The radix product, as the loose bound num_lines_ must not exceed. The
    // exact bound below is smaller whenever the split is ragged, which for a
    // 3x3 kernel it always is.
    const std::int64_t radix_product =
        checked_mul(n_pos_hi_, stride_[static_cast<int>(Digit::POS_HI)], "num_lines");

    // One past the largest line this flatten can produce, and not the radix
    // product: with n_pos = 9 and n_pos_lo = 8 the pair (pos_hi, pos_lo) takes
    // 9 of its 16 combinations, so the product overstates the id space by
    // nearly half and every coverage figure computed from it would be deflated.
    //
    // The position term is maximised by a loop rather than by evaluating it at
    // pos = n_pos - 1. The two digits pull in opposite directions, so the
    // largest sum is not in general at the largest pos, and a closed form here
    // would be a plausible wrong answer. The loop runs KH*KW times, once.
    std::int64_t pos_term_max = 0;
    for (std::int64_t pos = 0; pos < n_pos_; ++pos) {
        const std::int64_t term = (pos / n_pos_lo_) * stride_[static_cast<int>(Digit::POS_HI)] +
                                  (pos % n_pos_lo_);
        if (term > pos_term_max) pos_term_max = term;
    }
    num_lines_ = 1 + pos_term_max
        + (n_cout_blocks_ - 1) * stride_[static_cast<int>(Digit::COUT)]
        + (n_cin_blocks_ - 1)  * stride_[static_cast<int>(Digit::CIN)];

    if (num_lines_ < 1 || num_lines_ > radix_product) {
        reject("num_lines " + std::to_string(num_lines_) +
               " is outside (0, radix product " + std::to_string(radix_product) + "]");
    }
}

std::int64_t KhkwSplitMapper::digit_stride(Digit d) const {
    switch (d) {
        case Digit::POS_HI:
        case Digit::COUT:
        case Digit::CIN:
        case Digit::POS_LO:
            return stride_[static_cast<int>(d)];
    }
    throw std::logic_error("KhkwSplitMapper::digit_stride: unknown Digit");
}

std::int64_t KhkwSplitMapper::digit_radix(Digit d) const {
    switch (d) {
        case Digit::POS_HI: return n_pos_hi_;
        case Digit::COUT:   return n_cout_blocks_;
        case Digit::CIN:    return n_cin_blocks_;
        case Digit::POS_LO: return n_pos_lo_;
    }
    throw std::logic_error("KhkwSplitMapper::digit_radix: unknown Digit");
}

std::int64_t KhkwSplitMapper::block_len(Axis a) const {
    switch (a) {
        case Axis::KH:   return static_cast<std::int64_t>(shape_.KH);
        case Axis::KW:   return static_cast<std::int64_t>(shape_.KW);
        case Axis::CIN:  return n_cin_blocks_;
        case Axis::COUT: return n_cout_blocks_;
    }
    throw std::logic_error("KhkwSplitMapper::block_len: unknown Axis");
}

LineId KhkwSplitMapper::line_of(const Coord& c) const {
    for (Axis a : kAxes) {
        const std::int32_t v = coord_on(c, a);
        const std::int32_t n = extent_on(shape_, a);
        if (v < 0 || v >= n) {
            reject_range(std::string(axis_name(a)) + " coordinate out of range [0, " +
                         std::to_string(n) + "), got " + std::to_string(v));
        }
    }

    const auto blk_of = [&](Axis a) -> std::int64_t {
        return static_cast<std::int64_t>(coord_on(c, a)) /
               block_size_on(a, cin_block_, cout_block_);
    };

    const std::int64_t pos = static_cast<std::int64_t>(coord_on(c, Axis::KH)) * shape_.KW +
                             coord_on(c, Axis::KW);

    std::int64_t line = 0;
    line += (pos / n_pos_lo_)   * digit_stride(Digit::POS_HI);
    line += blk_of(Axis::COUT)  * digit_stride(Digit::COUT);
    line += blk_of(Axis::CIN)   * digit_stride(Digit::CIN);
    line += (pos % n_pos_lo_)   * digit_stride(Digit::POS_LO);
    return LineId{line};
}

// The contract layout.h states, discharged the way SplitCinMapper discharges
// it: the lines are built in a local vector so a call that throws part way
// leaves `out` untouched by construction, and the result is sorted and
// de-duplicated unconditionally.
//
// The sort is load-bearing here in a way it is not for the other two mappers. A
// burst along KH or KW walks `pos`, and line_of is NOT monotone in pos: raising
// pos from 7 to 8 wraps pos_lo to 0 and raises pos_hi, which under a small
// COUT x CIN grid can move the line down. Neither the increasing-ids guarantee
// nor the unique() below, which removes only ADJACENT equals, would hold
// without it.
void KhkwSplitMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    if (b.count < 1) {
        reject("burst count must be >= 1, got " + std::to_string(b.count));
    }
    positive_or_reject("burst stride", b.stride);

    const std::int32_t n     = extent_on(shape_, b.axis);
    const std::int64_t start = coord_on(b.anchor, b.axis);
    // int64 because count and stride are both int32 and their product is not:
    // a wild count would otherwise wrap into a valid-looking coordinate.
    const std::int64_t last  = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
    if (last < 0 || last >= n) {
        reject_range(std::string(axis_name(b.axis)) + " coordinate out of range [0, " +
                     std::to_string(n) + "), got " + std::to_string(last));
    }

    std::vector<LineId> lines;
    for (std::int32_t i = 0; i < b.count; ++i) {
        const std::int64_t v = start + static_cast<std::int64_t>(i) * b.stride;
        lines.push_back(line_of(with_coord_on(b.anchor, b.axis, static_cast<std::int32_t>(v))));
    }

    std::sort(lines.begin(), lines.end());
    lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
    out.insert(out.end(), lines.begin(), lines.end());
}

// Identical to the other two mappers, and that is the design rather than an
// accident: a layout moves which line an element lands on and leaves the
// cache's indexing alone. The range check runs BEFORE the division, because
// LineId is signed and a negative id would come back out of `line % num_sets`
// as a negative set index.
Placement KhkwSplitMapper::locate(LineId line, std::int64_t num_sets) const {
    const std::int64_t v = line.get();
    if (v < 0 || v >= num_lines_) {
        reject_range("line id out of range [0, " + std::to_string(num_lines_) + "), got " +
                     std::to_string(v));
    }
    return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};
}

// The same three factors, in the same order and with the same separator, as
// BlockPackMapper and SplitCinMapper: the three layouts produce the same line
// size out of the same config fields, and a reader should not be able to tell
// from the message which one they are looking at.
std::string KhkwSplitMapper::line_size_terms(std::int64_t) const {
    return "cin_block " + std::to_string(cin_block_) + " x cout_block " +
           std::to_string(cout_block_) + " x weight_bytes " +
           std::to_string(weight_bytes_);
}

}  // namespace wcache
