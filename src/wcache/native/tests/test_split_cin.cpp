// Units W1 and W2: SplitCinMapper, end to end.
//
// W1 was the constructor, the accessors and line_of. W2 added expand and
// locate, and with them the interface suite of tests/mapper_conformance.h,
// which is parameterised over `const AddressMapper&` and could not run until
// both existed.
//
// Four things this file pins, in the order they matter:
//
//   1. The property the whole layout exists for: `line_of(c) % n_cin_lo`
//      equals `(cin / cin_block) % n_cin_lo` for EVERY coordinate in the
//      layer. That is what makes the L1 set index a function of cin alone,
//      and it is checked exhaustively on a small shape and on the real V8
//      geometry rather than argued from the strides.
//
//   2. The flatten is injective. A layout that collided would report reuse
//      that is not there, which is a plausible wrong hit rate rather than a
//      crash, so this is checked by construction over the whole coordinate
//      space of a small shape.
//
//   3. The one number that distinguishes this layout from BlockPackMapper's:
//      the digit order. A hand-computed line id for the case worked through in
//      SET_INDEX_COLLAPSE.md, plus a direct check that a unit step in cin now
//      moves the line by 1 rather than by n_cout_blocks.
//
//   4. Every rejection path fires, throws std::invalid_argument, carries the
//      "SplitCinMapper: " prefix, and prints the offending value.
//
// The negative half, whether a wrong split_cin.cpp makes this file go red, is
// what tests/mutation_check.sh is for.
#include <wcache/split_cin.h>
#include <wcache/block_pack.h>
#include <wcache/layout.h>
#include <wcache/types.h>

#include <cstdint>
#include <cstdio>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "mapper_conformance.h"

using namespace wcache;

namespace {

// The real V8 geometry at config C2: vgg16 layer_08_features_27 under a 16 KB
// 8-way L1 with 16-byte lines, which is 128 sets. Every number in
// SET_INDEX_COLLAPSE.md is this shape, so a check written against it can be
// compared with what was measured on the trace.
constexpr WeightShape kV8{3, 3, 512, 512};
constexpr std::int32_t kCinBlock  = 1;
constexpr std::int32_t kCoutBlock = 16;
constexpr std::int32_t kWeightB   = 1;
constexpr std::int64_t kSets      = 128;

// A small shape for the exhaustive passes. 3 * 3 * 8 * 8 = 576 coordinates at
// block 1, which is small enough to enumerate in full and large enough that
// every digit takes more than one value. n_cin_lo of 4 divides 8, so this
// shape exercises the dense case; the ragged case gets its own test below.
constexpr WeightShape kSmall{3, 3, 8, 8};

// Reports the message as well as the type, because a rejection that fires for
// the wrong reason still throws std::invalid_argument. Returns the message so
// one reporter can check the prefix, the parameter name, and the value.
std::string message_of(void (*f)()) {
    try {
        f();
    } catch (const std::exception& e) {
        return e.what();
    }
    return "(no exception)";
}

bool contains(const std::string& hay, const std::string& needle) {
    return hay.find(needle) != std::string::npos;
}

// --- 1. the property the layout exists for -----------------------------------

// `line % n_cin_lo == cin_blk % n_cin_lo`, for every coordinate. Exhaustive on
// the small shape: 576 coordinates, no sampling, so a digit order that happened
// to work for the coordinates a random pass drew cannot slip through.
void test_set_index_is_cin_alone_small() {
    check::group("set index is cin alone, exhaustive on 3x3x8x8");
    for (std::int64_t lo : {1, 2, 4, 8}) {
        const SplitCinMapper m(kSmall, 1, 1, 1, lo);
        bool all_match = true;
        for (std::int32_t kh = 0; kh < kSmall.KH; ++kh)
            for (std::int32_t kw = 0; kw < kSmall.KW; ++kw)
                for (std::int32_t ci = 0; ci < kSmall.CIN; ++ci)
                    for (std::int32_t co = 0; co < kSmall.COUT; ++co) {
                        const std::int64_t line = m.line_of(Coord{kh, kw, ci, co}).get();
                        if (line % lo != ci % lo) all_match = false;
                    }
        CHECK_TRUE(all_match);
    }
}

// The same property on the real geometry, where cin_block is 1, cout_block is
// 16 and n_cin_lo is 128. 3 * 3 * 512 * 512 is 2.36M coordinates, so this walks
// cout by cout_block instead of by 1: every cout inside one block flattens to
// the same line, which test_cout_block_folds below is what pins.
void test_set_index_is_cin_alone_v8() {
    check::group("set index is cin alone, V8 at 128 sets");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    bool all_match = true;
    std::set<std::int64_t> sets_reached;
    for (std::int32_t kh = 0; kh < kV8.KH; ++kh)
        for (std::int32_t kw = 0; kw < kV8.KW; ++kw)
            for (std::int32_t ci = 0; ci < kV8.CIN; ++ci)
                for (std::int32_t co = 0; co < kV8.COUT; co += kCoutBlock) {
                    const std::int64_t line = m.line_of(Coord{kh, kw, ci, co}).get();
                    if (line % kSets != ci % kSets) all_match = false;
                    sets_reached.insert(line % kSets);
                }
    CHECK_TRUE(all_match);

    // The measured claim, restated as a test: cin sweeps 0..511, so cin % 128
    // takes all 128 values and the layer reaches every set. Under
    // BlockPackMapper one core reached 8.
    CHECK_EQ(check::ssize(sets_reached), kSets);
}

// The half of the mechanism that makes the above useful: a core owning ONE
// cout block still reaches every set, because its set index does not depend on
// cout at all. This is the check that would have failed on the old layout.
void test_one_cout_block_still_reaches_every_set() {
    check::group("a single cout block reaches every set");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    std::set<std::int64_t> sets_reached;
    // cout 0..15 is cout block 0, which is all core 0 touches inside a tile.
    for (std::int32_t kh = 0; kh < kV8.KH; ++kh)
        for (std::int32_t kw = 0; kw < kV8.KW; ++kw)
            for (std::int32_t ci = 0; ci < kV8.CIN; ++ci) {
                const std::int64_t line = m.line_of(Coord{kh, kw, ci, 0}).get();
                sets_reached.insert(line % kSets);
            }
    CHECK_EQ(check::ssize(sets_reached), kSets);
}

// --- 2. injectivity ----------------------------------------------------------

// Distinct (kh, kw, cin block, cout block) tuples get distinct lines, and every
// line is inside [0, num_lines()). Exhaustive on the small shape at two block
// sizes, so the fold from elements to blocks is exercised as well as the
// flatten.
void test_flatten_is_injective_and_in_range() {
    check::group("flatten is injective and stays inside num_lines");
    for (std::int32_t blk : {1, 2}) {
        for (std::int64_t lo : {1, 2, 4}) {
            const SplitCinMapper m(kSmall, blk, blk, 1, lo);
            std::set<std::int64_t> seen;
            bool in_range = true;
            std::int64_t tuples = 0;
            for (std::int32_t kh = 0; kh < kSmall.KH; ++kh)
                for (std::int32_t kw = 0; kw < kSmall.KW; ++kw)
                    for (std::int32_t ci = 0; ci < kSmall.CIN; ci += blk)
                        for (std::int32_t co = 0; co < kSmall.COUT; co += blk) {
                            const std::int64_t line = m.line_of(Coord{kh, kw, ci, co}).get();
                            if (line < 0 || line >= m.num_lines().get()) in_range = false;
                            seen.insert(line);
                            ++tuples;
                        }
            CHECK_TRUE(in_range);
            CHECK_EQ(check::ssize(seen), tuples);
        }
    }
}

// Every cout inside one cout block folds to the same line, and every cin inside
// one cin block folds to the same line. This is what makes the walk in
// test_set_index_is_cin_alone_v8 legitimate, and it is the property that says
// the split rearranged the digits without changing what a line holds.
void test_blocks_fold() {
    check::group("elements inside one block share a line");
    const SplitCinMapper m(kV8, 4, kCoutBlock, kWeightB, kSets);
    const std::int64_t base = m.line_of(Coord{1, 2, 100, 5}).get();
    bool folds = true;
    for (std::int32_t co = 0; co < kCoutBlock; ++co)
        for (std::int32_t ci = 100; ci < 104; ++ci)
            if (m.line_of(Coord{1, 2, ci, co}).get() != base) folds = false;
    CHECK_TRUE(folds);
    // And the next block over is a different line, so the fold is a fold and
    // not a collapse.
    CHECK_TRUE(m.line_of(Coord{1, 2, 104, 5}).get() != base);
    CHECK_TRUE(m.line_of(Coord{1, 2, 100, 16}).get() != base);
}

// --- 3. the digit order ------------------------------------------------------

// The five radices, innermost first, on the V8 geometry. These are the numbers
// the header's nesting comment claims, read back one by one, so a reordered
// Digit enum or a mis-folded stride is caught here rather than through
// num_lines(), where two errors can cancel.
void test_the_five_strides() {
    check::group("the five radices, V8 at 128 sets");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);

    CHECK_EQ(m.n_cin_blocks(), 512);   // CIN 512, cin_block 1
    CHECK_EQ(m.n_cout_blocks(), 32);   // COUT 512, cout_block 16
    CHECK_EQ(m.n_cin_lo(), 128);
    CHECK_EQ(m.n_cin_hi(), 4);         // 512 / 128

    CHECK_EQ(m.digit_stride(Digit::CIN_LO), 1);
    CHECK_EQ(m.digit_stride(Digit::COUT), 128);          // n_cin_lo
    CHECK_EQ(m.digit_stride(Digit::CIN_HI), 32 * 128);   // n_cout_blocks * n_cin_lo
    CHECK_EQ(m.digit_stride(Digit::KW), 4 * 32 * 128);   // n_cin_hi * above
    CHECK_EQ(m.digit_stride(Digit::KH), 3 * 4 * 32 * 128);

    CHECK_EQ(m.digit_radix(Digit::KH), 3);
    CHECK_EQ(m.digit_radix(Digit::KW), 3);
    CHECK_EQ(m.digit_radix(Digit::CIN_HI), 4);
    CHECK_EQ(m.digit_radix(Digit::COUT), 32);
    CHECK_EQ(m.digit_radix(Digit::CIN_LO), 128);

    // num_lines is the product of all five, and equals BlockPackMapper's
    // 3 * 3 * 512 * 32 for the same shape because 128 divides 512.
    CHECK_EQ(m.num_lines().get(), 3 * 3 * 4 * 32 * 128);
    CHECK_EQ(m.num_lines().get(), 3 * 3 * 512 * 32);
}

// The case worked through by hand in SET_INDEX_COLLAPSE.md section 10:
// kh=1, kw=2, cin=100, cout=5 under V8 at 128 sets.
//
//   tap    = 1*3 + 2 = 5, so kh contributes 1 * 49152 and kw 2 * 16384
//   cin    = 100 -> cin_hi = 0, cin_lo = 100
//   cout   = 5   -> cout_blk = 0
//   line   = 1*49152 + 2*16384 + 0*4096 + 0*128 + 100 = 82,020
void test_line_of_the_hand_computed_case() {
    check::group("the hand-computed case");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    CHECK_EQ(m.line_of(Coord{1, 2, 100, 5}).get(), 82020);
    // And its set index is cin % 128, which is 100.
    CHECK_EQ(m.line_of(Coord{1, 2, 100, 5}).get() % kSets, 100);
}

// The single fact that separates this layout from BlockPackMapper's: a unit
// step in cin moves the line by 1, not by n_cout_blocks. Under the old layout
// this delta was 32, and 32 sharing a factor of 32 with 128 is the entire bug.
void test_a_cin_step_moves_the_line_by_one() {
    check::group("a cin step moves the line by 1");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    bool unit_steps = true;
    // Inside one cin_lo group, so no carry into cin_hi.
    for (std::int32_t ci = 0; ci + 1 < 128; ++ci) {
        const std::int64_t a = m.line_of(Coord{0, 0, ci, 0}).get();
        const std::int64_t b = m.line_of(Coord{0, 0, ci + 1, 0}).get();
        if (b - a != 1) unit_steps = false;
    }
    CHECK_TRUE(unit_steps);

    // A cout block step moves it by n_cin_lo, which is what keeps cout out of
    // the L1 index and 4 of its 5 bits inside L2's.
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 16}).get() - m.line_of(Coord{0, 0, 0, 0}).get(),
             kSets);
}

// --- the ragged case ---------------------------------------------------------

// n_cin_lo that does not divide the block count. The constructor accepts it,
// n_cin_hi rounds up, num_lines overcounts by the holes, and the flatten stays
// injective and in range. All four are the deliberate reading stated in the
// header, so all four are pinned.
void test_ragged_n_cin_lo_is_accepted_and_stays_sound() {
    check::group("n_cin_lo that does not divide the block count");
    const WeightShape s{1, 1, 10, 4};
    const SplitCinMapper m(s, 1, 1, 1, 4);   // 10 cin blocks, n_cin_lo 4

    CHECK_EQ(m.n_cin_blocks(), 10);
    CHECK_EQ(m.n_cin_hi(), 3);              // ceil(10 / 4), not 2

    // NOT the radix product 1*1*3*4*4 = 48. layout.h defines num_lines() as one
    // past the LARGEST line the mapper can produce, and the conformance suite
    // checks that the bound is reached. With 10 cin blocks and n_cin_lo 4 the
    // top of the cin_hi digit is only partly used: the largest cin block is 9,
    // which splits to cin_hi 2 and cin_lo 1, so the largest line is
    // 2*16 + 3*4 + 1 = 45 and the bound is 46. A 48 here would be a bound too
    // loose, which deflates every coverage figure computed by dividing it.
    CHECK_EQ(m.num_lines().get(), 46);

    std::set<std::int64_t> seen;
    bool in_range = true, set_ok = true;
    for (std::int32_t ci = 0; ci < s.CIN; ++ci)
        for (std::int32_t co = 0; co < s.COUT; ++co) {
            const std::int64_t line = m.line_of(Coord{0, 0, ci, co}).get();
            if (line < 0 || line >= m.num_lines().get()) in_range = false;
            if (line % 4 != ci % 4) set_ok = false;
            seen.insert(line);
        }
    CHECK_TRUE(in_range);
    CHECK_TRUE(set_ok);
    CHECK_EQ(check::ssize(seen), 40);       // 10 cin x 4 cout, all distinct
    // 46 ids for 40 tuples: the 6 holes the header says locate will treat as
    // legal ids the trace never produces.
    CHECK_EQ(m.num_lines().get() - check::ssize(seen), 6);
    // And the bound is reached, which is the half c_num_lines_is_exact checks.
    std::int64_t largest = -1;
    for (std::int64_t l : seen) if (l > largest) largest = l;
    CHECK_EQ(largest, m.num_lines().get() - 1);
}

// n_cin_lo larger than the block count. Legal, and the top of the set index is
// simply never reached, which is a quality problem for config.cpp to warn
// about rather than a constructor error.
void test_n_cin_lo_larger_than_the_block_count() {
    check::group("n_cin_lo larger than the block count");
    const WeightShape s{1, 1, 4, 4};
    const SplitCinMapper m(s, 1, 1, 1, 64);
    CHECK_EQ(m.n_cin_hi(), 1);
    CHECK_EQ(m.n_cin_blocks(), 4);
    // Largest line is cin_lo 3 plus cout block 3: 3*64 + 3 = 195, so 196.
    // The radix product would have said 1*1*1*4*64 = 256.
    CHECK_EQ(m.num_lines().get(), 196);
    std::set<std::int64_t> sets_reached;
    for (std::int32_t ci = 0; ci < s.CIN; ++ci)
        for (std::int32_t co = 0; co < s.COUT; ++co)
            sets_reached.insert(m.line_of(Coord{0, 0, ci, co}).get() % 64);
    CHECK_EQ(check::ssize(sets_reached), 4);   // 4 of 64, and no throw
}

// --- 4. the rejection paths --------------------------------------------------

void test_rejects_non_positive_extents() {
    check::group("non-positive extents");
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(WeightShape{0, 3, 8, 8}, 4, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(WeightShape{3, 0, 8, 8}, 4, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(WeightShape{3, 3, 0, 8}, 4, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(WeightShape{3, 3, 8, 0}, 4, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(WeightShape{3, 3, 8, -1}, 4, 4, 2, 4));
}

void test_rejects_non_positive_blocks_and_widths() {
    check::group("non-positive blocks, widths, and n_cin_lo");
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, 0, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, -1, 4, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, 4, 0, 2, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, 4, 4, 0, 4));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, 4, 4, 2, 0));
    CHECK_THROWS(std::invalid_argument, SplitCinMapper(kSmall, 4, 4, 2, -8));
}

// A rejection that fires for the wrong reason still throws the right type, so
// the message is checked too: the prefix sends a reader to this file, the
// parameter name says which argument, and the value distinguishes "the config
// loader left it 0" from "the header was decoded at the wrong offset".
void test_rejection_messages_name_the_parameter_and_the_value() {
    check::group("rejection messages");
    const std::string m = message_of([] { SplitCinMapper(kSmall, 4, 4, 2, -8); });
    CHECK_TRUE(contains(m, "SplitCinMapper: "));
    CHECK_TRUE(contains(m, "n_cin_lo"));
    CHECK_TRUE(contains(m, "-8"));

    const std::string b = message_of([] { SplitCinMapper(kSmall, 0, 4, 2, 4); });
    CHECK_TRUE(contains(b, "SplitCinMapper: "));
    CHECK_TRUE(contains(b, "cin_block"));
    CHECK_TRUE(contains(b, "0"));

    const std::string e = message_of([] { SplitCinMapper(WeightShape{3, 3, 0, 8}, 4, 4, 2, 4); });
    CHECK_TRUE(contains(e, "SplitCinMapper: "));
    CHECK_TRUE(contains(e, "CIN"));
}

// A coordinate outside the shape is std::out_of_range and not
// std::invalid_argument. The two must stay distinguishable: a bad
// configuration is found once, at construction, and a bad coordinate is found
// per call while the trace is being replayed.
void test_line_of_range_type_and_the_truncation_trap() {
    check::group("line_of range failures");
    const SplitCinMapper m(kV8, 4, kCoutBlock, kWeightB, kSets);
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{3, 0, 0, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 512, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 0, 512}));
    // The trap block_pack.cpp records: with cin_block 4, cin = -1 divides to
    // block 0 and would pass a block_len check. The shape check is what makes
    // it visible.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, -1, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, -3, 0}));

    const std::string msg = [&] {
        try { m.line_of(Coord{0, 0, 512, 0}); } catch (const std::exception& e) { return std::string(e.what()); }
        return std::string("(no exception)");
    }();
    CHECK_TRUE(contains(msg, "SplitCinMapper: "));
    CHECK_TRUE(contains(msg, "CIN"));
    CHECK_TRUE(contains(msg, "512"));
}

// --- the line size, and what it is not a function of -------------------------

void test_line_size_ignores_the_shape_and_the_split() {
    check::group("line size is the three layout parameters only");
    const SplitCinMapper a(kV8, 4, 8, 2, 128);
    const SplitCinMapper b(WeightShape{1, 1, 1, 1}, 4, 8, 2, 1);
    CHECK_EQ(a.line_size_bytes(), 64);
    CHECK_EQ(b.line_size_bytes(), 64);
    // Same three factors, a different n_cin_lo, the same line size: the split
    // changes where a line goes, never how big it is.
    const SplitCinMapper c(kV8, 4, 8, 2, 7);
    CHECK_EQ(c.line_size_bytes(), 64);
    CHECK_TRUE(a.line_size_terms(64) == b.line_size_terms(64));
    CHECK_TRUE(contains(a.line_size_terms(64), "cin_block 4"));
    CHECK_TRUE(contains(a.line_size_terms(64), "cout_block 8"));
    CHECK_TRUE(contains(a.line_size_terms(64), "weight_bytes 2"));
}

void test_block_len_is_the_extent_in_lines() {
    check::group("block_len");
    const SplitCinMapper m(kV8, 4, kCoutBlock, kWeightB, kSets);
    CHECK_EQ(m.block_len(Axis::KH), 3);
    CHECK_EQ(m.block_len(Axis::KW), 3);
    CHECK_EQ(m.block_len(Axis::CIN), 128);    // 512 / 4, the whole block count
    CHECK_EQ(m.block_len(Axis::COUT), 32);    // 512 / 16
    // CIN reports the whole block count, which is what the two halves of the
    // split cover between them.
    CHECK_TRUE(m.n_cin_hi() * m.n_cin_lo() >= m.block_len(Axis::CIN));
}

// --- expand and locate -------------------------------------------------------

// The interface suite, parameterised over `const AddressMapper&`. Five
// blockings, for the reason test_block_pack.cpp gives: several contracts are
// inert under any single one. Three values of n_cin_lo on top of that, because
// n_cin_lo is this mapper's own parameter and 1 (no split at all), a divisor,
// and a non-divisor (the ragged case, where num_lines is not the radix
// product) exercise different arithmetic.
void test_conformance() {
    const WeightShape shape{3, 3, 8, 12};
    const conformance::Env env = conformance::make_env(shape);

    for (std::int64_t lo : {1, 2, 5}) {
        const std::string tag = " (n_cin_lo " + std::to_string(lo) + ")";
        conformance::run_all(SplitCinMapper(shape, 1, 1, 2, lo),
                             env, ("SplitCinMapper: one element per line" + tag).c_str());
        conformance::run_all(SplitCinMapper(shape, 4, 4, 2, lo),
                             env, ("SplitCinMapper: 4x4 blocks" + tag).c_str());
        conformance::run_all(SplitCinMapper(shape, 8, 12, 2, lo),
                             env, ("SplitCinMapper: a whole CIN x COUT plane per line" + tag).c_str());
        conformance::run_all(SplitCinMapper(shape, 3, 5, 2, lo),
                             env, ("SplitCinMapper: neither extent divides" + tag).c_str());
        conformance::run_all(SplitCinMapper(shape, 16, 16, 2, lo),
                             env, ("SplitCinMapper: blocks wider than their extents" + tag).c_str());
    }
}

// The corpus burst, hand computed: 4 consecutive cout from a 16-wide cout
// block, which is what every WCTS stream in this study carries (burst_dim
// COUT, burst_span 4, burst_stride 1). All four fold into one line, which is
// why lines_per_burst is 1 and why l1_demand_reserve defaults to 1.
void test_expand_the_corpus_burst() {
    check::group("expand: the corpus burst");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    std::vector<LineId> out;
    m.expand(Burst{Coord{1, 2, 100, 0}, Axis::COUT, 4, 1}, out);
    CHECK_EQ(check::ssize(out), 1);
    CHECK_EQ(out[0].get(), 82020);          // the W1 hand-computed line

    // A burst crossing a cout block boundary touches two lines, one cout block
    // apart, which under this layout is n_cin_lo apart and not 1 apart.
    out.clear();
    m.expand(Burst{Coord{1, 2, 100, 14}, Axis::COUT, 4, 1}, out);
    CHECK_EQ(check::ssize(out), 2);
    CHECK_EQ(out[1].get() - out[0].get(), kSets);
}

// A burst along CIN is the case the split could have broken, because cin now
// feeds two digits and the low one wraps. A run of 4 inside one cin_lo group
// gives four consecutive lines; a run that crosses the wrap must still come
// back strictly increasing.
void test_expand_along_cin_including_the_wrap() {
    check::group("expand: along CIN, across the cin_lo wrap");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);

    std::vector<LineId> out;
    m.expand(Burst{Coord{0, 0, 10, 0}, Axis::CIN, 4, 1}, out);
    CHECK_EQ(check::ssize(out), 4);
    CHECK_EQ(out[0].get(), 10);
    CHECK_EQ(out[3].get(), 13);

    // cin 126..129 crosses cin_lo 127 -> 0 with cin_hi 0 -> 1.
    out.clear();
    m.expand(Burst{Coord{0, 0, 126, 0}, Axis::CIN, 4, 1}, out);
    CHECK_EQ(check::ssize(out), 4);
    bool increasing = true;
    for (std::size_t i = 1; i < out.size(); ++i)
        if (!(out[i - 1] < out[i])) increasing = false;
    CHECK_TRUE(increasing);
    // 126, 127, then 4096 (cin_hi 1, cin_lo 0), then 4097.
    CHECK_EQ(out[0].get(), 126);
    CHECK_EQ(out[1].get(), 127);
    CHECK_EQ(out[2].get(), 4096);
    CHECK_EQ(out[3].get(), 4097);
}

// The malformed and out-of-range paths, and the promise that a call which
// throws appends nothing. The conformance suite checks all three over its own
// bursts; these pin the message and the type on this mapper's own prefix.
void test_expand_refusals_leave_out_untouched() {
    check::group("expand: refusals append nothing");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    std::vector<LineId> out{LineId{7}};

    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 1}, out));
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, -1, 1}, out));
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 0}, out));
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, -1}, out));
    CHECK_THROWS(std::out_of_range, m.expand(Burst{Coord{0, 0, 0, 510}, Axis::COUT, 4, 1}, out));
    // The far end computed in int64: anchor 0, stride 2^30, count 5 lands at
    // 2^32, which truncates to a legal-looking 0 in int32.
    CHECK_THROWS(std::out_of_range,
                 m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 5, 1 << 30}, out));

    CHECK_EQ(check::ssize(out), 1);         // untouched, all six times
    CHECK_EQ(out[0].get(), 7);
}

// locate is BlockPackMapper's six lines, so what is worth pinning here is the
// property the whole layout exists for: at the num_sets this mapper's
// n_cin_lo was built for, the set index IS cin.
void test_locate_set_index_is_cin() {
    check::group("locate: the set index is cin");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    bool set_is_cin = true;
    std::set<std::int64_t> sets_reached;
    for (std::int32_t ci = 0; ci < kV8.CIN; ++ci) {
        // cout block 0 only: one core's worth, which is where the old layout
        // reached 8 sets of 128.
        const Placement p = m.locate(m.line_of(Coord{1, 2, ci, 0}), kSets);
        if (p.set_index.get() != ci % kSets) set_is_cin = false;
        sets_reached.insert(p.set_index.get());
    }
    CHECK_TRUE(set_is_cin);
    CHECK_EQ(check::ssize(sets_reached), kSets);
}

// The same mapper serves L1 and L2 with different num_sets, which is what
// layout.h means by "One instance serves the whole hierarchy". At L2's 2048
// sets the set index is no longer cin alone, and that is correct rather than a
// regression: the point of putting COUT directly above CIN_LO is that 4 of its
// 5 bits survive into a 2048-set index.
void test_locate_serves_both_levels() {
    check::group("locate: one mapper, two set counts");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    constexpr std::int64_t kL2Sets = 2048;

    std::set<std::int64_t> l2_sets;
    for (std::int32_t ci = 0; ci < kV8.CIN; ++ci)
        for (std::int32_t co = 0; co < kV8.COUT; co += kCoutBlock)
            l2_sets.insert(m.locate(m.line_of(Coord{0, 0, ci, co}), kL2Sets).set_index.get());
    CHECK_EQ(check::ssize(l2_sets), kL2Sets);

    // And the identity holds at both set counts, interleaved, with no state.
    const LineId l = m.line_of(Coord{1, 2, 100, 5});
    const Placement a = m.locate(l, kSets);
    const Placement b = m.locate(l, kL2Sets);
    CHECK_EQ(a.tag.get() * kSets + a.set_index.get(), l.get());
    CHECK_EQ(b.tag.get() * kL2Sets + b.set_index.get(), l.get());
    CHECK_EQ(m.locate(l, kSets).set_index, a.set_index);
}

void test_locate_range_check_runs_before_the_division() {
    check::group("locate: range check");
    const SplitCinMapper m(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    CHECK_THROWS(std::out_of_range, m.locate(LineId{-1}, kSets));
    CHECK_THROWS(std::out_of_range, m.locate(LineId{m.num_lines().get()}, kSets));
    const std::string msg = [&] {
        try { m.locate(LineId{-1}, kSets); } catch (const std::exception& e) { return std::string(e.what()); }
        return std::string("(no exception)");
    }();
    CHECK_TRUE(contains(msg, "SplitCinMapper: "));
    CHECK_TRUE(contains(msg, "got -1"));
}

// --- W4: what the driver's probe mapper rests on -----------------------------
//
// Both drivers expand the widest burst through a BlockPackMapper to size the
// L1 demand reserve, and they do it even when cfg.layout says split_cin,
// because validate() is what resolves the width the real mapper is built from.
// That is only sound if the NUMBER of lines a burst touches is the same under
// both nestings. It is, and the reason is that a burst covers a fixed set of
// BLOCK coordinates and both flattens are injective on those, so the two line
// sets are the same size however differently they are numbered.
//
// Pinned rather than argued, because a mapper added later could break it and
// the symptom would be a reserve sized for the wrong layout, which looks like
// an MSHR result.
void test_both_layouts_agree_on_how_many_lines_a_burst_touches() {
    check::group("W4: the line COUNT of a burst does not depend on the nesting");
    const BlockPackMapper bp(kV8, kCinBlock, kCoutBlock, kWeightB);
    std::vector<LineId> a, b;

    // The corpus burst, at the origin, which is the one the drivers expand.
    for (std::int64_t lo : {std::int64_t{1}, std::int64_t{7}, std::int64_t{64},
                        kSets, std::int64_t{1024}}) {
        const SplitCinMapper sc(kV8, kCinBlock, kCoutBlock, kWeightB, lo);
        a.clear();
        b.clear();
        bp.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 1}, a);
        sc.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 1}, b);
        CHECK_EQ(check::ssize(a), check::ssize(b));
    }

    // And a sweep: every axis, several spans and strides, several origins, at
    // one representative split. The ids differ; only the count is claimed.
    const SplitCinMapper sc(kV8, kCinBlock, kCoutBlock, kWeightB, kSets);
    bool ever_differed = false;
    for (Axis ax : conformance::kAxes) {
        for (std::int32_t span : {1, 2, 3, 4, 8, 16, 17, 33}) {
            for (std::int32_t stride : {1, 2, 5}) {
                for (const Coord& c : {Coord{0, 0, 0, 0}, Coord{1, 2, 100, 0},
                                       Coord{2, 1, 127, 14}, Coord{0, 2, 300, 240}}) {
                    if (coord_on(c, ax) +
                            (span - 1) * stride >= extent_on(kV8, ax)) {
                        continue;   // past the layer, which both mappers refuse
                    }
                    a.clear();
                    b.clear();
                    bp.expand(Burst{c, ax, span, stride}, a);
                    sc.expand(Burst{c, ax, span, stride}, b);
                    CHECK_EQ(check::ssize(a), check::ssize(b));
                    if (a != b) ever_differed = true;
                }
            }
        }
    }
    // Non-vacuous: the counts agree because the LAYOUTS are different, not
    // because the two mappers are secretly the same one.
    CHECK_TRUE(ever_differed);
}

}  // namespace

int main() {
    test_set_index_is_cin_alone_small();
    test_set_index_is_cin_alone_v8();
    test_one_cout_block_still_reaches_every_set();
    test_flatten_is_injective_and_in_range();
    test_blocks_fold();
    test_the_five_strides();
    test_line_of_the_hand_computed_case();
    test_a_cin_step_moves_the_line_by_one();
    test_ragged_n_cin_lo_is_accepted_and_stays_sound();
    test_n_cin_lo_larger_than_the_block_count();
    test_rejects_non_positive_extents();
    test_rejects_non_positive_blocks_and_widths();
    test_rejection_messages_name_the_parameter_and_the_value();
    test_line_of_range_type_and_the_truncation_trap();
    test_line_size_ignores_the_shape_and_the_split();
    test_block_len_is_the_extent_in_lines();
    test_conformance();
    test_expand_the_corpus_burst();
    test_expand_along_cin_including_the_wrap();
    test_expand_refusals_leave_out_untouched();
    test_locate_set_index_is_cin();
    test_locate_serves_both_levels();
    test_locate_range_check_runs_before_the_division();
    test_both_layouts_agree_on_how_many_lines_a_burst_touches();
    return check::summary();
}
