#pragma once

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

class NoPrefetcher final : public Prefetcher {
public:
    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>&) override;
};

}  // namespace cachesim
