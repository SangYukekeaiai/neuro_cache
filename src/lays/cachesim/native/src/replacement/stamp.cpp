#include "cachesim/replacement/stamp.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace {

constexpr std::int64_t kNeverStamped = 0;

[[noreturn]] void reject(const char* who, const std::string& what) {
    throw std::invalid_argument(std::string(who) + ": " + what);
}

}  // namespace

StampPolicy::StampPolicy(std::int32_t num_slots) : next_stamp_(kNeverStamped + 1) {
    if (num_slots < 1) {
        reject("StampPolicy", "num_slots must be >= 1, got " + std::to_string(num_slots));
    }
    stamp_.assign(static_cast<std::size_t>(num_slots), kNeverStamped);
}

std::size_t StampPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= stamp_.size()) {
        throw std::out_of_range("StampPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(stamp_.size()) + ")");
    }
    return static_cast<std::size_t>(s);
}

void StampPolicy::stamp(SlotId slot) {
    stamp_[index_or_reject("stamp", slot)] = next_stamp_;
    ++next_stamp_;
}

void StampPolicy::on_fill(SlotId slot) { stamp(slot); }

void StampPolicy::on_invalidate(SlotId slot) {
    stamp_[index_or_reject("on_invalidate", slot)] = kNeverStamped;
}

SlotId StampPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) reject("StampPolicy::pick_victim", "the candidate set is empty");

    SlotId       victim = candidates.front().slot;
    std::int64_t oldest = stamp_[index_or_reject("pick_victim", victim)];
    for (std::size_t i = 1; i < candidates.size(); ++i) {
        const SlotId       slot = candidates[i].slot;
        const std::int64_t age  = stamp_[index_or_reject("pick_victim", slot)];
        if (age < oldest || (age == oldest && slot < victim)) {
            oldest = age;
            victim = slot;
        }
    }
    return victim;
}

void LruPolicy::on_hit(SlotId slot) { stamp(slot); }

void FifoPolicy::on_hit(SlotId) {}

}  // namespace cachesim
