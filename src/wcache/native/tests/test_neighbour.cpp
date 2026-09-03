// AddressMapper::neighbour, on all three mappers.
//
// The check is against `line_of` rather than against a recomputed stride: the
// neighbour of a line must be the line of the neighbouring COORDINATE, and
// stating it that way is what makes the test independent of the arithmetic it
// is testing. Exhaustive over a small shape, so there is no sampling to argue
// about, plus the two edges and the two refusals every mapper owes.
#include <optional>
#include <stdexcept>
#include <string>

#include "check.h"
#include "wcache/block_pack.h"
#include "wcache/khkw_split.h"
#include "wcache/layout.h"
#include "wcache/split_cin.h"
#include "wcache/types.h"

namespace {

using namespace wcache;

// Small enough to enumerate completely, and still 3x3 so the kernel position
// splits the way the campaign's layers do.
const WeightShape kSmall{3, 3, 64, 32};
constexpr std::int32_t kCinBlock = 16, kCoutBlock = 4, kBytes = 1;

std::int32_t block_of(const Coord& c, Axis a) {
    switch (a) {
        case Axis::KH:   return c.kh;
        case Axis::KW:   return c.kw;
        case Axis::CIN:  return c.cin / kCinBlock;
        case Axis::COUT: return c.cout / kCoutBlock;
    }
    throw std::logic_error("block_of");
}

Coord stepped(const Coord& c, Axis a, std::int32_t d) {
    Coord n = c;
    switch (a) {
        case Axis::KH:   n.kh   += d;              break;
        case Axis::KW:   n.kw   += d;              break;
        case Axis::CIN:  n.cin  += d * kCinBlock;  break;
        case Axis::COUT: n.cout += d * kCoutBlock; break;
    }
    return n;
}

bool in_shape(const Coord& c) {
    return c.kh >= 0 && c.kh < kSmall.KH && c.kw >= 0 && c.kw < kSmall.KW &&
           c.cin >= 0 && c.cin < kSmall.CIN && c.cout >= 0 && c.cout < kSmall.COUT;
}

// One mapper, every coordinate, every axis, both directions.
template <typename M>
void exhaustive(const char* name, const M& m) {
    long checked = 0, edges = 0;
    for (std::int32_t kh = 0; kh < kSmall.KH; ++kh)
    for (std::int32_t kw = 0; kw < kSmall.KW; ++kw)
    for (std::int32_t ci = 0; ci < kSmall.CIN; ci += kCinBlock)
    for (std::int32_t co = 0; co < kSmall.COUT; co += kCoutBlock) {
        const Coord c{kh, kw, ci, co};
        const LineId line = m.line_of(c);
        for (Axis a : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT}) {
            for (std::int32_t d : {-1, 1, -2, 2}) {
                const Coord n = stepped(c, a, d);
                const std::optional<LineId> got = m.neighbour(line, a, d);
                if (in_shape(n)) {
                    CHECK_TRUE(got.has_value());
                    CHECK_TRUE(got->get() == m.line_of(n).get());
                    // and the block index really moved by d
                    CHECK_TRUE(block_of(n, a) == block_of(c, a) + d);
                } else {
                    CHECK_TRUE(!got.has_value());
                    ++edges;
                }
                ++checked;
            }
        }
    }
    CHECK_TRUE(edges > 0);
    std::printf("  %-16s %ld checks, %ld of them at an edge\n", name, checked, edges);
}

// Both refusals the interface documents.
template <typename M>
void refusals(const char* name, const M& m) {
    (void)name;
    CHECK_THROWS(std::out_of_range, m.neighbour(LineId{m.num_lines().get()}, Axis::CIN, 1));
    CHECK_THROWS(std::out_of_range, m.neighbour(LineId{-1}, Axis::CIN, 1));
}

// delta 0 is the identity, on every mapper and every axis.
template <typename M>
void identity(const char* name, const M& m) {
    const LineId line = m.line_of(Coord{1, 1, 32, 8});
    for (Axis a : {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT}) {
        const std::optional<LineId> got = m.neighbour(line, a, 0);
        CHECK_TRUE(got.has_value() && got->get() == line.get());
    }
}

}  // namespace

int main() {
    const KhkwSplitMapper khkw(kSmall, kCinBlock, kCoutBlock, kBytes);
    const BlockPackMapper bp(kSmall, kCinBlock, kCoutBlock, kBytes);
    const SplitCinMapper  sc(kSmall, kCinBlock, kCoutBlock, kBytes, 2);

    std::printf("test_neighbour\n");
    exhaustive("khkw_split", khkw);
    exhaustive("block_pack", bp);
    exhaustive("split_cin", sc);
    refusals("khkw_split", khkw);
    refusals("block_pack", bp);
    refusals("split_cin", sc);
    identity("khkw_split", khkw);
    identity("block_pack", bp);
    identity("split_cin", sc);

    // The one case that motivated putting this on the mapper: under split_cin a
    // cin step can carry between two digits, so it is NOT one stride.
    const LineId l = sc.line_of(Coord{1, 1, 16, 8});
    const std::optional<LineId> up = sc.neighbour(l, Axis::CIN, 1);
    CHECK_TRUE(up.has_value());
    // The carry is visible as a jump that is NOT one CIN_LO stride: with
    // n_cin_lo = 2 the block at cin 16 is cin_lo = 1, so +1 wraps to cin_hi + 1.
    CHECK_TRUE(up->get() - l.get() != 1);

    return check::summary();
}
