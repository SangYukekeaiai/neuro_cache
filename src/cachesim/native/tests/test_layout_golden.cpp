// The observable mapping of all three layouts, pinned on a fixed grid.
//
// For every (shape, blocking, layout) case below this records, in a fixed
// order: num_lines, line_size_bytes, line_size_terms, line_of of every
// coordinate in the shape, expand of a set of bursts along every axis, and
// locate of every line id under several set counts. A last case per layout
// records the type and message of every refusal the mapper makes on a fixed
// set of bad inputs. The values are folded into one FNV-1a hash per case and
// compared against the table at the bottom, so a change to any line address,
// placement or refusal in any case turns this red.
//
// The table is output, not a specification. After an intended mapping change,
// regenerate it with
//
//     build/fixture/test_layout_golden --print-golden
//
// and paste the printed rows over kGolden.
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "cachesim/block_pack.h"
#include "cachesim/khkw_split.h"
#include "cachesim/layout.h"
#include "cachesim/split_cin.h"
#include "cachesim/types.h"

namespace {

using namespace cachesim;

struct Golden {
    const char*   name;
    std::int64_t  values;
    std::uint64_t hash;
};

// FNV-1a over the bytes of each value, plus a count of values folded in.
class Recorder {
public:
    void add(std::int64_t v) {
        auto u = static_cast<std::uint64_t>(v);
        for (int i = 0; i < 8; ++i) {
            hash_ ^= (u & 0xffu);
            hash_ *= 0x100000001b3ULL;
            u >>= 8;
        }
        ++values_;
    }
    void add(const std::string& s) {
        add(static_cast<std::int64_t>(s.size()));
        for (char ch : s) add(static_cast<std::int64_t>(static_cast<unsigned char>(ch)));
    }
    std::uint64_t hash() const { return hash_; }
    std::int64_t  values() const { return values_; }

private:
    std::uint64_t hash_   = 0xcbf29ce484222325ULL;
    std::int64_t  values_ = 0;
};

constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};
constexpr std::int64_t kNumSets[4] = {1, 3, 8, 64};

template <typename M>
void record(const M& m, const WeightShape& s, Recorder& r) {
    r.add(m.num_lines().get());
    r.add(m.line_size_bytes());
    r.add(m.line_size_terms(m.line_size_bytes()));

    for (std::int32_t kh = 0; kh < s.KH; ++kh)
    for (std::int32_t kw = 0; kw < s.KW; ++kw)
    for (std::int32_t ci = 0; ci < s.CIN; ++ci)
    for (std::int32_t co = 0; co < s.COUT; ++co) {
        const Coord c{kh, kw, ci, co};
        r.add(m.line_of(c).get());

        // Bursts anchored at walked coordinate 0 or 1: the longest run that
        // fits, and a run of 2, at strides 1, 2 and 3.
        for (Axis a : kAxes) {
            const std::int32_t at = coord_on(c, a);
            if (at > 1) continue;
            const std::int32_t n = extent_on(s, a);
            for (std::int32_t stride = 1; stride <= 3; ++stride) {
                const std::int32_t longest = (n - 1 - at) / stride + 1;
                for (std::int32_t count : {longest, 2}) {
                    if (count > longest) continue;
                    std::vector<LineId> out{LineId{-7}};  // expand appends
                    m.expand(Burst{c, a, count, stride}, out);
                    r.add(static_cast<std::int64_t>(out.size()));
                    for (const LineId& l : out) r.add(l.get());
                }
            }
        }
    }

    for (std::int64_t sets : kNumSets) {
        for (std::int64_t id = 0; id < m.num_lines().get(); ++id) {
            const Placement p = m.locate(LineId{id}, sets);
            r.add(p.set_index.get());
            r.add(p.tag.get());
        }
    }
}

// Runs f and records what came out: 0 if it returned, else a tag for the
// exception type followed by its message.
template <typename F>
void outcome(Recorder& r, F f) {
    try {
        f();
        r.add(0);
    } catch (const std::invalid_argument& e) {
        r.add(1);
        r.add(std::string(e.what()));
    } catch (const std::out_of_range& e) {
        r.add(2);
        r.add(std::string(e.what()));
    } catch (const std::logic_error& e) {
        r.add(3);
        r.add(std::string(e.what()));
    }
}

// Every refusal a constructed mapper makes on a fixed set of bad calls.
template <typename M>
void record_call_errors(const M& m, const WeightShape& s, Recorder& r) {
    for (Axis a : kAxes) {
        for (std::int32_t bad : {-1, extent_on(s, a)}) {
            const Coord c = with_coord_on(Coord{0, 0, 0, 0}, a, bad);
            outcome(r, [&] { (void)m.line_of(c); });
        }
    }
    std::vector<LineId> out;
    const Coord origin{0, 0, 0, 0};
    outcome(r, [&] { m.expand(Burst{origin, Axis::COUT, 0, 1}, out); });
    outcome(r, [&] { m.expand(Burst{origin, Axis::COUT, -3, 1}, out); });
    outcome(r, [&] { m.expand(Burst{origin, Axis::COUT, 1, 0}, out); });
    outcome(r, [&] { m.expand(Burst{origin, Axis::COUT, 1, -2}, out); });
    outcome(r, [&] { m.expand(Burst{origin, Axis::COUT, 0, 0}, out); });
    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(s, a);
        outcome(r, [&] { m.expand(Burst{origin, a, n + 1, 1}, out); });
        outcome(r, [&] { m.expand(Burst{with_coord_on(origin, a, -1), a, 1, 1}, out); });
        outcome(r, [&] { m.expand(Burst{origin, a, 2, 1 << 30}, out); });
    }
    outcome(r, [&] { m.expand(Burst{Coord{s.KH, 0, 0, 0}, Axis::COUT, 1, 1}, out); });
    outcome(r, [&] { m.expand(Burst{Coord{0, 0, -1, 0}, Axis::KW, 1, 1}, out); });
    r.add(static_cast<std::int64_t>(out.size()));
    const std::int64_t n = m.num_lines().get();
    for (std::int64_t id : {std::int64_t{-1}, n, n + 5}) {
        outcome(r, [&] { (void)m.locate(LineId{id}, 8); });
        outcome(r, [&] { (void)m.neighbour(LineId{id}, Axis::CIN, 1); });
    }
}

// Every refusal of a layout's constructor on a fixed set of bad arguments,
// then, if `calls`, the call refusals of one valid mapper. `make` builds the
// layout from (shape, cin_block, cout_block, weight_bytes).
template <typename Make>
void record_errors(Make make, bool calls, Recorder& r) {
    const WeightShape s{2, 3, 17, 9};
    constexpr std::int32_t kBig = std::numeric_limits<std::int32_t>::max();
    for (Axis a : kAxes) {
        for (std::int32_t bad : {0, -4}) {
            WeightShape t = s;
            if (a == Axis::KH) t.KH = bad;
            if (a == Axis::KW) t.KW = bad;
            if (a == Axis::CIN) t.CIN = bad;
            if (a == Axis::COUT) t.COUT = bad;
            outcome(r, [&] { (void)make(t, 5, 3, 1); });
        }
    }
    outcome(r, [&] { (void)make(s, 0, 3, 1); });
    outcome(r, [&] { (void)make(s, -1, 3, 1); });
    outcome(r, [&] { (void)make(s, 5, 0, 1); });
    outcome(r, [&] { (void)make(s, 5, -7, 1); });
    outcome(r, [&] { (void)make(s, 5, 3, 0); });
    outcome(r, [&] { (void)make(s, 5, 3, -1); });
    outcome(r, [&] { (void)make(s, kBig, kBig, kBig); });
    // Overflow with a small kernel: KhkwSplitMapper's constructor loops over
    // KH*KW positions, so a large KH*KW would hang here if the overflow guard
    // were ever broken instead of turning the case red.
    outcome(r, [&] { (void)make(WeightShape{2, 2, kBig, kBig}, 1, 1, 1); });
    outcome(r, [&] { (void)make(WeightShape{1, 3, kBig, kBig}, 1, 1, 1); });
    outcome(r, [&] { (void)make(WeightShape{1, 1, kBig, kBig}, 1, 1, 1); });
    if (calls) record_call_errors(make(s, 5, 3, 1), s, r);
}

struct Case {
    std::string   name;
    std::int64_t  values;
    std::uint64_t hash;
};

std::vector<Case> run_grid() {
    const WeightShape shapes[] = {
        {1, 1, 1, 4}, {3, 3, 64, 32}, {1, 1, 100, 30},
        {2, 3, 17, 9}, {5, 5, 8, 12}, {3, 1, 40, 6},
    };
    struct Blocking { std::int32_t cin, cout, bytes; };
    const Blocking blockings[] = {{1, 1, 1}, {4, 4, 1}, {16, 4, 2}, {5, 3, 1}, {64, 64, 1}};
    const std::int64_t cin_los[] = {1, 2, 3, 8};

    std::vector<Case> cases;
    const auto add_case = [&](const std::string& name, const auto& m, const WeightShape& s) {
        Recorder r;
        record(m, s, r);
        cases.push_back(Case{name, r.values(), r.hash()});
    };
    for (const WeightShape& s : shapes) {
        for (const Blocking& b : blockings) {
            const std::string tag = std::to_string(s.KH) + "x" + std::to_string(s.KW) + "x" +
                                    std::to_string(s.CIN) + "x" + std::to_string(s.COUT) +
                                    " blk " + std::to_string(b.cin) + "x" +
                                    std::to_string(b.cout) + " wb " + std::to_string(b.bytes);
            add_case("block_pack " + tag, BlockPackMapper(s, b.cin, b.cout, b.bytes), s);
            for (std::int64_t lo : cin_los) {
                add_case("split_cin lo " + std::to_string(lo) + " " + tag,
                         SplitCinMapper(s, b.cin, b.cout, b.bytes, lo), s);
            }
            add_case("khkw_split " + tag, KhkwSplitMapper(s, b.cin, b.cout, b.bytes), s);
        }
    }
    const auto add_errors = [&](const std::string& name, const auto& make, bool calls) {
        Recorder r;
        record_errors(make, calls, r);
        cases.push_back(Case{name, r.values(), r.hash()});
    };
    add_errors("errors block_pack", [](WeightShape s, std::int32_t ci, std::int32_t co,
                                       std::int32_t wb) { return BlockPackMapper(s, ci, co, wb); },
               true);
    for (std::int64_t lo : {std::int64_t{3}, std::int64_t{0}, std::int64_t{-2}}) {
        add_errors("errors split_cin lo " + std::to_string(lo),
                   [lo](WeightShape s, std::int32_t ci, std::int32_t co, std::int32_t wb) {
                       return SplitCinMapper(s, ci, co, wb, lo);
                   },
                   lo > 0);
    }
    add_errors("errors khkw_split", [](WeightShape s, std::int32_t ci, std::int32_t co,
                                       std::int32_t wb) { return KhkwSplitMapper(s, ci, co, wb); },
               true);
    return cases;
}

// Captured with --print-golden; see the top of this file.
const Golden kGolden[] = {
    {"block_pack 1x1x1x4 blk 1x1 wb 1", 236, 0x9c9c33f7a21340d9ULL},
    {"split_cin lo 1 1x1x1x4 blk 1x1 wb 1", 236, 0x9c9c33f7a21340d9ULL},
    {"split_cin lo 2 1x1x1x4 blk 1x1 wb 1", 260, 0x91be711d9ca4edd9ULL},
    {"split_cin lo 3 1x1x1x4 blk 1x1 wb 1", 284, 0x9ed5f7a87000fda1ULL},
    {"split_cin lo 8 1x1x1x4 blk 1x1 wb 1", 404, 0x51c273031a8458a6ULL},
    {"khkw_split 1x1x1x4 blk 1x1 wb 1", 236, 0x9c9c33f7a21340d9ULL},
    {"block_pack 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"split_cin lo 1 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"split_cin lo 2 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"split_cin lo 3 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"split_cin lo 8 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"khkw_split 1x1x1x4 blk 4x4 wb 1", 199, 0x4dc50456a419708dULL},
    {"block_pack 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"split_cin lo 1 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"split_cin lo 2 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"split_cin lo 3 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"split_cin lo 8 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"khkw_split 1x1x1x4 blk 16x4 wb 2", 200, 0x4d06d3e960d0ef6aULL},
    {"block_pack 1x1x1x4 blk 5x3 wb 1", 213, 0x7acc5e06d6000ee7ULL},
    {"split_cin lo 1 1x1x1x4 blk 5x3 wb 1", 213, 0x7acc5e06d6000ee7ULL},
    {"split_cin lo 2 1x1x1x4 blk 5x3 wb 1", 221, 0x69b7f8cec141ef86ULL},
    {"split_cin lo 3 1x1x1x4 blk 5x3 wb 1", 229, 0xc4db5d0d8990bc63ULL},
    {"split_cin lo 8 1x1x1x4 blk 5x3 wb 1", 269, 0x1a2f337aaf3bdc9dULL},
    {"khkw_split 1x1x1x4 blk 5x3 wb 1", 213, 0x7acc5e06d6000ee7ULL},
    {"block_pack 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"split_cin lo 1 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"split_cin lo 2 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"split_cin lo 3 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"split_cin lo 8 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"khkw_split 1x1x1x4 blk 64x64 wb 1", 201, 0x267ed2a17804fccbULL},
    {"block_pack 3x3x64x32 blk 1x1 wb 1", 749614, 0x9fb814271985cafdULL},
    {"split_cin lo 1 3x3x64x32 blk 1x1 wb 1", 749614, 0x9fb814271985cafdULL},
    {"split_cin lo 2 3x3x64x32 blk 1x1 wb 1", 749614, 0x82826ee12f9b3f31ULL},
    {"split_cin lo 3 3x3x64x32 blk 1x1 wb 1", 754206, 0xbfcfb019471248b1ULL},
    {"split_cin lo 8 3x3x64x32 blk 1x1 wb 1", 749614, 0x87bd3f281278a2c5ULL},
    {"khkw_split 3x3x64x32 blk 1x1 wb 1", 864246, 0x2c35b30b34f2f4c8ULL},
    {"block_pack 3x3x64x32 blk 4x4 wb 1", 527566, 0x2379024f3be655f4ULL},
    {"split_cin lo 1 3x3x64x32 blk 4x4 wb 1", 527566, 0x2379024f3be655f4ULL},
    {"split_cin lo 2 3x3x64x32 blk 4x4 wb 1", 527566, 0x3c4c7e154ce528e4ULL},
    {"split_cin lo 3 3x3x64x32 blk 4x4 wb 1", 528702, 0xdcbe1c823b55191fULL},
    {"split_cin lo 8 3x3x64x32 blk 4x4 wb 1", 527566, 0xe4cd17e4e82c96c4ULL},
    {"khkw_split 3x3x64x32 blk 4x4 wb 1", 534678, 0x34ddb289e11c5dd3ULL},
    {"block_pack 3x3x64x32 blk 16x4 wb 2", 499631, 0x840872e790ad0f28ULL},
    {"split_cin lo 1 3x3x64x32 blk 16x4 wb 2", 499631, 0x840872e790ad0f28ULL},
    {"split_cin lo 2 3x3x64x32 blk 16x4 wb 2", 499631, 0xdda3ff4b30328128ULL},
    {"split_cin lo 3 3x3x64x32 blk 16x4 wb 2", 500767, 0x9e5dc20a3be5ec48ULL},
    {"split_cin lo 8 3x3x64x32 blk 16x4 wb 2", 501903, 0x373d7e1c8e128819ULL},
    {"khkw_split 3x3x64x32 blk 16x4 wb 2", 501367, 0xa0810c55325d912aULL},
    {"block_pack 3x3x64x32 blk 5x3 wb 1", 534694, 0xc08adb2f9f340cd1ULL},
    {"split_cin lo 1 3x3x64x32 blk 5x3 wb 1", 534694, 0xc08adb2f9f340cd1ULL},
    {"split_cin lo 2 3x3x64x32 blk 5x3 wb 1", 535478, 0xbd39e2fd806a1df5ULL},
    {"split_cin lo 3 3x3x64x32 blk 5x3 wb 1", 536262, 0x0a0f7af3d431f056ULL},
    {"split_cin lo 8 3x3x64x32 blk 5x3 wb 1", 537046, 0x4eaa06a6110771bfULL},
    {"khkw_split 3x3x64x32 blk 5x3 wb 1", 542646, 0xd11e1917e10e7849ULL},
    {"block_pack 3x3x64x32 blk 64x64 wb 1", 467448, 0x3f8550d4e096336eULL},
    {"split_cin lo 1 3x3x64x32 blk 64x64 wb 1", 467448, 0x3f8550d4e096336eULL},
    {"split_cin lo 2 3x3x64x32 blk 64x64 wb 1", 467512, 0x5746c9b75be898f3ULL},
    {"split_cin lo 3 3x3x64x32 blk 64x64 wb 1", 467576, 0x0f26609f5942add4ULL},
    {"split_cin lo 8 3x3x64x32 blk 64x64 wb 1", 467896, 0xb1878c27b6336458ULL},
    {"khkw_split 3x3x64x32 blk 64x64 wb 1", 467448, 0x3f8550d4e096336eULL},
    {"block_pack 1x1x100x30 blk 1x1 wb 1", 107606, 0xaef606bdf418a03fULL},
    {"split_cin lo 1 1x1x100x30 blk 1x1 wb 1", 107606, 0xaef606bdf418a03fULL},
    {"split_cin lo 2 1x1x100x30 blk 1x1 wb 1", 107606, 0xbfb2aa6e6d24c290ULL},
    {"split_cin lo 3 1x1x100x30 blk 1x1 wb 1", 108070, 0xc0a9ec7c0d278910ULL},
    {"split_cin lo 8 1x1x100x30 blk 1x1 wb 1", 108534, 0xb8e6c007210c65bdULL},
    {"khkw_split 1x1x100x30 blk 1x1 wb 1", 107606, 0xa984d90c4b87eb0aULL},
    {"block_pack 1x1x100x30 blk 4x4 wb 1", 71876, 0xd2795160759c6348ULL},
    {"split_cin lo 1 1x1x100x30 blk 4x4 wb 1", 71876, 0xd2795160759c6348ULL},
    {"split_cin lo 2 1x1x100x30 blk 4x4 wb 1", 71932, 0x41255070bf509c55ULL},
    {"split_cin lo 3 1x1x100x30 blk 4x4 wb 1", 71988, 0xbf7e3cd92f565554ULL},
    {"split_cin lo 8 1x1x100x30 blk 4x4 wb 1", 72268, 0x1d120c290f258b35ULL},
    {"khkw_split 1x1x100x30 blk 4x4 wb 1", 71876, 0xcb007a53ad143188ULL},
    {"block_pack 1x1x100x30 blk 16x4 wb 2", 67455, 0x64c432e150eb59dfULL},
    {"split_cin lo 1 1x1x100x30 blk 16x4 wb 2", 67455, 0x64c432e150eb59dfULL},
    {"split_cin lo 2 1x1x100x30 blk 16x4 wb 2", 67511, 0x9ce640bc149d1d8fULL},
    {"split_cin lo 3 1x1x100x30 blk 16x4 wb 2", 67567, 0xa0f97d9c9da5a7e3ULL},
    {"split_cin lo 8 1x1x100x30 blk 16x4 wb 2", 67511, 0xedaf1eb6c14df88fULL},
    {"khkw_split 1x1x100x30 blk 16x4 wb 2", 67455, 0x2b00ff2898ac249fULL},
    {"block_pack 1x1x100x30 blk 5x3 wb 1", 72446, 0x2b64bb435a913bb1ULL},
    {"split_cin lo 1 1x1x100x30 blk 5x3 wb 1", 72446, 0x2b64bb435a913bb1ULL},
    {"split_cin lo 2 1x1x100x30 blk 5x3 wb 1", 72446, 0xc8fd8ed313d1eed1ULL},
    {"split_cin lo 3 1x1x100x30 blk 5x3 wb 1", 72518, 0xd9dcbf03ef1acfacULL},
    {"split_cin lo 8 1x1x100x30 blk 5x3 wb 1", 72734, 0x82d6deec95a042d5ULL},
    {"khkw_split 1x1x100x30 blk 5x3 wb 1", 72446, 0xbb7b73fc4b94da91ULL},
    {"block_pack 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"split_cin lo 1 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"split_cin lo 2 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"split_cin lo 3 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"split_cin lo 8 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"khkw_split 1x1x100x30 blk 64x64 wb 1", 61924, 0x064053c206067504ULL},
    {"block_pack 2x3x17x9 blk 1x1 wb 1", 41497, 0xc8810d9fae2dc4fbULL},
    {"split_cin lo 1 2x3x17x9 blk 1x1 wb 1", 41497, 0xc8810d9fae2dc4fbULL},
    {"split_cin lo 2 2x3x17x9 blk 1x1 wb 1", 41921, 0xfb9c0793a7757f9cULL},
    {"split_cin lo 3 2x3x17x9 blk 1x1 wb 1", 41921, 0x16116aaf4311813aULL},
    {"split_cin lo 8 2x3x17x9 blk 1x1 wb 1", 44465, 0x522d5d763aa3b701ULL},
    {"khkw_split 2x3x17x9 blk 1x1 wb 1", 41497, 0x849b1088a9d0f384ULL},
    {"block_pack 2x3x17x9 blk 4x4 wb 1", 30523, 0xe5e67626552bcc5eULL},
    {"split_cin lo 1 2x3x17x9 blk 4x4 wb 1", 30523, 0xe5e67626552bcc5eULL},
    {"split_cin lo 2 2x3x17x9 blk 4x4 wb 1", 30659, 0x434b68be063e37c1ULL},
    {"split_cin lo 3 2x3x17x9 blk 4x4 wb 1", 30659, 0x032f1f8d19da20f1ULL},
    {"split_cin lo 8 2x3x17x9 blk 4x4 wb 1", 30931, 0xc68264460983aefeULL},
    {"khkw_split 2x3x17x9 blk 4x4 wb 1", 30523, 0xc204a77e6eac388cULL},
    {"block_pack 2x3x17x9 blk 16x4 wb 2", 29066, 0x8a0467bf16b4c570ULL},
    {"split_cin lo 1 2x3x17x9 blk 16x4 wb 2", 29066, 0x8a0467bf16b4c570ULL},
    {"split_cin lo 2 2x3x17x9 blk 16x4 wb 2", 29066, 0x727e2c318209790cULL},
    {"split_cin lo 3 2x3x17x9 blk 16x4 wb 2", 29202, 0x4cb2a902f592ebb2ULL},
    {"split_cin lo 8 2x3x17x9 blk 16x4 wb 2", 29882, 0xd5487642f3538d58ULL},
    {"khkw_split 2x3x17x9 blk 16x4 wb 2", 29066, 0x7fd7933c3bc8e902ULL},
    {"block_pack 2x3x17x9 blk 5x3 wb 1", 30619, 0x2fb0e0fdf2694b6dULL},
    {"split_cin lo 1 2x3x17x9 blk 5x3 wb 1", 30619, 0x2fb0e0fdf2694b6dULL},
    {"split_cin lo 2 2x3x17x9 blk 5x3 wb 1", 30619, 0xa7032d36bc375968ULL},
    {"split_cin lo 3 2x3x17x9 blk 5x3 wb 1", 30891, 0x69f2cb0e40761545ULL},
    {"split_cin lo 8 2x3x17x9 blk 5x3 wb 1", 31163, 0xc39f07f83df4cd02ULL},
    {"khkw_split 2x3x17x9 blk 5x3 wb 1", 30619, 0x22c7d8e02026c295ULL},
    {"block_pack 2x3x17x9 blk 64x64 wb 1", 27591, 0x73af91628951f3ebULL},
    {"split_cin lo 1 2x3x17x9 blk 64x64 wb 1", 27591, 0x73af91628951f3ebULL},
    {"split_cin lo 2 2x3x17x9 blk 64x64 wb 1", 27631, 0xd6b246cbce33a66cULL},
    {"split_cin lo 3 2x3x17x9 blk 64x64 wb 1", 27671, 0xf7aeb7b8cfd8133dULL},
    {"split_cin lo 8 2x3x17x9 blk 64x64 wb 1", 27871, 0xb3abe639e0f18f30ULL},
    {"khkw_split 2x3x17x9 blk 64x64 wb 1", 27591, 0x73af91628951f3ebULL},
    {"block_pack 5x5x8x12 blk 1x1 wb 1", 108786, 0x0faf817a1909ada1ULL},
    {"split_cin lo 1 5x5x8x12 blk 1x1 wb 1", 108786, 0x0faf817a1909ada1ULL},
    {"split_cin lo 2 5x5x8x12 blk 1x1 wb 1", 108786, 0xe17c09f24e0d2206ULL},
    {"split_cin lo 3 5x5x8x12 blk 1x1 wb 1", 111178, 0xd6e5174fb77fd94dULL},
    {"split_cin lo 8 5x5x8x12 blk 1x1 wb 1", 108786, 0x8704f08d2a636182ULL},
    {"khkw_split 5x5x8x12 blk 1x1 wb 1", 114106, 0x241e10537c206828ULL},
    {"block_pack 5x5x8x12 blk 4x4 wb 1", 78186, 0x046567b86efe5376ULL},
    {"split_cin lo 1 5x5x8x12 blk 4x4 wb 1", 78186, 0x046567b86efe5376ULL},
    {"split_cin lo 2 5x5x8x12 blk 4x4 wb 1", 78186, 0xee7d08cb0a5058b6ULL},
    {"split_cin lo 3 5x5x8x12 blk 4x4 wb 1", 78778, 0xaf99675522b8a6e0ULL},
    {"split_cin lo 8 5x5x8x12 blk 4x4 wb 1", 81738, 0xc0a0bd5e1f78a308ULL},
    {"khkw_split 5x5x8x12 blk 4x4 wb 1", 78466, 0x09e4278ca5fa3272ULL},
    {"block_pack 5x5x8x12 blk 16x4 wb 2", 75487, 0xc5b59c2916af5a9cULL},
    {"split_cin lo 1 5x5x8x12 blk 16x4 wb 2", 75487, 0xc5b59c2916af5a9cULL},
    {"split_cin lo 2 5x5x8x12 blk 16x4 wb 2", 76079, 0x7bba550411fb1914ULL},
    {"split_cin lo 3 5x5x8x12 blk 16x4 wb 2", 76671, 0xa22f65acdd947a2cULL},
    {"split_cin lo 8 5x5x8x12 blk 16x4 wb 2", 79631, 0x64a72b9b0cf4529bULL},
    {"khkw_split 5x5x8x12 blk 16x4 wb 2", 75599, 0x9d65dbdaea561beaULL},
    {"block_pack 5x5x8x12 blk 5x3 wb 1", 79886, 0xf733c45ea1cfa3d5ULL},
    {"split_cin lo 1 5x5x8x12 blk 5x3 wb 1", 79886, 0xf733c45ea1cfa3d5ULL},
    {"split_cin lo 2 5x5x8x12 blk 5x3 wb 1", 79886, 0x76ab9c6653f908d0ULL},
    {"split_cin lo 3 5x5x8x12 blk 5x3 wb 1", 80678, 0xbc57ed5193abf629ULL},
    {"split_cin lo 8 5x5x8x12 blk 5x3 wb 1", 84638, 0xaaa6d43e17f170d3ULL},
    {"khkw_split 5x5x8x12 blk 5x3 wb 1", 80278, 0x8023106f55a70c64ULL},
    {"block_pack 5x5x8x12 blk 64x64 wb 1", 72488, 0x5610ed1c7c3cc5d4ULL},
    {"split_cin lo 1 5x5x8x12 blk 64x64 wb 1", 72488, 0x5610ed1c7c3cc5d4ULL},
    {"split_cin lo 2 5x5x8x12 blk 64x64 wb 1", 72680, 0x11542b6fe2084a81ULL},
    {"split_cin lo 3 5x5x8x12 blk 64x64 wb 1", 72872, 0x105bd31458783d7fULL},
    {"split_cin lo 8 5x5x8x12 blk 64x64 wb 1", 73832, 0x5eec92ef6caa239cULL},
    {"khkw_split 5x5x8x12 blk 64x64 wb 1", 72488, 0x5610ed1c7c3cc5d4ULL},
    {"block_pack 3x1x40x6 blk 1x1 wb 1", 31282, 0x6013b989faf51321ULL},
    {"split_cin lo 1 3x1x40x6 blk 1x1 wb 1", 31282, 0x6013b989faf51321ULL},
    {"split_cin lo 2 3x1x40x6 blk 1x1 wb 1", 31282, 0x7a3bcd5d95878fc7ULL},
    {"split_cin lo 3 3x1x40x6 blk 1x1 wb 1", 31554, 0x5db1f612468c8b61ULL},
    {"split_cin lo 8 3x1x40x6 blk 1x1 wb 1", 31282, 0x77e3a7831204d5fbULL},
    {"khkw_split 3x1x40x6 blk 1x1 wb 1", 31282, 0x9557e3235ae754f6ULL},
    {"block_pack 3x1x40x6 blk 4x4 wb 1", 22564, 0xc1a939d6fd15482cULL},
    {"split_cin lo 1 3x1x40x6 blk 4x4 wb 1", 22564, 0xc1a939d6fd15482cULL},
    {"split_cin lo 2 3x1x40x6 blk 4x4 wb 1", 22564, 0xb58d469ca0aa1e2cULL},
    {"split_cin lo 3 3x1x40x6 blk 4x4 wb 1", 22644, 0x4b511478125b66d4ULL},
    {"split_cin lo 8 3x1x40x6 blk 4x4 wb 1", 22804, 0xbae5c4bd2aa457faULL},
    {"khkw_split 3x1x40x6 blk 4x4 wb 1", 22564, 0x6d10b42bec7886bcULL},
    {"block_pack 3x1x40x6 blk 16x4 wb 2", 21455, 0x4a5ff8698bf978b5ULL},
    {"split_cin lo 1 3x1x40x6 blk 16x4 wb 2", 21455, 0x4a5ff8698bf978b5ULL},
    {"split_cin lo 2 3x1x40x6 blk 16x4 wb 2", 21495, 0xb3261a1488e5fb70ULL},
    {"split_cin lo 3 3x1x40x6 blk 16x4 wb 2", 21455, 0xc2a600d9a2bcf715ULL},
    {"split_cin lo 8 3x1x40x6 blk 16x4 wb 2", 21655, 0x01396deb47ce2d65ULL},
    {"khkw_split 3x1x40x6 blk 16x4 wb 2", 21455, 0x9c6d20d193f2b2d5ULL},
    {"block_pack 3x1x40x6 blk 5x3 wb 1", 22594, 0xb51eff7dd464e789ULL},
    {"split_cin lo 1 3x1x40x6 blk 5x3 wb 1", 22594, 0xb51eff7dd464e789ULL},
    {"split_cin lo 2 3x1x40x6 blk 5x3 wb 1", 22594, 0x44087a5edc2ad4a9ULL},
    {"split_cin lo 3 3x1x40x6 blk 5x3 wb 1", 22634, 0x936c11a8c770e371ULL},
    {"split_cin lo 8 3x1x40x6 blk 5x3 wb 1", 22594, 0xa711953193880d49ULL},
    {"khkw_split 3x1x40x6 blk 5x3 wb 1", 22594, 0xe129676fe1a70f29ULL},
    {"block_pack 3x1x40x6 blk 64x64 wb 1", 20400, 0xc9951ef0e64ecea5ULL},
    {"split_cin lo 1 3x1x40x6 blk 64x64 wb 1", 20400, 0xc9951ef0e64ecea5ULL},
    {"split_cin lo 2 3x1x40x6 blk 64x64 wb 1", 20416, 0x122df2e3fa200425ULL},
    {"split_cin lo 3 3x1x40x6 blk 64x64 wb 1", 20432, 0x177ce67d396394a5ULL},
    {"split_cin lo 8 3x1x40x6 blk 64x64 wb 1", 20512, 0xd7421568939c8573ULL},
    {"khkw_split 3x1x40x6 blk 64x64 wb 1", 20400, 0xc9951ef0e64ecea5ULL},
    {"errors block_pack", 2961, 0x245dc646209bd126ULL},
    {"errors split_cin lo 3", 2918, 0xc9ed116694dea63eULL},
    {"errors split_cin lo 0", 863, 0xe420b6a1cfaa27f2ULL},
    {"errors split_cin lo -2", 867, 0xb10296d96d6829b2ULL},
    {"errors khkw_split", 2979, 0xa369007e4466e07bULL},
};
const std::size_t kGoldenSize = sizeof(kGolden) / sizeof(kGolden[0]);

}  // namespace

int main(int argc, char** argv) {
    const std::vector<Case> cases = run_grid();

    if (argc > 1 && std::strcmp(argv[1], "--print-golden") == 0) {
        for (const Case& c : cases) {
            std::printf("    {\"%s\", %" PRId64 ", 0x%016" PRIx64 "ULL},\n", c.name.c_str(),
                        c.values, c.hash);
        }
        return 0;
    }

    std::printf("test_layout_golden\n");
    CHECK_EQ(static_cast<std::int64_t>(cases.size()), static_cast<std::int64_t>(kGoldenSize));
    std::int64_t total = 0;
    for (std::size_t i = 0; i < cases.size() && i < kGoldenSize; ++i) {
        const Case& c = cases[i];
        const Golden& g = kGolden[i];
        CHECK_TRUE(c.name == g.name);
        CHECK_EQ(c.values, g.values);
        check::is_true(__FILE__, __LINE__, c.name.c_str(), c.hash == g.hash);
        total += c.values;
    }
    std::printf("  %zu cases, %" PRId64 " recorded values\n", cases.size(), total);
    return check::summary();
}
