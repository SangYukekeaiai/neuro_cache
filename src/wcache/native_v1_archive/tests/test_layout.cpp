// Fixture tests for unit 1 (BlockPackMapper geometry and burst expansion)
// and unit 2 (locate). Design: src/wcache/TEST_DESIGN.md.
//
// Groups A through F and I are hand-computed values, so they also serve as a
// regression on the numbers quoted in REVIEW.md. Group G is the part that
// actually establishes correctness: a brute-force oracle that computes what
// expand means the slow, obvious way and compares.
//
//   make -C src/wcache/native test

#include "check.h"
#include "wcache/layout.h"

#include <algorithm>
#include <cstdint>
#include <random>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

using namespace wcache;
using Lines = std::vector<LineId>;

// ---------------------------------------------------------------- helpers

// The real layer used throughout the sweep, and the corpus's block sizes.
static WeightShape real_shape() { return WeightShape{3, 3, 512, 512}; }
static BlockPackMapper real_mapper() { return BlockPackMapper(real_shape(), 4, 4, 1); }

static Coord with_coord(Coord c, Axis a, std::int32_t v) {
    switch (a) {
        case Axis::KH:   c.kh   = v; break;
        case Axis::KW:   c.kw   = v; break;
        case Axis::CIN:  c.cin  = v; break;
        case Axis::COUT: c.cout = v; break;
    }
    return c;
}

static Lines expand_of(const BlockPackMapper& m, const Burst& b) {
    Lines out;
    m.expand(b, out);
    return out;
}

// The oracle. Enumerates the run one element at a time and asks line_of
// where each one lives, then sorts and uniques. Computed a completely
// different way from the block-range arithmetic under test: expand
// short-circuits the whole contiguous range in the unit-stride path, this
// never does.
//
// line_of is shared between the two, so this does not validate line_of
// itself. Group D tests line_of standing alone and group B derives the
// strides from it independently, which closes that gap.
static Lines oracle(const BlockPackMapper& m, const Burst& b) {
    Lines v;
    const std::int32_t start = coord_on(b.anchor, b.axis);
    for (std::int32_t i = 0; i < b.count; ++i) {
        v.push_back(m.line_of(with_coord(b.anchor, b.axis, start + i * b.stride)));
    }
    std::sort(v.begin(), v.end());
    v.erase(std::unique(v.begin(), v.end()), v.end());
    return v;
}

// ------------------------------------------ A: constructor, derived sizes

static void group_a() {
    check::group("A  constructor and derived quantities");

    BlockPackMapper m = real_mapper();
    CHECK_EQ(m.n_cin_blocks(), 128);                        // A1
    CHECK_EQ(m.n_cout_blocks(), 128);
    CHECK_EQ(m.num_lines(), 147456);                        // A3  3*3*128*128

    // A2: ceiling division, not floor. CIN 10 over blocks of 4 is 3 blocks.
    BlockPackMapper ceil_case(WeightShape{3, 3, 10, 512}, 4, 4, 1);
    CHECK_EQ(ceil_case.n_cin_blocks(), 3);

    // A4: with dims that divide, the packed size equals the true tensor size.
    CHECK_EQ(m.line_size_bytes(), 16);                      // 4 * 4 * 1
    CHECK_EQ(m.num_lines() * m.line_size_bytes(), 3 * 3 * 512 * 512);
    CHECK_EQ(m.weight_bytes(), 1);

    // A5: with dims that do not divide, padding is real and costs lines.
    BlockPackMapper pad(WeightShape{3, 3, 10, 10}, 4, 4, 1);
    CHECK_EQ(pad.num_lines(), 81);                          // 3*3*3*3
    CHECK_TRUE(pad.num_lines() * pad.line_size_bytes() > 3 * 3 * 10 * 10);

    // line_size_bytes tracks weight_bytes, which is a v2 header field.
    BlockPackMapper wide(real_shape(), 4, 4, 2);
    CHECK_EQ(wide.line_size_bytes(), 32);
    CHECK_EQ(wide.num_lines(), m.num_lines());              // layout unchanged

    // A6, A7: every rejected constructor argument.
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{0, 3, 512, 512}, 4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 0, 512, 512}, 4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 3, 0, 512}, 4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{3, 3, 512, 0}, 4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(WeightShape{-1, 3, 512, 512}, 4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), 0, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), 4, 0, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), -4, 4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), 4, -4, 1));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), 4, 4, 0));
    CHECK_THROWS(std::invalid_argument, BlockPackMapper(real_shape(), 4, 4, -1));

    // A8: 6.87e10 lines, past 32 bits. Fails loudly if a widening cast is
    // ever dropped from the constructor.
    BlockPackMapper huge(WeightShape{64, 64, 4096, 4096}, 1, 1, 1);
    CHECK_EQ(huge.num_lines(), std::int64_t{68719476736});
}

// ------------------------------------------------------- B: line_stride

static void group_b() {
    check::group("B  line_stride");

    BlockPackMapper m = real_mapper();                      // B1
    CHECK_EQ(m.line_stride(Axis::COUT), 1);
    CHECK_EQ(m.line_stride(Axis::CIN), 128);
    CHECK_EQ(m.line_stride(Axis::KW), 16384);               // 128*128
    CHECK_EQ(m.line_stride(Axis::KH), 49152);               // 3*128*128

    BlockPackMapper unit(real_shape(), 1, 1, 1);            // B2
    CHECK_EQ(unit.line_stride(Axis::COUT), 1);
    CHECK_EQ(unit.line_stride(Axis::CIN), 512);
    CHECK_EQ(unit.line_stride(Axis::KW), 262144);
    CHECK_EQ(unit.line_stride(Axis::KH), 786432);

    // B3 is what makes B1 more than a transcription of the code: it derives
    // each stride from line_of, which is the other side of the same
    // arithmetic, instead of restating the table.
    const Axis axes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};
    for (Axis a : axes) {
        const Coord base{1, 1, 4, 4};
        const std::int32_t stepped = coord_on(base, a) + m.block_len(a);
        CHECK_EQ(m.line_of(with_coord(base, a, stepped)) - m.line_of(base),
                 m.line_stride(a));
    }
}

// --------------------------------------------------------- C: block_len

static void group_c() {
    check::group("C  block_len");

    BlockPackMapper m = real_mapper();                      // C1
    CHECK_EQ(m.block_len(Axis::KH), 1);
    CHECK_EQ(m.block_len(Axis::KW), 1);
    CHECK_EQ(m.block_len(Axis::CIN), 4);
    CHECK_EQ(m.block_len(Axis::COUT), 4);

    BlockPackMapper rect(real_shape(), 2, 8, 1);            // C2
    CHECK_EQ(rect.block_len(Axis::KH), 1);                  // never packs across
    CHECK_EQ(rect.block_len(Axis::KW), 1);                  // the kernel axes
    CHECK_EQ(rect.block_len(Axis::CIN), 2);
    CHECK_EQ(rect.block_len(Axis::COUT), 8);
}

// ----------------------------------------------------------- D: line_of

static void group_d() {
    check::group("D  line_of");

    BlockPackMapper m = real_mapper();
    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}), 0);                        // D1
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}), m.num_lines() - 1);    // D2, no gap
    CHECK_EQ(m.line_of(Coord{2, 2, 511, 511}), 147455);
    CHECK_EQ(m.line_of(Coord{1, 1, 0, 0}), 65536);                    // D4

    // D3: every element of one 4x4 tile lands on the same line.
    for (std::int32_t ci = 0; ci < 4; ++ci) {
        for (std::int32_t co = 0; co < 4; ++co) {
            CHECK_EQ(m.line_of(Coord{1, 1, ci, co}), 65536);
        }
    }

    // D5: line_of is onto [0, num_lines). Every element of a tiny tensor,
    // and the set of line ids it produces is exactly the dense range. This is
    // the line-level version of the reachability check; group I does the
    // set-level one.
    BlockPackMapper tiny(WeightShape{2, 2, 8, 8}, 2, 2, 1);
    CHECK_EQ(tiny.num_lines(), 64);
    std::set<LineId> seen;
    for (std::int32_t kh = 0; kh < 2; ++kh)
        for (std::int32_t kw = 0; kw < 2; ++kw)
            for (std::int32_t ci = 0; ci < 8; ++ci)
                for (std::int32_t co = 0; co < 8; ++co)
                    seen.insert(tiny.line_of(Coord{kh, kw, ci, co}));
    CHECK_EQ(check::ssize(seen), tiny.num_lines());
    CHECK_EQ(*seen.begin(), 0);
    CHECK_EQ(*seen.rbegin(), tiny.num_lines() - 1);
}

// -------------------------------------------------- E: expand, unit stride

static void group_e() {
    check::group("E  expand at unit stride");

    BlockPackMapper m = real_mapper();

    // E1 and E6 are a pair and both must be present. If last_coord were
    // computed as start + count*stride instead of start + (count-1)*stride,
    // E1 would give 2 lines instead of 1 while E6 would still give 2, so
    // either case alone passes under one of the two possible bugs.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 1}),
             Lines{65536});                                            // E1
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 3}, Axis::COUT, 4, 1}),
             (Lines{65536, 65537}));                                   // E6

    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 2}, Axis::COUT, 4, 1}),
             (Lines{65536, 65537}));                                   // E2
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 16, 1}),
             (Lines{65536, 65537, 65538, 65539}));                     // E3

    BlockPackMapper narrow(real_shape(), 4, 1, 1);                     // E4
    CHECK_EQ(expand_of(narrow, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 1}),
             (Lines{262144, 262145, 262146, 262147}));

    BlockPackMapper wide(real_shape(), 4, 8, 1);                       // E5
    CHECK_EQ(expand_of(wide, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 1}),
             Lines{32768});

    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 1, 1}),
             Lines{65536});                                            // E7

    Lines whole_row = expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 512, 1});
    CHECK_EQ(check::ssize(whole_row), 128);                            // E8
    CHECK_EQ(whole_row.front(), 65536);
    CHECK_EQ(whole_row.back(), 65663);

    // E9 to E11: the other three axes. block_len is 1 on KH and KW, so those
    // runs touch one line per element, spaced by the axis stride.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 6, 0}, Axis::CIN, 4, 1}),
             (Lines{65664, 65792}));                                   // E9
    CHECK_EQ(expand_of(m, Burst{{0, 0, 0, 0}, Axis::KH, 3, 1}),
             (Lines{0, 49152, 98304}));                                // E10
    CHECK_EQ(expand_of(m, Burst{{0, 0, 0, 0}, Axis::KW, 3, 1}),
             (Lines{0, 16384, 32768}));                                // E11
}

// ---------------------------------------------- F: expand, non-unit stride

static void group_f() {
    check::group("F  expand at non-unit stride");

    BlockPackMapper m = real_mapper();

    // F1: cout 0,8,16,24 lands on blocks 0,2,4,6. Blocks 1,3,5 are skipped
    // entirely, which the contiguous-range path cannot express.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 8}),
             (Lines{65536, 65538, 65540, 65542}));
    // F2: cout 0,2,4,6 lands on blocks 0,0,1,1, so dedup fires.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 2}),
             (Lines{65536, 65537}));
    // F3: stride exactly the block size, one line per element, no dedup.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 4, 4}),
             (Lines{65536, 65537, 65538, 65539}));
    // F4: cout 0,3,6,9,12 lands on blocks 0,0,1,2,3. Irregular dedup, not a
    // clean every-other pattern.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::COUT, 5, 3}),
             (Lines{65536, 65537, 65538, 65539}));
    // F5: the strided path and the axis generality are separate mechanisms,
    // and F1 to F4 exercise only one of them.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 0}, Axis::CIN, 3, 5}),
             (Lines{65536, 65664, 65792}));
}

// -------------------------------------- G: contract invariants vs. oracle

struct GStats {
    std::int64_t bursts = 0;
    std::int64_t lines  = 0;
    std::int64_t g1 = 0, g2 = 0, g3 = 0, g4 = 0, g5 = 0, g6 = 0;
    // Shape of the generated set, not correctness. A count of bursts says
    // nothing about coverage if most of them are single-element no-ops, and an
    // earlier generator produced exactly that: 76% degenerate, and only 4.3% of
    // the total reaching the contiguous range logic with more than one line to
    // emit. These are asserted below so a future edit to the generator cannot
    // quietly hollow the group out again.
    std::int64_t contiguous = 0;        // stride == 1, the path production takes
    std::int64_t contiguous_multi = 0;  // and emitting more than one line
    std::int64_t strided_multi = 0;     // strided path, more than one line
    std::int64_t degenerate = 0;        // count == 1
    int reported = 0;
};

static void check_one_burst(const BlockPackMapper& m, const Burst& b, GStats& s) {
    // G6: expand appends. Pre-fill with a sentinel and confirm it survives.
    // Worth its own invariant because appending is a deliberate interface
    // choice, and this is what fails if it is ever reversed.
    const LineId sentinel = -12345;
    Lines out;
    out.push_back(sentinel);
    m.expand(b, out);
    if (out.empty() || out[0] != sentinel) ++s.g6;

    const Lines got(out.begin() + 1, out.end());
    ++s.bursts;
    s.lines += check::ssize(got);

    const bool multi = got.size() > 1;
    if (b.count == 1)                 ++s.degenerate;
    if (b.stride == 1)                ++s.contiguous;
    if (b.stride == 1 && multi)       ++s.contiguous_multi;
    if (b.stride != 1 && multi)       ++s.strided_multi;

    for (std::size_t i = 1; i < got.size(); ++i) {
        if (got[i] <= got[i - 1]) { ++s.g1; break; }        // G1 increasing
    }
    std::set<LineId> uniq(got.begin(), got.end());
    if (check::ssize(uniq) != check::ssize(got)) ++s.g2;    // G2 no duplicates
    for (LineId l : got) {
        if (l < 0 || l >= m.num_lines()) { ++s.g3; break; } // G3 in range
    }

    const Lines want = oracle(m, b);
    if (got != want) {                                      // G4 equals oracle
        ++s.g4;
        if (s.reported < 5) {
            ++s.reported;
            std::printf("  mismatch: anchor{%d,%d,%d,%d} axis=%d count=%d stride=%d\n"
                        "    expand : %s\n    oracle : %s\n",
                        b.anchor.kh, b.anchor.kw, b.anchor.cin, b.anchor.cout,
                        static_cast<int>(b.axis), b.count, b.stride,
                        check::to_str(got).c_str(), check::to_str(want).c_str());
        }
    }
    // G5: every element the burst denotes has its line in the output.
    const std::int32_t start = coord_on(b.anchor, b.axis);
    for (std::int32_t i = 0; i < b.count; ++i) {
        const LineId l = m.line_of(with_coord(b.anchor, b.axis, start + i * b.stride));
        if (uniq.find(l) == uniq.end()) { ++s.g5; break; }
    }
}

static void group_g() {
    check::group("G  contract invariants against the brute-force oracle");

    // Deterministic: a fixed seed means a failure reproduces exactly.
    std::mt19937 rng(20260806u);

    const WeightShape shapes[5] = {
        {3, 3, 512, 512},  // the real layer
        {1, 1, 7, 13},     // odd primes, coprime with every block size below,
                           // so every partial trailing block is exercised
        {3, 3, 10, 10},    // dims that do not divide
        {2, 2, 8, 8},      // tiny, so a whole tensor is enumerable
        // Non-square kernel. Every shape above has KH == KW, which made four
        // separate KH/KW confusions invisible: swapping the two in
        // line_stride, in WeightShape::extent, in line_of's flatten, or in
        // line_of's own bound check each passed the whole suite. Non-square
        // kernels are ordinary (1x3, 3x1 and 7x1 factorized convolutions), and
        // one shape closes all four at once. Group J pins the hand values.
        {2, 5, 8, 8},
    };
    const std::int32_t cin_blocks[4]  = {1, 2, 4, 8};
    const std::int32_t cout_blocks[5] = {1, 2, 4, 8, 16};
    const Axis axes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};
    const int per_combo = 200;

    GStats s;
    for (const WeightShape& shape : shapes) {
        for (std::int32_t cb : cin_blocks) {
            for (std::int32_t ob : cout_blocks) {
                BlockPackMapper m(shape, cb, ob, 1);
                for (Axis a : axes) {
                    const std::int32_t extent = shape.extent(a);
                    for (int k = 0; k < per_combo; ++k) {
                        // Stride 1 half the time, rather than uniform over
                        // [1,9]. Uniform gave the contiguous path only 11% of
                        // the bursts, and per plan Part 1.1 the current trace
                        // decodes cout_start..cout_end into stride 1, so the
                        // contiguous path is the only one production traffic
                        // takes. The strided path still gets half.
                        const std::int32_t stride =
                            std::bernoulli_distribution(0.5)(rng)
                                ? 1
                                : std::uniform_int_distribution<std::int32_t>(2, 9)(rng);
                        // Draw the count from what the axis can hold, then
                        // place the anchor among the positions that fit.
                        // Drawing the anchor first and deriving the count from
                        // the room left collapsed 76% of bursts to a
                        // single-element no-op, because on an axis of extent 3
                        // a random anchor usually leaves no room. Every burst
                        // is still legal by construction, so the count stays
                        // exactly per_combo for every combination.
                        const std::int32_t max_count = (extent - 1) / stride + 1;
                        const std::int32_t count = std::uniform_int_distribution<std::int32_t>(
                            1, std::min(32, max_count))(rng);
                        const std::int32_t span  = (count - 1) * stride;
                        const std::int32_t start = std::uniform_int_distribution<std::int32_t>(
                            0, extent - 1 - span)(rng);
                        const Coord anchor{
                            std::uniform_int_distribution<std::int32_t>(0, shape.KH - 1)(rng),
                            std::uniform_int_distribution<std::int32_t>(0, shape.KW - 1)(rng),
                            std::uniform_int_distribution<std::int32_t>(0, shape.CIN - 1)(rng),
                            std::uniform_int_distribution<std::int32_t>(0, shape.COUT - 1)(rng)};
                        check_one_burst(
                            m, Burst{with_coord(anchor, a, start), a, count, stride}, s);
                    }
                }
            }
        }
    }

    std::printf("  %lld bursts, %lld lines emitted\n",
                static_cast<long long>(s.bursts), static_cast<long long>(s.lines));
    std::printf("  contiguous %lld (multi-line %lld), strided multi-line %lld, degenerate %lld\n",
                static_cast<long long>(s.contiguous),
                static_cast<long long>(s.contiguous_multi),
                static_cast<long long>(s.strided_multi),
                static_cast<long long>(s.degenerate));
    CHECK_EQ(s.bursts, std::int64_t{80000});
    // Coverage floors, not correctness. They exist because the previous
    // generator reported 64,000 bursts while giving the contiguous range logic
    // only 2,778 non-trivial cases, and nothing in the output showed it.
    //
    // The three floors are deliberately uneven, because the achievable ceiling
    // is uneven. A strided run needs an axis long enough to hold one:
    // max_count is (extent - 1) / stride + 1, so of the 20 shape-by-axis
    // combinations here, 5 (the KH or KW of {1,1,7,13}, {2,2,8,8} and {2,5,8,8})
    // have an extent of 1 or 2 and can NEVER emit a multi-line strided burst,
    // and 4 more at extent 3 manage it only at stride 2. Around 10,000 is
    // therefore near the structural maximum for strided_multi, not a target to
    // tune upward, and the same cap is most of why degenerate sits near half.
    // The contiguous floor is the one that should be high: that path takes all
    // of production's traffic and has no such limit on the long axes.
    CHECK_TRUE(s.contiguous_multi >= 20000);
    CHECK_TRUE(s.strided_multi >= 9000);
    CHECK_TRUE(s.degenerate <= s.bursts * 55 / 100);
    CHECK_EQ(s.g1, 0);   // strictly increasing within a call
    CHECK_EQ(s.g2, 0);   // no duplicates
    CHECK_EQ(s.g3, 0);   // every line in [0, num_lines)
    CHECK_EQ(s.g4, 0);   // equals the oracle exactly, as a sequence
    CHECK_EQ(s.g5, 0);   // every element's line is present
    CHECK_EQ(s.g6, 0);   // appends, does not assign
}

// ------------------------------------------------- H: edge and error cases

static void group_h() {
    check::group("H  edge and error cases");

    BlockPackMapper m = real_mapper();

    Lines out{999};
    m.expand(Burst{{1, 1, 0, 0}, Axis::COUT, 0, 1}, out);      // H1 legitimately empty
    CHECK_EQ(out, Lines{999});

    Lines sink;
    // H2: a negative count used to be swallowed as "empty", which made a
    // corrupt trace quietly drop one core's demand for a tick while a corrupt
    // stride stopped the run. Both are trace-sourced; both fail alike now.
    CHECK_THROWS(std::invalid_argument,
                 m.expand(Burst{{1, 1, 0, 0}, Axis::COUT, -1, 1}, sink));

    CHECK_THROWS(std::invalid_argument,                        // H3
                 m.expand(Burst{{1, 1, 0, 0}, Axis::COUT, 4, 0}, sink));
    CHECK_THROWS(std::invalid_argument,                        // H4
                 m.expand(Burst{{1, 1, 0, 0}, Axis::COUT, 4, -1}, sink));

    // H5 and H6 exist only because the extent check is a throw rather than an
    // assert. Under the old assert these two aborted the process and were
    // untestable, and in the sweep build they were not checked at all.
    CHECK_THROWS(std::out_of_range,                            // H5 runs off the end
                 m.expand(Burst{{1, 1, 0, 510}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                            // H6 starts below zero
                 m.expand(Burst{{1, 1, 0, -1}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                            // exactly one past
                 m.expand(Burst{{1, 1, 0, 511}, Axis::COUT, 2, 1}, sink));
    // The last legal element is accepted, so the check is not off by one.
    CHECK_EQ(expand_of(m, Burst{{1, 1, 0, 511}, Axis::COUT, 1, 1}),
             Lines{65536 + 127});
    // The overflow case from finding 2. Widened, this now throws; in 32 bits
    // (count-1)*stride wrapped to -1294967296 and the check passed.
    CHECK_THROWS(std::out_of_range,
                 m.expand(Burst{{1, 1, 0, 0}, Axis::COUT, 100001, 30000}, sink));

    // Every case above walks the COUT axis, which left the guard untested on
    // the other three. That was not academic: a build enforcing the upper
    // bound only when `axis == COUT`, and a build enforcing the lower bound
    // only when `axis == COUT`, each passed the whole suite. It matters
    // because types.h says format v2 carries burst_dim precisely so a future
    // arch can burst along CIN.
    const Axis axes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};
    for (Axis a : axes) {
        const std::int32_t last = real_shape().extent(a) - 1;
        // Starts on the last legal element and runs one past it.
        CHECK_THROWS(std::out_of_range,
                     m.expand(Burst{with_coord(Coord{0, 0, 0, 0}, a, last), a, 2, 1}, sink));
        // Starts below zero.
        CHECK_THROWS(std::out_of_range,
                     m.expand(Burst{with_coord(Coord{0, 0, 0, 0}, a, -1), a, 2, 1}, sink));
        // And the last legal element alone is still accepted.
        Lines ok;
        m.expand(Burst{with_coord(Coord{0, 0, 0, 0}, a, last), a, 1, 1}, ok);
        CHECK_EQ(check::ssize(ok), 1);
    }

    // The anchor's OTHER three coordinates, which expand's axis check never
    // sees. These were asserts, so in the sweep build they were not checked at
    // all, and signed division truncating toward zero meant a small negative
    // coordinate did not even go negative: it aliased onto block 0. Measured
    // under -DNDEBUG before the fix, all with a legal COUT burst:
    //   cin -1 gave line 65536, identical to the legal cin 0
    //   cin 512 gave 81920 and kw 3 gave 98304, both inside the tensor
    //   kh -1 gave -32767, which then hands locate a negative set index
    CHECK_THROWS(std::out_of_range,                     // aliases onto block 0
                 m.expand(Burst{{1, 1, -1, 0}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                     // a real neighbouring line
                 m.expand(Burst{{1, 1, -4, 0}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                     // one past CIN
                 m.expand(Burst{{1, 1, 512, 0}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                     // one past KW
                 m.expand(Burst{{1, 3, 0, 0}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                     // one past KH
                 m.expand(Burst{{3, 1, 0, 0}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range,                     // the negative-line case
                 m.expand(Burst{{-1, 1, 0, 4}, Axis::COUT, 4, 1}, sink));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 1, -1, 0}));
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{1, 1, 0, 512}));

    CHECK_EQ(check::ssize(sink), 0);  // nothing was appended by any of them
}

// ------------------------------------------------------- I: unit 2, locate

static void group_i() {
    check::group("I  locate");

    BlockPackMapper m = real_mapper();

    SetIndex p0 = m.locate(0, 1024);                       // I1
    CHECK_EQ(p0.set_index, 0);
    CHECK_EQ(p0.tag, 0);

    SetIndex p1 = m.locate(65537, 1024);                   // I2
    CHECK_EQ(p1.set_index, 1);
    CHECK_EQ(p1.tag, 64);

    CHECK_THROWS(std::invalid_argument, m.locate(0, 0));   // I6
    CHECK_THROWS(std::invalid_argument, m.locate(0, -1));

    // I8: the line itself must be in range, and this must hold in the sweep
    // build. It was an assert, on the grounds that any line reaching locate
    // came from this same mapper. The signedness change broke that reasoning:
    // signed % follows its dividend, so under -DNDEBUG locate(-32767, 1024)
    // returned set_index -1023, which a 32-way array turns into slot -32736.
    // That is an out-of-bounds subscript, not a wrong answer, and it was
    // reachable end to end from a malformed trace.
    CHECK_THROWS(std::out_of_range, m.locate(-1, 1024));
    CHECK_THROWS(std::out_of_range, m.locate(-32767, 1024));
    CHECK_THROWS(std::out_of_range, m.locate(m.num_lines(), 1024));

    const std::int64_t set_counts[4] = {1, 512, 1024, 4096};
    for (std::int64_t num_sets : set_counts) {
        std::set<std::int64_t> reached;
        std::set<std::pair<std::int64_t, std::int64_t>> placements;
        bool bounds_ok = true, rebuild_ok = true;
        for (LineId line = 0; line < m.num_lines(); ++line) {
            SetIndex p = m.locate(line, num_sets);
            if (p.set_index < 0 || p.set_index >= num_sets) bounds_ok = false;   // I4
            if (p.tag * num_sets + p.set_index != line) rebuild_ok = false;      // I3
            reached.insert(p.set_index);
            placements.insert({p.set_index, p.tag});
        }
        CHECK_TRUE(bounds_ok);
        CHECK_TRUE(rebuild_ok);
        // I5: every set is reachable. This is the whole point of indexing by
        // the flattened line id. The previous simulator indexed by the sum of
        // a line's tensor coordinates, which reached 50.6% of 512 sets, 25.3%
        // of 1024 and 6.3% of 4096 on this same layer.
        CHECK_EQ(check::ssize(reached), num_sets);
        // I7: distinct lines never share a (set, tag) pair, so a tag match
        // inside the matched set is a complete identity check and never an
        // aliasing one. Implied by I3, asserted separately so a failure names
        // the right cause.
        CHECK_EQ(check::ssize(placements), m.num_lines());
    }

    // Placement follows the layout, not the other way round: a different
    // block size gives a different line for the same element, and locate
    // follows it.
    BlockPackMapper narrow(real_shape(), 4, 1, 1);
    CHECK_EQ(narrow.locate(narrow.line_of(Coord{1, 1, 0, 0}), 1024).set_index,
             262144 % 1024);
}

// ------------------------------------------------ J: non-square kernel

// Every other shape in this file has KH == KW, which made the two axes
// indistinguishable. Four separate confusions passed the whole suite: reading
// shape_.KH in line_stride(KH), returning KW from WeightShape::extent(KH),
// using shape_.KH in line_of's flatten, and comparing c.kh against shape_.KW
// in line_of's own bound check. This group is small on purpose: the shape is
// what does the work, and every value below is derived by hand.
//
// Shape {KH=2, KW=5, CIN=8, COUT=8} at blocks 2x2, so n_cin = n_cout = 4 and
// num_lines = 2 * 5 * 4 * 4 = 160.
static void group_j() {
    check::group("J  non-square kernel, KH != KW");

    BlockPackMapper m(WeightShape{2, 5, 8, 8}, 2, 2, 1);
    CHECK_EQ(m.num_lines(), 160);

    // The strides are where KH and KW differ. Stepping one kh crosses a whole
    // kw row: KW * n_cin * n_cout = 5 * 16 = 80. Stepping one kw crosses
    // n_cin * n_cout = 16. If line_stride(KH) read KH instead of KW it would
    // give 2 * 16 = 32, and expand would disagree with line_of by 48.
    CHECK_EQ(m.line_stride(Axis::COUT), 1);
    CHECK_EQ(m.line_stride(Axis::CIN), 4);
    CHECK_EQ(m.line_stride(Axis::KW), 16);
    CHECK_EQ(m.line_stride(Axis::KH), 80);

    CHECK_EQ(m.line_of(Coord{0, 0, 0, 0}), 0);
    CHECK_EQ(m.line_of(Coord{1, 0, 0, 0}), 80);   // one kh
    CHECK_EQ(m.line_of(Coord{0, 1, 0, 0}), 16);   // one kw, deliberately different
    CHECK_EQ(m.line_of(Coord{1, 4, 7, 7}), 159);  // the last element, num_lines - 1

    // The two kernel axes have different extents, so a run legal on one is
    // illegal on the other. This is what catches a swapped WeightShape::extent.
    CHECK_EQ(expand_of(m, Burst{{0, 0, 0, 0}, Axis::KH, 2, 1}), (Lines{0, 80}));
    CHECK_EQ(expand_of(m, Burst{{0, 0, 0, 0}, Axis::KW, 5, 1}),
             (Lines{0, 16, 32, 48, 64}));
    Lines sink;
    CHECK_THROWS(std::out_of_range,                       // 3 exceeds KH = 2
                 m.expand(Burst{{0, 0, 0, 0}, Axis::KH, 3, 1}, sink));
    m.expand(Burst{{0, 0, 0, 0}, Axis::KW, 5, 1}, sink);  // but 5 is legal on KW
    CHECK_EQ(check::ssize(sink), 5);

    // line_of's own bound check must compare kh against KH and kw against KW.
    // The pair below is what tells those two comparisons apart: with KH = 2
    // and KW = 5, a kh of 2 is out of range while a kw of 2 is perfectly
    // legal, so a check that compared kh against KW would accept the first.
    // On a square shape no test can distinguish them, which is exactly how
    // that mutation survived the previous suite.
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{2, 0, 0, 0}));  // kh past KH
    CHECK_EQ(m.line_of(Coord{0, 2, 0, 0}), 32);                     // kw of 2 is legal
    CHECK_THROWS(std::out_of_range, m.line_of(Coord{0, 5, 0, 0}));  // kw past KW
    // And through expand, on an axis the burst does not walk, so only the
    // anchor validation can catch it.
    CHECK_THROWS(std::out_of_range,
                 m.expand(Burst{{2, 0, 0, 0}, Axis::COUT, 2, 1}, sink));

    // And the same on the packed axes, so the group is not purely about KH/KW.
    CHECK_EQ(expand_of(m, Burst{{1, 4, 0, 0}, Axis::COUT, 8, 1}),
             (Lines{144, 145, 146, 147}));
    CHECK_EQ(expand_of(m, Burst{{0, 0, 0, 0}, Axis::CIN, 8, 1}),
             (Lines{0, 4, 8, 12}));

    // Set reachability holds on a non-square shape too.
    std::set<std::int64_t> reached;
    for (LineId line = 0; line < m.num_lines(); ++line) {
        reached.insert(m.locate(line, 16).set_index);
    }
    CHECK_EQ(check::ssize(reached), 16);
}

int main() {
    group_a();
    group_b();
    group_c();
    group_d();
    group_e();
    group_f();
    group_g();
    group_h();
    group_i();
    group_j();
    return check::summary();
}
