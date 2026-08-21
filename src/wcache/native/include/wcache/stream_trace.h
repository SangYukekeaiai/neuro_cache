// StreamingTileTrace: a TileTrace served from a WCTS stream through a one-tile
// sliding window. Plan v3 unit A3, plan D Tasks 2 and 3.
//
// The engine never learns which reader it has (decisions B10, B23), so this
// class implements trace.h's seven pure virtuals unchanged and adds the window
// controls beside them. Only the driver calls `advance()`.
//
// The window is one whole tile and cannot be finer, because `tile_tail` is
// `mac_cycles - max_tick` and `max_tick` is a maximum over every core in the
// tile: no part of a tile can be answered for until all of it has arrived.
//
// The four per-(core, tile) queries answer only for the tile the window holds.
// Any other tile throws std::out_of_range naming both indices, which is what
// makes a lockstep-driver bug loud instead of silently wrong. Two per-tile
// scalars are retained for every tile already streamed, because
// `Engine::barrier_arrive` reads `tile_tail` for the tile that is ending, after
// the window may have moved on, and because `tick_base` accumulates from
// `mac_cycles` for the V1 check. At 128 tiles that is 2 KB.
#pragma once

#include <cstdint>
#include <vector>

#include "wcache/byte_source.h"
#include "wcache/stream_format.h"
#include "wcache/trace.h"
#include "wcache/types.h"

namespace wcache {

class StreamingTileTrace final : public TileTrace {
public:
    // Reads and validates the stream header immediately, then leaves the window
    // EMPTY: `window_tile()` is -1 until the first `advance()`. Throws
    // std::invalid_argument (a bad header) or std::runtime_error (a truncated
    // one). `src` must outlive the trace.
    explicit StreamingTileTrace(ByteSource& src);

    // --- TileTrace, the seven pure virtuals, unchanged in signature ---------
    std::int32_t n_tiles() const override;
    std::int32_t n_cores() const override;
    std::int32_t n_bursts(CoreId core, std::int32_t tile) const override;
    const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick tile_tail(std::int32_t tile) const override;

    // --- the window, which the ENGINE never touches -------------------------
    // -1 before the first advance(), otherwise the one tile the four
    // per-(core, tile) queries answer for.
    std::int32_t window_tile() const { return window_; }

    // Decodes the next tile frame. Returns false at the trailer, having
    // verified the end magic and the total burst count. Throws when
    // `tile_index` is not the expected counter, when a core id is out of range
    // or not ascending, when a local_tick is not ascending, when
    // `run_end <= run_start`, or when the derived tile_tail is below 1.
    bool advance();

    // G14's diagnostic, for the window tile only: how many DISTINCT address
    // records this core touches in it.
    //
    // Distinct ADDRESS TUPLES, not distinct lines. A line count depends on the
    // layout (`cin_block`, `cout_block`), which is a property of the run
    // configuration, and the trace has no configuration and no mapper; the
    // tuple count is a property of the trace alone. It is also the quantity
    // §1.3's survey measured (24 addresses per core per tile), so it is the one
    // comparable to it. Two burst records are the same address when the whole
    // on-disk 5-tuple matches: [kh, kw, cin, run_start, run_end]. The axis and
    // the stride are header-wide and cannot tell two records of one stream
    // apart, so they are not part of the key.
    //
    // Throws std::out_of_range when the window is empty or `core` is outside
    // [0, n_cores), for the reason the four per-(core, tile) queries do: a
    // driver bug must be loud rather than silently wrong.
    std::int32_t distinct_addresses(CoreId core) const;

    // --- header and per-tile scalars, for D1, D2 and the V1 check ------------
    const stream::StreamHeader& header() const { return header_; }

    // Retained for every tile already streamed.
    std::int64_t mac_cycles(std::int32_t tile) const;

    // Running sum of mac_cycles over tiles [0, tile). tick_base(0) == 0.
    // Defined for every tile already streamed plus one past it.
    std::int64_t tick_base(std::int32_t tile) const;

private:
    void require_window(std::int32_t tile) const;
    void require_core(CoreId core) const;
    void require_streamed(std::int32_t tile, const char* what) const;
    void read_trailer();

    ByteSource*          src_;
    stream::StreamHeader header_;

    // The window: one tile's payload, refilled by advance() and never
    // reallocated in steady state.
    std::vector<Burst>        bursts_;
    std::vector<std::int64_t> ticks_;
    std::vector<std::int32_t> core_begin_;  // per core, offset into bursts_/ticks_
    std::vector<std::int32_t> core_end_;
    std::vector<unsigned char> frame_;      // the raw payload of the window tile

    // Retained for every tile already streamed.
    std::vector<std::int64_t> mac_cycles_;
    std::vector<std::int64_t> tile_tail_;
    std::vector<std::int64_t> tick_base_;   // size n_tiles + 1

    std::int32_t  window_       = -1;
    std::int32_t  streamed_     = 0;   // tiles decoded so far
    std::uint64_t bursts_seen_  = 0;
    bool          at_end_       = false;
};

// The tensor the stream describes, read out of the header's dim extents. Every
// consumer that builds a mapper needs it, so it is stated here once rather than
// once per program. Throws std::invalid_argument naming the missing dim code.
WeightShape shape_of(const stream::StreamHeader& hdr);

}  // namespace wcache
