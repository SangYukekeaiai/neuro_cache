#include "cachesim/prefetch/next_line.h"

#include <algorithm>
#include <stdexcept>

namespace cachesim {

NextLinePrefetcher::NextLinePrefetcher(std::int32_t distance) : distance_(distance) {
    if (distance < 1) {
        throw std::invalid_argument("NextLinePrefetcher: distance must be >= 1");
    }
}

void NextLinePrefetcher::on_demand(const PrefetchContext& ctx,
                                 std::vector<PrefetchTarget>& out) {
    const auto line = ctx.line.get();
    const auto end = ctx.mapper.num_lines().get();
    if (line < 0 || line >= end) {
        throw std::out_of_range("NextLinePrefetcher: demand line outside layer extent");
    }
    // Bound before adding: the final line never wraps into another tensor.
    const auto degree = std::min<std::int64_t>(distance_, end - line - 1);
    for (std::int64_t d = 1; d <= degree; ++d) {
        out.push_back(PrefetchTarget{LineId{line + d}, ctx.k});
    }
}

}  // namespace cachesim
