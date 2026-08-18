// Unit A2b: BlockPackMapper construction and validation.
//
// A2b is a constructor and six accessors. Everything it computes is derived
// state, and until A2c writes line_of that state is observable ONLY through
// num_lines(), line_size_bytes(), and the six accessors block_pack.h exposes
// for exactly this reason. So this file is written the other way round from
// test_layout.cpp: there the unit was an interface and the tests were about
// shape, here the unit is arithmetic and validation and the tests are about
// values and about messages.
//
// Three things are pinned:
//
//   1. every rejection path fires, throws std::invalid_argument, carries the
//      "BlockPackMapper: " prefix, names the offending parameter, and prints
//      the offending value. A message that only restates the rule ("block
//      sizes must be positive") is what v1 shipped, and it does not say which
//      block or what it held.
//   2. the derived state: ceiling division in blocks_covering, the exact
//      product in num_lines, the exact product in line_size_bytes, and the
//      fact that line_size_bytes does not read the shape.
//   3. A2d's expand and locate, which replaced the two stub tripwires this
//      file used to carry. The conformance suite of tests/mapper_conformance.h
//      is run over the real mapper here, since that header is parameterised
//      over `const AddressMapper&` and this is the file that knows the concrete
//      one; the hand-computed values and the oracle beside it are what the
//      interface-level suite cannot say.
//
// The negative half at the type level (deriving from a `final` class, unwrapping
// a LineId, calling the constructor with a Coord) is in tests/compile_fail.sh.
// The negative half at the behaviour level (does a wrong block_pack.cpp make
// this file go red) is tests/mutation_check.sh.
#include <wcache/block_pack.h>
#include <wcache/layout.h>
#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "check.h"
#include "mapper_conformance.h"

using namespace wcache;

namespace {

// ===========================================================================
// Message probes
// ===========================================================================
//
// The rejection tests care about three properties of one string, so the probe
// returns the string and a single reporter checks all three. CHECK_THROWS
// alone would say "it threw invalid_argument" and nothing about whether the
// message is usable, which is the half N11 actually asks for.

constexpr const char* kPrefix = "BlockPackMapper: ";

// The exception type is encoded INTO the returned string rather than checked
// separately, so that a mutation changing invalid_argument to some other type
// fails the prefix check with a message that says what came out instead. The
// order of the catch clauses is narrowest first: invalid_argument derives from
// logic_error, so the reverse order would report every rejection as a plain
// logic_error and the stub tripwires below would stop distinguishing anything.
template <typename Fn>
std::string thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::invalid_argument& e) {
        return e.what();
    } catch (const std::logic_error& e) {
        return std::string("[logic_error, not invalid_argument] ") + e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong exception type] ") + e.what();
    } catch (...) {
        return "[non-std exception]";
    }
    return "[no exception thrown]";
}

// The same probe for the A2d stubs, where logic_error is the RIGHT answer and
// invalid_argument is the wrong one. Two probes rather than one parameterised
// probe, because the two units disagree about which type is correct and a
// single probe would have to be told, which is the thing being tested.
template <typename Fn>
std::string logic_thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::invalid_argument& e) {
        return std::string("[invalid_argument, not logic_error] ") + e.what();
    } catch (const std::logic_error& e) {
        return e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong exception type] ") + e.what();
    } catch (...) {
        return "[non-std exception]";
    }
    return "[no exception thrown]";
}

// A third probe, for A2c's range failures. std::out_of_range is caught FIRST
// because it derives from std::logic_error, so the reverse order would report
// every range failure as a plain logic_error and would stop telling a bad
// coordinate apart from the unknown-Axis refusal. Those are the two failures
// this increment draws a line between, so the probe has to keep them apart.
template <typename Fn>
std::string range_thrown_by(Fn fn) {
    try {
        fn();
    } catch (const std::out_of_range& e) {
        return e.what();
    } catch (const std::invalid_argument& e) {
        return std::string("[invalid_argument, not out_of_range] ") + e.what();
    } catch (const std::logic_error& e) {
        return std::string("[logic_error, not out_of_range] ") + e.what();
    } catch (const std::exception& e) {
        return std::string("[wrong exception type] ") + e.what();
    } catch (...) {
        return "[non-std exception]";
    }
    return "[no exception thrown]";
}

bool contains(const std::string& hay, const char* needle) {
    return hay.find(needle) != std::string::npos;
}

// One check, and on failure it prints the message that actually came out.
// A CHECK_TRUE per needle would print the expression source instead, which for
// a containment test on a runtime string says nothing a reader can act on.
void expect_message(const char* name,
                    const std::string& actual,
                    const char* prefix,
                    std::initializer_list<const char*> needles) {
    ++check::g_checks;
    std::string missing;
    if (actual.rfind(prefix, 0) != 0) {
        missing += " prefix \"";
        missing += prefix;
        missing += "\"";
    }
    for (const char* n : needles) {
        if (!contains(actual, n)) {
            missing += " \"";
            missing += n;
            missing += "\"";
        }
    }
    if (!missing.empty()) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-40s missing:%s\n  message  : %s\n",
                        name, missing.c_str(), actual.c_str());
    }
}

// A shape whose four extents are all legal, so a test about a block size is not
// accidentally a test about an extent. The constructor checks the extents
// first, so any of these tests written against a degenerate shape would be
// caught by the wrong branch and would still look green.
constexpr WeightShape kOk{3, 3, 256, 64};

// The four axes in nesting order, outermost first. The same list block_pack.cpp
// keeps in its own anonymous namespace, written out here rather than reached
// for across the translation unit boundary: a test that borrowed the library's
// copy would agree with a reordered library by construction, and B17's whole
// point is that the order is a decision the test has to restate independently.
constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

// An Axis value no enumerator names. Axis is `: std::uint8_t`, so 9 is a value
// of the underlying type and the cast is well defined rather than UB, which is
// what makes this probe legal at all. tests/test_types.cpp uses the same value
// for extent_on and coord_on, and A2c's two per-axis functions follow that
// precedent, so the probe is spelled the same way.
constexpr Axis kNoSuchAxis = static_cast<Axis>(9);

// ===========================================================================
// The valid configurations
// ===========================================================================

void test_accessors_return_what_was_constructed() {
    check::group("A2b: the accessors report the constructor's arguments");

    // A corpus-shaped layer. cout_block 128 over COUT 64 is the ONE place the
    // 7.7 GB corpus reaches the rounding path at all, so it is the positive
    // case as well as the ceiling case.
    const BlockPackMapper m(kOk, 64, 128, 1);

    CHECK_EQ(m.shape().KH,   std::int32_t{3});
    CHECK_EQ(m.shape().KW,   std::int32_t{3});
    CHECK_EQ(m.shape().CIN,  std::int32_t{256});
    CHECK_EQ(m.shape().COUT, std::int32_t{64});
    CHECK_EQ(m.cin_block(),    std::int32_t{64});
    CHECK_EQ(m.cout_block(),   std::int32_t{128});
    CHECK_EQ(m.weight_bytes(), std::int32_t{1});

    // 256 / 64 divides exactly; 64 / 128 does not and rounds UP to one line.
    CHECK_EQ(m.n_cin_blocks(),  std::int64_t{4});
    CHECK_EQ(m.n_cout_blocks(), std::int64_t{1});

    // 3 * 3 * 4 * 1, and 64 * 128 * 1.
    CHECK_EQ(m.num_lines().get(), std::int64_t{36});
    CHECK_EQ(m.line_size_bytes(), std::int64_t{8192});

    // A floor in either divisor changes both answers, which is what makes the
    // two lines above a test of the ceiling rather than of the multiply.
    CHECK_TRUE(std::int64_t{64 / 128} != m.n_cout_blocks());

    // The same values through the interface the engine actually holds, so that
    // an override which stopped overriding is caught here rather than at A2d.
    const AddressMapper& base = m;
    CHECK_EQ(base.num_lines().get(), std::int64_t{36});
    CHECK_EQ(base.line_size_bytes(), std::int64_t{8192});
    CHECK_TRUE(base.num_lines() == LineId{36});
}

void test_an_asymmetric_configuration() {
    check::group("A2b: cin and cout are told apart, in both the block and the count");

    // Deliberately asymmetric on every axis that could be confused:
    //   cin_block  32 != cout_block 8
    //   n_cin      4  != n_cout     7
    //   both extents non-divisible, so a floor in EITHER changes num_lines
    //   KH 3 != KW 5, so dropping one from the product changes it too
    //
    // A symmetric case catches none of this: swapping the two block counts
    // leaves the product alone (multiplication commutes), and a floor taken in
    // one divisor and a ceiling in the other cancels when the two extents and
    // the two blocks are equal.
    const BlockPackMapper m(WeightShape{3, 5, 100, 50}, 32, 8, 2);

    CHECK_EQ(m.n_cin_blocks(),  std::int64_t{4});   // ceil(100 / 32), floor is 3
    CHECK_EQ(m.n_cout_blocks(), std::int64_t{7});   // ceil(50 / 8),   floor is 6
    CHECK_TRUE(m.n_cin_blocks() != m.n_cout_blocks());
    CHECK_TRUE(m.cin_block() != m.cout_block());

    // 3 * 5 * 4 * 7. A floor on CIN gives 315, a floor on COUT gives 360,
    // dropping KW gives 84: three different wrong answers, all reachable.
    CHECK_EQ(m.num_lines().get(), std::int64_t{420});

    // 32 * 8 * 2. Dropping weight_bytes gives 256.
    CHECK_EQ(m.line_size_bytes(), std::int64_t{512});

    // The shape is copied, not referenced: the mapper outlives whatever the
    // caller decoded the header into.
    WeightShape s{3, 5, 100, 50};
    const BlockPackMapper n(s, 32, 8, 2);
    s.CIN = 1;
    CHECK_EQ(n.shape().CIN, std::int32_t{100});
    CHECK_EQ(n.n_cin_blocks(), std::int64_t{4});
}

void test_blocks_covering_rounds_up() {
    check::group("A2b: a partial trailing block still occupies a whole line");

    struct Case {
        std::int32_t extent;
        std::int32_t block;
        std::int64_t expect;  // hand computed, not recomputed from the formula
    };
    // Both divisible and non-divisible cases. The divisible ones are not
    // padding: they are what catches a rounding term that over-counts (a
    // `+ block` where the code says `+ block - 1`), which a suite of only
    // non-divisible cases would pass.
    const Case cases[] = {
        {  64, 128, 1},  // the corpus case: block wider than the extent
        { 100,  32, 4},
        {   7,   4, 2},
        {  65,  64, 2},
        {   3,   2, 2},
        {  50,   8, 7},
        {   1,   1, 1},
        { 256,  64, 4},  // divisible
        { 512, 512, 1},  // divisible, block == extent
        {   4,   1, 4},  // divisible, block of one
    };

    int non_vacuous = 0;
    for (const Case& c : cases) {
        // Driven twice: once with the extent on CIN and once on COUT, so a
        // mutation that fixes the rounding in one divisor and not the other
        // cannot hide behind the case that was checked.
        const BlockPackMapper on_cin(WeightShape{1, 1, c.extent, 1}, c.block, 1, 1);
        CHECK_EQ(on_cin.n_cin_blocks(), c.expect);
        CHECK_EQ(on_cin.n_cout_blocks(), std::int64_t{1});
        CHECK_EQ(on_cin.num_lines().get(), c.expect);

        const BlockPackMapper on_cout(WeightShape{1, 1, 1, c.extent}, 1, c.block, 1);
        CHECK_EQ(on_cout.n_cout_blocks(), c.expect);
        CHECK_EQ(on_cout.n_cin_blocks(), std::int64_t{1});
        CHECK_EQ(on_cout.num_lines().get(), c.expect);

        if (static_cast<std::int64_t>(c.extent / c.block) != c.expect) ++non_vacuous;
    }

    // The control on the table itself. Every check above would also pass under
    // a floor if every case divided exactly, so the table is only a test of the
    // ceiling while this count is positive. Five, not one, so that deleting a
    // few rows in a later edit is noticed.
    CHECK_TRUE(non_vacuous >= 5);
}

void test_line_size_never_reads_the_shape() {
    check::group("A2b: line_size_bytes is a function of the layout, not the layer");

    // block_pack.cpp's stated reason: D1 turns cache_size_bytes into a set
    // count with this, so a line size that varied per layer would make L1 and
    // L2 a different cache for every layer and the size sweep incomparable.
    const BlockPackMapper tiny(WeightShape{1, 1, 1, 4}, 64, 64, 2);
    const BlockPackMapper big(WeightShape{3, 3, 512, 512}, 64, 64, 2);
    CHECK_EQ(tiny.line_size_bytes(), std::int64_t{8192});
    CHECK_EQ(big.line_size_bytes(), std::int64_t{8192});
    CHECK_EQ(tiny.line_size_bytes(), big.line_size_bytes());

    // The degenerate configuration the tiny verification trace needs, and the
    // one block_pack.cpp deliberately does NOT reject: a block wider than the
    // extent is one short line, not a configuration error.
    CHECK_EQ(tiny.n_cin_blocks(),  std::int64_t{1});
    CHECK_EQ(tiny.n_cout_blocks(), std::int64_t{1});
    CHECK_EQ(tiny.num_lines().get(), std::int64_t{1});

    // The corpus maximum, at the finest blocking: 3 * 3 * 512 * 512.
    const BlockPackMapper finest(WeightShape{3, 3, 512, 512}, 1, 1, 4);
    CHECK_EQ(finest.num_lines().get(), std::int64_t{2359296});
    CHECK_EQ(finest.line_size_bytes(), std::int64_t{4});

    // And weight_bytes really does scale it, rather than being stored and
    // forgotten. Same layout, four times the element width.
    const BlockPackMapper wide(WeightShape{3, 3, 512, 512}, 1, 1, 16);
    CHECK_EQ(wide.line_size_bytes(), std::int64_t{16});
    CHECK_EQ(wide.num_lines().get(), finest.num_lines().get());
}

// ===========================================================================
// The rejections
// ===========================================================================

void test_rejects_a_non_positive_extent() {
    check::group("A2b: every extent must be >= 1, and the message says which");

    // All four, at 0 and at a negative. KH and KW are not blocked and it would
    // be easy to check only the two that are; they are radices in the flatten
    // just as much as the block counts are. block_pack.cpp:105 records the
    // consequence for KW specifically: a KW of 0 collapses the KH stride to
    // zero, so (0, 1) and (1, 0) name the same line. That is a wrong hit rate,
    // not a crash, which is why it is rejected rather than read as an empty
    // tensor.
    expect_message("KH = 0",  thrown_by([] { BlockPackMapper(WeightShape{0, 3, 8, 8}, 4, 4, 2); }),
                   kPrefix, {"KH", "extent", "got 0"});
    expect_message("KH = -7", thrown_by([] { BlockPackMapper(WeightShape{-7, 3, 8, 8}, 4, 4, 2); }),
                   kPrefix, {"KH", "extent", "got -7"});
    expect_message("KW = 0",  thrown_by([] { BlockPackMapper(WeightShape{3, 0, 8, 8}, 4, 4, 2); }),
                   kPrefix, {"KW", "extent", "got 0"});
    expect_message("KW = -7", thrown_by([] { BlockPackMapper(WeightShape{3, -7, 8, 8}, 4, 4, 2); }),
                   kPrefix, {"KW", "extent", "got -7"});
    expect_message("CIN = 0", thrown_by([] { BlockPackMapper(WeightShape{3, 3, 0, 8}, 4, 4, 2); }),
                   kPrefix, {"CIN", "extent", "got 0"});
    expect_message("CIN = -7", thrown_by([] { BlockPackMapper(WeightShape{3, 3, -7, 8}, 4, 4, 2); }),
                   kPrefix, {"CIN", "extent", "got -7"});
    expect_message("COUT = 0", thrown_by([] { BlockPackMapper(WeightShape{3, 3, 8, 0}, 4, 4, 2); }),
                   kPrefix, {"COUT", "extent", "got 0"});
    expect_message("COUT = -7", thrown_by([] { BlockPackMapper(WeightShape{3, 3, 8, -7}, 4, 4, 2); }),
                   kPrefix, {"COUT", "extent", "got -7"});

    // The far end of the range, which is what a header decoded at the wrong
    // offset actually produces. INT32_MIN is also the value whose negation
    // overflows, so a check written as `-n > 0` rather than `n < 1` would let
    // it through.
    expect_message("CIN = INT32_MIN",
                   thrown_by([] { BlockPackMapper(WeightShape{3, 3, INT32_MIN, 8}, 4, 4, 2); }),
                   kPrefix, {"CIN", "got -2147483648"});

    // The type, stated separately from the text, so that a mutation which kept
    // the message and changed the exception is caught by a check that says so.
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{0, 3, 8, 8}, 4, 4, 2));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 0, 8, 8}, 4, 4, 2));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 3, 0, 8}, 4, 4, 2));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 3, 8, 0}, 4, 4, 2));

    // The other side of the boundary: 1 is legal on every axis. Without this,
    // a check mutated from `< 1` to `< 2` would still reject everything the
    // cases above feed it and still look correct.
    const BlockPackMapper unit(WeightShape{1, 1, 1, 1}, 1, 1, 1);
    CHECK_EQ(unit.num_lines().get(), std::int64_t{1});
    CHECK_EQ(unit.line_size_bytes(), std::int64_t{1});
}

void test_rejects_a_non_positive_block() {
    check::group("A2b: cin_block, cout_block and weight_bytes must be >= 1");

    // A block of 0 divides by zero in blocks_covering; a negative one makes the
    // block index follow the sign of the coordinate, and truncation toward zero
    // means the damage is a plausible neighbouring line rather than a crash.
    expect_message("cin_block = 0",
                   thrown_by([] { BlockPackMapper(kOk, 0, 4, 2); }),
                   kPrefix, {"cin_block", "got 0"});
    expect_message("cin_block = -7",
                   thrown_by([] { BlockPackMapper(kOk, -7, 4, 2); }),
                   kPrefix, {"cin_block", "got -7"});
    expect_message("cout_block = 0",
                   thrown_by([] { BlockPackMapper(kOk, 4, 0, 2); }),
                   kPrefix, {"cout_block", "got 0"});
    expect_message("cout_block = -7",
                   thrown_by([] { BlockPackMapper(kOk, 4, -7, 2); }),
                   kPrefix, {"cout_block", "got -7"});
    // Not a layout radix: weight_bytes only scales line_size_bytes. Checked
    // anyway because a zero makes line_size_bytes zero and D1 divides
    // cache_size_bytes by it.
    expect_message("weight_bytes = 0",
                   thrown_by([] { BlockPackMapper(kOk, 4, 4, 0); }),
                   kPrefix, {"weight_bytes", "got 0"});
    expect_message("weight_bytes = -7",
                   thrown_by([] { BlockPackMapper(kOk, 4, 4, -7); }),
                   kPrefix, {"weight_bytes", "got -7"});

    expect_message("cin_block = INT32_MIN",
                   thrown_by([] { BlockPackMapper(kOk, INT32_MIN, 4, 2); }),
                   kPrefix, {"cin_block", "got -2147483648"});
    expect_message("cout_block = INT32_MIN",
                   thrown_by([] { BlockPackMapper(kOk, 4, INT32_MIN, 2); }),
                   kPrefix, {"cout_block", "got -2147483648"});
    expect_message("weight_bytes = INT32_MIN",
                   thrown_by([] { BlockPackMapper(kOk, 4, 4, INT32_MIN); }),
                   kPrefix, {"weight_bytes", "got -2147483648"});

    CHECK_THROWS(std::invalid_argument, BlockPackMapper(kOk, 0, 4, 2));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(kOk, 4, 0, 2));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(kOk, 4, 4, 0));

    // Each message names ONE parameter, not all three. A rejection that said
    // "block sizes must be positive" would satisfy every containment check
    // above if the needles were only the rule, which is why the value is a
    // needle and why this asserts the other two names are absent.
    const std::string only_cout = thrown_by([] { BlockPackMapper(kOk, 4, 0, 2); });
    CHECK_TRUE(!contains(only_cout, "cin_block"));
    CHECK_TRUE(!contains(only_cout, "weight_bytes"));

    // 1 is legal for all three.
    const BlockPackMapper ones(kOk, 1, 1, 1);
    CHECK_EQ(ones.n_cin_blocks(),  std::int64_t{256});
    CHECK_EQ(ones.n_cout_blocks(), std::int64_t{64});
    CHECK_EQ(ones.line_size_bytes(), std::int64_t{1});
}

void test_rejects_an_overflowing_configuration() {
    check::group("A2b: the products are checked, not wrapped");

    // Signed overflow is undefined behaviour rather than wraparound, so these
    // inputs are chosen to trip the guard BEFORE the multiply happens: every
    // factor fed to checked_mul below is a value the guard rejects, so the
    // product is never formed and the test is not itself UB.
    //
    // Note what this means for the guard's own reachability. checked_mul takes
    // int64 arguments, and the widest int32 pair is INT32_MAX * INT32_MAX =
    // 4611686014132420609, which fits. So the FIRST multiply of each pair
    // (cin_block * cout_block, and KH * KW) can never overflow, and only the
    // second and third calls are reachable at all.

    // line_size_bytes: (INT32_MAX * INT32_MAX) * 3 does not fit. Three, not
    // two: twice 4611686014132420609 is 9223372028264841218, which is still
    // under INT64_MAX, so a weight_bytes of 2 is accepted and is the boundary
    // control at the end of this function.
    expect_message("line_size_bytes overflows",
                   thrown_by([] {
                       BlockPackMapper(WeightShape{1, 1, 1, 1}, INT32_MAX, INT32_MAX, 3);
                   }),
                   kPrefix, {"line_size_bytes", "overflow", "4611686014132420609", "* 3"});

    // num_lines, at the second fold: (KH * KW) * n_cin_blocks.
    expect_message("num_lines overflows on n_cin_blocks",
                   thrown_by([] {
                       BlockPackMapper(WeightShape{INT32_MAX, INT32_MAX, 4, 1}, 1, 1, 1);
                   }),
                   kPrefix, {"num_lines", "overflow", "4611686014132420609", "* 4"});

    // num_lines, at the third fold: (KH * KW * n_cin_blocks) * n_cout_blocks.
    // A distinct trailing factor from the case above, so the two cases cannot
    // both be satisfied by whichever fold happens to fire.
    expect_message("num_lines overflows on n_cout_blocks",
                   thrown_by([] {
                       BlockPackMapper(WeightShape{INT32_MAX, INT32_MAX, 1, 8}, 1, 1, 1);
                   }),
                   kPrefix, {"num_lines", "overflow", "4611686014132420609", "* 8"});

    // invalid_argument, not out_of_range and not a bare logic_error: the
    // configuration is the thing that is wrong, and A2d's range failures are
    // the ones that will be out_of_range.
    CHECK_THROWS(std::invalid_argument,
                 BlockPackMapper(WeightShape{1, 1, 1, 1}, INT32_MAX, INT32_MAX, 3));
    CHECK_THROWS(std::invalid_argument,
                 BlockPackMapper(WeightShape{INT32_MAX, INT32_MAX, 4, 1}, 1, 1, 1));

    // Just under the guard, so the guard is a boundary and not a blanket
    // rejection of large inputs. INT32_MAX * INT32_MAX is the largest product
    // two int32 blocks can make, and at weight_bytes = 1 it must be accepted.
    const BlockPackMapper huge(WeightShape{1, 1, 1, 1}, INT32_MAX, INT32_MAX, 1);
    CHECK_EQ(huge.line_size_bytes(), std::int64_t{4611686014132420609});
    CHECK_EQ(huge.num_lines().get(), std::int64_t{1});

    // The exact boundary, one step below the rejected case: doubling that
    // product still fits, and the guard must let it through. Without this the
    // three rejection cases above would also pass under a guard that rejected
    // every product past some smaller round number.
    const BlockPackMapper at_bound(WeightShape{1, 1, 1, 1}, INT32_MAX, INT32_MAX, 2);
    CHECK_EQ(at_bound.line_size_bytes(), std::int64_t{9223372028264841218});

    const BlockPackMapper wide(WeightShape{INT32_MAX, INT32_MAX, 1, 1}, 1, 1, 1);
    CHECK_EQ(wide.num_lines().get(), std::int64_t{4611686014132420609});
    CHECK_EQ(wide.line_size_bytes(), std::int64_t{1});
}

// ===========================================================================
// A2c: the flatten helpers
// ===========================================================================
//
// A2c adds line_stride, block_len and line_of, and one private stride_[4].
// The unit is arithmetic, so these tests are about VALUES, and about three
// things values alone do not cover:
//
//   the truncation trap  integer division truncates toward zero, so a negative
//                        coordinate divides into a real block index and names
//                        a real line. B25 says only the shape check makes that
//                        visible, and that is the single most important
//                        assertion in this section.
//   block_len alone      B25 declined to route line_of's range check through
//                        block_len, so block_len has NO caller inside the
//                        library until A2d. Nothing but a direct test can
//                        catch a mutation to it.
//   the identity U9      block_len(outer) * line_stride(outer) == num_lines(),
//                        and the adjacent-pair form. Kept out of production
//                        (the constructor establishes it a few lines earlier)
//                        and pinned here instead.

void test_line_stride_is_the_b17_radices() {
    check::group("A2c: line_stride returns the B17/B22 radices, as a delta and not an id");

    // The board's worked case, B22: 3x3x512x512 at cin_block = cout_block = 16
    // gives n_cin = n_cout = 32 and num_lines = 9216.
    const BlockPackMapper board(WeightShape{3, 3, 512, 512}, 16, 16, 1);
    CHECK_EQ(board.line_stride(Axis::KH),   std::int64_t{3072});  // KW * n_cin * n_cout
    CHECK_EQ(board.line_stride(Axis::KW),   std::int64_t{1024});  // n_cin * n_cout
    CHECK_EQ(board.line_stride(Axis::CIN),  std::int64_t{32});    // n_cout
    CHECK_EQ(board.line_stride(Axis::COUT), std::int64_t{1});     // innermost
    CHECK_EQ(board.num_lines().get(), std::int64_t{9216});

    // That shape is symmetric in both pairs (KH == KW, n_cin == n_cout), so a
    // transposed pair of strides passes every check above. This one is
    // asymmetric on every axis at once: KH 3 != KW 5, n_cin 4 != n_cout 7,
    // and all four radices are distinct numbers.
    const BlockPackMapper asym(WeightShape{3, 5, 100, 50}, 32, 8, 2);
    CHECK_EQ(asym.line_stride(Axis::KH),   std::int64_t{140});  // 5 * 4 * 7
    CHECK_EQ(asym.line_stride(Axis::KW),   std::int64_t{28});   // 4 * 7
    CHECK_EQ(asym.line_stride(Axis::CIN),  std::int64_t{7});    // 7
    CHECK_EQ(asym.line_stride(Axis::COUT), std::int64_t{1});

    // Strictly decreasing along the enumerator order, which is what "KH is
    // outermost, COUT is innermost" means arithmetically. Only true because
    // every block_len on this shape is at least 2; the degenerate case below
    // is the one where it is not, and it is stated there rather than assumed
    // here.
    CHECK_TRUE(asym.line_stride(Axis::KH) > asym.line_stride(Axis::KW));
    CHECK_TRUE(asym.line_stride(Axis::KW) > asym.line_stride(Axis::CIN));
    CHECK_TRUE(asym.line_stride(Axis::CIN) > asym.line_stride(Axis::COUT));

    // The mirror of the asymmetric shape, with the two extents and the two
    // blocks exchanged, so that a stride table which hardcoded the four
    // numbers above cannot pass both.
    const BlockPackMapper mirror(WeightShape{5, 3, 50, 100}, 8, 32, 2);
    CHECK_EQ(mirror.line_stride(Axis::KH),   std::int64_t{84});  // 3 * 7 * 4
    CHECK_EQ(mirror.line_stride(Axis::KW),   std::int64_t{28});  // 7 * 4
    CHECK_EQ(mirror.line_stride(Axis::CIN),  std::int64_t{4});   // 4
    CHECK_EQ(mirror.line_stride(Axis::COUT), std::int64_t{1});

    // The tiny verification trace's layer, 3x3x1x4 at 1/1. CIN has exactly one
    // block, so it contributes no depth and line_stride(CIN) == line_stride(KW).
    // A duplicate in the stride table is legal, and this is when it happens; a
    // test that asserted the four strides are always distinct would be wrong.
    const BlockPackMapper tiny(WeightShape{3, 3, 1, 4}, 1, 1, 4);
    CHECK_EQ(tiny.line_stride(Axis::KH),   std::int64_t{12});
    CHECK_EQ(tiny.line_stride(Axis::KW),   std::int64_t{4});
    CHECK_EQ(tiny.line_stride(Axis::CIN),  std::int64_t{4});
    CHECK_EQ(tiny.line_stride(Axis::COUT), std::int64_t{1});
    CHECK_EQ(tiny.num_lines().get(), std::int64_t{36});

    // COUT is innermost on every configuration, not only on the ones above.
    // That is the half of B22 the whole set-spreading argument rests on: a
    // COUT-walking burst is a contiguous run of ids.
    CHECK_EQ(board.line_stride(Axis::COUT), std::int64_t{1});
    CHECK_EQ(asym.line_stride(Axis::COUT),  std::int64_t{1});
    CHECK_EQ(mirror.line_stride(Axis::COUT), std::int64_t{1});
    CHECK_EQ(tiny.line_stride(Axis::COUT),  std::int64_t{1});

    // No state, and const: L1 and L2 share one mapper.
    CHECK_EQ(asym.line_stride(Axis::CIN), asym.line_stride(Axis::CIN));
}

void test_block_len_is_the_extent_in_lines() {
    check::group("A2c: block_len, which B25 left with no in-library caller");

    // B25 declined to route line_of's range check through block_len, so until
    // A2d there is no code path in the library that reads this function. A
    // mutation to it therefore reddens nothing else in the suite, and these
    // checks are the only thing standing between a swapped CIN/COUT arm and a
    // wrong range check at A2d.
    //
    // The shape is chosen so all FOUR answers are different numbers, and so
    // that neither block count coincides with its own extent. A shape where
    // any two agreed would let a swapped pair through.
    const BlockPackMapper m(WeightShape{3, 5, 100, 50}, 32, 8, 2);

    CHECK_EQ(m.block_len(Axis::KH),   std::int64_t{3});  // unblocked: the raw extent
    CHECK_EQ(m.block_len(Axis::KW),   std::int64_t{5});  // unblocked: the raw extent
    CHECK_EQ(m.block_len(Axis::CIN),  std::int64_t{4});  // ceil(100 / 32), NOT 100
    CHECK_EQ(m.block_len(Axis::COUT), std::int64_t{7});  // ceil(50 / 8),   NOT 50

    // Stated as inequalities as well, so that the failure of a "returns the
    // extent" mutation reads as what it is rather than as an arithmetic slip.
    CHECK_TRUE(m.block_len(Axis::CIN)  != static_cast<std::int64_t>(m.shape().CIN));
    CHECK_TRUE(m.block_len(Axis::COUT) != static_cast<std::int64_t>(m.shape().COUT));
    CHECK_TRUE(m.block_len(Axis::CIN)  != m.block_len(Axis::COUT));
    CHECK_TRUE(m.block_len(Axis::KH)   != m.block_len(Axis::KW));

    // And against the accessors that already report the same two numbers, so a
    // block_len arm that stopped reading the member is caught by a check that
    // says which member it should have read.
    CHECK_EQ(m.block_len(Axis::CIN),  m.n_cin_blocks());
    CHECK_EQ(m.block_len(Axis::COUT), m.n_cout_blocks());
    CHECK_EQ(m.block_len(Axis::KH),   static_cast<std::int64_t>(m.shape().KH));
    CHECK_EQ(m.block_len(Axis::KW),   static_cast<std::int64_t>(m.shape().KW));

    // The same four answers on the mirrored shape. Every one of the four moves,
    // so a table of constants cannot satisfy both mappers.
    const BlockPackMapper mirror(WeightShape{5, 3, 50, 100}, 8, 32, 2);
    CHECK_EQ(mirror.block_len(Axis::KH),   std::int64_t{5});
    CHECK_EQ(mirror.block_len(Axis::KW),   std::int64_t{3});
    CHECK_EQ(mirror.block_len(Axis::CIN),  std::int64_t{7});   // ceil(50 / 8)
    CHECK_EQ(mirror.block_len(Axis::COUT), std::int64_t{4});   // ceil(100 / 32)

    // block_len rounds UP for the same reason blocks_covering does: a short
    // final block still occupies a whole line. A floor on either axis here
    // gives 3 and 6.
    CHECK_TRUE(m.block_len(Axis::CIN)  != std::int64_t{100 / 32});
    CHECK_TRUE(m.block_len(Axis::COUT) != std::int64_t{50 / 8});

    // The block wider than its extent, which the corpus really does reach at
    // cout_block 128 over COUT 64, and which the tiny trace reaches on CIN.
    const BlockPackMapper wide(kOk, 64, 128, 1);
    CHECK_EQ(wide.block_len(Axis::CIN),  std::int64_t{4});
    CHECK_EQ(wide.block_len(Axis::COUT), std::int64_t{1});

    // The other factorisation of num_lines: the product of the four block_lens.
    // line_stride's identity below is the first one; this is the second, and
    // together they are what a swapped radix breaks.
    std::int64_t product = 1;
    for (Axis a : kAxes) product *= m.block_len(a);
    CHECK_EQ(product, m.num_lines().get());
    CHECK_EQ(product, std::int64_t{420});

    std::int64_t mirror_product = 1;
    for (Axis a : kAxes) mirror_product *= mirror.block_len(a);
    CHECK_EQ(mirror_product, mirror.num_lines().get());

    // No state, and const.
    CHECK_EQ(m.block_len(Axis::CIN), m.block_len(Axis::CIN));
}

void test_the_radix_identity() {
    check::group("A2c: U9, the radix identity, as a test rather than a production assert");

    // U9 asked whether this belongs in production. It does not: the
    // constructor establishes it a few lines earlier, and the four
    // static_asserts at block_pack.cpp:32-35 already pin the Axis ordering the
    // array indexing depends on. What it IS good for is catching a swapped or
    // dropped radix from outside, which is what this does.
    //
    // Two forms, because they fail differently. The outermost form catches a
    // stride that is wrong by an overall factor; the adjacent-pair form
    // catches a pair swapped in the middle, which leaves the outermost
    // product alone.
    const WeightShape shapes[5] = {
        WeightShape{3, 3, 512, 512},
        WeightShape{3, 5, 100, 50},
        WeightShape{5, 3, 50, 100},
        WeightShape{3, 3, 1, 4},
        WeightShape{1, 1, 1, 1},
    };
    const std::int32_t cins[5]  = {16, 32, 8, 1, 1};
    const std::int32_t couts[5] = {16, 8, 32, 1, 1};

    for (int i = 0; i < 5; ++i) {
        const BlockPackMapper m(shapes[i], cins[i], couts[i], 2);

        // block_len(outermost) * line_stride(outermost) == num_lines()
        CHECK_EQ(m.block_len(Axis::KH) * m.line_stride(Axis::KH), m.num_lines().get());

        // line_stride(outer) == block_len(inner) * line_stride(inner), walking
        // the four axes in nesting order.
        for (int k = 0; k + 1 < 4; ++k) {
            const Axis outer = kAxes[k];
            const Axis inner = kAxes[k + 1];
            CHECK_EQ(m.line_stride(outer), m.block_len(inner) * m.line_stride(inner));
        }

        // The innermost axis closes the recursion: nothing is nested inside
        // COUT, so its stride is 1 by definition rather than by derivation.
        CHECK_EQ(m.line_stride(Axis::COUT), std::int64_t{1});
    }
}

void test_line_of_the_board_case() {
    check::group("A2c: line_of on B22's worked case");

    // 3x3x512x512 at 16/16. Strides (3072, 1024, 32, 1), num_lines 9216.
    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // The board's number: 1*3072 + 2*1024 + (80/16)*32 + (48/16)*1
    //                   = 3072 + 2048 + 160 + 3 = 5283.
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 48}).get(), std::int64_t{5283});

    // The board's burst, [kh=1, kw=2, cin=80, cout 0..511 stride 1]: 512
    // elements collapse to 32 distinct lines because cout_block is 16, and
    // those 32 ids are 5280..5311, contiguous. Contiguity is the property the
    // whole B22 argument rests on, so it is walked rather than sampled at the
    // ends.
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 0}).get(),   std::int64_t{5280});
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 511}).get(), std::int64_t{5311});

    std::vector<std::int64_t> burst;
    for (std::int32_t cout = 0; cout < 512; ++cout) {
        const std::int64_t l = m.line_of(Coord{1, 2, 80, cout}).get();
        if (burst.empty() || burst.back() != l) burst.push_back(l);
    }
    CHECK_EQ(check::ssize(burst), std::int64_t{32});
    bool contiguous = true;
    for (std::size_t i = 0; i < burst.size(); ++i)
        contiguous = contiguous && burst[i] == 5280 + static_cast<std::int64_t>(i);
    CHECK_TRUE(contiguous);

    // Both extremes of the layer. The maximum is the tight one: a stride one
    // too small produces a maximum below num_lines - 1 and nothing crashes,
    // the ids simply alias, and no in-range check notices.
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}).get(), std::int64_t{0});
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}).get(), m.num_lines().get() - 1);
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}).get(), std::int64_t{9215});

    // The Horner spelling in block_pack.cpp's header comment, evaluated here,
    // must agree with the loop the code actually runs. The comment is
    // documentation and the loop is the implementation, and nothing else in
    // the tree checks that they say the same thing.
    const std::int64_t horner = ((1 * 3 + 2) * 32 + 5) * 32 + 3;
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 48}).get(), horner);

    // line_of returns a LineId, and the id it returns is the one the LineId
    // comparison operators see. Checked through the tagged type as well as
    // through .get(), because A1's whole point is that the tag survives.
    CHECK_TRUE(m.line_of(Coord{1, 2, 80, 48}) == LineId{5283});
    CHECK_TRUE(m.line_of(Coord{0, 0, 0, 0}) < m.num_lines());
}

void test_line_of_mid_block_and_the_step() {
    check::group("A2c: the divide is real, and one block step is one stride");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // Three different elements of the same 16x16 tile, all naming line 5283.
    // Neither is at a block boundary, so a flatten that dropped the division
    // returns three different numbers and none of them is 5283.
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 48}).get(), std::int64_t{5283});
    CHECK_EQ(m.line_of(Coord{1, 2, 85, 50}).get(), std::int64_t{5283});
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 51}).get(), std::int64_t{5283});
    CHECK_EQ(m.line_of(Coord{1, 2, 95, 63}).get(), std::int64_t{5283});  // last element of the tile

    // Crossing a block boundary moves the id by exactly that axis's stride,
    // which is a second statement of what a stride IS and is what catches a
    // stride read from the wrong slot of stride_[4].
    CHECK_EQ(m.line_of(Coord{1, 2, 96, 48}).get(),
             m.line_of(Coord{1, 2, 80, 48}).get() + m.line_stride(Axis::CIN));
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 64}).get(),
             m.line_of(Coord{1, 2, 80, 48}).get() + m.line_stride(Axis::COUT));
    CHECK_EQ(m.line_of(Coord{2, 2, 80, 48}).get(),
             m.line_of(Coord{1, 2, 80, 48}).get() + m.line_stride(Axis::KH));
    CHECK_EQ(m.line_of(Coord{1, 1, 80, 48}).get() + m.line_stride(Axis::KW),
             m.line_of(Coord{1, 2, 80, 48}).get());

    // The literal answers too, so the four checks above cannot both be wrong
    // in the same direction and still agree.
    CHECK_EQ(m.line_of(Coord{1, 2, 96, 48}).get(), std::int64_t{5315});
    CHECK_EQ(m.line_of(Coord{1, 2, 80, 64}).get(), std::int64_t{5284});

    // KH and KW are NOT blocked, so a one-step move on them is a whole stride
    // rather than a sixteenth of one. A flatten that divided all four axes by
    // cin_block would collapse kh 0, 1 and 2 onto one line here.
    CHECK_TRUE(m.line_of(Coord{0, 0, 0, 0}) != m.line_of(Coord{1, 0, 0, 0}));
    CHECK_TRUE(m.line_of(Coord{0, 0, 0, 0}) != m.line_of(Coord{0, 1, 0, 0}));
    CHECK_EQ(m.line_of(Coord{1, 0, 0, 0}).get(), m.line_stride(Axis::KH));
    CHECK_EQ(m.line_of(Coord{0, 1, 0, 0}).get(), m.line_stride(Axis::KW));

    // The asymmetric shape's three worked flattens, where a floor in either
    // divisor, a dropped KW, or a transposed pair all give a different answer.
    const BlockPackMapper asym(WeightShape{3, 5, 100, 50}, 32, 8, 2);
    CHECK_EQ(asym.line_of(Coord{0, 0, 96, 48}).get(), std::int64_t{27});
    CHECK_EQ(asym.line_of(Coord{1, 3, 64, 16}).get(), std::int64_t{240});
    CHECK_EQ(asym.line_of(Coord{2, 4, 99, 49}).get(), std::int64_t{419});
    CHECK_EQ(asym.line_of(Coord{2, 4, 99, 49}).get(), asym.num_lines().get() - 1);
    CHECK_EQ(asym.line_of(Coord{0, 0, 0, 0}).get(), std::int64_t{0});

    // And the tiny verification trace's layer, where the last element is 35.
    const BlockPackMapper tiny(WeightShape{3, 3, 1, 4}, 1, 1, 4);
    CHECK_EQ(tiny.line_of(Coord{2, 2, 0, 3}).get(), std::int64_t{35});
    CHECK_EQ(tiny.line_of(Coord{2, 2, 0, 3}).get(), tiny.num_lines().get() - 1);
}

void test_line_of_rejects_the_truncation_trap() {
    check::group("A2c: B25, a negative coordinate divides into a REAL line unless checked");

    // The point of this whole section. C++ integer division truncates toward
    // zero, so -1 / 16 == 0, not -1. Without the explicit check,
    // line_of(1, 2, -1, 48) would compute 1*3072 + 2*1024 + 0*32 + 3 = 5123,
    // an ordinary id inside [0, 9216) belonging to the tile
    // cin in [0, 16) x cout in [48, 64). Nothing about 5123 announces where it
    // came from, and the whole range cin in [-15, -1] lands on block 0 the
    // same way. An off-by-one in a caller's loop, or a trace field decoded at
    // the wrong offset, then produces a hit on a real line and a hit rate that
    // looks plausible.
    //
    // This is the v1 lesson the archive preserved. Signedness is what lets the
    // wrong value be REPRESENTED; only the check makes it VISIBLE.
    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // Every coordinate in [-(cin_block - 1), -1] divides to block 0. Walked,
    // not sampled: a check written as `v < -8` would pass a sampled test.
    for (std::int32_t cin = -15; cin <= -1; ++cin) {
        CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, cin, 48}));
    }
    // The same on COUT, which is the innermost axis and the one whose wrong
    // answer is nearest to the right one.
    for (std::int32_t cout = -15; cout <= -1; ++cout) {
        CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, 80, cout}));
    }
    // And on the two unblocked axes, where the divisor is 1 and a naive reader
    // might believe the sign takes care of itself. It does not: -1 / 1 == -1
    // multiplied by stride 3072 gives a NEGATIVE id, which is a different
    // failure from the aliasing above and is caught by the same check.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{-1, 2, 80, 48}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, -1, 80, 48}));

    // Overshoot aliases just as silently as undershoot: cin = 512 divides to
    // block 32, and 32 * 32 = 1024, so the flatten would walk into the next kw
    // plane and return a perfectly ordinary id.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, 512, 48}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, 80, 512}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{3, 2, 80, 48}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 3, 80, 48}));

    // The far ends, which is what a header decoded at the wrong offset
    // actually produces.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, INT32_MIN, 48}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, INT32_MAX, 48}));

    // The other side of every boundary, so that a check mutated into a blanket
    // refusal is not mistaken for a correct one. 0 and extent - 1 are legal on
    // all four axes.
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}).get(), std::int64_t{0});
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}).get(), std::int64_t{9215});
    CHECK_EQ(m.line_of(Coord{2, 0, 0, 0}).get(), m.line_stride(Axis::KH) * 2);
    CHECK_EQ(m.line_of(Coord{0, 0, 511, 0}).get(), m.line_stride(Axis::CIN) * 31);
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 511}).get(), std::int64_t{31});
}

void test_line_of_rejects_the_padded_tail() {
    check::group("A2c: B25, the padded tail passes a block_len check and is not an element");

    // The case B25 names. CIN = 100 with cin_block = 32 gives n_cin_blocks = 4,
    // so cin = 100 divides to block 3 and 3 < 4: a range check written against
    // block_len would accept it while it names an element the layer does not
    // have. The whole padded tail cin in [100, 128) gets through the same way,
    // and so does the tail cout in [50, 56) on the other axis.
    //
    // This is what makes the check read extent_on(shape_, a) rather than
    // block_len(a), and it is the assertion that fails if a later edit
    // "simplifies" the two into one.
    const BlockPackMapper m(WeightShape{3, 5, 100, 50}, 32, 8, 2);
    CHECK_EQ(m.block_len(Axis::CIN),  std::int64_t{4});
    CHECK_EQ(m.block_len(Axis::COUT), std::int64_t{7});

    // The whole padded tail on CIN. Every one of these divides to a block index
    // strictly less than block_len(CIN).
    for (std::int32_t cin = 100; cin < 128; ++cin) {
        CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, cin, 0}));
        CHECK_TRUE(static_cast<std::int64_t>(cin / 32) < m.block_len(Axis::CIN));
    }
    // The whole padded tail on COUT, likewise.
    for (std::int32_t cout = 50; cout < 56; ++cout) {
        CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 0, cout}));
        CHECK_TRUE(static_cast<std::int64_t>(cout / 8) < m.block_len(Axis::COUT));
    }
    // And the negative side of the same argument, stated on this shape too:
    // -1 / 32 == 0, which is a legal block index here.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, -1, 0}));
    CHECK_TRUE(std::int64_t{-1 / 32} < m.block_len(Axis::CIN));
    CHECK_TRUE(std::int64_t{-1 / 32} >= 0);

    // The last legal element on each axis is still accepted, so the tail
    // rejection is a boundary and not an off-by-one that lost a real column.
    CHECK_EQ(m.line_of(Coord{2, 4, 99, 49}).get(), std::int64_t{419});
    CHECK_EQ(m.line_of(Coord{0, 0, 99, 0}).get(), m.line_stride(Axis::CIN) * 3);
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 49}).get(), std::int64_t{6});
}

void test_line_of_range_message_and_type() {
    check::group("A2c: the range failure is out_of_range, and says which axis, what range, what value");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // The message carries the class prefix, the axis name, the half-open range
    // and the offending value. N11 asks for a diagnosable failure, and a
    // message that only restates the rule does not say which axis or what it
    // held. The range is a needle in its exact printed form, because "[0, 512)"
    // is what tells a reader the check is half-open.
    expect_message("CIN = -1",
                   range_thrown_by([&] { return m.line_of(Coord{1, 2, -1, 48}); }),
                   kPrefix, {"CIN", "coordinate", "[0, 512)", "got -1"});
    expect_message("CIN = -15",
                   range_thrown_by([&] { return m.line_of(Coord{1, 2, -15, 48}); }),
                   kPrefix, {"CIN", "coordinate", "[0, 512)", "got -15"});
    expect_message("CIN = 512",
                   range_thrown_by([&] { return m.line_of(Coord{0, 0, 512, 0}); }),
                   kPrefix, {"CIN", "coordinate", "[0, 512)", "got 512"});
    expect_message("KH = 3",
                   range_thrown_by([&] { return m.line_of(Coord{3, 0, 0, 0}); }),
                   kPrefix, {"KH", "coordinate", "[0, 3)", "got 3"});
    expect_message("KW = -1",
                   range_thrown_by([&] { return m.line_of(Coord{0, -1, 0, 0}); }),
                   kPrefix, {"KW", "coordinate", "[0, 3)", "got -1"});
    expect_message("COUT = 512",
                   range_thrown_by([&] { return m.line_of(Coord{0, 0, 0, 512}); }),
                   kPrefix, {"COUT", "coordinate", "[0, 512)", "got 512"});

    // Each message names ONE axis. A message that listed all four would
    // satisfy every containment check above.
    const std::string only_cin =
        range_thrown_by([&] { return m.line_of(Coord{0, 0, -1, 0}); });
    CHECK_TRUE(!contains(only_cin, "KH"));
    CHECK_TRUE(!contains(only_cin, "KW"));
    CHECK_TRUE(!contains(only_cin, "COUT"));

    // The type, pinned separately from the text. B25's whole vocabulary rests
    // on the distinction: invalid_argument is a configuration that is malformed
    // regardless of the layer and is found once at construction, out_of_range
    // is a well-formed coordinate outside THIS layer and is found per call
    // while a trace is being replayed. logic_error is programmer error.
    // A caller that catches one must not catch the other.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 2, -1, 48}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 0, 512, 0}));

    // Not invalid_argument, stated as its own check: invalid_argument and
    // out_of_range are siblings under logic_error, so a bare logic_error check
    // would accept either and the distinction would go untested.
    bool caught_invalid = false;
    try {
        (void)m.line_of(Coord{1, 2, -1, 48});
    } catch (const std::out_of_range&) {
        // right
    } catch (const std::invalid_argument&) {
        caught_invalid = true;
    } catch (...) {
    }
    CHECK_TRUE(!caught_invalid);

    // out_of_range derives from logic_error, so a caller catching the base
    // still sees it. Recorded because A2d's stubs throw a plain logic_error
    // and the two will coexist on the same object.
    CHECK_THROWS(std::logic_error, m.line_of(Coord{1, 2, -1, 48}));
}

void test_an_axis_outside_the_enumerators_refuses() {
    check::group("A2c: an Axis that is not one of the four is a program bug, not a range failure");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // extent_on's precedent, followed exactly: refuse rather than invent an
    // answer. A fallback here would be worse than in types.h, because
    // line_stride indexes stride_[4] and an out-of-enumerator cast is a read
    // past the end of the object. The switch is what stops that, and this is
    // the only check that says so.
    CHECK_THROWS(std::logic_error, m.line_stride(kNoSuchAxis));
    CHECK_THROWS(std::logic_error, m.block_len(kNoSuchAxis));

    // logic_error and NOT out_of_range, which is the same distinction the
    // previous function draws from the other side: an Axis of 9 did not come
    // from a range, it came from a cast or from uninitialised memory.
    bool line_stride_was_range = false;
    try {
        (void)m.line_stride(kNoSuchAxis);
    } catch (const std::out_of_range&) {
        line_stride_was_range = true;
    } catch (const std::logic_error&) {
    } catch (...) {
    }
    CHECK_TRUE(!line_stride_was_range);

    bool block_len_was_range = false;
    try {
        (void)m.block_len(kNoSuchAxis);
    } catch (const std::out_of_range&) {
        block_len_was_range = true;
    } catch (const std::logic_error&) {
    } catch (...) {
    }
    CHECK_TRUE(!block_len_was_range);

    // The messages name the function, so a stack with several per-axis switches
    // in it says which one refused.
    expect_message("line_stride, unknown Axis",
                   logic_thrown_by([&] { return m.line_stride(kNoSuchAxis); }),
                   "BlockPackMapper::line_stride", {"unknown Axis"});
    expect_message("block_len, unknown Axis",
                   logic_thrown_by([&] { return m.block_len(kNoSuchAxis); }),
                   "BlockPackMapper::block_len", {"unknown Axis"});

    // line_of takes a Coord and loops over the four enumerators itself, so it
    // has no way to be handed a bad Axis and there is no third case to write.
    // Stated as a check on the reachable half instead: every legal axis
    // answers, and none of the four throws.
    for (Axis a : kAxes) {
        CHECK_TRUE(m.line_stride(a) >= 1);
        CHECK_TRUE(m.block_len(a) >= 1);
    }
}

void test_line_of_is_onto_with_the_expected_fan_in() {
    check::group("A2c: line_of is onto [0, num_lines), and the fan-in is the block area");

    // The surjectivity B23 says the engine rests on, and the fan-in histogram
    // that makes it more than a reachability count. A rounding error in ONE
    // divisor leaves every line reachable and only moves mass between the
    // buckets, so the histogram is the half that catches it.
    //
    // 3x5x100x50 at cin_block 32 / cout_block 8. Neither extent divides, so the
    // last block on each axis is short: CIN has 3 full blocks of 32 and one of
    // 4, COUT has 6 full blocks of 8 and one of 2. The four products of those
    // are the four fan-in values, and the four counts are 3*5 = 15 kernel
    // positions times the number of (cin block, cout block) pairs of each kind.
    const WeightShape s{3, 5, 100, 50};
    const BlockPackMapper m(s, 32, 8, 2);
    const std::int64_t n = m.num_lines().get();
    CHECK_EQ(n, std::int64_t{420});

    std::vector<std::int64_t> fan(static_cast<std::size_t>(n), 0);
    std::int64_t visited = 0;
    bool all_in_range = true;
    for (std::int32_t kh = 0; kh < s.KH; ++kh)
        for (std::int32_t kw = 0; kw < s.KW; ++kw)
            for (std::int32_t cin = 0; cin < s.CIN; ++cin)
                for (std::int32_t cout = 0; cout < s.COUT; ++cout) {
                    const std::int64_t l = m.line_of(Coord{kh, kw, cin, cout}).get();
                    ++visited;
                    if (l < 0 || l >= n) {
                        all_in_range = false;
                        continue;
                    }
                    ++fan[static_cast<std::size_t>(l)];
                }

    CHECK_TRUE(all_in_range);
    CHECK_EQ(visited, std::int64_t{75000});  // KH * KW * CIN * COUT

    std::int64_t at256 = 0, at64 = 0, at32 = 0, at8 = 0, other = 0, unreached = 0;
    for (std::int64_t f : fan) {
        if (f == 0)        ++unreached;
        else if (f == 256) ++at256;   // 32 cin x 8 cout, a full block
        else if (f == 64)  ++at64;    // 32 cin x 2 cout, short on COUT only
        else if (f == 32)  ++at32;    //  4 cin x 8 cout, short on CIN only
        else if (f == 8)   ++at8;     //  4 cin x 2 cout, short on both
        else               ++other;
    }

    // Reachability: nothing unreachable, so num_lines is not loose.
    CHECK_EQ(unreached, std::int64_t{0});
    // And no fan-in the block geometry does not predict.
    CHECK_EQ(other, std::int64_t{0});

    // The histogram itself. 3 full cin blocks x 6 full cout blocks x 15 kernel
    // positions = 270; 3 x 1 x 15 = 45; 1 x 6 x 15 = 90; 1 x 1 x 15 = 15.
    CHECK_EQ(at256, std::int64_t{270});
    CHECK_EQ(at64,  std::int64_t{45});
    CHECK_EQ(at32,  std::int64_t{90});
    CHECK_EQ(at8,   std::int64_t{15});

    // The four buckets are all 420 lines, and the weighted sum is the tensor.
    CHECK_EQ(at256 + at64 + at32 + at8, n);
    CHECK_EQ(at256 * 256 + at64 * 64 + at32 * 32 + at8 * 8, std::int64_t{75000});
    CHECK_EQ(at256 * 256 + at64 * 64 + at32 * 32 + at8 * 8, visited);

    // A second, dividing shape, where the fan-in is uniform and equals the
    // block area exactly. The non-dividing case above cannot catch a mutation
    // that only breaks the full-block path, and this one cannot catch a
    // rounding error at all, so both are needed.
    const WeightShape t{2, 3, 32, 16};
    const BlockPackMapper u(t, 8, 4, 1);
    const std::int64_t un = u.num_lines().get();
    CHECK_EQ(un, std::int64_t{2 * 3 * 4 * 4});
    std::vector<std::int64_t> ufan(static_cast<std::size_t>(un), 0);
    for (std::int32_t kh = 0; kh < t.KH; ++kh)
        for (std::int32_t kw = 0; kw < t.KW; ++kw)
            for (std::int32_t cin = 0; cin < t.CIN; ++cin)
                for (std::int32_t cout = 0; cout < t.COUT; ++cout)
                    ++ufan[static_cast<std::size_t>(
                        u.line_of(Coord{kh, kw, cin, cout}).get())];
    bool uniform = true;
    for (std::int64_t f : ufan) uniform = uniform && f == 32;  // 8 * 4
    CHECK_TRUE(uniform);
    CHECK_EQ(check::ssize(ufan), un);
}

// ===========================================================================
// A2d: expand and locate
// ===========================================================================
//
// This section replaces the A2b tripwires that pinned the two logic_error
// stubs. The tripwires said so themselves: when A2d lands they FAIL, and they
// are to be replaced by the conformance suite rather than deleted, because the
// thing they were guarding (a stub quietly given a body, so that expand appends
// nothing and reads exactly like a burst that touched no lines) is guarded from
// then on by a suite that says what the two members must actually do.
//
// Three layers, and the order matters:
//
//   the conformance suite  every contract layout.h states, run over the real
//                          mapper in five configurations. Nothing here knows
//                          about blocking, so this is the half that says
//                          BlockPackMapper is an AddressMapper.
//   hand-computed values   what a block-packed expand and locate answer, which
//                          the conformance suite cannot check because it is
//                          parameterised over the interface.
//   the oracle             expand against the slow, obvious definition of what
//                          it means, over a generated burst set.

void test_a2d_conformance() {
    // Five configurations, because several contracts are inert under one of
    // them. At blocks 1x1 every element is its own line and the de-duplication
    // path never fires; at cout_block == COUT a whole COUT burst is one id and
    // the strictly-increasing check has almost nothing to compare; at blocks
    // that do not divide their extents the padded tail exists and num_lines()
    // is a ceiling. A mapper that passed only at one blocking would be a suite
    // that tested one blocking.
    //
    // The shape is small on purpose: c_num_lines_is_exact sweeps every element.
    const WeightShape shape{3, 3, 8, 12};
    const conformance::Env env = conformance::make_env(shape);

    conformance::run_all(BlockPackMapper(shape, 1, 1, 2), env,
                         "BlockPackMapper: one element per line");
    conformance::run_all(BlockPackMapper(shape, 4, 4, 2), env,
                         "BlockPackMapper: 4x4 blocks");
    conformance::run_all(BlockPackMapper(shape, 8, 12, 2), env,
                         "BlockPackMapper: a whole CIN x COUT plane per line");
    conformance::run_all(BlockPackMapper(shape, 3, 5, 2), env,
                         "BlockPackMapper: neither extent divides");
    conformance::run_all(BlockPackMapper(shape, 16, 16, 2), env,
                         "BlockPackMapper: blocks wider than their extents");

    // A shape with an extent of 1 on two axes, which is what a 1x1 convolution
    // looks like and where several of make_env's bursts degenerate.
    const WeightShape pointwise{1, 1, 16, 16};
    conformance::run_all(BlockPackMapper(pointwise, 4, 4, 2), conformance::make_env(pointwise),
                         "BlockPackMapper: 1x1 layer");

    // The corpus's own shape at the corpus's own blocking, so the suite is not
    // only run on fixtures. COUT 64 under cout_block 128 is the one place the
    // 7.7 GB corpus reaches the rounding path at all.
    const WeightShape corpus{3, 3, 256, 64};
    conformance::run_all(BlockPackMapper(corpus, 64, 128, 1), conformance::make_env(corpus),
                         "BlockPackMapper: a corpus-shaped layer");
}

void test_expand_hand_computed() {
    check::group("A2d: expand on B22's worked case, by hand");

    // 3x3x512x512 at 16/16. Strides (3072, 1024, 32, 1), num_lines 9216, and
    // line_of{1,2,80,48} == 5283, all pinned by A2c's own cases above.
    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // The board's burst: 512 COUT elements collapse to the 32 contiguous ids
    // 5280..5311. Contiguity along COUT is the whole of B22, and this is the
    // first test in the tree that gets it out of expand rather than out of a
    // loop over line_of.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 512, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{32});
        bool contiguous = check::ssize(out) == 32;
        for (std::size_t i = 0; contiguous && i < out.size(); ++i)
            contiguous = out[i] == LineId{5280 + static_cast<std::int64_t>(i)};
        CHECK_TRUE(contiguous);
    }

    // The off-by-one pair, which has to be present in BOTH directions: a far
    // end computed as `start + count * stride` gives 2 lines for the first and
    // 2 for the second, so only having them together tells the two apart.
    // cout 48..63 is one whole block; cout 48..64 crosses into the next.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 48}, Axis::COUT, 16, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{1});
        CHECK_TRUE(out[0] == LineId{5283});
    }
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 48}, Axis::COUT, 17, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{2});
        CHECK_TRUE(out[0] == LineId{5283});
        CHECK_TRUE(out[1] == LineId{5284});
    }

    // Stride exactly one block: no de-duplication at all, 32 elements to 32
    // lines. Stride two blocks: the gaps are real, 16 lines with every second
    // id missing. Both on the axis the corpus actually walks.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 32, 16}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{32});
        CHECK_TRUE(out[0] == LineId{5280});
        CHECK_TRUE(out[31] == LineId{5311});
    }
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 16, 32}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{16});
        bool every_other = check::ssize(out) == 16;
        for (std::size_t i = 0; every_other && i < out.size(); ++i)
            every_other = out[i] == LineId{5280 + 2 * static_cast<std::int64_t>(i)};
        CHECK_TRUE(every_other);
    }

    // Irregular de-duplication: elements 0, 5, 10, 15, 20 land in blocks
    // 0, 0, 0, 0, 1, which is neither "all distinct" nor "all the same" and is
    // the shape a stride coprime with the block produces.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 5, 5}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{2});
        CHECK_TRUE(out[0] == LineId{5280});
        CHECK_TRUE(out[1] == LineId{5281});
    }

    // A burst on CIN, the other blocked axis, where the spacing between ids is
    // line_stride(CIN) rather than 1. A mapper that assumed COUT would give a
    // contiguous run here.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 0, 48}, Axis::CIN, 4, 16}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{4});
        CHECK_TRUE(out[0] == LineId{5123});
        CHECK_TRUE(out[1] == LineId{5155});
        CHECK_TRUE(out[2] == LineId{5187});
        CHECK_TRUE(out[3] == LineId{5219});
    }

    // The A2a -> A2d carried obligation, in the file that owns it now: a burst
    // along an axis the layout does not block is legal and touches `count`
    // distinct lines, because KH and KW have a block size of 1. The corpus
    // never emits one, so only a test announces a regression here.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::KH, 3, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{3});
        CHECK_TRUE(out[0] == LineId{0});
        CHECK_TRUE(out[1] == LineId{3072});
        CHECK_TRUE(out[2] == LineId{6144});
    }
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::KW, 3, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{3});
        CHECK_TRUE(out[0] == LineId{0});
        CHECK_TRUE(out[1] == LineId{1024});
        CHECK_TRUE(out[2] == LineId{2048});
    }

    // The degenerate burst a cout_block of 1 produces, at the last element of
    // the layer: one element, one line, and it is num_lines() - 1.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{2, 2, 511, 511}, Axis::COUT, 1, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{1});
        CHECK_TRUE(out[0] == LineId{m.num_lines().get() - 1});
    }

    // Appends, and appends after whatever was already there. layout.h's reason
    // is the accumulate pattern: a whole tick's demand goes into one reused
    // buffer, so a mapper that assigned would keep only the last core's lines
    // and every earlier core's demand would vanish with no error anywhere.
    {
        std::vector<LineId> acc(3, LineId{-777});
        m.expand(Burst{Coord{1, 2, 80, 48}, Axis::COUT, 16, 1}, acc);
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 16, 1}, acc);
        CHECK_EQ(check::ssize(acc), std::int64_t{5});
        CHECK_TRUE(acc[0] == LineId{-777});
        CHECK_TRUE(acc[1] == LineId{-777});
        CHECK_TRUE(acc[2] == LineId{-777});
        CHECK_TRUE(acc[3] == LineId{5283});
        CHECK_TRUE(acc[4] == LineId{0});
        // And the buffer as a whole is NOT sorted, which layout.h says out loud
        // ("neither sorted nor unique across calls"). Asserting it here stops a
        // later reader from strengthening the per-call guarantee into a
        // per-buffer one that no caller can honour.
        CHECK_TRUE(acc[4] < acc[3]);
    }
}

void test_expand_rejects_a_malformed_stride() {
    check::group("A2d: B49, stride < 1 is invalid_argument and nothing is appended");

    // This function replaces `test_expand_is_strictly_increasing_whatever_the_walk`,
    // whose three cases asserted that a stride of 0 and a negative stride were
    // served. B49 settled that they are not, so those cases now describe a
    // burst the mapper refuses and their subject is the refusal.
    //
    // What went with them is worth stating rather than leaving as a gap for a
    // later reader to find: a downward walk was the only thing on this mapper
    // that made B31's unconditional sort observable, so the sort now has no
    // input that reorders anything. It is still there, and the reason it is
    // still there is in block_pack.cpp beside it; the matching mutation is an
    // intentional `allow` in tests/mutation_check.sh for the same reason
    // `A2c block_size_on invents an answer` is (B41), unreachable rather than
    // untested. The strictly-increasing guarantee itself is not untested: it is
    // asserted per call by c_single_call_strictly_increasing over seven
    // configurations, by the hand-computed cases above, and over 32,000
    // generated bursts in test_expand_against_the_oracle.
    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // invalid_argument and not out_of_range, the same tier as a bad count and
    // for the same reason: a stride of 0 asks for one element `count` times and
    // a negative stride is a run walking backwards, and `burst_stride` in the
    // format v2 header is the step to the NEXT element. Neither is a run a
    // trace can describe at any layer, so neither is a coordinate failure.
    //
    // Each anchor below is a legal coordinate and each count is legal, so the
    // stride is the only thing wrong with these bursts.
    expect_message("stride = 0",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{1, 2, 80, 48}, Axis::COUT, 4, 0}, out);
                   }),
                   kPrefix, {"burst stride", "must be >= 1", "got 0"});
    expect_message("stride = -1",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{1, 2, 80, 63}, Axis::COUT, 64, -1}, out);
                   }),
                   kPrefix, {"burst stride", "must be >= 1", "got -1"});
    expect_message("stride = -16",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{1, 2, 80, 63}, Axis::COUT, 4, -16}, out);
                   }),
                   kPrefix, {"burst stride", "must be >= 1", "got -16"});
    // The far end of the range, and the value whose negation overflows: a check
    // written as `-stride > 0` rather than `stride < 1` would let it through.
    expect_message("stride = INT32_MIN",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, INT32_MIN}, out);
                   }),
                   kPrefix, {"burst stride", "got -2147483648"});

    // The type, pinned separately from the text, on all four axes: the stride
    // check must not live inside a per-axis branch.
    for (Axis a : kAxes) {
        std::vector<LineId> out;
        CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, a, 4, 0}, out));
        CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, a, 1, -1}, out));
    }

    // NOT out_of_range, as its own check, for the reason B27 exists: the two
    // are siblings under logic_error, so a bare logic_error check would accept
    // either and the tier a catch site dispatches on would go untested.
    bool was_range = false;
    try {
        std::vector<LineId> out;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 0}, out);
    } catch (const std::out_of_range&) {
        was_range = true;
    } catch (const std::exception&) {
    } catch (...) {
    }
    CHECK_TRUE(!was_range);

    // Nothing appended. The strong guarantee is the same one the count check
    // and the range checks give, and it has to hold for a refusal reached this
    // early too.
    std::vector<LineId> acc;
    acc.push_back(LineId{99});
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, 0}, acc));
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 4, -1}, acc));
    CHECK_EQ(check::ssize(acc), std::int64_t{1});
    CHECK_TRUE(acc[0] == LineId{99});

    // The other side of the boundary: 1 is a legal stride, and so is a stride
    // wider than the block. Without these, a check mutated from `< 1` to `< 2`
    // would still reject everything above and still look correct.
    {
        std::vector<LineId> one;
        m.expand(Burst{Coord{1, 2, 80, 48}, Axis::COUT, 4, 1}, one);
        CHECK_EQ(check::ssize(one), std::int64_t{1});
        CHECK_TRUE(one[0] == LineId{5283});

        std::vector<LineId> wide;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 4, 32}, wide);
        CHECK_EQ(check::ssize(wide), std::int64_t{4});
        CHECK_TRUE(wide[0] == LineId{5280});
        CHECK_TRUE(wide[3] == LineId{5286});
    }
}

void test_expand_validates_count_then_stride_then_range() {
    check::group("A2d: which check fires when a burst is wrong in two ways at once");

    // Three of expand's refusals can apply to one burst, and the message says
    // which one the code reached first. layout.h states each rule and says
    // nothing about their order, exactly as it says nothing about the far-end
    // versus walk order (U13), so these cases pin what the code does rather
    // than a rule anybody wrote down. They are here because the order is
    // otherwise an accident: U10's re-throw at the engine boundary dispatches
    // on the exception TYPE, so a burst that is both malformed and out of range
    // reaches a different catch site depending on which check ran, and a later
    // unit would be written against an order nobody chose.
    //
    // The open question that owns the malformed-versus-out-of-range half of
    // this is U12 and it stays open: what is written here is the observation,
    // not the ruling.
    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // Count before stride. Both are malformed, both are invalid_argument, so
    // only the message separates them.
    expect_message("count 0 and stride 0 together",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 0}, out);
                   }),
                   kPrefix, {"burst count", "got 0"});
    expect_message("count -1 and stride -1 together",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, -1, -1}, out);
                   }),
                   kPrefix, {"burst count", "got -1"});

    // Stride before the coordinate range check, which is the tier boundary: the
    // burst below is malformed (stride 0) and also names a COUT the layer does
    // not have, and the stride check runs first, so it is invalid_argument and
    // the message names the stride. A mapper that ranged first would answer
    // out_of_range for the same burst.
    expect_message("stride 0 on an anchor past the extent",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 512}, Axis::COUT, 4, 0}, out);
                   }),
                   kPrefix, {"burst stride", "got 0"});
    // And the same burst through the type probe, since the message check alone
    // would pass on a mapper that threw the right text with the wrong type.
    {
        std::vector<LineId> out;
        CHECK_THROWS(std::invalid_argument,
                     m.expand(Burst{Coord{0, 0, 0, 512}, Axis::COUT, 4, 0}, out));
    }

    // The whole chain in one burst: a count, a stride and a coordinate all
    // wrong, and the count is what is reported.
    expect_message("all three wrong at once",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 512}, Axis::COUT, 0, 0}, out);
                   }),
                   kPrefix, {"burst count", "got 0"});
}

void test_expand_rejects_a_malformed_count() {
    check::group("A2d: B38, count < 1 is invalid_argument and nothing is appended");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // invalid_argument and not out_of_range: a count of zero is malformed
    // whatever layer it is applied to, and B27's vocabulary is what lets a
    // catch site tell a bad burst from a bad coordinate. v1 read a zero count
    // as a legal empty run; B38 dropped that reading because an empty burst is
    // a core asking for nothing, which under C1's serialization would need a
    // served time for a request with no lines.
    expect_message("count = 0",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 1}, out);
                   }),
                   kPrefix, {"count", "must be >= 1", "got 0"});
    expect_message("count = -1",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, -1, 1}, out);
                   }),
                   kPrefix, {"count", "must be >= 1", "got -1"});
    // The far end of the range, and the value whose negation overflows: a check
    // written as `-count > 0` rather than `count < 1` would let it through.
    expect_message("count = INT32_MIN",
                   thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, INT32_MIN, 1}, out);
                   }),
                   kPrefix, {"count", "got -2147483648"});

    // The type, pinned separately from the text, on all four axes: the count
    // check must not live inside a per-axis branch.
    for (Axis a : kAxes) {
        std::vector<LineId> out;
        CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, a, 0, 1}, out));
        CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, a, -1, 1}, out));
    }

    // NOT out_of_range, as its own check. The two are siblings under
    // logic_error, so a bare logic_error check would accept either and the
    // distinction B38 rests on would go untested.
    bool was_range = false;
    try {
        std::vector<LineId> out;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 1}, out);
    } catch (const std::out_of_range&) {
        was_range = true;
    } catch (const std::exception&) {
    } catch (...) {
    }
    CHECK_TRUE(!was_range);

    // Nothing appended, and the count check runs before the range check would
    // have: a zero-count burst whose anchor is fine leaves the buffer alone.
    std::vector<LineId> acc;
    acc.push_back(LineId{99});
    CHECK_THROWS(std::invalid_argument, m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 0, 1}, acc));
    CHECK_EQ(check::ssize(acc), std::int64_t{1});
    CHECK_TRUE(acc[0] == LineId{99});

    // The other side of the boundary: 1 is a legal count. Without this, a check
    // mutated from `< 1` to `< 2` would still reject everything above and still
    // look correct.
    std::vector<LineId> one;
    m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 1, 1}, one);
    CHECK_EQ(check::ssize(one), std::int64_t{1});
}

void test_expand_checks_the_far_end_in_int64() {
    check::group("A2d: the far end of the walk is computed and checked in 64 bits");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);

    // THE case for this check, and it is not the same as "a burst that leaves
    // the tensor". Every element of the walk is flattened through line_of,
    // which validates all four coordinates, so a burst running off the end
    // throws with or without a far-end check. What the far-end check buys is
    // that the coordinate it reports is the FAR END, computed in int64, rather
    // than whatever the walk happened to reach first after a narrowing to
    // int32.
    //
    // Anchor 0, stride 2^30, count 5: the elements are 0, 2^30, 2^31, 3*2^30
    // and 2^32. The last one truncates to a perfectly legal 0 on the way into
    // an int32 coordinate, which is the wrap this check exists to make
    // impossible. The message is the observable: 4294967296 is a number only
    // 64-bit arithmetic can produce, and a walk that discovered the failure one
    // element at a time would report 1073741824 instead.
    expect_message("stride 2^30, the far end wraps",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 5, 1 << 30}, out);
                       return 0;
                   }),
                   kPrefix, {"COUT", "coordinate out of range", "[0, 512)", "got 4294967296"});

    // The same argument at the other end, which the lower half of the check
    // owns. B49 changed what can reach it and this case is rebuilt around the
    // change: with `stride < 1` refused the walk can only run upward, so
    // `last >= start` always and `last < 0` holds exactly when the ANCHOR's own
    // coordinate on the walked axis is negative. A negative stride is no longer
    // available, and it is not needed.
    //
    // Anchor -8, count 4, stride 1: the elements are -8, -7, -6, -5, so the far
    // end is -5 while the first element the walk would reject is -8. That gap
    // is the whole point and it is the mirror of the 2^30 case above: with the
    // check the message names the far end, without it the message names
    // whatever the walk reached first. Both are COUT, both are out_of_range,
    // and only the value tells them apart, which is why this case asserts the
    // value rather than only the axis.
    expect_message("the far end is below zero",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, -8}, Axis::COUT, 4, 1}, out);
                       return 0;
                   }),
                   kPrefix, {"COUT", "coordinate out of range", "[0, 512)", "got -5"});

    // The ordinary one-past-the-end burst, where the far end and the first bad
    // element coincide. Present so the two cases above read as the extra they
    // are rather than as the only spelling that works.
    expect_message("one past the last element",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, 511}, Axis::COUT, 2, 1}, out);
                       return 0;
                   }),
                   kPrefix, {"COUT", "[0, 512)", "got 512"});

    // The boundary of the check, and the case that took work to find. `>= n`
    // and `> n` disagree on exactly one value, a far end sitting on the extent,
    // and BOTH spellings refuse it: the walk's last element is the coordinate n,
    // which line_of rejects with the same axis and the same value, so on an
    // ordinary burst the two are indistinguishable. What separates them is which
    // check fires FIRST, and the burst below is wrong twice on purpose so that
    // the answer differs: its COUT far end lands exactly on 512 and its anchor's
    // CIN is one past the layer. Checking the far end up front names COUT, the
    // failure this burst's own count and stride produced; discovering it during
    // the walk names CIN instead, because line_of validates the four
    // coordinates in Axis order and reaches the bad anchor first.
    //
    // layout.h does not say which of two simultaneous failures is reported, so
    // this pins what the code does rather than a rule anybody wrote down. It is
    // in the reviewer's report as a question for the same reason the malformed
    // versus out-of-range ordering is.
    expect_message("the far end lands exactly on the extent",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 512, 0}, Axis::COUT, 3, 256}, out);
                       return 0;
                   }),
                   kPrefix, {"COUT", "coordinate out of range", "[0, 512)", "got 512"});

    // The near end, which the far-end check does not look at. With `stride < 1`
    // refused the walk runs upward, so a burst can begin below zero and still
    // have a far end inside the layer: -5, count 10, stride 1 ends at 4. The
    // far-end check passes it and line_of rejects the first element, which is
    // the boundary of what a one-sided check can own. Present so that the
    // one-sidedness is a tested fact rather than an oversight, and so that the
    // "nothing appended" guarantee is shown to hold on this route too.
    expect_message("the near end is below zero, the far end is not",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 0, -5}, Axis::COUT, 10, 1}, out);
                       return 0;
                   }),
                   kPrefix, {"COUT", "coordinate out of range", "[0, 512)", "got -5"});

    // An anchor out of range on an axis the burst does NOT walk. The far-end
    // check only looks at the walked axis, so this one is line_of's to catch,
    // and it is the case that says the other three coordinates are validated at
    // all. It is the companion to the case above: together they say the far-end
    // check owns the walked axis and line_of owns the other three.
    expect_message("the anchor is out of range off-axis",
                   range_thrown_by([&] {
                       std::vector<LineId> out;
                       m.expand(Burst{Coord{0, 0, 512, 0}, Axis::COUT, 4, 1}, out);
                       return 0;
                   }),
                   kPrefix, {"CIN", "[0, 512)", "got 512"});

    // Whichever half fires, the type is out_of_range and the buffer is
    // untouched: the walk builds into a local vector and appends once, so the
    // strong guarantee holds by construction rather than by a rollback.
    const Burst offenders[5] = {
        Burst{Coord{0, 0, 0, 0}, Axis::COUT, 5, 1 << 30},
        Burst{Coord{0, 0, 0, -8}, Axis::COUT, 4, 1},
        Burst{Coord{0, 0, 0, -5}, Axis::COUT, 10, 1},
        Burst{Coord{0, 0, 0, 511}, Axis::COUT, 2, 1},
        Burst{Coord{0, 0, 512, 0}, Axis::COUT, 4, 1},
    };
    for (const Burst& b : offenders) {
        std::vector<LineId> acc;
        acc.push_back(LineId{-777});
        acc.push_back(LineId{5283});
        CHECK_THROWS(std::out_of_range, m.expand(b, acc));
        CHECK_EQ(check::ssize(acc), std::int64_t{2});
        CHECK_TRUE(acc[0] == LineId{-777});
        CHECK_TRUE(acc[1] == LineId{5283});
    }

    // The other side of the boundary. The widest legal burst on the axis, and
    // the widest legal strided one, both accepted: a far-end check written as
    // `start + count * stride` rejects the first of these, so the pair is what
    // makes the rejections above a boundary rather than a blanket refusal.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 512, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{32});
        std::vector<LineId> strided;
        m.expand(Burst{Coord{0, 0, 0, 0}, Axis::COUT, 2, 511}, strided);
        CHECK_EQ(check::ssize(strided), std::int64_t{2});
    }
}

void test_locate() {
    check::group("A2d: locate, and the range check that runs BEFORE the division");

    const BlockPackMapper m(WeightShape{3, 3, 512, 512}, 16, 16, 1);
    CHECK_EQ(m.num_lines().get(), std::int64_t{9216});

    // The identity, by hand, at a set count that is not the whole range:
    // 5283 = 82 * 64 + 35.
    const Placement p = m.locate(LineId{5283}, 64);
    CHECK_EQ(p.set_index, std::int64_t{35});
    CHECK_EQ(p.tag, std::int64_t{82});
    CHECK_EQ(p.tag * 64 + p.set_index, std::int64_t{5283});

    // The degenerate array: one set, so every line is in set 0 and the tag IS
    // the line. This is the configuration where a mapper that swapped the two
    // fields is at its most visible and a mapper that returned {0, 0} is not.
    const Placement one = m.locate(LineId{5283}, 1);
    CHECK_EQ(one.set_index, std::int64_t{0});
    CHECK_EQ(one.tag, std::int64_t{5283});

    // Both ends of the range, at several set counts, with the identity and the
    // postcondition together. The postcondition is what the range check buys:
    // LineId is signed (B5), so without it a negative id comes back out of
    // `line % num_sets` as a negative set index and a cache array subscripts
    // its slot vector from below (v1's F9).
    const std::int64_t set_counts[5] = {1, 2, 64, 1024, 9216};
    for (std::int64_t num_sets : set_counts) {
        const LineId ids[3] = {LineId{0}, LineId{5283}, LineId{9215}};
        for (LineId l : ids) {
            const Placement q = m.locate(l, num_sets);
            CHECK_TRUE(q.set_index >= 0);
            CHECK_TRUE(q.set_index < num_sets);
            CHECK_EQ(q.tag * num_sets + q.set_index, l.get());
        }
    }

    // A COUT-walking burst spreads over min(count, num_sets) distinct sets,
    // which is B22's set-spreading claim reached through the two members that
    // are supposed to deliver it rather than asserted about the radices.
    {
        std::vector<LineId> out;
        m.expand(Burst{Coord{1, 2, 80, 0}, Axis::COUT, 512, 1}, out);
        CHECK_EQ(check::ssize(out), std::int64_t{32});
        std::vector<std::int64_t> sets;
        for (LineId l : out) sets.push_back(m.locate(l, 32).set_index);
        std::sort(sets.begin(), sets.end());
        sets.erase(std::unique(sets.begin(), sets.end()), sets.end());
        CHECK_EQ(check::ssize(sets), std::int64_t{32});  // one line per set, alias free
    }

    // The range check itself, at both ends and one step outside each.
    CHECK_THROWS(std::out_of_range, m.locate(LineId{-1}, 64));
    CHECK_THROWS(std::out_of_range, m.locate(LineId{9216}, 64));
    CHECK_THROWS(std::out_of_range, m.locate(LineId{INT64_MIN}, 64));
    CHECK_THROWS(std::out_of_range, m.locate(LineId{INT64_MAX}, 64));
    // And the two ids just inside it, so the check is a boundary rather than a
    // blanket refusal that happens to reject the cases above.
    CHECK_EQ(m.locate(LineId{0}, 64).set_index, std::int64_t{0});
    CHECK_EQ(m.locate(LineId{9215}, 64).tag, std::int64_t{143});
    CHECK_EQ(m.locate(LineId{9215}, 64).set_index, std::int64_t{63});

    // The message, and the type. out_of_range, not invalid_argument: a LineId
    // outside [0, num_lines()) is well formed and outside THIS layer, which is
    // the middle tier of B27 and is the same tier line_of throws from.
    expect_message("line id -1",
                   range_thrown_by([&] { return m.locate(LineId{-1}, 64).tag; }),
                   kPrefix, {"line id out of range", "[0, 9216)", "got -1"});
    expect_message("line id num_lines()",
                   range_thrown_by([&] { return m.locate(LineId{9216}, 64).tag; }),
                   kPrefix, {"line id out of range", "[0, 9216)", "got 9216"});

    bool caught_invalid = false;
    try {
        (void)m.locate(LineId{-1}, 64);
    } catch (const std::out_of_range&) {
    } catch (const std::invalid_argument&) {
        caught_invalid = true;
    } catch (...) {
    }
    CHECK_TRUE(!caught_invalid);

    // No state: L1 and L2 share one mapper and call locate with different set
    // counts, interleaved, so an answer that depended on the previous call
    // would make the two levels able to disturb each other.
    const Placement a1 = m.locate(LineId{5283}, 64);
    (void)m.locate(LineId{7}, 1024);
    const Placement a2 = m.locate(LineId{5283}, 64);
    CHECK_EQ(a1.set_index, a2.set_index);
    CHECK_EQ(a1.tag, a2.tag);

    // NOT owned here, recorded so it is not read as covered: locate does not
    // validate num_sets, so `locate(l, 0)` divides by zero. layout.h states no
    // precondition on it and the plan gives no unit the check, so no case is
    // written for it and the reviewer's report carries it instead.
}

void test_expand_against_the_oracle() {
    check::group("A2d: expand against the slow, obvious definition of what it means");

    // TEST_DESIGN.md's group G, rebuilt for this mapper. The oracle enumerates
    // the burst one element at a time and flattens each with line_of, then
    // sorts and uniques. That is deliberately the definition rather than the
    // implementation: expand walks the same elements but reaches its answer
    // through one sort and one unique over a locally built vector, and the two
    // agree only if both are right.
    //
    // line_of is shared between the two, so this does not validate line_of;
    // A2c's own cases do that, and they are hand-computed rather than derived.
    //
    // Deterministic, with a fixed seed, so a failure reproduces exactly.
    std::mt19937 rng(20260818u);

    const WeightShape shapes[4] = {
        WeightShape{3, 3, 512, 512},  // the corpus
        WeightShape{1, 1, 7, 13},     // coprime with every block below, so every
                                      // partial trailing block is exercised
        WeightShape{3, 3, 10, 10},    // non-dividing
        WeightShape{2, 5, 8, 8},      // KH != KW, which is F11's whole lesson
    };
    const std::int32_t cin_blocks[4]  = {1, 2, 4, 8};
    const std::int32_t cout_blocks[5] = {1, 2, 4, 8, 16};

    std::int64_t bursts = 0;
    std::int64_t multi_line = 0;    // the burst touched more than one line
    std::int64_t deduped = 0;       // several elements shared a line
    bool agrees = true;
    bool increasing = true;
    bool in_range = true;
    bool appends = true;

    for (const WeightShape& s : shapes)
        for (std::int32_t cb : cin_blocks)
            for (std::int32_t ob : cout_blocks) {
                const BlockPackMapper m(s, cb, ob, 2);
                for (Axis a : kAxes) {
                    const std::int32_t n = extent_on(s, a);
                    for (int t = 0; t < 100; ++t) {
                        // The count is derived from the room left on the axis
                        // rather than drawn and rejected. Rejection loses every
                        // draw on an axis of extent 1, which the {1,1,7,13}
                        // shape has two of, and would leave the per-combination
                        // counts uneven and the total short (TEST_DESIGN's own
                        // correction to group G).
                        const std::int32_t anchor =
                            static_cast<std::int32_t>(rng() % static_cast<std::uint32_t>(n));
                        const std::int32_t stride =
                            static_cast<std::int32_t>(1 + rng() % 9u);
                        const std::int32_t room = (n - 1 - anchor) / stride + 1;
                        const std::int32_t cap = room < 32 ? room : 32;
                        const std::int32_t count =
                            static_cast<std::int32_t>(1 + rng() % static_cast<std::uint32_t>(cap));

                        const Burst b{with_coord_on(Coord{0, 0, 0, 0}, a, anchor), a, count,
                                      stride};

                        // The sentinel is what makes this an append test as
                        // well: it is checked to survive every one of the
                        // bursts below, not only the first.
                        std::vector<LineId> got;
                        got.push_back(LineId{-777});
                        m.expand(b, got);

                        std::vector<LineId> want;
                        for (std::int32_t i = 0; i < count; ++i)
                            want.push_back(m.line_of(
                                with_coord_on(b.anchor, a, anchor + i * stride)));
                        std::sort(want.begin(), want.end(),
                                  [](LineId x, LineId y) { return x < y; });
                        want.erase(std::unique(want.begin(), want.end(),
                                               [](LineId x, LineId y) { return x == y; }),
                                   want.end());

                        ++bursts;
                        if (want.size() > 1) ++multi_line;
                        if (static_cast<std::int32_t>(want.size()) < count) ++deduped;

                        appends = appends && !got.empty() && got[0] == LineId{-777};
                        agrees = agrees && got.size() == want.size() + 1;
                        for (std::size_t i = 0; agrees && i < want.size(); ++i)
                            agrees = got[i + 1] == want[i];
                        for (std::size_t i = 2; i < got.size(); ++i)
                            increasing = increasing && got[i - 1] < got[i];
                        for (std::size_t i = 1; i < got.size(); ++i)
                            in_range = in_range && LineId{-1} < got[i] && got[i] < m.num_lines();
                    }
                }
            }

    CHECK_TRUE(agrees);
    CHECK_TRUE(increasing);
    CHECK_TRUE(in_range);
    CHECK_TRUE(appends);
    CHECK_EQ(bursts, std::int64_t{4 * 4 * 5 * 4 * 100});

    // The coverage floors, which are F13's lesson: a large burst count can
    // still leave the interesting paths nearly untouched. Both are asserted
    // rather than reported, so a later edit to the generator that quietly
    // collapsed every burst to a single element fails here instead of passing
    // with a smaller suite.
    //
    // The two numbers are uneven on purpose, and both come from the structure
    // of the grid rather than from what a run happened to produce. Half the
    // bursts walk KH or KW, whose block size is 1, so they can never
    // de-duplicate at all; of the rest, the cin_block = 1 column and the
    // cout_block = 1 column cannot either. That leaves 12,400 of the 32,000
    // bursts able to de-duplicate even in principle, and only those whose
    // stride is narrower than the block actually do. A floor above that ceiling
    // would be a floor set to make the run pass.
    CHECK_TRUE(multi_line >= 3000);
    CHECK_TRUE(deduped >= 2000);
    std::printf("  oracle: %lld bursts, %lld multi-line, %lld de-duplicated\n",
                static_cast<long long>(bursts), static_cast<long long>(multi_line),
                static_cast<long long>(deduped));
}

// ===========================================================================
// Compile-time properties of A2b
// ===========================================================================
//
// Stated here, in the file that must build, so that losing one is a build
// failure rather than a silent weakening. The negative spellings are in
// compile_fail.sh.

static_assert(std::is_final<BlockPackMapper>::value,
              "B10: a differently nested layout is a new AddressMapper, not a subclass");
static_assert(std::is_base_of<AddressMapper, BlockPackMapper>::value, "");
static_assert(!std::is_abstract<BlockPackMapper>::value,
              "a validation increment whose object cannot be constructed cannot be tested");
static_assert(!std::is_default_constructible<BlockPackMapper>::value, "");

// The four AddressMapper members are really overrides, not overloads that left
// the base's pure virtuals unimplemented. `!is_abstract` above already implies
// it, and these say which four.
static_assert(std::is_same<decltype(&BlockPackMapper::expand),
                           void (BlockPackMapper::*)(const Burst&, std::vector<LineId>&)
                               const>::value, "");
static_assert(std::is_same<decltype(&BlockPackMapper::locate),
                           Placement (BlockPackMapper::*)(LineId, std::int64_t) const>::value, "");

// num_lines is a LineId and line_size_bytes an int64, on the concrete class as
// well as on the interface: a line count and a byte count are not the same
// quantity, and the concrete declarations are what a caller holding a
// BlockPackMapper by value actually binds to.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().num_lines()),
                           LineId>::value, "");
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().line_size_bytes()),
                           std::int64_t>::value, "");

// The accessors' widths, which are the whole point of exposing them: a block
// count is a factor of a line count, so it is int64 like the product, while a
// block SIZE is int32 like the extents it divides. Narrowing n_cin_blocks to
// int32 is exactly the mixed-width expression the v1 line_of bug lived in.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().n_cin_blocks()),
                           std::int64_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().n_cout_blocks()),
                           std::int64_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().cin_block()),
                           std::int32_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().cout_block()),
                           std::int32_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().weight_bytes()),
                           std::int32_t>::value, "");
// shape() hands back a reference to the stored shape, and a const one: the
// layer geometry is fixed at construction and every derived value was computed
// from it, so a caller that could write through this accessor would leave
// num_lines() describing a tensor the mapper no longer has.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().shape()),
                           const WeightShape&>::value, "");

// --- A2c ---------------------------------------------------------------------
//
// line_stride returns std::int64_t and NOT LineId, and that is B24 and the A2b
// to A2c board row rather than a style choice: a stride is a DELTA and LineId
// is an address. LineId is a Tagged with no arithmetic at all, so a stride
// typed as LineId could not be multiplied by a block index without stripping
// the tag at every use, and a tag that has to be stripped before every use
// carries nothing. v1 returned LineId here. Stated as an exact-type assert
// rather than as is_integral, because int32 would also be integral and would
// be the mixed-width expression the v1 line_of bug lived in.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().line_stride(Axis::KH)),
                           std::int64_t>::value,
              "B24: a stride is a delta, not a LineId");
static_assert(!std::is_same<decltype(std::declval<const BlockPackMapper&>().line_stride(Axis::KH)),
                            LineId>::value, "");

// block_len is int64 for the same reason the two block-count accessors are: a
// block count is a factor of a line count, and keeping a factor narrower than
// its product is the boundary the v1 signedness class lived on.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>().block_len(Axis::CIN)),
                           std::int64_t>::value, "");

// line_of is the one that DOES return a LineId: it names an address, so the
// arithmetic is done in plain int64 and the tag is put on once, at the return.
static_assert(std::is_same<decltype(std::declval<const BlockPackMapper&>()
                                        .line_of(std::declval<const Coord&>())),
                           LineId>::value, "");

// All three are const. One mapper serves L1 and L2, so a helper that could
// mutate the mapper while answering a query would make the two levels able to
// disturb each other.
static_assert(std::is_same<decltype(&BlockPackMapper::line_stride),
                           std::int64_t (BlockPackMapper::*)(Axis) const>::value, "");
static_assert(std::is_same<decltype(&BlockPackMapper::block_len),
                           std::int64_t (BlockPackMapper::*)(Axis) const>::value, "");
static_assert(std::is_same<decltype(&BlockPackMapper::line_of),
                           LineId (BlockPackMapper::*)(const Coord&) const>::value, "");

}  // namespace

int main() {
    test_accessors_return_what_was_constructed();
    test_an_asymmetric_configuration();
    test_blocks_covering_rounds_up();
    test_line_size_never_reads_the_shape();
    test_rejects_a_non_positive_extent();
    test_rejects_a_non_positive_block();
    test_rejects_an_overflowing_configuration();
    test_line_stride_is_the_b17_radices();
    test_block_len_is_the_extent_in_lines();
    test_the_radix_identity();
    test_line_of_the_board_case();
    test_line_of_mid_block_and_the_step();
    test_line_of_rejects_the_truncation_trap();
    test_line_of_rejects_the_padded_tail();
    test_line_of_range_message_and_type();
    test_an_axis_outside_the_enumerators_refuses();
    test_line_of_is_onto_with_the_expected_fan_in();
    test_a2d_conformance();
    test_expand_hand_computed();
    test_expand_rejects_a_malformed_count();
    test_expand_rejects_a_malformed_stride();
    test_expand_validates_count_then_stride_then_range();
    test_expand_checks_the_far_end_in_int64();
    test_locate();
    test_expand_against_the_oracle();
    return check::summary();
}
