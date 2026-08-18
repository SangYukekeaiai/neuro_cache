// Conformance checks for AddressMapper (unit A2a).
//
// A2a is an interface. A test that builds a Placement from two ints and reads
// them back proves nothing, and a test that exercises one concrete mapper
// tests that mapper, not the interface. What A2a actually asserts lives in the
// comments on layout.h, and every one of those statements is a claim about
// EVERY implementation. This header turns each of them into a check
// parameterised over an `AddressMapper&`, so a concrete mapper plugs in with
// one line:
//
//     conformance::run_all(mapper, conformance::make_env(shape), "BlockPackMapper");
//
// That is what A2d is expected to add. Nothing here knows about blocking,
// packing, or cin_block / cout_block: the checks use only what layout.h
// promises, so a mapper that packs nothing and a mapper that blocks two axes
// both go through unchanged.
//
// Two conventions that matter for how this file is written:
//
//  1. No function here calls check::group(). Each is driven twice: once over a
//     conforming mapper, where a failure is a real failure, and once over a
//     deliberately broken one, where a failure is the expected result and the
//     counters are detached (expect_failure in test_layout.cpp). A group
//     header per contract would make the second pass unreadable.
//
//  2. Every check catches, rather than letting an exception escape. A mapper
//     that throws where the contract says it must not is exactly the thing
//     under test, and an escaping exception would end the run instead of
//     reporting one failure and continuing.
#pragma once

#include <wcache/layout.h>
#include <wcache/types.h>

#include <algorithm>
#include <cstdint>
#include <exception>
#include <stdexcept>
#include <vector>

#include "check.h"

namespace conformance {

using namespace wcache;

// Declaration order, which A1b's carried obligation says is the row-major
// nesting order. Written out once so a loop over the four axes is written once.
inline constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};

// The value a check seeds `out` with before calling expand. Negative on
// purpose: real line ids are non-negative, so a mapper that treats the buffer
// as scratch cannot overwrite the sentinel with something that still looks
// like a sentinel.
inline constexpr std::int64_t kSentinel = -777;

// What the checks need beyond the mapper itself. The interface deliberately
// does not expose the layer shape (locate takes num_sets as an argument for
// the same reason), so the caller supplies it.
struct Env {
    WeightShape        shape;
    std::vector<Burst> legal;    // must be accepted
    std::vector<Burst> illegal;  // must throw, and must append nothing
    std::vector<Burst> sweep;    // together, every element of the tensor
};

// Bursts derived from the shape alone, so the same Env drives any mapper.
//
// The legal set deliberately covers all four axes, not only COUT: the A2a ->
// A2d carried obligation is that a burst along an axis the layout does not
// block is legal, the corpus never produces one, and only a test announces the
// regression.
inline Env make_env(const WeightShape& shape) {
    Env e;
    e.shape = shape;
    const Coord origin{0, 0, 0, 0};

    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(shape, a);

        // The degenerate burst a cout_block of 1 produces, and the one D9 says
        // expand must still return a list for.
        e.legal.push_back(Burst{origin, a, 1, 1});
        // The whole axis: the widest legal run, and under a packing narrower
        // than the axis the case where several elements share a line.
        e.legal.push_back(Burst{origin, a, n, 1});
        // A run that does not start at 0, so a mapper that ignores the anchor
        // and walks from the origin is not accidentally right.
        if (n >= 3) e.legal.push_back(Burst{with_coord_on(origin, a, 1), a, n - 1, 1});
        // stride > 1 is a header field (format v2 burst_stride) and nothing
        // downstream may assume it is 1.
        if (n >= 4) e.legal.push_back(Burst{origin, a, n / 2, 2});
        // The last element of the axis on its own: the boundary an off-by-one
        // in the range check turns into a spurious throw.
        e.legal.push_back(Burst{with_coord_on(origin, a, n - 1), a, 1, 1});

        // Illegal, four ways. The first two are caught before the walk starts;
        // the last two begin legal and leave the tensor part way, which is the
        // pair that separates "checks first" from "checks as it goes".
        e.illegal.push_back(Burst{with_coord_on(origin, a, n), a, 1, 1});
        e.illegal.push_back(Burst{with_coord_on(origin, a, -1), a, 1, 1});
        e.illegal.push_back(Burst{origin, a, n + 1, 1});
        if (n >= 2) e.illegal.push_back(Burst{with_coord_on(origin, a, n - 1), a, 2, 1});
    }

    // An anchor out of range on an axis the burst does NOT walk. The range
    // check covers all four coordinates or it covers one.
    e.illegal.push_back(Burst{Coord{0, 0, shape.CIN, 0}, Axis::COUT, 1, 1});
    e.illegal.push_back(Burst{Coord{shape.KH, 0, 0, 0}, Axis::COUT, 1, 1});
    e.illegal.push_back(Burst{Coord{0, -1, 0, 0}, Axis::CIN, 1, 1});

    // Every element of the tensor, as COUT-major bursts. num_lines()'s "one
    // past the LARGEST id this mapper can produce" is an exact claim, and only
    // a full sweep can check that the largest is actually reached.
    for (std::int32_t kh = 0; kh < shape.KH; ++kh)
        for (std::int32_t kw = 0; kw < shape.KW; ++kw)
            for (std::int32_t cin = 0; cin < shape.CIN; ++cin)
                e.sweep.push_back(Burst{Coord{kh, kw, cin, 0}, Axis::COUT, shape.COUT, 1});

    return e;
}

// Calls expand and reports whether it threw, instead of letting the exception
// out. Used wherever the contract says the call must succeed.
inline bool try_expand(const AddressMapper& m, const Burst& b, std::vector<LineId>& out) {
    try {
        m.expand(b, out);
        return true;
    } catch (const std::exception&) {
        return false;
    } catch (...) {
        return false;
    }
}

// --- contract 1: expand appends, and appends the same thing every time ------
//
// layout.h: "Appends rather than assigns so a caller can accumulate a whole
// tick's demand into one reused buffer." A mapper that assigns satisfies every
// other check in this file, so this is the only thing that announces it. The
// second half is the one that catches a mapper carrying state between calls:
// what a burst appends may not depend on what is already in the buffer.
inline void c_appends_not_assigns(const AddressMapper& m, const Env& e) {
    std::vector<LineId> acc(3, LineId{kSentinel});
    std::int64_t expect = 3;

    for (const Burst& b : e.legal) {
        std::vector<LineId> alone;
        if (!try_expand(m, b, alone)) { CHECK_TRUE(false); continue; }
        CHECK_TRUE(check::ssize(alone) >= 1);  // a legal burst touches a line

        if (!try_expand(m, b, acc)) { CHECK_TRUE(false); continue; }
        expect += check::ssize(alone);
        CHECK_EQ(check::ssize(acc), expect);   // grew by exactly that many
    }

    // The caller's own data is still there, unshifted, after every call.
    CHECK_TRUE(acc.size() >= 3);
    if (acc.size() >= 3) {
        CHECK_TRUE(acc[0] == LineId{kSentinel});
        CHECK_TRUE(acc[1] == LineId{kSentinel});
        CHECK_TRUE(acc[2] == LineId{kSentinel});
    }
}

// --- contract 2: within one call, strictly increasing ------------------------
//
// layout.h: "The ids appended by a single call are strictly increasing and
// distinct." Strict covers both halves at once, so there is no separate
// uniqueness check.
//
// The buffer is seeded before the call and the comparison starts one past the
// seed, because the guarantee is explicitly per call: an accumulated buffer is
// "neither sorted nor unique across calls", and comparing the first appended
// id against the seed would be asserting a promise the interface refuses.
inline void c_single_call_strictly_increasing(const AddressMapper& m, const Env& e) {
    for (const Burst& b : e.legal) {
        std::vector<LineId> out(2, LineId{kSentinel});
        const std::size_t base = out.size();
        if (!try_expand(m, b, out)) { CHECK_TRUE(false); continue; }

        for (std::size_t i = base + 1; i < out.size(); ++i) CHECK_TRUE(out[i - 1] < out[i]);

        // At most one line per element. A burst along an axis the layout does
        // not block hits this bound exactly (the A2d obligation); a burst
        // along a packed axis stays under it. Nothing may exceed it.
        CHECK_TRUE(check::ssize(out) - static_cast<std::int64_t>(base) <= b.count);
    }
}

// --- contract 3: a throwing call appends nothing -----------------------------
//
// layout.h: "every range check must run before the first append, so a call
// that throws appends nothing and leaves `out` exactly as it was." This is the
// strong exception guarantee, and it is the contract a future implementation
// that computes as it goes breaks without breaking anything else: its ids are
// still sorted, still distinct, still inside num_lines.
//
// The buffer is seeded with what stands in for a previous core's lines,
// because that is the accumulate pattern layout.h describes and the state an
// eager implementation corrupts.
inline void c_throwing_call_appends_nothing(const AddressMapper& m, const Env& e) {
    for (const Burst& b : e.illegal) {
        std::vector<LineId> out;
        out.push_back(LineId{kSentinel});
        out.push_back(LineId{kSentinel + 1});
        const std::vector<LineId> before = out;

        bool threw = false;
        try {
            m.expand(b, out);
        } catch (const std::exception&) {
            threw = true;
        } catch (...) {
            threw = true;
        }
        CHECK_TRUE(threw);  // a coordinate outside the shape must not be served

        CHECK_EQ(check::ssize(out), check::ssize(before));
        bool identical = out.size() == before.size();
        for (std::size_t i = 0; identical && i < before.size(); ++i)
            identical = out[i] == before[i];
        CHECK_TRUE(identical);
    }
}

// --- contract 3b: which exception -------------------------------------------
//
// layout.h says "throws" and does not name a type. check.h does, and its
// comment was written for this unit: "invalid_argument for a bad
// configuration, out_of_range for a burst that leaves the tensor". Kept as its
// own check rather than folded into the one above, so that an implementation
// choosing a different type fails here alone and the disagreement is visible
// instead of being read as a broken range check.
inline void c_throw_type_is_out_of_range(const AddressMapper& m, const Env& e) {
    for (const Burst& b : e.illegal) {
        std::vector<LineId> out;
        CHECK_THROWS(std::out_of_range, m.expand(b, out));
    }
}

// --- contract 4: any axis, including one the layout does not block -----------
//
// layout.h: "An implementation therefore reads the walked axis out of the
// burst; it may not assume COUT, and it may not assume that the walked axis is
// one it blocks."
inline void c_accepts_any_axis(const AddressMapper& m, const Env& e) {
    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(e.shape, a);
        std::vector<LineId> out;
        const bool ok = try_expand(m, Burst{Coord{0, 0, 0, 0}, a, n, 1}, out);
        CHECK_TRUE(ok);
        if (!ok) continue;
        CHECK_TRUE(check::ssize(out) >= 1);
        CHECK_TRUE(check::ssize(out) <= n);
    }
}

// --- contract 5: a burst is exactly the lines its elements touch -------------
//
// layout.h: "Appends the distinct lines this burst touches." The elements a
// burst touches are anchor, anchor + stride, ... along b.axis, so expanding
// the burst must yield the same SET of lines as expanding those elements one
// at a time.
//
// This is the check that catches a mapper reading the wrong axis or ignoring
// the stride. Both of those stay sorted, stay distinct, stay inside
// num_lines(), and append a plausible number of ids, so nothing else in this
// file notices them. It is also the only check here that pins expand's
// meaning rather than its shape.
inline void c_burst_is_its_elements(const AddressMapper& m, const Env& e) {
    for (const Burst& b : e.legal) {
        std::vector<LineId> whole;
        if (!try_expand(m, b, whole)) { CHECK_TRUE(false); continue; }

        std::vector<LineId> parts;
        const std::int32_t start = coord_on(b.anchor, b.axis);
        bool ok = true;
        for (std::int32_t i = 0; i < b.count && ok; ++i) {
            const Coord c = with_coord_on(b.anchor, b.axis, start + i * b.stride);
            ok = try_expand(m, Burst{c, b.axis, 1, 1}, parts);
        }
        CHECK_TRUE(ok);
        if (!ok) continue;

        std::sort(parts.begin(), parts.end(),
                  [](LineId x, LineId y) { return x < y; });
        parts.erase(std::unique(parts.begin(), parts.end(),
                                [](LineId x, LineId y) { return x == y; }),
                    parts.end());

        CHECK_EQ(check::ssize(whole), check::ssize(parts));
        bool same = whole.size() == parts.size();
        for (std::size_t i = 0; same && i < parts.size(); ++i) same = whole[i] == parts[i];
        CHECK_TRUE(same);
    }
}

// --- contract 6: locate's identity -------------------------------------------
//
// layout.h, on Placement: "`line == tag * num_sets + set_index` holds without a
// cast and a bounds check written the obvious way (`0 <= set_index &&
// set_index < num_sets`) is not vacuously true."
//
// Driven over ids the mapper actually produced, plus both ends of its range,
// and over several set counts including 1 (where every line is in set 0 and
// the tag is the line) so that a mapper cannot be right only at one power of
// two.
inline void c_locate_identity(const AddressMapper& m, const Env& e) {
    std::vector<LineId> lines;
    for (const Burst& b : e.legal) (void)try_expand(m, b, lines);
    lines.push_back(LineId{0});
    const std::int64_t last = m.num_lines().get() - 1;
    if (last >= 0) lines.push_back(LineId{last});

    const std::int64_t set_counts[6] = {1, 2, 4, 8, 64, 1024};
    for (std::int64_t num_sets : set_counts) {
        for (LineId l : lines) {
            const Placement p = m.locate(l, num_sets);
            CHECK_TRUE(p.set_index >= 0);
            CHECK_TRUE(p.set_index < num_sets);
            CHECK_EQ(p.tag * num_sets + p.set_index, l.get());

            // No state: L1 and L2 share one mapper and call locate with
            // different num_sets, interleaved.
            const Placement again = m.locate(l, num_sets);
            CHECK_EQ(again.set_index, p.set_index);
            CHECK_EQ(again.tag, p.tag);
        }
    }
}

// --- contract 7: num_lines is one past the largest ---------------------------
//
// layout.h: "One past the largest LineId this mapper can produce. The bound the
// engine checks tags against, and what D2 divides by for coverage." Both halves
// are checkable and both matter: an upper bound that is too loose silently
// deflates every coverage figure D2 reports, and one that is too tight makes
// the engine's bound check reject real lines.
inline void c_num_lines_is_exact(const AddressMapper& m, const Env& e) {
    const LineId n = m.num_lines();
    CHECK_TRUE(n > LineId{0});

    std::vector<LineId> out;
    for (const Burst& b : e.sweep) {
        if (!try_expand(m, b, out)) { CHECK_TRUE(false); return; }
    }
    CHECK_TRUE(check::ssize(out) >= 1);

    LineId max = LineId{-1};
    bool in_range = true;
    for (LineId l : out) {
        in_range = in_range && LineId{-1} < l && l < n;
        if (max < l) max = l;
    }
    CHECK_TRUE(in_range);                       // nothing at or past the bound
    CHECK_EQ(max.get(), n.get() - 1);           // and the bound is reached
}

// --- contract 8: line_size_bytes ---------------------------------------------
//
// layout.h puts this on the interface because "CacheLevel holds an
// AddressMapper and needs this to turn the config's cache_size_bytes into a
// set count". That division is the whole reason it exists, so zero is a divide
// by zero at config load and a negative is a nonsense set count.
inline void c_line_size_bytes_is_usable(const AddressMapper& m, const Env&) {
    CHECK_TRUE(m.line_size_bytes() > 0);
    CHECK_EQ(m.line_size_bytes(), m.line_size_bytes());  // no state, same as locate
}

// Every contract, in one call. This is the line A2d adds.
inline void run_all(const AddressMapper& m, const Env& e, const char* who) {
    check::group(who);
    c_appends_not_assigns(m, e);
    c_single_call_strictly_increasing(m, e);
    c_throwing_call_appends_nothing(m, e);
    c_throw_type_is_out_of_range(m, e);
    c_accepts_any_axis(m, e);
    c_burst_is_its_elements(m, e);
    c_locate_identity(m, e);
    c_num_lines_is_exact(m, e);
    c_line_size_bytes_is_usable(m, e);
}

}  // namespace conformance
