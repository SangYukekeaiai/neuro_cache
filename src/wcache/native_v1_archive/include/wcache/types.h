// Core scalar types shared by every wcache module.
// Design: log/2026-08-05-cachesim-redesign-plan.md
#pragma once

#include <cstdint>
#include <stdexcept>

namespace wcache {

// Signed on purpose. A LineId is a dense index into [0, num_lines), and it is
// mixed in arithmetic with Coord, block counts and set counts, all of which
// are signed. When the two signednesses meet, the signed operand converts to
// unsigned, so every comparison against zero downstream becomes vacuous and
// -Wsign-conversion has to be answered with a cast at each crossing. That is
// not hypothetical here: it is how line_of came to flatten in unsigned and
// silently return `base - 1` for a negative cout under -DNDEBUG. The unsigned
// range is dead weight besides: the largest tensor in the sweep needs about
// 2^36 lines against int64_t's 2^63. A future hashed or XOR-folded set index
// wants unsigned bit operations, and can cast at that one site.
//
// What signedness does NOT buy, since an earlier version of this comment
// claimed it did: it does not make an out-of-range coordinate visibly
// negative. Integer division truncates toward zero, so any cin in
// [-(cin_block-1), -1] lands on block 0 and produces a perfectly ordinary
// line id. Only an explicit range check catches that, which is why
// line_of validates all four coordinates with a throw rather than an assert.
// Signedness buys the check the ability to work at all, not the check itself.
using LineId = std::int64_t;   // index of a cache line in the weight tensor
using CoreId = std::uint32_t;  // trace core_id, decoded via spatial_factors
// Signed: the engine subtracts ticks (stall time, and
// max(tick_base + tick, core_ready_time)). An unsigned subtraction that goes
// negative wraps to a huge plausible value rather than a visibly wrong one,
// the same failure the signed LineId avoids.
using Tick   = std::int64_t;   // global time, tick_base + tile-local tick

// The four axes of the weight tensor, logical shape [KH][KW][CIN][COUT].
// Declaration order is the row-major nesting order, outermost first, and
// AddressMapper relies on that.
enum class Axis : std::uint8_t { KH = 0, KW = 1, CIN = 2, COUT = 3 };

// One element of the weight tensor.
struct Coord {
    std::int32_t kh;
    std::int32_t kw;
    std::int32_t cin;
    std::int32_t cout;
};

// A run of weight elements fetched together, in the canonical form every
// wcache module uses. The trace's on-disk 5-tuple is NOT this shape: today
// it is [kh, kw, cin, cout_start, cout_end], which TraceReader decodes into
// {anchor={kh,kw,cin,cout_start}, axis=COUT, count=cout_end-cout_start,
// stride=1}. Format v2 carries burst_dim and burst_stride as header fields
// precisely so a future arch can burst along CIN instead, so `axis` and
// `stride` are read from the header, never assumed.
struct Burst {
    Coord        anchor;  // the run's first element
    Axis         axis;    // which axis the run walks (header burst_dim)
    std::int32_t count;   // number of elements in the run
    std::int32_t stride;  // step along `axis` between elements (burst_stride)
};

// Extents of the layer's weight tensor, from the trace's workload_dims.
struct WeightShape {
    std::int32_t KH;
    std::int32_t KW;
    std::int32_t CIN;
    std::int32_t COUT;

    std::int32_t extent(Axis a) const {
        switch (a) {
            case Axis::KH:   return KH;
            case Axis::KW:   return KW;
            case Axis::CIN:  return CIN;
            case Axis::COUT: return COUT;
        }
        // Unreachable: the switch covers every Axis enumerator. A fallback
        // extent of 0 would silently turn the bound check in expand into a
        // check against an empty tensor, so this path fails loudly instead.
        throw std::logic_error("WeightShape::extent: unknown Axis");
    }
};

// The coordinate of `c` on axis `a`.
inline std::int32_t coord_on(const Coord& c, Axis a) {
    switch (a) {
        case Axis::KH:   return c.kh;
        case Axis::KW:   return c.kw;
        case Axis::CIN:  return c.cin;
        case Axis::COUT: return c.cout;
    }
    // Unreachable: the switch covers every Axis enumerator. A fallback of 0
    // would be the worst of the four, because expand reads the anchor's
    // coordinate through this function: a bad Axis would silently expand the
    // burst from coordinate 0 and emit a valid-looking line. Fail loudly.
    throw std::logic_error("coord_on: unknown Axis");
}

}  // namespace wcache
