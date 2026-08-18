#include "wcache/layout.h"

#include <cassert>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// Cold path only, kept out of line_of so the check there stays four
// comparisons with no string machinery in the common case.
[[noreturn]] void throw_outside_tensor(const Coord& c, const WeightShape& s) {
    throw std::out_of_range(
        "BlockPackMapper: coordinate {" + std::to_string(c.kh) + "," +
        std::to_string(c.kw) + "," + std::to_string(c.cin) + "," +
        std::to_string(c.cout) + "} is outside the weight tensor {" +
        std::to_string(s.KH) + "," + std::to_string(s.KW) + "," +
        std::to_string(s.CIN) + "," + std::to_string(s.COUT) + "}");
}

}  // namespace

BlockPackMapper::BlockPackMapper(WeightShape shape,
                                std::int32_t cin_block,
                                std::int32_t cout_block,
                                std::int32_t weight_bytes)
    : shape_(shape),
      cin_block_(cin_block),
      cout_block_(cout_block),
      weight_bytes_(weight_bytes) {
    if (shape.KH <= 0 || shape.KW <= 0 || shape.CIN <= 0 || shape.COUT <= 0) {
        throw std::invalid_argument("BlockPackMapper: weight shape must be positive");
    }
    if (cin_block <= 0 || cout_block <= 0) {
        throw std::invalid_argument("BlockPackMapper: block sizes must be positive");
    }
    if (weight_bytes <= 0) {
        throw std::invalid_argument("BlockPackMapper: weight_bytes must be positive");
    }
    // Ceiling division: a partial trailing block still occupies a line.
    n_cin_blocks_  = (static_cast<std::int64_t>(shape.CIN)  + cin_block  - 1) / cin_block;
    n_cout_blocks_ = (static_cast<std::int64_t>(shape.COUT) + cout_block - 1) / cout_block;
    // A line holds the whole cin_block x cout_block tile, padding included, so
    // this is the block area and not the count of real elements in it. Plan
    // 3.5 sizes the arrays from this, so a partial trailing block costs a full
    // line's worth of capacity, which is what real hardware does too.
    line_size_bytes_ = static_cast<std::int64_t>(cin_block) * cout_block * weight_bytes;
    num_lines_ = static_cast<LineId>(shape.KH) * shape.KW
               * n_cin_blocks_ * n_cout_blocks_;
}

std::int32_t BlockPackMapper::block_len(Axis a) const {
    switch (a) {
        case Axis::KH:   return 1;
        case Axis::KW:   return 1;
        case Axis::CIN:  return cin_block_;
        case Axis::COUT: return cout_block_;
    }
    // Unreachable: the switch covers every Axis enumerator. Throwing rather
    // than returning a plausible value means a future axis added to the enum
    // stops the run instead of silently packing 1 element per line.
    throw std::logic_error("BlockPackMapper::block_len: unknown Axis");
}

LineId BlockPackMapper::line_stride(Axis a) const {
    const LineId cout_dim = n_cout_blocks_;
    const LineId cin_dim  = n_cin_blocks_;
    switch (a) {
        case Axis::COUT: return 1;
        case Axis::CIN:  return cout_dim;
        case Axis::KW:   return cin_dim * cout_dim;
        case Axis::KH:   return static_cast<LineId>(shape_.KW) * cin_dim * cout_dim;
    }
    // Unreachable: the switch covers every Axis enumerator. A fallback of 0
    // would be actively corrupting, since expand would then emit `count`
    // copies of one line id and break the strictly increasing contract, so
    // this path fails loudly instead. `throw` is used rather than
    // `assert(false)` because it survives -DNDEBUG, and rather than
    // __builtin_unreachable() because it is standard C++17 and therefore
    // clean under -Wpedantic. Control cannot reach the end of the function,
    // so -Wreturn-type is satisfied without a corrupting return value.
    throw std::logic_error("BlockPackMapper::line_stride: unknown Axis");
}

LineId BlockPackMapper::line_of(const Coord& c) const {
    // Throws rather than asserts, on all four axes. These were asserts, which
    // left three of the four coordinates unchecked in the sweep build, because
    // expand's own range check covers only the axis the burst walks. The
    // consequences were not theoretical. Measured under -DNDEBUG on the real
    // layer, with a legal COUT burst and one bad anchor coordinate:
    //
    //   cin = -1   ->  line 65536, identical to the legal cin = 0
    //   cin = -4   ->  line 65408, a real neighbouring line
    //   cin = 512  ->  line 81920, one past CIN, still inside the tensor
    //   kw  = 3    ->  line 98304, one past KW, still inside the tensor
    //   kh  = -1   ->  line -32767, which then gives locate a negative set
    //
    // The first four are silently wrong hit rates. The last is worse: a
    // negative line reaches locate, signed % follows its dividend, and the
    // resulting negative set index subscripts a cache array out of bounds.
    //
    // Note what this means for the signedness argument in types.h. Signedness
    // alone does NOT keep a bad coordinate visible: integer division truncates
    // toward zero, so any cin in [-(cin_block-1), -1] lands on block 0 rather
    // than going negative. Only this check catches those.
    //
    // Affordable because expand calls line_of once per burst, for the anchor,
    // and then walks the run by adding a fixed line stride.
    if (c.kh  < 0 || c.kh  >= shape_.KH  || c.kw   < 0 || c.kw   >= shape_.KW ||
        c.cin < 0 || c.cin >= shape_.CIN || c.cout < 0 || c.cout >= shape_.COUT) {
        throw_outside_tensor(c, shape_);
    }
    const std::int64_t cin_blk  = c.cin  / cin_block_;
    const std::int64_t cout_blk = c.cout / cout_block_;
    // The whole flatten stays signed, LineId included, so an out-of-range
    // coordinate stays visibly negative rather than wrapping into a plausible
    // neighbouring line under -DNDEBUG. One widening cast to start the
    // expression in 64 bits is all this needs; there is no signedness boundary
    // left to cross.
    return ((static_cast<LineId>(c.kh) * shape_.KW + c.kw) * n_cin_blocks_ + cin_blk)
           * n_cout_blocks_ + cout_blk;
}

void BlockPackMapper::expand(const Burst& b, std::vector<LineId>& out) const {
    if (b.count < 0) {
        // Split from the empty case below, which used to swallow both. A count
        // of 0 is a legitimately empty run; a negative count is malformed, and
        // treating it as empty made a corrupt trace quietly drop one core's
        // demand for that tick while a corrupt stride stopped the run. Both are
        // trace-sourced, so both fail the same way now.
        throw std::invalid_argument("BlockPackMapper: burst count must not be negative");
    }
    if (b.count == 0) {
        return;  // an empty run touches nothing
    }
    if (b.stride <= 0) {
        throw std::invalid_argument("BlockPackMapper: burst stride must be positive");
    }

    // Widen before multiplying, matching the strided loop below. In 32 bits
    // count * stride wraps (count=100001, stride=30000 gives -1294967296),
    // which makes the bound check pass on exactly the runs that leave the
    // tensor furthest, and signed overflow is UB besides.
    const std::int32_t start_coord = coord_on(b.anchor, b.axis);
    const std::int64_t last_coord  = start_coord
                                   + static_cast<std::int64_t>(b.count - 1) * b.stride;
    // Throws rather than asserts, unlike the per-element checks in line_of.
    // A burst comes from the trace, which is external input, so the check has
    // to survive the sweep build's -DNDEBUG: it is the only thing standing
    // between a malformed trace and line ids that are wrong but look fine.
    // Affordable because it runs once per burst, not once per element, and a
    // burst averages tens of elements across the corpus.
    // The `start_coord < 0` half is redundant with line_of's own check below,
    // since start_coord is just the anchor's coordinate on this axis and
    // line_of now validates all four. Mutation testing confirms it: removing
    // this half alone changes no observable behaviour, because line_of throws
    // the same std::out_of_range a few lines later. It is kept so expand's
    // contract is self-contained rather than depending on the order in which
    // it happens to call line_of. The `last_coord` half is NOT redundant and
    // is the reason this check exists: line_of only ever sees the anchor, so
    // nothing else looks at where the run ENDS.
    if (start_coord < 0 || last_coord >= shape_.extent(b.axis)) {
        throw std::out_of_range("BlockPackMapper::expand: burst leaves the weight tensor");
    }

    // The run varies exactly one axis, so every line it touches sits at a
    // fixed LineId step from the anchor's line.
    const LineId       base      = line_of(b.anchor);
    const LineId       step      = line_stride(b.axis);
    const std::int32_t blk       = block_len(b.axis);
    const std::int64_t first_blk = start_coord / blk;

    if (b.stride == 1) {
        // Unit stride visits every element in [start, last], so the blocks
        // touched are the contiguous range [first_blk, last_blk].
        const std::int64_t last_blk = last_coord / blk;
        // Deliberately no reserve here. reserve(size + n) sets capacity to
        // exactly size + n, leaving zero slack, so it defeats push_back's
        // geometric growth and makes every later append into a shared buffer
        // reallocate and copy the whole running vector. push_back amortizes
        // correctly on its own. Only the caller knows the per-tick total
        // across cores, so the one useful reserve is hoisted into its loop.
        for (std::int64_t bi = first_blk; bi <= last_blk; ++bi) {
            out.push_back(base + (bi - first_blk) * step);
        }
        return;
    }

    // Strided runs can skip whole blocks, so walk the elements and keep the
    // block index only when it changes. The run is monotonically increasing,
    // so comparing against the previous block is a complete deduplication.
    std::int64_t prev_blk = first_blk;
    out.push_back(base);
    for (std::int32_t i = 1; i < b.count; ++i) {
        const std::int64_t cur_blk = (start_coord + static_cast<std::int64_t>(i) * b.stride) / blk;
        if (cur_blk != prev_blk) {
            out.push_back(base + (cur_blk - first_blk) * step);
            prev_blk = cur_blk;
        }
    }
}

SetIndex BlockPackMapper::locate(LineId line, std::int64_t num_sets) const {
    if (num_sets <= 0) {
        // Config-sourced: num_sets is derived from cache_size_bytes,
        // associativity and the line size in the YAML (plan 3.5), so it has
        // to fail in the sweep build too, not only under assertions.
        throw std::invalid_argument("BlockPackMapper: num_sets must be positive");
    }
    // Throws rather than asserts. This was an assert on the grounds that any
    // line reaching locate came from expand or line_of on this same mapper, so
    // it was an internal invariant. The signedness change invalidated that
    // reasoning: signed % follows the sign of its dividend, so a negative line
    // now yields a NEGATIVE set index, and a caller subscripting its set
    // storage with it reads out of bounds. Measured: locate(-32767, 1024)
    // returns set_index -1023, which a 32-way array turns into slot -32736.
    // Under the previous unsigned LineId a garbage line still produced an
    // in-range set index, so this is the one place the migration traded a
    // defined-but-wrong answer for undefined behaviour. Two comparisons on the
    // probe path is the right price for closing it.
    if (line < 0 || line >= num_lines_) {
        throw std::out_of_range("BlockPackMapper::locate: line " + std::to_string(line) +
                                " is outside [0, " + std::to_string(num_lines_) + ")");
    }

    // Index by the flattened LineId itself. The previous simulator indexed by
    // the sum of a line's tensor coordinates, which is not a bijection onto a
    // dense range, so most sets were unreachable: over a 4-sizes x
    // 3-line-sizes x 6-structures x 8-layers grid, a quarter of the points
    // lost sets, the worst case reached only 3% of them, and direct-mapped
    // configurations suffered most. `line` is already the mixed-radix flatten
    // of (kh, kw, cin_blk, cout_blk) produced by line_of, so it is a
    // bijection onto the dense range [0, num_lines_). Consecutive lines
    // therefore land in consecutive sets, and every set is reachable whenever
    // the layer has at least num_sets distinct lines.
    //
    // LineId, num_sets and both SetIndex fields are all signed, so this needs
    // no cast at all. It used to need two, and the range check above is what
    // keeps `line` non-negative so the signed % cannot return a negative index.
    SetIndex placement;
    placement.set_index = line % num_sets;
    // The tag is what distinguishes two lines sharing a set. By the division
    // identity, line == tag * num_sets + set_index with
    // 0 <= set_index < num_sets, so (tag, set_index) reconstructs `line`
    // uniquely and comparing tags within the matched set is a complete
    // line-identity check, never an aliasing one.
    placement.tag = line / num_sets;
    return placement;
}

}  // namespace wcache
