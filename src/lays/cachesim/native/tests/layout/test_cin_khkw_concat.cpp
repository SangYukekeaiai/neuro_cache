// CinKhkwConcatMapper: dense block coverage, GEMM equivalence, placement,
// neighbour boundaries, and the interface contracts every mapper owes.
#include <algorithm>
#include <cstdint>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "mapper_conformance.h"
#include "cachesim/config.h"
#include "cachesim/enum_names.h"
#include "cachesim/layout/block_pack.h"
#include "cachesim/layout/cin_khkw_concat.h"
#include "cachesim/layout/factory.h"
#include "cachesim/layout/khkw_split.h"

namespace {

using namespace cachesim;
using Digit = CinKhkwConcatMapper::Digit;
const WeightShape kV8{3, 3, 512, 512};

void test_the_two_digits_and_hand_computed_flatten() {
    check::group("two dense digits and hand-computed line ids");
    const CinKhkwConcatMapper m(kV8, 16, 4, 1);
    CHECK_EQ(m.n_cin_blocks(), 32);
    CHECK_EQ(m.n_cout_blocks(), 128);
    CHECK_EQ(m.n_pos(), 9);
    CHECK_EQ(m.n_d(), 288);
    CHECK_EQ(m.digit_stride(Digit::D), 1);
    CHECK_EQ(m.digit_stride(Digit::COUT), 288);
    CHECK_EQ(m.digit_radix(Digit::D), 288);
    CHECK_EQ(m.digit_radix(Digit::COUT), 128);
    CHECK_EQ(m.num_lines().get(), 36864);
    CHECK_EQ(m.line_size_bytes(), 64);
    CHECK_TRUE(m.line_size_terms(64) == "cin_block 16 x cout_block 4 x weight_bytes 1");
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}).get(), 0);
    CHECK_EQ(m.line_of(Coord{0, 1, 0, 0}).get(), 1);
    CHECK_EQ(m.line_of(Coord{2, 1, 0, 0}).get(), 7);
    CHECK_EQ(m.line_of(Coord{2, 2, 0, 0}).get(), 8);
    CHECK_EQ(m.line_of(Coord{0, 0, 16, 0}).get(), 9);
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 4}).get(), 288);
    CHECK_EQ(m.line_of(Coord{2, 2, 31, 7}).get(), 305);
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}), LineId{36863});
    CHECK_THROWS(std::logic_error, m.digit_stride(static_cast<Digit>(99)));
    CHECK_THROWS(std::logic_error, m.digit_radix(static_cast<Digit>(99)));
    CHECK_THROWS(std::logic_error, m.block_len(static_cast<Axis>(99)));
}

void test_dense_bijection_with_non_dividing_blocks() {
    check::group("every block hits [0, num_lines) exactly once, including partial blocks");
    for (const WeightShape shape : {WeightShape{3, 3, 7, 11}, WeightShape{1, 1, 7, 11}}) {
        const CinKhkwConcatMapper m(shape, 3, 4, 2);
        std::set<std::int64_t> seen;
        for (std::int32_t kh = 0; kh < shape.KH; ++kh)
        for (std::int32_t kw = 0; kw < shape.KW; ++kw)
        for (std::int32_t ci = 0; ci < shape.CIN; ci += 3)
        for (std::int32_t co = 0; co < shape.COUT; co += 4) {
            const auto line = m.line_of(Coord{kh, kw, ci, co});
            CHECK_TRUE(seen.insert(line.get()).second);
        }
        CHECK_EQ(m.num_lines().get(), shape.KH * shape.KW * 3 * 3);
        CHECK_EQ(check::ssize(seen), m.num_lines().get());
        std::int64_t expected = 0;
        for (std::int64_t line : seen) CHECK_EQ(line, expected++);
        // Elements inside each block share its line, including the ragged tail.
        for (std::int32_t kh = 0; kh < shape.KH; ++kh)
        for (std::int32_t kw = 0; kw < shape.KW; ++kw)
        for (std::int32_t ci = 0; ci < shape.CIN; ++ci)
        for (std::int32_t co = 0; co < shape.COUT; ++co) {
            CHECK_EQ(m.line_of(Coord{kh, kw, ci, co}),
                     m.line_of(Coord{kh, kw, (ci / 3) * 3, (co / 4) * 4}));
        }
    }
}

void test_one_by_one_matches_khkw_split_line_for_line() {
    check::group("1x1 equivalence to khkw_split at every element");
    for (const WeightShape shape : {WeightShape{1, 1, 7, 11}, WeightShape{1, 1, 32, 64}})
    for (std::int32_t cb : {1, 3, 16, 64})
    for (std::int32_t ob : {1, 4, 5, 128}) {
        const CinKhkwConcatMapper m(shape, cb, ob, 1);
        const KhkwSplitMapper old(shape, cb, ob, 1);
        CHECK_EQ(m.num_lines(), old.num_lines());
        for (std::int32_t ci = 0; ci < shape.CIN; ++ci)
        for (std::int32_t co = 0; co < shape.COUT; ++co) {
            const Coord c{0, 0, ci, co};
            CHECK_EQ(m.line_of(c), old.line_of(c));
        }
    }
}

void test_placement_and_small_d_coverage() {
    check::group("placement at either level, without ninth-position aliasing");
    const CinKhkwConcatMapper m(kV8, 16, 4, 1);
    for (std::int64_t sets : {7, 32, 512}) {
        for (std::int64_t line = 0; line < m.num_lines().get(); line += 977) {
            const Placement p = m.locate(LineId{line}, sets);
            CHECK_TRUE(p.set_index.get() >= 0 && p.set_index.get() < sets);
            CHECK_EQ(p.tag.get() * sets + p.set_index.get(), line);
        }
    }
    CHECK_TRUE(m.locate(m.line_of(Coord{0, 0, 0, 0}), 32).set_index
               != m.locate(m.line_of(Coord{2, 2, 0, 0}), 32).set_index);
    std::set<std::int64_t> core_sets;
    for (std::int32_t kh = 0; kh < 3; ++kh)
    for (std::int32_t kw = 0; kw < 3; ++kw)
    for (std::int32_t ci = 0; ci < 512; ci += 16)
    for (std::int32_t co = 160; co < 192; co += 4) {
        core_sets.insert(m.locate(m.line_of(Coord{kh, kw, ci, co}), 32).set_index.get());
    }
    CHECK_EQ(check::ssize(core_sets), 32);

    check::group("COUT tops up D < sets, but too few owned lines cannot cover");
    // Four COUT blocks per core, eight CIN blocks: 32 consecutive lines.
    const CinKhkwConcatMapper small(WeightShape{1, 1, 128, 256}, 16, 4, 1);
    CHECK_EQ(small.n_d(), 8);
    for (std::int32_t core = 0; core < 16; ++core) {
        std::set<std::int64_t> reached;
        for (std::int32_t ci = 0; ci < 128; ci += 16)
        for (std::int32_t co = core * 16; co < (core + 1) * 16; co += 4) {
            reached.insert(small.locate(small.line_of(Coord{0, 0, ci, co}), 32).set_index.get());
        }
        CHECK_EQ(check::ssize(reached), 32);
    }
    // A non-power-of-two D=3 also covers after 11 COUT blocks, not after 10.
    const CinKhkwConcatMapper odd(WeightShape{1, 1, 40, 88}, 16, 4, 1);
    for (std::int32_t count : {10, 11}) {
        std::set<std::int64_t> reached;
        for (std::int32_t ci = 0; ci < 40; ci += 16)
        for (std::int32_t co = 44; co < 44 + count * 4; co += 4) {
            reached.insert(odd.locate(odd.line_of(Coord{0, 0, ci, co}), 32).set_index.get());
        }
        CHECK_EQ(check::ssize(reached), count == 10 ? 30 : 32);
    }
}

void test_neighbours_follow_axes_without_wrapping() {
    check::group("neighbours preserve other axes and stop at shape edges");
    for (const WeightShape shape : {WeightShape{3, 5, 7, 11}, WeightShape{1, 1, 7, 11}}) {
        const CinKhkwConcatMapper m(shape, 3, 4, 1);
        for (std::int32_t kh = 0; kh < shape.KH; ++kh)
        for (std::int32_t kw = 0; kw < shape.KW; ++kw)
        for (std::int32_t ci = 0; ci < shape.CIN; ci += 3)
        for (std::int32_t co = 0; co < shape.COUT; co += 4)
        for (Axis axis : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT})
        for (std::int32_t delta : {INT32_MIN, -4, -1, 0, 1, 4, INT32_MAX}) {
            const Coord c{kh, kw, ci, co};
            const std::int64_t step = axis == Axis::CIN ? 3 : axis == Axis::COUT ? 4 : 1;
            const std::int64_t want = coord_on(c, axis) + static_cast<std::int64_t>(delta) * step;
            const auto next = m.neighbour(m.line_of(c), axis, delta);
            const bool inside = want >= 0 && want < extent_on(shape, axis);
            CHECK_EQ(next.has_value(), inside);
            if (inside && next) {
                CHECK_EQ(*next, m.line_of(with_coord_on(c, axis, static_cast<std::int32_t>(want))));
            }
        }
    }
}

void test_refusals_and_overflow() {
    check::group("constructor, coordinate, placement and neighbour refusals");
    for (std::int32_t bad : {-1, 0}) {
        for (const WeightShape shape : {WeightShape{bad, 3, 512, 512},
                                       WeightShape{3, bad, 512, 512},
                                       WeightShape{3, 3, bad, 512},
                                       WeightShape{3, 3, 512, bad}}) {
            CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(shape, 16, 4, 1));
        }
    }
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(kV8, 0, 4, 1));
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(kV8, 16, -1, 1));
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(kV8, 16, 4, 0));
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(WeightShape{INT32_MAX, INT32_MAX, 3, 1}, 1, 1, 1));
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(WeightShape{INT32_MAX, INT32_MAX, 1, 3}, 1, 1, 1));
    CHECK_THROWS(std::invalid_argument, CinKhkwConcatMapper(WeightShape{1, 1, 1, 1}, INT32_MAX, INT32_MAX, 3));
    const CinKhkwConcatMapper m(WeightShape{3, 3, 7, 11}, 3, 4, 1);
    for (Axis a : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT}) {
        CHECK_THROWS(std::out_of_range, m.line_of(with_coord_on(Coord{0, 0, 0, 0}, a, -1)));
        CHECK_THROWS(std::out_of_range, m.line_of(with_coord_on(Coord{0, 0, 0, 0}, a, extent_on(m.shape(), a))));
    }
    CHECK_THROWS(std::out_of_range, m.locate(LineId{-1}, 32));
    CHECK_THROWS(std::out_of_range, m.locate(m.num_lines(), 32));
    CHECK_THROWS(std::invalid_argument, m.locate(LineId{0}, 0));
    CHECK_THROWS(std::out_of_range, m.neighbour(LineId{-1}, Axis::CIN, 1));
    CHECK_THROWS(std::out_of_range, m.neighbour(m.num_lines(), Axis::COUT, -1));
    CHECK_THROWS(std::logic_error, m.neighbour(LineId{0}, static_cast<Axis>(99), 0));
}

void test_config_and_factory() {
    check::group("config spelling, sentinel validation, and factory construction");
    RunConfig cfg = parse_config(R"({"layout":"cin_khkw_concat","cin_block":16,"cout_block":4})");
    CHECK_TRUE(cfg.layout == LayoutKind::CinKhkwConcat);
    CHECK_TRUE(std::string(name_of(cfg.layout)) == "cin_khkw_concat");
    std::vector<Warning> warnings;
    validate(cfg, 1, warnings);
    CHECK_EQ(cfg.cin_lo_blocks, -1);
    const auto mapper = make_mapper(cfg, kV8, warnings);
    CHECK_TRUE(dynamic_cast<CinKhkwConcatMapper*>(mapper.get()) != nullptr);
    CHECK_EQ(mapper->num_lines().get(), 36864);
    for (std::int64_t width : {-2, 0, 32}) {
        cfg.cin_lo_blocks = width;
        CHECK_THROWS(std::invalid_argument, validate(cfg, 1, warnings));
    }
}

void test_burst_counts_and_conformance() {
    const WeightShape shape{3, 3, 8, 12};
    for (std::int32_t cb : {1, 3, 4, 8})
    for (std::int32_t ob : {1, 4, 5, 12}) {
        const CinKhkwConcatMapper m(shape, cb, ob, 2);
        const BlockPackMapper bp(shape, cb, ob, 2);
        for (Axis a : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT}) {
            std::vector<LineId> x, y;
            const Burst burst{Coord{0, 0, 0, 0}, a, extent_on(shape, a), 1};
            m.expand(burst, x);
            bp.expand(burst, y);
            CHECK_EQ(check::ssize(x), check::ssize(y));
        }
        conformance::run_all(m, conformance::make_env(shape), "CinKhkwConcatMapper: blocking grid");
    }
    for (const WeightShape other : {WeightShape{1, 1, 8, 12}, WeightShape{7, 7, 8, 12}}) {
        conformance::run_all(CinKhkwConcatMapper(other, 3, 5, 1), conformance::make_env(other),
                             "CinKhkwConcatMapper: 1x1 and 7x7 kernels");
    }
}

}  // namespace

int main() {
    test_the_two_digits_and_hand_computed_flatten();
    test_dense_bijection_with_non_dividing_blocks();
    test_one_by_one_matches_khkw_split_line_for_line();
    test_placement_and_small_d_coverage();
    test_neighbours_follow_axes_without_wrapping();
    test_refusals_and_overflow();
    test_config_and_factory();
    test_burst_counts_and_conformance();
    return check::summary();
}
