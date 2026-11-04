// CinKhkwConcatMapper: CIN blocks and kernel position form one dense digit.
//
// A sibling of KhkwSplitMapper, not a flag or a subclass of its flatten (B10):
// a differently nested layout owns its line_of, bounds and neighbour arithmetic.
//
// --- what this layout does ---------------------------------------------------
//
//     pos = kh * KW + kw
//     d   = cin_blk * (KH*KW) + pos       in [0, D)
//     D   = n_cin_blocks * KH*KW
//
// The two digits nest, outermost first, as
//
//     [cout_blk][d]                     line = cout_blk * D + d
//
// Unlike the split position in khkw_split, all kernel positions occupy the
// same dense digit. A 3x3 kernel has nine positions, with no unused radix
// combinations and no special alias for its ninth position. num_lines is the
// exact product n_cout_blocks * D, including partial channel blocks.
//
// --- why the digits sit in that order ----------------------------------------
//
// A core sweeps CIN and position within its contiguous COUT slice. If D is
// smaller than the set count, consecutive COUT blocks extend the same dense
// interval, so COUT can supply the remaining set indices through modulo.
// Full reach still requires at least as many owned lines as sets. For 1x1,
// this reduces to [cout_blk][cin_blk], exactly as khkw_split does.
//
// No split-width argument: cin_lo_blocks remains the -1 sentinel.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "cachesim/layout/mapper.h"
#include "cachesim/types.h"

namespace cachesim {

class CinKhkwConcatMapper final : public AddressMapper {
public:
    enum class Digit : std::uint8_t { COUT = 0, D = 1 };

    // Same argument order and rejection vocabulary as KhkwSplitMapper.
    CinKhkwConcatMapper(WeightShape shape, std::int32_t cin_block,
                        std::int32_t cout_block, std::int32_t weight_bytes);

    void expand(const Burst& b, std::vector<LineId>& out) const override;
    Placement locate(LineId line, std::int64_t num_sets) const override;
    std::optional<LineId> neighbour(LineId line, Axis a, std::int32_t delta) const override;

    LineId line_of(const Coord& c) const;
    std::int64_t digit_stride(Digit d) const;
    std::int64_t digit_radix(Digit d) const;
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
    std::int64_t       n_d()           const { return n_d_; }

private:
    WeightShape shape_;
    std::int32_t cin_block_;
    std::int32_t cout_block_;
    std::int32_t weight_bytes_;
    std::int64_t n_cin_blocks_    = 0;
    std::int64_t n_cout_blocks_   = 0;
    std::int64_t n_pos_           = 0;
    std::int64_t n_d_             = 0;
    std::int64_t line_size_bytes_ = 0;
    std::int64_t num_lines_       = 0;
};

}  // namespace cachesim
