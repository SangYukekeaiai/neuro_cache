// AddressMapper: logical tensor coordinates -> cache lines.
//
// Plan v2 Part 2.1, the address-generator row: `AddressMapper::expand(Burst)
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
    // the same line (measured merge ratio 1.13 at 1024 cores). A caller
    // accumulating across cores must sort and unique before counting distinct
    // lines.
    //
    // On throwing: every range check must run before the first append, so a
    // call that throws appends nothing and leaves `out` exactly as it was.
    // The obligation this does NOT discharge is one level up: in the
    // accumulate pattern, a burst that throws part way through a tick leaves
    // the buffer holding a well-formed but PARTIAL tick, the earlier cores
    // only. The engine must decide whether such a tick is discarded or the run
    // aborts, and must not silently simulate the partial one.
    //
    // A coordinate outside the layer's shape throws (N11, V15) rather than
    // wrapping into a valid-looking line id.
    virtual void expand(const Burst& b, std::vector<LineId>& out) const = 0;

    // Placement of `line` in an array of `num_sets` sets.
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
