#include "cachesim/layout/cin_khkw_concat.h"

#include <stdexcept>
#include <string>

#include "layout_common.h"
#include "cachesim/index/set_index.h"

namespace cachesim {
namespace {

constexpr const char* kName = "CinKhkwConcatMapper";

}  // namespace

CinKhkwConcatMapper::CinKhkwConcatMapper(WeightShape shape, std::int32_t cin_block,
                                       std::int32_t cout_block, std::int32_t weight_bytes)
    : shape_(shape), cin_block_(cin_block), cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    detail::check_shape_and_blocking(kName, shape, cin_block, cout_block, weight_bytes);
    n_cin_blocks_ = detail::blocks_covering(shape.CIN, cin_block);
    n_cout_blocks_ = detail::blocks_covering(shape.COUT, cout_block);
    n_pos_ = static_cast<std::int64_t>(shape.KH) * shape.KW;
    n_d_ = detail::checked_mul(kName, n_cin_blocks_, n_pos_, "D line radix");
    num_lines_ = detail::checked_mul(kName, n_cout_blocks_, n_d_, "num_lines");
    line_size_bytes_ = detail::line_size_bytes(kName, cin_block, cout_block, weight_bytes);
}

std::int64_t CinKhkwConcatMapper::digit_stride(Digit d) const {
    switch (d) {
        case Digit::COUT: return n_d_;
        case Digit::D:    return 1;
    }
    throw std::logic_error("CinKhkwConcatMapper::digit_stride: unknown Digit");
}

std::int64_t CinKhkwConcatMapper::digit_radix(Digit d) const {
    switch (d) {
        case Digit::COUT: return n_cout_blocks_;
        case Digit::D:    return n_d_;
    }
    throw std::logic_error("CinKhkwConcatMapper::digit_radix: unknown Digit");
}

std::int64_t CinKhkwConcatMapper::block_len(Axis a) const {
    switch (a) {
        case Axis::KH:   return shape_.KH;
        case Axis::KW:   return shape_.KW;
        case Axis::CIN:  return n_cin_blocks_;
        case Axis::COUT: return n_cout_blocks_;
    }
    throw std::logic_error("CinKhkwConcatMapper::block_len: unknown Axis");
}

LineId CinKhkwConcatMapper::line_of(const Coord& c) const {
    detail::check_in_shape(kName, shape_, c);
    const std::int64_t pos = static_cast<std::int64_t>(coord_on(c, Axis::KH)) * shape_.KW
                            + coord_on(c, Axis::KW);
    const std::int64_t ci = coord_on(c, Axis::CIN) / cin_block_;
    const std::int64_t co = coord_on(c, Axis::COUT) / cout_block_;
    return LineId{co * n_d_ + ci * n_pos_ + pos};
}

void CinKhkwConcatMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    detail::expand_burst(kName, *this, b, out);
}

Placement CinKhkwConcatMapper::locate(LineId line, std::int64_t num_sets) const {
    if (line.get() < 0 || line.get() >= num_lines_) {
        detail::reject_range(kName, "line id out of range [0, " +
                                   std::to_string(num_lines_) + "), got " +
                                   std::to_string(line.get()));
    }
    return set_index(line, num_sets);
}

std::string CinKhkwConcatMapper::line_size_terms(std::int64_t) const {
    return detail::line_size_terms(cin_block_, cout_block_, weight_bytes_);
}

std::optional<LineId> CinKhkwConcatMapper::neighbour(LineId line, Axis a,
                                                   std::int32_t delta) const {
    if (line.get() < 0 || line.get() >= num_lines_) {
        detail::reject_range(kName, "line id out of range [0, " +
                                   std::to_string(num_lines_) + "), got " +
                                   std::to_string(line.get()));
    }
    const std::int64_t d = line.get() % n_d_;
    if (a == Axis::CIN || a == Axis::COUT) {
        const std::int64_t block = a == Axis::CIN ? d / n_pos_ : line.get() / n_d_;
        const std::int64_t want = block + delta;
        if (want < 0 || want >= block_len(a)) return std::nullopt;
        const std::int64_t stride = a == Axis::CIN ? n_pos_ : n_d_;
        return LineId{line.get() + static_cast<std::int64_t>(delta) * stride};
    }
    if (a != Axis::KH && a != Axis::KW) {
        throw std::logic_error("CinKhkwConcatMapper::neighbour: unknown Axis");
    }
    const std::int64_t pos = d % n_pos_;
    const std::int64_t kh = pos / shape_.KW;
    const std::int64_t kw = pos % shape_.KW;
    const std::int64_t nkh = kh + (a == Axis::KH ? delta : 0);
    const std::int64_t nkw = kw + (a == Axis::KW ? delta : 0);
    if (nkh < 0 || nkh >= shape_.KH || nkw < 0 || nkw >= shape_.KW) return std::nullopt;
    return LineId{line.get() - pos + nkh * shape_.KW + nkw};
}

}  // namespace cachesim
