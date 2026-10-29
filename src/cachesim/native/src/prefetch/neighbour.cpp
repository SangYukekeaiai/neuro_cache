#include "cachesim/prefetch/neighbour.h"

#include <stdexcept>
#include <string>

namespace cachesim {

NeighbourPrefetcher::NeighbourPrefetcher(Axis axis,
                                         std::int32_t distance,
                                         bool up,
                                         bool down)
    : axis_(axis), distance_(distance), up_(up), down_(down) {
    if (distance < 1) {
        throw std::invalid_argument("NeighbourPrefetcher: distance must be >= 1, got " +
                                    std::to_string(distance));
    }
    if (!up && !down) {
        throw std::invalid_argument("NeighbourPrefetcher: both directions are off");
    }
}

void NeighbourPrefetcher::on_demand(const PrefetchContext& ctx,
                                    std::vector<PrefetchTarget>& out) {
    // Near first, both ways, so that a budget that runs out part way through
    // spends what it had on the closest lines rather than the furthest.
    for (std::int32_t d = 1; d <= distance_; ++d) {
        if (up_) {
            if (const auto line = ctx.mapper.neighbour(ctx.line, axis_, d)) {
                out.push_back(PrefetchTarget{*line, ctx.k});
            }
        }
        if (down_) {
            if (const auto line = ctx.mapper.neighbour(ctx.line, axis_, -d)) {
                out.push_back(PrefetchTarget{*line, ctx.k});
            }
        }
    }
}

}  // namespace cachesim
