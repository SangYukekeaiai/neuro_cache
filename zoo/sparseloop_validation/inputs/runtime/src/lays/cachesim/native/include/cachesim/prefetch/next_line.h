#pragma once

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

class NextLinePrefetcher final : public Prefetcher {
public:
    explicit NextLinePrefetcher(std::int32_t distance = 1);

    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) override;

private:
    std::int32_t distance_;
};

}  // namespace cachesim
