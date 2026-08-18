// Unit A2a: Placement and the AddressMapper interface.
//
// A2a has no executable code of its own: Placement is two int64s and every
// AddressMapper member is pure. Its content is entirely in the contracts its
// comments state, and those are claims about implementations that do not exist
// yet. So the bulk of this unit's test is not in this file, it is in
// tests/mapper_conformance.h: a set of contract checks parameterised over an
// `AddressMapper&`, which A2d plugs BlockPackMapper into with one line.
//
// This file supplies three things:
//
//   1. mappers to drive that suite with. One conforming, in three
//      configurations, and fifteen that each break exactly one contract.
//   2. the expect-failure driver, which asserts that each broken mapper is
//      actually caught. This is the compile_fail.sh control discipline brought
//      inside the binary: a conformance suite no wrong implementation fails is
//      decoration, and the only way to know is to write the wrong ones.
//   3. the ordinary unit tests for Placement's shape and for the virtual
//      destructor, which are properties of A2a itself rather than of any
//      implementation.
//
// The negative half at the type level (an abstract class cannot be
// instantiated, a subclass may not drop a pure virtual or its const) cannot
// live in a file that must compile. It is tests/compile_fail.sh.
#include <wcache/layout.h>
#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "check.h"
#include "mapper_conformance.h"

using namespace wcache;

namespace {

using conformance::Env;
using conformance::kAxes;

// ===========================================================================
// The conforming mapper
// ===========================================================================
//
// This is NOT BlockPackMapper and is not a preview of one: no cin_block, no
// cout_block, no blocking at all. A2b to A2d build the real thing. What is
// needed here is the smallest object that satisfies layout.h, so the
// conformance checks have something to pass on, and then a family of near
// misses so they have something to fail on.
//
// PackedRowMajor flattens in the declaration order of Axis, which A1b's
// carried obligation says IS the row-major nesting order, and packs `pack_`
// consecutive elements of that order into one line. With pack_ = 1 every
// element is its own line and the de-duplication path never fires; with
// pack_ = COUT a whole COUT burst collapses to one line and it always does.
// Both are run below, because a check that only ever sees one of them is
// half a check.
class PackedRowMajor : public AddressMapper {
public:
    PackedRowMajor(WeightShape shape, std::int64_t pack, std::int64_t weight_bytes)
        : shape_(shape), pack_(pack), weight_bytes_(weight_bytes) {}

    void expand(const Burst& b, std::vector<LineId>& out) const override {
        // Every range check first, and nothing appended until they all pass.
        // That ordering is the contract, not an implementation preference.
        check_range(b);
        append_walk(b, out);
    }

    Placement locate(LineId line, std::int64_t num_sets) const override {
        return Placement{line.get() % num_sets, line.get() / num_sets};
    }

    LineId num_lines() const override { return LineId{(elements() + pack_ - 1) / pack_}; }

    std::int64_t line_size_bytes() const override { return pack_ * weight_bytes_; }

protected:
    // The flatten A1b's obligation pins: reordering Axis without reordering
    // this expression gives plausible, wrong line ids.
    std::int64_t flat(const Coord& c) const {
        return ((static_cast<std::int64_t>(c.kh) * shape_.KW + c.kw) * shape_.CIN + c.cin) *
                   shape_.COUT +
               c.cout;
    }

    std::int64_t line_of(const Coord& c) const { return flat(c) / pack_; }

    std::int64_t elements() const {
        return static_cast<std::int64_t>(shape_.KH) * shape_.KW * shape_.CIN * shape_.COUT;
    }

    void check_range(const Burst& b) const {
        if (b.count < 1) throw std::invalid_argument("burst count must be >= 1");
        if (b.stride < 1) throw std::invalid_argument("burst stride must be >= 1");
        for (Axis a : kAxes) in_range_or_throw(a, coord_on(b.anchor, a));
        // The far end of the walk, which is where a burst that starts legal
        // leaves the tensor. Computed in 64 bits so a large count cannot wrap
        // into a valid-looking coordinate.
        const std::int64_t last = static_cast<std::int64_t>(coord_on(b.anchor, b.axis)) +
                                  static_cast<std::int64_t>(b.count - 1) * b.stride;
        if (last >= extent_on(shape_, b.axis))
            throw std::out_of_range(std::string("burst leaves the tensor along ") +
                                    axis_name(b.axis));
    }

    void in_range_or_throw(Axis a, std::int32_t v) const {
        if (v < 0 || v >= extent_on(shape_, a))
            throw std::out_of_range(std::string(axis_name(a)) + " coordinate " +
                                    std::to_string(v) + " outside [0, " +
                                    std::to_string(extent_on(shape_, a)) + ")");
    }

    // The walk, factored out so a broken subclass can reuse the flatten and
    // break only the thing it means to break.
    void append_walk(const Burst& b, std::vector<LineId>& out) const {
        const std::int32_t start = coord_on(b.anchor, b.axis);
        std::int64_t last = -1;
        for (std::int32_t i = 0; i < b.count; ++i) {
            const Coord c = with_coord_on(b.anchor, b.axis, start + i * b.stride);
            const std::int64_t line = line_of(c);
            if (line != last) {
                out.push_back(LineId{line});
                last = line;
            }
        }
    }

    WeightShape  shape_;
    std::int64_t pack_;
    std::int64_t weight_bytes_;
};

// ===========================================================================
// The non-conforming mappers, one contract each
// ===========================================================================
//
// Each derives from the conforming one and breaks exactly one thing, so that
// when the suite catches it there is no doubt about which check did the work.
// Any of these would pass a suite that only asserted "expand returned some
// sorted ids", which is the suite this file exists to avoid writing.

// Contract 1. The buffer is cleared, so an accumulate across cores keeps only
// the last core's lines. Sorted, distinct, in range, right count: invisible to
// everything except the append check.
class AssignsInsteadOfAppends : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        out.clear();
        PackedRowMajor::expand(b, out);
    }
};

// Contract 1, the state half. Remembers the last line emitted across calls, so
// two bursts that meet on a line drop the join. This is what a mapper written
// with a "don't repeat myself" cache looks like, and it is legal C++ under the
// const interface because the member is mutable.
class DedupesAcrossCalls : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        std::vector<LineId> tmp;
        PackedRowMajor::expand(b, tmp);
        for (LineId l : tmp) {
            if (!(l == last_)) out.push_back(l);
            last_ = l;
        }
    }

private:
    mutable LineId last_{-1};
};

// Contract 2. Descending inside a single call. Still distinct, still the right
// count, still in range.
class AppendsDescending : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        const std::size_t base = out.size();
        PackedRowMajor::expand(b, out);
        std::reverse(out.begin() + static_cast<std::ptrdiff_t>(base), out.end());
    }
};

// Contract 2. One id per element with no de-duplication, so a burst narrower
// than a line appends the same id several times. Non-decreasing but not
// strictly increasing, which is exactly the distinction the check is for: a
// caller counting distinct lines would over-count every packed burst.
class KeepsDuplicates : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        check_range(b);
        const std::int32_t start = coord_on(b.anchor, b.axis);
        for (std::int32_t i = 0; i < b.count; ++i)
            out.push_back(LineId{line_of(with_coord_on(b.anchor, b.axis, start + i * b.stride))});
    }
};

// Contract 3. Checks each element as it reaches it, which is the natural way
// to write expand and the one layout.h forbids: a burst that starts inside the
// tensor and runs off the end appends its legal prefix and then throws.
class ChecksAsItGoes : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        const std::int32_t start = coord_on(b.anchor, b.axis);
        std::int64_t last = -1;
        for (std::int32_t i = 0; i < b.count; ++i) {
            const Coord c = with_coord_on(b.anchor, b.axis, start + i * b.stride);
            for (Axis a : kAxes) in_range_or_throw(a, coord_on(c, a));
            const std::int64_t line = line_of(c);
            if (line != last) {
                out.push_back(LineId{line});
                last = line;
            }
        }
    }
};

// Contract 3b. Throws, and leaves the buffer alone, but names the wrong type.
// Split out from the eager mapper above so the two failures never blur: this
// one satisfies the strong guarantee and only disagrees about the type.
class ThrowsWrongType : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        try {
            PackedRowMajor::expand(b, out);
        } catch (const std::out_of_range& ex) {
            throw std::runtime_error(ex.what());
        }
    }
};

// Contract 3c. v1's reading of an empty burst, which B38 dropped: `count < 1`
// is served as a legal run of no elements. It throws nothing, appends nothing,
// and every other check in the file passes on it, because every other check is
// driven from the legal and illegal sets and this mapper is right on both.
class ServesAnEmptyBurst : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        if (b.count < 1) return;
        PackedRowMajor::expand(b, out);
    }
};

// Contract 3c, the tier half. Refuses the burst, leaves the buffer alone, and
// names the wrong tier. Split from the mapper above for the same reason
// ThrowsWrongType is split from ChecksAsItGoes: one disagrees about whether to
// refuse, the other only about which refusal it is, and blurring them would let
// a single fake stand for two different failures.
class MalformedBurstIsOutOfRange : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        if (b.count < 1) throw std::out_of_range("burst count must be >= 1");
        PackedRowMajor::expand(b, out);
    }
};

// Contract 3c, the stride half. Serves a burst whose stride is 0 or negative as
// the one line its anchor sits on, which is the reading B49 rejected. Its own
// bucket-mate above disagrees about the count; this one disagrees about the
// stride, and without it nothing in this file would notice if the Env's
// stride-malformed bursts were dropped.
class ServesAStandingStillBurst : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        if (b.stride < 1) {
            out.push_back(LineId{line_of(b.anchor)});
            return;
        }
        PackedRowMajor::expand(b, out);
    }
};

// Contract 4. Refuses an axis it does not pack. The A2a -> A2d carried
// obligation in one class: the corpus never issues a KH burst, so this mapper
// would run the entire study without complaint.
class RejectsUnpackedAxis : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        if (b.axis != Axis::COUT)
            throw std::invalid_argument("this layout only bursts along COUT");
        PackedRowMajor::expand(b, out);
    }
};

// Contract 5. Reads the anchor's COUT whatever the burst says, which is the
// shape of "today's corpus always says COUT" baked in. Its output is sorted,
// distinct, in range and plausibly sized for every burst.
class AssumesCout : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        check_range(b);
        Burst forced = b;
        forced.axis = Axis::COUT;
        // Clamp so the forced walk stays inside the tensor: the point is a
        // wrong answer, not a second throw.
        const std::int32_t room = shape_.COUT - b.anchor.cout;
        forced.count = b.count < room ? b.count : room;
        forced.stride = 1;
        append_walk(forced, out);
    }
};

// Contract 5. Walks with stride 1 whatever the header said. Format v2 carries
// burst_stride precisely so this cannot be assumed.
class IgnoresStride : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    void expand(const Burst& b, std::vector<LineId>& out) const override {
        check_range(b);
        Burst flat_walk = b;
        flat_walk.stride = 1;
        append_walk(flat_walk, out);
    }
};

// Contract 6. Set index and tag swapped. Silent under a small number of sets
// and catastrophic under a large one, and the identity catches it either way.
class SwapsSetAndTag : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    Placement locate(LineId line, std::int64_t num_sets) const override {
        return Placement{line.get() / num_sets, line.get() % num_sets};
    }
};

// Contract 7. A bound that is merely an upper bound. Every id is still inside
// it, so only the "one PAST the largest" half notices, and that half is what
// D2's coverage denominator rests on.
class LooseNumLines : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    LineId num_lines() const override { return LineId{PackedRowMajor::num_lines().get() * 2}; }
};

// Contract 7, the other direction: a bound real lines exceed, which is the
// engine rejecting valid tags.
class TightNumLines : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    LineId num_lines() const override { return LineId{PackedRowMajor::num_lines().get() / 2}; }
};

// Contract 8. Zero bytes per line, which is the divide by zero D1 would hit
// while turning cache_size_bytes into a set count.
class ZeroLineSize : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    std::int64_t line_size_bytes() const override { return 0; }
};

// Contract 9, added by A4b. layout.h's line_size_terms has an inline DEFAULT
// rather than being pure, so no mapper is obliged to override it and every
// mapper inherits a correct answer for free. These two are the ways an override
// can still take that away.
//
// Empty is the first. SetAssociativeArray's refusal then reads "... 8-byte
// lines ()", which is a message that has lost the reason it was made
// actionable, and nothing else in the tree would notice.
class EmptyLineSizeTerms : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    std::string line_size_terms() const override { return ""; }
};

// And the worse one: terms that are well formed and describe a different line
// size. PackedRowMajor here packs 4 elements of 2 bytes, so its line is 8, and
// this says 3 x 5. A reader acts on it, changes the wrong config field, and the
// geometry is still refused. Non-empty is therefore not enough on its own,
// which is why the contract multiplies the numbers out.
class MisleadingLineSizeTerms : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    std::string line_size_terms() const override { return "cin_block 3 x weight_bytes 5"; }
};

// ===========================================================================
// The expect-failure driver
// ===========================================================================
//
// The contract checks are ordinary CHECK_ macros, so their failures land in
// the global counters and print. Here the counters are snapshotted, the body
// runs quiet, the counters are restored, and the only thing that survives is
// the verdict: did the check catch this mapper or not.
//
// The `ran == 0` arm is the control. Without it, a case that silently exercised
// no checks at all (an empty Env, a renamed contract, a typo in the fake) would
// report "not caught" or, worse in a later refactor, be quietly counted as a
// catch. It is the same reason compile_fail.sh ends with accept cases.
template <typename Fn>
void expect_caught(const char* name, Fn body) {
    const int checks_before   = check::g_checks;
    const int failures_before = check::g_failures;
    {
        const check::Quiet quiet;
        body();
    }
    const int ran    = check::g_checks - checks_before;
    const int failed = check::g_failures - failures_before;
    check::g_checks   = checks_before;
    check::g_failures = failures_before;

    ++check::g_checks;
    if (ran == 0) {
        ++check::g_failures;
        std::printf("FAIL  %-40s the contract check ran NO checks at all\n", name);
    } else if (failed == 0) {
        ++check::g_failures;
        std::printf("FAIL  %-40s NOT caught (%d checks, all passed)\n", name, ran);
    } else {
        std::printf("  caught  %-38s %d of %d checks failed\n", name, failed, ran);
    }
}

// ===========================================================================
// Placement
// ===========================================================================

void test_placement_is_an_aggregate() {
    check::group("Placement: two signed 64-bit fields, brace initialised");

    // Declaration order, with no constructor to keep in step. locate() returns
    // one of these by braced init, so swapping the two field declarations
    // silently swaps every mapper's answer; that is why the order is pinned
    // here by value rather than assumed.
    const Placement p{3, 100};
    CHECK_EQ(p.set_index, std::int64_t{3});
    CHECK_EQ(p.tag, std::int64_t{100});

    Placement q{0, 0};
    q.set_index = 7;  // assignable, unlike the Tagged scalars
    q.tag = -1;
    CHECK_EQ(q.set_index, std::int64_t{7});
    CHECK_EQ(q.tag, std::int64_t{-1});

    // Copying copies values, not a handle.
    Placement r = p;
    r.tag = 55;
    CHECK_EQ(r.tag, std::int64_t{55});
    CHECK_EQ(p.tag, std::int64_t{100});
}

void test_placement_identity_at_the_boundaries() {
    check::group("Placement: line == tag * num_sets + set_index");

    // layout.h's stated reason for both fields being signed and 64-bit is that
    // this identity holds without a cast. Checked at the two ends of a set, at
    // a tag large enough to need 64 bits, and at INT64_MAX.
    struct Case {
        std::int64_t line;
        std::int64_t num_sets;
    };
    const Case cases[] = {
        {0, 1},                      // the degenerate array: one set, tag == line
        {0, 64},                     // set_index = 0
        {63, 64},                    // set_index = num_sets - 1
        {64, 64},                    // first line of the next tag
        {1'000'003, 128},            // a tag that is not a small number
        {(std::int64_t{1} << 40), 512},
        {INT64_MAX, 8},              // set_index 7, tag (INT64_MAX - 7) / 8
        {INT64_MAX - 1, 2},
        {INT64_MAX, 1},              // tag == INT64_MAX, num_sets == 1
    };

    for (const Case& c : cases) {
        const Placement p{c.line % c.num_sets, c.line / c.num_sets};
        CHECK_TRUE(p.set_index >= 0);
        CHECK_TRUE(p.set_index < c.num_sets);
        // The multiply is the step that would overflow if these were computed
        // from a fabricated tag rather than from a real line, which is why the
        // cases above all derive the placement from a line id.
        CHECK_EQ(p.tag * c.num_sets + p.set_index, c.line);
    }

    // What the interface does NOT promise, recorded here so nobody reads the
    // cases above as covering it: Placement is a plain aggregate, so a caller
    // may build one with any tag at all, and `tag * num_sets` then overflows
    // for tag > INT64_MAX / num_sets. That is signed overflow, undefined
    // behaviour, and layout.h states no precondition on tag. Nothing is
    // asserted about it here; it is in the reviewer's report as a question.
}

// ===========================================================================
// The interface itself
// ===========================================================================

// Set by ~DtorProbe. A flag rather than an inspection, because the property is
// "the derived destructor RUNS", and std::has_virtual_destructor only says the
// compiler was asked to make it possible.
bool g_derived_dtor_ran = false;

class DtorProbe : public PackedRowMajor {
public:
    using PackedRowMajor::PackedRowMajor;
    ~DtorProbe() override { g_derived_dtor_ran = true; }
};

void test_virtual_destructor_runs() {
    check::group("AddressMapper: deleting through a base pointer runs ~Derived");

    // A non-virtual base destructor here is undefined behaviour whose usual
    // symptom is a leak, not a crash, so it would not announce itself in any
    // other test. The engine holds mappers by base pointer, so this is the
    // shape it will actually be destroyed in.
    const WeightShape shape{2, 2, 4, 8};

    g_derived_dtor_ran = false;
    {
        AddressMapper* m = new DtorProbe(shape, 4, 2);
        CHECK_TRUE(!g_derived_dtor_ran);  // control: not set before the delete
        delete m;
    }
    CHECK_TRUE(g_derived_dtor_ran);

    // And through the owner the engine will actually use.
    g_derived_dtor_ran = false;
    {
        std::unique_ptr<AddressMapper> owned(new DtorProbe(shape, 4, 2));
        CHECK_TRUE(!g_derived_dtor_ran);
    }
    CHECK_TRUE(g_derived_dtor_ran);
}

void test_dynamic_dispatch() {
    check::group("AddressMapper: calls resolve on the dynamic type");

    // The point of the interface: the engine holds an AddressMapper and never
    // learns which one it has. Two layouts behind one reference must give two
    // different answers for the same burst, or the abstraction is decorative.
    const WeightShape shape{2, 2, 4, 8};
    const PackedRowMajor one_per_line(shape, 1, 2);
    const PackedRowMajor four_per_line(shape, 4, 2);

    const AddressMapper* mappers[2] = {&one_per_line, &four_per_line};
    const Burst b{Coord{0, 0, 0, 0}, Axis::COUT, 8, 1};

    std::vector<LineId> a, c;
    mappers[0]->expand(b, a);
    mappers[1]->expand(b, c);
    CHECK_EQ(check::ssize(a), std::int64_t{8});  // every element its own line
    CHECK_EQ(check::ssize(c), std::int64_t{2});  // four elements share a line
    CHECK_TRUE(mappers[0]->line_size_bytes() != mappers[1]->line_size_bytes());
    CHECK_TRUE(mappers[0]->num_lines() != mappers[1]->num_lines());
}

// ===========================================================================
// Driving the conformance suite
// ===========================================================================

void test_conforming_mappers_pass() {
    // Three packings, because several checks are inert under one of them: at
    // pack = 1 the de-duplication path never fires and a burst always yields
    // `count` ids; at pack = COUT a whole COUT burst is one id and the
    // strictly-increasing check has almost nothing to compare. A mapper that
    // passed only at one packing would be a suite that tested one packing.
    //
    // The shape is small on purpose: the sweep in c_num_lines_is_exact visits
    // every element of the tensor.
    const WeightShape shape{3, 3, 8, 12};
    const Env env = conformance::make_env(shape);

    const PackedRowMajor unpacked(shape, 1, 2);
    const PackedRowMajor packed4(shape, 4, 2);
    const PackedRowMajor packed_line(shape, 12, 2);  // a whole COUT run per line

    conformance::run_all(unpacked, env, "conformance: one element per line");
    conformance::run_all(packed4, env, "conformance: four elements per line");
    conformance::run_all(packed_line, env, "conformance: a COUT run per line");

    // A shape with an extent of 1 on two axes, which is what a 1x1 convolution
    // looks like and where several of make_env's bursts degenerate.
    const WeightShape pointwise{1, 1, 16, 16};
    conformance::run_all(PackedRowMajor(pointwise, 4, 2), conformance::make_env(pointwise),
                         "conformance: 1x1 layer");

    // ---------------------------------------------------------------------
    // A2d's `conformance::run_all(BlockPackMapper(...), env, "BlockPackMapper")`
    // landed in tests/test_block_pack.cpp, not here. Recorded rather than left
    // as a stale invitation: this file is A2a's, its fifteen fakes and its
    // expect-failure driver are about the interface, and the Makefile builds one
    // binary per test file precisely so a helper written for one unit cannot
    // leak into another's. Including block_pack.h here would make the A2a binary
    // depend on the concrete mapper for no gain, since run_all takes an
    // `const AddressMapper&` and does not care which file calls it.
    // ---------------------------------------------------------------------
}

void test_broken_mappers_are_caught() {
    check::group("the conformance suite catches a mapper that breaks a contract");

    const WeightShape shape{3, 3, 8, 12};
    const Env env = conformance::make_env(shape);

    // pack = 4 for every fake, so that bursts both share lines and do not,
    // and no fake is caught only because its packing was degenerate.
    const AssignsInsteadOfAppends assigns(shape, 4, 2);
    const DedupesAcrossCalls     stateful(shape, 4, 2);
    const AppendsDescending      descending(shape, 4, 2);
    const KeepsDuplicates        duplicates(shape, 4, 2);
    const ChecksAsItGoes         eager(shape, 4, 2);
    const ThrowsWrongType        wrong_type(shape, 4, 2);
    const ServesAnEmptyBurst     empty_ok(shape, 4, 2);
    const MalformedBurstIsOutOfRange empty_is_range(shape, 4, 2);
    const ServesAStandingStillBurst  standing_still(shape, 4, 2);
    const RejectsUnpackedAxis    cout_only(shape, 4, 2);
    const AssumesCout            assumes_cout(shape, 4, 2);
    const IgnoresStride          ignores_stride(shape, 4, 2);
    const SwapsSetAndTag         swapped(shape, 4, 2);
    const LooseNumLines          loose(shape, 4, 2);
    const TightNumLines          tight(shape, 4, 2);
    const ZeroLineSize           zero_bytes(shape, 4, 2);
    const EmptyLineSizeTerms     no_terms(shape, 4, 2);
    const MisleadingLineSizeTerms wrong_terms(shape, 4, 2);

    expect_caught("expand assigns instead of appending",
                  [&] { conformance::c_appends_not_assigns(assigns, env); });
    expect_caught("expand carries state between calls",
                  [&] { conformance::c_appends_not_assigns(stateful, env); });
    expect_caught("one call appends descending ids",
                  [&] { conformance::c_single_call_strictly_increasing(descending, env); });
    expect_caught("one call repeats a line id",
                  [&] { conformance::c_single_call_strictly_increasing(duplicates, env); });
    expect_caught("range checked as the walk goes",
                  [&] { conformance::c_throwing_call_appends_nothing(eager, env); });
    expect_caught("throws, but not out_of_range",
                  [&] { conformance::c_throw_type_is_out_of_range(wrong_type, env); });
    expect_caught("serves a zero-count burst (v1's reading)",
                  [&] { conformance::c_malformed_burst_is_invalid_argument(empty_ok, env); });
    expect_caught("a zero-count burst throws out_of_range",
                  [&] { conformance::c_malformed_burst_is_invalid_argument(empty_is_range, env); });
    expect_caught("serves a stride < 1 burst",
                  [&] { conformance::c_malformed_burst_is_invalid_argument(standing_still, env); });
    expect_caught("refuses an axis it does not pack",
                  [&] { conformance::c_accepts_any_axis(cout_only, env); });
    expect_caught("walks COUT whatever the burst says",
                  [&] { conformance::c_burst_is_its_elements(assumes_cout, env); });
    expect_caught("ignores the burst stride",
                  [&] { conformance::c_burst_is_its_elements(ignores_stride, env); });
    expect_caught("locate swaps set index and tag",
                  [&] { conformance::c_locate_identity(swapped, env); });
    expect_caught("num_lines is only an upper bound",
                  [&] { conformance::c_num_lines_is_exact(loose, env); });
    expect_caught("num_lines is below a real id",
                  [&] { conformance::c_num_lines_is_exact(tight, env); });
    expect_caught("line_size_bytes is zero",
                  [&] { conformance::c_line_size_bytes_is_usable(zero_bytes, env); });
    expect_caught("line_size_terms says nothing",
                  [&] { conformance::c_line_size_terms_is_informative(no_terms, env); });
    expect_caught("line_size_terms names another line size",
                  [&] { conformance::c_line_size_terms_is_informative(wrong_terms, env); });

    // The control the other way round. Every case above asserts that a check
    // fails; this asserts that the same machinery reports a pass when the
    // mapper is right, so "caught" cannot mean "always fails".
    {
        const PackedRowMajor good(shape, 4, 2);
        const int checks_before   = check::g_checks;
        const int failures_before = check::g_failures;
        conformance::c_appends_not_assigns(good, env);
        conformance::c_single_call_strictly_increasing(good, env);
        conformance::c_throwing_call_appends_nothing(good, env);
        conformance::c_malformed_burst_is_invalid_argument(good, env);
        conformance::c_burst_is_its_elements(good, env);
        conformance::c_locate_identity(good, env);
        const int ran = check::g_checks - checks_before;
        const int failed = check::g_failures - failures_before;
        CHECK_TRUE(ran > 0);
        CHECK_EQ(failed, 0);
    }
}

// ===========================================================================
// Compile-time properties of A2a
// ===========================================================================
//
// Here rather than in compile_fail.sh where the property is positive: a
// static_assert states it in the file that must build, so losing it is a build
// failure in the suite rather than a silent weakening.

static_assert(std::is_abstract<AddressMapper>::value, "");
static_assert(std::is_polymorphic<AddressMapper>::value, "");

// The one that would otherwise only show up as a leak. std::has_virtual_destructor
// is the compile-time half; test_virtual_destructor_runs is the observable half,
// and both are kept because either alone is weaker than the pair.
static_assert(std::has_virtual_destructor<AddressMapper>::value, "");

// An abstract class cannot be copied or sliced, which is what keeps the engine
// from accidentally taking a mapper by value and losing the layout.
static_assert(!std::is_copy_constructible<AddressMapper>::value, "");
static_assert(!std::is_default_constructible<AddressMapper>::value, "");

// A concrete implementation is ordinary: constructible, and usable through the
// base. If PackedRowMajor left a pure virtual unimplemented this line would
// fail, which is what makes the four compile_fail cases' controls meaningful.
static_assert(!std::is_abstract<PackedRowMajor>::value, "");
static_assert(std::is_base_of<AddressMapper, PackedRowMajor>::value, "");
static_assert(std::is_convertible<PackedRowMajor*, AddressMapper*>::value, "");

// Placement: an aggregate of two signed 64-bit fields, in that order.
static_assert(std::is_aggregate<Placement>::value, "");
static_assert(std::is_standard_layout<Placement>::value, "");
static_assert(std::is_trivially_copyable<Placement>::value, "");
static_assert(sizeof(Placement) == 2 * sizeof(std::int64_t), "");
static_assert(std::is_same<decltype(Placement::set_index), std::int64_t>::value, "");
static_assert(std::is_same<decltype(Placement::tag), std::int64_t>::value, "");
static_assert(std::is_signed<decltype(Placement::set_index)>::value, "");
static_assert(std::is_signed<decltype(Placement::tag)>::value, "");
// layout.h's stated reason for signedness, restated as arithmetic rather than
// as a trait: on an unsigned field `0 <= set_index` is vacuously true and the
// bounds check in every array becomes half a check. This says the field can
// actually hold a value that fails it.
static_assert(static_cast<decltype(Placement::set_index)>(-1) < 0, "");

// The interface's signatures, pinned. A2b's override must match these, and a
// silently changed parameter type would turn an override into an overload: the
// base's pure virtual stays unimplemented and the class stays abstract, which
// is caught, but a changed RETURN type or a dropped const is not always.
static_assert(std::is_same<decltype(&AddressMapper::locate),
                           Placement (AddressMapper::*)(LineId, std::int64_t) const>::value, "");
static_assert(std::is_same<decltype(&AddressMapper::expand),
                           void (AddressMapper::*)(const Burst&, std::vector<LineId>&) const>::value,
              "");
static_assert(std::is_same<decltype(&AddressMapper::num_lines),
                           LineId (AddressMapper::*)() const>::value, "");
static_assert(std::is_same<decltype(&AddressMapper::line_size_bytes),
                           std::int64_t (AddressMapper::*)() const>::value, "");

// num_lines returns a LineId and line_size_bytes an int64: a line count and a
// byte count are not the same quantity, and N12's whole argument is that the
// type wall is what stops them being added together. The negative half is in
// compile_fail.sh; this is the positive statement that they are different types.
static_assert(!std::is_same<decltype(std::declval<const AddressMapper&>().num_lines()),
                            decltype(std::declval<const AddressMapper&>().line_size_bytes())>::value,
              "");

}  // namespace

int main() {
    test_placement_is_an_aggregate();
    test_placement_identity_at_the_boundaries();
    test_virtual_destructor_runs();
    test_dynamic_dispatch();
    test_conforming_mappers_pass();
    test_broken_mappers_are_caught();
    return check::summary();
}
