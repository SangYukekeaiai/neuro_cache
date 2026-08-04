#pragma once
// Port of cache.py: reduces all 3 declared cache types to (num_sets,
// ways), same formulas as _num_sets_and_ways, and composes num_sets
// independent LRUPolicy instances the same way the Cache class does --
// cache_type (structural) and policy (eviction) stay independent axes
// here too, not one hardcoded class per (type, policy) pair.
#include <cstdint>
#include <vector>

#include "config.h"
#include "policy.h"

namespace cachesim {

inline void num_sets_and_ways(const CacheConfig &cfg, int64_t &num_sets, int64_t &ways) {
    int64_t capacity = cfg.capacity_lines();
    switch (cfg.cache_type) {
        case CacheType::FullyAssociative:
            num_sets = 1;
            ways = capacity;
            return;
        case CacheType::DirectMapped:
            num_sets = capacity;
            ways = 1;
            return;
        case CacheType::SetAssociative:
            ways = cfg.associativity;
            num_sets = capacity / ways;
            if (num_sets < 1) num_sets = 1;
            return;
    }
    throw std::runtime_error("cachesim: unreachable cache_type"); // CacheType is exhaustive above
}

class Cache {
public:
    explicit Cache(const CacheConfig &cfg) {
        require_policy_implemented(cfg.policy);
        num_sets_and_ways(cfg, num_sets_, ways_);
        sets_.reserve(size_t(num_sets_));
        for (int64_t i = 0; i < num_sets_; ++i) sets_.emplace_back(ways_);
    }

    bool access(int64_t packed_tag) { return sets_[size_t(set_index(packed_tag))].access(packed_tag); }

    // access() honoring this tick's pin set on eviction -- see policy.h's
    // PinStamps. The pin set is passed whole, not filtered to this set:
    // only lines resident in the set are ever eviction candidates, so
    // pinned tags belonging to other sets simply never come up.
    bool access_pinned(int64_t packed_tag, const PinStamps &pins) {
        return sets_[size_t(set_index(packed_tag))].access_pinned(packed_tag, pins);
    }

    // Residency only, no recency move and no insert on a miss -- see
    // policy.h's contains for why hierarchy.h needs the question asked
    // this way.
    bool contains(int64_t packed_tag) const { return sets_[size_t(set_index(packed_tag))].contains(packed_tag); }

    // Recency stamp of a resident line -- see policy.h's stamp.
    int64_t stamp(int64_t packed_tag) const { return sets_[size_t(set_index(packed_tag))].stamp(packed_tag); }

private:
    // _set_index: packed_tag % num_sets, degenerating to always 0 when
    // num_sets == 1 (fully-associative) -- same rule as cache.py.
    int64_t set_index(int64_t packed_tag) const {
        return num_sets_ > 1 ? ((packed_tag % num_sets_) + num_sets_) % num_sets_ : 0;
    }

    int64_t num_sets_ = 0, ways_ = 0;
    std::vector<LRUPolicy> sets_;
};

} // namespace cachesim
