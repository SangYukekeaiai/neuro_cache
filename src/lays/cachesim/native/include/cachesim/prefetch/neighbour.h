#pragma once

#include <cstdint>

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

class NeighbourPrefetcher final : public Prefetcher {
public:
    NeighbourPrefetcher(Axis axis, std::int32_t distance, bool up, bool down);

    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) override;

    Axis         axis() const { return axis_; }
    std::int32_t distance() const { return distance_; }
    bool         up() const { return up_; }
    bool         down() const { return down_; }

private:
    Axis         axis_;
    std::int32_t distance_;
    bool         up_;
    bool         down_;
};

}  // namespace cachesim
