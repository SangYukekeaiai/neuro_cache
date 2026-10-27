#include "cachesim/khkw_split.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "layout_common.h"

namespace cachesim {
namespace {

constexpr const char* kName = "KhkwSplitMapper";

}  // namespace

KhkwSplitMapper::KhkwSplitMapper(WeightShape shape,
                                 std::int32_t cin_block,
                                 std::int32_t cout_block,
                                 std::int32_t weight_bytes)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    detail::check_shape_and_blocking(kName, shape, cin_block, cout_block, weight_bytes);

    n_cin_blocks_  = detail::blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = detail::blocks_covering(shape.COUT, cout_block);

    // The kernel position, and the split. Both extents are int32 and already
    // checked positive, so the product cannot overflow int64.
    n_pos_    = static_cast<std::int64_t>(shape.KH) * shape.KW;
    n_pos_lo_ = std::min<std::int64_t>(kPosLoRadix, n_pos_);
    n_pos_hi_ = (n_pos_ + n_pos_lo_ - 1) / n_pos_lo_;

    line_size_bytes_ = detail::line_size_bytes(kName, cin_block, cout_block, weight_bytes);

    stride_[static_cast<int>(Digit::POS_LO)] = 1;
    stride_[static_cast<int>(Digit::CIN)]    = n_pos_lo_;
    stride_[static_cast<int>(Digit::COUT)]   =
        detail::checked_mul(kName, n_cin_blocks_, n_pos_lo_, "COUT line stride");
    stride_[static_cast<int>(Digit::POS_HI)] =
        detail::checked_mul(kName, n_cout_blocks_, stride_[static_cast<int>(Digit::COUT)],
                            "POS_HI line stride");

    // The radix product, as the loose bound num_lines_ must not exceed. The
    // exact bound below is smaller whenever the split is ragged, which for a
    // 3x3 kernel it always is.
    const std::int64_t radix_product =
        detail::checked_mul(kName, n_pos_hi_, stride_[static_cast<int>(Digit::POS_HI)],
                            "num_lines");

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
        detail::reject(kName, "num_lines " + std::to_string(num_lines_) +
                       " is outside (0, radix product " + std::to_string(radix_product) +
                       "]");
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
    detail::check_in_shape(kName, shape_, c);

    const auto blk_of = [&](Axis a) -> std::int64_t {
        return static_cast<std::int64_t>(coord_on(c, a)) /
               detail::block_size_on(kName, a, cin_block_, cout_block_);
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

// The sort in detail::expand_burst is load-bearing here in a way it is not for
// the other two mappers. A burst along KH or KW walks `pos`, and line_of is NOT
// monotone in pos: raising pos from 7 to 8 wraps pos_lo to 0 and raises
// pos_hi, which under a small COUT x CIN grid can move the line down.
void KhkwSplitMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    detail::expand_burst(kName, *this, b, out);
}

Placement KhkwSplitMapper::locate(LineId line, std::int64_t num_sets) const {
    return detail::locate_line(kName, num_lines_, line, num_sets);
}

std::string KhkwSplitMapper::line_size_terms(std::int64_t) const {
    return detail::line_size_terms(cin_block_, cout_block_, weight_bytes_);
}



std::optional<LineId> KhkwSplitMapper::neighbour(LineId line, Axis a,
                                                 std::int32_t delta) const {
    if (line.get() < 0 || line.get() >= num_lines_) {
        detail::reject_range(kName, "KhkwSplitMapper::neighbour: line " +
                                        std::to_string(line.get()) + " outside [0, " +
                                        std::to_string(num_lines_) + ")");
    }
    // CIN and COUT are each ONE digit here, so they are one stride away. KH and
    // KW are two digits of the split position and need the position rebuilt,
    // which is the whole reason this arithmetic belongs to the mapper.
    if (a == Axis::CIN || a == Axis::COUT) {
        const Digit d = (a == Axis::CIN) ? Digit::CIN : Digit::COUT;
        const std::int64_t stride = digit_stride(d);
        const std::int64_t radix  = digit_radix(d);
        const std::int64_t blk    = (line.get() / stride) % radix;
        const std::int64_t want   = blk + delta;
        if (want < 0 || want >= radix) return std::nullopt;
        return LineId{line.get() + static_cast<std::int64_t>(delta) * stride};
    }
    if (a != Axis::KH && a != Axis::KW) {
        throw std::logic_error("KhkwSplitMapper::neighbour: unknown Axis");
    }
    // pos = kh * KW + kw, stored as (pos / n_pos_lo, pos % n_pos_lo).
    const std::int64_t pos_lo = (line.get() / digit_stride(Digit::POS_LO)) % n_pos_lo_;
    const std::int64_t pos_hi = line.get() / digit_stride(Digit::POS_HI);
    const std::int64_t pos    = pos_hi * n_pos_lo_ + pos_lo;
    const std::int64_t kw     = pos % shape_.KW;
    const std::int64_t kh     = pos / shape_.KW;
    const std::int64_t nkh    = (a == Axis::KH) ? kh + delta : kh;
    const std::int64_t nkw    = (a == Axis::KW) ? kw + delta : kw;
    if (nkh < 0 || nkh >= shape_.KH || nkw < 0 || nkw >= shape_.KW) return std::nullopt;
    const std::int64_t npos = nkh * shape_.KW + nkw;
    const std::int64_t base = line.get() - pos_hi * digit_stride(Digit::POS_HI)
                                         - pos_lo * digit_stride(Digit::POS_LO);
    return LineId{base + (npos / n_pos_lo_) * digit_stride(Digit::POS_HI)
                       + (npos % n_pos_lo_) * digit_stride(Digit::POS_LO)};
}

}  // namespace cachesim
