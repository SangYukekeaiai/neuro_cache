// Unit A4b: SetAssociativeArray's construction and validation.
//
// A4b is a constructor and three accessors. Its five verbs are A4c's and are
// std::logic_error stubs here (B19), so everything this file can reach is the
// geometry the constructor derives and the seven refusals it makes on the way.
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
// derived quantities, L is the rejections. Groups M through S are A4c's.
#include <wcache/set_associative.h>

#include <wcache/block_pack.h>
#include <wcache/cache.h>
#include <wcache/layout.h>

#include <cstdint>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <type_traits>
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

// The mirror probe, for the A4c stubs, where logic_error is the RIGHT answer.
// Two probes rather than one parameterised probe, for test_block_pack.cpp's
// reason: the two cases disagree about which type is correct, and a single
// probe would have to be told which, which is the thing being tested.
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
        return Placement{line.get() % num_sets, line.get() / num_sets};
    }
    LineId       num_lines()       const override { return LineId{1}; }
    std::int64_t line_size_bytes() const override { ++reads_; return line_bytes_; }

    int reads() const { return reads_; }

private:
    std::int64_t line_bytes_;
    mutable int  reads_ = 0;
};

// The same mapper with line_size_terms OVERRIDDEN, so the two halves of the
// refusal message come from two different sources. It exists for one measured
// reason, recorded in test_the_line_size_is_read_exactly_once below: the inline
// default in layout.h calls line_size_bytes() a second time, so "read once" is
// a property of the CONSTRUCTOR and not of the whole refusal path, and only a
// mapper that overrides the terms can show the difference.
class TermsMapper final : public TinyMapper {
public:
    using TinyMapper::TinyMapper;
    std::string line_size_terms() const override { return "a fixed string"; }
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

    // And the exception, measured rather than assumed, which is a reviewer
    // finding rather than a designed behaviour: layout.h's INLINE DEFAULT for
    // line_size_terms is `std::to_string(line_size_bytes())`, so a mapper that
    // does not override it is asked a SECOND time, from inside the message.
    //
    // The constructor's own discipline is intact -- every division still uses
    // the one value it read -- so no geometry can come out wrong. What it costs
    // is confined to the diagnostic: for a mapper that answers inconsistently,
    // the "-byte lines" half and the bracketed half of one message are two
    // reads and can disagree with each other. That is exactly the "second thing
    // that can disagree with the first" block_pack.cpp's own line_size_terms
    // comment says it avoided by not repeating the product.
    //
    // Pinned rather than left as a note, so that a later change to either side
    // has to come here and say which way it went.
    // Side effect worth knowing about, found by the meta-verification round and
    // recorded so it is not read later as a coincidence: because the second
    // read comes from inside the message, this check also goes red for a
    // mutation that drops line_size_terms() from the message entirely. That is
    // incidental coverage of something this test is not about, so it is NOT
    // what the terms are pinned by; the L4 group below carries that, and it was
    // shown to be load-bearing with this check and the two others disabled.
    TinyMapper defaulted(96);
    (void)thrown_by([&] { SetAssociativeArray bad(defaulted, 65536, 8); });
    CHECK_EQ(defaulted.reads(), 2);
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
    CHECK_TRUE(other.line_size_terms() == "7");
    const AddressMapper& base = other;
    CHECK_TRUE(base.line_size_terms() == "7");

    // And BlockPackMapper's override is reachable through the same base
    // reference, which is what makes it an override rather than a shadow.
    const BlockPackMapper packed(kShape, 12, 8, 1);
    const AddressMapper& pbase = packed;
    CHECK_TRUE(pbase.line_size_terms() == "cin_block 12 x cout_block 8 x weight_bytes 1");

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
// The A4c stubs, and what this file therefore cannot say
// ===========================================================================

void test_the_five_verbs_are_still_stubs() {
    check::group("A4b: the five verbs are A4c stubs and say so");

    // B19's convention, and the tripwire B45 named: a stub quietly given a
    // plausible body is the one failure in a validation increment that produces
    // no wrong number at all. `probe` returning NoSlot and `free_slot`
    // returning SlotId{0} would look exactly like a correctly empty cache, so
    // the refusal is what stands between A4b and a suite that silently believes
    // A4c is finished.
    //
    // This is also the honest answer to "every slot starts as NoLine". The slot
    // vector is private and all three verbs that could report it throw, so the
    // initial fill is NOT observable at A4b, by anything. What is checked here
    // is the property that keeps it from being MIS-reported: nothing answers
    // the question yet. Three mutation cases against the fill are written into
    // mutation_check.sh and are carried by A4c's tests, not by this file.
    const BlockPackMapper m(kShape, 16, 16, 1);
    const SetAssociativeArray a(m, 65536, 8);
    SetAssociativeArray mutable_a(m, 65536, 8);
    std::vector<Candidate> out;

    expect_message("probe", logic_thrown_by([&] { (void)a.probe(LineId{0}); }),
                   "SetAssociativeArray::probe", {"not implemented", "A4c"});
    expect_message("free_slot", logic_thrown_by([&] { (void)a.free_slot(LineId{0}); }),
                   "SetAssociativeArray::free_slot", {"not implemented", "A4c"});
    expect_message("victim_candidates",
                   logic_thrown_by([&] { a.victim_candidates(LineId{0}, out); }),
                   "SetAssociativeArray::victim_candidates", {"not implemented", "A4c"});
    expect_message("insert",
                   logic_thrown_by([&] { (void)mutable_a.insert(LineId{0}, SlotId{0}); }),
                   "SetAssociativeArray::insert", {"not implemented", "A4c"});
    expect_message("invalidate", logic_thrown_by([&] { mutable_a.invalidate(SlotId{0}); }),
                   "SetAssociativeArray::invalidate", {"not implemented", "A4c"});

    // And through the base, which is the only way the engine reaches them, so
    // an override that failed to override would show up as no exception at all.
    const CacheArray& r = a;
    expect_message("probe through the base", logic_thrown_by([&] { (void)r.probe(LineId{0}); }),
                   "SetAssociativeArray::probe", {"A4c"});
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
// the const mapper reference the array holds.
static_assert(std::is_same<decltype(std::declval<const AddressMapper&>().line_size_terms()),
                           std::string>::value, "");

}  // namespace

int main() {
    test_the_two_real_geometries();
    test_the_direct_mapped_and_fully_associative_ends();
    test_one_mapper_serves_several_arrays();
    test_the_line_size_is_read_exactly_once();
    test_the_array_is_usable_through_the_base();
    test_the_three_positivity_refusals();
    test_the_exactness_refusal_names_all_three_terms();
    test_the_inline_default_of_line_size_terms();
    test_the_two_associativity_refusals_are_distinguishable();
    test_the_slot_bound_and_its_boundary();
    test_the_order_the_checks_run_in();
    test_every_refusal_is_invalid_argument();
    test_the_five_verbs_are_still_stubs();
    return check::summary();
}
