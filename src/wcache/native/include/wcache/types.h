// Scalar types for the wcache event-driven model.
//
// Plan v2 unit A1, decision N12: SimTime, LocalTick, and RefusalOrder must be
// mutually uncomparable, so that no expression can silently mix simulated
// time, trace-local time, and an arbitration counter. They are three different
// quantities that all happen to be int64.
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <stdexcept>

namespace wcache {

// A distinct type over Rep. Tag is only ever an incomplete struct: it names
// the quantity and is never instantiated.
//
// No default constructor. A defaulted SlotId would mean slot 0 and a defaulted
// SimTime would mean the start of the run, both of which are valid values that
// a forgotten initialiser would produce silently. Containers spell the fill
// value out instead: std::vector<SlotId>(n, NoSlot).
template <typename Rep, typename Tag>
class Tagged {
public:
    using rep_type = Rep;

    Tagged() = delete;
    constexpr explicit Tagged(Rep v) : v_(v) {}

    constexpr Rep get() const { return v_; }

private:
    Rep v_;
};

// Deduction requires both operands to be the same instantiation, which is what
// makes SimTime{1} == LocalTick{1} a compile error rather than true.
template <typename Rep, typename Tag>
constexpr bool operator==(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() == b.get(); }
template <typename Rep, typename Tag>
constexpr bool operator!=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() != b.get(); }
template <typename Rep, typename Tag>
constexpr bool operator<(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() < b.get(); }
template <typename Rep, typename Tag>
constexpr bool operator<=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() <= b.get(); }
template <typename Rep, typename Tag>
constexpr bool operator>(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() > b.get(); }
template <typename Rep, typename Tag>
constexpr bool operator>=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() >= b.get(); }

namespace tags {
struct line;
struct core;
struct slot;
struct sim_time;
struct local_tick;
struct refusal_order;
}  // namespace tags

// Every id below is signed, and that is a convention rather than a preference:
// the v1 tree's line_of bug was an unsigned flatten in an expression that mixed
// signedness. One signedness across the whole layout class removes the class of
// bug rather than the instance.

// A line address in the flat weight space, tag * num_sets + set_index (A2).
using LineId = Tagged<std::int64_t, tags::line>;

using CoreId = Tagged<std::int32_t, tags::core>;

// A dense, stable index over the slots of one array. It is the only handle
// that crosses between CacheArray and ReplacementPolicy (plan 2.2), so a
// policy indexes a flat vector with it and never computes a set index.
using SlotId = Tagged<std::int32_t, tags::slot>;

// Simulated time. The engine has no tick; `now` is the timestamp of the event
// being dispatched (P1).
using SimTime = Tagged<std::int64_t, tags::sim_time>;

// Trace time, and only ever an offset within one tile (Part 5). There is no
// absolute LocalTick, which is why no operation produces one from a SimTime.
using LocalTick = Tagged<std::int64_t, tags::local_tick>;

// Arbitration order, 3.8: the value of a global counter at a request's first
// refusal, not a tick. 64-bit because a run's total refusals can exceed 32 bits
// at 1024 cores (plan Part 9 Q8).
using RefusalOrder = Tagged<std::int64_t, tags::refusal_order>;

// Sentinels. Both sit at the top of their range so that ordinary `<` puts them
// last, which is what makes the comparisons below single-valued.
inline constexpr SlotId NoSlot{INT32_MAX};

// 3.8's key is (r.refusal == NONE, r.refusal): refused beats fresh, FIFO within
// refused. With NONE at the top of the range, plain `a.refusal < b.refusal`
// computes that whole key, so the refused bit is not carried as a second field.
inline constexpr RefusalOrder NoRefusal{INT64_MAX};

// Simulated durations are SimTime values, so a latency added to an accept time
// is the same quantity as the time it advances.
constexpr SimTime operator+(SimTime a, SimTime b) { return SimTime{a.get() + b.get()}; }
constexpr SimTime operator-(SimTime a, SimTime b) { return SimTime{a.get() - b.get()}; }
constexpr SimTime& operator+=(SimTime& a, SimTime b) { a = a + b; return a; }

// The one permitted crossing between trace time and simulated time, and the
// only expression in Part 5 that needs it:
//     issue_time(c) = tile_origin[tile(c)] + local_tick(c, cursor)
// N12 asks that the time-like types be uncomparable, which this does not
// weaken: there is still no way to compare a LocalTick with a SimTime, and no
// operation yields a LocalTick from a SimTime.
constexpr SimTime operator+(SimTime origin, LocalTick offset) {
    return SimTime{origin.get() + offset.get()};
}

constexpr LocalTick operator+(LocalTick a, LocalTick b) { return LocalTick{a.get() + b.get()}; }
constexpr LocalTick operator-(LocalTick a, LocalTick b) { return LocalTick{a.get() - b.get()}; }

// ---------------------------------------------------------------------------
// Tensor geometry (A1b)
//
// Plain int32 coordinates rather than six more tagged types. The four axes are
// addressed generically through `Axis`, so coord_on and extent must return one
// type; tagging them per axis would make exactly the code that needs to be
// generic impossible to write.
// ---------------------------------------------------------------------------

// The weight tensor's logical shape is [KH][KW][CIN][COUT]. Declaration order
// is the row-major nesting order, outermost first, and AddressMapper (A2)
// depends on that.
enum class Axis : std::uint8_t { KH = 0, KW = 1, CIN = 2, COUT = 3 };

// One element of the weight tensor.
struct Coord {
    std::int32_t kh;
    std::int32_t kw;
    std::int32_t cin;
    std::int32_t cout;
};

// A run of weight elements fetched together, in the canonical form every
// module uses. The trace's on-disk 5-tuple is a different shape: today it is
// [kh, kw, cin, cout_start, cout_end], which TraceReader (A3) decodes into
// {anchor = {kh, kw, cin, cout_start}, axis = COUT,
//  count = cout_end - cout_start, stride = 1}.
// Format v2 carries burst_dim and burst_stride as header fields so a future
// architecture can burst along CIN instead, so `axis` and `stride` are read
// from the header and never assumed.
//
// This is plan D9's unit of issue: one trace event is a burst, not a line, and
// under a layout narrower than the burst it expands to several lines.
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
};

// The extent of `shape` along `a`.
constexpr std::int32_t extent_on(const WeightShape& shape, Axis a) {
    switch (a) {
        case Axis::KH:   return shape.KH;
        case Axis::KW:   return shape.KW;
        case Axis::CIN:  return shape.CIN;
        case Axis::COUT: return shape.COUT;
    }
    // Unreachable: the switch covers every enumerator. Returning 0 instead
    // would turn A2's bound check into a check against an empty tensor, which
    // rejects everything rather than failing where the fault is.
    throw std::logic_error("extent_on: unknown Axis");
}

// The coordinate of `c` along `a`.
constexpr std::int32_t coord_on(const Coord& c, Axis a) {
    switch (a) {
        case Axis::KH:   return c.kh;
        case Axis::KW:   return c.kw;
        case Axis::CIN:  return c.cin;
        case Axis::COUT: return c.cout;
    }
    // Unreachable, and the worst of the four to paper over: A2's expand reads
    // the anchor through this function, so a fallback of 0 would silently walk
    // the burst from coordinate 0 and emit valid-looking line ids.
    throw std::logic_error("coord_on: unknown Axis");
}

// `c` with its coordinate along `a` replaced. A2's expand walks a burst by
// stepping one axis, which needs a write as well as coord_on's read.
constexpr Coord with_coord_on(Coord c, Axis a, std::int32_t v) {
    switch (a) {
        case Axis::KH:   c.kh   = v; return c;
        case Axis::KW:   c.kw   = v; return c;
        case Axis::CIN:  c.cin  = v; return c;
        case Axis::COUT: c.cout = v; return c;
    }
    throw std::logic_error("with_coord_on: unknown Axis");
}

// For the messages N11 requires when a coordinate leaves workload_dims.
constexpr const char* axis_name(Axis a) {
    switch (a) {
        case Axis::KH:   return "KH";
        case Axis::KW:   return "KW";
        case Axis::CIN:  return "CIN";
        case Axis::COUT: return "COUT";
    }
    throw std::logic_error("axis_name: unknown Axis");
}

}  // namespace wcache

// LineId keys the MSHR file's `line -> Mshr` map (plan 3.3).
namespace std {
template <typename Rep, typename Tag>
struct hash<wcache::Tagged<Rep, Tag>> {
    size_t operator()(wcache::Tagged<Rep, Tag> v) const noexcept {
        return hash<Rep>{}(v.get());
    }
};
}  // namespace std
