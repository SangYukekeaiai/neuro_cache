// Layout construction belongs to the library, not to either CLI driver.
#pragma once

#include <memory>
#include <vector>

#include "cachesim/config.h"
#include "cachesim/layout/mapper.h"

namespace cachesim {

std::unique_ptr<AddressMapper> make_mapper(const RunConfig& cfg,
                                           const WeightShape& shape,
                                           std::vector<Warning>& warnings);

}  // namespace cachesim
