// Shared LineId -> cache placement rule.
#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>

#include "cachesim/layout/mapper.h"

namespace cachesim {

// Coordinate flattening belongs to each layout. Once a LineId exists, every
// layout uses the same modulo mapping into a set and tag.
inline Placement set_index(LineId line, std::int64_t num_sets) {
    if (num_sets < 1) {
        throw std::invalid_argument("set_index: num_sets must be >= 1, got " +
                                    std::to_string(num_sets));
    }
    const std::int64_t value = line.get();
    if (value < 0) {
        throw std::out_of_range("set_index: line id must be non-negative, got " +
                                std::to_string(value));
    }
    return Placement{SetIndex{value % num_sets}, TagId{value / num_sets}};
}

}  // namespace cachesim
