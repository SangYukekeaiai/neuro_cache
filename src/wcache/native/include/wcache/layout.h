// AddressMapper: logical tensor coordinates -> cache lines.
//
// Plan v3 Part 2.1, the address-generator row: `AddressMapper::expand(Burst)
// -> [LineId]`, shaped by `cin_block`, `cout_block`, `weight_bytes`.
//
// Keeping logical coordinates in the trace and resolving them here is what
// makes the layout a swept parameter rather than a property baked into the
// 7.7 GB corpus. One trace, replayed under several blockings, is several
// different demand profiles.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/types.h"

namespace wcache {

// Where a line sits in a set-associative array: which set holds it, and the
// value that tells it apart from the other lines mapping to that same set.
//
// Both fields are signed, matching LineId, so `line == tag * num_sets +
// set_index` holds without a cast and a bounds check written the obvious way
// (`0 <= set_index && set_index < num_sets`) is not vacuously true.
//
// Named Placement, not SetIndex: it holds two fields, and "index" reads as
// one. A4 needs `SetIndex` for a tagged scalar, so that a policy handed a
// SlotId where a set index belongs fails to compile.
struct Placement {
    std::int64_t set_index;  // in [0, num_sets)
    std::int64_t tag;
};

// The interface, deliberately abstract. A layout is a hypothesis about how
// weights are arranged in memory, and the study compares hypotheses; the
// engine holds an AddressMapper and never learns which one it has.
//
// One instance serves the whole hierarchy. L1 and L2 differ in size and
// associativity, not in how the tensor is laid out, so the set count is a
// `locate` argument rather than mapper state.
class AddressMapper {
public:
    virtual ~AddressMapper() = default;

    // --- what an implementation throws --------------------------------------
    //
    // One vocabulary for the whole tree, so that a catch site can tell a bad
    // configuration from a bad access by type alone:
    //
    //   std::invalid_argument  the argument is malformed whatever layer it is
    //                          applied to. A burst with `count < 1`.
    //   std::out_of_range      the argument is well formed but names something
    //                          outside THIS layer. A coordinate past an extent,
    //                          a LineId outside [0, num_lines()).
    //   std::logic_error       programmer error. An Axis outside the
    //                          enumerators.
    //
    // The contract belongs here rather than in a comment on the test helpers,
    // because which type is thrown is part of what an implementation promises
    // and is what the engine's re-throw at the level above is written against.

    // --- what an implementation must accept ---------------------------------
    //
    // A burst along ANY axis. `b.axis` and `b.stride` come from the format v2
    // header, and today's corpus always says COUT with stride 1, but a trace
    // written as [kh, kw, cout, cin_start, cin_end] bursts along CIN and is
    // the same struct. An implementation therefore reads the walked axis out
    // of the burst; it may not assume COUT, and it may not assume that the
    // walked axis is one it blocks. A burst along KH is legal and, under a
    // block-packed layout, touches `count` distinct lines because KH is not
    // blocked.
    //
    // Appends the distinct lines this burst touches to `out`. The ids appended
    // by a single call are strictly increasing and distinct; that guarantee is
    // per call and does not extend to the buffer as a whole. Appends rather
    // than assigns so a caller can accumulate a whole tick's demand into one
    // reused buffer, and such a buffer is neither sorted nor unique across
    // calls: different cores in one tick touch lines out of order and touch
    // the same line, and the merge ratio is measured above 1. A caller
    // accumulating across cores must sort and unique before counting distinct
    // lines.
    //
    // "Strictly increasing" is an obligation on the IMPLEMENTATION, not a
    // property a layout is free to have or not have: an implementation whose
    // natural walk order does not produce increasing ids sorts before it
    // appends. The checks that hold implementations to this interface are
    // parameterised over this abstract class, so a guarantee that varied per
    // implementation could not be checked at all.
    //
    // A burst with `count < 1` or with `stride < 1` throws
    // std::invalid_argument. A core asking for nothing is malformed at every
    // layer, and admitting it would leave every consumer below with a request
    // that has no lines to special-case. A stride of 0 is the same element
    // asked for `count` times and a negative stride is a run walking backwards;
    // `burst_stride` in the format v2 header is a step to the next element of
    // the run, so neither is a run a trace can describe, and both are malformed
    // whatever layer they are applied to rather than outside this one.
    //
    // On throwing: every range check must run before the first append, so a
    // call that throws appends nothing and leaves `out` exactly as it was.
    // The obligation this does NOT discharge is one level up: in the
    // accumulate pattern, a burst that throws part way through a tick leaves
    // the buffer holding a well-formed but PARTIAL tick, the earlier cores
    // only. The engine must decide whether such a tick is discarded or the run
    // aborts, and must not silently simulate the partial one.
    //
    // A coordinate outside the layer's shape throws std::out_of_range (N11,
    // V15) rather than wrapping into a valid-looking line id.
    virtual void expand(const Burst& b, std::vector<LineId>& out) const = 0;

    // Placement of `line` in an array of `num_sets` sets.
    //
    // Precondition: `0 <= line.get() < num_lines()`. An id outside that range
    // throws std::out_of_range, and the check runs BEFORE the division, which
    // is what makes the postcondition `0 <= set_index < num_sets` a fact
    // rather than an assumption: LineId is signed, so a negative id would
    // otherwise come back out of `line % num_sets` as a negative set index and
    // index an array from below.
    virtual Placement locate(LineId line, std::int64_t num_sets) const = 0;

    // One past the largest LineId this mapper can produce. The bound the
    // engine checks tags against, and what D2 divides by for coverage.
    virtual LineId num_lines() const = 0;

    // Bytes held by one line. On the interface rather than on the concrete
    // mapper because CacheLevel holds an AddressMapper and needs this to turn
    // the config's cache_size_bytes into a set count. Only the layout knows
    // how many elements a line packs, so only the layout can answer.
    virtual std::int64_t line_size_bytes() const = 0;
};

}  // namespace wcache
