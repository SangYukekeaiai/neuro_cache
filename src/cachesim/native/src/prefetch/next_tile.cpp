#include "cachesim/prefetch/next_tile.h"

#include <stdexcept>
#include <string>

namespace cachesim {

NextTilePrefetcher::NextTilePrefetcher(std::int32_t distance) : distance_(distance) {
    if (distance < 1) {
        throw std::invalid_argument("NextTilePrefetcher: distance must be >= 1, got " +
                                    std::to_string(distance));
    }
}

void NextTilePrefetcher::on_demand(const PrefetchContext& ctx,
                                  std::vector<PrefetchTarget>& out) {
    for (std::int32_t i = 0; i < distance_; ++i) {
        if (const auto line = ctx.mapper.neighbour(ctx.line, Axis::COUT, i + 1)) {
            out.push_back(PrefetchTarget{*line, ctx.k});
        }
    }
}

}  // namespace cachesim
