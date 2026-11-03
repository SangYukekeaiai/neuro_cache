// What the two native drivers write and measure, stated once.
//
// This is app support rather than library code: the CSV text and padding
// diagnostic belong to the driver boundary, while the engine owns the
// simulation counters. Keeping the measurement here is important because a
// padding fraction that differed between a run and a sweep of the same
// configuration would look like a cache effect.
#pragma once

#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "cachesim/layout/mapper.h"
#include "cachesim/trace/stream_format.h"
#include "cachesim/trace/stream_trace.h"
#include "cachesim/types.h"

namespace cachesim {
namespace app {

// D1's `l1_demand_reserve` default, which validate() needs before any burst has
// been decoded. Asked of the MAPPER rather than computed as
// `burst_span / cout_block`: the division is only right when the burst walks
// COUT, and a trace that bursts along CIN or KH would silently get a reserve
// sized for the wrong axis. Ruling Q-D put `burst_span` in the header, so the
// widest burst the layer can hold is expandable here, at the origin.
//
// The mapper handed in need not be the one the run will use, and both drivers
// pass a BlockPackMapper here even when cfg.layout says split_cin. A burst
// covers a fixed set of BLOCK coordinates, and every mapper is injective on
// those, so the COUNT is the same under any nesting; only the ids differ. The
// alternative is a chicken and egg, since validate() is what resolves the
// width the real mapper is built from. test_split_cin pins the equality this
// rests on over the corpus burst and a sweep of others.
inline std::int32_t lines_per_burst(const AddressMapper& mapper,
                                    const stream::StreamHeader& hdr) {
    const Burst widest{Coord{0, 0, 0, 0}, hdr.burst_dim, hdr.burst_span, hdr.burst_stride};
    std::vector<LineId> lines;
    mapper.expand(widest, lines);
    return static_cast<std::int32_t>(lines.size());
}

// The `padding_fraction` column: the share of the weight elements pulled into
// L1 that no burst ever consumed,
//
//   (lines_touched * elements_per_line - distinct_elements) / (lines_touched * elements_per_line)
//
// Per RUN and not per burst, which is the reading ruled at open question Q-G:
// two bursts sharing a line pay for that line's padding once. It is a property
// of the LAYOUT and the trace rather than of a cache, so one meter serves a
// whole sweep: every point of a sweep shares one mapper by construction.
//
// Both sets are bitmaps rather than hash sets because they are dense and known
// in size: a 3x3x512x512 layer is 2.4M elements, which is 300 KB as bits and
// well over a hundred megabytes as an unordered_set.
class PaddingMeter {
public:
    PaddingMeter(const AddressMapper& mapper, const WeightShape& shape,
                 std::int64_t elements_per_line)
        : mapper_(mapper),
          shape_(shape),
          elements_per_line_(elements_per_line),
          line_seen_(static_cast<std::size_t>(mapper.num_lines().get()), false),
          element_seen_(static_cast<std::size_t>(shape.KH) * static_cast<std::size_t>(shape.KW) *
                            static_cast<std::size_t>(shape.CIN) *
                            static_cast<std::size_t>(shape.COUT),
                        false) {}

    void observe(const Burst& b) {
        mapper_.expand(b, lines_);
        for (const LineId& l : lines_) line_seen_[static_cast<std::size_t>(l.get())] = true;
        lines_.clear();
        for (std::int32_t k = 0; k < b.count; ++k) {
            Coord c = b.anchor;
            const std::int32_t step = k * b.stride;
            switch (b.axis) {
                case Axis::KH:   c.kh += step;   break;
                case Axis::KW:   c.kw += step;   break;
                case Axis::CIN:  c.cin += step;  break;
                case Axis::COUT: c.cout += step; break;
            }
            element_seen_[element_index(c)] = true;
        }
    }

    // Every burst of the window tile, for a driver that has just advanced it.
    void observe_tile(const StreamingTileTrace& trace) {
        const std::int32_t tile = trace.window_tile();
        for (std::int32_t c = 0; c < trace.n_cores(); ++c) {
            const CoreId core{c};
            const std::int32_t n = trace.n_bursts(core, tile);
            for (std::int32_t k = 0; k < n; ++k) observe(trace.burst(core, tile, BurstIndex{k}));
        }
    }

    // Zero when nothing was touched: there is no padding in a layer no burst
    // read, and the alternative is a NaN in a column an analysis averages.
    double fraction() const {
        std::int64_t lines = 0;
        for (bool seen : line_seen_) lines += seen ? 1 : 0;
        std::int64_t elements = 0;
        for (bool seen : element_seen_) elements += seen ? 1 : 0;
        const std::int64_t fetched = lines * elements_per_line_;
        if (fetched == 0) return 0.0;
        return static_cast<double>(fetched - elements) / static_cast<double>(fetched);
    }

private:
    std::size_t element_index(const Coord& c) const {
        const std::int64_t i =
            ((static_cast<std::int64_t>(c.kh) * shape_.KW + c.kw) * shape_.CIN + c.cin) *
                shape_.COUT + c.cout;
        return static_cast<std::size_t>(i);
    }

    const AddressMapper& mapper_;
    WeightShape          shape_;
    std::int64_t         elements_per_line_;
    std::vector<bool>    line_seen_;
    std::vector<bool>    element_seen_;
    std::vector<LineId>  lines_;
};

inline void write_out(const std::string& out_path, const std::string& text) {
    if (out_path == "-") {
        std::cout << text;
        std::cout.flush();
        return;
    }
    std::ofstream out(out_path);
    if (!out) throw std::runtime_error("cannot write " + out_path);
    out << text;
}

}  // namespace app
}  // namespace cachesim
