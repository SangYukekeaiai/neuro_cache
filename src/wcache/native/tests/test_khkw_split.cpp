// KhkwSplitMapper: the flatten, the placement it exists for, and the interface
// contracts every mapper owes.
//
// The property this layout is FOR is the one test_split_cin pins for its own
// layout and BlockPackMapper fails: one core, which owns a contiguous slice of
// COUT and nothing else, must still reach every L1 set. Here it holds because
// the two digits under the index are the kernel position and CIN, and a core
// sweeps both of them fully inside a tile.
#include <algorithm>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "mapper_conformance.h"
#include "wcache/block_pack.h"
#include "wcache/khkw_split.h"
#include "wcache/types.h"

namespace {

using namespace wcache;
using Digit = KhkwSplitMapper::Digit;

// V8, the campaign's running layer, at the 64-byte line the sweep's widest
// point uses: 16 CIN x 4 COUT x 1 byte.
const WeightShape kV8{3, 3, 512, 512};

// --- the flatten --------------------------------------------------------------

void test_the_four_strides() {
    check::group("the four strides");
    const KhkwSplitMapper m(kV8, 16, 4, 1);

    CHECK_EQ(m.n_cin_blocks(), 32);
    CHECK_EQ(m.n_cout_blocks(), 128);
    CHECK_EQ(m.n_pos(), 9);
    CHECK_EQ(m.n_pos_lo(), 8);
    CHECK_EQ(m.n_pos_hi(), 2);

    CHECK_EQ(m.digit_stride(Digit::POS_LO), 1);
    CHECK_EQ(m.digit_stride(Digit::CIN), 8);
    CHECK_EQ(m.digit_stride(Digit::COUT), 32 * 8);
    CHECK_EQ(m.digit_stride(Digit::POS_HI), 128 * 32 * 8);

    CHECK_EQ(m.digit_radix(Digit::POS_LO), 8);
    CHECK_EQ(m.digit_radix(Digit::CIN), 32);
    CHECK_EQ(m.digit_radix(Digit::COUT), 128);
    CHECK_EQ(m.digit_radix(Digit::POS_HI), 2);

    CHECK_EQ(m.line_size_bytes(), 64);
}

void test_line_of_the_hand_computed_case() {
    check::group("line_of, by hand");
    const KhkwSplitMapper m(kV8, 16, 4, 1);

    // pos = 0, everything else 0.
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}).get(), 0);
    // kh 0, kw 1 -> pos 1, which is pos_lo and therefore the unit step.
    CHECK_EQ(m.line_of(Coord{0, 1, 0, 0}).get(), 1);
    // kh 2, kw 1 -> pos 7, still inside the low digit.
    CHECK_EQ(m.line_of(Coord{2, 1, 0, 0}).get(), 7);
    // kh 2, kw 2 -> pos 8, the one position that wraps into pos_hi.
    CHECK_EQ(m.line_of(Coord{2, 2, 0, 0}).get(), 128 * 32 * 8);
    // cin 16 is cin block 1, one CIN step above the base.
    CHECK_EQ(m.line_of(Coord{0, 0, 16, 0}).get(), 8);
    // cout 4 is cout block 1.
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 4}).get(), 32 * 8);
    // A coordinate inside a block lands on the block's line, not past it.
    CHECK_EQ(m.line_of(Coord{0, 0, 31, 7}).get(), 32 * 8 + 8);
}

void test_the_flatten_is_injective_on_blocks() {
    check::group("injective on the block grid");
    const WeightShape shape{3, 3, 8, 12};
    const KhkwSplitMapper m(shape, 2, 3, 1);

    std::set<std::int64_t> seen;
    std::int64_t n = 0;
    for (std::int32_t kh = 0; kh < shape.KH; ++kh)
    for (std::int32_t kw = 0; kw < shape.KW; ++kw)
    for (std::int32_t ci = 0; ci < shape.CIN; ci += 2)
    for (std::int32_t co = 0; co < shape.COUT; co += 3) {
        const std::int64_t l = m.line_of(Coord{kh, kw, ci, co}).get();
        CHECK_TRUE(l >= 0 && l < m.num_lines().get());
        seen.insert(l);
        ++n;
    }
    CHECK_EQ(check::ssize(seen), n);
}

// num_lines is the exact bound and not the radix product. With 9 positions
// split at 8 the pair (pos_hi, pos_lo) reaches 9 of its 16 combinations, so a
// bound taken from the product would overstate the id space by nearly half and
// deflate every coverage figure computed from it.
void test_num_lines_is_tighter_than_the_radix_product() {
    check::group("num_lines vs the radix product");
    const KhkwSplitMapper m(kV8, 16, 4, 1);

    const std::int64_t product = m.n_pos_hi() * m.digit_stride(Digit::POS_HI);
    // pos = 8 gives pos_hi 1, pos_lo 0, so the largest line is
    // stride(POS_HI) + (128-1)*stride(COUT) + (32-1)*stride(CIN).
    const std::int64_t expect = 1 + 128 * 32 * 8 + 127 * 32 * 8 + 31 * 8;
    CHECK_EQ(m.num_lines().get(), expect);
    CHECK_TRUE(m.num_lines().get() < product);
}

// A 1x1 kernel has one position, so a fixed radix of 8 would pin pos_lo at 0,
// make every line a multiple of 8, and leave seven eighths of the L1 sets
// unreachable. The min against KH*KW is what stops that.
void test_a_one_by_one_kernel_does_not_lose_its_low_bits() {
    check::group("1x1 kernel");
    const KhkwSplitMapper m(WeightShape{1, 1, 64, 64}, 4, 4, 1);
    CHECK_EQ(m.n_pos(), 1);
    CHECK_EQ(m.n_pos_lo(), 1);
    CHECK_EQ(m.n_pos_hi(), 1);
    CHECK_EQ(m.digit_stride(Digit::CIN), 1);
    // 16 cin blocks x 16 cout blocks, contiguous.
    CHECK_EQ(m.num_lines().get(), 16 * 16);
}

// --- the placement this layout exists for -------------------------------------

// One core owns a contiguous slice of COUT. Under block_pack its pinned
// cout_blk sits in the low bits and starves the index; here it sits above CIN
// and contributes nothing to a 32-set L1, so the core reaches every set.
void test_one_core_reaches_every_l1_set() {
    check::group("one core, every set");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    const BlockPackMapper bp(kV8, 16, 4, 1);
    const std::int64_t sets = 32;  // 16 KB / 64-byte lines / 8 ways

    // Core 5 of 16: COUT [160, 192).
    std::set<std::int64_t> mine, theirs;
    for (std::int32_t kh = 0; kh < 3; ++kh)
    for (std::int32_t kw = 0; kw < 3; ++kw)
    for (std::int32_t ci = 0; ci < 512; ci += 16)
    for (std::int32_t co = 160; co < 192; co += 4) {
        mine.insert(m.locate(m.line_of(Coord{kh, kw, ci, co}), sets).set_index.get());
        theirs.insert(bp.locate(bp.line_of(Coord{kh, kw, ci, co}), sets).set_index.get());
    }
    CHECK_EQ(check::ssize(mine), sets);
    // Non-vacuous: the layout being compared against does NOT reach them all.
    CHECK_TRUE(check::ssize(theirs) < sets);
}

// The trade the 3-bit split makes: position 8 aliases onto position 0's set and
// is told apart by the tag. Worth pinning because it is the one place this
// layout deliberately gives something up.
void test_the_ninth_position_aliases_onto_the_first() {
    check::group("position 8 aliases position 0");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    const std::int64_t sets = 32;

    const Placement a = m.locate(m.line_of(Coord{0, 0, 0, 0}), sets);
    const Placement b = m.locate(m.line_of(Coord{2, 2, 0, 0}), sets);
    CHECK_EQ(a.set_index.get(), b.set_index.get());
    CHECK_TRUE(a.tag.get() != b.tag.get());
}

// locate must stay correct for any num_sets, because L2 calls it with a
// different one through the same mapper.
void test_locate_serves_both_levels() {
    check::group("locate at both levels");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    for (std::int64_t sets : {std::int64_t{32}, std::int64_t{512}}) {
        for (std::int64_t l = 0; l < m.num_lines().get(); l += 977) {
            const Placement p = m.locate(LineId{l}, sets);
            CHECK_TRUE(p.set_index.get() >= 0 && p.set_index.get() < sets);
            CHECK_EQ(p.tag.get() * sets + p.set_index.get(), l);
        }
    }
}

void test_locate_range_check_runs_before_the_division() {
    check::group("locate refuses an out-of-range id");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    CHECK_THROWS(std::out_of_range, m.locate(LineId{-1}, 32));
    CHECK_THROWS(std::out_of_range, m.locate(m.num_lines(), 32));
}

// --- the burst walk -----------------------------------------------------------

// A burst along KH walks `pos`, and line_of is not monotone in pos: raising it
// from 7 to 8 wraps pos_lo to 0 and raises pos_hi. Under a small COUT x CIN
// grid that can move the line DOWN, so expand's unconditional sort is what
// makes the increasing-ids guarantee hold rather than an argument about the
// walk order.
void test_a_kernel_burst_is_sorted_despite_the_wrap() {
    check::group("a KH burst is still increasing");
    const WeightShape shape{3, 3, 4, 4};
    const KhkwSplitMapper m(shape, 4, 4, 1);  // one CIN block, one COUT block

    std::vector<LineId> out;
    m.expand(Burst{Coord{0, 2, 0, 0}, Axis::KH, 3, 1}, out);
    CHECK_EQ(check::ssize(out), 3);
    CHECK_TRUE(std::is_sorted(out.begin(), out.end()));
    // Non-vacuous: the raw walk order is 2, 5, 8 -> lines 2, 5, and the wrap.
    CHECK_TRUE(out.back().get() > out.front().get());
    CHECK_EQ(out.back().get(), m.digit_stride(Digit::POS_HI));
}

// Every mapper is injective on block coordinates, so a burst touches the same
// NUMBER of lines under any nesting. app_support::lines_per_burst rests on
// this, since it sizes the L1 demand reserve from a BlockPackMapper even when
// the run uses another layout.
void test_it_agrees_with_block_pack_on_how_many_lines_a_burst_touches() {
    check::group("burst line counts match block_pack");
    const WeightShape shape{3, 3, 8, 12};
    for (std::int32_t cb : {1, 2, 4}) {
        for (std::int32_t ob : {1, 3, 6}) {
            const KhkwSplitMapper m(shape, cb, ob, 2);
            const BlockPackMapper bp(shape, cb, ob, 2);
            for (Axis a : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT}) {
                std::vector<LineId> x, y;
                const std::int32_t n = extent_on(shape, a);
                m.expand(Burst{Coord{0, 0, 0, 0}, a, n, 1}, x);
                bp.expand(Burst{Coord{0, 0, 0, 0}, a, n, 1}, y);
                CHECK_EQ(check::ssize(x), check::ssize(y));
            }
        }
    }
}

void test_expand_refusals_leave_out_untouched() {
    check::group("a refused burst appends nothing");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    std::vector<LineId> out{LineId{-777}};
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 1}, out));
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 0}, out));
    CHECK_THROWS(std::out_of_range, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 600, 1}, out));
    CHECK_EQ(check::ssize(out), 1);
    CHECK_EQ(out[0].get(), -777);
}

// --- refusals -----------------------------------------------------------------

void test_rejects_non_positive_extents_blocks_and_widths() {
    check::group("constructor refusals");
    CHECK_THROWS(std::invalid_argument, KhkwSplitMapper(WeightShape{0, 3, 4, 4}, 1, 1, 1));
    CHECK_THROWS(std::invalid_argument, KhkwSplitMapper(WeightShape{3, 3, 0, 4}, 1, 1, 1));
    CHECK_THROWS(std::invalid_argument, KhkwSplitMapper(kV8, 0, 4, 1));
    CHECK_THROWS(std::invalid_argument, KhkwSplitMapper(kV8, 16, 0, 1));
    CHECK_THROWS(std::invalid_argument, KhkwSplitMapper(kV8, 16, 4, 0));
}

void test_line_of_refuses_a_coordinate_outside_the_shape() {
    check::group("line_of refusals");
    const KhkwSplitMapper m(kV8, 16, 4, 1);
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{3, 0, 0, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 512, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 0, -1}));
}

// --- the interface ------------------------------------------------------------

void test_conformance() {
    const WeightShape shape{3, 3, 8, 12};
    const conformance::Env env = conformance::make_env(shape);
    conformance::run_all(KhkwSplitMapper(shape, 1, 1, 2), env,
                         "KhkwSplitMapper: one element per line");
    conformance::run_all(KhkwSplitMapper(shape, 4, 4, 2), env,
                         "KhkwSplitMapper: 4x4 blocks");
    conformance::run_all(KhkwSplitMapper(shape, 8, 12, 2), env,
                         "KhkwSplitMapper: a whole CIN x COUT plane per line");
    conformance::run_all(KhkwSplitMapper(shape, 3, 5, 2), env,
                         "KhkwSplitMapper: blocks that do not divide");

    // A kernel whose position count is under the split radix, and one over it.
    const WeightShape flat{1, 1, 8, 12};
    conformance::run_all(KhkwSplitMapper(flat, 2, 3, 1), conformance::make_env(flat),
                         "KhkwSplitMapper: 1x1 kernel");
    const WeightShape wide{7, 7, 8, 12};
    conformance::run_all(KhkwSplitMapper(wide, 2, 3, 1), conformance::make_env(wide),
                         "KhkwSplitMapper: 7x7 kernel");
}

}  // namespace

int main() {
    test_the_four_strides();
    test_line_of_the_hand_computed_case();
    test_the_flatten_is_injective_on_blocks();
    test_num_lines_is_tighter_than_the_radix_product();
    test_a_one_by_one_kernel_does_not_lose_its_low_bits();
    test_one_core_reaches_every_l1_set();
    test_the_ninth_position_aliases_onto_the_first();
    test_locate_serves_both_levels();
    test_locate_range_check_runs_before_the_division();
    test_a_kernel_burst_is_sorted_despite_the_wrap();
    test_it_agrees_with_block_pack_on_how_many_lines_a_burst_touches();
    test_expand_refusals_leave_out_untouched();
    test_rejects_non_positive_extents_blocks_and_widths();
    test_line_of_refuses_a_coordinate_outside_the_shape();
    test_conformance();
    return check::summary();
}
