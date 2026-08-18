// Unit A1: Tagged and the six scalar types (A1a), then the tensor geometry
// (A1b).
//
// The negative half of A1's exit criterion ("any mix of the three time-like
// types fails to compile") cannot live here, because a test that must not
// compile cannot be in a file that must. It is tests/compile_fail.sh.
#include <wcache/types.h>

#include <cstdint>
#include <cstring>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

#include "check.h"

using namespace wcache;

namespace {

// --- construction and round trip -------------------------------------------

void test_round_trip() {
    check::group("round trip");

    CHECK_EQ(LineId{0}.get(), std::int64_t{0});
    CHECK_EQ(LineId{1}.get(), std::int64_t{1});
    CHECK_EQ(LineId{-1}.get(), std::int64_t{-1});
    CHECK_EQ(LineId{INT64_MAX}.get(), INT64_MAX);
    CHECK_EQ(LineId{INT64_MIN}.get(), INT64_MIN);

    CHECK_EQ(CoreId{0}.get(), std::int32_t{0});
    CHECK_EQ(CoreId{1023}.get(), std::int32_t{1023});
    CHECK_EQ(CoreId{INT32_MAX}.get(), INT32_MAX);

    CHECK_EQ(SlotId{0}.get(), std::int32_t{0});
    CHECK_EQ(SlotId{INT32_MAX}.get(), INT32_MAX);

    CHECK_EQ(SimTime{0}.get(), std::int64_t{0});
    CHECK_EQ(SimTime{-5}.get(), std::int64_t{-5});
    CHECK_EQ(LocalTick{0}.get(), std::int64_t{0});
    CHECK_EQ(RefusalOrder{0}.get(), std::int64_t{0});

    // Copying preserves the value; Tagged is trivially copyable.
    SimTime a{42};
    SimTime b = a;
    CHECK_EQ(b.get(), std::int64_t{42});
    b = SimTime{7};
    CHECK_EQ(b.get(), std::int64_t{7});
    CHECK_EQ(a.get(), std::int64_t{42});  // assignment to b did not touch a
}

// --- comparison -------------------------------------------------------------
//
// Every operator is checked at less, equal, and greater, on every type. The
// equal case is the one that matters: a `<=` written as `<` is right at less
// and at greater and wrong only at equal, and that is the exact mutation the
// hand-written alternative made easy to hide.

template <typename T>
void check_ordering(const char* what) {
    check::group(what);
    const T lo{4};
    const T mid{5};
    const T mid2{5};
    const T hi{6};

    CHECK_TRUE(mid == mid2);
    CHECK_TRUE(!(mid == hi));
    CHECK_TRUE(mid != hi);
    CHECK_TRUE(!(mid != mid2));

    CHECK_TRUE(lo < mid);
    CHECK_TRUE(!(mid < mid2));   // equal is not less
    CHECK_TRUE(!(hi < mid));

    CHECK_TRUE(lo <= mid);
    CHECK_TRUE(mid <= mid2);     // equal IS less-or-equal
    CHECK_TRUE(!(hi <= mid));

    CHECK_TRUE(hi > mid);
    CHECK_TRUE(!(mid > mid2));   // equal is not greater
    CHECK_TRUE(!(lo > mid));

    CHECK_TRUE(hi >= mid);
    CHECK_TRUE(mid >= mid2);     // equal IS greater-or-equal
    CHECK_TRUE(!(lo >= mid));
}

void test_ordering_negative_and_boundary() {
    check::group("ordering across zero and at the extremes");

    CHECK_TRUE(SimTime{-1} < SimTime{0});
    CHECK_TRUE(SimTime{-2} < SimTime{-1});
    CHECK_TRUE(LineId{INT64_MIN} < LineId{0});
    CHECK_TRUE(LineId{0} < LineId{INT64_MAX});
    CHECK_TRUE(LineId{INT64_MIN} < LineId{INT64_MAX});
    CHECK_TRUE(CoreId{-1} < CoreId{0});   // signed, so this is a real ordering
}

// --- sentinels and the 3.8 arbitration key ---------------------------------

void test_sentinels() {
    check::group("sentinels");

    CHECK_EQ(NoSlot.get(), INT32_MAX);
    CHECK_EQ(NoRefusal.get(), INT64_MAX);

    CHECK_TRUE(SlotId{0} != NoSlot);
    CHECK_TRUE(SlotId{INT32_MAX - 1} != NoSlot);
    CHECK_TRUE(SlotId{INT32_MAX} == NoSlot);

    // 3.8: key(r) = (r.refusal == NONE, r.refusal). With NONE at the top of
    // the range, a single `<` computes the whole key. Both clauses:
    const RefusalOrder older{5};
    const RefusalOrder newer{8};
    const RefusalOrder fresh = NoRefusal;

    CHECK_TRUE(older < newer);   // FIFO within refused
    CHECK_TRUE(older < fresh);   // refused beats fresh
    CHECK_TRUE(newer < fresh);   // refused beats fresh, whatever the stamp
    CHECK_TRUE(!(fresh < older));

    // The sentinel is the maximum, so nothing sorts after it.
    CHECK_TRUE(!(fresh < fresh));
    CHECK_TRUE(RefusalOrder{INT64_MAX - 1} < fresh);
}

// --- arithmetic -------------------------------------------------------------

void test_arithmetic() {
    check::group("arithmetic");

    CHECK_EQ((SimTime{5} + SimTime{3}).get(), std::int64_t{8});
    CHECK_EQ((SimTime{5} - SimTime{3}).get(), std::int64_t{2});
    CHECK_EQ((SimTime{3} - SimTime{5}).get(), std::int64_t{-2});  // signed, no wrap
    CHECK_EQ((SimTime{0} + SimTime{0}).get(), std::int64_t{0});

    SimTime acc{10};
    acc += SimTime{5};
    CHECK_EQ(acc.get(), std::int64_t{15});
    acc += SimTime{-15};
    CHECK_EQ(acc.get(), std::int64_t{0});

    CHECK_EQ((LocalTick{5} + LocalTick{3}).get(), std::int64_t{8});
    CHECK_EQ((LocalTick{5} - LocalTick{3}).get(), std::int64_t{2});

    // Part 5's one crossing: issue_time = tile_origin + local_tick.
    CHECK_EQ((SimTime{1200} + LocalTick{17}).get(), std::int64_t{1217});
    CHECK_EQ((SimTime{0} + LocalTick{0}).get(), std::int64_t{0});
    // The result is a SimTime, not a LocalTick. If it were not, this line
    // would not compile.
    const SimTime issue = SimTime{1200} + LocalTick{17};
    CHECK_TRUE(issue == SimTime{1217});

    // Part 5's stretch statistic is SimTime - SimTime, and goes negative when
    // a tile finishes ahead of its trace time.
    CHECK_EQ((SimTime{100} - SimTime{140}).get(), std::int64_t{-40});
}

// --- hashing ----------------------------------------------------------------

void test_hash() {
    check::group("hash");

    // Plan 3.3: MshrFile::entries is line -> Mshr.
    std::unordered_map<LineId, int> entries;
    entries.emplace(LineId{42}, 1);
    entries.emplace(LineId{7}, 2);
    entries.emplace(LineId{-3}, 3);
    CHECK_EQ(check::ssize(entries), std::int64_t{3});
    CHECK_EQ(entries.at(LineId{42}), 1);
    CHECK_EQ(entries.at(LineId{7}), 2);
    CHECK_EQ(entries.at(LineId{-3}), 3);
    CHECK_EQ(check::ssize(entries), std::int64_t{3});

    // Re-inserting the same key does not add an entry, which is I1's
    // "at most one live Mshr per line" resting on the map.
    entries.emplace(LineId{42}, 99);
    CHECK_EQ(check::ssize(entries), std::int64_t{3});
    CHECK_EQ(entries.at(LineId{42}), 1);

    CHECK_EQ(check::ssize(entries), std::int64_t{3});
    entries.erase(LineId{7});
    CHECK_EQ(check::ssize(entries), std::int64_t{2});

    // Equal keys must hash equal. (Unequal keys need not hash unequal, so
    // there is deliberately no check for that.)
    const std::hash<LineId> h;
    CHECK_TRUE(h(LineId{42}) == h(LineId{42}));
    CHECK_TRUE(h(LineId{0}) == h(LineId{0}));

    // The tag carries nothing at runtime, so a Tagged hashes as its payload.
    CHECK_TRUE(h(LineId{42}) == std::hash<std::int64_t>{}(42));
}

// --- containers -------------------------------------------------------------

void test_containers() {
    check::group("containers without a default constructor");

    // Decision B2: Tagged has no default constructor, so a vector must be
    // told what to fill with. This is the spelling A4 will use for ways.
    std::vector<SlotId> ways(4, NoSlot);
    CHECK_EQ(check::ssize(ways), std::int64_t{4});
    CHECK_TRUE(ways[0] == NoSlot);
    CHECK_TRUE(ways[3] == NoSlot);
    ways[2] = SlotId{1};
    CHECK_TRUE(ways[2] == SlotId{1});
    CHECK_TRUE(ways[1] == NoSlot);

    std::vector<SimTime> stamps;
    stamps.push_back(SimTime{3});
    stamps.push_back(SimTime{1});
    CHECK_EQ(check::ssize(stamps), std::int64_t{2});
    CHECK_TRUE(stamps[1] < stamps[0]);
}

// ===========================================================================
// Unit A1b: tensor geometry
// ===========================================================================

// Every axis, in declaration order, so a loop over the four is written once.
constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

void test_axis_order() {
    check::group("Axis: declaration order is the row-major nesting order");

    // A2 flattens as ((kh * KW + kw) * CIN + cin) * COUT + cout, and the
    // nesting there is exactly this order. Reordering the enumerators without
    // reordering that expression yields plausible, wrong line ids, and nothing
    // else in the suite would announce it. Pinned numerically, not by name.
    CHECK_EQ(static_cast<int>(Axis::KH), 0);
    CHECK_EQ(static_cast<int>(Axis::KW), 1);
    CHECK_EQ(static_cast<int>(Axis::CIN), 2);
    CHECK_EQ(static_cast<int>(Axis::COUT), 3);

    CHECK_TRUE(std::strcmp(axis_name(Axis::KH), "KH") == 0);
    CHECK_TRUE(std::strcmp(axis_name(Axis::KW), "KW") == 0);
    CHECK_TRUE(std::strcmp(axis_name(Axis::CIN), "CIN") == 0);
    CHECK_TRUE(std::strcmp(axis_name(Axis::COUT), "COUT") == 0);
}

void test_accessors() {
    check::group("extent_on / coord_on: each axis reads its own field");

    // Four distinct values per struct, so an accessor returning a neighbour is
    // wrong at every axis rather than at three of the four.
    const WeightShape shape{3, 5, 256, 512};
    const Coord       c{1, 2, 64, 100};

    CHECK_EQ(extent_on(shape, Axis::KH), 3);
    CHECK_EQ(extent_on(shape, Axis::KW), 5);
    CHECK_EQ(extent_on(shape, Axis::CIN), 256);
    CHECK_EQ(extent_on(shape, Axis::COUT), 512);

    CHECK_EQ(coord_on(c, Axis::KH), 1);
    CHECK_EQ(coord_on(c, Axis::KW), 2);
    CHECK_EQ(coord_on(c, Axis::CIN), 64);
    CHECK_EQ(coord_on(c, Axis::COUT), 100);

    // Zero is a legal coordinate and a legal extent, and is the value a
    // silent fallback would return, so it is checked explicitly rather than
    // left to the distinct-value cases above.
    const Coord origin{0, 0, 0, 0};
    for (Axis a : kAxes) CHECK_EQ(coord_on(origin, a), 0);
}

void test_with_coord_on() {
    check::group("with_coord_on: writes one axis, copies the rest");

    const Coord anchor{1, 0, 64, 12};

    const Coord third = with_coord_on(anchor, Axis::COUT, 14);
    CHECK_EQ(third.kh, 1);
    CHECK_EQ(third.kw, 0);
    CHECK_EQ(third.cin, 64);
    CHECK_EQ(third.cout, 14);

    // The argument is taken by value, so the caller's anchor is untouched.
    // A2's expand keeps one anchor and derives every element from it, so an
    // accessor that mutated in place would corrupt the walk after step one.
    CHECK_EQ(anchor.cout, 12);

    // The whole cross product: writing axis `w` changes `w` and nothing else.
    // This is what catches a case label that writes a neighbouring field, the
    // mutation a single-axis test at COUT would let through.
    for (Axis w : kAxes) {
        const Coord out = with_coord_on(anchor, w, 77);
        for (Axis r : kAxes) {
            const std::int32_t expect = (r == w) ? 77 : coord_on(anchor, r);
            CHECK_EQ(coord_on(out, r), expect);
        }
    }
}

void test_unknown_axis_throws() {
    check::group("an Axis outside the enumerators refuses to answer");

    // Well-defined rather than undefined: Axis fixes its underlying type to
    // uint8_t, so 9 is a representable value of the type. That is what makes
    // this test legal to write, and it is why the underlying type is pinned.
    const Axis bad = static_cast<Axis>(9);
    const WeightShape shape{3, 3, 8, 8};
    const Coord       c{0, 0, 0, 0};

    // A fallback return of 0 would be the tempting alternative and is the
    // worst one: A2 reads the anchor through coord_on, so a silent 0 walks the
    // burst from the origin and emits well-formed, wrong line ids.
    CHECK_THROWS(std::logic_error, extent_on(shape, bad));
    CHECK_THROWS(std::logic_error, coord_on(c, bad));
    CHECK_THROWS(std::logic_error, with_coord_on(c, bad, 1));
    CHECK_THROWS(std::logic_error, axis_name(bad));
}

// Stands in for A3, which does not exist yet: decode one on-disk 5-tuple into
// the canonical Burst, with the field order and burst axis supplied by the
// format v2 header rather than assumed. Written here because A1b's claim is
// that Burst can carry any of these, and the claim is worth nothing untested.
Burst decode(const std::int32_t tuple[5],
             const Axis fixed[3],   // which axis each of the first 3 fields is
             Axis burst_axis,
             std::int32_t burst_stride) {
    Coord anchor{0, 0, 0, 0};
    for (int i = 0; i < 3; ++i) anchor = with_coord_on(anchor, fixed[i], tuple[i]);
    anchor = with_coord_on(anchor, burst_axis, tuple[3]);
    const std::int32_t count = (tuple[4] - tuple[3] + burst_stride - 1) / burst_stride;
    return Burst{anchor, burst_axis, count, burst_stride};
}

void test_burst_decode_any_tuple_order() {
    check::group("Burst carries a burst on any axis, not only COUT");

    // Today's corpus: [kh, kw, cin, cout_start, cout_end].
    {
        const std::int32_t tuple[5] = {1, 0, 64, 12, 16};
        const Axis fixed[3] = {Axis::KH, Axis::KW, Axis::CIN};
        const Burst b = decode(tuple, fixed, Axis::COUT, 1);

        CHECK_EQ(b.anchor.kh, 1);
        CHECK_EQ(b.anchor.kw, 0);
        CHECK_EQ(b.anchor.cin, 64);
        CHECK_EQ(b.anchor.cout, 12);
        CHECK_TRUE(b.axis == Axis::COUT);
        CHECK_EQ(b.count, 4);
        CHECK_EQ(b.stride, 1);

        // Walking the burst is the same expression whatever the axis, which is
        // the property A2's expand rests on.
        const std::int32_t start = coord_on(b.anchor, b.axis);
        for (std::int32_t i = 0; i < b.count; ++i) {
            const Coord e = with_coord_on(b.anchor, b.axis, start + i * b.stride);
            CHECK_EQ(e.cout, 12 + i);
            CHECK_EQ(e.cin, 64);   // the other three are held fixed
            CHECK_EQ(e.kh, 1);
            CHECK_EQ(e.kw, 0);
        }
    }

    // A future corpus: [kh, kw, cout, cin_start, cin_end]. Same struct, same
    // walk, no new field and no branch on the format.
    {
        const std::int32_t tuple[5] = {1, 0, 100, 64, 68};
        const Axis fixed[3] = {Axis::KH, Axis::KW, Axis::COUT};
        const Burst b = decode(tuple, fixed, Axis::CIN, 1);

        CHECK_EQ(b.anchor.kh, 1);
        CHECK_EQ(b.anchor.kw, 0);
        CHECK_EQ(b.anchor.cin, 64);
        CHECK_EQ(b.anchor.cout, 100);
        CHECK_TRUE(b.axis == Axis::CIN);
        CHECK_EQ(b.count, 4);

        const std::int32_t start = coord_on(b.anchor, b.axis);
        for (std::int32_t i = 0; i < b.count; ++i) {
            const Coord e = with_coord_on(b.anchor, b.axis, start + i * b.stride);
            CHECK_EQ(e.cin, 64 + i);
            CHECK_EQ(e.cout, 100);
            CHECK_EQ(e.kh, 1);
            CHECK_EQ(e.kw, 0);
        }
    }

    // A stride > 1, which the header may carry and which nothing downstream
    // may assume away: cin 64, 66, 68, 70.
    {
        const std::int32_t tuple[5] = {2, 1, 8, 64, 72};
        const Axis fixed[3] = {Axis::KH, Axis::KW, Axis::COUT};
        const Burst b = decode(tuple, fixed, Axis::CIN, 2);

        CHECK_EQ(b.count, 4);
        CHECK_EQ(b.stride, 2);
        const std::int32_t start = coord_on(b.anchor, b.axis);
        CHECK_EQ(with_coord_on(b.anchor, b.axis, start + 3 * b.stride).cin, 70);
    }

    // A one-element burst, the degenerate case a layout sweep produces at
    // cout_block = 1 and the shape D9's expand must still return a list for.
    {
        const std::int32_t tuple[5] = {0, 0, 0, 5, 6};
        const Axis fixed[3] = {Axis::KH, Axis::KW, Axis::CIN};
        const Burst b = decode(tuple, fixed, Axis::COUT, 1);
        CHECK_EQ(b.count, 1);
        CHECK_EQ(b.anchor.cout, 5);
    }
}

void test_geometry_is_a_bag_of_values() {
    check::group("Coord / WeightShape / Burst are plain aggregates");

    // Brace initialisation in declaration order, with no constructor to keep
    // in step, is the property every worked example above assumes.
    const WeightShape shape{3, 3, 256, 512};
    CHECK_EQ(shape.KH, 3);
    CHECK_EQ(shape.COUT, 512);

    Coord c{1, 2, 3, 4};
    c.cin = 30;                   // assignable, unlike the Tagged scalars
    CHECK_EQ(c.cin, 30);

    const Burst b{Coord{1, 0, 64, 12}, Axis::COUT, 4, 1};
    CHECK_EQ(b.anchor.cin, 64);
    CHECK_EQ(b.count, 4);

    // Copying a Burst copies its anchor; the anchor is a value, not a handle.
    Burst copy = b;
    copy.anchor.cout = 99;
    CHECK_EQ(copy.anchor.cout, 99);
    CHECK_EQ(b.anchor.cout, 12);
}

// --- compile-time usability -------------------------------------------------
//
// These are checked by the compiler, not at run time. They are here so that
// losing constexpr shows up as a build failure in the test suite rather than
// at the first static_assert someone writes in engine code.

static_assert(SimTime{5} + SimTime{3} == SimTime{8}, "");
static_assert(SimTime{5} + LocalTick{3} == SimTime{8}, "");
static_assert(SimTime{5} - SimTime{3} == SimTime{2}, "");
static_assert(LocalTick{5} + LocalTick{3} == LocalTick{8}, "");
static_assert(RefusalOrder{7} < NoRefusal, "");
static_assert(SlotId{0} != NoSlot, "");
static_assert(LineId{5}.get() == 5, "");

// Layout: the wrapper must cost nothing, or the whole scheme is a tax.
static_assert(sizeof(LineId) == sizeof(std::int64_t), "");
static_assert(sizeof(CoreId) == sizeof(std::int32_t), "");
static_assert(sizeof(SlotId) == sizeof(std::int32_t), "");
static_assert(sizeof(SimTime) == sizeof(std::int64_t), "");
static_assert(alignof(SimTime) == alignof(std::int64_t), "");
static_assert(std::is_trivially_copyable<SimTime>::value, "");
static_assert(std::is_standard_layout<SimTime>::value, "");

// N12 at the type level: the three time-like types are genuinely distinct.
static_assert(!std::is_same<SimTime, LocalTick>::value, "");
static_assert(!std::is_same<SimTime, RefusalOrder>::value, "");
static_assert(!std::is_same<LocalTick, RefusalOrder>::value, "");
static_assert(!std::is_same<LineId, SlotId>::value, "");
static_assert(std::is_same<SimTime, Tagged<std::int64_t, tags::sim_time>>::value, "");

// A1b at compile time. The accessors are constexpr so that A2 can compute
// geometry in a static_assert; losing that shows up here as a build failure
// rather than at the first engine-side use.
static_assert(coord_on(Coord{1, 2, 3, 4}, Axis::KH) == 1, "");
static_assert(coord_on(Coord{1, 2, 3, 4}, Axis::COUT) == 4, "");
static_assert(extent_on(WeightShape{3, 5, 7, 9}, Axis::CIN) == 7, "");
static_assert(with_coord_on(Coord{1, 2, 3, 4}, Axis::CIN, 30).cin == 30, "");
static_assert(with_coord_on(Coord{1, 2, 3, 4}, Axis::CIN, 30).cout == 4, "");

// The four axes are addressed generically, so their coordinates are one type.
static_assert(std::is_same<decltype(coord_on(std::declval<const Coord&>(), Axis::KH)),
                           std::int32_t>::value, "");
static_assert(std::is_same<decltype(coord_on(std::declval<const Coord&>(), Axis::CIN)),
                           decltype(coord_on(std::declval<const Coord&>(), Axis::COUT))>::value,
              "");

// Aggregates, and no bigger than their fields: geometry is copied per burst.
static_assert(sizeof(Coord) == 4 * sizeof(std::int32_t), "");
static_assert(sizeof(WeightShape) == 4 * sizeof(std::int32_t), "");
static_assert(sizeof(Axis) == 1, "");
static_assert(std::is_same<std::underlying_type<Axis>::type, std::uint8_t>::value, "");
static_assert(std::is_trivially_copyable<Burst>::value, "");
static_assert(std::is_standard_layout<Coord>::value, "");

// Coord and WeightShape are four int32s each and are deliberately not the
// same type, so an extent cannot be handed to a coordinate reader.
static_assert(!std::is_same<Coord, WeightShape>::value, "");

}  // namespace

int main() {
    test_round_trip();
    check_ordering<LineId>("ordering: LineId");
    check_ordering<CoreId>("ordering: CoreId");
    check_ordering<SlotId>("ordering: SlotId");
    check_ordering<SimTime>("ordering: SimTime");
    check_ordering<LocalTick>("ordering: LocalTick");
    check_ordering<RefusalOrder>("ordering: RefusalOrder");
    test_ordering_negative_and_boundary();
    test_sentinels();
    test_arithmetic();
    test_hash();
    test_containers();

    test_axis_order();
    test_accessors();
    test_with_coord_on();
    test_unknown_axis_throws();
    test_burst_decode_any_tuple_order();
    test_geometry_is_a_bag_of_values();
    return check::summary();
}
