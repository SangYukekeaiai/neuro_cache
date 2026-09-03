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
#include <optional>
#include <string>
#include <vector>

#include "wcache/types.h"

namespace wcache {

// Which memory layout a run uses.
//
// A config knob and not a compile-time choice, for the reason PolicyKind is
// one: the study COMPARES layouts, and the comparison only means anything if
// the two runs differ in this field and nothing else. A build flag would make
// the two halves of the comparison two different binaries.
//
// The vocabulary lives beside AddressMapper rather than in config.h because
// the module that owns the thing owns the name of the thing. A mapper added
// later needs an enumerator here, a spelling in config.cpp, and a branch at
// the two construction sites; nothing else in the tree learns the list.
//
//     BlockPack  BlockPackMapper, nesting [KH][KW][cin_blk][cout_blk]
//     SplitCin   SplitCinMapper,  nesting [KH][KW][cin_hi][cout_blk][cin_lo]
//     KhkwSplit  KhkwSplitMapper, nesting [pos_hi][cout_blk][cin_blk][pos_lo],
//                where pos = kh * KW + kw split at min(8, KH*KW)
//
// Both mappers answer the same interface below, so the engine still never
// learns which one it has. What changes is which line a coordinate lands on,
// and therefore which set the line lands in.
enum class LayoutKind : std::uint8_t {
    BlockPack = 0,
    SplitCin  = 1,
    KhkwSplit = 2,
};

// Where a line sits in a set-associative array: which set holds it, and the
// value that tells it apart from the other lines mapping to that same set.
//
// Both fields are tagged scalars over int64 rather than raw int64. A set index
// and a tag are two quantities a set-associative array holds side by side, and
// as raw ints either one flows into a LineId, a SimTime, a future 64-bit slot
// handle, or the other, with no diagnostic and no width to catch it. Naming
// them is what makes such a line fail to compile (N12).
//
// The identity that defines the pair is
//
//     line == tag * num_sets + set_index
//
// and that is the form to read, to check an implementation against, and to keep
// in this comment. In code each field is unwrapped, so the same equation is
// spelled `p.tag.get() * num_sets + p.set_index.get() == line.get()`; the
// `.get()`s are the price of the naming above and carry no meaning of their
// own. The same holds for the bound the set index owes,
// `0 <= set_index < num_sets`, which is not vacuously true because the
// representation underneath stays signed.
//
// Named Placement, not SetIndex: it holds two fields, and "index" reads as
// one. `SetIndex` is the tagged scalar for the first field (B9) and `TagId` is
// its sibling for the second, so a policy handed a SlotId where a set index
// belongs, or a tag where a line id belongs, fails to compile.
struct Placement {
    SetIndex set_index;  // in [0, num_sets)
    TagId    tag;
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
    // A burst along ANY axis. `b.axis` and `b.stride` come from the stream
    // header's `burst_dim` and `burst_stride`, which the trace generator emits
    // (ruling R1 of 2026-08-20, closing U27), and
    // every burst in today's corpus is COUT with stride 1, but a trace written
    // as [kh, kw, cout, cin_start, cin_end] bursts along CIN and is the same
    // struct. An implementation therefore reads the walked axis out of the
    // burst; it may not assume COUT, and it may not assume that the walked
    // axis is one it blocks. A burst along KH is legal and, under a
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
    // a stride is the step to the next element of the run, so neither is a run
    // a trace can describe, and both are malformed
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
    // The line `delta` BLOCKS along `a` from `line`, or nothing when that step
    // leaves the layer. Blocks, not elements: on CIN and COUT one step is one
    // `cin_block` / `cout_block`, and on KH and KW it is one row or column,
    // which is what `block_len` already measures.
    //
    // Here rather than in a prefetcher because the arithmetic is the layout's:
    // CIN is one digit at one stride under BlockPack and KhkwSplit and is SPLIT
    // across two digits under SplitCin, and a policy that knew which would be a
    // policy that had learned its layout. The engine holds an AddressMapper and
    // never learns which one it has, and this keeps that true for prefetching.
    //
    // Throws std::out_of_range for a `line` outside [0, num_lines()), and
    // std::logic_error for an Axis outside the enumerators.
    virtual std::optional<LineId> neighbour(LineId line, Axis a,
                                            std::int32_t delta) const = 0;

    virtual LineId num_lines() const = 0;

    // Bytes held by one line. On the interface rather than on the concrete
    // mapper because CacheLevel holds an AddressMapper and needs this to turn
    // the config's cache_size_bytes into a set count. Only the layout knows
    // how many elements a line packs, so only the layout can answer.
    virtual std::int64_t line_size_bytes() const = 0;

    // The factors line_size_bytes() is the product of, for a diagnostic that
    // has to be actionable rather than only true.
    //
    // SetAssociativeArray refuses a cache_size_bytes that is not a whole number
    // of lines, and a non-power-of-two line size is deliberately legal (B16),
    // so "65536 is not a whole number of 96-byte lines" leaves a reader with no
    // way to reach the config field that produced the 96. Only the layout knows
    // what a line packs, which is the same reason line_size_bytes() is on this
    // interface at all, so only the layout can name the terms.
    //
    // A default rather than a pure virtual, and the default is the bare
    // product. The cost of requiring it is out of proportion to a message: it
    // would oblige every AddressMapper in the tree, including every test fake,
    // to implement a function about diagnostics. The default is always correct
    // if uninformative, so a mapper whose line size does not decompose into
    // named factors is free to say nothing more.
    //
    // `line_bytes` is the line size the CALLER already read, and the default
    // prints that value rather than asking for it again. Without the argument
    // the default's body is std::to_string(line_size_bytes()), so one refusal
    // message asks one mapper for its line size twice; for a mapper whose
    // answer is not stable the "-byte lines" half and the bracketed half then
    // disagree, which is the failure the read-once discipline exists to
    // prevent. An override naming its own factors does not need the value and
    // may ignore it.
    virtual std::string line_size_terms(std::int64_t line_bytes) const {
        return std::to_string(line_bytes);
    }
};

}  // namespace wcache
