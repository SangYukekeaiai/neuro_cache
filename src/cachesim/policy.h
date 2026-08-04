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

// The lines one tick has pinned, tag -> that line's recency stamp from
// before this tick's touches. hierarchy.h builds one of these per tick
// out of the L2 lookups that hit, and access_pinned consults it: a
// pinned line is not evicted by this tick's own fills, and the stamps
// only break the overflow case where every resident line of the set is
// pinned. Empty means "nothing pinned", which is exactly plain LRU.
using PinStamps = std::unordered_map<int64_t, int64_t>;

// One cache SET's resident lines, `capacity` many, LRU eviction --
// same scope as policy.py's LRUPolicy: one set, not the whole cache.
// cache.h composes num_sets of these together, same as cache.py does.
class LRUPolicy {
public:
    explicit LRUPolicy(int64_t capacity) : capacity_(capacity) {
        if (capacity <= 0) throw std::runtime_error("LRUPolicy: capacity must be positive");
        map_.reserve(size_t(capacity) * 2);
    }

    bool access(int64_t tag) { return insert_or_touch(tag, nullptr); }

    // access() with this tick's pin set honored on eviction. Identical to
    // access() whenever `pins` is empty, which is what lets the two-level
    // engine reproduce its pre-pinning results exactly.
    bool access_pinned(int64_t tag, const PinStamps &pins) { return insert_or_touch(tag, &pins); }

    // Residency only: no recency move, no insert on a miss. hierarchy.h
    // resolves every core's L2 lookup within one tick against the set as
    // it stood when the tick began, so it has to be able to ask "is this
    // line resident?" without access()'s two side effects, either of
    // which would let one core's same-tick lookup change what the next
    // core sees. Additive: no existing caller's behavior changes.
    bool contains(int64_t tag) const { return map_.find(tag) != map_.end(); }

    // When `tag` was last accessed, on this set's own monotonic counter.
    // Recency order IS stamp order, so the smallest stamp is the LRU end;
    // hierarchy.h reads a stamp while L2 still holds its start-of-tick
    // state and hands it back as a pin, which is how "closest to LRU
    // before this tick's touches" survives the touches that follow.
    // Stamps are per set, and are only ever compared between lines of one
    // set, so the per-instance counter is enough. Reading the position out
    // of order_ instead would be a walk of the whole set on every L2 hit.
    int64_t stamp(int64_t tag) const {
        auto it = map_.find(tag);
        if (it == map_.end()) throw std::runtime_error("LRUPolicy::stamp: tag is not resident");
        return it->second.stamp;
    }

private:
    struct Entry {
        std::list<int64_t>::iterator pos;
        int64_t stamp;
    };

    bool insert_or_touch(int64_t tag, const PinStamps *pins) {
        auto it = map_.find(tag);
        if (it != map_.end()) {
            order_.erase(it->second.pos);
            order_.push_front(tag);
            it->second.pos = order_.begin();
            it->second.stamp = ++clock_;
            return true;
        }
        if (int64_t(order_.size()) >= capacity_) {
            auto victim = choose_victim(pins);
            map_.erase(*victim);
            order_.erase(victim);
        }
        order_.push_front(tag);
        map_[tag] = Entry{order_.begin(), ++clock_};
        return false;
    }

    // Plain LRU takes the back of order_. With a non-empty pin set the
    // rule becomes: the LRU-most line that is NOT pinned, walking from the
    // LRU end towards MRU. If the walk runs out, every resident line of
    // this set was read this tick and protection has to give way to
    // something: the plan's overflow fallback sacrifices the pinned line
    // that was closest to LRU BEFORE this tick's touches, which is the
    // smallest pinned stamp. Not the current LRU end, which this tick's
    // own hit-touches have already reshuffled.
    //
    // Both loops are bounded by the pin count, not by the number of ways:
    // the walk stops at the first unpinned line, and the fallback is only
    // reached when every resident line is pinned.
    std::list<int64_t>::iterator choose_victim(const PinStamps *pins) {
        if (pins == nullptr || pins->empty()) return std::prev(order_.end());
        auto fallback = order_.end();
        int64_t fallback_stamp = 0;
        for (auto it = order_.end(); it != order_.begin();) {
            --it;
            auto pin = pins->find(*it);
            if (pin == pins->end()) return it;
            if (fallback == order_.end() || pin->second < fallback_stamp) {
                fallback = it;
                fallback_stamp = pin->second;
            }
        }
        return fallback; // never end(): a full set has at least one line
    }

    int64_t capacity_;
    int64_t clock_ = 0;
    std::list<int64_t> order_;                       // front == most recently used
    std::unordered_map<int64_t, Entry> map_;
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
