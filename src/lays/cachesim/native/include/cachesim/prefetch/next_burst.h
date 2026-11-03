#pragma once

#include <cstdint>
#include <vector>

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

// The trace's burst queue is resolved when a tile starts, so this policy can
// fetch ahead without predicting a future address. The cursor is per core and
// resets at the tile boundary; it is policy state, while the L1/L2 credit and
// port mechanics remain in the owning CacheLevel/Engine.
class NextBurstPrefetcher final : public Prefetcher {
public:
    NextBurstPrefetcher(std::int32_t distance, std::int32_t n_cores);

    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) override;
    void on_tile_start(CoreId core) override;
    void on_issued(CoreId core, BurstIndex last_complete_burst) override;

    std::int32_t distance() const { return distance_; }
    BurstIndex pf_cursor(CoreId core) const;

private:
    std::int32_t distance_;
    std::vector<std::int32_t> pf_cursor_;
    std::vector<std::int32_t> last_tile_;
    std::vector<std::int32_t> last_burst_;
    std::vector<LineId> lines_;
};

}  // namespace cachesim
