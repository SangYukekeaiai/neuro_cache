#include "cachesim/prefetch/next_burst.h"

#include <cstddef>
#include <stdexcept>
#include <string>

namespace cachesim {

NextBurstPrefetcher::NextBurstPrefetcher(std::int32_t distance, std::int32_t n_cores)
    : distance_(distance) {
    if (distance < 1) {
        throw std::invalid_argument("NextBurstPrefetcher: distance must be >= 1, got " +
                                    std::to_string(distance));
    }
    if (n_cores < 1) {
        throw std::invalid_argument("NextBurstPrefetcher: n_cores must be >= 1, got " +
                                    std::to_string(n_cores));
    }
    const std::size_t n = static_cast<std::size_t>(n_cores);
    pf_cursor_.assign(n, 0);
    last_tile_.assign(n, -1);
    last_burst_.assign(n, -1);
}

BurstIndex NextBurstPrefetcher::pf_cursor(CoreId core) const {
    return BurstIndex{pf_cursor_.at(static_cast<std::size_t>(core.get()))};
}

void NextBurstPrefetcher::on_tile_start(CoreId core) {
    const std::size_t c = static_cast<std::size_t>(core.get());
    pf_cursor_.at(c) = 0;
    last_tile_.at(c) = -1;
    last_burst_.at(c) = -1;
}

void NextBurstPrefetcher::on_demand(const PrefetchContext& ctx,
                                    std::vector<PrefetchTarget>& out) {
    const std::size_t c = static_cast<std::size_t>(ctx.core.get());
    // A burst has several lines. The engine asks once per line so the same
    // policy also supports Neighbour at either level; NextBurst emits each
    // burst in its once-per-burst issue order.
    if (last_tile_.at(c) == ctx.tile && last_burst_.at(c) == ctx.k.get()) return;
    last_tile_.at(c)  = ctx.tile;
    last_burst_.at(c) = ctx.k.get();

    std::int32_t& cursor = pf_cursor_.at(c);
    const std::int32_t next = ctx.k.get() + 1;
    // A budget can stop issue part way through a burst, leaving the cursor on
    // that burst until the level reports a complete issue. Once the core has
    // advanced, however, every burst through `ctx.k` is its business and must
    // not be prefetched again. This pull-forward is deliberately unconditional.
    if (cursor < next) cursor = next;
    const std::int32_t last = ctx.k.get() + distance_;
    const std::int32_t n_bursts = ctx.trace.n_bursts(ctx.core, ctx.tile);

    // Cursor advancement is feedback from the level: only a fully issued burst
    // reaches on_issued. A partial burst therefore leaves the cursor unchanged
    // until this hook's next demand applies the pull-forward above.
    for (std::int32_t burst = cursor; burst <= last && burst < n_bursts; ++burst) {
        lines_.clear();
        ctx.mapper.expand(ctx.trace.burst(ctx.core, ctx.tile, BurstIndex{burst}), lines_);
        for (const LineId line : lines_) {
            out.push_back(PrefetchTarget{line, BurstIndex{burst}});
        }
    }
}

void NextBurstPrefetcher::on_issued(CoreId core, BurstIndex last_complete_burst) {
    std::int32_t& cursor = pf_cursor_.at(static_cast<std::size_t>(core.get()));
    const std::int32_t next = last_complete_burst.get() + 1;
    if (cursor < next) cursor = next;
}

}  // namespace cachesim
