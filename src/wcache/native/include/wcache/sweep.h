// BroadcastSweep: N configurations over ONE pass of one stream. Plan D unit
// D3a, Task 17.
//
// A stream can be read once and a grid has many points, so the reader holds one
// tile window, every engine in the grid consumes that same tile, and the window
// moves only when all of them have finished it. Each engine keeps its own
// simulated clock and they diverge, which is fine: the window is indexed by
// TILE and not by cycle.
//
// Single-threaded and cooperative, with no threads and no coroutines.
// `Engine::step_tile` is what makes that possible, because it returns with the
// next barrier still queued, so every engine can be parked at the same tile
// seam while the window moves.
//
// Resident memory is one tile window plus N engine states, which is the whole
// point: nothing here buffers the stream.
#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

#include "wcache/config.h"
#include "wcache/engine.h"
#include "wcache/layout.h"
#include "wcache/stream_trace.h"

namespace wcache {

class BroadcastSweep {
public:
    // Called once per tile, after the window has moved and before any engine
    // consumes it. The driver owns the loop, so this is the only way a caller
    // can see a tile: the histogram, the padding meter and `--progress` all
    // arrive through it.
    using TileObserver = std::function<void(const StreamingTileTrace&)>;

    // `trace` and `mapper` must outlive the sweep. ONE mapper serves the whole
    // hierarchy and the whole grid, so every configuration must share its
    // LAYOUT (cin_block, cout_block, weight_bytes): a layout change would
    // change what a line is mid-stream. Throws std::invalid_argument naming the
    // first configuration that differs, or the layout the mapper was built for
    // when the grid asks for another one. A line size sweep is therefore
    // several sweeps, one per line size, each over its own pass of the stream.
    //
    // Also throws std::invalid_argument on an empty grid and on a grid larger
    // than `max_engines`, which exists so an oversized grid fails at startup
    // rather than by OOM three hours in.
    //
    // Every configuration must already be validated: `to_engine_params` refuses
    // one whose `l1_demand_reserve` is still the sentinel.
    BroadcastSweep(StreamingTileTrace& trace, const AddressMapper& mapper,
                   std::vector<RunConfig> configs, std::int32_t max_engines);

    // One pass. Advances the window tile by tile, letting every engine reach
    // that tile's barrier before the window moves, then finishes every engine.
    // Throws whatever an engine throws, with the offending configuration's
    // index prepended and its type kept.
    void run(const TileObserver& on_tile = TileObserver{});

    std::size_t      size() const { return engines_.size(); }
    const Engine&    engine(std::size_t i) const;
    // The mutable overload exists so a driver can attach an instrument to a
    // grid point after the sweep is built and before it runs, which is what
    // `wcache_sweep --oracle` does. It is NOT an invitation to steer the sweep
    // from outside: the tile loop is this class's, and the app is the layer
    // that knows which trace and which mapper the engines run (decisions B10
    // and B23), so an attach-oracles method here would put the app's knowledge
    // in the wrong file.
    Engine&          engine(std::size_t i);
    const RunConfig& config(std::size_t i) const;

    // Wall seconds spent inside engine dispatch for configuration i, for the
    // `sim_wall_seconds` column. Only dispatch is counted, so the reader's own
    // decoding is not charged to any one grid point.
    double wall_seconds(std::size_t i) const;

private:
    StreamingTileTrace*                  trace_;
    std::vector<RunConfig>               configs_;
    std::vector<std::unique_ptr<Engine>> engines_;
    std::vector<double>                  wall_;
};

}  // namespace wcache
