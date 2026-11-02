#include "cachesim/prefetch/next_tile.h"

#include <algorithm>
#include <stdexcept>
#include <string>

namespace cachesim {

NextTilePrefetcher::NextTilePrefetcher(std::int32_t distance, std::int32_t min_touches)
    : distance_(distance), min_touches_(min_touches) {
    if (distance < 1) {
        throw std::invalid_argument("NextTilePrefetcher: distance must be >= 1, got " +
                                    std::to_string(distance));
    }
    if (min_touches < 0) {
        throw std::invalid_argument("NextTilePrefetcher: min_touches must be >= 0, got " +
                                    std::to_string(min_touches));
    }
}

bool NextTilePrefetcher::on_access(LineId line, std::int32_t tile) {
    TouchRecord& rec = touches_[line.get()];
    if (rec.tile != tile) {
        rec.tile  = tile;
        rec.count = 0;
    }
    ++rec.count;
    return rec.count == std::max(min_touches_, std::int32_t{1});
}

void NextTilePrefetcher::on_demand(const PrefetchContext& ctx,
                                  std::vector<PrefetchTarget>& out) {
    if (!ctx.retrigger && min_touches_ > 0) {
        const auto rec = touches_.find(ctx.line.get());
        const std::int32_t count =
            (rec != touches_.end() && rec->second.tile == ctx.tile) ? rec->second.count : 0;
        if (count < min_touches_) {
            ++filtered_;
            return;
        }
    }
    for (std::int32_t i = 0; i < distance_; ++i) {
        if (const auto line = ctx.mapper.neighbour(ctx.line, Axis::COUT, i + 1)) {
            out.push_back(PrefetchTarget{*line, ctx.k});
        }
    }
}

}  // namespace cachesim
