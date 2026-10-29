#pragma once

#include <cstdint>

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

// Stateless L2 policy: emit the next distance COUT blocks, forward only.
// PrefetchParams::axis, up and down are ignored; the axis is always COUT
// and each step is one block. Targets outside the COUT extent are skipped.
class NextTilePrefetcher final : public Prefetcher {
public:
    explicit NextTilePrefetcher(std::int32_t distance);

    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) override;

private:
    std::int32_t distance_;
};

}  // namespace cachesim
