#pragma once
// Port of policy.py: per-set replacement-policy implementations. Only
// LRUPolicy is real, matching policy.py exactly -- the other names in
// config.POLICIES (fifo, lfu, random, input_activity) are declared but
// raise immediately on construction there, so require_policy_implemented
// raises the same way here, at Cache-construction time (cache.h), not on
// the first access().
#include <cstdint>
#include <list>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace cachesim {

// One cache SET's resident lines, `capacity` many, LRU eviction --
// same scope as policy.py's LRUPolicy: one set, not the whole cache.
// cache.h composes num_sets of these together, same as cache.py does.
class LRUPolicy {
public:
    explicit LRUPolicy(int64_t capacity) : capacity_(capacity) {
        if (capacity <= 0) throw std::runtime_error("LRUPolicy: capacity must be positive");
        map_.reserve(size_t(capacity) * 2);
    }

    bool access(int64_t tag) {
        auto it = map_.find(tag);
        if (it != map_.end()) {
            order_.erase(it->second);
            order_.push_front(tag);
            it->second = order_.begin();
            return true;
        }
        if (int64_t(order_.size()) >= capacity_) {
            int64_t victim = order_.back();
            order_.pop_back();
            map_.erase(victim);
        }
        order_.push_front(tag);
        map_[tag] = order_.begin();
        return false;
    }

private:
    int64_t capacity_;
    std::list<int64_t> order_;                                    // front == most recently used
    std::unordered_map<int64_t, std::list<int64_t>::iterator> map_;
};

// Mirrors policy.py's _UnimplementedPolicy: fail fast and loud rather
// than silently falling back to lru for a policy name that isn't real yet.
inline void require_policy_implemented(const std::string &name) {
    if (name != "lru") {
        throw std::runtime_error("cachesim: policy '" + name +
                                  "' is declared in config.POLICIES for completeness but not yet implemented");
    }
}

} // namespace cachesim
