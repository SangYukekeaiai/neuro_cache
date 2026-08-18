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
#include <type_traits>
#include <utility>

namespace wcache {

namespace detail {

// True when `To x{v}` is well formed for a v of type From, false when that
// initialisation would narrow.
//
// The whole test is the braced initialisation inside decltype. List
// initialisation is the one context the language already forbids a narrowing
// conversion in, so this asks the compiler its own question instead of
// enumerating widths and signednesses by hand and getting one of them wrong.
//
// std::declval<From>() names a value of type From without constructing one,
// and its not being a constant expression is load-bearing rather than
// incidental: a constant that happens to fit is a permitted narrowing
// (`std::int32_t x{5L}` is legal C++), and that exception must not leak into a
// rule that is about types. A run-time int64 and a literal 5L would otherwise
// answer differently.
template <typename To, typename From, typename = void>
struct converts_without_narrowing : std::false_type {};

template <typename To, typename From>
struct converts_without_narrowing<To, From, std::void_t<decltype(To{std::declval<From>()})>>
    : std::true_type {};

}  // namespace detail

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

    // One constructor, and a constrained template rather than the obvious
    // `Tagged(Rep)`, which is decision B29 (U2) made mechanical.
    //
    // With a plain `Rep` parameter, `SlotId s{p.tag}` on an int64 converts in
    // the argument, and g++ reports that as a -Wnarrowing warning and compiles
    // it anyway; compile_fail.sh runs without -Werror, so a 64-bit value was
    // diagnosed and then truncated to 32 bits regardless. Constraining the
    // template removes the overload rather than converting, so a narrowing
    // source leaves the line with no constructor to call and it fails under
    // every flag combination. `explicit` still handles the other half, the
    // conversion nobody asked for at all.
    //
    // The plain constructor is gone rather than kept beside this one: an
    // unconstrained `Tagged(Rep)` is exactly the overload the narrowing
    // argument would bind to, so keeping it would leave the gap open.
    //
    // `v_{v}` is the same test written a second time and is NOT a second line
    // of defence: the constraint is solely load-bearing. Measured, because the
    // obvious reading is wrong. Remove the constraint and keep the braces, and
    // `SlotId s{p.tag}` still compiles, carrying `-Wnarrowing` and
    // `-Wconversion` and nothing else; keep the constraint and parenthesise to
    // `v_(v)`, and that line is still rejected. The braces are defeated by
    // exactly the permissiveness this mechanism exists to route around, which
    // is why reaching for them as the fix does not work. They are kept for
    // stating the rule where the value lands, not for enforcing it.
    template <typename U,
              typename = std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>>
    constexpr explicit Tagged(U v) : v_{v} {}

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
struct set_index;
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

// Which set of a set-associative array a line competes in: the first half of
// AddressMapper::locate's answer, in [0, num_sets). The seventh tagged type,
// and the one A1a's carried obligation asked A4 for.
//
// It exists because a set index and a slot id are both plain integers that a
// set-associative array holds at the same time, one line apart, so
// `policy.on_hit(SlotId{set_index})` is a spelling the code invites. The
// non-narrowing constructor above stops that particular pair on width alone
// (a set index is int64, a SlotId int32), but only by accident of the two
// widths: a set index reaching a LineId, or reaching a future 64-bit slot
// handle, would not narrow and would compile. Naming the quantity is what
// makes the refusal about meaning rather than about size.
//
// int64, matching Placement::set_index and locate's num_sets argument, so no
// conversion sits between locate's answer and this type.
using SetIndex = Tagged<std::int64_t, tags::set_index>;

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

// What a slot holding nothing reports, so that "free" and "holds a line" are
// one comparison in the array's way scan rather than a second valid bit per
// slot. A real LineId is in [0, num_lines()) and num_lines() is itself an
// int64 the layout's overflow guard bounds at INT64_MAX, so INT64_MAX is one
// past every id any mapper can produce and cannot collide with a resident
// line.
inline constexpr LineId NoLine{INT64_MAX};

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
