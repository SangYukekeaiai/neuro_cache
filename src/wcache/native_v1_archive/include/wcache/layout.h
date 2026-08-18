// AddressMapper: logical tensor coordinates -> cache lines.
// Plan Part 3.3. Keeping logical coordinates in the trace and resolving
// them here is what makes the layout a swept parameter instead of a
// property baked into the 7.7 GB corpus (plan Part 1.4).
#pragma once

#include <vector>

#include "wcache/types.h"

namespace wcache {

// Where a line sits in a set-associative array: which set holds it, and the
// value that tells it apart from the other lines mapping to that same set.
// Both fields are signed, matching LineId, so `line == tag * num_sets +
// set_index` holds without a cast and a bounds check written the obvious way
// (`0 <= set_index && set_index < num_sets`) is not vacuously true.
struct SetIndex {
    std::int64_t set_index;  // in [0, num_sets)
    std::int64_t tag;
};

class AddressMapper {
public:
    virtual ~AddressMapper() = default;

    // Appends the distinct lines this burst touches to `out`. The ids
    // appended by a single call are strictly increasing and distinct; that
    // guarantee is per call and does not extend to the buffer as a whole.
    // Appends rather than assigns so a caller can accumulate a whole tick's
    // demand into one reused buffer, and such a buffer is neither sorted nor
    // unique across calls: different cores in one tick touch lines out of
    // order and touch the same line (measured merge ratio 1.13 at 1024
    // cores). A caller accumulating across cores must therefore sort and
    // unique the buffer before counting distinct lines, which is what the
    // distinct-lines-per-tick statistic of plan Part 2.4 needs.
    //
    // On throwing: every range check in an implementation must run before the
    // first append, so a call that throws appends nothing and the buffer is
    // left exactly as it was. BlockPackMapper honours that and the test suite
    // pins it. The obligation this does NOT discharge belongs one level up: in
    // the accumulate pattern, a burst that throws part way through a tick
    // leaves the buffer holding a well-formed but PARTIAL tick, the earlier
    // cores only. The engine must decide whether such a tick is discarded or
    // the run aborts, and must not silently simulate the partial one. That
    // decision belongs with the per-tick reserve obligation in the engine's
    // spec, not here.
    virtual void expand(const Burst& b, std::vector<LineId>& out) const = 0;

    // Placement of `line` in an array of `num_sets` sets.
    // `num_sets` is a parameter rather than mapper state because one layout
    // instance serves the whole hierarchy, and L1 and L2 carry their own
    // cache_size_bytes and associativity (plan 3.5), so they have different
    // set counts.
    virtual SetIndex locate(LineId line, std::int64_t num_sets) const = 0;

    virtual LineId num_lines() const = 0;

    // Bytes held by one line. On the interface rather than on the concrete
    // mapper because CacheLevel holds an AddressMapper and needs this to turn
    // the YAML's cache_size_bytes into a set count (plan 3.5). Only the layout
    // knows how many elements a line packs, so only the layout can answer.
    virtual std::int64_t line_size_bytes() const = 0;
};

// Packs a cin_block x cout_block sub-block of the [KH][KW][CIN][COUT]
// weight tensor into one line, so a line is identified by
// (kh, kw, cin / cin_block, cout / cout_block) in row-major order.
// line_size_bytes is cin_block * cout_block * weight_bytes (plan 3.5).
//
// weight_bytes is a constructor argument rather than something the caller
// carries separately because it is a format v2 header field that arrives with
// the same trace as the shape, and because the alternative is unit 3 plumbing
// it to CacheLevel and recomputing the product there, giving two places that
// can disagree about the size of a line.
class BlockPackMapper final : public AddressMapper {
public:
    BlockPackMapper(WeightShape shape,
                    std::int32_t cin_block,
                    std::int32_t cout_block,
                    std::int32_t weight_bytes);

    void expand(const Burst& b, std::vector<LineId>& out) const override;
    SetIndex locate(LineId line, std::int64_t num_sets) const override;
    LineId num_lines() const override { return num_lines_; }
    std::int64_t line_size_bytes() const override { return line_size_bytes_; }

    // The line holding element `c`.
    LineId line_of(const Coord& c) const;

    // Elements per line along `a`: cin_block on CIN, cout_block on COUT,
    // 1 on KH and KW, which are not blocked.
    std::int32_t block_len(Axis a) const;

    // LineId delta produced by stepping one whole block along `a`.
    LineId line_stride(Axis a) const;

    std::int64_t n_cin_blocks()  const { return n_cin_blocks_; }
    std::int64_t n_cout_blocks() const { return n_cout_blocks_; }
    std::int32_t weight_bytes()  const { return weight_bytes_; }

private:
    WeightShape  shape_;
    std::int32_t cin_block_;
    std::int32_t cout_block_;
    std::int32_t weight_bytes_;
    std::int64_t n_cin_blocks_;
    std::int64_t n_cout_blocks_;
    std::int64_t line_size_bytes_;
    LineId       num_lines_;
};

}  // namespace wcache
