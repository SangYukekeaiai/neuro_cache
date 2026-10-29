#include "cachesim/prefetch/prefetcher.h"

#include <stdexcept>
#include <string>

#include "cachesim/prefetch/neighbour.h"
#include "cachesim/prefetch/next_burst.h"
#include "cachesim/prefetch/none.h"

namespace cachesim {

std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind kind,
                                            PrefetchParams params,
                                            std::int32_t n_cores) {
    switch (kind) {
        case PrefetchKind::None:
            if (params.distance < 0) {
                throw std::invalid_argument("make_prefetcher: distance must be >= 0, got " +
                                            std::to_string(params.distance));
            }
            return std::make_unique<NoPrefetcher>();
        case PrefetchKind::NextBurst:
            return std::make_unique<NextBurstPrefetcher>(params.distance, n_cores);
        case PrefetchKind::Neighbour:
            return std::make_unique<NeighbourPrefetcher>(params.axis, params.distance, params.up,
                                                         params.down);
    }
    throw std::invalid_argument("make_prefetcher: unknown PrefetchKind");
}

}  // namespace cachesim
