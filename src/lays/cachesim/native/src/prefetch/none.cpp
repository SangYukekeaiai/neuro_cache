#include "cachesim/prefetch/none.h"

namespace cachesim {

void NoPrefetcher::on_demand(const PrefetchContext&, std::vector<PrefetchTarget>&) {}

}  // namespace cachesim
