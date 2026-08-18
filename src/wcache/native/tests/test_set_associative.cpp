// Units A4b and A4c: SetAssociativeArray, whole.
//
// A4b is the constructor and three accessors: the geometry it derives and the
// seven refusals it makes on the way. A4c is the five verbs, which were
// std::logic_error stubs (B19) when A4b landed and now have bodies.
//
// The six checks that pinned the stubs are gone from this file, replaced
// rather than deleted: they said in their own comment that A4c is the event
// that makes "nothing answers the question yet" meaningless, which is B45's
// precedent for a tripwire whose target has landed. What replaces each of them
// is a check on the behaviour the verb now has.
//
// Its own file rather than more of tests/test_cache.cpp, and the reason is the
// same one that put SetAssociativeArray in its own header. test_cache.cpp
// includes <wcache/cache.h> and nothing else, which is what makes it evidence
// that the array interface needs no layout header; adding A4b there would drag
// set_associative.h, and therefore layout.h, into that file and quietly retire
// the property. The split mirrors A2's exactly: test_layout.cpp for the
// abstract AddressMapper, test_block_pack.cpp for the concrete mapper.
// TEST_DESIGN_CACHE.md section 1 names test_cache.cpp instead, but it is
// written against the v1 archive's single-binary build and B21 replaced that
// with one binary per test file.
//
// Group letters follow TEST_DESIGN_CACHE.md: K is the constructor and the
// derived quantities, L is the rejections, M through S are the verbs. That
// document predates `invalidate` being on the interface and lists it as not
// covered; it is covered here, alongside `insert`, since the two are the only
// verbs that take a SlotId and they share one bound check.
#include <wcache/set_associative.h>

#include <wcache/block_pack.h>
#include <wcache/cache.h>
#include <wcache/layout.h>

#include <cstdint>
#include <initializer_list>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "check.h"

using namespace wcache;

namespace {

// ===========================================================================
// Probes and fixtures
// ===========================================================================
//
// The message probe is test_block_pack.cpp's, kept in that shape deliberately:
// the exception type is encoded INTO the returned string rather than checked
// separately, so a mutation that changes invalid_argument to some other type
// fails the prefix check with a message naming what came out instead. Catch
// clauses narrowest first, since invalid_argument derives from logic_error and
// the reverse order would report every refusal as a plain logic_error and stop
// telling a refusal apart from an A4c stub.

constexpr const char* kPrefix = "SetAssociativeArray: ";

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

// The mirror probe, for the verbs, where out_of_range is the RIGHT answer:
// B27 gives out_of_range to a well-formed argument naming something outside
// this layer, which a slot id past the end and a line id past the mapper both
// are. Two probes rather than one parameterised probe, for test_block_pack.cpp's
// reason: the two cases disagree about which type is correct, and a single
// probe would have to be told which, which is the thing being tested.
//
// The catch order is narrowest first and both siblings are named before their
// base, so a refusal that came out as invalid_argument is reported as that
// rather than as a plain logic_error.
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

// One check per message, printing the message that actually came out. A
// CHECK_TRUE per needle would print the expression source instead, which for a
// containment test on a runtime string tells a reader nothing they can act on.
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
            std::printf("FAIL  %-46s missing:%s\n  message  : %s\n",
                        name, missing.c_str(), actual.c_str());
    }
}

// The same, for a needle that must be ABSENT. Used where two refusals could
// both apply and the question is which one ran, since a message containing
// both names would pass every containment check while proving nothing about
// the order.
void expect_absent(const char* name, const std::string& actual, const char* needle) {
    ++check::g_checks;
    if (contains(actual, needle)) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s should NOT contain \"%s\"\n  message  : %s\n",
                        name, needle, actual.c_str());
    }
}

// Everything the array will answer about every line, read through the
// interface and nothing else. The slot vector is private, so this is what an
// "array state" comparison has to be made of: probe, free_slot and the whole
// candidate list, for every line the mapper admits.
//
// It is deliberately built from the CONST verbs only. That is what lets it
// stand as evidence about probe: a snapshot that had to insert something to
// read the state would be changing the thing it measures.
std::vector<std::int64_t> observables(const SetAssociativeArray& a, std::int64_t lines) {
    std::vector<std::int64_t> v;
    std::vector<Candidate> out;
    for (std::int64_t l = 0; l < lines; ++l) {
        const LineId line{l};
        v.push_back(a.probe(line).get());
        v.push_back(a.free_slot(line).get());
        a.victim_candidates(line, out);
        for (const Candidate& c : out) {
            v.push_back(c.slot.get());
            v.push_back(c.line.get());
        }
    }
    return v;
}

// One check per comparison, reporting the FIRST index that differs rather than
// printing two vectors of several thousand numbers. A CHECK_EQ on the vectors
// would be correct and unreadable, and the index is the only part a reader can
// act on: it names which line, and which of its answers, moved.
void expect_same_observables(const char* name,
                             const std::vector<std::int64_t>& before,
                             const std::vector<std::int64_t>& after) {
    ++check::g_checks;
    if (before.size() != after.size()) {
        ++check::g_failures;
        if (!check::g_quiet)
            std::printf("FAIL  %-46s length %zu became %zu\n",
                        name, before.size(), after.size());
        return;
    }
    for (std::size_t i = 0; i < before.size(); ++i) {
        if (before[i] != after[i]) {
            ++check::g_failures;
            if (!check::g_quiet)
                std::printf("FAIL  %-46s answer %zu was %lld, is now %lld\n", name, i,
                            static_cast<long long>(before[i]),
                            static_cast<long long>(after[i]));
            return;
        }
    }
}

// --- the mappers -------------------------------------------------------------

// B22's worked layer, at the blocks that give the 256-byte line the plan's L1
// example is sized in: 16 x 16 x 1. Every accepted geometry below is a byte
// count over this line size, so a test about associativity is never
// accidentally a test about the line size.
constexpr WeightShape kShape{3, 3, 512, 512};
constexpr std::int64_t kLine = 256;  // cin_block 16 x cout_block 16 x weight_bytes 1

// The smallest AddressMapper that answers the two questions the array asks,
// with the line size under the test's control. TEST_DESIGN_CACHE.md section 6
// flags this as the one piece of new scaffolding the design needs, for the
// case a real BlockPackMapper cannot reach: line_size_bytes() <= 0, which
// BlockPackMapper's own constructor refuses before an array could ever see it.
//
// It deliberately does NOT override line_size_terms(). That is not an
// oversight, it is the fixture for layout.h's inline default: a mapper whose
// line size does not decompose into named factors must still produce a
// well-formed refusal.
//
// It counts its line_size_bytes() calls, because "read once" is stated in
// set_associative.cpp as load-bearing and nothing else can observe it.
class TinyMapper : public AddressMapper {
public:
    explicit TinyMapper(std::int64_t line_bytes) : line_bytes_(line_bytes) {}

    void expand(const Burst&, std::vector<LineId>&) const override {
        throw std::logic_error("TinyMapper::expand: A4b never calls it");
    }
    Placement locate(LineId line, std::int64_t num_sets) const override {
        return Placement{SetIndex{line.get() % num_sets}, TagId{line.get() / num_sets}};
    }
    LineId       num_lines()       const override { return LineId{1}; }
    std::int64_t line_size_bytes() const override { ++reads_; return line_bytes_; }

    int reads() const { return reads_; }

private:
    std::int64_t line_bytes_;
    mutable int  reads_ = 0;
};

// The same mapper with line_size_terms OVERRIDDEN, so the array's refusal has
// to reach the override rather than the inline default. It is what shows that
// the default is a default and not a fixed answer.
class TermsMapper final : public TinyMapper {
public:
    using TinyMapper::TinyMapper;
    std::string line_size_terms(std::int64_t) const override { return "a fixed string"; }
};

// A mapper that answers line_size_bytes() DIFFERENTLY on every call. Nothing in
// the tree needs such a mapper to work; it exists to make the read-once
// discipline observable, and it is the case Q3's argument was added for.
//
// The array reads the line size once, refuses on that value, and passes the
// same value to line_size_terms, so both halves of the message name the first
// answer. Before Q3 the inline default asked the mapper again and printed the
// SECOND answer, so one message said "96-byte lines (97)": a diagnostic
// contradicting itself. That is checked below rather than argued.
class DriftingLineSize : public AddressMapper {
public:
    void expand(const Burst&, std::vector<LineId>&) const override {
        throw std::logic_error("DriftingLineSize::expand: never called");
    }
    Placement locate(LineId line, std::int64_t num_sets) const override {
        return Placement{SetIndex{line.get() % num_sets}, TagId{line.get() / num_sets}};
    }
    LineId       num_lines()       const override { return LineId{1}; }
    std::int64_t line_size_bytes() const override { return 96 + reads_++; }

private:
    mutable std::int64_t reads_ = 0;
};

// ===========================================================================
// Group K: the accepted geometries and what the constructor derives
// ===========================================================================

void test_the_two_real_geometries() {
    check::group("A4b K1, K2, K6: the L1 and L2 geometries, and num_slots = num_sets x assoc");

    const BlockPackMapper m(kShape, 16, 16, 1);
    CHECK_EQ(m.line_size_bytes(), kLine);

    // K1, the plan's L1: 64 KB of 256-byte lines is 256 lines, 8 ways deep is
    // 32 sets. All three numbers differ, which is the whole point of the case:
    // num_slots alone is the same number under a swapped division, so a
    // geometry where two of the three agreed would hide it.
    const SetAssociativeArray l1(m, 65536, 8);
    CHECK_EQ(l1.num_sets(),      std::int64_t{32});
    CHECK_EQ(l1.associativity(), std::int32_t{8});
    CHECK_EQ(l1.num_slots(),     std::int32_t{256});
    CHECK_EQ(l1.num_slots(), static_cast<std::int32_t>(l1.num_sets() * l1.associativity()));

    // K2, an L2: 512 KB is 2048 lines, 16 ways deep is 128 sets.
    const SetAssociativeArray l2(m, 524288, 16);
    CHECK_EQ(l2.num_sets(),      std::int64_t{128});
    CHECK_EQ(l2.associativity(), std::int32_t{16});
    CHECK_EQ(l2.num_slots(),     std::int32_t{2048});
    CHECK_EQ(l2.num_slots(), static_cast<std::int32_t>(l2.num_sets() * l2.associativity()));
}

void test_the_direct_mapped_and_fully_associative_ends() {
    check::group("A4b K3, K4: associativity 1 and associativity == total_lines");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // K3, the direct-mapped case set_associative.h calls out by name: one way
    // per set, so the set count and the slot count coincide and the
    // associativity is the only thing that says which is which.
    const SetAssociativeArray direct(m, 4096, 1);
    CHECK_EQ(direct.num_sets(),      std::int64_t{16});
    CHECK_EQ(direct.associativity(), std::int32_t{1});
    CHECK_EQ(direct.num_slots(),     std::int32_t{16});

    // K4, the other end: every line in one set. This is the case that pins the
    // `associativity > total_lines` bound as a strict `>`: at assoc ==
    // total_lines the geometry is legal, so a `>=` there would refuse a fully
    // associative cache, which is a configuration the sweep grid contains.
    const SetAssociativeArray full(m, 4096, 16);
    CHECK_EQ(full.num_sets(),      std::int64_t{1});
    CHECK_EQ(full.associativity(), std::int32_t{16});
    CHECK_EQ(full.num_slots(),     std::int32_t{16});

    // And the degenerate corner where all three are 1, which is where an
    // implementation that multiplied somewhere it should divide still looks
    // right. It is here so the two cases above are not the only evidence.
    const SetAssociativeArray one(m, 256, 1);
    CHECK_EQ(one.num_sets(),      std::int64_t{1});
    CHECK_EQ(one.associativity(), std::int32_t{1});
    CHECK_EQ(one.num_slots(),     std::int32_t{1});
}

void test_one_mapper_serves_several_arrays() {
    check::group("A4b: one mapper, several arrays, held by reference");

    // layout.h's promise that one mapper instance serves the whole hierarchy,
    // which is why the array holds it by reference rather than copying a set
    // count out of it. Two arrays of different geometry built from one const
    // mapper, both still correct afterwards: an array that mutated the mapper,
    // or cached something on it, shows up as the second construction changing
    // the first's answers.
    const BlockPackMapper m(kShape, 16, 16, 1);

    const SetAssociativeArray a(m, 65536, 8);
    const SetAssociativeArray b(m, 4096, 4);

    CHECK_EQ(a.num_sets(),  std::int64_t{32});
    CHECK_EQ(b.num_sets(),  std::int64_t{4});
    CHECK_EQ(a.num_slots(), std::int32_t{256});
    CHECK_EQ(b.num_slots(), std::int32_t{16});
    CHECK_EQ(m.line_size_bytes(), kLine);
}

void test_the_line_size_is_read_exactly_once() {
    check::group("A4b: the mapper's line size is read once, not per check");

    // set_associative.cpp states this as load-bearing: line_size_bytes() is a
    // VIRTUAL call whose answer the constructor divides by twice, and a mapper
    // free to compute it per call is a mapper free to answer differently at the
    // byte check than at the line count. Nothing else in the suite can see it,
    // because a mapper that answers consistently gives the same geometry either
    // way; only the call count distinguishes them.
    TinyMapper counted(kLine);
    CHECK_EQ(counted.reads(), 0);

    const SetAssociativeArray a(counted, 65536, 8);
    CHECK_EQ(counted.reads(), 1);
    CHECK_EQ(a.num_sets(), std::int64_t{32});

    // The refusal path, where the line size is used three times over: the
    // exactness test, the "-byte lines" half of the message, and the terms in
    // brackets. Still one read, because the first two use the value the
    // constructor already holds and the third is the mapper's own override.
    TermsMapper refused(96);
    (void)thrown_by([&] { SetAssociativeArray bad(refused, 65536, 8); });
    CHECK_EQ(refused.reads(), 1);

    // The mapper that does NOT override the terms, which is where the defect
    // used to be. layout.h's inline default was
    // `std::to_string(line_size_bytes())`, so it asked the mapper a SECOND
    // time from inside the message and this check read 2.
    //
    // Q3 gave line_size_terms the line size as an argument, so the default
    // prints the value the constructor already read and the whole refusal comes
    // from ONE read. This is the check that says the fix landed, and it is why
    // the previous round's finding is no longer recorded as a live cost.
    TinyMapper defaulted(96);
    (void)thrown_by([&] { SetAssociativeArray bad(defaulted, 65536, 8); });
    CHECK_EQ(defaulted.reads(), 1);
}

void test_the_refusal_message_cannot_contradict_itself() {
    check::group("A4b Q3: both halves of the refusal come from one read");

    // The behaviour the read count above stands in for, measured directly. A
    // count of 1 is evidence only if a second read would actually change the
    // message, so this is the mapper for which it would: it answers 96, then
    // 97, then 98, and it does not override line_size_terms.
    //
    // With one read, the "-byte lines" half and the bracketed half are the same
    // number. With two, they were 96 and 97 and the message told a reader to go
    // looking for a 97-byte line that no configuration produces.
    DriftingLineSize drifting;
    const std::string msg = thrown_by([&] { SetAssociativeArray a(drifting, 65536, 8); });
    CHECK_TRUE(msg == "SetAssociativeArray: cache_size_bytes 65536 is not a whole number of "
                      "96-byte lines (96)");
}

void test_the_array_is_usable_through_the_base() {
    check::group("A4b: the array answers through CacheArray");

    // The engine owns levels through CacheArray, so num_slots has to arrive
    // that way. num_sets and associativity deliberately do NOT: a fully
    // associative array has no meaningful set count, and putting them on the
    // interface would invite a policy to read them, which is plan 2.2's
    // array/policy split leaking. That half is a compile_fail.sh case; this is
    // the half that must work.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const SetAssociativeArray a(m, 65536, 8);

    const CacheArray& r = a;
    CHECK_EQ(r.num_slots(), std::int32_t{256});

    // And deleted through a base pointer, which is what the engine does. A
    // non-virtual base destructor here leaks the slot vector for the whole
    // sweep and nothing says so.
    CacheArray* p = new SetAssociativeArray(m, 4096, 4);
    CHECK_EQ(p->num_slots(), std::int32_t{16});
    delete p;
}

// ===========================================================================
// Group L: the seven refusals
// ===========================================================================
//
// Every one of them is a `throw` rather than an `assert` precisely so it
// survives -DNDEBUG, and this whole file therefore runs in both build modes
// (TEST_DESIGN_CACHE.md section 2). `make MODE=release test` is not optional
// here: it is the build the sweep runs in.

void test_the_three_positivity_refusals() {
    check::group("A4b L1, L2, L3: a non-positive size, associativity or line size");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // L1. The boundary, not the sign: 0 is the value a config loader that
    // forgot a field actually produces, and a check written `< 0` agrees with
    // `< 1` on every negative and disagrees only there.
    expect_message("size 0", thrown_by([&] { SetAssociativeArray a(m, 0, 8); }),
                   kPrefix, {"cache_size_bytes", "must be >= 1", "got 0"});
    expect_message("size negative", thrown_by([&] { SetAssociativeArray a(m, -256, 8); }),
                   kPrefix, {"cache_size_bytes", "must be >= 1", "got -256"});

    // L2.
    expect_message("associativity 0", thrown_by([&] { SetAssociativeArray a(m, 65536, 0); }),
                   kPrefix, {"associativity", "must be >= 1", "got 0"});
    expect_message("associativity negative", thrown_by([&] { SetAssociativeArray a(m, 65536, -4); }),
                   kPrefix, {"associativity", "must be >= 1", "got -4"});

    // L3, which needs the stub mapper: a line size of 0 is a division by zero
    // one line later, and BlockPackMapper's own constructor refuses it long
    // before an array could see it, so no real mapper can reach this branch.
    const TinyMapper zero(0);
    expect_message("line size 0", thrown_by([&] { SetAssociativeArray a(zero, 65536, 8); }),
                   kPrefix, {"mapper line_size_bytes", "must be >= 1", "got 0"});
    const TinyMapper negative(-256);
    expect_message("line size negative", thrown_by([&] { SetAssociativeArray a(negative, 65536, 8); }),
                   kPrefix, {"mapper line_size_bytes", "must be >= 1", "got -256"});
}

void test_the_exactness_refusal_names_all_three_terms() {
    check::group("A4b L4: a size that is not a whole number of lines names the factors");

    // The plan's exit criterion for A4 ("non-exact size / (line x assoc)
    // throws"), and the A2b carried obligation to this unit: a non-power-of-two
    // line size is deliberately legal (B16), so "65536 is not a whole number of
    // 96-byte lines" is actionable only if the 96 can be traced back to the
    // config fields that produced it. cin_block 12 x cout_block 8 x
    // weight_bytes 1 is 96, and 65536 = 96 * 682 + 64.
    //
    // Refused rather than floored, because D2 echoes cache_size_bytes verbatim
    // into every results row: a silently floored geometry attributes the whole
    // sweep's hit rates to a capacity the simulator never had.
    const BlockPackMapper odd(kShape, 12, 8, 1);
    CHECK_EQ(odd.line_size_bytes(), std::int64_t{96});

    const std::string msg = thrown_by([&] { SetAssociativeArray a(odd, 65536, 8); });

    // Four separate needles, not one whole-string compare. The value, the line
    // size, and each of the three factors are five independently droppable
    // pieces, and a single equality check would report "the message changed"
    // for any of them without saying which.
    expect_message("the offending size", msg, kPrefix, {"cache_size_bytes 65536"});
    expect_message("the line size",      msg, kPrefix, {"96-byte lines"});
    expect_message("cin_block",          msg, kPrefix, {"cin_block 12"});
    expect_message("cout_block",         msg, kPrefix, {"cout_block 8"});
    expect_message("weight_bytes",       msg, kPrefix, {"weight_bytes 1"});

    // And the one thing the refusal must NOT be: a message that names only the
    // product is the message the obligation exists to replace, so the factors
    // being present is checked above and the whole message is checked here
    // against the exact text, which is what pins the punctuation the three
    // factors are joined with.
    CHECK_TRUE(msg == "SetAssociativeArray: cache_size_bytes 65536 is not a whole number of "
                      "96-byte lines (cin_block 12 x cout_block 8 x weight_bytes 1)");

    // The boundary. One byte either side of an exact multiple is refused, and
    // the exact multiple is accepted, so the check is a divisibility test
    // rather than a range.
    expect_message("one byte short", thrown_by([&] { SetAssociativeArray a(odd, 65472 - 1, 1); }),
                   kPrefix, {"is not a whole number of"});
    expect_message("one byte over",  thrown_by([&] { SetAssociativeArray a(odd, 65472 + 1, 1); }),
                   kPrefix, {"is not a whole number of"});
    const SetAssociativeArray exact(odd, 65472, 1);
    CHECK_EQ(exact.num_slots(), std::int32_t{682});
}

void test_the_inline_default_of_line_size_terms() {
    check::group("A4b: line_size_terms' inline default, for a mapper that does not override it");

    // layout.h gives line_size_terms an inline default rather than making it
    // pure virtual, because requiring it would oblige every AddressMapper in
    // the tree, including sixteen non-conforming test fakes and four
    // `subclass omits ...` reject cases, to implement a function about
    // diagnostics. The cost is that the default has to be correct if
    // uninformative, and TinyMapper is a mapper that does not override it.
    const TinyMapper plain(96);
    const std::string msg = thrown_by([&] { SetAssociativeArray a(plain, 65536, 8); });

    // Still well formed, still names the size and the line size, and the
    // parenthesised terms are the bare product rather than empty.
    expect_message("default terms", msg, kPrefix,
                   {"cache_size_bytes 65536", "96-byte lines", "(96)"});
    CHECK_TRUE(msg == "SetAssociativeArray: cache_size_bytes 65536 is not a whole number of "
                      "96-byte lines (96)");

    // The default is a fact about AddressMapper, not about the array, so it is
    // also checked where it is defined: an unoverridden line_size_terms is the
    // line size printed, for any line size.
    const TinyMapper other(7);
    CHECK_TRUE(other.line_size_terms(other.line_size_bytes()) == "7");
    const AddressMapper& base = other;
    CHECK_TRUE(base.line_size_terms(base.line_size_bytes()) == "7");

    // The default prints the value it is HANDED, which is Q3's whole point and
    // is what makes the two halves of one refusal agree by construction. A
    // caller that passes something else gets that something else back, so the
    // default can never disagree with the message it is being embedded in.
    CHECK_TRUE(base.line_size_terms(4096) == "4096");

    // And BlockPackMapper's override is reachable through the same base
    // reference, which is what makes it an override rather than a shadow. It
    // names its own factors, so it ignores the value it is passed.
    const BlockPackMapper packed(kShape, 12, 8, 1);
    const AddressMapper& pbase = packed;
    CHECK_TRUE(pbase.line_size_terms(pbase.line_size_bytes()) ==
               "cin_block 12 x cout_block 8 x weight_bytes 1");
    CHECK_TRUE(pbase.line_size_terms(-1) == "cin_block 12 x cout_block 8 x weight_bytes 1");

    // The default is a default, not a fixed answer: a mapper that overrides it
    // is what the array prints. Checked with a mapper other than
    // BlockPackMapper, so the property is about the virtual rather than about
    // the one class in the tree that happens to implement it.
    const TermsMapper overridden(96);
    CHECK_TRUE(thrown_by([&] { SetAssociativeArray a(overridden, 65536, 8); }) ==
               "SetAssociativeArray: cache_size_bytes 65536 is not a whole number of "
               "96-byte lines (a fixed string)");
}

void test_the_two_associativity_refusals_are_distinguishable() {
    check::group("A4b L5, L6, L7: assoc over the whole cache versus assoc that does not divide");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // L5. 64 KB of 256-byte lines is 256 lines; 512 ways is more cache than
    // exists.
    const std::string over = thrown_by([&] { SetAssociativeArray a(m, 65536, 512); });
    expect_message("assoc exceeds the cache", over, kPrefix,
                   {"associativity 512", "exceeds the whole cache of 256 lines"});

    // L6. Three ways into 256 lines does not divide, which is the likelier of
    // the two: a sweep grid crosses a power-of-two size with an associativity
    // that need not be one.
    const std::string ragged = thrown_by([&] { SetAssociativeArray a(m, 65536, 3); });
    expect_message("assoc does not divide", ragged, kPrefix,
                   {"256 lines do not divide evenly into sets of 3"});

    // L7, and it is the case that makes L5 and L6 two checks rather than one.
    // Both are "bad associativity" and an over-associative point fails the
    // divisibility test too, so an implementation that dropped either check
    // would still throw on both inputs. Only the text tells them apart.
    expect_absent("exceeds is not a divide message", over, "divide");
    expect_absent("divide is not an exceeds message", ragged, "exceeds");
}

void test_the_slot_bound_and_its_boundary() {
    check::group("A4b L8, L9: more lines than a SlotId can name, and the boundary");

    // Slot ids are exactly [0, num_slots) and SlotId's representation is int32,
    // so a geometry with more lines than that has upper slots no SlotId can
    // name: storage the sweep paid for and never used, visible only as a hit
    // rate a few points below the truth.
    //
    // A one-byte line, so cache_size_bytes IS the line count and the two
    // geometries below sit one apart.
    const BlockPackMapper byte_line(WeightShape{1, 1, 1, 1}, 1, 1, 1);
    CHECK_EQ(byte_line.line_size_bytes(), std::int64_t{1});

    // L8, over the bound: 2^32 lines.
    //
    // The associativity is 3, which does not divide 2^32, and that is chosen
    // rather than incidental. It makes the divisibility check a SECOND refusal
    // waiting behind this one, so a slot bound that stopped firing would still
    // throw -- and would throw a different message. The refusal is therefore
    // pinned by which message comes out, not merely by something coming out.
    const std::string over =
        thrown_by([&] { SetAssociativeArray a(byte_line, 4294967296LL, 3); });
    expect_message("over the slot bound", over, kPrefix,
                   {"4294967296 lines", "exceeds the 2147483647 slots a SlotId can name"});
    expect_absent("not a divide message", over, "divide");

    // L9, the boundary, and it is exact rather than approximate: at
    // total_lines == INT32_MAX the largest slot id is INT32_MAX - 1, one short
    // of NoSlot, so no valid slot can be mistaken for the sentinel. The bound
    // is therefore `>` and not `>=`.
    //
    // The accepted side cannot be constructed: INT32_MAX slots is a slot vector
    // of about 17 GB, which the constructor fills. So the boundary is pinned
    // the only way it can be, by the message: at exactly INT32_MAX the slot
    // bound does NOT fire, and the refusal that comes out is the divisibility
    // one. A `>=` there would produce the slots message instead. INT32_MAX is
    // odd, so associativity 2 is what makes a refusal arrive at all.
    const std::string at_bound =
        thrown_by([&] { SetAssociativeArray a(byte_line, 2147483647LL, 2); });
    expect_message("at the slot bound", at_bound, kPrefix,
                   {"2147483647 lines do not divide evenly into sets of 2"});
    expect_absent("the slot bound did not fire", at_bound, "SlotId can name");
}

void test_the_order_the_checks_run_in() {
    check::group("A4b: which refusal wins when a geometry is wrong twice");

    // set_associative.cpp states the order and calls it load-bearing, and
    // layout.h's tier vocabulary does not settle it, so these cases pin what
    // the code does rather than a rule anybody wrote. They are worth pinning
    // because a sweep grid takes a cross product: a point wrong in two ways is
    // the expected case, and which message it produces is what a reader acts on.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const TinyMapper zero_line(0);

    // Size before associativity.
    expect_message("size 0 beats associativity 0",
                   thrown_by([&] { SetAssociativeArray a(m, 0, 0); }),
                   kPrefix, {"cache_size_bytes", "got 0"});

    // Associativity before the line size, so the two positivity checks are
    // ordered rather than one check with two names.
    expect_message("associativity 0 beats line size 0",
                   thrown_by([&] { SetAssociativeArray a(zero_line, 65536, 0); }),
                   kPrefix, {"associativity", "got 0"});

    // The line size before the byte exactness, which is what stops a line size
    // of 0 from being a division by zero rather than a diagnosable refusal.
    expect_message("line size 0 beats exactness",
                   thrown_by([&] { SetAssociativeArray a(zero_line, 65535, 8); }),
                   kPrefix, {"mapper line_size_bytes", "got 0"});

    // Byte exactness before the associativity bound. 65535 is not a whole
    // number of 256-byte lines AND 512 ways is more cache than exists, and the
    // exactness message is the one that comes out.
    const std::string both = thrown_by([&] { SetAssociativeArray a(m, 65535, 512); });
    expect_message("exactness beats the associativity bound", both, kPrefix,
                   {"is not a whole number of"});
    expect_absent("and not the other way round", both, "exceeds the whole cache");

    // The associativity bound before the divides-into-sets check, which is the
    // one place in this constructor where the order buys nothing but a better
    // message: 3 lines with 512 ways fails both, and "3 lines do not divide
    // evenly into sets of 512" describes a rounding problem rather than a cache
    // too small to hold one set.
    const std::string tiny = thrown_by([&] { SetAssociativeArray a(m, 768, 512); });
    expect_message("the bound beats the divide", tiny, kPrefix,
                   {"associativity 512", "exceeds the whole cache of 3 lines"});
    expect_absent("and not the other way round", tiny, "divide");
}

void test_every_refusal_is_invalid_argument() {
    check::group("A4b: every refusal is invalid_argument, per B27's tiers");

    // B18's convention, carried to this class: a construction failure is
    // invalid_argument because the argument is malformed regardless of layer,
    // out_of_range is reserved for a well-formed argument outside THIS layer,
    // and logic_error is programmer error including a stub. The catch site has
    // to be able to tell a bad configuration from a bad access, which is why
    // the type is part of the contract and not an implementation detail.
    //
    // CHECK_THROWS names the type it wants, and invalid_argument is the
    // narrowest of the three: catching logic_error here would pass for an
    // invalid_argument as well and would prove nothing.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const BlockPackMapper odd(kShape, 12, 8, 1);
    const TinyMapper zero(0);
    const BlockPackMapper byte_line(WeightShape{1, 1, 1, 1}, 1, 1, 1);

    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(m, 0, 8));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(m, 65536, 0));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(zero, 65536, 8));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(odd, 65536, 8));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(byte_line, 4294967296LL, 3));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(m, 65536, 512));
    CHECK_THROWS(std::invalid_argument, SetAssociativeArray(m, 65536, 3));
}

// ===========================================================================
// A4c: the five verbs
// ===========================================================================
//
// One geometry carries most of the groups and is named here rather than
// rebuilt per test: 64 KB of 256-byte lines is 256 lines, 8 ways deep is 32
// sets. All three numbers differ, which is what stops a wrong answer from
// coinciding with a right one.

constexpr std::int64_t kBytes = 65536;
constexpr std::int32_t kWays  = 8;
constexpr std::int64_t kSets  = 32;
constexpr std::int32_t kSlots = 256;

// The mapper admits 9216 lines. A snapshot over 512 of them visits every set
// sixteen times, so the other 8704 buy repetition rather than coverage.
constexpr std::int64_t kSnapLines = 512;

// One draw from the test's RNG, in [0, n). mt19937's result_type is
// uint_fast32_t, which is 64 bits on this platform, so every draw narrows
// explicitly rather than through an implicit conversion -Wconversion would
// rightly complain about.
std::int64_t draw(std::mt19937& rng, std::int64_t n) {
    return static_cast<std::int64_t>(rng() % static_cast<std::mt19937::result_type>(n));
}

// The set `line` competes in, asked of the mapper rather than recomputed here.
// TEST_DESIGN_CACHE.md section 3's rule: `locate` is shared between the model
// and the code, so nothing below re-derives the line-to-set map. Group I tests
// `locate` standing alone; what is tested here is everything the array builds
// on top of it.
std::int64_t set_of(const AddressMapper& m, std::int64_t num_sets, std::int64_t line) {
    return m.locate(LineId{line}, num_sets).set_index.get();
}

// ---------------------------------------------------------------------------
// Group M: probe
// ---------------------------------------------------------------------------

void test_probe_finds_a_line_only_where_it_lives() {
    check::group("A4c M1..M5: probe hit, miss, repeatability, and its scoping");

    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);

    // M1. A fresh array holds nothing, across many sets rather than one.
    for (std::int64_t l = 0; l < 64; ++l) CHECK_EQ(a.probe(LineId{l}), NoSlot);

    // M2. Insert, then probe answers with the slot that was inserted into.
    const SlotId s = a.free_slot(LineId{7});
    CHECK_TRUE(s != NoSlot);
    CHECK_TRUE(!a.insert(LineId{7}, s).evicted);
    CHECK_EQ(a.probe(LineId{7}), s);

    // M3. Repeatable: ten consecutive calls, no drift.
    for (int i = 0; i < 10; ++i) CHECK_EQ(a.probe(LineId{7}), s);

    // M4. A different line in the SAME set is still a miss, and specifically is
    // not reported at the neighbour's slot. This is the case that catches a
    // probe comparing against something other than the line id: 7 and 7 + kSets
    // land in one set and differ only in the tag half.
    CHECK_EQ(set_of(m, kSets, 7), set_of(m, kSets, 7 + kSets));
    CHECK_EQ(a.probe(LineId{7 + kSets}), NoSlot);

    // M5. A line in a DIFFERENT set is a miss too, which catches a probe that
    // forgot to scope itself to the set and scanned the whole array.
    CHECK_TRUE(set_of(m, kSets, 8) != set_of(m, kSets, 7));
    CHECK_EQ(a.probe(LineId{8}), NoSlot);

    // And through the base, which is the only way the engine reaches it.
    const CacheArray& r = a;
    CHECK_EQ(r.probe(LineId{7}), s);
    CHECK_EQ(r.probe(LineId{8}), NoSlot);
}

void test_probe_is_not_an_access() {
    check::group("A4c M6: no sequence of probes changes any later answer");

    // Plan 2.2 requires that "probe is const and is NOT an access", and the
    // class makes that enforceable rather than promised: probe is const and
    // SetAssociativeArray has no mutable member for a const function to write.
    // What is checked here is the consequence a caller actually depends on, and
    // it is checked as an invariance rather than as a value.
    //
    // Two arrays are built and filled in lockstep. One is then probed twenty
    // thousand times -- hits, misses and repeats, over every line the mapper
    // admits -- and the other is not. Afterwards the storm's array agrees with
    // its own pre-storm snapshot AND with the array that never saw the storm.
    //
    // The second array is what a before/after snapshot alone cannot supply. A
    // probe that recorded something only a LATER verb reads back would still
    // pass a before/after comparison on one array; it shows up only against an
    // array with a different probe history. Note that taking a snapshot is
    // itself probing, which is the point rather than a flaw: reading this
    // array's state costs probes, so "unprobed" is not a state a test can be
    // in, and what is being pinned is that the NUMBER and ORDER of probes does
    // not matter.
    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray stormed(m, kBytes, kWays);
    SetAssociativeArray untouched(m, kBytes, kWays);

    // Partly filled, so free ways, occupied ways and full sets are all present:
    // lines 0..199 over 32 sets leave every set six or seven deep of eight.
    for (std::int64_t l = 0; l < 200; ++l) {
        const SlotId f = stormed.free_slot(LineId{l});
        CHECK_TRUE(f != NoSlot);
        (void)stormed.insert(LineId{l}, f);
        (void)untouched.insert(LineId{l}, f);
    }
    // And one set driven to full, so the storm covers the exhausted case too.
    for (std::int64_t ln = 200; ln < 200 + kSets * 3; ln += kSets) {
        const SlotId f = stormed.free_slot(LineId{ln});
        if (f == NoSlot) break;
        (void)stormed.insert(LineId{ln}, f);
        (void)untouched.insert(LineId{ln}, f);
    }

    const std::vector<std::int64_t> before = observables(stormed, kSnapLines);

    const std::int64_t lines = m.num_lines().get();
    std::mt19937 rng(20260818u);
    for (int i = 0; i < 20000; ++i) {
        const std::int64_t l = draw(rng, lines);
        (void)stormed.probe(LineId{l});
        (void)stormed.probe(LineId{l});  // the repeat, which is what a recency stack would record
    }

    expect_same_observables("the storm changed nothing",
                            before, observables(stormed, kSnapLines));
    expect_same_observables("and the two arrays still agree",
                            observables(untouched, kSnapLines), observables(stormed, kSnapLines));

    // The same statement about free_slot and victim_candidates, which are const
    // for the same reason and are already inside `observables` above. This is
    // the one that says so out loud: the two arrays diverge in nothing but how
    // many const calls they have served.
    CHECK_EQ(stormed.free_slot(LineId{0}), untouched.free_slot(LineId{0}));
}

// ---------------------------------------------------------------------------
// Group N: free_slot
// ---------------------------------------------------------------------------

void test_free_slot_is_the_lowest_free_way() {
    check::group("A4c N1..N5: the lowest free way, exhaustion, and neighbouring sets");

    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);

    // N1, N2. One set, filled a way at a time, and the answer climbs by exactly
    // one each time. That ordering is load-bearing rather than tidy: it is what
    // makes the answer a function of the array's state alone, so two arrays
    // given the same insert sequence agree slot for slot. An implementation
    // free to return any free way would still be correct and would make every
    // fixture below it unwritable.
    const std::int32_t base = static_cast<std::int32_t>(set_of(m, kSets, 5)) * kWays;
    for (std::int32_t w = 0; w < kWays; ++w) {
        const SlotId f = a.free_slot(LineId{5});
        CHECK_EQ(f, SlotId{base + w});
        (void)a.insert(LineId{5 + kSets * w}, f);
    }

    // N3. The set is full and free_slot says so rather than picking a victim.
    CHECK_EQ(a.free_slot(LineId{5}), NoSlot);

    // N4. A full set does not starve a different one, which is what catches a
    // free_slot that scanned the whole array instead of one set.
    const SlotId other = a.free_slot(LineId{6});
    CHECK_TRUE(other != NoSlot);
    CHECK_EQ(other, SlotId{static_cast<std::int32_t>(set_of(m, kSets, 6)) * kWays});

    // N5. An insert OVER an occupied way leaves the set full: replacing is not
    // freeing, so the exhaustion answer does not change.
    const InsertResult r = a.insert(LineId{5 + kSets * kWays}, SlotId{base});
    CHECK_TRUE(r.evicted);
    CHECK_EQ(a.free_slot(LineId{5}), NoSlot);
}

void test_free_slot_is_deterministic_across_arrays() {
    check::group("A4c N6: two arrays, one insert sequence, identical slots throughout");

    // The property N2's ordering exists to buy, stated at the level a sweep
    // depends on: a cold-start fill is reproducible, so two runs of the same
    // configuration place lines identically and a hit rate is a fact about the
    // trace rather than about the run.
    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);
    SetAssociativeArray b(m, kBytes, kWays);

    std::mt19937 rng(7u);
    for (int i = 0; i < 2000; ++i) {
        const std::int64_t l = draw(rng, 400);
        const SlotId fa = a.free_slot(LineId{l});
        const SlotId fb = b.free_slot(LineId{l});
        CHECK_EQ(fa, fb);
        if (fa == NoSlot) continue;
        const InsertResult ra = a.insert(LineId{l}, fa);
        const InsertResult rb = b.insert(LineId{l}, fb);
        CHECK_EQ(ra.evicted_line, rb.evicted_line);
    }
    expect_same_observables("the two arrays are the same array",
                            observables(a, kSnapLines), observables(b, kSnapLines));
}

// ---------------------------------------------------------------------------
// Group O: victim_candidates
// ---------------------------------------------------------------------------

void test_victim_candidates_reports_one_whole_set() {
    check::group("A4c O1..O8: the candidate list is one whole set, in slot order");

    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);

    // O2, and TEST_DESIGN_CACHE.md calls it the single most valuable case in
    // the group: the verb REPLACES the buffer's contents. An appending version
    // lets a caller that forgot to clear pick a victim from a previous fill in
    // a DIFFERENT set, and the line is then stored where probe can never look
    // for it. No crash, just a hit rate quietly below the truth for a whole run.
    std::vector<Candidate> out(7, Candidate{SlotId{99}, LineId{99}});
    a.victim_candidates(LineId{5}, out);
    CHECK_EQ(check::ssize(out), std::int64_t{kWays});  // O1, at fill level zero

    // O4, O7. A fresh set: every way free, carrying NoLine, in ascending slot
    // order starting at the set's base.
    const std::int32_t base = static_cast<std::int32_t>(set_of(m, kSets, 5)) * kWays;
    for (std::int32_t w = 0; w < kWays; ++w) {
        CHECK_EQ(out[static_cast<std::size_t>(w)].slot, SlotId{base + w});
        CHECK_EQ(out[static_cast<std::size_t>(w)].line, NoLine);
    }

    // O1, O4, O5. Partly filled: the size does not change with the fill level,
    // the occupied ways carry the line that is actually resident, and the free
    // ways still carry NoLine.
    (void)a.insert(LineId{5}, SlotId{base});
    (void)a.insert(LineId{5 + kSets * 2}, SlotId{base + 2});
    a.victim_candidates(LineId{5}, out);
    CHECK_EQ(check::ssize(out), std::int64_t{kWays});
    CHECK_EQ(out[0].line, LineId{5});
    CHECK_EQ(out[1].line, NoLine);
    CHECK_EQ(out[2].line, LineId{5 + kSets * 2});
    for (std::size_t w = 3; w < out.size(); ++w) CHECK_EQ(out[w].line, NoLine);

    // O6. Every entry that carries a line is where probe finds that line, which
    // is what ties the candidate list to the rest of the interface rather than
    // leaving it a private report.
    for (const Candidate& c : out) {
        if (c.line == NoLine) continue;
        CHECK_EQ(a.probe(c.line), c.slot);
    }

    // O3. Called twice in a row, the second answer equals the first.
    std::vector<Candidate> again;
    a.victim_candidates(LineId{5}, again);
    CHECK_EQ(check::ssize(again), check::ssize(out));
    bool identical = true;
    for (std::size_t i = 0; i < out.size(); ++i)
        identical = identical && again[i].slot == out[i].slot && again[i].line == out[i].line;
    CHECK_TRUE(identical);

    // O8. The buffer converges: after the first call has grown it, calls 2..10
    // do not reallocate. That is the local, testable half of the buffer-reuse
    // argument, and it is what makes clearing rather than shrinking the right
    // way to replace the contents.
    a.victim_candidates(LineId{5}, again);
    const std::size_t settled = again.capacity();
    for (int i = 0; i < 9; ++i) {
        a.victim_candidates(LineId{5 + i}, again);
        CHECK_EQ(static_cast<std::int64_t>(again.capacity()),
                 static_cast<std::int64_t>(settled));
    }

    // O9. And the whole verb is const in effect as well as in signature.
    const std::vector<std::int64_t> before = observables(a, kSnapLines);
    for (std::int64_t l = 0; l < 300; ++l) a.victim_candidates(LineId{l}, again);
    expect_same_observables("candidates leave the array alone",
                            before, observables(a, kSnapLines));
}

void test_victim_candidates_leaves_the_buffer_alone_when_it_throws() {
    check::group("A4c: a throwing victim_candidates does not empty the caller's buffer");

    // base_slot is the only thing in the verb that can throw, and it runs
    // BEFORE out.clear(). That order is the contract rather than an accident:
    // a caller that hands over a buffer and gets an exception must get the
    // buffer back as it was, not emptied. It is the same rule expand states as
    // "every range check runs before the first append", applied to a verb that
    // assigns instead of appending.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const SetAssociativeArray a(m, kBytes, kWays);

    const std::vector<Candidate> junk(7, Candidate{SlotId{99}, LineId{99}});
    std::vector<Candidate> out = junk;

    const std::int64_t past_the_end = m.num_lines().get();
    expect_message("a line the mapper does not have",
                   range_thrown_by([&] { a.victim_candidates(LineId{past_the_end}, out); }),
                   "BlockPackMapper: line id out of range",
                   {"got 9216"});

    CHECK_EQ(check::ssize(out), std::int64_t{7});
    bool untouched = true;
    for (std::size_t i = 0; i < out.size(); ++i)
        untouched = untouched && out[i].slot == junk[i].slot && out[i].line == junk[i].line;
    CHECK_TRUE(untouched);

    // The other two const verbs refuse the same line the same way. They add no
    // rejection of their own, so what is pinned is that the refusal arrives at
    // all rather than a negative set index being formed and indexed with.
    expect_message("probe refuses it too",
                   range_thrown_by([&] { (void)a.probe(LineId{past_the_end}); }),
                   "BlockPackMapper: line id out of range", {});
    expect_message("free_slot refuses it too",
                   range_thrown_by([&] { (void)a.free_slot(LineId{past_the_end}); }),
                   "BlockPackMapper: line id out of range", {});
    expect_message("and a negative line",
                   range_thrown_by([&] { (void)a.probe(LineId{-1}); }),
                   "BlockPackMapper: line id out of range", {"got -1"});
}

// ---------------------------------------------------------------------------
// Group P: insert, and invalidate alongside it
// ---------------------------------------------------------------------------

void test_insert_reports_what_it_displaced() {
    check::group("A4c P1..P7: eviction reporting, and what an insert leaves alone");

    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);
    const std::int32_t base = static_cast<std::int32_t>(set_of(m, kSets, 5)) * kWays;

    // P1. Into a free slot: nothing was displaced, and both fields say so.
    const InsertResult cold = a.insert(LineId{5}, SlotId{base});
    CHECK_TRUE(!cold.evicted);
    CHECK_EQ(cold.evicted_line, NoLine);
    CHECK_EQ(a.probe(LineId{5}), SlotId{base});  // P4

    // Fill two more ways, so the untouched-neighbour checks below have
    // something to be untouched.
    (void)a.insert(LineId{5 + kSets}, SlotId{base + 1});
    (void)a.insert(LineId{5 + kSets * 2}, SlotId{base + 2});

    const std::vector<std::int64_t> other_sets_before = observables(a, kSnapLines);

    // P2. Into an occupied slot: the previous occupant is named, not the line
    // being installed and not merely a flag.
    const InsertResult hot = a.insert(LineId{5 + kSets * 3}, SlotId{base});
    CHECK_TRUE(hot.evicted);
    CHECK_EQ(hot.evicted_line, LineId{5});

    // P3, at this call. The invariant is checked over the whole replay in group
    // R as well; here it is checked where the two fields are actually written.
    CHECK_EQ(hot.evicted, hot.evicted_line != NoLine);
    CHECK_EQ(cold.evicted, cold.evicted_line != NoLine);

    // P4, P5. The new line is where the insert put it and the old one is gone.
    CHECK_EQ(a.probe(LineId{5 + kSets * 3}), SlotId{base});
    CHECK_EQ(a.probe(LineId{5}), NoSlot);

    // P6. The other ways of the same set are untouched, which is what catches
    // an insert that wrote to the wrong way or cleared the set on the way in.
    CHECK_EQ(a.probe(LineId{5 + kSets}), SlotId{base + 1});
    CHECK_EQ(a.probe(LineId{5 + kSets * 2}), SlotId{base + 2});

    // P7. And no other set moved. `observables` covers every set sixteen times
    // over, so this is the whole array minus the two answers that were supposed
    // to change, checked by replaying the same eviction on a second array.
    SetAssociativeArray replay(m, kBytes, kWays);
    (void)replay.insert(LineId{5}, SlotId{base});
    (void)replay.insert(LineId{5 + kSets}, SlotId{base + 1});
    (void)replay.insert(LineId{5 + kSets * 2}, SlotId{base + 2});
    expect_same_observables("the second array matched before the eviction",
                            other_sets_before, observables(replay, kSnapLines));
    (void)replay.insert(LineId{5 + kSets * 3}, SlotId{base});
    expect_same_observables("and matches after it",
                            observables(a, kSnapLines), observables(replay, kSnapLines));
}

void test_invalidate_frees_a_slot_and_is_idempotent() {
    check::group("A4c: invalidate, including on a slot that is already free");

    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);
    const std::int32_t base = static_cast<std::int32_t>(set_of(m, kSets, 5)) * kWays;

    // A full set, so the effect of freeing one way is unambiguous.
    for (std::int32_t w = 0; w < kWays; ++w) (void)a.insert(LineId{5 + kSets * w}, SlotId{base + w});
    CHECK_EQ(a.free_slot(LineId{5}), NoSlot);

    // Invalidating a resident slot drops the line: probe stops finding it, the
    // slot becomes the lowest free way of its set, and the candidate list
    // reports it as free rather than as still holding the departed line.
    a.invalidate(SlotId{base + 3});
    CHECK_EQ(a.probe(LineId{5 + kSets * 3}), NoSlot);
    CHECK_EQ(a.free_slot(LineId{5}), SlotId{base + 3});
    std::vector<Candidate> out;
    a.victim_candidates(LineId{5}, out);
    CHECK_EQ(out[3].line, NoLine);
    CHECK_EQ(out[3].slot, SlotId{base + 3});

    // The rest of the set is untouched, which is what catches an invalidate
    // that cleared the set rather than the way.
    for (std::int32_t w = 0; w < kWays; ++w) {
        if (w == 3) continue;
        CHECK_EQ(a.probe(LineId{5 + kSets * w}), SlotId{base + w});
    }

    // Invalidating an ALREADY FREE slot leaves it free and changes nothing
    // else. cache.h states this outright, and the implementation needs no
    // branch for it, which is exactly why it is worth a check: there is nothing
    // in the code to read that says the case was considered.
    const std::vector<std::int64_t> before = observables(a, kSnapLines);
    a.invalidate(SlotId{base + 3});
    a.invalidate(SlotId{base + 3});
    expect_same_observables("invalidate on a free slot is a no-op", before,
                            observables(a, kSnapLines));

    // And a slot in a set nobody has touched, which is the same case one step
    // further out: every slot of the array starts free.
    a.invalidate(SlotId{kSlots - 1});
    expect_same_observables("including in an untouched set", before,
                            observables(a, kSnapLines));
}

void test_the_two_verbs_that_take_a_slot_range_check_it() {
    check::group("A4c: insert and invalidate refuse a slot outside [0, num_slots)");

    // The slot is range-checked and the line is not, which cache.h calls a
    // deliberate asymmetry: an out-of-range slot is an out-of-bounds WRITE into
    // the slot vector, and it is reachable by one plausible mistake, since
    // `insert(line, free_slot(line))` without testing for NoSlot passes
    // INT32_MAX here. A line outside the mapper's range is a stored value that
    // every reader refuses at locate.
    const BlockPackMapper m(kShape, 16, 16, 1);
    SetAssociativeArray a(m, kBytes, kWays);
    CHECK_EQ(a.num_slots(), kSlots);

    expect_message("insert at -1",
                   range_thrown_by([&] { (void)a.insert(LineId{0}, SlotId{-1}); }),
                   "SetAssociativeArray::insert",
                   {"slot -1", "outside [0, 256)"});
    expect_message("insert one past the end",
                   range_thrown_by([&] { (void)a.insert(LineId{0}, SlotId{kSlots}); }),
                   "SetAssociativeArray::insert",
                   {"slot 256", "outside [0, 256)"});
    // The mistake the check exists for, spelled out: a caller that passed the
    // NoSlot it was handed rather than testing for it.
    expect_message("insert at NoSlot",
                   range_thrown_by([&] { (void)a.insert(LineId{0}, NoSlot); }),
                   "SetAssociativeArray::insert", {"2147483647"});

    expect_message("invalidate at -1",
                   range_thrown_by([&] { a.invalidate(SlotId{-1}); }),
                   "SetAssociativeArray::invalidate",
                   {"slot -1", "outside [0, 256)"});
    expect_message("invalidate one past the end",
                   range_thrown_by([&] { a.invalidate(SlotId{kSlots}); }),
                   "SetAssociativeArray::invalidate",
                   {"slot 256", "outside [0, 256)"});
    expect_message("invalidate at NoSlot",
                   range_thrown_by([&] { a.invalidate(NoSlot); }),
                   "SetAssociativeArray::invalidate", {"2147483647"});

    // Each message names ITS OWN verb, which is the reason the shared check
    // takes the name rather than reporting the class: a caller with a stray
    // slot id needs to know which call it reached.
    expect_absent("insert is not an invalidate message",
                  range_thrown_by([&] { (void)a.insert(LineId{0}, SlotId{-1}); }), "invalidate");

    // The boundary is open at the top and closed at the bottom, so the last
    // slot is accepted and nothing was written by any of the refusals above.
    const InsertResult r = a.insert(LineId{kSlots - 1}, SlotId{kSlots - 1});
    CHECK_TRUE(!r.evicted);
    a.invalidate(SlotId{0});
    a.invalidate(SlotId{kSlots - 1});
    CHECK_EQ(a.probe(LineId{kSlots - 1}), NoSlot);
}

// ---------------------------------------------------------------------------
// Group Q: capacity and conflict
// ---------------------------------------------------------------------------

void test_capacity_and_conflict() {
    check::group("A4c Q1, Q2, Q3: one eviction per set overflow, reuse, and assoc 1");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // Q1. associativity + 1 distinct lines into one set costs exactly one
    // eviction. A set that evicted early is a cache reporting a capacity it
    // does not have; one that evicted late has written outside its set.
    SetAssociativeArray a(m, kBytes, kWays);
    int evictions = 0;
    for (std::int32_t w = 0; w <= kWays; ++w) {
        const LineId line{5 + kSets * w};
        SlotId s = a.free_slot(line);
        if (s == NoSlot) {
            std::vector<Candidate> out;
            a.victim_candidates(line, out);
            s = out[0].slot;  // a stand-in policy; it only has to be legal
        }
        if (a.insert(line, s).evicted) ++evictions;
    }
    CHECK_EQ(evictions, 1);

    // Q2. A working set smaller than one set, replayed: one miss per line, then
    // all hits. This is the property a hit rate is made of, so an off-by-one in
    // the way scan shows up here as a stream of misses rather than as a number
    // slightly wrong.
    SetAssociativeArray b(m, kBytes, kWays);
    int misses = 0;
    for (int pass = 0; pass < 5; ++pass) {
        for (std::int32_t w = 0; w < kWays; ++w) {
            const LineId line{5 + kSets * w};
            if (b.probe(line) != NoSlot) continue;
            ++misses;
            (void)b.insert(line, b.free_slot(line));
        }
    }
    CHECK_EQ(misses, static_cast<int>(kWays));

    // Q3. Direct-mapped, which is a real configuration and is the width at
    // which an off-by-one in the way loop stops being visible: two lines
    // num_sets apart evict each other every time.
    SetAssociativeArray d(m, 4096, 1);
    CHECK_EQ(d.num_sets(), std::int64_t{16});
    CHECK_EQ(d.associativity(), std::int32_t{1});
    const SlotId only = d.free_slot(LineId{3});
    CHECK_TRUE(only != NoSlot);
    CHECK_TRUE(!d.insert(LineId{3}, only).evicted);
    CHECK_EQ(d.free_slot(LineId{3}), NoSlot);
    CHECK_EQ(d.free_slot(LineId{19}), NoSlot);  // 3 + 16, the same set

    const InsertResult first = d.insert(LineId{19}, only);
    CHECK_TRUE(first.evicted);
    CHECK_EQ(first.evicted_line, LineId{3});
    const InsertResult second = d.insert(LineId{3}, only);
    CHECK_TRUE(second.evicted);
    CHECK_EQ(second.evicted_line, LineId{19});
}

// ---------------------------------------------------------------------------
// Group S: the slot numbering, which is white-box on purpose
// ---------------------------------------------------------------------------

void test_the_slot_numbering_is_a_partition_of_the_array() {
    check::group("A4c S1..S3, Q4, Q5: a set is exactly its ways, and the sets partition the slots");

    // Explicitly NOT a CacheArray contract test. cache.h says a fully
    // associative array will number slots differently while the same policies
    // keep working, so if such a class ever fails these that is correct
    // behaviour rather than a regression. What IS a contract test is the
    // partition half below: every slot reachable under exactly one set is what
    // makes "the storage the sweep paid for is the storage it used" checkable.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const SetAssociativeArray a(m, kBytes, kWays);

    std::vector<int> seen(static_cast<std::size_t>(kSlots), 0);
    std::vector<Candidate> out;
    bool s1 = true, s2 = true, ascending = true;

    for (std::int64_t s = 0; s < kSets; ++s) {
        // A line landing in set s. locate is `line % num_sets` for this mapper,
        // but the test asks rather than assumes.
        const LineId line{s};
        CHECK_EQ(set_of(m, kSets, s), s);

        a.victim_candidates(line, out);
        s1 = s1 && check::ssize(out) == std::int64_t{kWays};
        const std::int32_t base = static_cast<std::int32_t>(s) * kWays;
        for (std::int32_t w = 0; w < kWays; ++w) {
            const std::int32_t got = out[static_cast<std::size_t>(w)].slot.get();
            s1 = s1 && got == base + w;                        // S1
            if (w > 0) ascending = ascending && got > out[static_cast<std::size_t>(w - 1)].slot.get();
            ++seen[static_cast<std::size_t>(got)];             // Q4, Q5
        }
        // S2. probe and free_slot answer inside the same range. The array is
        // empty, so free_slot is the base and probe is NoSlot; the check is
        // that free_slot's answer belongs to this set and no other.
        const SlotId f = a.free_slot(line);
        s2 = s2 && f.get() >= base && f.get() < base + kWays;
    }
    CHECK_TRUE(s1);
    CHECK_TRUE(s2);
    CHECK_TRUE(ascending);  // O7, restated across every set

    // Q4 and Q5 together: every slot appears under exactly one set. A slot seen
    // twice is two sets sharing storage, a slot never seen is storage no line
    // can reach, and both show up only as a hit rate a few points from the
    // truth.
    int unreachable = 0, shared = 0;
    for (int n : seen) {
        if (n == 0) ++unreachable;
        if (n > 1) ++shared;
    }
    CHECK_EQ(unreachable, 0);
    CHECK_EQ(shared, 0);

    // S3, across the other geometries K3 and K4 covered, so density is a fact
    // about the class rather than about one associativity.
    const SetAssociativeArray direct(m, 4096, 1);
    const SetAssociativeArray full(m, 4096, 16);
    for (const SetAssociativeArray* p : {&direct, &full}) {
        std::vector<int> hit(static_cast<std::size_t>(p->num_slots()), 0);
        for (std::int64_t s = 0; s < p->num_sets(); ++s) {
            p->victim_candidates(LineId{s}, out);
            for (const Candidate& c : out) ++hit[static_cast<std::size_t>(c.slot.get())];
        }
        bool dense = true;
        for (int n : hit) dense = dense && n == 1;
        CHECK_TRUE(dense);
    }
}

// ---------------------------------------------------------------------------
// Group R: randomized replay against an independent model
// ---------------------------------------------------------------------------

// The model deliberately does NOT recompute slot ids. cache.h states that
// `set_index * associativity + way` is this class's private business and that a
// fully associative array will number slots differently while the same policies
// keep working, so a shadow model that recomputed slot ids that way would test
// the formula twice and the contract not at all.
//
// What it holds instead is, per set, the mapping from whatever slot the ARRAY
// handed back to the line the model believes is in it. Everything compared
// below is then a statement the interface actually makes.
struct Model {
    std::int64_t num_sets = 0;
    std::int32_t ways     = 0;
    // [set] -> the occupied (slot, line) pairs, at most `ways` of them.
    std::vector<std::vector<std::pair<std::int32_t, std::int64_t>>> sets;

    void reset(std::int64_t s, std::int32_t w) {
        num_sets = s;
        ways     = w;
        sets.assign(static_cast<std::size_t>(s), {});
    }
    std::vector<std::pair<std::int32_t, std::int64_t>>& at(std::int64_t s) {
        return sets[static_cast<std::size_t>(s)];
    }
};

// Counted rather than checked per access, so one mismatch is one FAIL line
// naming how many times it happened rather than tens of thousands of them. The
// counters are the check; the printed tally is what says the stream reached the
// path it claims to (F13's lesson, that a large case count can leave the
// interesting path nearly untouched).
struct Replay {
    long accesses = 0, hits = 0, misses = 0, evictions = 0, victim_needed = 0;
    long bad_residency = 0, bad_stability = 0, bad_eviction = 0, bad_exhaustion = 0,
         bad_candidate_count = 0, bad_insert_fields = 0;
};

Replay replay(const AddressMapper& m, SetAssociativeArray& a, int accesses, unsigned seed) {
    Model model;
    model.reset(a.num_sets(), a.associativity());
    Replay r;

    const std::int64_t lines = m.num_lines().get();
    const std::int64_t hot   = a.num_sets() * 2;  // a working set that actually fills sets
    std::vector<std::int64_t> recent;
    std::vector<Candidate> out;
    std::mt19937 rng(seed);

    for (int i = 0; i < accesses; ++i) {
        std::int64_t l;
        const std::int64_t pick = draw(rng, 3);
        if (pick == 0 || recent.empty()) {
            l = draw(rng, lines);
        } else if (pick == 1) {
            l = draw(rng, hot);
        } else {
            l = recent[static_cast<std::size_t>(draw(rng, check::ssize(recent)))];
        }
        recent.push_back(l);
        if (recent.size() > 32) recent.erase(recent.begin());

        const LineId line{l};
        const std::int64_t set = m.locate(line, a.num_sets()).set_index.get();
        auto& occupied = model.at(set);

        ++r.accesses;
        const SlotId found = a.probe(line);

        // Residency, against the model's membership.
        std::int32_t model_slot = NoSlot.get();
        for (const auto& entry : occupied)
            if (entry.second == l) model_slot = entry.first;
        if (found.get() != model_slot) ++r.bad_residency;

        if (found != NoSlot) {
            ++r.hits;
            // Stability: the same slot on a second call while resident.
            if (a.probe(line) != found) ++r.bad_stability;
            continue;
        }
        ++r.misses;

        // Exhaustion: free_slot answers NoSlot exactly when the model's set is
        // full, which is the one thing the array knows and the policy does not.
        const SlotId free = a.free_slot(line);
        const bool model_full = check::ssize(occupied) >= std::int64_t{model.ways};
        if ((free == NoSlot) != model_full) ++r.bad_exhaustion;

        SlotId target = free;
        if (free == NoSlot) {
            ++r.victim_needed;
            a.victim_candidates(line, out);
            if (check::ssize(out) != std::int64_t{model.ways}) ++r.bad_candidate_count;
            // The lowest-numbered slot, as a stand-in policy: A4c has none, and
            // the choice only has to be legal rather than smart.
            target = out[0].slot;
        }

        const InsertResult got = a.insert(line, target);

        // What the model says was in that slot.
        std::int64_t displaced = NoLine.get();
        for (auto& entry : occupied) {
            if (entry.first == target.get()) {
                displaced = entry.second;
                entry.second = l;
            }
        }
        if (displaced == NoLine.get()) occupied.push_back({target.get(), l});

        if (got.evicted_line.get() != displaced) ++r.bad_eviction;
        if (got.evicted != (got.evicted_line != NoLine)) ++r.bad_insert_fields;  // P3
        if (got.evicted) ++r.evictions;
    }
    return r;
}

void expect_clean_replay(const char* name, const Replay& r) {
    if (!check::g_quiet)
        std::printf("  %-22s %ld accesses, %ld hits, %ld misses, %ld evictions,"
                    " %.1f%% of misses needed a victim\n",
                    name, r.accesses, r.hits, r.misses, r.evictions,
                    r.misses == 0 ? 0.0 : 100.0 * static_cast<double>(r.victim_needed) /
                                              static_cast<double>(r.misses));
    CHECK_EQ(r.bad_residency, 0L);
    CHECK_EQ(r.bad_stability, 0L);
    CHECK_EQ(r.bad_exhaustion, 0L);
    CHECK_EQ(r.bad_candidate_count, 0L);
    CHECK_EQ(r.bad_eviction, 0L);
    CHECK_EQ(r.bad_insert_fields, 0L);
    // The stream has to reach the eviction path, or the group is not testing
    // what its name says. This is the check F13 would have wanted.
    CHECK_TRUE(r.victim_needed > r.misses / 10);
}

void test_the_replay_agrees_with_the_model() {
    check::group("A4c R: randomized replay against an independent model");

    const BlockPackMapper m(kShape, 16, 16, 1);

    // The small geometry first, because it is the one that stresses eviction:
    // 4 sets of 4 ways fill constantly, where a uniform stream over 32 sets
    // would barely fill one.
    SetAssociativeArray small(m, 4096, 4);
    expect_clean_replay("4 sets x 4 ways", replay(m, small, 20000, 11u));

    // And the plan's L1 geometry, which confirms nothing breaks at scale.
    SetAssociativeArray l1(m, kBytes, kWays);
    expect_clean_replay("32 sets x 8 ways", replay(m, l1, 20000, 12u));

    // Direct-mapped, where every miss into an occupied set is an eviction and
    // the way loop runs once.
    SetAssociativeArray direct(m, 4096, 1);
    expect_clean_replay("16 sets x 1 way", replay(m, direct, 20000, 13u));
}

// ===========================================================================
// Compile-time shape
// ===========================================================================

// `final` for B10's reason: a class deriving from this one would be inheriting
// the set-associative geometry in order to disagree with part of it, which is
// the shape that makes a bug in one override invisible in the others.
static_assert(std::is_final<SetAssociativeArray>::value, "");
static_assert(std::is_base_of<CacheArray, SetAssociativeArray>::value, "");
static_assert(!std::is_abstract<SetAssociativeArray>::value, "");

// The two accessors that are NOT on the interface stay off it, which is plan
// 2.2's array/policy split. A policy sizes its per-slot state from num_slots
// and must not be able to reach for a set count.
static_assert(std::is_same<decltype(std::declval<const SetAssociativeArray&>().num_sets()),
                           std::int64_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const SetAssociativeArray&>().associativity()),
                           std::int32_t>::value, "");
static_assert(std::is_same<decltype(std::declval<const SetAssociativeArray&>().num_slots()),
                           std::int32_t>::value, "");

// The constructor's widths: an int64 byte count because it is divided by an
// int64 line size, an int32 associativity because it multiplies into a slot
// count that is int32 because SlotId is.
static_assert(std::is_constructible<SetAssociativeArray, const AddressMapper&,
                                    std::int64_t, std::int32_t>::value, "");

// layout.h's new virtual is const and returns a string, so it can be called on
// the const mapper reference the array holds. Since Q3 it also TAKES the line
// size the caller read, and the whole signature is pinned rather than just the
// return type: the argument is the mechanism, so an arity that quietly went
// back to nought would take the read-once guarantee with it and every override
// in the tree would go on compiling as an unrelated overload.
static_assert(std::is_same<decltype(&AddressMapper::line_size_terms),
                           std::string (AddressMapper::*)(std::int64_t) const>::value, "");

}  // namespace

int main() {
    test_the_two_real_geometries();
    test_the_direct_mapped_and_fully_associative_ends();
    test_one_mapper_serves_several_arrays();
    test_the_line_size_is_read_exactly_once();
    test_the_refusal_message_cannot_contradict_itself();
    test_the_array_is_usable_through_the_base();
    test_the_three_positivity_refusals();
    test_the_exactness_refusal_names_all_three_terms();
    test_the_inline_default_of_line_size_terms();
    test_the_two_associativity_refusals_are_distinguishable();
    test_the_slot_bound_and_its_boundary();
    test_the_order_the_checks_run_in();
    test_every_refusal_is_invalid_argument();
    test_probe_finds_a_line_only_where_it_lives();
    test_probe_is_not_an_access();
    test_free_slot_is_the_lowest_free_way();
    test_free_slot_is_deterministic_across_arrays();
    test_victim_candidates_reports_one_whole_set();
    test_victim_candidates_leaves_the_buffer_alone_when_it_throws();
    test_insert_reports_what_it_displaced();
    test_invalidate_frees_a_slot_and_is_idempotent();
    test_the_two_verbs_that_take_a_slot_range_check_it();
    test_capacity_and_conflict();
    test_the_slot_numbering_is_a_partition_of_the_array();
    test_the_replay_agrees_with_the_model();
    return check::summary();
}
